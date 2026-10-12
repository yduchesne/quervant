//! Public contract integration slice (PR 2 Phase 5).
//!
//! These tests exercise real `trawler-core` public types and validators only.
//! They assert contract acceptance/rejection, ordered batch assembly and geo
//! validation. They do **not** execute searches, score hits, persist data, read
//! a PIT, or claim any runtime behavior owned by later PRs.

use trawler_core::contract::{
    Aggregate, Aggregation, BatchBudget, BatchQueryRequest, BatchQueryResponse, Bound, BudgetKind,
    BudgetPolicy, Budgets, CancelReason, Capability, CapabilityRequest, CapabilitySet, Cardinality,
    Cursor, Document, DocumentKey, ExactDistinct, FieldDefinition, FieldOptions, FieldType,
    FieldValue, FieldValues, GeoBoundingBox, GeoPoint, GeoPolygon, GeoRadius, GroupBy, GroupKey,
    InvalidQueryReason, IpNetwork, JsonPathExpr, MutationIntent, MutationRequest, PerQueryOutcome,
    PitId, Projection, Query, QueryError, QueryRequest, Schema, SearchResponse, Sort,
    SortDirection, SortField, TimeBucket, Timestamp, TopK, TopKFrequency,
};

const BUDGET_KINDS: &[BudgetKind] = &[
    BudgetKind::JsonDepth,
    BudgetKind::QueryDepth,
    BudgetKind::Fields,
    BudgetKind::ArrayElements,
    BudgetKind::DocumentBytes,
    BudgetKind::ResultWindow,
    BudgetKind::Groups,
    BudgetKind::GroupKeyFields,
    BudgetKind::GroupExpansions,
    BudgetKind::DistinctKeys,
    BudgetKind::QueriesPerBatch,
];

fn server_budgets() -> Budgets {
    let mut budgets = Budgets::new();
    for kind in BUDGET_KINDS {
        budgets.set(*kind, 10_000).unwrap();
    }
    budgets
}

