//! Test-only independent semantic reference oracles (Phase 4).
//!
//! These functions deliberately re-derive predicate and aggregation semantics
//! with straightforward implementations so contract conformance tests can
//! compare against the production validators. They are compiled for tests only.

use std::collections::{BTreeMap, BTreeSet};
use std::net::IpAddr;

use super::document::FieldValues;
use super::value::{FieldValue, IpNetwork};

/// Whether a field is present (including explicit null and empty multi-value).
#[must_use]
pub fn exists(state: &FieldValues) -> bool {
    !state.is_absent()
}

/// Whether a field is absent.
#[must_use]
pub fn missing(state: &FieldValues) -> bool {
    state.is_absent()
}

/// Whether a field is explicitly null.
#[must_use]
pub fn is_null(state: &FieldValues) -> bool {
    state.is_explicit_null()
}

/// Any-member membership for present, non-null values.
#[must_use]
pub fn in_matches(state: &FieldValues, members: &[FieldValue]) -> bool {
    if state.is_absent() || state.is_explicit_null() {
        return false;
    }
    state.values().any(|value| members.contains(value))
}

/// `NOT IN` is the negation only over present, non-null values; absent/null are
/// excluded, and an empty multi-value is vacuously non-matching (`true`).
#[must_use]
pub fn not_in_matches(state: &FieldValues, members: &[FieldValue]) -> bool {
    if state.is_absent() || state.is_explicit_null() {
        return false;
    }
    if state.is_empty_multi() {
        return true;
    }
    !in_matches(state, members)
}

/// Independent family-aware CIDR membership.
#[must_use]
pub fn cidr_contains(network: &IpNetwork, addr: &IpAddr) -> bool {
    match (network.addr(), addr) {
        (IpAddr::V4(net), IpAddr::V4(candidate)) => {
            let prefix = network.prefix();
            if prefix > 32 {
                return false;
            }
            let mask = if prefix == 0 {
                0
            } else {
                u32::MAX << (32 - u32::from(prefix))
            };
            (u32::from(net) & mask) == (u32::from(*candidate) & mask)
        }
        (IpAddr::V6(net), IpAddr::V6(candidate)) => {
            let prefix = network.prefix();
            if prefix > 128 {
                return false;
            }
            let mask = if prefix == 0 {
                0
            } else {
                u128::MAX << (128 - u32::from(prefix))
            };
            (u128::from(net) & mask) == (u128::from(*candidate) & mask)
        }
        _ => false,
    }
}

/// Exact distinct count with per-document membership.
#[must_use]
pub fn distinct_count(documents: &[Vec<i64>]) -> usize {
    let mut set = BTreeSet::new();
    for document in documents {
        for value in document {
            set.insert(*value);
        }
    }
    set.len()
}

/// Top-K frequent values: documents containing a value, once per document.
#[must_use]
pub fn top_k(documents: &[Vec<i64>], k: usize) -> Vec<(i64, usize)> {
    let mut counts: BTreeMap<i64, usize> = BTreeMap::new();
    for document in documents {
        let unique: BTreeSet<i64> = document.iter().copied().collect();
        for value in unique {
            *counts.entry(value).or_default() += 1;
        }
    }
    let mut entries: Vec<(i64, usize)> = counts.into_iter().collect();
    entries.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    entries.truncate(k);
    entries
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::value::{FieldValue, GeoPoint, IpNetwork};

    fn keyword(value: &str) -> FieldValue {
        FieldValue::Keyword(value.to_owned())
    }

    #[test]
    fn presence_truth_table() {
        let x = keyword("x");
        assert!(!exists(&FieldValues::Absent));
        assert!(missing(&FieldValues::Absent));
        assert!(!is_null(&FieldValues::Absent));
        assert!(exists(&FieldValues::ExplicitNull));
        assert!(!missing(&FieldValues::ExplicitNull));
        assert!(is_null(&FieldValues::ExplicitNull));
        assert!(exists(&FieldValues::Empty));
        assert!(!is_null(&FieldValues::Empty));
        assert!(exists(&FieldValues::Single(x.clone())));
    }

    #[test]
    fn membership_truth_table() {
        let x = keyword("x");
        let y = keyword("y");
        let members = [x.clone()];
        assert!(!in_matches(&FieldValues::Absent, &members));
        assert!(!not_in_matches(&FieldValues::Absent, &members));
        assert!(!in_matches(&FieldValues::ExplicitNull, &members));
        assert!(!not_in_matches(&FieldValues::ExplicitNull, &members));
        assert!(!in_matches(&FieldValues::Empty, &members));
        assert!(not_in_matches(&FieldValues::Empty, &members));
        assert!(in_matches(&FieldValues::Single(x.clone()), &members));
        assert!(!not_in_matches(&FieldValues::Single(x.clone()), &members));
        assert!(!in_matches(&FieldValues::Single(y.clone()), &members));
        assert!(not_in_matches(&FieldValues::Single(y.clone()), &members));
        assert!(in_matches(
            &FieldValues::Multi(vec![x.clone(), y.clone()]),
            &members
        ));
        assert!(!not_in_matches(&FieldValues::Multi(vec![x, y]), &members));
    }

    #[test]
    fn cidr_reference_matches_families() {
        let v4 = IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap();
        assert!(cidr_contains(&v4, &"10.1.2.3".parse().unwrap()));
        assert!(!cidr_contains(&v4, &"11.0.0.1".parse().unwrap()));
        assert!(!cidr_contains(&v4, &"2001:db8::1".parse().unwrap()));
        let v6 = IpNetwork::new("2001:db8::".parse().unwrap(), 32).unwrap();
        assert!(cidr_contains(&v6, &"2001:db8::1".parse().unwrap()));
        assert!(!cidr_contains(&v6, &"2001:db9::1".parse().unwrap()));
        let _ = GeoPoint::new(0.0, 0.0);
    }

    #[test]
    fn distinct_and_frequency_reference() {
        let documents = vec![vec![1, 1, 2], vec![2, 3], vec![3, 3]];
        assert_eq!(distinct_count(&documents), 3);
        let top = top_k(&documents, 2);
        assert_eq!(top[0], (2, 2));
        assert_eq!(top[1], (3, 2));
        assert_eq!(top_k(&documents, 10).len(), 3);
    }
}
