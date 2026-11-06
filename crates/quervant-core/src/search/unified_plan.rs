//! Compilation of a [`Query`] into a unified lexical/typed predicate tree (PR 14 final design D1).
//!
//! Lexical leaves are compiled with the existing PR 7 analyzer/automaton pipeline
//! ([`super::plan`]); typed leaves are compiled with the existing typed predicate
//! compiler ([`super::typed`]). The original Boolean structure is preserved so
//! `And`/`Or`/`Not` membership matches the AST exactly. `Not` is always evaluated
//! against the effective-live universe, never a physical tombstoned document.
//!
//! No scoring math or typed evaluation is duplicated here: this module only
//! resolves leaves and records their identity.

use std::collections::{BTreeMap, BTreeSet};

use crate::analysis::{AnalysisLimits, AnalyzerRegistry, Cancellation};
use crate::contract::query::Query;
use crate::contract::schema::Schema;
use crate::segment::CodecSchema;

use super::error::SearchResult;
use super::limits::SearchLimits;
use super::plan::{self, CompiledLeaf};
use super::typed;

/// One node of the compiled unified predicate tree.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum UnifiedNode {
    MatchAll,
    /// Index into [`UnifiedPlan::lexical_leaves`].
    Lexical(usize),
    /// Index into [`UnifiedPlan::typed_leaves`].
    Typed(usize),
    And(Vec<UnifiedNode>),
    Or(Vec<UnifiedNode>),
    Not(Box<UnifiedNode>),
}

/// A fully validated unified compilation.
pub(crate) struct UnifiedPlan {
    pub(crate) root: UnifiedNode,
    /// Distinct lexical leaves (equivalent clauses are interned).
    pub(crate) lexical_leaves: Vec<CompiledLeaf>,
    /// Distinct typed leaves, each with its own resolved geo leaves.
    pub(crate) typed_leaves: Vec<typed::Compiled>,
    /// Lexical leaves reachable through an even number of `Not` nodes.
    pub(crate) positive_lexical: BTreeSet<usize>,
    /// Field ids requiring BM25 statistics, from positive lexical leaves only.
    pub(crate) scoring_field_ids: Vec<u32>,
    /// Canonical codec schema for segment compatibility checks.
    pub(crate) codec: CodecSchema,
}

impl UnifiedPlan {
    #[must_use]
    pub(crate) fn has_lexical(&self) -> bool {
        !self.lexical_leaves.is_empty()
    }
}

struct Compiler<'a> {
    schema: &'a Schema,
    registry: &'a AnalyzerRegistry,
    search_limits: &'a SearchLimits,
    analysis_limits: &'a AnalysisLimits,
    cancel: &'a dyn Cancellation,
    codec: CodecSchema,
    bindings: crate::analysis::SchemaAnalyzerBindings,
    typed_plan: typed::TypedPlan,
    lexical_leaves: Vec<CompiledLeaf>,
    lexical_index: BTreeMap<String, usize>,
    typed_leaves: Vec<typed::Compiled>,
    typed_index: BTreeMap<String, usize>,
}

/// Compiles a validated query into a unified predicate tree.
pub(crate) fn compile(
    query: &Query,
    schema: &Schema,
    registry: &AnalyzerRegistry,
    search_limits: &SearchLimits,
    analysis_limits: &AnalysisLimits,
    cancel: &dyn Cancellation,
) -> SearchResult<UnifiedPlan> {
    let bindings = crate::analysis::SchemaAnalyzerBindings::resolve(schema, registry)?;
    let codec = CodecSchema::from_contract(schema, &bindings)?;
    let typed_plan = typed::TypedPlan::build(schema);
    let mut compiler = Compiler {
        schema,
        registry,
        search_limits,
        analysis_limits,
        cancel,
        codec,
        bindings,
        typed_plan,
        lexical_leaves: Vec::new(),
        lexical_index: BTreeMap::new(),
        typed_leaves: Vec::new(),
        typed_index: BTreeMap::new(),
    };
    let root = compiler.compile_node(query)?;
    let mut positive = BTreeSet::new();
    collect_positive(&root, false, &mut positive);
    let scoring_field_ids = positive
        .iter()
        .flat_map(|index| compiler.lexical_leaves[*index].scoring_fields())
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
    Ok(UnifiedPlan {
        root,
        lexical_leaves: compiler.lexical_leaves,
        typed_leaves: compiler.typed_leaves,
        positive_lexical: positive,
        scoring_field_ids,
        codec: compiler.codec,
    })
}

impl Compiler<'_> {
    fn compile_node(&mut self, query: &Query) -> SearchResult<UnifiedNode> {
        match query {
            Query::MatchAll => Ok(UnifiedNode::MatchAll),
            Query::And(children) => {
                let mut nodes = Vec::with_capacity(children.len());
                for child in children {
                    nodes.push(self.compile_node(child)?);
                }
                Ok(UnifiedNode::And(nodes))
            }
            Query::Or(children) => {
                let mut nodes = Vec::with_capacity(children.len());
                for child in children {
                    nodes.push(self.compile_node(child)?);
                }
                Ok(UnifiedNode::Or(nodes))
            }
            Query::Not(inner) => Ok(UnifiedNode::Not(Box::new(self.compile_node(inner)?))),
            Query::Term { .. }
            | Query::Phrase { .. }
            | Query::Prefix { .. }
            | Query::Glob { .. }
            | Query::Regex { .. }
            | Query::Fuzzy { .. } => {
                let leaf = plan::compile_lexical_leaf(
                    query,
                    self.schema,
                    self.registry,
                    self.codec.clone(),
                    self.bindings.clone(),
                    self.search_limits,
                    self.analysis_limits,
                    self.cancel,
                )?;
                Ok(UnifiedNode::Lexical(self.intern_lexical(leaf)))
            }
            _ => {
                let compiled = typed::compile_query(query, &self.typed_plan)?;
                Ok(UnifiedNode::Typed(self.intern_typed(query, compiled)))
            }
        }
    }

    fn intern_lexical(&mut self, leaf: CompiledLeaf) -> usize {
        let key = format!("{leaf:?}");
        if let Some(index) = self.lexical_index.get(&key) {
            return *index;
        }
        let index = self.lexical_leaves.len();
        self.lexical_index.insert(key, index);
        self.lexical_leaves.push(leaf);
        index
    }

    /// Typed leaves are interned by their canonical structural representation, so
    /// equivalent clauses share one evaluation.
    fn intern_typed(&mut self, query: &Query, compiled: typed::Compiled) -> usize {
        let key = format!("{query:?}");
        if let Some(index) = self.typed_index.get(&key) {
            return *index;
        }
        let index = self.typed_leaves.len();
        self.typed_index.insert(key, index);
        self.typed_leaves.push(compiled);
        index
    }
}

fn collect_positive(node: &UnifiedNode, negated: bool, positive: &mut BTreeSet<usize>) {
    match node {
        UnifiedNode::MatchAll | UnifiedNode::Typed(_) => {}
        UnifiedNode::Lexical(index) => {
            if !negated {
                positive.insert(*index);
            }
        }
        UnifiedNode::And(children) | UnifiedNode::Or(children) => {
            for child in children {
                collect_positive(child, negated, positive);
            }
        }
        UnifiedNode::Not(inner) => collect_positive(inner, !negated, positive),
    }
}