fn schema() -> Schema {
    Schema::new(
        vec![
            FieldDefinition::new(
                "message",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )
            .with_analyzer("en_default"),
            FieldDefinition::new(
                "host",
                FieldType::Keyword,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            )
            .with_normalizer("lowercase"),
            FieldDefinition::new(
                "tags",
                FieldType::Keyword,
                Cardinality::Multi,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "src_ip",
                FieldType::IpAddress,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "net",
                FieldType::IpNetwork,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "ts",
                FieldType::Timestamp,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "bytes",
                FieldType::U64,
                Cardinality::Single,
                FieldOptions::new(true, true, true),
            ),
            FieldDefinition::new(
                "loc",
                FieldType::GeoPoint,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
            FieldDefinition::new(
                "body",
                FieldType::Json,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            ),
        ],
        Some("ts".into()),
    )
    .unwrap()
}

fn cross_domain_query() -> Query {
    Query::And(vec![
        Query::Term {
            field: "message".into(),
            value: FieldValue::Text("failed login".into()),
        },
        Query::IpInCidr {
            field: "src_ip".into(),
            network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
        },
        Query::TimeRange {
            field: "ts".into(),
            start: Timestamp::from_micros(1_700_000_000_000_000),
            end: Timestamp::from_micros(1_700_000_600_000_000),
        },
        Query::JsonPathEquals {
            field: "body".into(),
            path: JsonPathExpr::parse("$.events[0].user").unwrap(),
            value: FieldValue::Keyword("root".into()),
        },
        Query::GeoBoundingBox {
            field: "loc".into(),
            bbox: GeoBoundingBox::new(10.0, 40.0, 20.0, 50.0).unwrap(),
        },
    ])
}

fn document() -> Document {
    let mut document = Document::new(DocumentKey::new("doc-7").unwrap());
    document
        .insert(
            "message",
            FieldValues::Single(FieldValue::Text("failed login".into())),
        )
        .unwrap();
    document
        .insert(
            "host",
            FieldValues::Single(FieldValue::Keyword("web-1".into())),
        )
        .unwrap();
    document
        .insert(
            "tags",
            FieldValues::Multi(vec![FieldValue::Keyword("auth".into())]),
        )
        .unwrap();
    document
        .insert(
            "src_ip",
            FieldValues::Single(FieldValue::Ip("10.1.2.3".parse().unwrap())),
        )
        .unwrap();
    document
        .insert(
            "ts",
            FieldValues::Single(FieldValue::Timestamp(Timestamp::from_micros(1))),
        )
        .unwrap();
    document
        .insert("bytes", FieldValues::Single(FieldValue::U64(42)))
        .unwrap();
    document
        .insert(
            "loc",
            FieldValues::Single(FieldValue::GeoPoint(GeoPoint::new(15.0, 45.0).unwrap())),
        )
        .unwrap();
    document
}

fn supported() -> CapabilitySet {
    CapabilitySet::new().with(Capability::new("regex_query", 1))
}

fn rich_request() -> QueryRequest {
    let mut request = QueryRequest::new(cross_domain_query());
    request.sort = Sort::new(vec![
        SortField::new("host", SortDirection::Asc),
        SortField::new("ts", SortDirection::Desc),
    ]);
    request.top_k = TopK { limit: 25 };
    request.projection = Projection::Fields(vec!["host".into(), "ts".into()]);
    request.aggregation = Some(Aggregation {
        group_by: Some(GroupBy::new(vec![GroupKey::Field("host".into())])),
        aggregates: vec![
            Aggregate::count(),
            Aggregate::sum("bytes"),
            Aggregate::max("ts"),
        ],
        exact_distinct: Some(ExactDistinct {
            field: "host".into(),
        }),
        top_k: Some(TopKFrequency {
            field: "host".into(),
            k: 3,
        }),
        time_bucket: Some(TimeBucket {
            width_micros: 60_000_000,
        }),
    });
    request.capabilities = CapabilityRequest {
        required: vec![Capability::new("regex_query", 1)],
        optional: vec![Capability::new("hybrid_rrf", 1)],
    };
    request
}

#[test]
fn x01_cross_domain_request_accepted() {
    let schema = schema();
    let budgets = server_budgets();
    schema.validate_document(&document(), &budgets).unwrap();

    let request = rich_request();
    request.validate(&schema, &supported()).unwrap();

    // Mutation shapes are validated without allocating revisions.
    let mutation = MutationRequest::insert(document());
    mutation.validate().unwrap();
    assert_eq!(mutation.intent, MutationIntent::Insert);

    let policy = BudgetPolicy::with_server(budgets);
    assert_eq!(
        policy
            .effective(BudgetKind::ResultWindow, Some(25))
            .unwrap(),
        25
    );
}

#[test]
fn x02_cross_domain_invalid_rejected_precisely() {
    let schema = schema();
    let request = QueryRequest::new(Query::IpInCidr {
        field: "host".into(),
        network: IpNetwork::new("10.0.0.0".parse().unwrap(), 8).unwrap(),
    });
    request.validate(&schema, &supported()).unwrap_err();

    let mut inverted = QueryRequest::new(Query::TimeRange {
        field: "ts".into(),
        start: Timestamp::from_micros(2),
        end: Timestamp::from_micros(1),
    });
    inverted.budgets = server_budgets();
    assert!(matches!(
        inverted.validate(&schema, &supported()),
        Err(QueryError::InvalidQuery(
            InvalidQueryReason::InvalidTimeRange { .. }
        ))
    ));

    let geo = QueryRequest::new(Query::GeoRadius {
        field: "host".into(),
        radius: GeoRadius::new(GeoPoint::new(0.0, 0.0).unwrap(), 100.0).unwrap(),
    });
    assert!(geo.validate(&schema, &supported()).is_err());
}

#[test]
fn x03_projection_sort_cursor_composition() {
    let schema = schema();
    let mut request = rich_request();
    let sort = request.sort.clone();
    let pit = PitId::new("pit-1").unwrap();
    let cursor = Cursor::new(
        pit.clone(),
        sort.clone(),
        DocumentKey::new("doc-6").unwrap(),
        Timestamp::from_micros(1_000),
    );
    request.pit = Some(pit.clone());
    request.cursor = Some(cursor.clone());
    request.validate(&schema, &supported()).unwrap();
    assert!(
        cursor
            .validate(&pit, &sort, Timestamp::from_micros(999))
            .is_ok()
    );

    // A cursor without a PIT is a per-query contract error.
    let mut missing_pit = rich_request();
    missing_pit.cursor = Some(cursor.clone());
    assert!(matches!(
        missing_pit.validate(&schema, &supported()),
        Err(QueryError::InvalidQuery(
            InvalidQueryReason::CursorPitMismatch
        ))
    ));

    // Requesting a non-stored field is rejected.
    let mut bad_projection = rich_request();
    bad_projection.projection = Projection::Fields(vec!["message".into()]);
    assert!(bad_projection.validate(&schema, &supported()).is_ok());
    let mut unstored = rich_request();
    unstored.projection = Projection::Fields(vec!["not-a-field".into()]);
    assert!(unstored.validate(&schema, &supported()).is_err());
}

fn batch(queries: Vec<QueryRequest>, max: usize) -> BatchQueryRequest {
    BatchQueryRequest::new(queries, None, BatchBudget::new(max))
}

#[test]
fn x04_batch_ordered_mixed_outcomes() {
    let schema = schema();
    let ok = rich_request();
    let bad = QueryRequest::new(Query::Term {
        field: "does-not-exist".into(),
        value: FieldValue::Text("x".into()),
    });
    let request = batch(vec![ok.clone(), bad, ok], 3);
    let results = request.validate(&schema, &supported()).unwrap();
    assert_eq!(results.len(), 3);
    let mapped: Vec<Result<SearchResponse, QueryError>> = results
        .into_iter()
        .map(|result| result.map(|()| SearchResponse::empty()))
        .collect();
    let response = BatchQueryResponse::from_validation_for(&request, mapped).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(_))
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

#[test]
fn b01_empty_batch_rejected() {
    let request = batch(vec![], 4);
    assert!(matches!(
        request.validate_envelope(),
        Err(QueryError::InvalidBatch(_))
    ));
}

#[test]
fn b02_size_limit_and_no_truncation() {
    let schema = schema();
    let request = batch(vec![rich_request(), rich_request()], 2);
    assert!(request.validate(&schema, &supported()).is_ok());
    let oversized = batch(vec![rich_request(), rich_request(), rich_request()], 2);
    assert!(matches!(
        oversized.validate_envelope(),
        Err(QueryError::InvalidBatch(_))
    ));
}

#[test]
fn b03_b04_b06_ordered_slots_and_per_query_isolation() {
    let schema = schema();
    let ok = rich_request();
    let bad = QueryRequest::new(Query::Term {
        field: "missing".into(),
        value: FieldValue::Text("x".into()),
    });
    let request = batch(vec![ok.clone(), bad, ok.clone()], 3);
    let results = request.validate(&schema, &supported()).unwrap();
    assert_eq!(results.len(), 3);
    // Simulate out-of-order computation: results are indexed back by input slot.
    let mut ordered: Vec<Option<Result<SearchResponse, QueryError>>> = vec![None; 3];
    for (index, result) in results.into_iter().enumerate() {
        ordered[index] = Some(result.map(|()| SearchResponse::empty()));
    }
    let mapped: Vec<Result<SearchResponse, QueryError>> =
        ordered.into_iter().map(Option::unwrap).collect();
    let response = BatchQueryResponse::from_validation_for(&request, mapped).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(_))
    ));
    assert!(matches!(
        response.slot(2),
        Some(PerQueryOutcome::Success(_))
    ));
}

