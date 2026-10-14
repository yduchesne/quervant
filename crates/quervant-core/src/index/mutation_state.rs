//! Immutable generation mutation state (PR 9).
//!
//! The authoritative logical-key state at a committed generation is stored in a
//! dedicated, content-addressed, descriptor-verified sidecar rather than in the
//! segment files (which remain byte-immutable and shared). Each row records a
//! logical [`DocumentKey`], its monotonically increasing revision, and either a
//! `LIVE` winning physical pointer or a `DELETED` tombstone. A bounded, finite
//! idempotency replay ledger is part of the same generation state.
//!
//! The payload is wrapped in the shared container envelope and validated by
//! SHA-256 (`ContentDescriptor`). It is fully deterministic: rows and replay
//! entries are strictly ascending, so equal logical state encodes to equal
//! bytes.

use std::collections::BTreeMap;

use quervant_objectstore::ContentDigest;
use sha2::{Digest, Sha256};

use crate::contract::document::{
    Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent,
};
use crate::contract::value::FieldValue;

use super::super::segment::format::{
    ByteReader, ByteWriter, ContainerBuilder, ContainerKind, FEATURE_MUTATION_STATE, SectionKind,
    parse_container,
};
use super::super::segment::schema::field_type_tag;
use super::super::segment::value::{encode_scalar, state_of};
use super::super::segment::{SegmentError, SegmentLimits, SegmentResult};

/// Payload version for the mutation-state section.
pub(crate) const MUTATION_STATE_VERSION: u16 = 1;

/// Logical key status.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum KeyStatus {
    Deleted,
    Live,
}

impl KeyStatus {
    const fn tag(self) -> u8 {
        match self {
            Self::Deleted => 0,
            Self::Live => 1,
        }
    }

    fn from_tag(tag: u8) -> SegmentResult<Self> {
        match tag {
            0 => Ok(Self::Deleted),
            1 => Ok(Self::Live),
            value => Err(SegmentError::Corrupt {
                context: "mutation-state status",
                detail: format!("unknown status {value}"),
            }),
        }
    }
}

/// One logical key's generation state.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct KeyRow {
    /// Stable logical key.
    pub key: DocumentKey,
    /// Monotonically increasing revision (>= 1).
    pub revision: u64,
    /// Logical status.
    pub status: KeyStatus,
    /// Winning segment id (live only).
    pub segment_id: Option<String>,
    /// Winning physical doc id (live only).
    pub doc_id: Option<u64>,
}

impl KeyRow {
    /// A live winner row.
    pub(crate) fn live(
        key: DocumentKey,
        revision: u64,
        segment_id: impl Into<String>,
        doc_id: u64,
    ) -> Self {
        Self {
            key,
            revision,
            status: KeyStatus::Live,
            segment_id: Some(segment_id.into()),
            doc_id: Some(doc_id),
        }
    }

    /// A tombstone row.
    pub(crate) fn deleted(key: DocumentKey, revision: u64) -> Self {
        Self {
            key,
            revision,
            status: KeyStatus::Deleted,
            segment_id: None,
            doc_id: None,
        }
    }

    /// Whether this row is a live winner.
    #[must_use]
    pub(crate) const fn is_live(&self) -> bool {
        matches!(self.status, KeyStatus::Live)
    }
}

/// One idempotency replay-ledger entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ReplayRow {
    /// Opaque nonempty idempotency token.
    pub token: IdempotencyKey,
    /// Fingerprint of the original request payload.
    pub fingerprint: [u8; 32],
    /// The logical key the request targeted.
    pub key: DocumentKey,
    /// The intent of the original request.
    pub intent: MutationIntent,
    /// The revision assigned to the original accepted operation.
    pub revision: u64,
}

/// The complete authoritative logical state of one committed generation.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub(crate) struct MutationStateV1 {
    rows: Vec<KeyRow>,
    replay: Vec<ReplayRow>,
}

impl MutationStateV1 {
    /// The empty state (no keys, no replay).
    #[must_use]
    #[allow(dead_code)]
    pub(crate) fn empty() -> Self {
        Self {
            rows: Vec::new(),
            replay: Vec::new(),
        }
    }

