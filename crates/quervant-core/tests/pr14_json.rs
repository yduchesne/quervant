//! PR 14 phase 14C: JSON path range, scalar-array membership and indexed sort.
//!
//! Expected key sets are enumerated independently from the approved JSON
//! semantics (scalar types stay distinct; missing/null/containers never match a
//! scalar range; array membership examines immediate scalar elements only).

mod pr14_common;

use pr14_common::*;
use quervant_core::analysis::CancellationFlag;
use quervant_core::contract::budget::Budgets;
use quervant_core::contract::query::{ConcreteJsonPath, JsonPathExpr, JsonPathSegment};
use quervant_core::contract::value::{JsonNumber, JsonValue, Timestamp};
use quervant_core::search::{SearchError, SearchLimits, TypedCursor, TypedSearcher};

fn path(expr: &str) -> ConcreteJsonPath {
    JsonPathExpr::parse(expr)
        .expect("path parses")
        .to_concrete()
        .expect("path is concrete")
}

fn num(value: i64) -> JsonValue {
    JsonValue::Number(JsonNumber::I64(value))
}

fn fnum(value: f64) -> JsonValue {
    JsonValue::Number(JsonNumber::F64(value))
}

fn unum(value: u64) -> JsonValue {
    JsonValue::Number(JsonNumber::U64(value))
}

fn obj(entries: Vec<(&str, JsonValue)>) -> JsonValue {
    JsonValue::Object(
        entries
            .into_iter()
            .map(|(key, value)| (key.to_owned(), value))
            .collect(),
    )
}

fn json_doc(key: &str, body: JsonValue) -> quervant_core::contract::document::Document {
    let mut document = doc(key);
    set(&mut document, "body", FieldValue::Json(body));
    document
}

fn search_json(index: &quervant_core::index::Index, query: Query) -> Vec<String> {
    let snapshot = index.snapshot();
    hit_keys(&typed_search(&snapshot, &request(query)))
}

fn range(field: &str, expr: &str, lower: Bound<FieldValue>, upper: Bound<FieldValue>) -> Query {
    Query::JsonPathRange {
        field: field.to_owned(),
        path: path(expr),
        lower,
        upper,
    }
}

fn contains(field: &str, expr: &str, value: FieldValue) -> Query {
    Query::JsonPathArrayContains {
        field: field.to_owned(),
        path: path(expr),
        value,
    }
}

fn basic_docs() -> Vec<quervant_core::contract::document::Document> {
    vec![
        json_doc(
            "a",
            obj(vec![("n", num(1)), ("s", JsonValue::String("1".into()))]),
        ),
        json_doc("b", obj(vec![("n", fnum(1.0))])),
        json_doc("c", obj(vec![("n", unum(1))])),
        json_doc("d", obj(vec![("n", num(2))])),
        json_doc("e", obj(vec![("n", num(3))])),
    ]
}

// J01 — inclusive/exclusive range endpoints on an indexed JSON path.
#[test]
fn j01_range_endpoints() {
    let index = committed(basic_docs());
    let keys = |lower, upper| search_json(&index, range("body", "$.n", lower, upper));
    assert_eq!(
        keys(
            Bound::Included(FieldValue::I64(1)),
            Bound::Included(FieldValue::I64(2))
        ),
        ["a", "d"]
    );
    assert_eq!(
        keys(
            Bound::Excluded(FieldValue::I64(1)),
            Bound::Included(FieldValue::I64(2))
        ),
        ["d"]
    );
    assert_eq!(
        keys(
            Bound::Included(FieldValue::I64(1)),
            Bound::Excluded(FieldValue::I64(2))
        ),
        ["a"]
    );
    assert_eq!(
        keys(
            Bound::Excluded(FieldValue::I64(1)),
            Bound::Excluded(FieldValue::I64(2))
        ),
        Vec::<String>::new()
    );
}

// J02 — numeric type distinctions are preserved (no coercion).
#[test]
fn j02_scalar_types_stay_distinct() {
    let index = committed(basic_docs());
    // I64 range 1..=1 matches only the I64 node, not U64 1, F64 1.0 or "1".
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.n",
                Bound::Included(FieldValue::I64(1)),
                Bound::Included(FieldValue::I64(1))
            )
        ),
        ["a"]
    );
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.n",
                Bound::Included(FieldValue::U64(1)),
                Bound::Included(FieldValue::U64(1))
            )
        ),
        ["c"]
    );
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.n",
                Bound::Included(FieldValue::F64(1.0)),
                Bound::Included(FieldValue::F64(1.0))
            )
        ),
        ["b"]
    );
    // A string comparison only matches string nodes.
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.s",
                Bound::Included(FieldValue::Keyword("1".into())),
                Bound::Included(FieldValue::Keyword("1".into()))
            )
        ),
        ["a"]
    );
}

