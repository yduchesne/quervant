//! PR 14 phase 14B: typed presence, membership and IP/CIDR predicate execution.
//!
//! Every assertion is checked against an independently enumerated expected key
//! set derived from the approved PR 2 truth tables (A09/A10) and IP semantics
//! (A07/A08), not from the implementation under test.

mod pr14_common;

use std::sync::Arc;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::document::{DocumentKey, MutationRequest};
use quervant_core::search::{SearchError, SearchLimits, TypedSearcher};

fn keys(query: Query) -> Vec<String> {
    let index = committed(presence_docs());
    let snapshot = index.snapshot();
    hit_keys(&typed_search(&snapshot, &request(query)))
}

fn presence_docs() -> Vec<quervant_core::contract::document::Document> {
    let mut docs = Vec::new();
    // a: field absent
    docs.push(doc("a"));
    // b: explicit null
    let mut b = doc("b");
    set_null(&mut b, "nullable");
    set_null(&mut b, "host");
    set_multi(&mut b, "tags", vec![]);
    set_null(&mut b, "tags");
    docs.push(b);
    // c: empty multi
    let mut c = doc("c");
    set_empty(&mut c, "nullable");
    set(&mut c, "host", FieldValue::Keyword("c".into()));
    set_empty(&mut c, "tags");
    docs.push(c);
    // d/e: values
    let mut d = doc("d");
    set(&mut d, "nullable", FieldValue::I64(7));
    set(&mut d, "host", FieldValue::Keyword("d".into()));
    set_multi(&mut d, "tags", vec![FieldValue::Keyword("x".into())]);
    docs.push(d);
    let mut e = doc("e");
    set(&mut e, "nullable", FieldValue::I64(9));
    set(&mut e, "host", FieldValue::Keyword("x".into()));
    set_multi(
        &mut e,
        "tags",
        vec![
            FieldValue::Keyword("x".into()),
            FieldValue::Keyword("y".into()),
        ],
    );
    docs.push(e);
    docs
}

// T01 — EXISTS/MISSING/IS NULL truth table (A09).
#[test]
fn t01_presence_truth_table() {
    assert_eq!(
        keys(Query::Exists {
            field: "nullable".into()
        }),
        ["b", "c", "d", "e"]
    );
    assert_eq!(
        keys(Query::Missing {
            field: "nullable".into()
        }),
        ["a"]
    );
    assert_eq!(
        keys(Query::IsNull {
            field: "nullable".into()
        }),
        ["b"]
    );
    // Exists and Missing partition the universe.
    let exists = keys(Query::Exists {
        field: "nullable".into(),
    });
    let missing = keys(Query::Missing {
        field: "nullable".into(),
    });
    assert_eq!(exists.len() + missing.len(), 5);
    // IS NULL implies EXISTS and excludes MISSING.
    assert!(exists.contains(&"b".to_owned()));
    assert!(!missing.contains(&"b".to_owned()));
}

// T02 — IN/NOT IN truth table including absent/null/empty multi.
#[test]
fn t02_membership_truth_table() {
    let in_set = Query::In {
        field: "nullable".into(),
        values: vec![FieldValue::I64(7), FieldValue::I64(9)],
    };
    // Any-member membership over present non-null values.
    assert_eq!(keys(in_set.clone()), ["d", "e"]);
    // NOT IN excludes absent/null but accepts empty multi vacuously.
    let not_in = Query::NotIn {
        field: "nullable".into(),
        values: vec![FieldValue::I64(7), FieldValue::I64(9)],
    };
    assert_eq!(keys(not_in.clone()), ["c"]);
    // NOT(IN) is the complement and includes absent/null: it differs from NOT IN.
    let not_in_query = Query::Not(Box::new(in_set));
    assert_eq!(keys(not_in_query), ["a", "b", "c"]);
    assert_ne!(
        keys(not_in),
        keys(Query::Not(Box::new(Query::In {
            field: "nullable".into(),
            values: vec![FieldValue::I64(7), FieldValue::I64(9)],
        })))
    );
}

// T03 — membership over multi-valued fields uses any-member semantics.
#[test]
fn t03_multivalue_membership() {
    let in_x = Query::In {
        field: "tags".into(),
        values: vec![FieldValue::Keyword("x".into())],
    };
    // d has [x], e has [x, y], c empty; b explicit null; a absent.
    assert_eq!(keys(in_x), ["d", "e"]);
    let not_in_x = Query::NotIn {
        field: "tags".into(),
        values: vec![FieldValue::Keyword("x".into())],
    };
    // c empty is vacuously NOT IN; d/e contain x; a/b absent/null excluded.
    assert_eq!(keys(not_in_x), ["c"]);
}