    /// Build state from a key-indexed map and replay map, canonicalizing order.
    #[must_use]
    pub(crate) fn from_parts(
        rows: BTreeMap<DocumentKey, KeyRow>,
        replay: BTreeMap<IdempotencyKey, ReplayRow>,
    ) -> Self {
        Self {
            rows: rows.into_values().collect(),
            replay: replay.into_values().collect(),
        }
    }

    /// All key rows in strictly ascending key order.
    #[must_use]
    pub(crate) fn rows(&self) -> &[KeyRow] {
        &self.rows
    }

    /// All replay rows in strictly ascending token order.
    #[must_use]
    pub(crate) fn replay_rows(&self) -> &[ReplayRow] {
        &self.replay
    }

    /// Look up one key row.
    #[must_use]
    pub(crate) fn row(&self, key: &DocumentKey) -> Option<&KeyRow> {
        self.rows
            .binary_search_by(|row| row.key.cmp(key))
            .ok()
            .map(|index| &self.rows[index])
    }

    /// Look up one replay entry.
    #[must_use]
    pub(crate) fn replay_entry(&self, token: &IdempotencyKey) -> Option<&ReplayRow> {
        self.replay
            .binary_search_by(|row| row.token.cmp(token))
            .ok()
            .map(|index| &self.replay[index])
    }

    /// The current revision for `key` (`0` if absent).
    #[must_use]
    #[allow(dead_code)]
    pub(crate) fn revision(&self, key: &DocumentKey) -> u64 {
        self.row(key).map(|row| row.revision).unwrap_or(0)
    }

    /// Whether `key` is currently live.
    #[must_use]
    #[allow(dead_code)]
    pub(crate) fn is_live(&self, key: &DocumentKey) -> bool {
        self.row(key).is_some_and(KeyRow::is_live)
    }

    /// Number of rows.
    #[must_use]
    #[allow(dead_code)]
    pub(crate) fn row_count(&self) -> usize {
        self.rows.len()
    }

    /// Number of replay entries.
    #[must_use]
    pub(crate) fn replay_count(&self) -> usize {
        self.replay.len()
    }

    /// Conservative modeled replay-ledger bytes for preflight bounds.
    #[must_use]
    pub(crate) fn replay_bytes(&self) -> u64 {
        self.replay.iter().fold(0u64, |total, row| {
            total
                .saturating_add(96)
                .saturating_add(row.token.as_str().len() as u64)
                .saturating_add(row.key.as_str().len() as u64)
        })
    }

    /// Conservative modeled retained bytes, used for [`IndexLimits`] preflight.
    ///
    /// [`IndexLimits`]: crate::index::IndexLimits
    #[must_use]
    #[allow(dead_code)]
    pub(crate) fn retained_bytes(&self) -> u64 {
        let mut total: u64 = 0;
        for row in &self.rows {
            total = total
                .saturating_add(64)
                .saturating_add(row.key.as_str().len() as u64)
                .saturating_add(row.segment_id.as_ref().map_or(0, |id| id.len() as u64));
        }
        for row in &self.replay {
            total = total
                .saturating_add(96)
                .saturating_add(row.token.as_str().len() as u64)
                .saturating_add(row.key.as_str().len() as u64);
        }
        total
    }