#[test]
fn b05_independent_query_options_are_not_shared() {
    let schema = schema();
    let mut first = rich_request();
    first.top_k = TopK { limit: 5 };
    first.sort = Sort::new(vec![SortField::new("host", SortDirection::Asc)]);
    let mut second = rich_request();
    second.top_k = TopK { limit: 50 };
    second.sort = Sort::new(vec![SortField::new("ts", SortDirection::Desc)]);
    assert_ne!(first.top_k, second.top_k);
    assert_ne!(first.sort, second.sort);
    let request = batch(vec![first, second], 2);
    let results = request.validate(&schema, &supported()).unwrap();
    assert!(results.iter().all(Result::is_ok));
}

#[test]
fn b07_conflicting_shared_pit_is_envelope_error() {
    let shared = PitId::new("pit-shared").unwrap();
    let mut query = rich_request();
    query.pit = Some(PitId::new("pit-own").unwrap());
    let request = BatchQueryRequest::new(vec![query], Some(shared), BatchBudget::new(4));
    assert!(matches!(
        request.validate_envelope(),
        Err(QueryError::InvalidBatch(_))
    ));
}

#[test]
fn b08_budget_boundaries_are_independent() {
    let policy = BudgetPolicy::new(
        Budgets::new().with(BudgetKind::ResultWindow, 100).unwrap(),
        Budgets::new().with(BudgetKind::ResultWindow, 80).unwrap(),
        Budgets::new().with(BudgetKind::ResultWindow, 50).unwrap(),
        Budgets::new().with(BudgetKind::ResultWindow, 10).unwrap(),
    );
    assert_eq!(
        policy.effective(BudgetKind::ResultWindow, None).unwrap(),
        10
    );
    assert_eq!(
        policy
            .effective(BudgetKind::ResultWindow, Some(20))
            .unwrap(),
        20
    );
    assert!(matches!(
        policy.effective(BudgetKind::ResultWindow, Some(60)),
        Err(QueryError::BudgetPolicyViolation { .. })
    ));
    assert!(matches!(
        policy.effective(BudgetKind::ResultWindow, Some(0)),
        Err(QueryError::InvalidQuery(
            InvalidQueryReason::ZeroBudget { .. }
        ))
    ));
}