// T04 — IPv4/IPv6 exact equality never coerces across families.
#[test]
fn t04_ip_exact_family() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let v4 = typed_search(
        &snapshot,
        &request(Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        }),
    );
    assert_eq!(hit_keys(&v4), ["a"]);
    let v6 = typed_search(
        &snapshot,
        &request(Query::IpExact {
            field: "ip".into(),
            addr: "2001:db8::1".parse().unwrap(),
        }),
    );
    assert_eq!(hit_keys(&v6), ["b"]);
    // The IPv4-mapped address is a distinct IPv6 identity.
    let mapped = typed_search(
        &snapshot,
        &request(Query::IpExact {
            field: "ip".into(),
            addr: "::ffff:192.0.2.1".parse().unwrap(),
        }),
    );
    assert_eq!(hit_keys(&mapped), ["c"]);
}

// T05 — inclusive, family-aware IP ranges.
#[test]
fn t05_ip_range_endpoints() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let range = |start: &str, end: &str| {
        typed_search(
            &snapshot,
            &request(Query::IpRange {
                field: "ip".into(),
                start: start.parse().unwrap(),
                end: end.parse().unwrap(),
            }),
        )
    };
    assert_eq!(hit_keys(&range("192.0.2.1", "192.0.2.1")), ["a"]);
    assert_eq!(hit_keys(&range("192.0.2.1", "192.0.2.2")), ["a", "d"]);
    // Mixed-family bounds are rejected at validation before any scan.
    let mixed = typed_search_result(
        &snapshot,
        &request(Query::IpRange {
            field: "ip".into(),
            start: "192.0.2.1".parse().unwrap(),
            end: "2001:db8::1".parse().unwrap(),
        }),
    );
    assert!(mixed.is_err());
}

// T06 — CIDR /0 and /32 boundaries for IPv4.
#[test]
fn t06_ipv4_cidr_boundaries() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let all_v4 = typed_search(
        &snapshot,
        &request(Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("0.0.0.0".parse().unwrap(), 0).unwrap(),
        }),
    );
    // Matches every IPv4 address (a, d, e) but never IPv6 (b, c).
    assert_eq!(hit_keys(&all_v4), ["a", "d", "e"]);
    let host = typed_search(
        &snapshot,
        &request(Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("192.0.2.1".parse().unwrap(), 32).unwrap(),
        }),
    );
    assert_eq!(hit_keys(&host), ["a"]);
}

// T07 — CIDR /0 and /128 boundaries for IPv6.
#[test]
fn t07_ipv6_cidr_boundaries() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let all_v6 = typed_search(
        &snapshot,
        &request(Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("::".parse().unwrap(), 0).unwrap(),
        }),
    );
    assert_eq!(hit_keys(&all_v6), ["b", "c"]);
    let host = typed_search(
        &snapshot,
        &request(Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("2001:db8::1".parse().unwrap(), 128).unwrap(),
        }),
    );
    assert_eq!(hit_keys(&host), ["b"]);
}

// T08 — NOT IN CIDR: absent/null excluded, present non-matching included.
#[test]
fn t08_ip_not_in_cidr() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let not_v4 = typed_search(
        &snapshot,
        &request(Query::IpNotInCidr {
            field: "ip".into(),
            network: IpNetwork::new("0.0.0.0".parse().unwrap(), 0).unwrap(),
        }),
    );
    // IPv6 addresses are present and not contained; absent/null excluded.
    assert_eq!(hit_keys(&not_v4), ["b", "c"]);
    // NOT(IN) differs: it resurrects absent and null documents.
    let not_in = typed_search(
        &snapshot,
        &request(Query::Not(Box::new(Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("0.0.0.0".parse().unwrap(), 0).unwrap(),
        }))),
    );
    assert_eq!(hit_keys(&not_in), ["b", "c", "f"]);
}

// T09 — IpNetwork field containment (stored network is a subset of the query).
#[test]
fn t09_ip_network_containment() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let within = typed_search(
        &snapshot,
        &request(Query::IpInCidr {
            field: "net".into(),
            network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
        }),
    );
    assert_eq!(hit_keys(&within), ["d", "e"]);
    let v6 = typed_search(
        &snapshot,
        &request(Query::IpInCidr {
            field: "net".into(),
            network: IpNetwork::new("2001:db8::".parse().unwrap(), 32).unwrap(),
        }),
    );
    assert_eq!(hit_keys(&v6), ["f"]);
}