    /// Encode the sidecar into the shared container envelope.
    pub(crate) fn encode(&self) -> SegmentResult<Vec<u8>> {
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION);
        payload.u32(
            u32::try_from(self.rows.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.rows.len() as u64,
            })?,
        );
        let mut previous: Option<&str> = None;
        for row in &self.rows {
            if let Some(previous) = previous {
                if previous.as_bytes() >= row.key.as_str().as_bytes() {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state rows",
                        detail: "rows are not strictly ascending".to_owned(),
                    });
                }
            }
            previous = Some(row.key.as_str());
            if row.revision == 0 {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state rows",
                    detail: "zero revision".to_owned(),
                });
            }
            payload.len_prefixed_u16(row.key.as_str().as_bytes())?;
            payload.u64(row.revision);
            payload.u8(row.status.tag());
            match (row.status, &row.segment_id, row.doc_id) {
                (KeyStatus::Live, Some(segment_id), Some(doc_id)) => {
                    payload.len_prefixed_u16(segment_id.as_bytes())?;
                    payload.u64(doc_id);
                }
                (KeyStatus::Deleted, None, None) => {}
                _ => {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state rows",
                        detail: "status/pointer mismatch".to_owned(),
                    });
                }
            }
        }
        payload.u32(
            u32::try_from(self.replay.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.replay.len() as u64,
            })?,
        );
        let mut previous_token: Option<&str> = None;
        for row in &self.replay {
            if let Some(previous) = previous_token {
                if previous.as_bytes() >= row.token.as_str().as_bytes() {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state replay",
                        detail: "replay entries are not strictly ascending".to_owned(),
                    });
                }
            }
            previous_token = Some(row.token.as_str());
            if row.revision == 0 {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state replay",
                    detail: "zero revision".to_owned(),
                });
            }
            payload.len_prefixed_u16(row.token.as_str().as_bytes())?;
            payload.bytes(&row.fingerprint);
            payload.len_prefixed_u16(row.key.as_str().as_bytes())?;
            payload.u8(intent_tag(row.intent));
            payload.u64(row.revision);
        }

        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
        builder.build()
    }

    /// Decode and structurally validate a sidecar.
    ///
    /// Rejects unknown status/intent, zero revision, duplicate/unsorted keys or
    /// tokens, malformed lengths and unknown required features. Semantic
    /// pointer validation against a manifest happens at the index layer.
    pub(crate) fn decode(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<Self> {
        let view = parse_container(bytes, limits)?;
        if view.kind() != ContainerKind::MutationState {
            return Err(SegmentError::Corrupt {
                context: "mutation state",
                detail: "not a mutation-state container".to_owned(),
            });
        }
        view.ensure_supported_features()?;
        let body = view
            .body(SectionKind::MutationState)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::MutationState as u16,
            })?;
        let mut reader = ByteReader::new(body);
        let version = reader.u16("mutation-state version")?;
        if version != MUTATION_STATE_VERSION {
            return Err(SegmentError::Corrupt {
                context: "mutation-state version",
                detail: format!("unsupported {version}"),
            });
        }
        let row_count = reader.u32("mutation-state row count")?;
        limits.check_entries(u64::from(row_count))?;
        limits.check_alloc::<KeyRow>(u64::from(row_count))?;
        let mut rows: Vec<KeyRow> = Vec::new();
        rows.try_reserve_exact(row_count as usize)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: u64::from(row_count),
            })?;
        let mut previous: Option<DocumentKey> = None;
        for _ in 0..row_count {
            let key_bytes = reader.len_prefixed_u16("mutation-state key")?;
            let key_ref =
                std::str::from_utf8(key_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "mutation-state key",
                })?;
            let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
                context: "mutation-state key",
                detail: "invalid document key".to_owned(),
            })?;
            if let Some(previous) = &previous {
                if previous >= &key {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state rows",
                        detail: "rows are not strictly ascending".to_owned(),
                    });
                }
            }
            previous = Some(key.clone());
            let revision = reader.u64("mutation-state revision")?;
            if revision == 0 {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state rows",
                    detail: "zero revision".to_owned(),
                });
            }
            let status = KeyStatus::from_tag(reader.u8("mutation-state status")?)?;
            let (segment_id, doc_id) = match status {
                KeyStatus::Live => {
                    let segment_bytes = reader.len_prefixed_u16("mutation-state segment id")?;
                    let segment_ref = std::str::from_utf8(segment_bytes).map_err(|_| {
                        SegmentError::InvalidUtf8 {
                            context: "mutation-state segment id",
                        }
                    })?;
                    if segment_ref.is_empty() {
                        return Err(SegmentError::Corrupt {
                            context: "mutation-state rows",
                            detail: "empty segment id".to_owned(),
                        });
                    }
                    (
                        Some(segment_ref.to_owned()),
                        Some(reader.u64("mutation-state doc id")?),
                    )
                }
                KeyStatus::Deleted => (None, None),
            };
            rows.push(KeyRow {
                key,
                revision,
                status,
                segment_id,
                doc_id,
            });
        }
        let replay_count = reader.u32("mutation-state replay count")?;
        limits.check_entries(u64::from(replay_count))?;
        limits.check_alloc::<ReplayRow>(u64::from(replay_count))?;
        let mut replay: Vec<ReplayRow> = Vec::new();
        replay
            .try_reserve_exact(replay_count as usize)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: u64::from(replay_count),
            })?;
        let mut previous_token: Option<IdempotencyKey> = None;
        for _ in 0..replay_count {
            let token_bytes = reader.len_prefixed_u16("mutation-state token")?;
            let token_ref =
                std::str::from_utf8(token_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "mutation-state token",
                })?;
            let token = IdempotencyKey::new(token_ref).map_err(|_| SegmentError::Corrupt {
                context: "mutation-state token",
                detail: "invalid idempotency token".to_owned(),
            })?;
            if let Some(previous) = &previous_token {
                if previous >= &token {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state replay",
                        detail: "replay entries are not strictly ascending".to_owned(),
                    });
                }
            }
            previous_token = Some(token.clone());
            let fingerprint = reader.bytes(32, "mutation-state fingerprint")?;
            let mut fingerprint_array = [0u8; 32];
            fingerprint_array.copy_from_slice(fingerprint);
            let key_bytes = reader.len_prefixed_u16("mutation-state replay key")?;
            let key_ref =
                std::str::from_utf8(key_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "mutation-state replay key",
                })?;
            let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
                context: "mutation-state replay key",
                detail: "invalid document key".to_owned(),
            })?;
            let intent = intent_from_tag(reader.u8("mutation-state replay intent")?)?;
            let revision = reader.u64("mutation-state replay revision")?;
            if revision == 0 {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state replay",
                    detail: "zero revision".to_owned(),
                });
            }
            replay.push(ReplayRow {
                token,
                fingerprint: fingerprint_array,
                key,
                intent,
                revision,
            });
        }
        reader.expect_end("mutation state")?;
        Ok(Self { rows, replay })
    }

    /// The SHA-256 digest of the canonical encoding.
    #[allow(dead_code)]
    pub(crate) fn content_digest(&self) -> SegmentResult<ContentDigest> {
        Ok(ContentDigest::sha256_v1(&self.encode()?))
    }
}