// J03 — missing/null/object/array nodes never match a scalar range.
#[test]
fn j03_non_scalar_does_not_match() {
    let docs = vec![
        json_doc("missing", obj(vec![("other", num(1))])),
        json_doc("null", obj(vec![("n", JsonValue::Null)])),
        json_doc("object", obj(vec![("n", obj(vec![("x", num(1))]))])),
        json_doc("array", obj(vec![("n", JsonValue::Array(vec![num(1)]))])),
        json_doc("match", obj(vec![("n", num(1))])),
    ];
    let index = committed(docs);
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.n",
                Bound::Included(FieldValue::I64(0)),
                Bound::Included(FieldValue::I64(10))
            )
        ),
        ["match"]
    );
}

// J04 — signed, unsigned and float domains are compared inside their own type.
#[test]
fn j04_signed_unsigned_float() {
    let docs = vec![
        json_doc("neg", obj(vec![("n", num(-1))])),
        json_doc("pos", obj(vec![("n", num(1))])),
        json_doc("float", obj(vec![("n", fnum(0.5))])),
    ];
    let index = committed(docs);
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.n",
                Bound::Included(FieldValue::I64(-2)),
                Bound::Included(FieldValue::I64(0))
            )
        ),
        ["neg"]
    );
    assert_eq!(
        search_json(
            &index,
            range(
                "body",
                "$.n",
                Bound::Included(FieldValue::F64(0.0)),
                Bound::Included(FieldValue::F64(1.0))
            )
        ),
        ["float"]
    );
}

// J05 — scalar-array membership inspects immediate elements only.
#[test]
fn j05_immediate_array_membership() {
    let docs = vec![
        json_doc(
            "flat",
            obj(vec![(
                "tags",
                JsonValue::Array(vec![
                    JsonValue::String("a".into()),
                    JsonValue::String("b".into()),
                ]),
            )]),
        ),
        json_doc(
            "nested",
            obj(vec![(
                "tags",
                JsonValue::Array(vec![JsonValue::Array(vec![JsonValue::String("a".into())])]),
            )]),
        ),
        json_doc("scalar", obj(vec![("tags", JsonValue::String("a".into()))])),
        json_doc("empty", obj(vec![("tags", JsonValue::Array(vec![]))])),
    ];
    let index = committed(docs);
    let query = contains("body", "$.tags", FieldValue::Keyword("a".into()));
    // Flat array matches; the nested array element is an array, not a scalar.
    assert_eq!(search_json(&index, query.clone()), ["flat"]);
    // A scalar at the path is not an array and never matches.
    let index2 = committed(vec![json_doc(
        "scalar",
        obj(vec![("tags", JsonValue::String("a".into()))]),
    )]);
    assert!(search_json(&index2, query).is_empty());
}

// J06 — indexed-but-not-stored JSON fields answer range and membership.
#[test]
fn j06_indexed_not_stored() {
    let mut document = doc("only-raw");
    set(
        &mut document,
        "raw",
        FieldValue::Json(obj(vec![
            ("n", num(7)),
            (
                "tags",
                JsonValue::Array(vec![JsonValue::String("x".into())]),
            ),
        ])),
    );
    let index = committed(vec![document]);
    assert_eq!(
        search_json(
            &index,
            range(
                "raw",
                "$.n",
                Bound::Included(FieldValue::I64(7)),
                Bound::Included(FieldValue::I64(7))
            )
        ),
        ["only-raw"]
    );
    assert_eq!(
        search_json(
            &index,
            contains("raw", "$.tags", FieldValue::Keyword("x".into()))
        ),
        ["only-raw"]
    );
}

// J07 — malformed path depth and overly long members fail closed with a budget.
#[test]
fn j07_path_budgets_fail_closed() {
    let index = committed(vec![json_doc("a", obj(vec![("n", num(1))]))]);
    let snapshot = index.snapshot();
    let deep = ConcreteJsonPath::new(vec![JsonPathSegment::Member("a".into()); 129]).unwrap();
    let result = typed_search_result(
        &snapshot,
        &request(Query::JsonPathRange {
            field: "body".into(),
            path: deep,
            lower: Bound::Included(FieldValue::I64(0)),
            upper: Bound::Included(FieldValue::I64(1)),
        }),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));

    let long = ConcreteJsonPath::new(vec![JsonPathSegment::Member("x".repeat(65_536))]).unwrap();
    let result = typed_search_result(
        &snapshot,
        &request(Query::JsonPathArrayContains {
            field: "body".into(),
            path: long,
            value: FieldValue::I64(1),
        }),
    );
    assert!(matches!(result, Err(SearchError::ResourceLimit { .. })));
}

// J08 — reversed bounds and type-mismatched bounds are rejected before scanning.
#[test]
fn j08_reversed_and_mismatched_bounds() {
    let index = committed(vec![json_doc("a", obj(vec![("n", num(1))]))]);
    let snapshot = index.snapshot();
    let reversed = typed_search_result(
        &snapshot,
        &request(range(
            "body",
            "$.n",
            Bound::Included(FieldValue::I64(5)),
            Bound::Included(FieldValue::I64(1)),
        )),
    );
    assert!(reversed.is_err());
    let mismatched = Query::JsonPathRange {
        field: "body".into(),
        path: path("$.n"),
        lower: Bound::Included(FieldValue::I64(1)),
        upper: Bound::Included(FieldValue::Keyword("z".into())),
    };
    assert!(mismatched.validate(&schema(), &Budgets::new()).is_err());
}

