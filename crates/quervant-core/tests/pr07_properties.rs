//! PR 7 seeded property tests (P01–P05) against independent oracles.
//!
//! Each test uses a small deterministic LCG so failures are reproducible from the
//! logged seed. Oracles are computed from the fixture token streams with the
//! standard library, never from the production postings executor.

mod common;

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use quervant_core::analysis::{AnalyzerRegistry, NeverCancel};
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{Cardinality, Document, DocumentKey, FieldValues};
use quervant_core::contract::query::Query;
use quervant_core::contract::result::TopK;
use quervant_core::contract::schema::{FieldDefinition, FieldOptions, Schema};
use quervant_core::contract::value::{FieldType, FieldValue};
use quervant_core::index::{Index, ReaderSnapshot};
use quervant_core::search::{LexicalSearcher, SearchLimits};
use quervant_core::storage::{Directory, MemoryDirectory};

fn prop_schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
            FieldDefinition::new(
                "body",
                FieldType::Text,
                Cardinality::Multi,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("whitespace"),
        ],
        None,
    )
    .expect("prop schema")
}

fn registry() -> AnalyzerRegistry {
    AnalyzerRegistry::builtin()
}

fn build_index(batches: Vec<Vec<Document>>) -> Arc<ReaderSnapshot> {
    let directory: Arc<dyn Directory> = Arc::new(MemoryDirectory::new());
    let index = Index::create(directory.clone(), prop_schema(), registry()).unwrap();
    let mut writer = index.writer().unwrap();
    for batch in &batches {
        for document in batch {
            writer.insert(document.clone()).unwrap();
        }
        writer.flush().unwrap();
    }
    writer.commit().unwrap();
    drop(writer);
    Index::open_existing(directory, prop_schema(), registry())
        .unwrap()
        .snapshot()
}

fn doc_title(key: &str, text: &str) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "title",
            FieldValues::Single(FieldValue::Text(text.to_owned())),
        )
        .unwrap();
    document
}

fn doc_body(key: &str, values: Vec<&str>) -> Document {
    let mut document = Document::new(DocumentKey::new(key).unwrap());
    document
        .insert(
            "body",
            FieldValues::Multi(
                values
                    .into_iter()
                    .map(|value| FieldValue::Text(value.to_owned()))
                    .collect(),
            ),
        )
        .unwrap();
    document
}

fn search(snapshot: &ReaderSnapshot, query: &Query) -> quervant_core::search::SearchResponse {
    let schema = prop_schema();
    let registry = registry();
    LexicalSearcher::new(snapshot, &schema, &registry, SearchLimits::default())
        .search(
            query,
            TopK::new(5_000).unwrap(),
            &Budgets::new(),
            &NeverCancel,
        )
        .expect("search")
}

fn result_set(snapshot: &ReaderSnapshot, query: &Query) -> BTreeSet<String> {
    search(snapshot, query)
        .hits
        .into_iter()
        .map(|hit| hit.key.as_str().to_owned())
        .collect()
}

/// A small deterministic linear congruential generator.
struct Lcg(u64);

impl Lcg {
    fn new(seed: u64) -> Self {
        Self(seed)
    }

    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1_442_695_040_888_963_407);
        self.0 >> 33
    }

    fn below(&mut self, bound: usize) -> usize {
        if bound == 0 {
            0
        } else {
            (self.next() as usize) % bound
        }
    }
}

// ---------------------------------------------------------------------------
// P01 — random bounded Boolean ASTs against a std-library set oracle.
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
enum Ast {
    MatchAll,
    Term(usize),
    And(Vec<Ast>),
    Or(Vec<Ast>),
    Not(Box<Ast>),
}

