//! PR 9 independent-oracle property test.
//!
//! A seeded deterministic operation stream is replayed against the production
//! `IndexWriter` while a test-only `BTreeMap` oracle tracks the expected live
//! key set and revisions. The oracle never calls production mutation-state or
//! live-mask code.

mod pr09_common;

use std::collections::BTreeMap;

use pr09_common::{create, doc, hit_keys, memory};

use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::contract::query::Query;
use quervant_core::index::IndexError;

/// A deterministic 64-bit linear congruential generator.
struct Lcg(u64);

impl Lcg {
    fn next(&mut self) -> u64 {
        self.0 = self
            .0
            .wrapping_mul(6364136223846793005)
            .wrapping_add(1442695040888963407);
        self.0 >> 33
    }
}

#[test]
fn t42_seeded_stream_matches_independent_oracle() {
    let directory = memory();
    let index = create(directory.clone());
    let mut oracle: BTreeMap<String, (u64, Option<String>)> = BTreeMap::new();
    let mut rng = Lcg(0x5eed_1234_abcd_0001);
    let mut writer = index.writer().unwrap();

    for step in 0..80u64 {
        let key = format!("k{}", rng.next() % 8);
        let title = if rng.next() % 2 == 0 { "alpha" } else { "beta" };
        let document_key = DocumentKey::new(&key).unwrap();
        let previous = oracle.get(&key).map_or(0, |(revision, _)| *revision);
        let live = oracle
            .get(&key)
            .and_then(|(_, value)| value.as_ref())
            .is_some();
        match rng.next() % 4 {
            0 => {
                // Insert: rejected iff currently live.
                let result = writer.apply(MutationRequest::insert(doc(&key, title, "", "x", 1)));
                if live {
                    assert!(matches!(result, Err(IndexError::DuplicateDocument { .. })));
                } else {
                    let revision = result.unwrap().revision.unwrap();
                    assert_eq!(revision, previous + 1, "step {step} insert revision");
                    oracle.insert(key.clone(), (revision, Some(title.to_owned())));
                }
            }
            1 => {
                let revision = writer
                    .apply(MutationRequest::upsert(doc(&key, title, "", "x", 1)))
                    .unwrap()
                    .revision
                    .unwrap();
                assert_eq!(revision, previous + 1, "step {step} upsert revision");
                oracle.insert(key.clone(), (revision, Some(title.to_owned())));
            }
            2 => {
                let revision = writer
                    .apply(MutationRequest::delete(document_key))
                    .unwrap()
                    .revision
                    .unwrap();
                assert_eq!(revision, previous + 1, "step {step} delete revision");
                oracle.insert(key.clone(), (revision, None));
            }
            _ => {
                // Upsert then immediately verify the volatile view.
                let revision = writer
                    .apply(MutationRequest::upsert(doc(&key, title, "", "x", 1)))
                    .unwrap()
                    .revision
                    .unwrap();
                assert_eq!(revision, previous + 1);
                oracle.insert(key.clone(), (revision, Some(title.to_owned())));
            }
        }

        if step % 10 == 9 {
            writer.commit().unwrap();
            // Reopen to exercise the durable generation path.
            writer.close().unwrap();
            writer = index.writer().unwrap();
            let snapshot = writer.reader();
            let mut expected: Vec<String> = oracle
                .iter()
                .filter(|(_, (_, value))| value.is_some())
                .map(|(key, _)| key.clone())
                .collect();
            expected.sort();
            assert_eq!(
                hit_keys(&snapshot, &Query::MatchAll),
                expected,
                "step {step} live set"
            );
        }
    }
}