// J09 — JSON path sort orders values, then null, then missing (missing-last).
#[test]
fn j09_sort_missing_null() {
    let docs = vec![
        json_doc("two", obj(vec![("n", num(2))])),
        json_doc("one", obj(vec![("n", num(1))])),
        json_doc("null", obj(vec![("n", JsonValue::Null)])),
        doc("absent"),
    ];
    let index = committed(docs);
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.n").unwrap()),
    ]);
    let mut request = request(Query::MatchAll);
    request.sort = sort;
    let response = typed_search(&snapshot, &request);
    assert_eq!(hit_keys(&response), ["one", "two", "null", "absent"]);
}

// J10 — wildcard JSON sort applies the declared multi-value selector.
#[test]
fn j10_sort_multivalue_selector() {
    let docs = vec![
        json_doc(
            "a",
            JsonValue::Array(vec![obj(vec![("n", num(5))]), obj(vec![("n", num(1))])]),
        ),
        json_doc("b", JsonValue::Array(vec![obj(vec![("n", num(3))])])),
    ];
    let index = committed(docs);
    let snapshot = index.snapshot();
    let wildcard = JsonPathExpr::parse("$[*].n").unwrap();
    let run = |selector| {
        let mut request = request(Query::MatchAll);
        request.sort = Sort::new(vec![
            SortField::new("body", SortDirection::Asc)
                .with_json_path(wildcard.clone())
                .with_multi(selector),
        ]);
        hit_keys(&typed_search(&snapshot, &request))
    };
    assert_eq!(run(MultiValueSelector::Min), ["a", "b"]);
    assert_eq!(run(MultiValueSelector::Max), ["b", "a"]);
}

// J11 — JSON sort paginates without gaps or duplicates under tied values.
#[test]
fn j11_json_sort_search_after() {
    let docs = vec![
        json_doc("a", obj(vec![("n", num(1))])),
        json_doc("b", obj(vec![("n", num(1))])),
        json_doc("c", obj(vec![("n", num(1))])),
        json_doc("d", obj(vec![("n", num(2))])),
    ];
    let index = committed(docs);
    let snapshot = index.snapshot();
    let sort = Sort::new(vec![
        SortField::new("body", SortDirection::Asc)
            .with_json_path(JsonPathExpr::parse("$.n").unwrap()),
    ]);
    let mut request = request(Query::MatchAll);
    request.sort = sort;
    request.top_k = TopK::new(1).unwrap();
    let mut after: Option<TypedCursor> = None;
    let mut seen: Vec<String> = Vec::new();
    for _ in 0..10 {
        request.after = after.clone();
        let response = typed_search(&snapshot, &request);
        seen.extend(hit_keys(&response));
        after = response.next_cursor;
        if after.is_none() {
            break;
        }
    }
    assert_eq!(seen, ["a", "b", "c", "d"]);
}

// J12 — JSON predicates compose with typed numerics, time, IP and geo.
#[test]
fn j12_json_composes_with_typed_predicates() {
    let mut a = json_doc("a", obj(vec![("n", num(5))]));
    set(&mut a, "score", FieldValue::F64(1.0));
    set(&mut a, "ip", FieldValue::Ip("192.0.2.1".parse().unwrap()));
    set(
        &mut a,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(10)),
    );
    let mut b = json_doc("b", obj(vec![("n", num(5))]));
    set(&mut b, "score", FieldValue::F64(2.0));
    set(&mut b, "ip", FieldValue::Ip("192.0.2.2".parse().unwrap()));
    set(
        &mut b,
        "ts",
        FieldValue::Timestamp(Timestamp::from_micros(10)),
    );
    let index = committed(vec![a, b]);
    let query = Query::And(vec![
        range(
            "body",
            "$.n",
            Bound::Included(FieldValue::I64(5)),
            Bound::Included(FieldValue::I64(5)),
        ),
        Query::Range {
            field: "score".into(),
            lower: Bound::Included(FieldValue::F64(1.5)),
            upper: Bound::Unbounded,
        },
        Query::IpInCidr {
            field: "ip".into(),
            network: IpNetwork::new("192.0.2.0".parse().unwrap(), 24).unwrap(),
        },
        Query::TimeRange {
            field: "ts".into(),
            start: Timestamp::from_micros(0),
            end: Timestamp::from_micros(20),
        },
    ]);
    assert_eq!(search_json(&index, query), ["b"]);
}

// J13 — cancellation is observed for JSON scans.
#[test]
fn j13_cancellation() {
    let index = committed(vec![json_doc("a", obj(vec![("n", num(1))]))]);
    let snapshot = index.snapshot();
    let cancel = CancellationFlag::new();
    cancel.cancel();
    let result = TypedSearcher::new(&snapshot, &schema(), SearchLimits::default()).search(
        &request(Query::MatchAll),
        &Budgets::new(),
        &cancel,
    );
    assert!(matches!(result, Err(SearchError::Cancelled)));
}