impl Ast {
    fn to_query(&self, vocab: &[&str]) -> Query {
        match self {
            Self::MatchAll => Query::MatchAll,
            Self::Term(index) => Query::Term {
                field: "title".into(),
                value: FieldValue::Text(vocab[*index].to_owned()),
            },
            Self::And(children) => {
                Query::And(children.iter().map(|child| child.to_query(vocab)).collect())
            }
            Self::Or(children) => {
                Query::Or(children.iter().map(|child| child.to_query(vocab)).collect())
            }
            Self::Not(inner) => Query::Not(Box::new(inner.to_query(vocab))),
        }
    }

    fn evaluate(
        &self,
        matching: &BTreeMap<usize, BTreeSet<String>>,
        universe: &BTreeSet<String>,
    ) -> BTreeSet<String> {
        match self {
            Self::MatchAll => universe.clone(),
            Self::Term(index) => matching.get(index).cloned().unwrap_or_default(),
            Self::And(children) => {
                let mut iter = children.iter();
                let Some(first) = iter.next() else {
                    return BTreeSet::new();
                };
                let mut accumulator = first.evaluate(matching, universe);
                for child in iter {
                    let next = child.evaluate(matching, universe);
                    accumulator = accumulator.intersection(&next).cloned().collect();
                }
                accumulator
            }
            Self::Or(children) => {
                let mut accumulator = BTreeSet::new();
                for child in children {
                    accumulator.extend(child.evaluate(matching, universe));
                }
                accumulator
            }
            Self::Not(inner) => universe
                .difference(&inner.evaluate(matching, universe))
                .cloned()
                .collect(),
        }
    }
}

fn generate_ast(lcg: &mut Lcg, depth: usize, vocab_len: usize) -> Ast {
    if depth == 0 || lcg.below(3) == 0 {
        if lcg.below(4) == 0 {
            return Ast::MatchAll;
        }
        return Ast::Term(lcg.below(vocab_len));
    }
    match lcg.below(4) {
        0 => {
            let count = lcg.below(3) + 1;
            Ast::And(
                (0..count)
                    .map(|_| generate_ast(lcg, depth - 1, vocab_len))
                    .collect(),
            )
        }
        1 => {
            let count = lcg.below(3) + 1;
            Ast::Or(
                (0..count)
                    .map(|_| generate_ast(lcg, depth - 1, vocab_len))
                    .collect(),
            )
        }
        2 => Ast::Not(Box::new(generate_ast(lcg, depth - 1, vocab_len))),
        _ => Ast::Term(lcg.below(vocab_len)),
    }
}

#[test]
fn p01_random_boolean_ast_matches_set_oracle() {
    let vocab = ["a", "b", "c", "d"];
    for seed in 0..200u64 {
        let mut lcg = Lcg::new(0x9e37_79b9_7f4a_7c15 ^ seed);
        let doc_count = lcg.below(20) + 1;
        let mut documents = Vec::new();
        let mut matching: BTreeMap<usize, BTreeSet<String>> = (0..vocab.len())
            .map(|index| (index, BTreeSet::new()))
            .collect();
        let mut universe = BTreeSet::new();
        for doc_index in 0..doc_count {
            let key = format!("d{doc_index:02}");
            let token_count = lcg.below(4) + 1;
            let doc_tokens: Vec<String> = (0..token_count)
                .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                .collect();
            for (term_index, term) in vocab.iter().enumerate() {
                if doc_tokens.iter().any(|token| token == term) {
                    matching.get_mut(&term_index).unwrap().insert(key.clone());
                }
            }
            universe.insert(key.clone());
            documents.push(doc_title(&key, &doc_tokens.join(" ")));
        }
        let snapshot = build_index(vec![documents]);
        let ast = generate_ast(&mut lcg, 5, vocab.len());
        let expected = ast.evaluate(&matching, &universe);
        let actual = result_set(&snapshot, &ast.to_query(&vocab));
        assert_eq!(actual, expected, "seed {seed} ast {ast:?}");
    }
}

// ---------------------------------------------------------------------------
// P02 — random phrases against exhaustive single-value position matching.
// ---------------------------------------------------------------------------