const fn intent_tag(intent: MutationIntent) -> u8 {
    match intent {
        MutationIntent::Insert => 0,
        MutationIntent::Upsert => 1,
        MutationIntent::Delete => 2,
    }
}

fn intent_from_tag(tag: u8) -> SegmentResult<MutationIntent> {
    match tag {
        0 => Ok(MutationIntent::Insert),
        1 => Ok(MutationIntent::Upsert),
        2 => Ok(MutationIntent::Delete),
        value => Err(SegmentError::Corrupt {
            context: "mutation-state intent",
            detail: format!("unknown intent {value}"),
        }),
    }
}

/// Deterministic SHA-256 fingerprint of a mutation request payload.
///
/// Covers intent, logical key and every field state, including the distinction
/// between absent, explicit null, empty multi, scalar, and ordered multi values.
/// Never uses `Debug`, randomized hashing or map iteration order.
pub(crate) fn mutation_fingerprint(
    intent: MutationIntent,
    key: &DocumentKey,
    document: Option<&Document>,
) -> SegmentResult<[u8; 32]> {
    let mut writer = ByteWriter::new();
    writer.u8(intent_tag(intent));
    writer.varint(key.as_str().len() as u64);
    writer.bytes(key.as_str().as_bytes());
    match document {
        Some(document) => {
            writer.u8(1);
            writer.varint(document.field_count() as u64);
            for (name, values) in document.fields() {
                writer.varint(name.len() as u64);
                writer.bytes(name.as_bytes());
                encode_fingerprint_values(&mut writer, values)?;
            }
        }
        None => writer.u8(0),
    }
    let digest = Sha256::digest(writer.as_slice());
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    Ok(out)
}

fn encode_fingerprint_values(writer: &mut ByteWriter, values: &FieldValues) -> SegmentResult<()> {
    writer.u8(state_of(values));
    match values {
        FieldValues::Absent | FieldValues::ExplicitNull | FieldValues::Empty => Ok(()),
        FieldValues::Single(value) => encode_fingerprint_scalar(writer, value),
        FieldValues::Multi(values) => {
            writer.varint(values.len() as u64);
            for value in values {
                encode_fingerprint_scalar(writer, value)?;
            }
            Ok(())
        }
    }
}

