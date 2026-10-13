//! PR 5 corrective pass 03: manifest preallocation budget enforcement (C7-*).
//!
//! The expected charge is computed independently from fixture inputs using the
//! documented model; production `retained_bytes()` is compared as a second
//! assertion, not used to derive expectations. Stage-prefix tests assert the
//! `LimitExceeded.requested` cumulative charge at the exact reservation stage.

use trawler_core::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use trawler_core::contract::schema::Schema;
use trawler_core::segment::format::{ByteWriter, ContainerBuilder, ContainerKind, SectionKind};
use trawler_core::segment::manifest::{Manifest, ManifestSegmentRef};
use trawler_core::segment::{CodecSchema, SegmentError, SegmentLimits};

const DUPLICATE_INDEX_BYTES: u64 = std::mem::size_of::<String>() as u64 + 32;

fn empty_schema() -> CodecSchema {
    let schema = Schema::new(Vec::new(), None).unwrap();
    let bindings = SchemaAnalyzerBindings::resolve(&schema, &AnalyzerRegistry::builtin()).unwrap();
    CodecSchema::from_contract(&schema, &bindings).unwrap()
}

fn reference(id: &str, key: &str, required: usize, optional: usize) -> ManifestSegmentRef {
    ManifestSegmentRef {
        segment_id: id.to_owned(),
        object_key: key.to_owned(),
        content_algorithm: 0,
        content_length: 10,
        content_digest: [7u8; 32],
        time_bounds: None,
        required_features: (0..required)
            .map(|i| (u16::try_from(i + 1).unwrap(), 1))
            .collect(),
        optional_features: (0..optional)
            .map(|i| (u16::try_from(i + 100).unwrap(), 1))
            .collect(),
    }
}

fn manifest_with(
    segments: Vec<ManifestSegmentRef>,
    manifest_required: usize,
    manifest_optional: usize,
) -> Manifest {
    Manifest {
        schema: empty_schema(),
        segments,
        required_features: (0..manifest_required)
            .map(|i| (u16::try_from(i + 1).unwrap(), 1))
            .collect(),
        optional_features: (0..manifest_optional)
            .map(|i| (u16::try_from(i + 100).unwrap(), 1))
            .collect(),
    }
}

/// Ordered modeled charge components, computed from fixture inputs only.
fn charge_components(manifest: &Manifest) -> Vec<(&'static str, u64)> {
    let mut components = Vec::new();
    components.push((
        "segment_vector",
        (manifest.segments.len() as u64)
            .checked_mul(std::mem::size_of::<ManifestSegmentRef>() as u64)
            .unwrap(),
    ));
    for reference in &manifest.segments {
        components.push(("segment_id", reference.segment_id.len() as u64));
        components.push((
            "object_key",
            (reference.object_key.len() as u64) * 2 + DUPLICATE_INDEX_BYTES,
        ));
        components.push((
            "required_features",
            reference.required_features.len() as u64 * std::mem::size_of::<(u16, u16)>() as u64,
        ));
        components.push((
            "optional_features",
            reference.optional_features.len() as u64 * std::mem::size_of::<(u16, u16)>() as u64,
        ));
    }
    components.push((
        "manifest_required_features",
        manifest.required_features.len() as u64 * std::mem::size_of::<(u16, u16)>() as u64,
    ));
    components.push((
        "manifest_optional_features",
        manifest.optional_features.len() as u64 * std::mem::size_of::<(u16, u16)>() as u64,
    ));
    components
}

fn oracle_charge(manifest: &Manifest) -> u64 {
    charge_components(manifest)
        .iter()
        .map(|(_, charge)| *charge)
        .sum()
}

fn decode_with_budget(bytes: &[u8], budget: u64) -> Result<Manifest, SegmentError> {
    Manifest::decode(
        bytes,
        &SegmentLimits::default().with_max_section_decode_bytes(budget),
    )
}