fn phrase_matches_in_value(value_tokens: &[String], phrase: &[String]) -> bool {
    if phrase.is_empty() || phrase.len() > value_tokens.len() {
        return false;
    }
    (0..=value_tokens.len() - phrase.len())
        .any(|start| value_tokens[start..start + phrase.len()] == *phrase)
}

#[test]
fn p02_random_phrases_match_exhaustive_reference() {
    let vocab = ["a", "b", "c"];
    for seed in 0..200u64 {
        let mut lcg = Lcg::new(0x2545_f491_4f6c_dd1d ^ seed);
        let doc_count = lcg.below(8) + 1;
        let mut documents = Vec::new();
        let mut values_by_doc: Vec<Vec<Vec<String>>> = Vec::new();
        for doc_index in 0..doc_count {
            let key = format!("p{doc_index:02}");
            let value_count = lcg.below(2) + 1;
            let mut raw_values = Vec::new();
            let mut token_values = Vec::new();
            for _ in 0..value_count {
                let token_count = lcg.below(4) + 1;
                let doc_tokens: Vec<String> = (0..token_count)
                    .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                    .collect();
                token_values.push(doc_tokens.clone());
                raw_values.push(doc_tokens.join(" "));
            }
            values_by_doc.push(token_values);
            documents.push(doc_body(
                &key,
                raw_values.iter().map(String::as_str).collect(),
            ));
        }
        let phrase_len = lcg.below(3) + 1;
        let phrase: Vec<String> = (0..phrase_len)
            .map(|_| vocab[lcg.below(vocab.len())].to_owned())
            .collect();
        let mut expected = BTreeSet::new();
        for (doc_index, values) in values_by_doc.iter().enumerate() {
            if values
                .iter()
                .any(|value_tokens| phrase_matches_in_value(value_tokens, &phrase))
            {
                expected.insert(format!("p{doc_index:02}"));
            }
        }
        let snapshot = build_index(vec![documents]);
        let query = Query::Phrase {
            field: "body".into(),
            terms: phrase.clone(),
        };
        let actual = result_set(&snapshot, &query);
        assert_eq!(actual, expected, "seed {seed} phrase {phrase:?}");
    }
}

// ---------------------------------------------------------------------------
// P03 — random term frequencies/lengths against the golden BM25 formula.
// ---------------------------------------------------------------------------

fn bm25_reference(tf: u64, df: u64, n: u64, dl: u64, avgdl: f64) -> f64 {
    if tf == 0 || n == 0 || avgdl <= 0.0 {
        return 0.0;
    }
    let tf = tf as f64;
    let df = df as f64;
    let n = n as f64;
    let dl = dl as f64;
    let idf = (1.0 + (n - df + 0.5) / (df + 0.5)).ln();
    idf * (tf * 2.2) / (tf + 1.2 * (1.0 - 0.75 + 0.75 * dl / avgdl))
}

