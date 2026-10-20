//! Query compilation and validation for the lexical executor (PR 7, D07-01/D07-02).
//!
//! Compilation is split from execution so the entire tree is validated and field
//! ids/analyzed terms are resolved **before** any segment is opened. Unsupported
//! operators fail closed with a typed error and never skip a subtree.

use std::collections::{BTreeMap, BTreeSet};

use crate::analysis::{
    AnalysisLimits, AnalyzerDefinition, AnalyzerRegistry, AnalyzerRole, Cancellation,
    SchemaAnalyzerBindings,
};
use crate::contract::query::Query;
use crate::contract::schema::Schema;
use crate::contract::value::{FieldType, FieldValue};
use crate::segment::CodecSchema;

use super::automaton::TermPredicate;
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
    /// A bounded multi-term pattern (prefix/glob/regex/fuzzy) on one field. The
    /// expanded term set is materialized per segment after readers are opened by
    /// [`crate::search::expand`], never during compilation.
    MultiTerm {
        field_id: u32,
        predicate: TermPredicate,
    },
}

impl CompiledLeaf {
    /// Distinct `(field, term)` scoring identities contributed by this leaf.
    ///
    /// `MultiTerm` leaves contribute no ordinary terms; their expanded terms are
    /// added to the query-wide scoring union during execution.
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
            Self::MultiTerm { .. } => Vec::new(),
        }
    }

    /// Field ids this leaf can contribute BM25 statistics for.
    pub(crate) fn scoring_fields(&self) -> Vec<u32> {
        match self {
            Self::Term { .. } | Self::Phrase { .. } => {
                self.scoring_terms().into_iter().map(|(f, _)| f).collect()
            }
            Self::MultiTerm { field_id, .. } => vec![*field_id],
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

/// Collect leaf indices reached through an **even** number of `Not` nodes.
///
/// A leaf is scoring-eligible if at least one such positive occurrence exists
/// anywhere in the tree. This is a query-level lexical contribution policy, not a
/// branch-provenance policy: an eligible leaf scores whenever the document matches
/// the overall Boolean query and the leaf itself, even if another `Or` branch alone
/// was sufficient for membership. The same leaf reached through both polarities
/// remains eligible exactly once; a leaf reached only through odd/negative
/// polarity is excluded entirely.
fn collect_positive_leaves(node: &CompiledNode, negated: bool, positive: &mut BTreeSet<usize>) {
    match node {
        CompiledNode::MatchAll => {}
        CompiledNode::Leaf(index) => {
            if !negated {
                positive.insert(*index);
            }
        }
        CompiledNode::And(children) | CompiledNode::Or(children) => {
            for child in children {
                collect_positive_leaves(child, negated, positive);
            }
        }
        CompiledNode::Not(child) => collect_positive_leaves(child, !negated, positive),
    }
}

/// A fully validated and compiled query.
#[derive(Debug, Clone)]
pub(crate) struct CompiledQuery {
    pub(crate) root: CompiledNode,
    pub(crate) leaves: Vec<CompiledLeaf>,
    /// Interned leaf indices eligible to contribute BM25 (even `Not` parity).
    pub(crate) positive_leaf_indices: BTreeSet<usize>,
    /// Distinct field ids, from eligible leaves only, that require BM25 statistics.
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
        automaton_states: 0,
    };
    let root = compiler.compile_node(query)?;
    let mut positive_leaf_indices = BTreeSet::new();
    collect_positive_leaves(&root, false, &mut positive_leaf_indices);
    for index in &positive_leaf_indices {
        if *index >= compiler.leaves.len() {
            return Err(SearchError::CorruptIndex {
                detail: "compiled leaf index is out of range".to_owned(),
            });
        }
    }
    let mut scoring_field_ids: Vec<u32> = positive_leaf_indices
        .iter()
        .flat_map(|index| compiler.leaves[*index].scoring_fields())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    scoring_field_ids.sort_unstable();
    Ok(CompiledQuery {
        root,
        leaves: compiler.leaves,
        positive_leaf_indices,
        scoring_field_ids,
        codec: compiler.codec,
    })
}

/// Compile exactly one lexical leaf query (Term/Phrase/Prefix/Glob/Regex/Fuzzy)
/// with a caller-supplied codec/bindings pair.
///
/// The unified compiler resolves bindings and the codec once and reuses them for
/// every leaf; this preserves the PR 7 analyzer/automaton pipeline without a
/// second compiler. A non-leaf query is a caller bug and fails closed.
#[allow(clippy::too_many_arguments)]
pub(crate) fn compile_lexical_leaf(
    query: &Query,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    codec: CodecSchema,
    bindings: SchemaAnalyzerBindings,
    search_limits: &SearchLimits,
    analysis_limits: &AnalysisLimits,
    cancel: &dyn Cancellation,
) -> SearchResult<CompiledLeaf> {
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
        automaton_states: 0,
    };
    let node = compiler.compile_node(query)?;
    match node {
        CompiledNode::Leaf(index) => {
            compiler
                .leaves
                .into_iter()
                .nth(index)
                .ok_or_else(|| SearchError::CorruptIndex {
                    detail: "lexical leaf index is out of range".to_owned(),
                })
        }
        _ => Err(SearchError::CorruptIndex {
            detail: "expected a single lexical leaf".to_owned(),
        }),
    }
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
    /// Query-wide sum of compiled automaton states across new multi-term leaves.
    automaton_states: u64,
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
    /// Canonical multi-term identity: kind, normalized pattern and fuzzy params.
    MultiTerm {
        field_id: u32,
        key: String,
    },
}