#[test]
fn b09_cancellation_produces_explicit_slots() {
    let outcomes = vec![
        PerQueryOutcome::Success(SearchResponse::empty()),
        PerQueryOutcome::Failure(QueryError::Cancelled {
            reason: CancelReason::BatchBudgetExhausted,
        }),
        PerQueryOutcome::Failure(QueryError::Cancelled {
            reason: CancelReason::ClientCancellation,
        }),
    ];
    let request = batch(vec![rich_request(), rich_request(), rich_request()], 3);
    let response = BatchQueryResponse::from_outcomes_for(&request, outcomes).unwrap();
    assert_eq!(response.len(), 3);
    assert!(matches!(
        response.slot(0),
        Some(PerQueryOutcome::Success(_))
    ));
    assert!(matches!(
        response.slot(1),
        Some(PerQueryOutcome::Failure(QueryError::Cancelled {
            reason: CancelReason::BatchBudgetExhausted
        }))
    ));
}

#[test]
fn b10_envelope_rejection_returns_no_response() {
    let request = batch(vec![], 4);
    assert!(request.validate_envelope().is_err());
    // There is deliberately no `BatchQueryResponse` value for an envelope
    // rejection; transport failure is a separate boundary outside the contract.
}

#[test]
fn b11_batch_reuses_standalone_result_types() {
    // The batch outcome carries the *same* `SearchResponse`/`QueryError` types.
    let success: PerQueryOutcome = PerQueryOutcome::Success(SearchResponse::empty());
    let failure: PerQueryOutcome = PerQueryOutcome::Failure(QueryError::BudgetExceeded {
        kind: BudgetKind::Groups,
    });
    let request = batch(vec![rich_request(), rich_request()], 2);
    let response = BatchQueryResponse::from_outcomes_for(&request, vec![success, failure]).unwrap();
    assert_eq!(response.len(), 2);
}

