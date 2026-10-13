//! Query compilation and validation for the lexical executor (PR 7, D07-01/D07-02).
//!
//! Compilation is split from execution so the entire tree is validated and field
//! ids/analyzed terms are resolved **before** any segment is opened. Unsupported
//! operators fail closed with a typed error and never skip a subtree.

use std::collections::{BTreeMap, BTreeSet};

use crate::analysis::{
    AnalysisLimits, AnalyzerRegistry, AnalyzerRole, Cancellation, SchemaAnalyzerBindings,
};
use crate::contract::query::Query;
use crate::contract::schema::Schema;
use crate::contract::value::{FieldType, FieldValue};
use crate::segment::CodecSchema;

use super::error::{SearchError, SearchResult};
use super::limits::SearchLimits;

/// One analyzed phrase component with its absolute query position.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct PhraseToken {
    pub(crate) term: String,
    pub(crate) position: u64,
    pub(crate) position_length: u64,
}

/// A compiled scoring leaf.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CompiledLeaf {
    /// A term query: the union of one or more analyzed terms on one field.
    Term { field_id: u32, terms: Vec<String> },
    /// A positional phrase query on one field.
    Phrase {
        field_id: u32,
        tokens: Vec<PhraseToken>,
    },
}

impl CompiledLeaf {
    /// Distinct `(field, term)` scoring identities contributed by this leaf.
    pub(crate) fn scoring_terms(&self) -> Vec<(u32, String)> {
        match self {
            Self::Term { field_id, terms } => {
                let mut set: BTreeSet<&str> = BTreeSet::new();
                for term in terms {
                    set.insert(term.as_str());
                }
                set.into_iter()
                    .map(|term| (*field_id, term.to_owned()))
                    .collect()
            }
            Self::Phrase { field_id, tokens } => {
                let mut set: BTreeSet<&str> = BTreeSet::new();
                for token in tokens {
                    set.insert(token.term.as_str());
                }
                set.into_iter()
                    .map(|term| (*field_id, term.to_owned()))
                    .collect()
            }
        }
    }
}

/// A compiled query node referencing leaves by index.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CompiledNode {
    MatchAll,
    Leaf(usize),
    And(Vec<CompiledNode>),
    Or(Vec<CompiledNode>),
    Not(Box<CompiledNode>),
}

/// A fully validated and compiled query.
#[derive(Debug, Clone)]
pub(crate) struct CompiledQuery {
    pub(crate) root: CompiledNode,
    pub(crate) leaves: Vec<CompiledLeaf>,
    /// Distinct field ids that require BM25 statistics.
    pub(crate) scoring_field_ids: Vec<u32>,
    /// The canonical codec schema every searched segment must match.
    pub(crate) codec: CodecSchema,
}

/// Compiles a validated query against the caller-supplied schema and analyzer
/// registry.
///
/// The caller must have already run [`Query::validate`]; this function
/// additionally rejects operators that are valid contract shapes but not
/// executable in PR 7, and resolves field ids and analyzed terms fail-closed.
pub(crate) fn compile(
    query: &Query,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    search_limits: &SearchLimits,
    analysis_limits: &AnalysisLimits,
    cancel: &dyn Cancellation,
) -> SearchResult<CompiledQuery> {
    let bindings = SchemaAnalyzerBindings::resolve(schema, registry)?;
    let codec = CodecSchema::from_contract(schema, &bindings)?;
    let mut compiler = Compiler {
        schema,
        registry,
        codec,
        bindings,
        search_limits,
        analysis_limits,
        cancel,
        leaves: Vec::new(),
        leaf_index: BTreeMap::new(),
        nodes: 0,
        scoring_terms: BTreeSet::new(),
    };
    let root = compiler.compile_node(query)?;
    let mut scoring_field_ids: Vec<u32> = compiler
        .scoring_terms
        .iter()
        .map(|(field_id, _)| *field_id)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    scoring_field_ids.sort_unstable();
    Ok(CompiledQuery {
        root,
        leaves: compiler.leaves,
        scoring_field_ids,
        codec: compiler.codec,
    })
}