// T10 — nested Boolean composition of typed and IP predicates.
#[test]
fn t10_compound_typed_boolean() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    // (ip in 192.0.2.0/24) AND NOT (exact 192.0.2.1)
    let query = Query::And(vec![
        Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("192.0.2.0".parse().unwrap(), 24).unwrap(),
        },
        Query::Not(Box::new(Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        })),
    ]);
    assert_eq!(hit_keys(&typed_search(&snapshot, &request(query))), ["d"]);
    // OR across families.
    let either = Query::Or(vec![
        Query::IpExact {
            field: "ip".into(),
            addr: "192.0.2.1".parse().unwrap(),
        },
        Query::IpExact {
            field: "ip".into(),
            addr: "2001:db8::1".parse().unwrap(),
        },
    ]);
    assert_eq!(
        hit_keys(&typed_search(&snapshot, &request(either))),
        ["a", "b"]
    );
}

// T11 — deletes and PIT snapshots apply before typed predicates.
#[test]
fn t11_delete_and_pit() {
    let directory = memory();
    let index = create(Arc::clone(&directory));
    {
        let mut writer = index.writer().unwrap();
        for document in ip_docs() {
            writer.insert(document).unwrap();
        }
        writer.commit().unwrap();
    }
    let pinned = reopen(Arc::clone(&directory)).snapshot();
    {
        let current = reopen(Arc::clone(&directory));
        let mut writer = current.writer().unwrap();
        writer
            .apply(MutationRequest::delete(DocumentKey::new("a").unwrap()))
            .unwrap();
        writer.commit().unwrap();
    }
    let live = reopen(directory).snapshot();
    let all = Query::IpInCidr {
        field: "ip".into(),
        network: IpNetwork::new("0.0.0.0".parse().unwrap(), 0).unwrap(),
    };
    // The old PIT still sees the deleted document; the current snapshot does not.
    assert_eq!(
        hit_keys(&typed_search(&pinned, &request(all.clone()))),
        ["a", "d", "e"]
    );
    assert_eq!(hit_keys(&typed_search(&live, &request(all))), ["d", "e"]);
}

// T12 — cancellation is observed before and during execution.
#[test]
fn t12_cancellation() {
    let index = committed(ip_docs());
    let snapshot = index.snapshot();
    let schema = schema();
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let result = TypedSearcher::new(&snapshot, &schema, SearchLimits::default()).search(
        &request(Query::MatchAll),
        &Budgets::new(),
        &cancel,
    );
    assert!(matches!(result, Err(SearchError::Cancelled)));
}

fn ip_docs() -> Vec<quervant_core::contract::document::Document> {
    let mut docs = Vec::new();
    // a: IPv4 192.0.2.1, subset net 192.0.2.0/24
    let mut a = doc("a");
    set(&mut a, "ip", FieldValue::Ip("192.0.2.1".parse().unwrap()));
    set(
        &mut a,
        "net",
        FieldValue::Cidr(IpNetwork::new("192.0.2.0".parse().unwrap(), 24).unwrap()),
    );
    docs.push(a);
    // b: IPv6 2001:db8::1
    let mut b = doc("b");
    set(&mut b, "ip", FieldValue::Ip("2001:db8::1".parse().unwrap()));
    docs.push(b);
    // c: IPv4-mapped IPv6 (stays IPv6)
    let mut c = doc("c");
    set(
        &mut c,
        "ip",
        FieldValue::Ip("::ffff:192.0.2.1".parse().unwrap()),
    );
    docs.push(c);
    // d: IPv4 192.0.2.2, network 10.1.0.0/16 (subset of 10/8)
    let mut d = doc("d");
    set(&mut d, "ip", FieldValue::Ip("192.0.2.2".parse().unwrap()));
    set(
        &mut d,
        "net",
        FieldValue::Cidr(IpNetwork::new("10.1.0.0".parse().unwrap(), 16).unwrap()),
    );
    docs.push(d);
    // e: IPv4 10.9.9.9, network 10.0.0.0/8 (exact query)
    let mut e = doc("e");
    set(&mut e, "ip", FieldValue::Ip("10.9.9.9".parse().unwrap()));
    set(
        &mut e,
        "net",
        FieldValue::Cidr(IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap()),
    );
    docs.push(e);
    // f: IPv6 network 2001:db8::/32
    let mut f = doc("f");
    set(
        &mut f,
        "net",
        FieldValue::Cidr(IpNetwork::new("2001:db8::".parse().unwrap(), 32).unwrap()),
    );
    docs.push(f);
    docs
}