/// A pattern leaf still to be prepared and compiled into a [`TermPredicate`].
enum QueryPattern<'a> {
    Prefix {
        field: &'a str,
        value: &'a str,
    },
    Glob {
        field: &'a str,
        value: &'a str,
    },
    Regex {
        field: &'a str,
        value: &'a str,
    },
    Fuzzy {
        field: &'a str,
        value: &'a str,
        max_edits: u8,
        transpositions: bool,
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
            Query::Prefix { field, prefix } => self.compile_pattern(QueryPattern::Prefix {
                field,
                value: prefix,
            }),
            Query::Glob { field, pattern } => self.compile_pattern(QueryPattern::Glob {
                field,
                value: pattern,
            }),
            Query::Regex { field, pattern } => self.compile_pattern(QueryPattern::Regex {
                field,
                value: pattern,
            }),
            Query::Fuzzy {
                field,
                value,
                max_edits,
                transpositions,
            } => self.compile_pattern(QueryPattern::Fuzzy {
                field,
                value,
                max_edits: *max_edits,
                transpositions: *transpositions,
            }),
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
            Query::JsonPathRange { .. } => unsupported("jsonpath_range"),
            Query::JsonPathArrayContains { .. } => unsupported("jsonpath_array_contains"),
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
            CompiledLeaf::MultiTerm {
                field_id,
                predicate,
            } => LeafKey::MultiTerm {
                field_id: *field_id,
                key: predicate.intern_key(),
            },
        };
        if let Some(index) = self.leaf_index.get(&key) {
            return Ok(CompiledNode::Leaf(*index));
        }
        if let CompiledLeaf::MultiTerm { predicate, .. } = &leaf {
            let states = predicate.compiled_states();
            self.automaton_states =
                self.automaton_states
                    .checked_add(states)
                    .ok_or(SearchError::ResourceLimit {
                        limit: self.search_limits.max_automaton_states(),
                        requested: u64::MAX,
                    })?;
            if self.automaton_states > self.search_limits.max_automaton_states() {
                return Err(SearchError::ResourceLimit {
                    limit: self.search_limits.max_automaton_states(),
                    requested: self.automaton_states,
                });
            }
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

    fn compile_pattern(&mut self, pattern: QueryPattern<'_>) -> SearchResult<CompiledNode> {
        let (field, predicate) = match pattern {
            QueryPattern::Prefix { field, value } => {
                let definition = self.lexical_definition(field, "prefix_on_unindexed_field")?;
                let prepared = crate::analysis::prepare_prefix(
                    definition,
                    value,
                    self.analysis_limits,
                    self.cancel,
                )?;
                (field, TermPredicate::prefix(&prepared))
            }
            QueryPattern::Glob { field, value } => {
                let definition = self.lexical_definition(field, "glob_on_unindexed_field")?;
                let prepared = crate::analysis::prepare_glob(
                    definition,
                    value,
                    self.analysis_limits,
                    self.cancel,
                )?;
                (field, TermPredicate::glob(&prepared, self.search_limits)?)
            }
            QueryPattern::Regex { field, value } => {
                let definition = self.lexical_definition(field, "regex_on_unindexed_field")?;
                let prepared = crate::analysis::prepare_regex(
                    definition,
                    value,
                    self.analysis_limits,
                    self.cancel,
                )?;
                (field, TermPredicate::regex(&prepared, self.search_limits)?)
            }
            QueryPattern::Fuzzy {
                field,
                value,
                max_edits,
                transpositions,
            } => {
                let definition = self.lexical_definition(field, "fuzzy_on_unindexed_field")?;
                let prepared = crate::analysis::prepare_term(
                    definition,
                    value,
                    self.analysis_limits,
                    self.cancel,
                )?;
                (
                    field,
                    TermPredicate::fuzzy(
                        prepared.term(),
                        max_edits,
                        transpositions,
                        self.search_limits,
                    )?,
                )
            }
        };
        let field_id = self.field_id(field)?;
        let leaf = CompiledLeaf::MultiTerm {
            field_id,
            predicate,
        };
        self.intern_leaf(leaf)
    }

    /// Resolve an indexed lexical field to its search analyzer, falling back to the
    /// identity (`keyword_noop`) analyzer when the field has none, exactly as the
    /// writer's exact-term fallback does.
    fn lexical_definition(
        &self,
        field: &str,
        unindexed_operator: &'static str,
    ) -> SearchResult<&AnalyzerDefinition> {
        let definition = self
            .schema
            .get(field)
            .ok_or_else(|| SearchError::CorruptIndex {
                detail: "query validated against a field missing from the supplied schema"
                    .to_owned(),
            })?;
        if !definition.options.indexed {
            return Err(SearchError::UnsupportedOperator {
                operator: unindexed_operator,
            });
        }
        if !matches!(definition.field_type, FieldType::Text | FieldType::Keyword) {
            return Err(SearchError::UnsupportedOperator {
                operator: "pattern_on_non_lexical_field",
            });
        }
        match self.search_definition(field)? {
            Some(definition) => Ok(definition),
            None => self.registry.get("keyword_noop").map_err(SearchError::from),
        }
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
    fn multi_term_operators_compile_to_one_leaf() {
        for query in [
            Query::Prefix {
                field: "tag".into(),
                prefix: "a".into(),
            },
            Query::Glob {
                field: "tag".into(),
                pattern: "a*e".into(),
            },
            Query::Regex {
                field: "tag".into(),
                pattern: "[a-z]+".into(),
            },
            Query::Fuzzy {
                field: "tag".into(),
                value: "cafe".into(),
                max_edits: 1,
                transpositions: true,
            },
        ] {
            let compiled = compile_query(&query)
                .unwrap_or_else(|error| panic!("expected {query:?} to compile, got {error:?}"));
            assert_eq!(compiled.leaves.len(), 1, "one leaf for {query:?}");
            assert!(matches!(compiled.leaves[0], CompiledLeaf::MultiTerm { .. }));
        }
    }

    #[test]
    fn duplicate_multi_term_leaves_intern() {
        let query = Query::Or(vec![
            Query::Prefix {
                field: "tag".into(),
                prefix: "ab".into(),
            },
            Query::Prefix {
                field: "tag".into(),
                prefix: "ab".into(),
            },
        ]);
        let compiled = compile_query(&query).unwrap();
        assert_eq!(compiled.leaves.len(), 1);
    }

    #[test]
    fn fuzzy_edits_above_two_are_rejected_by_contract() {
        let query = Query::Fuzzy {
            field: "tag".into(),
            value: "cafe".into(),
            max_edits: 3,
            transpositions: false,
        };
        let error = query
            .validate(&schema(), &crate::contract::budget::Budgets::new())
            .unwrap_err();
        assert!(matches!(
            error,
            QueryError::InvalidQuery(
                crate::contract::error::InvalidQueryReason::UnsupportedOperator { .. }
            )
        ));
    }

    #[test]
    fn fuzzy_requires_a_single_token() {
        let limits = SearchLimits::default();
        let registry = AnalyzerRegistry::builtin();
        let schema = schema();
        let multi = Query::Fuzzy {
            field: "body".into(),
            value: "two words".into(),
            max_edits: 1,
            transpositions: false,
        };
        assert!(matches!(
            compile(
                &multi,
                &schema,
                &registry,
                &limits,
                &AnalysisLimits::default(),
                &NeverCancel
            ),
            Err(SearchError::Analysis(_))
        ));
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