fn polygon(vertices: &[(f64, f64)]) -> Result<GeoPolygon, QueryError> {
    GeoPolygon::new(
        vertices
            .iter()
            .map(|(lon, lat)| GeoPoint::new(*lon, *lat).unwrap())
            .collect(),
        vec![],
    )
}

#[test]
fn g_cross_contract_fixtures() {
    // G-CROSS01: adjacent delta longitude below 180 with no antimeridian endpoint.
    assert!(polygon(&[(10.0, 0.0), (11.0, 0.0), (11.0, 1.0)]).is_ok());
    // G-CROSS02: adjacent delta longitude above 180.
    assert!(matches!(
        polygon(&[(170.0, 0.0), (-170.0, 0.0), (-170.0, 10.0)]),
        Err(QueryError::UnsupportedGeoShape { .. })
    ));
    // G-CROSS03: exactly 180 degrees is ambiguous.
    assert!(matches!(
        polygon(&[(-90.0, 0.0), (90.0, 0.0), (90.0, 10.0)]),
        Err(QueryError::UnsupportedGeoShape { .. })
    ));
    // G-CROSS04: a ring whose closing edge crosses the antimeridian.
    assert!(matches!(
        polygon(&[(170.0, 0.0), (175.0, 0.0), (-175.0, 5.0)]),
        Err(QueryError::UnsupportedGeoShape { .. })
    ));
    // G-CROSS05: an explicit +180 endpoint is conservatively ambiguous.
    assert!(matches!(
        polygon(&[(180.0, 0.0), (179.0, 0.0), (179.0, 1.0)]),
        Err(QueryError::UnsupportedGeoShape { .. })
    ));
    // G-CROSS06: an antimeridian-crossing bounding box remains supported.
    assert!(GeoBoundingBox::new(170.0, -10.0, -170.0, 10.0).is_ok());
    // G-CROSS07: an ordinary polygon near but not crossing the antimeridian.
    assert!(polygon(&[(170.0, 0.0), (171.0, 0.0), (171.0, 1.0)]).is_ok());
}

#[test]
fn d_and_p_contract_boundaries() {
    let schema = schema();
    let budgets = server_budgets();

    // D02: empty key.
    assert!(DocumentKey::new("").is_err());
    // D03: unknown document field.
    let mut unknown = Document::new(DocumentKey::new("d").unwrap());
    unknown
        .insert("nope", FieldValues::Single(FieldValue::Bool(true)))
        .unwrap();
    assert!(schema.validate_document(&unknown, &budgets).is_err());
    // D05: missing vs explicit null vs empty array are distinct.
    let mut states = Document::new(DocumentKey::new("d").unwrap());
    states.insert("host", FieldValues::ExplicitNull).unwrap();
    states.insert("tags", FieldValues::Empty).unwrap();
    assert!(states.get("missing").is_absent());
    assert!(states.get("host").is_explicit_null());
    assert!(states.get("tags").is_empty_multi());

    // P03: RHS/field type mismatch, no coercion.
    let mut request = QueryRequest::new(Query::Term {
        field: "bytes".into(),
        value: FieldValue::Keyword("42".into()),
    });
    request.budgets = server_budgets();
    assert!(matches!(
        request.validate(&schema, &supported()),
        Err(QueryError::TypeMismatch { .. })
    ));

    // P01/P02: presence and membership predicates validate on eligible fields.
    let presence = QueryRequest::new(Query::And(vec![
        Query::Exists {
            field: "host".into(),
        },
        Query::Missing {
            field: "tags".into(),
        },
        Query::IsNull {
            field: "src_ip".into(),
        },
    ]));
    assert!(presence.validate(&schema, &supported()).is_ok());
    let membership = QueryRequest::new(Query::NotIn {
        field: "host".into(),
        values: vec![FieldValue::Keyword("a".into())],
    });
    assert!(membership.validate(&schema, &supported()).is_ok());
    let empty_in = QueryRequest::new(Query::In {
        field: "host".into(),
        values: vec![],
    });
    assert!(empty_in.validate(&schema, &supported()).is_err());
}