#[test]
fn c7_u01_empty_manifest_zero_segment_charge() {
    let manifest = manifest_with(vec![], 0, 0);
    assert_eq!(oracle_charge(&manifest), 0);
    let bytes = manifest.encode().unwrap();
    assert_eq!(decode_with_budget(&bytes, 0).unwrap(), manifest);
    assert_eq!(manifest.retained_bytes().unwrap(), 0);
}

#[test]
fn c7_u17_independent_oracle_and_round_trip() {
    let manifest = manifest_with(
        vec![
            reference("segments/alpha", "objects/alpha", 2, 1),
            reference("segments/beta", "objects/beta", 0, 3),
            reference("segments/gamma", "objects/gamma", 1, 0),
        ],
        2,
        1,
    );
    let oracle = oracle_charge(&manifest);
    assert_eq!(manifest.retained_bytes().unwrap(), oracle);
    let bytes = manifest.encode().unwrap();
    let decoded = decode_with_budget(&bytes, oracle).unwrap();
    assert_eq!(decoded, manifest);
    assert_eq!(decoded.retained_bytes().unwrap(), oracle);
}

#[test]
fn c7_u02_exact_full_model_and_one_below() {
    let manifest = manifest_with(
        vec![
            reference("segments/alpha", "objects/alpha", 1, 1),
            reference("segments/beta", "objects/beta", 1, 1),
        ],
        1,
        1,
    );
    let full = oracle_charge(&manifest);
    let bytes = manifest.encode().unwrap();
    assert!(decode_with_budget(&bytes, full).is_ok());
    match decode_with_budget(&bytes, full - 1) {
        Err(SegmentError::LimitExceeded { requested, .. }) => assert_eq!(requested, full),
        other => panic!("expected LimitExceeded at {full}, got {other:?}"),
    }
}

#[test]
fn c7_stage_prefixes_reserve_before_allocating() {
    // A diverse manifest exercises every charged stage in order.
    let manifest = manifest_with(
        vec![
            reference("segments/alpha", "objects/alpha", 2, 1),
            reference("segments/beta", "objects/beta", 1, 2),
        ],
        2,
        1,
    );
    let bytes = manifest.encode().unwrap();
    let components = charge_components(&manifest);
    let mut cumulative = 0u64;
    for (stage, charge) in &components {
        cumulative += *charge;
        if cumulative == 0 {
            continue;
        }
        // A budget one below this stage's cumulative prefix must fail at this
        // stage with `requested == cumulative` (proving the preallocation
        // reservation is what rejects, not a later allocation).
        match decode_with_budget(&bytes, cumulative - 1) {
            Err(SegmentError::LimitExceeded { requested, .. }) => {
                assert_eq!(requested, cumulative, "stage {stage}");
            }
            other => panic!("stage {stage}: expected LimitExceeded, got {other:?}"),
        }
    }
}

#[test]
fn c7_i05_failed_then_valid_decode_is_independent() {
    let manifest = manifest_with(
        vec![reference("segments/alpha", "objects/alpha", 1, 0)],
        0,
        0,
    );
    let full = oracle_charge(&manifest);
    let bytes = manifest.encode().unwrap();
    assert!(matches!(
        decode_with_budget(&bytes, full - 1),
        Err(SegmentError::LimitExceeded { .. })
    ));
    // No externally visible partial state: a subsequent decode succeeds.
    assert_eq!(decode_with_budget(&bytes, full).unwrap(), manifest);
}

// --- crafted malformed payloads ---------------------------------------------

type FeatureList<'a> = &'a [(u16, u16)];
type RefSpec<'a> = (&'a str, &'a str, FeatureList<'a>, FeatureList<'a>);

