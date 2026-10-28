//! PR 15A — local regression vertical over the frozen `pr15a_v1` fixture.
//!
//! Phase P1 contains only the frozen fixture and pure-oracle gate (A-T00).
//! Local vertical tests A-T01…A-T17 are added in the P2 commit.

mod pr14_common;
mod pr15a_common;

use std::collections::{BTreeMap, BTreeSet};

use pr15a_common::*;

// ---------------------------------------------------------------------------
// A-T00 — frozen fixture and pure oracle
// ---------------------------------------------------------------------------

#[test]
fn a15_t00_frozen_fixture_and_pure_oracle() {
    assert_frozen_digest();

    // Every documented predicate is asserted against both the helper output and
    // a literal expectation, so a bug in the helper cannot change the answer.
    assert_eq!(oracle_sorted(Predicate::Alpha), vec!["a0", "a1", "b0", "b3"]);
    assert_eq!(
        oracle_sorted(Predicate::NAtLeast50),
        vec!["b0", "b1", "b2", "b3"]
    );
    assert_eq!(oracle_sorted(Predicate::AlphaAndN50), vec!["b0", "b3"]);
    assert_eq!(oracle_sorted(Predicate::HostH2), vec!["a1", "b1", "b3"]);
    assert_eq!(
        oracle_sorted(Predicate::Ipv4Cidr10),
        vec!["a0", "a1", "b3"]
    );
    assert_eq!(
        oracle_sorted(Predicate::TimeInclusive2000To5000),
        vec!["a1", "a2", "a3", "b0"]
    );
    assert_eq!(
        oracle_sorted(Predicate::AlphaAndHostH2),
        vec!["a1", "b3"]
    );
    assert_eq!(
        oracle_sorted(Predicate::NotAlpha),
        vec!["a2", "a3", "b1", "b2"]
    );
    assert_eq!(oracle_sorted(Predicate::SeverityTwo), vec!["a1", "b0"]);
    assert_eq!(
        oracle_sorted(Predicate::Ipv6Cidr2001Db8),
        vec!["a3", "b2"]
    );
    assert_eq!(
        oracle_group_counts(),
        BTreeMap::from([("h1", 3), ("h2", 3), ("h3", 2)])
    );
    assert_eq!(oracle_distinct_hosts(), 3);

    // Segment membership, insertion order and uniqueness are literal.
    let documents = base_documents();
    assert_eq!(documents.len(), 8);
    let keys: Vec<&str> = documents.iter().map(|doc| doc.key().as_str()).collect();
    assert_eq!(keys, OLD_KEYS);
    let unique: BTreeSet<&str> = keys.iter().copied().collect();
    assert_eq!(unique.len(), 8);
    let segment0_docs = segment0_documents();
    let segment1_docs = segment1_documents();
    let segment0: Vec<&str> = segment0_docs
        .iter()
        .map(|doc| doc.key().as_str())
        .collect();
    let segment1: Vec<&str> = segment1_docs
        .iter()
        .map(|doc| doc.key().as_str())
        .collect();
    assert_eq!(segment0, ["a0", "a1", "a2", "a3"]);
    assert_eq!(segment1, ["b0", "b1", "b2", "b3"]);

    // Intentional wrong-set negative: the oracle helper rejects an incomplete
    // alpha set. The suite stays green because the wrong set is asserted not
    // to equal the oracle result.
    let incomplete = ["a0", "a1", "b0"];
    assert_ne!(oracle_sorted(Predicate::Alpha), incomplete);
    assert!(!oracle_sorted(Predicate::Alpha).contains(&"a2"));
    assert_eq!(FIXTURE_VERSION, "pr15a_v1");
    assert!(CANONICAL_JSON.contains("\"version\": \"pr15a_v1\""));
}