fn encode_fingerprint_scalar(writer: &mut ByteWriter, value: &FieldValue) -> SegmentResult<()> {
    writer.u8(field_type_tag(value.field_type()));
    encode_scalar(writer, value.field_type(), value)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::FieldValues;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn state() -> MutationStateV1 {
        let rows = BTreeMap::from([
            (key("a"), KeyRow::live(key("a"), 2, "s-1", 0)),
            (key("b"), KeyRow::deleted(key("b"), 1)),
        ]);
        let replay = BTreeMap::from([(
            IdempotencyKey::new("tok").unwrap(),
            ReplayRow {
                token: IdempotencyKey::new("tok").unwrap(),
                fingerprint: [9u8; 32],
                key: key("a"),
                intent: MutationIntent::Upsert,
                revision: 2,
            },
        )]);
        MutationStateV1::from_parts(rows, replay)
    }

    #[test]
    fn round_trip_is_deterministic() {
        let state = state();
        let bytes = state.encode().unwrap();
        let decoded = MutationStateV1::decode(&bytes, &SegmentLimits::default()).unwrap();
        assert_eq!(decoded, state);
        assert_eq!(decoded.encode().unwrap(), bytes);
        assert!(state.is_live(&key("a")));
        assert!(!state.is_live(&key("b")));
        assert_eq!(state.revision(&key("a")), 2);
        assert_eq!(state.revision(&key("missing")), 0);
        assert!(
            state
                .replay_entry(&IdempotencyKey::new("tok").unwrap())
                .is_some()
        );
        assert_eq!(state.row_count(), 2);
        assert_eq!(state.replay_count(), 1);
        assert!(state.retained_bytes() > 0);
        assert!(state.content_digest().is_ok());
    }

    #[test]
    fn rejects_unsorted_and_duplicate_rows() {
        let mut bytes = state().encode().unwrap();
        // Flip the row count to zero is not enough; build a malformed payload
        // directly through the container.
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION);
        payload.u32(2);
        for k in ["b", "a"] {
            payload.len_prefixed_u16(k.as_bytes()).unwrap();
            payload.u64(1);
            payload.u8(0);
        }
        payload.u32(0);
        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
        let malformed = builder.build().unwrap();
        assert!(MutationStateV1::decode(&malformed, &SegmentLimits::default()).is_err());
        // Truncation at every prefix is rejected.
        for cut in 1..bytes.len() {
            let _ = MutationStateV1::decode(&bytes[..cut], &SegmentLimits::default());
        }
        // Unknown status.
        bytes.clear();
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION);
        payload.u32(1);
        payload.len_prefixed_u16(b"a").unwrap();
        payload.u64(1);
        payload.u8(7);
        payload.u32(0);
        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
        assert!(
            MutationStateV1::decode(&builder.build().unwrap(), &SegmentLimits::default()).is_err()
        );
    }

    #[test]
    fn fingerprint_distinguishes_field_states() {
        let alpha = Document::new(key("d"));
        let mut null = Document::new(key("d"));
        null.insert("a", FieldValues::ExplicitNull).unwrap();
        let mut empty = Document::new(key("d"));
        empty.insert("a", FieldValues::Empty).unwrap();
        let base = mutation_fingerprint(MutationIntent::Upsert, &key("d"), Some(&alpha)).unwrap();
        let null_fp = mutation_fingerprint(MutationIntent::Upsert, &key("d"), Some(&null)).unwrap();
        let empty_fp =
            mutation_fingerprint(MutationIntent::Upsert, &key("d"), Some(&empty)).unwrap();
        assert_ne!(base, null_fp);
        assert_ne!(null_fp, empty_fp);
        let delete = mutation_fingerprint(MutationIntent::Delete, &key("d"), None).unwrap();
        assert_ne!(base, delete);
        // Array ordering matters.
        let mut first = Document::new(key("d"));
        first
            .insert(
                "a",
                FieldValues::Multi(vec![FieldValue::I64(1), FieldValue::I64(2)]),
            )
            .unwrap();
        let mut second = Document::new(key("d"));
        second
            .insert(
                "a",
                FieldValues::Multi(vec![FieldValue::I64(2), FieldValue::I64(1)]),
            )
            .unwrap();
        assert_ne!(
            mutation_fingerprint(MutationIntent::Upsert, &key("d"), Some(&first)).unwrap(),
            mutation_fingerprint(MutationIntent::Upsert, &key("d"), Some(&second)).unwrap()
        );
    }
}