struct Compiler<'a> {
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
    codec: CodecSchema,
    bindings: SchemaAnalyzerBindings,
    search_limits: &'a SearchLimits,
    analysis_limits: &'a AnalysisLimits,
    cancel: &'a dyn Cancellation,
    leaves: Vec<CompiledLeaf>,
    /// Canonical leaf identity to leaf index, for duplicate-clause deduplication.
    leaf_index: BTreeMap<LeafKey, usize>,
    nodes: u64,
    scoring_terms: BTreeSet<(u32, String)>,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
enum LeafKey {
    Term {
        field_id: u32,
        terms: Vec<String>,
    },
    Phrase {
        field_id: u32,
        tokens: Vec<(String, u64, u64)>,
    },
}

impl Compiler<'_> {
    fn charge_node(&mut self) -> SearchResult<()> {
        self.nodes = self
            .nodes
            .checked_add(1)
            .ok_or(SearchError::ResourceLimit {
                limit: self.search_limits.max_compiled_nodes(),
                requested: u64::MAX,
            })?;
        if self.nodes > self.search_limits.max_compiled_nodes() {
            return Err(SearchError::ResourceLimit {
                limit: self.search_limits.max_compiled_nodes(),
                requested: self.nodes,
            });
        }
        self.check_cancelled()?;
        Ok(())
    }

    fn check_cancelled(&self) -> SearchResult<()> {
        if self.cancel.is_cancelled() {
            Err(SearchError::Cancelled)
        } else {
            Ok(())
        }
    }

    fn compile_node(&mut self, query: &Query) -> SearchResult<CompiledNode> {
        self.charge_node()?;
        match query {
            Query::MatchAll => Ok(CompiledNode::MatchAll),
            Query::Term { field, value } => {
                let leaf = self.compile_term(field, value)?;
                self.intern_leaf(leaf)
            }
            Query::Phrase { field, terms } => {
                let leaf = self.compile_phrase(field, terms)?;
                self.intern_leaf(leaf)
            }
            Query::And(children) => {
                let mut compiled = Vec::new();
                compiled.try_reserve_exact(children.len()).map_err(|_| {
                    SearchError::ResourceLimit {
                        limit: self.search_limits.max_compiled_nodes(),
                        requested: children.len() as u64,
                    }
                })?;
                for child in children {
                    compiled.push(self.compile_node(child)?);
                }
                Ok(CompiledNode::And(compiled))
            }
            Query::Or(children) => {
                let mut compiled = Vec::new();
                compiled.try_reserve_exact(children.len()).map_err(|_| {
                    SearchError::ResourceLimit {
                        limit: self.search_limits.max_compiled_nodes(),
                        requested: children.len() as u64,
                    }
                })?;
                for child in children {
                    compiled.push(self.compile_node(child)?);
                }
                Ok(CompiledNode::Or(compiled))
            }
            Query::Not(inner) => Ok(CompiledNode::Not(Box::new(self.compile_node(inner)?))),
            Query::Prefix { .. } => unsupported("prefix"),
            Query::Glob { .. } => unsupported("glob"),
            Query::Regex { .. } => unsupported("regex"),
            Query::Range { .. } => unsupported("range"),
            Query::TimeRange { .. } => unsupported("time_range"),
            Query::Exists { .. } => unsupported("exists"),
            Query::Missing { .. } => unsupported("missing"),
            Query::IsNull { .. } => unsupported("is_null"),
            Query::In { .. } => unsupported("in"),
            Query::NotIn { .. } => unsupported("not_in"),
            Query::IpExact { .. } => unsupported("ip_exact"),
            Query::IpRange { .. } => unsupported("ip_range"),
            Query::IpInCidr { .. } => unsupported("ip_in_cidr"),
            Query::IpNotInCidr { .. } => unsupported("ip_not_in_cidr"),
            Query::JsonPathEquals { .. } => unsupported("jsonpath_equals"),
            Query::JsonPathExists { .. } => unsupported("jsonpath_exists"),
            Query::GeoBoundingBox { .. } => unsupported("geo_bounding_box"),
            Query::GeoRadius { .. } => unsupported("geo_radius"),
            Query::GeoPolygon { .. } => unsupported("geo_polygon"),
        }
    }

    fn intern_leaf(&mut self, leaf: CompiledLeaf) -> SearchResult<CompiledNode> {
        let key = match &leaf {
            CompiledLeaf::Term { field_id, terms } => LeafKey::Term {
                field_id: *field_id,
                terms: terms.clone(),
            },
            CompiledLeaf::Phrase { field_id, tokens } => LeafKey::Phrase {
                field_id: *field_id,
                tokens: tokens
                    .iter()
                    .map(|token| (token.term.clone(), token.position, token.position_length))
                    .collect(),
            },
        };
        if let Some(index) = self.leaf_index.get(&key) {
            return Ok(CompiledNode::Leaf(*index));
        }
        for (field_id, term) in leaf.scoring_terms() {
            if self.scoring_terms.contains(&(field_id, term.clone())) {
                continue;
            }
            if self.scoring_terms.len() as u64 + 1 > self.search_limits.max_unique_query_terms() {
                return Err(SearchError::ResourceLimit {
                    limit: self.search_limits.max_unique_query_terms(),
                    requested: self.scoring_terms.len() as u64 + 1,
                });
            }
            self.scoring_terms.insert((field_id, term));
        }
        let index = self.leaves.len();
        self.leaves.push(leaf);
        self.leaf_index.insert(key, index);
        Ok(CompiledNode::Leaf(index))
    }

    fn compile_term(&mut self, field: &str, value: &FieldValue) -> SearchResult<CompiledLeaf> {
        let definition = self
            .schema
            .get(field)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "query validated against a field missing from the supplied schema"
                    .to_owned(),
            })?;
        if !definition.options.indexed {
            return Err(SearchError::UnsupportedOperator {
                operator: "term_on_unindexed_field",
            });
        }
        let field_id = self.field_id(field)?;
        let terms = match definition.field_type {
            FieldType::Text => {
                let Some(text) = as_text(value) else {
                    return Err(SearchError::UnsupportedOperator {
                        operator: "term_type_mismatch",
                    });
                };
                self.analyze_text_search(field, text)?
            }
            FieldType::Keyword => {
                let Some(text) = as_keyword(value) else {
                    return Err(SearchError::UnsupportedOperator {
                        operator: "term_type_mismatch",
                    });
                };
                self.analyze_keyword_search(field, text)?
            }
            _ => {
                return Err(SearchError::UnsupportedOperator {
                    operator: "term_on_non_lexical_field",
                });
            }
        };
        Ok(CompiledLeaf::Term { field_id, terms })
    }

    fn compile_phrase(&mut self, field: &str, components: &[String]) -> SearchResult<CompiledLeaf> {
        let definition = self
            .schema
            .get(field)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "query validated against a field missing from the supplied schema"
                    .to_owned(),
            })?;
        if !definition.options.indexed {
            return Err(SearchError::UnsupportedOperator {
                operator: "phrase_on_unindexed_field",
            });
        }
        if definition.field_type != FieldType::Text {
            return Err(SearchError::UnsupportedOperator {
                operator: "phrase_on_non_text_field",
            });
        }
        let field_id = self.field_id(field)?;
        // Concatenate the ordered lexical components with a single tokenization
        // boundary and analyze the joined text once. This preserves the analyzer's
        // positional semantics (including stopword holes and position lengths)
        // instead of fabricating cross-component adjacency.
        let joined = components.join(" ");
        let tokens = self.analyze_phrase(field, &joined)?;
        Ok(CompiledLeaf::Phrase { field_id, tokens })
    }

    fn field_id(&self, field: &str) -> SearchResult<u32> {
        self.codec
            .field_id(field)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: format!("field {field} is absent from the canonical codec schema"),
            })
    }

    fn search_definition(
        &self,
        field: &str,
    ) -> SearchResult<Option<&crate::analysis::AnalyzerDefinition>> {
        let Some(binding) = self.bindings.get(field) else {
            return Ok(None);
        };
        let Some(search) = &binding.search else {
            return Ok(None);
        };
        Ok(Some(self.registry.resolve_fingerprint(
            &search.id,
            &search.version,
            search.fingerprint,
        )?))
    }

    fn analyze_text_search(&self, field: &str, text: &str) -> SearchResult<Vec<String>> {
        let Some(definition) = self.search_definition(field)? else {
            return self.exact_terms(text);
        };
        let tokens = definition.collect_tokens(
            AnalyzerRole::Search,
            &[text],
            self.analysis_limits,
            self.cancel,
        )?;
        let mut set = BTreeSet::new();
        for token in &tokens {
            set.insert(token.term().to_owned());
        }
        Ok(set.into_iter().collect())
    }

    fn analyze_keyword_search(&self, field: &str, text: &str) -> SearchResult<Vec<String>> {
        let Some(definition) = self.search_definition(field)? else {
            return self.exact_terms(text);
        };
        let tokens = definition.collect_tokens(
            AnalyzerRole::Search,
            &[text],
            self.analysis_limits,
            self.cancel,
        )?;
        match tokens.as_slice() {
            [] => Ok(Vec::new()),
            [token] => Ok(vec![token.term().to_owned()]),
            // The keyword tokenizer must emit exactly one token per value; more is
            // an analyzer-contract violation, not an approximation.
            many => Err(SearchError::UnsupportedOperator {
                operator: if many.is_empty() {
                    "keyword_empty"
                } else {
                    "keyword_multiple_terms"
                },
            }),
        }
    }

    fn analyze_phrase(&self, field: &str, text: &str) -> SearchResult<Vec<PhraseToken>> {
        let Some(definition) = self.search_definition(field)? else {
            let terms = self.exact_terms(text)?;
            return Ok(terms
                .into_iter()
                .enumerate()
                .map(|(index, term)| PhraseToken {
                    term,
                    position: index as u64,
                    position_length: 1,
                })
                .collect());
        };
        let tokens = definition.collect_tokens(
            AnalyzerRole::Search,
            &[text],
            self.analysis_limits,
            self.cancel,
        )?;
        Ok(tokens
            .iter()
            .map(|token| PhraseToken {
                term: token.term().to_owned(),
                position: u64::from(token.position()),
                position_length: u64::from(token.position_length()),
            })
            .collect())
    }

    /// Mirrors the index-time exact-term fallback used when a Text/Keyword field
    /// has no configured analyzer/normalizer.
    fn exact_terms(&self, text: &str) -> SearchResult<Vec<String>> {
        if text.is_empty() {
            return Ok(Vec::new());
        }
        let bytes = u64::try_from(text.len()).unwrap_or(u64::MAX);
        if bytes > self.analysis_limits.max_term_bytes() {
            return Err(SearchError::ResourceLimit {
                limit: self.analysis_limits.max_term_bytes(),
                requested: bytes,
            });
        }
        if bytes > self.analysis_limits.max_input_bytes() {
            return Err(SearchError::ResourceLimit {
                limit: self.analysis_limits.max_input_bytes(),
                requested: bytes,
            });
        }
        Ok(vec![text.to_owned()])
    }
}