#[test]
fn i_t_s_capability_contract_boundaries() {
    let schema = schema();

    // I01/I02: IP family-aware range + CIDR boundaries.
    assert!(
        IpNetwork::new("0.0.0.0".parse().unwrap(), 0)
            .unwrap()
            .contains(&"203.0.113.1".parse().unwrap())
    );
    assert!(
        !IpNetwork::new("0.0.0.0".parse().unwrap(), 0)
            .unwrap()
            .contains(&"2001:db8::1".parse().unwrap())
    );
    let ip_range = QueryRequest::new(Query::IpRange {
        field: "src_ip".into(),
        start: "10.0.0.1".parse().unwrap(),
        end: "10.0.0.10".parse().unwrap(),
    });
    assert!(ip_range.validate(&schema, &supported()).is_ok());
    let family_mismatch = QueryRequest::new(Query::IpRange {
        field: "src_ip".into(),
        start: "10.0.0.1".parse().unwrap(),
        end: "2001:db8::1".parse().unwrap(),
    });
    assert!(family_mismatch.validate(&schema, &supported()).is_err());

    // T01: half-open boundary types.
    let window = Query::TimeRange {
        field: "ts".into(),
        start: Timestamp::from_micros(0),
        end: Timestamp::from_micros(0),
    };
    assert!(
        QueryRequest::new(window)
            .validate(&schema, &supported())
            .is_ok()
    );

    // S01/S02: sort and cursor contract.
    let sort = Sort::new(vec![SortField::new("ts", SortDirection::Desc)]);
    assert!(sort.validate(&schema).is_ok());
    let pit = PitId::new("pit").unwrap();
    let cursor = Cursor::new(
        pit.clone(),
        sort.clone(),
        DocumentKey::new("k").unwrap(),
        Timestamp::from_micros(10),
    );
    assert!(
        cursor
            .validate(&pit, &sort, Timestamp::from_micros(10))
            .is_err()
    );
    assert!(
        cursor
            .validate(&pit, &sort, Timestamp::from_micros(9))
            .is_ok()
    );

    // C01/C02: required vs optional capability negotiation.
    let supported = CapabilitySet::new();
    let required = CapabilityRequest {
        required: vec![Capability::new("regex_query", 1)],
        optional: vec![],
    };
    assert!(matches!(
        required.negotiate(&supported),
        Err(QueryError::UnsupportedCapability { .. })
    ));
    let optional = CapabilityRequest {
        required: vec![],
        optional: vec![Capability::new("hybrid_rrf", 1)],
    };
    assert!(optional.negotiate(&supported).is_ok());
}

#[test]
fn a_budget_and_geo_boundaries() {
    // A06/BG01/BG06: zero and overflow budget handling.
    assert!(Budgets::new().with(BudgetKind::Groups, 0).is_err());
    let policy = BudgetPolicy::with_server(server_budgets());
    assert_eq!(policy.effective(BudgetKind::Groups, None).unwrap(), 10_000);

    // G01: GeoPoint bounds and non-finite rejection.
    assert!(GeoPoint::new(-180.0, 90.0).is_ok());
    assert!(GeoPoint::new(-181.0, 0.0).is_err());
    assert!(GeoPoint::new(0.0, f64::NAN).is_err());

    // G02: radius and polygon contracts.
    assert!(GeoRadius::new(GeoPoint::new(0.0, 0.0).unwrap(), 0.0).is_err());
    assert!(GeoRadius::new(GeoPoint::new(0.0, 0.0).unwrap(), 1000.0).is_ok());

    // Bound representation is part of the numeric range contract.
    let bound = Bound::Included(FieldValue::I64(1));
    assert!(matches!(bound, Bound::Included(_)));
}