#[test]
fn p03_random_bm25_statistics_match_formula() {
    let vocab = ["x", "y", "z"];
    for seed in 0..200u64 {
        let mut lcg = Lcg::new(0xd1b5_4a32_d192_ed03 ^ seed);
        let doc_count = lcg.below(8) + 1;
        let mut documents = Vec::new();
        let mut token_lists: Vec<Vec<String>> = Vec::new();
        for doc_index in 0..doc_count {
            let key = format!("m{doc_index:02}");
            let token_count = lcg.below(5) + 1;
            let doc_tokens: Vec<String> = (0..token_count)
                .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                .collect();
            token_lists.push(doc_tokens.clone());
            documents.push(doc_title(&key, &doc_tokens.join(" ")));
        }
        let snapshot = build_index(vec![documents]);
        let query_term = vocab[lcg.below(vocab.len())];
        let n = doc_count as u64;
        let df = token_lists
            .iter()
            .filter(|tokens| tokens.iter().any(|token| token == query_term))
            .count() as u64;
        let avgdl = token_lists
            .iter()
            .map(|tokens| tokens.len() as f64)
            .sum::<f64>()
            / n as f64;
        let response = search(
            &snapshot,
            &Query::Term {
                field: "title".into(),
                value: FieldValue::Text(query_term.to_owned()),
            },
        );
        let mut expected: BTreeMap<String, f64> = BTreeMap::new();
        for (doc_index, tokens) in token_lists.iter().enumerate() {
            let tf = tokens
                .iter()
                .filter(|token| token.as_str() == query_term)
                .count() as u64;
            if tf == 0 {
                continue;
            }
            let dl = tokens.len() as u64;
            expected.insert(
                format!("m{doc_index:02}"),
                bm25_reference(tf, df, n, dl, avgdl),
            );
        }
        assert_eq!(response.total_hits as usize, expected.len(), "seed {seed}");
        for hit in &response.hits {
            let key = hit.key.as_str().to_owned();
            let expected_score = expected
                .get(&key)
                .unwrap_or_else(|| panic!("unexpected hit {key} for seed {seed}"));
            assert!(
                (hit.score - expected_score).abs() < 1e-10,
                "seed {seed} key {key}: {} vs {expected_score}",
                hit.score
            );
        }
    }
}

// ---------------------------------------------------------------------------
// P05 — randomized corpus partitioning across 1–4 segments.
// ---------------------------------------------------------------------------

fn partitioned_batches(documents: &[Document], segment_count: usize) -> Vec<Vec<Document>> {
    let mut batches: Vec<Vec<Document>> = vec![Vec::new(); segment_count];
    for (index, document) in documents.iter().enumerate() {
        batches[index % segment_count].push(document.clone());
    }
    batches
}

#[test]
fn p05_partitioning_preserves_hits_and_scores() {
    let vocab = ["a", "b", "c", "d"];
    for seed in 0..60u64 {
        let mut lcg = Lcg::new(0xdead_beef_1234_5678 ^ seed);
        let doc_count = lcg.below(12) + 1;
        let mut documents = Vec::new();
        for doc_index in 0..doc_count {
            let key = format!("q{doc_index:02}");
            let token_count = lcg.below(5) + 1;
            let doc_tokens: Vec<String> = (0..token_count)
                .map(|_| vocab[lcg.below(vocab.len())].to_owned())
                .collect();
            documents.push(doc_title(&key, &doc_tokens.join(" ")));
        }
        let query = Query::Or(vec![
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text(vocab[lcg.below(vocab.len())].to_owned()),
            },
            Query::Term {
                field: "title".into(),
                value: FieldValue::Text(vocab[lcg.below(vocab.len())].to_owned()),
            },
        ]);
        let single = search(&build_index(vec![documents.clone()]), &query);
        for segment_count in 1..=4usize {
            let snapshot = build_index(partitioned_batches(&documents, segment_count));
            let partitioned = search(&snapshot, &query);
            assert_eq!(
                single.total_hits, partitioned.total_hits,
                "seed {seed} segments {segment_count}"
            );
            let single_pairs: Vec<(String, f64)> = single
                .hits
                .iter()
                .map(|hit| (hit.key.as_str().to_owned(), hit.score))
                .collect();
            let partitioned_pairs: Vec<(String, f64)> = partitioned
                .hits
                .iter()
                .map(|hit| (hit.key.as_str().to_owned(), hit.score))
                .collect();
            assert_eq!(single_pairs.len(), partitioned_pairs.len());
            for (left, right) in single_pairs.iter().zip(&partitioned_pairs) {
                assert_eq!(left.0, right.0, "seed {seed} segments {segment_count}");
                assert!(
                    (left.1 - right.1).abs() < 1e-10,
                    "seed {seed} segments {segment_count}: {} vs {}",
                    left.1,
                    right.1
                );
            }
        }
    }
}