fn unsupported<T>(operator: &'static str) -> SearchResult<T> {
    Err(SearchError::UnsupportedOperator { operator })
}

fn as_text(value: &FieldValue) -> Option<&str> {
    match value {
        FieldValue::Text(text) => Some(text),
        _ => None,
    }
}

fn as_keyword(value: &FieldValue) -> Option<&str> {
    match value {
        FieldValue::Keyword(text) => Some(text),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, NeverCancel};
    use crate::contract::document::Cardinality;
    use crate::contract::error::QueryError;
    use crate::contract::schema::{FieldDefinition, FieldOptions};

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "body",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("english"),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::indexed_stored(),
                )
                .with_normalizer("keyword"),
                FieldDefinition::new(
                    "n",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            None,
        )
        .unwrap()
    }

    fn compile_query(query: &Query) -> SearchResult<CompiledQuery> {
        let registry = AnalyzerRegistry::builtin();
        let schema = schema();
        let limits = SearchLimits::default();
        let analysis = AnalysisLimits::default();
        query.validate(&schema, &crate::contract::budget::Budgets::new())?;
        compile(query, &schema, &registry, &limits, &analysis, &NeverCancel)
    }

    #[test]
    fn term_analyzes_text_and_keyword() {
        let query = Query::Term {
            field: "body".into(),
            value: FieldValue::Text("Running".into()),
        };
        let compiled = compile_query(&query).unwrap();
        match &compiled.leaves[0] {
            CompiledLeaf::Term { terms, .. } => assert_eq!(terms, &vec!["run".to_owned()]),
            other => panic!("unexpected {other:?}"),
        }
        let keyword = Query::Term {
            field: "tag".into(),
            value: FieldValue::Keyword("Café".into()),
        };
        let compiled = compile_query(&keyword).unwrap();
        match &compiled.leaves[0] {
            CompiledLeaf::Term { terms, .. } => assert_eq!(terms.len(), 1),
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn unsupported_operators_fail_closed() {
        for query in [
            Query::Prefix {
                field: "tag".into(),
                prefix: "a".into(),
            },
            Query::Glob {
                field: "tag".into(),
                pattern: "*".into(),
            },
            Query::Regex {
                field: "body".into(),
                pattern: "a.*".into(),
            },
            Query::Exists {
                field: "tag".into(),
            },
            Query::Term {
                field: "n".into(),
                value: FieldValue::I64(1),
            },
        ] {
            assert!(matches!(
                compile_query(&query),
                Err(SearchError::UnsupportedOperator { .. })
            ));
        }
    }

    #[test]
    fn duplicate_clauses_share_a_leaf() {
        let query = Query::And(vec![
            Query::Term {
                field: "body".into(),
                value: FieldValue::Text("run".into()),
            },
            Query::Term {
                field: "body".into(),
                value: FieldValue::Text("run".into()),
            },
        ]);
        let compiled = compile_query(&query).unwrap();
        assert_eq!(compiled.leaves.len(), 1);
        assert!(compiled.scoring_field_ids.contains(&0));
    }

    #[test]
    fn phrase_uses_search_positions() {
        let query = Query::Phrase {
            field: "body".into(),
            terms: vec!["quick".into(), "the".into(), "fox".into()],
        };
        let compiled = compile_query(&query).unwrap();
        match &compiled.leaves[0] {
            CompiledLeaf::Phrase { tokens, .. } => {
                assert_eq!(tokens.len(), 2);
                assert_eq!(tokens[0].term, "quick");
                assert_eq!(tokens[0].position, 0);
                assert_eq!(tokens[1].term, "fox");
                assert_eq!(tokens[1].position, 2);
            }
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn phrase_on_keyword_is_unsupported() {
        let query = Query::Phrase {
            field: "tag".into(),
            terms: vec!["a".into()],
        };
        assert!(matches!(
            compile_query(&query),
            Err(SearchError::UnsupportedOperator { .. })
        ));
    }

    #[test]
    fn unindexed_field_is_unsupported() {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "raw",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::new(false, true, false),
            )],
            None,
        )
        .unwrap();
        let registry = AnalyzerRegistry::builtin();
        let query = Query::Term {
            field: "raw".into(),
            value: FieldValue::Text("x".into()),
        };
        query
            .validate(&schema, &crate::contract::budget::Budgets::new())
            .unwrap();
        assert!(matches!(
            compile(
                &query,
                &schema,
                &registry,
                &SearchLimits::default(),
                &AnalysisLimits::default(),
                &NeverCancel
            ),
            Err(SearchError::UnsupportedOperator { .. })
        ));
    }

    #[test]
    fn node_budget_is_enforced() {
        let registry = AnalyzerRegistry::builtin();
        let schema = schema();
        let limits = SearchLimits::default().with_max_compiled_nodes(1).unwrap();
        let query = Query::And(vec![Query::MatchAll, Query::MatchAll]);
        let error = compile(
            &query,
            &schema,
            &registry,
            &limits,
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
    }

    #[test]
    fn duplicate_term_budget_is_enforced() {
        let registry = AnalyzerRegistry::builtin();
        let schema = schema();
        let limits = SearchLimits::default()
            .with_max_unique_query_terms(1)
            .unwrap();
        let query = Query::Or(vec![
            Query::Term {
                field: "body".into(),
                value: FieldValue::Text("alpha".into()),
            },
            Query::Term {
                field: "body".into(),
                value: FieldValue::Text("beta".into()),
            },
        ]);
        // The second distinct term over budget is rejected during compilation.
        let error = compile(
            &query,
            &schema,
            &registry,
            &limits,
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .unwrap_err();
        assert!(matches!(error, SearchError::ResourceLimit { .. }));
    }

    #[test]
    fn query_error_maps_to_search_error() {
        let err: SearchError = QueryError::ExpiredCursor.into();
        assert!(matches!(err, SearchError::Query(_)));
    }

    #[test]
    fn every_unsupported_operator_fails_closed() {
        use crate::contract::query::{Bound, GeoBoundingBox, GeoPolygon, GeoRadius, JsonPathExpr};
        use crate::contract::value::{GeoPoint, IpNetwork, Timestamp};

        let field = "body".to_owned();
        let polygon = GeoPolygon::new(
            vec![
                GeoPoint::new(0.0, 0.0).unwrap(),
                GeoPoint::new(1.0, 0.0).unwrap(),
                GeoPoint::new(1.0, 1.0).unwrap(),
            ],
            vec![],
        )
        .unwrap();
        let queries = vec![
            Query::Prefix {
                field: field.clone(),
                prefix: "a".into(),
            },
            Query::Glob {
                field: field.clone(),
                pattern: "*a".into(),
            },
            Query::Regex {
                field: field.clone(),
                pattern: "a.*".into(),
            },
            Query::Range {
                field: field.clone(),
                lower: Bound::Included(FieldValue::I64(0)),
                upper: Bound::Excluded(FieldValue::I64(1)),
            },
            Query::TimeRange {
                field: field.clone(),
                start: Timestamp::from_micros(0),
                end: Timestamp::from_micros(1),
            },
            Query::Exists {
                field: field.clone(),
            },
            Query::Missing {
                field: field.clone(),
            },
            Query::IsNull {
                field: field.clone(),
            },
            Query::In {
                field: field.clone(),
                values: vec![FieldValue::Text("a".into())],
            },
            Query::NotIn {
                field: field.clone(),
                values: vec![FieldValue::Text("a".into())],
            },
            Query::IpExact {
                field: field.clone(),
                addr: "10.0.0.1".parse().unwrap(),
            },
            Query::IpRange {
                field: field.clone(),
                start: "10.0.0.1".parse().unwrap(),
                end: "10.0.0.2".parse().unwrap(),
            },
            Query::IpInCidr {
                field: field.clone(),
                network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
            },
            Query::IpNotInCidr {
                field: field.clone(),
                network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
            },
            Query::JsonPathEquals {
                field: field.clone(),
                path: JsonPathExpr::parse("$.a").unwrap(),
                value: FieldValue::Text("a".into()),
            },
            Query::JsonPathExists {
                field: field.clone(),
                path: JsonPathExpr::parse("$.a").unwrap(),
            },
            Query::GeoBoundingBox {
                field: field.clone(),
                bbox: GeoBoundingBox::new(0.0, 0.0, 1.0, 1.0).unwrap(),
            },
            Query::GeoRadius {
                field: field.clone(),
                radius: GeoRadius::new(GeoPoint::new(0.0, 0.0).unwrap(), 10.0).unwrap(),
            },
            Query::GeoPolygon {
                field: field.clone(),
                polygon,
            },
        ];
        let registry = AnalyzerRegistry::builtin();
        let schema = schema();
        for query in queries {
            let error = compile(
                &query,
                &schema,
                &registry,
                &SearchLimits::default(),
                &AnalysisLimits::default(),
                &NeverCancel,
            )
            .unwrap_err();
            assert!(
                matches!(error, SearchError::UnsupportedOperator { .. }),
                "unexpected error for {query:?}: {error:?}"
            );
        }
    }
}