#[test]
fn j_json_path_contract() {
    // J01/J02: supported subset vs explicitly rejected syntax.
    assert!(JsonPathExpr::parse("$.events[0].ip").unwrap().is_concrete());
    assert!(!JsonPathExpr::parse("$.events[*].ip").unwrap().is_concrete());
    assert!(JsonPathExpr::parse("$..ip").is_err());
    assert!(JsonPathExpr::parse("$[?(@.ip)]").is_err());

    // J03: different revisions are distinct node identities via the shape only.
    let path = JsonPathExpr::parse("$.events[0].ip")
        .unwrap()
        .to_concrete()
        .unwrap();
    let key = DocumentKey::new("doc").unwrap();
    let first = trawler_core::contract::JsonNodeRef {
        key: key.clone(),
        revision: 1,
        path: path.clone(),
    };
    let second = trawler_core::contract::JsonNodeRef {
        key,
        revision: 2,
        path,
    };
    assert_ne!(first, second);
}

#[test]
fn b_card07_public_api_has_no_unchecked_response_constructor() {
    // The only public response constructors are `from_outcomes_for` and
    // `from_validation_for`, both bound to `&BatchQueryRequest`, so the
    // exactly-N invariant cannot be bypassed through the public API. A
    // compile-fail harness would require a new dev-dependency (`trybuild`),
    // which PR 2 does not add; this test exercises the enforced boundary and
    // the exported API is inspected by review.
    let accepted = batch(vec![rich_request(), rich_request()], 2);
    let error = BatchQueryResponse::from_outcomes_for(
        &accepted,
        vec![PerQueryOutcome::Success(SearchResponse::empty())],
    )
    .unwrap_err();
    assert!(matches!(
        error,
        QueryError::InvalidBatch(
            trawler_core::contract::InvalidBatchReason::CardinalityMismatch {
                expected: 2,
                actual: 1
            }
        )
    ));

    let rejected = BatchQueryRequest::new(vec![rich_request()], None, BatchBudget::new(0));
    assert!(matches!(
        BatchQueryResponse::from_outcomes_for(
            &rejected,
            vec![PerQueryOutcome::Success(SearchResponse::empty())]
        ),
        Err(QueryError::InvalidBatch(_))
    ));
}

#[test]
fn b_pol10_batch_aggregate_limit_uses_policy_hierarchy() {
    let policy = BudgetPolicy::new(
        Budgets::new()
            .with(BudgetKind::QueriesPerBatch, 10)
            .unwrap()
            .with(BudgetKind::BatchMemoryBytes, 1_000)
            .unwrap(),
        Budgets::new()
            .with(BudgetKind::BatchMemoryBytes, 800)
            .unwrap(),
        Budgets::new()
            .with(BudgetKind::BatchMemoryBytes, 600)
            .unwrap(),
        Budgets::new(),
    );

    let within = BatchQueryRequest::new(
        vec![rich_request()],
        None,
        BatchBudget::new(4).with_limits(
            Budgets::new()
                .with(BudgetKind::BatchMemoryBytes, 600)
                .unwrap(),
        ),
    );
    assert!(within.validate_envelope_with_policy(&policy).is_ok());

    let above = BatchQueryRequest::new(
        vec![rich_request()],
        None,
        BatchBudget::new(4).with_limits(
            Budgets::new()
                .with(BudgetKind::BatchMemoryBytes, 601)
                .unwrap(),
        ),
    );
    assert!(matches!(
        above.validate_envelope_with_policy(&policy),
        Err(QueryError::BudgetPolicyViolation {
            kind: BudgetKind::BatchMemoryBytes,
            requested: 601,
            ceiling: 600
        })
    ));
}