fn payload(schema_bytes: &[u8], refs: &[RefSpec<'_>]) -> Vec<u8> {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(schema_bytes.len() as u32);
    writer.bytes(schema_bytes);
    writer.u32(u32::try_from(refs.len()).unwrap());
    for (id, key, required, optional) in refs {
        writer.len_prefixed_u16(id.as_bytes()).unwrap();
        writer.len_prefixed_u16(key.as_bytes()).unwrap();
        writer.u8(0);
        writer.u64(10);
        writer.bytes(&[7u8; 32]);
        writer.u8(0);
        writer.u32(u32::try_from(required.len()).unwrap());
        for (fid, fver) in *required {
            writer.u16(*fid);
            writer.u16(*fver);
        }
        writer.u32(u32::try_from(optional.len()).unwrap());
        for (fid, fver) in *optional {
            writer.u16(*fid);
            writer.u16(*fver);
        }
    }
    writer.u32(0);
    writer.u32(0);
    writer.into_vec()
}

fn container(body: Vec<u8>) -> Vec<u8> {
    let mut builder = ContainerBuilder::new(ContainerKind::Manifest, 0);
    builder.section(SectionKind::Manifest, 0, 0, body);
    builder.build().unwrap()
}

#[test]
fn c7_u15_nonadjacent_duplicate_keys_rejected() {
    let schema = empty_schema().encode().unwrap();
    let bytes = container(payload(
        &schema,
        &[
            ("segments/a", "objects/a", &[], &[]),
            ("segments/b", "objects/b", &[], &[]),
            ("segments/c", "objects/a", &[], &[]),
        ],
    ));
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::InvalidManifest { .. })
    ));
}

#[test]
fn c7_u16_unordered_ids_rejected() {
    let schema = empty_schema().encode().unwrap();
    let bytes = container(payload(
        &schema,
        &[
            ("segments/b", "objects/b", &[], &[]),
            ("segments/a", "objects/a", &[], &[]),
        ],
    ));
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::InvalidManifest { .. })
    ));
}

#[test]
fn c7_u18_invalid_utf8_rejected() {
    let schema = empty_schema().encode().unwrap();
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(schema.len() as u32);
    writer.bytes(&schema);
    writer.u32(1);
    writer.u16(2);
    writer.u8(0xff);
    writer.u8(0xfe);
    let bytes = container(writer.into_vec());
    assert!(Manifest::decode(&bytes, &SegmentLimits::default()).is_err());
}

#[test]
fn c7_u19_truncated_rejected() {
    let manifest = manifest_with(vec![reference("segments/a", "objects/a", 1, 1)], 1, 1);
    let bytes = manifest.encode().unwrap();
    assert!(Manifest::decode(&bytes[..bytes.len() / 2], &SegmentLimits::default()).is_err());
}

#[test]
fn c7_u20_unknown_required_and_unsorted_features() {
    let manifest = manifest_with(vec![reference("segments/a", "objects/a", 0, 0)], 0, 0);
    let schema = empty_schema().encode().unwrap();
    let bytes = container(payload(
        &schema,
        &[("segments/a", "objects/a", &[(0xbeef, 1)], &[])],
    ));
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::UnsupportedFeature { .. })
    ));
    let _ = manifest;

    let bytes = container(payload(
        &schema,
        &[("segments/a", "objects/a", &[(2, 1), (1, 1)], &[])],
    ));
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::InvalidManifest { .. })
    ));
}

#[test]
fn c7_u21_large_count_rejected_before_alloc() {
    let schema = empty_schema().encode().unwrap();
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(schema.len() as u32);
    writer.bytes(&schema);
    writer.u32(u32::MAX);
    let bytes = container(writer.into_vec());
    assert!(matches!(
        Manifest::decode(&bytes, &SegmentLimits::default()),
        Err(SegmentError::LimitExceeded { .. })
    ));

    // Late feature count bomb after a valid entry.
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u32(schema.len() as u32);
    writer.bytes(&schema);
    writer.u32(1);
    writer.len_prefixed_u16(b"segments/a").unwrap();
    writer.len_prefixed_u16(b"objects/a").unwrap();
    writer.u8(0);
    writer.u64(10);
    writer.bytes(&[7u8; 32]);
    writer.u8(0);
    writer.u32(u32::MAX);
    let bytes = container(writer.into_vec());
    assert!(Manifest::decode(&bytes, &SegmentLimits::default()).is_err());
}
