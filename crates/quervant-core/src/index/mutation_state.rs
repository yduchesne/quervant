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
use crate::contract::mutation::{
    DocumentPatch, MutationAction, MutationBatch, MutationBatchResponse, MutationCommandOutcome,
    MutationKeyOutcome, MutationPrecondition, MutationTarget, PatchOperation,
};
use crate::contract::value::FieldValue;

use super::super::segment::format::{
    ByteReader, ByteWriter, ContainerBuilder, ContainerKind, FEATURE_MUTATION_STATE,
    FEATURE_MUTATION_STATE_V2, FEATURE_MUTATION_STATE_V3, SectionKind, parse_container,
};
use super::super::segment::schema::field_type_tag;
use super::super::segment::value::{encode_scalar, state_of};
use super::super::segment::{SegmentError, SegmentLimits, SegmentResult};

/// Payload version 1: key rows plus the single-key idempotency replay ledger.
pub(crate) const MUTATION_STATE_VERSION: u16 = 1;
/// Payload version 2: version 1 plus durable atomic-batch replay records.
pub(crate) const MUTATION_STATE_VERSION_BATCH: u16 = 2;
/// Payload version 3: version 2 with a sorted segment-id table and canonical
/// varint dictionary ordinals / physical document ids (PR 15I-A).
pub(crate) const MUTATION_STATE_VERSION_COMPACT: u16 = 3;
/// Domain separation tag for whole-batch idempotency fingerprints.
const BATCH_FINGERPRINT_DOMAIN: &[u8] = b"quervant.mutation.batch.fingerprint.v1";
/// Versioned domain separation tag for whole-batch fingerprints that contain at
/// least one query target. The query selector AST is encoded canonically in
/// addition to `max_matches` and `expected_generation`; explicit-key-only
/// batches keep the v1 bytes above unchanged.
const BATCH_FINGERPRINT_QUERY_DOMAIN: &[u8] = b"quervant.mutation.batch.fingerprint.v2.query";

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

/// One durable atomic-batch idempotency replay record.
///
/// The stored response is the canonical *original* outcome with every
/// `replayed` flag set to `false`. A replay lookup returns a clone with the
/// top-level and per-key flags set to `true`; keys are never reselected.
#[derive(Debug, Clone, PartialEq)]
pub(crate) struct BatchReplayRow {
    /// Opaque nonempty idempotency token.
    pub token: IdempotencyKey,
    /// Domain-separated fingerprint of the original batch request.
    pub fingerprint: [u8; 32],
    /// The canonical original outcome.
    pub response: MutationBatchResponse,
}
impl BatchReplayRow {
    /// Clamp the stored response into a replay response.
    #[must_use]
    pub(crate) fn replay_response(&self) -> MutationBatchResponse {
        let mut response = self.response.clone();
        response.replayed = true;
        for command in &mut response.outcomes {
            for outcome in &mut command.keys {
                outcome.replayed = true;
            }
        }
        response
    }
}

/// The complete authoritative logical state of one committed generation.
#[derive(Debug, Clone, PartialEq, Default)]
pub(crate) struct MutationStateV1 {
    rows: Vec<KeyRow>,
    replay: Vec<ReplayRow>,
    batch_replay: Vec<BatchReplayRow>,
}

impl MutationStateV1 {
    /// The empty state (no keys, no replay).
    #[must_use]
    #[allow(dead_code)]
    pub(crate) fn empty() -> Self {
        Self {
            rows: Vec::new(),
            replay: Vec::new(),
            batch_replay: Vec::new(),
        }
    }

    /// Build state from a key-indexed map and replay map, canonicalizing order.
    ///
    /// This constructor never carries batch replay records; use
    /// [`Self::with_batch_replay`] to attach them.
    #[must_use]
    pub(crate) fn from_parts(
        rows: BTreeMap<DocumentKey, KeyRow>,
        replay: BTreeMap<IdempotencyKey, ReplayRow>,
    ) -> Self {
        Self {
            rows: rows.into_values().collect(),
            replay: replay.into_values().collect(),
            batch_replay: Vec::new(),
        }
    }

    /// Attach canonical, token-sorted durable batch replay records.
    #[must_use]
    pub(crate) fn with_batch_replay(
        mut self,
        batch_replay: BTreeMap<IdempotencyKey, BatchReplayRow>,
    ) -> Self {
        self.batch_replay = batch_replay.into_values().collect();
        self
    }

    /// All durable batch replay rows in strictly ascending token order.
    #[must_use]
    pub(crate) fn batch_replay_rows(&self) -> &[BatchReplayRow] {
        &self.batch_replay
    }

    /// Look up one durable batch replay entry.
    #[must_use]
    pub(crate) fn batch_replay_entry(&self, token: &IdempotencyKey) -> Option<&BatchReplayRow> {
        self.batch_replay
            .binary_search_by(|row| row.token.cmp(token))
            .ok()
            .map(|index| &self.batch_replay[index])
    }

    /// Whether this state carries any batch replay record.
    #[must_use]
    pub(crate) fn has_batch_replay(&self) -> bool {
        !self.batch_replay.is_empty()
    }

    /// Number of durable batch replay entries.
    #[must_use]
    pub(crate) fn batch_replay_count(&self) -> usize {
        self.batch_replay.len()
    }

    /// Total number of persisted per-key batch outcomes.
    #[must_use]
    pub(crate) fn batch_replay_key_count(&self) -> usize {
        self.batch_replay
            .iter()
            .map(|row| row.response.key_outcome_count())
            .sum()
    }

    /// Conservative modeled bytes for durable batch replay records.
    #[must_use]
    pub(crate) fn batch_replay_bytes(&self) -> u64 {
        self.batch_replay.iter().fold(0u64, |total, row| {
            let encoded = row.response.encoded_len().unwrap_or(u64::MAX);
            total
                .saturating_add(64)
                .saturating_add(row.token.as_str().len() as u64)
                .saturating_add(encoded)
        })
    }

    /// Total modeled replay-ledger bytes across both replay collections.
    #[must_use]
    pub(crate) fn replay_bytes_total(&self) -> u64 {
        self.replay_bytes()
            .saturating_add(self.batch_replay_bytes())
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
        total.saturating_add(self.batch_replay_bytes())
    }

    /// Encode the sidecar using the lowest payload version that is safe.
    pub(crate) fn encode(&self) -> SegmentResult<Vec<u8>> {
        self.encode_with_mode(false)
    }

    /// Encode the sidecar, preserving an already-published v2 upgrade.
    ///
    /// `version_2_active` must be `true` when the committed generation already
    /// requires [`FEATURE_MUTATION_STATE_V2`]. An index that has been upgraded
    /// is never silently downgraded, even when every batch replay record has
    /// since been replaced by ordinary single-key entries.
    pub(crate) fn encode_with_mode(&self, version_2_active: bool) -> SegmentResult<Vec<u8>> {
        let use_version_2 = version_2_active || !self.batch_replay.is_empty();
        let mut payload = ByteWriter::new();
        payload.u16(if use_version_2 {
            MUTATION_STATE_VERSION_BATCH
        } else {
            MUTATION_STATE_VERSION
        });
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

        if use_version_2 {
            encode_batch_replay(&mut payload, &self.batch_replay)?;
        }

        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        if use_version_2 {
            builder.require_feature(FEATURE_MUTATION_STATE_V2, 1);
        }
        builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
        builder.build()
    }

    /// Encode the sidecar with the compact payload version 3 (PR 15I-A).
    ///
    /// The live mutation-state rows store one sorted segment-id table plus a
    /// canonical varint dictionary ordinal and a canonical varint physical
    /// document id per live row instead of a repeated full segment-id string and
    /// a fixed-width `u64` document id. The single-key replay rows and the batch
    /// replay block use the exact existing serialization; the batch block is
    /// always present, including an empty `u32(0)` count.
    ///
    /// `version_2_active` must be `true` when the committed generation already
    /// requires [`FEATURE_MUTATION_STATE_V2`]; it is also required whenever any
    /// batch replay record exists. The V3 marker is always required.
    pub(crate) fn encode_v3(
        &self,
        version_2_active: bool,
        limits: &SegmentLimits,
    ) -> SegmentResult<Vec<u8>> {
        let use_version_2 = version_2_active || !self.batch_replay.is_empty();

        // Preflight counts and every allocation the encoder makes.
        limits.check_entries(self.rows.len() as u64)?;
        limits.check_entries(self.replay.len() as u64)?;
        limits.check_entries(self.batch_replay.len() as u64)?;
        let row_count =
            u32::try_from(self.rows.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.rows.len() as u64,
            })?;
        let replay_count =
            u32::try_from(self.replay.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.replay.len() as u64,
            })?;

        // Validate rows and collect the borrowed live segment ids.
        let live_count = self.rows.iter().filter(|row| row.is_live()).count();
        limits.check_entries(live_count as u64)?;
        limits.check_alloc::<&str>(live_count as u64)?;
        let mut ids: Vec<&str> = Vec::new();
        ids.try_reserve_exact(live_count)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: live_count as u64,
            })?;
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
            match (row.status, &row.segment_id, row.doc_id) {
                (KeyStatus::Live, Some(segment_id), Some(_)) => {
                    if segment_id.is_empty() {
                        return Err(SegmentError::Corrupt {
                            context: "mutation-state rows",
                            detail: "empty segment id".to_owned(),
                        });
                    }
                    u16::try_from(segment_id.len()).map_err(|_| SegmentError::LengthMismatch {
                        context: "u16 length prefix",
                        expected: u64::from(u16::MAX),
                        actual: segment_id.len() as u64,
                    })?;
                    ids.push(segment_id.as_str());
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

        // Canonical dictionary: raw UTF-8 byte order, exact referenced ids only.
        ids.sort_unstable_by(|left, right| left.as_bytes().cmp(right.as_bytes()));
        ids.dedup();
        limits.check_entries(ids.len() as u64)?;
        let table_count = u32::try_from(ids.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: ids.len() as u64,
        })?;

        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION_COMPACT);
        payload.u32(table_count);
        for id in &ids {
            payload.len_prefixed_u16(id.as_bytes())?;
        }
        payload.u32(row_count);
        for row in &self.rows {
            payload.len_prefixed_u16(row.key.as_str().as_bytes())?;
            payload.u64(row.revision);
            payload.u8(row.status.tag());
            match (row.status, &row.segment_id, row.doc_id) {
                (KeyStatus::Live, Some(segment_id), Some(doc_id)) => {
                    let index = ids
                        .binary_search_by(|candidate| {
                            candidate.as_bytes().cmp(segment_id.as_str().as_bytes())
                        })
                        .map_err(|_| SegmentError::Corrupt {
                            context: "mutation-state V3 segment table",
                            detail: "live segment id is missing from the table".to_owned(),
                        })?;
                    let ordinal =
                        u32::try_from(index).map_err(|_| SegmentError::LimitExceeded {
                            limit: u64::from(u32::MAX),
                            requested: index as u64,
                        })?;
                    payload.varint(u64::from(ordinal));
                    payload.varint(doc_id);
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

        // Existing single-key replay serialization, unchanged.
        payload.u32(replay_count);
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

        // The batch block is always present for V3, even when empty.
        encode_batch_replay(&mut payload, &self.batch_replay)?;

        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.require_feature(FEATURE_MUTATION_STATE_V3, 1);
        if use_version_2 {
            builder.require_feature(FEATURE_MUTATION_STATE_V2, 1);
        }
        builder.section(SectionKind::MutationState, 0, 0, payload.into_vec());
        builder.build()
    }

    /// Decode and structurally validate a sidecar.
    ///
    /// Rejects unknown status/intent, zero revision, duplicate/unsorted keys or
    /// tokens, malformed lengths and unknown required features. Semantic
    /// pointer validation against a manifest happens at the index layer.
    #[allow(dead_code)]
    pub(crate) fn decode(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<Self> {
        Self::decode_with_version(bytes, limits).map(|(state, _)| state)
    }

    /// Decode a sidecar and report the payload version it was encoded with.
    ///
    /// The index layer needs the payload version so it can reject a mismatch
    /// between a V3 sidecar and the manifest feature set (and the reverse)
    /// before any state becomes visible.
    pub(crate) fn decode_with_version(
        bytes: &[u8],
        limits: &SegmentLimits,
    ) -> SegmentResult<(Self, u16)> {
        let view = parse_container(bytes, limits)?;
        if view.kind() != ContainerKind::MutationState {
            return Err(SegmentError::Corrupt {
                context: "mutation state",
                detail: "not a mutation-state container".to_owned(),
            });
        }
        // Required features are validated before any payload parsing.
        view.ensure_supported_features()?;
        let v3_required = view
            .required_features()
            .contains(&(FEATURE_MUTATION_STATE_V3, 1));
        let body = view
            .body(SectionKind::MutationState)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::MutationState as u16,
            })?;
        let mut reader = ByteReader::new(body);
        let version = reader.u16("mutation-state version")?;
        let state = match version {
            MUTATION_STATE_VERSION | MUTATION_STATE_VERSION_BATCH => {
                if v3_required {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state version",
                        detail: "required V3 feature with a legacy payload".to_owned(),
                    });
                }
                Self::decode_legacy_payload(&mut reader, limits, version)?
            }
            MUTATION_STATE_VERSION_COMPACT => {
                if !v3_required {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state version",
                        detail: "V3 payload without the required V3 feature".to_owned(),
                    });
                }
                let mut budget = V3DecodeBudget::new(*limits);
                Self::decode_v3_payload(&mut reader, limits, &mut budget)?
            }
            other => {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state version",
                    detail: format!("unsupported {other}"),
                });
            }
        };
        reader.expect_end("mutation state")?;
        Ok((state, version))
    }

    /// Decode a payload version 1 or 2 sidecar body.
    fn decode_legacy_payload(
        reader: &mut ByteReader<'_>,
        limits: &SegmentLimits,
        version: u16,
    ) -> SegmentResult<Self> {
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
        let batch_replay = if version == MUTATION_STATE_VERSION_BATCH {
            decode_batch_replay(reader, limits, None)?
        } else {
            Vec::new()
        };
        Ok(Self {
            rows,
            replay,
            batch_replay,
        })
    }

    /// Decode a payload version 3 body with the fixed cumulative decode budget.
    fn decode_v3_payload(
        reader: &mut ByteReader<'_>,
        limits: &SegmentLimits,
        budget: &mut V3DecodeBudget,
    ) -> SegmentResult<Self> {
        // ---- Sorted segment-id table -------------------------------------
        let table_count = reader.u32("mutation-state V3 segment table count")?;
        let table_count_u64 = u64::from(table_count);
        limits.check_entries(table_count_u64)?;
        limits.check_alloc::<&str>(table_count_u64)?;
        limits.check_alloc::<u8>(table_count_u64)?;
        budget.charge_struct::<&str>(table_count_u64)?;
        budget.charge_struct::<u8>(table_count_u64)?;
        let mut table: Vec<&str> = Vec::new();
        table
            .try_reserve_exact(table_count as usize)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: table_count_u64,
            })?;
        let mut usage: Vec<u8> = Vec::new();
        usage
            .try_reserve_exact(table_count as usize)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: table_count_u64,
            })?;
        let mut previous_entry: Option<&[u8]> = None;
        for _ in 0..table_count {
            let id_bytes = reader.len_prefixed_u16("mutation-state V3 segment table entry")?;
            if id_bytes.is_empty() {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state V3 segment table",
                    detail: "empty segment id".to_owned(),
                });
            }
            let id_ref = std::str::from_utf8(id_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "mutation-state V3 segment table",
            })?;
            if let Some(previous) = previous_entry {
                if previous >= id_bytes {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state V3 segment table",
                        detail: "segment ids are not strictly ascending".to_owned(),
                    });
                }
            }
            previous_entry = Some(id_bytes);
            budget.charge(id_bytes.len() as u64)?;
            table.push(id_ref);
            usage.push(0);
        }

        // ---- Key rows ------------------------------------------------------
        let row_count = reader.u32("mutation-state V3 row count")?;
        limits.check_entries(u64::from(row_count))?;
        limits.check_alloc::<KeyRow>(u64::from(row_count))?;
        if table_count > row_count {
            return Err(SegmentError::Corrupt {
                context: "mutation-state V3 segment table",
                detail: "segment table is larger than the row count".to_owned(),
            });
        }
        budget.charge_struct::<KeyRow>(u64::from(row_count))?;
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
            budget.charge(key_bytes.len() as u64)?;
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
                    let raw_ordinal = reader.varint("mutation-state V3 ordinal")?;
                    let ordinal =
                        u32::try_from(raw_ordinal).map_err(|_| SegmentError::Corrupt {
                            context: "mutation-state V3 ordinal",
                            detail: format!("ordinal {raw_ordinal} exceeds u32"),
                        })?;
                    if ordinal >= table_count {
                        return Err(SegmentError::Corrupt {
                            context: "mutation-state V3 ordinal",
                            detail: format!("ordinal {ordinal} is out of range for {table_count}"),
                        });
                    }
                    let id = table[ordinal as usize];
                    usage[ordinal as usize] = 1;
                    let doc_id = reader.varint("mutation-state V3 doc id")?;
                    // Retained owned copy of the selected dictionary entry.
                    budget.charge(id.len() as u64)?;
                    (Some(id.to_owned()), Some(doc_id))
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
        // Every table entry must be referenced by at least one live row, and an
        // empty table is only valid when no row is live.
        if usage.contains(&0) {
            return Err(SegmentError::Corrupt {
                context: "mutation-state V3 segment table",
                detail: "segment table entry is not referenced by a live row".to_owned(),
            });
        }

        // ---- Single-key replay ledger -------------------------------------
        let replay_count = reader.u32("mutation-state replay count")?;
        limits.check_entries(u64::from(replay_count))?;
        limits.check_alloc::<ReplayRow>(u64::from(replay_count))?;
        budget.charge_struct::<ReplayRow>(u64::from(replay_count))?;
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
            budget.charge(token_bytes.len() as u64)?;
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
            budget.charge(key_bytes.len() as u64)?;
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

        // ---- Batch replay block (always present in V3) ---------------------
        let batch_replay = decode_batch_replay(reader, limits, Some(budget))?;
        Ok(Self {
            rows,
            replay,
            batch_replay,
        })
    }
    /// The SHA-256 digest of the canonical encoding.
    #[allow(dead_code)]
    pub(crate) fn content_digest(&self) -> SegmentResult<ContentDigest> {
        Ok(ContentDigest::sha256_v1(&self.encode()?))
    }
}

/// Cumulative V3-only decode charge against `max_section_decode_bytes`.
///
/// Every reservation and every owned copy is charged **before** it happens, so
/// a crafted count header can never direct an unbounded allocation. V1/V2
/// decoding keeps its historically established accounting and passes `None`.
struct V3DecodeBudget {
    used: u64,
    limits: SegmentLimits,
}

impl V3DecodeBudget {
    const fn new(limits: SegmentLimits) -> Self {
        Self { used: 0, limits }
    }

    fn charge(&mut self, bytes: u64) -> SegmentResult<()> {
        let next = self
            .used
            .checked_add(bytes)
            .ok_or(SegmentError::LimitExceeded {
                limit: self.limits.max_section_decode_bytes(),
                requested: u64::MAX,
            })?;
        self.limits.check_decoded_bytes(next)?;
        self.used = next;
        Ok(())
    }

    fn charge_struct<T>(&mut self, count: u64) -> SegmentResult<()> {
        let bytes = count.checked_mul(std::mem::size_of::<T>() as u64).ok_or(
            SegmentError::LimitExceeded {
                limit: self.limits.max_section_decode_bytes(),
                requested: u64::MAX,
            },
        )?;
        self.charge(bytes)
    }
}

/// Encode the durability-critical batch replay block (payload version 2).
fn encode_batch_replay(payload: &mut ByteWriter, rows: &[BatchReplayRow]) -> SegmentResult<()> {
    payload.u32(
        u32::try_from(rows.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: rows.len() as u64,
        })?,
    );
    let mut previous_token: Option<&str> = None;
    for row in rows {
        if let Some(previous) = previous_token {
            if previous.as_bytes() >= row.token.as_str().as_bytes() {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state batch replay",
                    detail: "batch replay entries are not strictly ascending".to_owned(),
                });
            }
        }
        previous_token = Some(row.token.as_str());
        payload.len_prefixed_u16(row.token.as_str().as_bytes())?;
        payload.bytes(&row.fingerprint);
        encode_batch_response(payload, &row.response)?;
    }
    Ok(())
}

/// Whether a durable batch command outcome has a permitted cardinality shape.
///
/// `matched` counts **query-selected documents**; `keys` counts **per-key
/// mutation outcomes**. They normally agree. The single permitted exception
/// (M4-AD16) is the zero-match query-upsert fallback: `matched = 0` with
/// exactly one `Insert` outcome for the inserted fallback document. The durable
/// response does not store the action or query, so this predicate validates
/// shape only; the writer planner is the sole producer of the exceptional
/// shape and enforces its semantics.
fn batch_outcome_cardinality_is_valid(matched: u64, keys: &[MutationKeyOutcome]) -> bool {
    if u64::try_from(keys.len()).ok() == Some(matched) {
        return true;
    }
    matched == 0 && keys.len() == 1 && keys[0].intent == MutationIntent::Insert
}

/// Encode one canonical batch response.
///
/// The durable form always stores `replayed = false` everywhere; replay is
/// derived on lookup, never persisted. [`MutationBatchResponse::encoded_len`]
/// is the authoritative size of exactly this encoding.
fn encode_batch_response(
    payload: &mut ByteWriter,
    response: &MutationBatchResponse,
) -> SegmentResult<()> {
    if response.replayed {
        return Err(SegmentError::Corrupt {
            context: "mutation-state batch replay",
            detail: "durable batch response is marked replayed".to_owned(),
        });
    }
    payload.u32(u32::try_from(response.outcomes.len()).map_err(|_| {
        SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: response.outcomes.len() as u64,
        }
    })?);
    payload.u8(u8::from(response.replayed));
    for (index, command) in response.outcomes.iter().enumerate() {
        let ordinal = u32::try_from(index).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: index as u64,
        })?;
        if command.command_index != ordinal {
            return Err(SegmentError::Corrupt {
                context: "mutation-state batch replay",
                detail: "command ordinal is not its index".to_owned(),
            });
        }
        if !batch_outcome_cardinality_is_valid(command.matched, &command.keys) {
            return Err(SegmentError::Corrupt {
                context: "mutation-state batch replay",
                detail: "command matched count does not match its key list".to_owned(),
            });
        }
        payload.u32(command.command_index);
        payload.u64(command.matched);
        payload.u32(u32::try_from(command.keys.len()).map_err(|_| {
            SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: command.keys.len() as u64,
            }
        })?);
        let mut previous_key: Option<&str> = None;
        for outcome in &command.keys {
            if let Some(previous) = previous_key {
                if previous.as_bytes() >= outcome.key.as_str().as_bytes() {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state batch replay",
                        detail: "batch outcomes are not strictly ascending".to_owned(),
                    });
                }
            }
            previous_key = Some(outcome.key.as_str());
            if outcome.replayed {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state batch replay",
                    detail: "durable batch key outcome is marked replayed".to_owned(),
                });
            }
            payload.len_prefixed_u16(outcome.key.as_str().as_bytes())?;
            payload.u8(intent_tag(outcome.intent));
            match outcome.revision {
                Some(revision) => {
                    if revision == 0 {
                        return Err(SegmentError::Corrupt {
                            context: "mutation-state batch replay",
                            detail: "zero revision".to_owned(),
                        });
                    }
                    payload.u8(1);
                    payload.u64(revision);
                }
                None => payload.u8(0),
            }
            payload.u8(u8::from(outcome.replayed));
        }
    }
    Ok(())
}

/// Decode and validate the payload version 2 batch replay block.
fn decode_batch_replay(
    reader: &mut ByteReader<'_>,
    limits: &SegmentLimits,
    mut budget: Option<&mut V3DecodeBudget>,
) -> SegmentResult<Vec<BatchReplayRow>> {
    let count = reader.u32("mutation-state batch replay count")?;
    limits.check_entries(u64::from(count))?;
    limits.check_alloc::<BatchReplayRow>(u64::from(count))?;
    if let Some(budget) = budget.as_deref_mut() {
        budget.charge_struct::<BatchReplayRow>(u64::from(count))?;
    }
    let mut rows: Vec<BatchReplayRow> = Vec::new();
    rows.try_reserve_exact(count as usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::from(count),
        })?;
    let mut previous_token: Option<IdempotencyKey> = None;
    for _ in 0..count {
        let token_bytes = reader.len_prefixed_u16("mutation-state batch token")?;
        let token_ref =
            std::str::from_utf8(token_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                context: "mutation-state batch token",
            })?;
        let token = IdempotencyKey::new(token_ref).map_err(|_| SegmentError::Corrupt {
            context: "mutation-state batch token",
            detail: "invalid idempotency token".to_owned(),
        })?;
        if let Some(previous) = &previous_token {
            if previous >= &token {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state batch replay",
                    detail: "batch replay entries are not strictly ascending".to_owned(),
                });
            }
        }
        if let Some(budget) = budget.as_deref_mut() {
            budget.charge(token_bytes.len() as u64)?;
        }
        previous_token = Some(token.clone());
        let fingerprint = reader.bytes(32, "mutation-state batch fingerprint")?;
        let mut fingerprint_array = [0u8; 32];
        fingerprint_array.copy_from_slice(fingerprint);
        let response = decode_batch_response(reader, limits, budget.as_deref_mut())?;
        rows.push(BatchReplayRow {
            token,
            fingerprint: fingerprint_array,
            response,
        });
    }
    Ok(rows)
}

/// Decode and validate one canonical batch response.
fn decode_batch_response(
    reader: &mut ByteReader<'_>,
    limits: &SegmentLimits,
    budget: Option<&mut V3DecodeBudget>,
) -> SegmentResult<MutationBatchResponse> {
    let mut budget = budget;
    let command_count = reader.u32("mutation-state batch command count")?;
    limits.check_entries(u64::from(command_count))?;
    limits.check_alloc::<MutationCommandOutcome>(u64::from(command_count))?;
    if let Some(budget) = budget.as_deref_mut() {
        budget.charge_struct::<MutationCommandOutcome>(u64::from(command_count))?;
    }
    let replayed = reader.u8("mutation-state batch replayed")?;
    if replayed != 0 {
        return Err(SegmentError::Corrupt {
            context: "mutation-state batch replay",
            detail: "durable batch response is marked replayed".to_owned(),
        });
    }
    let mut outcomes: Vec<MutationCommandOutcome> = Vec::new();
    outcomes
        .try_reserve_exact(command_count as usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: u64::from(command_count),
        })?;
    for index in 0..command_count {
        let command_index = reader.u32("mutation-state batch command ordinal")?;
        if command_index != index {
            return Err(SegmentError::Corrupt {
                context: "mutation-state batch replay",
                detail: "command ordinal is not its index".to_owned(),
            });
        }
        let matched = reader.u64("mutation-state batch matched")?;
        let key_count = reader.u32("mutation-state batch key count")?;
        limits.check_entries(u64::from(key_count))?;
        limits.check_alloc::<MutationKeyOutcome>(u64::from(key_count))?;
        if let Some(budget) = budget.as_deref_mut() {
            budget.charge_struct::<MutationKeyOutcome>(u64::from(key_count))?;
        }
        let mut keys: Vec<MutationKeyOutcome> = Vec::new();
        keys.try_reserve_exact(key_count as usize)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: u64::from(key_count),
            })?;
        let mut previous_key: Option<DocumentKey> = None;
        for _ in 0..key_count {
            let key_bytes = reader.len_prefixed_u16("mutation-state batch key")?;
            let key_ref =
                std::str::from_utf8(key_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                    context: "mutation-state batch key",
                })?;
            let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
                context: "mutation-state batch key",
                detail: "invalid document key".to_owned(),
            })?;
            if let Some(previous) = &previous_key {
                if previous >= &key {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state batch replay",
                        detail: "batch outcomes are not strictly ascending".to_owned(),
                    });
                }
            }
            if let Some(budget) = budget.as_deref_mut() {
                budget.charge(key_bytes.len() as u64)?;
            }
            previous_key = Some(key.clone());
            let intent = intent_from_tag(reader.u8("mutation-state batch intent")?)?;
            let presence = reader.u8("mutation-state batch revision presence")?;
            let revision = match presence {
                0 => None,
                1 => {
                    let revision = reader.u64("mutation-state batch revision")?;
                    if revision == 0 {
                        return Err(SegmentError::Corrupt {
                            context: "mutation-state batch replay",
                            detail: "zero revision".to_owned(),
                        });
                    }
                    Some(revision)
                }
                _ => {
                    return Err(SegmentError::Corrupt {
                        context: "mutation-state batch replay",
                        detail: "invalid revision presence tag".to_owned(),
                    });
                }
            };
            let outcome_replayed = reader.u8("mutation-state batch key replayed")?;
            if outcome_replayed != 0 {
                return Err(SegmentError::Corrupt {
                    context: "mutation-state batch replay",
                    detail: "durable batch key outcome is marked replayed".to_owned(),
                });
            }
            keys.push(MutationKeyOutcome {
                key,
                intent,
                revision,
                replayed: false,
            });
        }
        // Cardinality is validated only after the command's outcomes are known:
        // the permitted zero-match fallback shape depends on the Insert intent.
        if !batch_outcome_cardinality_is_valid(matched, &keys) {
            return Err(SegmentError::Corrupt {
                context: "mutation-state batch replay",
                detail: "command matched count does not match its key list".to_owned(),
            });
        }
        outcomes.push(MutationCommandOutcome {
            command_index,
            matched,
            keys,
        });
    }
    Ok(MutationBatchResponse {
        outcomes,
        replayed: false,
    })
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

/// Canonical, domain-separated fingerprint of a whole mutation batch.
///
/// Covers every command field in request order: target shape and keys, action,
/// action payload (every five-state field value and ordered patch operation),
/// and precondition. It is domain-separated from the single-key fingerprint so
/// a batch token can never be reinterpreted as a single-key token.
///
/// Never uses `Debug`, randomized hashing or map iteration order. `Query`
/// targets are rejected before admission in M1, but they are still encoded
/// deterministically so the fingerprint of a malformed request is never
/// order-dependent.
pub(crate) fn batch_fingerprint(batch: &MutationBatch) -> SegmentResult<[u8; 32]> {
    let contains_query = batch
        .commands
        .iter()
        .any(|command| matches!(command.target, MutationTarget::Query(_)));
    let mut writer = ByteWriter::new();
    writer.bytes(if contains_query {
        BATCH_FINGERPRINT_QUERY_DOMAIN
    } else {
        BATCH_FINGERPRINT_DOMAIN
    });
    writer.varint(batch.commands.len() as u64);
    for command in &batch.commands {
        encode_fingerprint_target(&mut writer, &command.target, contains_query)?;
        encode_fingerprint_action(&mut writer, &command.action)?;
        encode_fingerprint_precondition(&mut writer, command.precondition);
    }
    let digest = Sha256::digest(writer.as_slice());
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    Ok(out)
}

fn encode_fingerprint_target(
    writer: &mut ByteWriter,
    target: &MutationTarget,
    query_inclusive: bool,
) -> SegmentResult<()> {
    match target {
        MutationTarget::Key(key) => {
            writer.u8(0);
            writer.varint(key.as_str().len() as u64);
            writer.bytes(key.as_str().as_bytes());
            Ok(())
        }
        MutationTarget::Keys(keys) => {
            writer.u8(1);
            writer.varint(keys.len() as u64);
            for key in keys {
                writer.varint(key.as_str().len() as u64);
                writer.bytes(key.as_str().as_bytes());
            }
            Ok(())
        }
        MutationTarget::Query(selector) => {
            writer.u8(2);
            writer.u64(selector.max_matches);
            match selector.expected_generation {
                Some(generation) => {
                    writer.u8(1);
                    writer.u64(generation);
                }
                None => writer.u8(0),
            }
            if query_inclusive {
                let mut query_bytes = Vec::new();
                crate::search::encode_canonical_query(&mut query_bytes, &selector.query);
                writer.varint(query_bytes.len() as u64);
                writer.bytes(&query_bytes);
            }
            Ok(())
        }
    }
}

fn encode_fingerprint_action(
    writer: &mut ByteWriter,
    action: &MutationAction,
) -> SegmentResult<()> {
    match action {
        MutationAction::Insert(document) => {
            writer.u8(0);
            encode_fingerprint_document(writer, document)
        }
        MutationAction::Upsert(document) => {
            writer.u8(1);
            encode_fingerprint_document(writer, document)
        }
        MutationAction::Replace(document) => {
            writer.u8(2);
            encode_fingerprint_document(writer, document)
        }
        MutationAction::Update(patch) => {
            writer.u8(3);
            encode_fingerprint_patch(writer, patch)
        }
        MutationAction::Delete => {
            writer.u8(4);
            Ok(())
        }
        // Additive M4 discriminant. Old discriminants `0..4` and the target
        // encoding above are unchanged, so pre-M4 fingerprints stay
        // byte-for-byte identical. Both documents are encoded, in this order, so
        // a token conflict is detected when either changes.
        MutationAction::QueryUpsert {
            replacement,
            fallback,
        } => {
            writer.u8(5);
            encode_fingerprint_document(writer, replacement)?;
            encode_fingerprint_document(writer, fallback)
        }
    }
}

fn encode_fingerprint_document(writer: &mut ByteWriter, document: &Document) -> SegmentResult<()> {
    writer.varint(document.key().as_str().len() as u64);
    writer.bytes(document.key().as_str().as_bytes());
    writer.varint(document.field_count() as u64);
    for (name, values) in document.fields() {
        writer.varint(name.len() as u64);
        writer.bytes(name.as_bytes());
        encode_fingerprint_values(writer, values)?;
    }
    Ok(())
}

fn encode_fingerprint_patch(writer: &mut ByteWriter, patch: &DocumentPatch) -> SegmentResult<()> {
    writer.varint(patch.operations.len() as u64);
    for operation in &patch.operations {
        match operation {
            PatchOperation::Set { field, values } => {
                writer.u8(0);
                writer.varint(field.len() as u64);
                writer.bytes(field.as_bytes());
                encode_fingerprint_values(writer, values)?;
            }
            PatchOperation::Unset { field } => {
                writer.u8(1);
                writer.varint(field.len() as u64);
                writer.bytes(field.as_bytes());
            }
        }
    }
    Ok(())
}

fn encode_fingerprint_precondition(writer: &mut ByteWriter, precondition: MutationPrecondition) {
    match precondition {
        MutationPrecondition::None => writer.u8(0),
        MutationPrecondition::MustExist => writer.u8(1),
        MutationPrecondition::MustNotExist => writer.u8(2),
        MutationPrecondition::ExpectedRevision(revision) => {
            writer.u8(3);
            writer.u64(revision);
        }
    }
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

#[cfg(test)]
mod m1_fixture_tests {
    use super::*;
    use crate::contract::document::FieldValues;

    /// Byte-exact payload version 1 fixture generated with the **pre-M1**
    /// (baseline) encoder at `cd3b9ac`, before any v2 encoder existed.
    ///
    /// Contents: live key `m1-live` at revision 3 -> segment `seg-m1-fixture`
    /// doc 7; tombstone `m1-dead` at revision 2; one single-key replay token
    /// `m1-single-token` (Upsert, revision 3).
    ///
    /// Regenerate only with the dedicated v1 encoder branch:
    /// `cargo test -p quervant-core --lib m1_fixture_tests::regenerate_v1_fixture
    /// -- --ignored --nocapture`
    const V1_FIXTURE: &[u8] = include_bytes!("../../tests/fixtures/m1/mutation_state_v1.bin");
    const V1_FIXTURE_SHA256: &str =
        "753094d07734fbbebf5b535d585af83107d241c917e7e731462d2af972efc469";

    fn fixture_state() -> MutationStateV1 {
        let live = DocumentKey::new("m1-live").unwrap();
        let dead = DocumentKey::new("m1-dead").unwrap();
        let token = IdempotencyKey::new("m1-single-token").unwrap();
        let rows = BTreeMap::from([
            (live.clone(), KeyRow::live(live, 3, "seg-m1-fixture", 7)),
            (dead.clone(), KeyRow::deleted(dead, 2)),
        ]);
        let mut document = Document::new(DocumentKey::new("m1-live").unwrap());
        document
            .insert(
                "body",
                FieldValues::Single(FieldValue::Text("baseline".into())),
            )
            .unwrap();
        let fingerprint =
            mutation_fingerprint(MutationIntent::Upsert, document.key(), Some(&document)).unwrap();
        let replay = BTreeMap::from([(
            token.clone(),
            ReplayRow {
                token,
                fingerprint,
                key: document.key().clone(),
                intent: MutationIntent::Upsert,
                revision: 3,
            },
        )]);
        MutationStateV1::from_parts(rows, replay)
    }

    #[test]
    fn baseline_v1_fixture_decodes_under_the_new_reader() {
        assert_eq!(
            ContentDigest::sha256_v1(V1_FIXTURE).to_hex(),
            V1_FIXTURE_SHA256
        );
        let decoded =
            MutationStateV1::decode(V1_FIXTURE, &SegmentLimits::default()).expect("v1 fixture");
        assert_eq!(decoded, fixture_state());
        assert_eq!(decoded.replay_count(), 1);
        assert_eq!(decoded.batch_replay_count(), 0);
        assert!(!decoded.has_batch_replay());
        assert_eq!(decoded.revision(&DocumentKey::new("m1-live").unwrap()), 3);
        assert!(decoded.is_live(&DocumentKey::new("m1-live").unwrap()));
        assert!(!decoded.is_live(&DocumentKey::new("m1-dead").unwrap()));
        // Re-encoding an untouched v1 state must stay v1 and byte-identical.
        assert_eq!(decoded.encode().unwrap(), V1_FIXTURE);
    }

    #[test]
    fn v2_round_trip_preserves_batch_replay() {
        let token = IdempotencyKey::new("batch-token").unwrap();
        let response = MutationBatchResponse {
            outcomes: vec![MutationCommandOutcome {
                command_index: 0,
                matched: 2,
                keys: vec![
                    MutationKeyOutcome {
                        key: DocumentKey::new("a").unwrap(),
                        intent: MutationIntent::Delete,
                        revision: Some(4),
                        replayed: false,
                    },
                    MutationKeyOutcome {
                        key: DocumentKey::new("b").unwrap(),
                        intent: MutationIntent::Delete,
                        revision: Some(1),
                        replayed: false,
                    },
                ],
            }],
            replayed: false,
        };
        let state = fixture_state().with_batch_replay(BTreeMap::from([(
            token.clone(),
            BatchReplayRow {
                token,
                fingerprint: [7u8; 32],
                response: response.clone(),
            },
        )]));
        let bytes = state.encode().unwrap();
        let decoded = MutationStateV1::decode(&bytes, &SegmentLimits::default()).unwrap();
        assert_eq!(decoded, state);
        assert_eq!(decoded.batch_replay_count(), 1);
        assert_eq!(decoded.batch_replay_key_count(), 2);
        assert!(decoded.batch_replay_bytes() > 0);
        assert!(decoded.replay_bytes_total() > decoded.replay_bytes());
        let row = decoded
            .batch_replay_entry(&IdempotencyKey::new("batch-token").unwrap())
            .expect("batch row");
        let replayed = row.replay_response();
        assert!(replayed.replayed);
        assert!(replayed.outcomes[0].keys.iter().all(|k| k.replayed));
        assert_eq!(
            replayed
                .outcomes
                .iter()
                .flat_map(|c| c.keys.iter().map(|k| (k.key.clone(), k.revision)))
                .collect::<Vec<_>>(),
            response
                .outcomes
                .iter()
                .flat_map(|c| c.keys.iter().map(|k| (k.key.clone(), k.revision)))
                .collect::<Vec<_>>()
        );
        // v2 is preserved even when the in-memory batch replay set is empty.
        assert!(
            MutationStateV1::from_parts(BTreeMap::new(), BTreeMap::new())
                .encode_with_mode(true)
                .unwrap()
                .len()
                > MutationStateV1::from_parts(BTreeMap::new(), BTreeMap::new())
                    .encode()
                    .unwrap()
                    .len()
        );
    }

    #[test]
    fn v2_requires_the_new_feature_before_payload_decode() {
        let state = fixture_state().with_batch_replay(BTreeMap::from([(
            IdempotencyKey::new("batch-token").unwrap(),
            BatchReplayRow {
                token: IdempotencyKey::new("batch-token").unwrap(),
                fingerprint: [1u8; 32],
                response: MutationBatchResponse {
                    outcomes: Vec::new(),
                    replayed: false,
                },
            },
        )]));
        let bytes = state.encode().unwrap();
        let view = parse_container(&bytes, &SegmentLimits::default()).unwrap();
        assert!(
            view.required_features()
                .contains(&(FEATURE_MUTATION_STATE_V2, 1))
        );
        // The new reader accepts the feature set.
        view.ensure_supported_features().unwrap();
        // The baseline feature table (all ids < 0x000B) does not contain the v2
        // feature, so a baseline reader rejects the container with the typed
        // `UnsupportedFeature` error before any payload version is read.
        assert!(
            crate::segment::format::SUPPORTED_FEATURES.contains(&(FEATURE_MUTATION_STATE_V2, 1)),
            "the new reader must know the v2 feature"
        );
        let baseline_table: Vec<(u16, u16)> = crate::segment::format::SUPPORTED_FEATURES
            .iter()
            .copied()
            .filter(|(id, _)| *id < FEATURE_MUTATION_STATE_V2)
            .collect();
        assert!(!baseline_table.contains(&(FEATURE_MUTATION_STATE_V2, 1)));
        assert!(matches!(
            crate::segment::format::ensure_features_supported(&[(0x7FFF, 1)]),
            Err(SegmentError::UnsupportedFeature { .. })
        ));
    }

    fn v2_container(payload: Vec<u8>) -> Vec<u8> {
        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.require_feature(FEATURE_MUTATION_STATE_V2, 1);
        builder.section(SectionKind::MutationState, 0, 0, payload);
        builder.build().unwrap()
    }

    /// Payload version 2 with zero rows/replay and one batch record, built by
    /// hand so malformations can be injected.
    fn v2_payload(batch_body: impl FnOnce(&mut ByteWriter)) -> Vec<u8> {
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION_BATCH);
        payload.u32(0); // rows
        payload.u32(0); // single-key replay
        payload.u32(1); // batch replay records
        payload.len_prefixed_u16(b"tok").unwrap();
        payload.bytes(&[3u8; 32]);
        batch_body(&mut payload);
        payload.into_vec()
    }

    fn valid_batch_body(payload: &mut ByteWriter) {
        payload.u32(1); // commands
        payload.u8(0); // replayed
        payload.u32(0); // ordinal
        payload.u64(1); // matched
        payload.u32(1); // keys
        payload.len_prefixed_u16(b"a").unwrap();
        payload.u8(2); // delete intent
        payload.u8(1); // revision present
        payload.u64(5);
        payload.u8(0); // replayed
    }

    #[test]
    fn u14_malformed_v2_records_are_typed_rejections() {
        let limits = SegmentLimits::default();
        // Baseline: the valid hand-built payload decodes.
        let valid = v2_container(v2_payload(valid_batch_body));
        assert!(MutationStateV1::decode(&valid, &limits).is_ok());

        let mut cases: Vec<(&str, Vec<u8>)> = Vec::new();
        // Unordered batch tokens.
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION_BATCH);
        payload.u32(0);
        payload.u32(0);
        payload.u32(2);
        for token in ["z", "a"] {
            payload.len_prefixed_u16(token.as_bytes()).unwrap();
            payload.bytes(&[0u8; 32]);
            valid_batch_body(&mut payload);
        }
        cases.push(("unsorted tokens", v2_container(payload.into_vec())));
        // Duplicate keys inside one command.
        cases.push((
            "duplicate keys",
            v2_container(v2_payload(|payload| {
                payload.u32(1);
                payload.u8(0);
                payload.u32(0);
                payload.u64(2);
                payload.u32(2);
                for _ in 0..2 {
                    payload.len_prefixed_u16(b"a").unwrap();
                    payload.u8(2);
                    payload.u8(1);
                    payload.u64(5);
                    payload.u8(0);
                }
            })),
        ));
        // Impossible command count on a nonempty payload.
        cases.push((
            "impossible command count",
            v2_container(v2_payload(|payload| {
                payload.u32(u32::MAX);
                valid_batch_body(payload);
            })),
        ));
        // Impossible matched count.
        cases.push((
            "matched mismatch",
            v2_container(v2_payload(|payload| {
                payload.u32(1);
                payload.u8(0);
                payload.u32(0);
                payload.u64(9);
                payload.u32(1);
                payload.len_prefixed_u16(b"a").unwrap();
                payload.u8(2);
                payload.u8(0);
                payload.u8(0);
            })),
        ));
        // Non-canonical replay flag.
        cases.push((
            "persisted replay flag",
            v2_container(v2_payload(|payload| {
                payload.u32(1);
                payload.u8(1);
                valid_batch_body(payload);
            })),
        ));
        // Invalid intent tag.
        cases.push((
            "invalid intent",
            v2_container(v2_payload(|payload| {
                payload.u32(1);
                payload.u8(0);
                payload.u32(0);
                payload.u64(1);
                payload.u32(1);
                payload.len_prefixed_u16(b"a").unwrap();
                payload.u8(9);
                payload.u8(0);
                payload.u8(0);
            })),
        ));
        // Trailing bytes.
        cases.push((
            "trailing bytes",
            v2_container(v2_payload(|payload| {
                valid_batch_body(payload);
                payload.u8(0xFF);
            })),
        ));

        for (label, bytes) in cases {
            assert!(
                MutationStateV1::decode(&bytes, &limits).is_err(),
                "{label} must be rejected"
            );
        }

        // Truncation at every prefix never panics.
        for cut in 0..valid.len() {
            let _ = MutationStateV1::decode(&valid[..cut], &limits);
        }
        // A v1 payload carrying the v2 feature is tolerated: the feature is a
        // superset requirement, and the absence of a batch block is simply an
        // empty batch replay set. The reader must not invent records.
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION);
        payload.u32(0);
        payload.u32(0);
        let decoded = MutationStateV1::decode(&v2_container(payload.into_vec()), &limits)
            .expect("v1 payload with the v2 feature");
        assert_eq!(decoded.batch_replay_count(), 0);
    }

    /// Regenerate the checked-in v1 fixture from the retained v1 encoder.
    ///
    /// Ignored by default; run manually and commit the resulting bytes and the
    /// printed digest. Never regenerate from a v2-active encoder.
    #[test]
    #[ignore = "manual fixture regeneration"]
    fn regenerate_v1_fixture() {
        let bytes = fixture_state().encode().unwrap();
        std::fs::write(
            concat!(
                env!("CARGO_MANIFEST_DIR"),
                "/tests/fixtures/m1/mutation_state_v1.bin"
            ),
            &bytes,
        )
        .unwrap();
        println!(
            "len={} sha256={}",
            bytes.len(),
            ContentDigest::sha256_v1(&bytes).to_hex()
        );
        assert_eq!(bytes, V1_FIXTURE);
    }
}

#[cfg(test)]
mod m1_rejection_tests {
    use super::*;
    use crate::contract::mutation::{MutationCommand, MutationPrecondition};

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn batch() -> MutationBatch {
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Keys(vec![key("a"), key("b")]),
            MutationAction::Delete,
        )])
    }

    #[test]
    fn batch_fingerprint_is_stable_and_domain_separated() {
        let fingerprint = batch_fingerprint(&batch()).unwrap();
        assert_eq!(fingerprint, batch_fingerprint(&batch()).unwrap());
        let single = mutation_fingerprint(MutationIntent::Delete, &key("a"), None).unwrap();
        assert_ne!(fingerprint, single);
    }

    #[test]
    fn batch_fingerprint_covers_order_keys_actions_and_preconditions() {
        let base = batch_fingerprint(&batch()).unwrap();
        let reversed = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Keys(vec![key("b"), key("a")]),
            MutationAction::Delete,
        )]);
        assert_ne!(base, batch_fingerprint(&reversed).unwrap());

        let with_precondition = MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Keys(vec![key("a"), key("b")]),
                MutationAction::Delete,
            )
            .with_precondition(MutationPrecondition::ExpectedRevision(3)),
        ]);
        assert_ne!(base, batch_fingerprint(&with_precondition).unwrap());

        let command_swap = MutationBatch::new(vec![
            MutationCommand::new(MutationTarget::Key(key("a")), MutationAction::Delete),
            MutationCommand::new(MutationTarget::Key(key("b")), MutationAction::Delete),
        ]);
        assert_ne!(base, batch_fingerprint(&command_swap).unwrap());
    }

    #[test]
    fn batch_fingerprint_distinguishes_field_states_and_patch_operations() {
        let mut document = Document::new(key("a"));
        document
            .insert("f", FieldValues::Single(FieldValue::I64(1)))
            .unwrap();
        let insert = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Insert(document.clone()),
        )]);
        let upsert = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Upsert(document.clone()),
        )]);
        assert_ne!(
            batch_fingerprint(&insert).unwrap(),
            batch_fingerprint(&upsert).unwrap()
        );

        let mut null = Document::new(key("a"));
        null.insert("f", FieldValues::ExplicitNull).unwrap();
        let null_batch = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Insert(null),
        )]);
        assert_ne!(
            batch_fingerprint(&insert).unwrap(),
            batch_fingerprint(&null_batch).unwrap()
        );

        let patch_set = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(DocumentPatch {
                operations: vec![PatchOperation::Set {
                    field: "f".to_owned(),
                    values: FieldValues::Empty,
                }],
            }),
        )]);
        let patch_unset = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Update(DocumentPatch {
                operations: vec![PatchOperation::Unset {
                    field: "f".to_owned(),
                }],
            }),
        )]);
        assert_ne!(
            batch_fingerprint(&patch_set).unwrap(),
            batch_fingerprint(&patch_unset).unwrap()
        );
    }

    fn hex(fingerprint: [u8; 32]) -> String {
        use std::fmt::Write as _;
        let mut out = String::with_capacity(64);
        for byte in fingerprint {
            let _ = write!(&mut out, "{byte:02x}");
        }
        out
    }

    fn explicit_simple() -> MutationBatch {
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Keys(vec![key("a"), key("b")]),
            MutationAction::Delete,
        )])
    }

    fn explicit_complex() -> MutationBatch {
        use crate::contract::document::{Document, FieldValues};
        use crate::contract::value::FieldValue;
        let mut document = Document::new(key("x"));
        document
            .insert("f", FieldValues::Single(FieldValue::I64(7)))
            .unwrap();
        MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("x")),
                MutationAction::Insert(document),
            )
            .with_precondition(MutationPrecondition::ExpectedRevision(3)),
            MutationCommand::new(
                MutationTarget::Keys(vec![key("a"), key("b"), key("a")]),
                MutationAction::Delete,
            ),
        ])
    }

    fn query_batch(
        query: crate::contract::query::Query,
        max_matches: u64,
        expected_generation: Option<u64>,
    ) -> MutationBatch {
        use crate::contract::mutation::QueryMutationSelector;
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(QueryMutationSelector {
                query,
                max_matches,
                expected_generation,
            }),
            MutationAction::Delete,
        )])
    }

    fn sample_term(text: &str) -> crate::contract::query::Query {
        crate::contract::query::Query::Term {
            field: "f".to_owned(),
            value: crate::contract::value::FieldValue::Text(text.to_owned()),
        }
    }

    /// M3-AD09 compatibility: explicit-key-only batches must retain the exact
    /// pre-M3 fingerprints. These goldens were generated from the pre-change
    /// tree at commit `52af5ff`.
    #[test]
    fn explicit_key_only_fingerprints_are_byte_compatible() {
        assert_eq!(
            hex(batch_fingerprint(&explicit_simple()).unwrap()),
            "32fdde8e07232b76f7d685c9a2bb9fcbcb72a3be8392f939606ce85e5fad7530"
        );
        assert_eq!(
            hex(batch_fingerprint(&explicit_complex()).unwrap()),
            "10912b0310cba564a5fec81663849aa0bdf95d5f39c5b5293f719450bb71630a"
        );
    }

    /// The original M3-AD09 reproduced collision: distinct query ASTs used to
    /// share one fingerprint. The v2 query domain must distinguish them even
    /// when `max_matches` and `expected_generation` are identical.
    #[test]
    fn query_fingerprint_no_longer_collides_across_distinct_asts() {
        let match_all = query_batch(crate::contract::query::Query::MatchAll, 7, Some(3));
        let term = query_batch(sample_term("x"), 7, Some(3));
        assert_ne!(
            batch_fingerprint(&match_all).unwrap(),
            batch_fingerprint(&term).unwrap(),
            "M3-AD09 regression: distinct query selectors must not collide"
        );
        // Determinism and field sensitivity.
        assert_eq!(
            batch_fingerprint(&match_all).unwrap(),
            batch_fingerprint(&query_batch(
                crate::contract::query::Query::MatchAll,
                7,
                Some(3)
            ))
            .unwrap()
        );
        assert_ne!(
            batch_fingerprint(&match_all).unwrap(),
            batch_fingerprint(&query_batch(
                crate::contract::query::Query::MatchAll,
                8,
                Some(3)
            ))
            .unwrap()
        );
        assert_ne!(
            batch_fingerprint(&match_all).unwrap(),
            batch_fingerprint(&query_batch(
                crate::contract::query::Query::MatchAll,
                7,
                None
            ))
            .unwrap()
        );
    }

    #[test]
    fn query_fingerprint_is_domain_separated_from_explicit_key_fingerprints() {
        let query = query_batch(crate::contract::query::Query::MatchAll, 1, None);
        let explicit = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            MutationAction::Delete,
        )]);
        assert_ne!(
            batch_fingerprint(&query).unwrap(),
            batch_fingerprint(&explicit).unwrap()
        );
    }
}

#[cfg(test)]
mod ad16_tests {
    use super::*;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn token() -> IdempotencyKey {
        IdempotencyKey::new("tok").unwrap()
    }

    fn outcome(value: &str, intent: MutationIntent, revision: u64) -> MutationKeyOutcome {
        MutationKeyOutcome {
            key: key(value),
            intent,
            revision: Some(revision),
            replayed: false,
        }
    }

    fn command(matched: u64, keys: Vec<MutationKeyOutcome>) -> MutationBatchResponse {
        MutationBatchResponse {
            outcomes: vec![MutationCommandOutcome {
                command_index: 0,
                matched,
                keys,
            }],
            replayed: false,
        }
    }

    fn state_with(response: MutationBatchResponse) -> MutationStateV1 {
        MutationStateV1::from_parts(BTreeMap::new(), BTreeMap::new()).with_batch_replay(
            BTreeMap::from([(
                token(),
                BatchReplayRow {
                    token: token(),
                    fingerprint: [7u8; 32],
                    response,
                },
            )]),
        )
    }

    /// Encoder-side assertion: the response shape is rejected as corrupt.
    fn assert_encoder_rejects(label: &str, response: MutationBatchResponse) {
        let error = state_with(response)
            .encode()
            .expect_err(&format!("{label} must be rejected by the encoder"));
        assert!(
            matches!(
                &error,
                SegmentError::Corrupt { context, detail }
                    if *context == "mutation-state batch replay"
                        && detail == "command matched count does not match its key list"
            ),
            "{label}: unexpected error {error:?}"
        );
    }

    // ---- byte-level decoder fixtures (independent of the encoder) ----

    fn v2_container(payload: Vec<u8>) -> Vec<u8> {
        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.require_feature(FEATURE_MUTATION_STATE_V2, 1);
        builder.section(SectionKind::MutationState, 0, 0, payload);
        builder.build().unwrap()
    }

    /// One batch record whose response body is written by `body`.
    fn crafted_v2(body: impl FnOnce(&mut ByteWriter)) -> Vec<u8> {
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION_BATCH);
        payload.u32(0); // rows
        payload.u32(0); // single-key replay
        payload.u32(1); // batch replay records
        payload.len_prefixed_u16(b"tok").unwrap();
        payload.bytes(&[3u8; 32]);
        body(&mut payload);
        v2_container(payload.into_vec())
    }

    fn write_command(payload: &mut ByteWriter, matched: u64, keys: &[(u8, &str, Option<u64>)]) {
        payload.u32(1); // commands
        payload.u8(0); // response replayed flag
        payload.u32(0); // ordinal
        payload.u64(matched);
        payload.u32(u32::try_from(keys.len()).unwrap());
        for (intent, value, revision) in keys {
            payload.len_prefixed_u16(value.as_bytes()).unwrap();
            payload.u8(*intent);
            match revision {
                Some(revision) => {
                    payload.u8(1);
                    payload.u64(*revision);
                }
                None => payload.u8(0),
            }
            payload.u8(0); // persisted per-key replayed flag
        }
    }

    fn assert_decoder_rejects(label: &str, matched: u64, keys: &[(u8, &str, Option<u64>)]) {
        let bytes = crafted_v2(|payload| write_command(payload, matched, keys));
        let error = MutationStateV1::decode(&bytes, &SegmentLimits::default())
            .expect_err(&format!("{label} must be rejected by the decoder"));
        assert!(
            matches!(
                &error,
                SegmentError::Corrupt { context, detail }
                    if *context == "mutation-state batch replay"
                        && detail == "command matched count does not match its key list"
            ),
            "{label}: unexpected error {error:?}"
        );
    }

    // AD16-T01: ordinary equality with valid intents round-trips exactly.
    #[test]
    fn ad16_t01_equality_shapes_round_trip() {
        for response in [
            command(1, vec![outcome("a", MutationIntent::Upsert, 3)]),
            command(
                2,
                vec![
                    outcome("a", MutationIntent::Insert, 1),
                    outcome("b", MutationIntent::Delete, 2),
                ],
            ),
        ] {
            let state = state_with(response.clone());
            let bytes = state.encode().expect("valid equality shape");
            let decoded = MutationStateV1::decode(&bytes, &SegmentLimits::default()).unwrap();
            assert_eq!(decoded, state);
            let row = decoded.batch_replay_entry(&token()).expect("row");
            assert_eq!(row.response, response);
        }
    }

    // AD16-T02: zero matches with no key outcomes remains accepted (M3 no-op).
    #[test]
    fn ad16_t02_zero_match_empty_outcomes_round_trip() {
        let response = command(0, Vec::new());
        let state = state_with(response.clone());
        let bytes = state.encode().expect("zero-match no-op");
        let decoded = MutationStateV1::decode(&bytes, &SegmentLimits::default()).unwrap();
        assert_eq!(
            decoded.batch_replay_entry(&token()).unwrap().response,
            response
        );
    }

    // AD16-T03: the single approved exception round-trips with matched=0.
    #[test]
    fn ad16_t03_zero_match_single_insert_fallback_round_trips() {
        let response = command(0, vec![outcome("fallback", MutationIntent::Insert, 4)]);
        let state = state_with(response.clone());
        let bytes = state.encode().expect("approved fallback shape");
        let decoded = MutationStateV1::decode(&bytes, &SegmentLimits::default()).unwrap();
        assert_eq!(decoded, state);
        let row = decoded.batch_replay_entry(&token()).expect("row");
        assert_eq!(row.response, response);
        assert_eq!(row.response.outcomes[0].matched, 0);
        assert_eq!(row.response.outcomes[0].keys.len(), 1);
        assert_eq!(
            row.response.outcomes[0].keys[0].intent,
            MutationIntent::Insert
        );
        // Re-encoding the decoded state is byte-identical.
        assert_eq!(decoded.encode().unwrap(), bytes);
    }

    // AD16-T04..T08: every other cardinality/intent shape is corrupt, on both
    // the encoder and a hand-built decoder fixture.
    #[test]
    fn ad16_t04_zero_match_single_upsert_is_rejected() {
        assert_encoder_rejects(
            "matched=0 upsert",
            command(0, vec![outcome("a", MutationIntent::Upsert, 1)]),
        );
        assert_decoder_rejects("matched=0 upsert", 0, &[(1, "a", Some(1))]);
    }

    #[test]
    fn ad16_t05_zero_match_single_delete_is_rejected() {
        assert_encoder_rejects(
            "matched=0 delete",
            command(0, vec![outcome("a", MutationIntent::Delete, 1)]),
        );
        assert_decoder_rejects("matched=0 delete", 0, &[(2, "a", Some(1))]);
    }

    #[test]
    fn ad16_t06_zero_match_two_inserts_are_rejected() {
        assert_encoder_rejects(
            "matched=0 two inserts",
            command(
                0,
                vec![
                    outcome("a", MutationIntent::Insert, 1),
                    outcome("b", MutationIntent::Insert, 2),
                ],
            ),
        );
        assert_decoder_rejects(
            "matched=0 two inserts",
            0,
            &[(0, "a", Some(1)), (0, "b", Some(2))],
        );
    }

    #[test]
    fn ad16_t07_one_match_two_outcomes_is_rejected() {
        assert_encoder_rejects(
            "matched=1 two outcomes",
            command(
                1,
                vec![
                    outcome("a", MutationIntent::Insert, 1),
                    outcome("b", MutationIntent::Insert, 2),
                ],
            ),
        );
        assert_decoder_rejects(
            "matched=1 two outcomes",
            1,
            &[(0, "a", Some(1)), (0, "b", Some(2))],
        );
    }

    #[test]
    fn ad16_t08_two_matches_one_outcome_is_rejected() {
        assert_encoder_rejects(
            "matched=2 one outcome",
            command(2, vec![outcome("a", MutationIntent::Insert, 1)]),
        );
        assert_decoder_rejects("matched=2 one outcome", 2, &[(0, "a", Some(1))]);
    }

    // AD16-T09: the pre-existing malformed-v2 `matched mismatch` fixture shape
    // (matched > key count) is still corrupt.
    #[test]
    fn ad16_t09_large_matched_mismatch_is_still_rejected() {
        assert_decoder_rejects("matched=9 one outcome", 9, &[(2, "a", Some(5))]);
        assert_encoder_rejects(
            "matched=9 one outcome",
            command(9, vec![outcome("a", MutationIntent::Delete, 5)]),
        );
    }

    // AD16-T10: the moved decoder check must not bypass ordering, revision,
    // intent or trailing-byte validation for otherwise-valid cardinalities.
    #[test]
    fn ad16_t10_decoder_keeps_independent_validation() {
        let limits = SegmentLimits::default();
        let cases: Vec<(&str, Vec<u8>)> = vec![
            (
                "unsorted keys",
                crafted_v2(|payload| {
                    write_command(payload, 2, &[(0, "b", Some(1)), (0, "a", Some(2))]);
                }),
            ),
            (
                "duplicate keys",
                crafted_v2(|payload| {
                    write_command(payload, 2, &[(0, "a", Some(1)), (0, "a", Some(2))]);
                }),
            ),
            (
                "zero revision",
                crafted_v2(|payload| write_command(payload, 1, &[(0, "a", Some(0))])),
            ),
            (
                "invalid revision presence",
                crafted_v2(|payload| {
                    payload.u32(1);
                    payload.u8(0);
                    payload.u32(0);
                    payload.u64(1);
                    payload.u32(1);
                    payload.len_prefixed_u16(b"a").unwrap();
                    payload.u8(0);
                    payload.u8(9);
                }),
            ),
            (
                "unknown intent",
                crafted_v2(|payload| write_command(payload, 1, &[(9, "a", Some(1))])),
            ),
            (
                "persisted replay flag",
                crafted_v2(|payload| {
                    payload.u32(1);
                    payload.u8(1);
                    write_command(payload, 1, &[(0, "a", Some(1))]);
                }),
            ),
            (
                "trailing bytes",
                crafted_v2(|payload| {
                    write_command(payload, 1, &[(0, "a", Some(1))]);
                    payload.u8(0xFF);
                }),
            ),
            (
                "ordinal mismatch",
                crafted_v2(|payload| {
                    payload.u32(1);
                    payload.u8(0);
                    payload.u32(7);
                    payload.u64(1);
                    payload.u32(1);
                    payload.len_prefixed_u16(b"a").unwrap();
                    payload.u8(0);
                    payload.u8(1);
                    payload.u64(1);
                    payload.u8(0);
                }),
            ),
        ];
        for (label, bytes) in cases {
            assert!(
                MutationStateV1::decode(&bytes, &limits).is_err(),
                "{label} must still be rejected"
            );
        }
    }
}

#[cfg(test)]
mod m4_fingerprint_tests {
    use super::*;
    use crate::contract::document::FieldValues;
    use crate::contract::mutation::{MutationCommand, QueryMutationSelector};
    use crate::contract::value::FieldValue;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn hex(digest: [u8; 32]) -> String {
        use std::fmt::Write as _;
        let mut out = String::with_capacity(64);
        for byte in digest {
            let _ = write!(out, "{byte:02x}");
        }
        out
    }

    fn document(key_value: &str, title: &str, n: i64) -> Document {
        let mut document = Document::new(key(key_value));
        document
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text(title.to_owned())),
            )
            .unwrap();
        document
            .insert("n", FieldValues::Single(FieldValue::I64(n)))
            .unwrap();
        document
    }

    fn query_upsert(replacement: Document, fallback: Document) -> MutationBatch {
        MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(QueryMutationSelector {
                query: crate::contract::query::Query::MatchAll,
                max_matches: 5,
                expected_generation: Some(2),
            }),
            MutationAction::QueryUpsert {
                replacement,
                fallback,
            },
        )])
    }

    /// T21/T22: fingerprints generated by the pre-M4 code at base `4e64acb`
    /// (P0 commit `1c59e2c`), before the additive M4 tag `5` arm existed.
    /// They must stay byte-for-byte identical.
    #[test]
    fn m4_t21_t22_pre_m4_fingerprints_are_byte_compatible() {
        let explicit_delete_keys = MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Keys(vec![key("a"), key("b")]),
                MutationAction::Delete,
            )
            .with_precondition(MutationPrecondition::ExpectedRevision(3)),
        ]);
        // Exactly the payload used to generate the pre-M4 golden: title only.
        let mut inserted = Document::new(key("doc"));
        inserted
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("x".to_owned())),
            )
            .unwrap();
        let explicit_insert_delete = MutationBatch::new(vec![
            MutationCommand::new(
                MutationTarget::Key(key("doc")),
                MutationAction::Insert(inserted),
            ),
            MutationCommand::new(MutationTarget::Key(key("c")), MutationAction::Delete),
        ]);
        let m3_query_delete = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Query(QueryMutationSelector {
                query: crate::contract::query::Query::MatchAll,
                max_matches: 5,
                expected_generation: Some(2),
            }),
            MutationAction::Delete,
        )]);
        assert_eq!(
            hex(batch_fingerprint(&explicit_delete_keys).unwrap()),
            "fab46e5b6d465010a9e3d815118e9c7e2ce132b8e40794476acd660c21443d23"
        );
        assert_eq!(
            hex(batch_fingerprint(&explicit_insert_delete).unwrap()),
            "6a70edb3678eb0cc69a96bb239717bdf2ca4b768685810ceeb52d7b84d399ed1"
        );
        assert_eq!(
            hex(batch_fingerprint(&m3_query_delete).unwrap()),
            "f77197ed428a7d280f37164ee48b0966ae7b870a5a00d6801896e0649a7768f3"
        );
    }

    /// T32 (unit level): the M4 tag `5` fingerprint is deterministic and covers
    /// the replacement and fallback documents independently.
    #[test]
    fn m4_t32_query_upsert_fingerprint_is_deterministic_and_covers_both_documents() {
        let replacement = document("replacement", "title", 1);
        let fallback = document("fallback", "title", 2);
        let base = query_upsert(replacement.clone(), fallback.clone());
        let baseline = batch_fingerprint(&base).unwrap();
        assert_eq!(batch_fingerprint(&base).unwrap(), baseline);

        let mut changed_replacement = replacement.clone();
        changed_replacement
            .insert("n", FieldValues::Single(FieldValue::I64(9)))
            .unwrap();
        let replacement_changed =
            batch_fingerprint(&query_upsert(changed_replacement, fallback.clone())).unwrap();
        assert_ne!(replacement_changed, baseline);

        let mut changed_fallback = fallback.clone();
        changed_fallback
            .insert(
                "title",
                FieldValues::Single(FieldValue::Text("other".to_owned())),
            )
            .unwrap();
        let fallback_changed =
            batch_fingerprint(&query_upsert(replacement, changed_fallback)).unwrap();
        assert_ne!(fallback_changed, baseline);
        assert_ne!(fallback_changed, replacement_changed);

        // The M4 action lives in the query-inclusive v2 domain, distinct from
        // the equivalent explicit-key tag-1 upsert fingerprint.
        let explicit_upsert = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("replacement")),
            MutationAction::Upsert(document("replacement", "title", 1)),
        )]);
        assert_ne!(batch_fingerprint(&explicit_upsert).unwrap(), baseline);
    }
}

/// PR 15I-A compact payload version 3: codec, compatibility and budget tests.
#[cfg(test)]
mod pr15i_a_v3_tests {
    use super::*;
    use crate::contract::mutation::MutationCommand;
    use crate::segment::format::SectionEntry;

    const V3_FEATURE: (u16, u16) = (FEATURE_MUTATION_STATE_V3, 1);
    const V2_FEATURE: (u16, u16) = (FEATURE_MUTATION_STATE_V2, 1);

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).unwrap()
    }

    fn token(value: &str) -> IdempotencyKey {
        IdempotencyKey::new(value).unwrap()
    }

    fn live(k: &str, rev: u64, seg: &str, doc: u64) -> KeyRow {
        KeyRow::live(key(k), rev, seg, doc)
    }

    fn deleted(k: &str, rev: u64) -> KeyRow {
        KeyRow::deleted(key(k), rev)
    }

    fn state_of(rows: Vec<KeyRow>) -> MutationStateV1 {
        let rows = rows.into_iter().map(|row| (row.key.clone(), row)).collect();
        MutationStateV1::from_parts(rows, BTreeMap::new())
    }

    fn state_of_all(
        rows: Vec<KeyRow>,
        replay: Vec<ReplayRow>,
        batch: Vec<BatchReplayRow>,
    ) -> MutationStateV1 {
        let rows = rows.into_iter().map(|row| (row.key.clone(), row)).collect();
        let replay = replay
            .into_iter()
            .map(|row| (row.token.clone(), row))
            .collect();
        let batch = batch
            .into_iter()
            .map(|row| (row.token.clone(), row))
            .collect();
        MutationStateV1::from_parts(rows, replay).with_batch_replay(batch)
    }

    fn encode(state: &MutationStateV1, version_2_active: bool) -> Vec<u8> {
        state
            .encode_v3(version_2_active, &SegmentLimits::default())
            .unwrap()
    }

    fn decode(bytes: &[u8]) -> (MutationStateV1, u16) {
        MutationStateV1::decode_with_version(bytes, &SegmentLimits::default()).unwrap()
    }

    fn decode_err(bytes: &[u8]) -> SegmentError {
        MutationStateV1::decode(bytes, &SegmentLimits::default()).unwrap_err()
    }

    fn body(bytes: &[u8]) -> &[u8] {
        let view = parse_container(bytes, &SegmentLimits::default()).unwrap();
        view.body(SectionKind::MutationState).unwrap()
    }

    /// Walk the leading V3 segment table of a payload body.
    fn table_of(body: &[u8]) -> Vec<String> {
        assert_eq!(
            u16::from_le_bytes([body[0], body[1]]),
            MUTATION_STATE_VERSION_COMPACT
        );
        let count = u32::from_le_bytes([body[2], body[3], body[4], body[5]]) as usize;
        let mut position = 6;
        let mut out = Vec::new();
        for _ in 0..count {
            let len = u16::from_le_bytes([body[position], body[position + 1]]) as usize;
            position += 2;
            out.push(
                std::str::from_utf8(&body[position..position + len])
                    .unwrap()
                    .to_owned(),
            );
            position += len;
        }
        out
    }

    fn replay_row(tok: &str, k: &str, rev: u64) -> ReplayRow {
        ReplayRow {
            token: token(tok),
            fingerprint: [7u8; 32],
            key: key(k),
            intent: MutationIntent::Upsert,
            revision: rev,
        }
    }

    fn batch_row(tok: &str, fingerprint: u8, response: MutationBatchResponse) -> BatchReplayRow {
        BatchReplayRow {
            token: token(tok),
            fingerprint: [fingerprint; 32],
            response,
        }
    }

    fn simple_batch_response() -> MutationBatchResponse {
        MutationBatchResponse {
            outcomes: vec![MutationCommandOutcome {
                command_index: 0,
                matched: 1,
                keys: vec![MutationKeyOutcome {
                    key: key("a"),
                    intent: MutationIntent::Delete,
                    revision: Some(4),
                    replayed: false,
                }],
            }],
            replayed: false,
        }
    }

    fn v3_payload(table: &[&[u8]]) -> ByteWriter {
        let mut payload = ByteWriter::new();
        payload.u16(MUTATION_STATE_VERSION_COMPACT);
        payload.u32(table.len() as u32);
        for id in table {
            payload.len_prefixed_u16(id).unwrap();
        }
        payload
    }

    fn live_row(payload: &mut ByteWriter, k: &str, rev: u64, ordinal: u64, doc: u64) {
        payload.len_prefixed_u16(k.as_bytes()).unwrap();
        payload.u64(rev);
        payload.u8(1);
        payload.varint(ordinal);
        payload.varint(doc);
    }

    fn live_row_raw_ordinal(payload: &mut ByteWriter, k: &str, rev: u64, ordinal: &[u8], doc: u64) {
        payload.len_prefixed_u16(k.as_bytes()).unwrap();
        payload.u64(rev);
        payload.u8(1);
        payload.bytes(ordinal);
        payload.varint(doc);
    }

    fn deleted_row(payload: &mut ByteWriter, k: &str, rev: u64) {
        payload.len_prefixed_u16(k.as_bytes()).unwrap();
        payload.u64(rev);
        payload.u8(0);
    }

    fn v3_container(payload: Vec<u8>, required_v3: bool, optional_v3: bool) -> Vec<u8> {
        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        if required_v3 {
            builder.require_feature(FEATURE_MUTATION_STATE_V3, 1);
        }
        if optional_v3 {
            builder.optional_feature(FEATURE_MUTATION_STATE_V3, 1);
        }
        builder.section(SectionKind::MutationState, 0, 0, payload);
        builder.build().unwrap()
    }

    fn crafted(payload: ByteWriter) -> Vec<u8> {
        v3_container(payload.into_vec(), true, false)
    }

    fn many_segments(count: usize) -> MutationStateV1 {
        let rows = (0..count)
            .map(|index| KeyRow::live(key(&format!("k{index:03}")), 1, format!("s{index:04}"), 0))
            .collect();
        state_of(rows)
    }

    // ---------------- U01-U06: determinism and canonical table -------------

    #[test]
    fn u01_v3_encoding_is_deterministic_in_both_history_modes() {
        let state = state_of_all(
            vec![live("a", 2, "s-1", 0), deleted("b", 1)],
            vec![replay_row("tok", "a", 2)],
            vec![batch_row("btok", 7, simple_batch_response())],
        );
        for version_2_active in [false, true] {
            let first = encode(&state, version_2_active);
            let second = encode(&state, version_2_active);
            assert_eq!(first, second);
            let (decoded, version) = decode(&first);
            assert_eq!(version, MUTATION_STATE_VERSION_COMPACT);
            assert_eq!(decoded, state);
        }
    }

    #[test]
    fn u02_insertion_order_and_shared_segment_do_not_change_bytes() {
        let mut first: BTreeMap<DocumentKey, KeyRow> = BTreeMap::new();
        first.insert(key("a"), live("a", 1, "s-shared", 0));
        first.insert(key("b"), live("b", 1, "s-shared", 1));
        let mut second: BTreeMap<DocumentKey, KeyRow> = BTreeMap::new();
        second.insert(key("b"), live("b", 1, "s-shared", 1));
        second.insert(key("a"), live("a", 1, "s-shared", 0));
        let left = MutationStateV1::from_parts(first, BTreeMap::new());
        let right = MutationStateV1::from_parts(second, BTreeMap::new());
        let left_bytes = encode(&left, false);
        let right_bytes = encode(&right, false);
        assert_eq!(left_bytes, right_bytes);
        assert_eq!(table_of(body(&left_bytes)), vec!["s-shared".to_owned()]);
    }

    #[test]
    fn u03_dictionary_is_sorted_by_raw_bytes() {
        let mut first: BTreeMap<DocumentKey, KeyRow> = BTreeMap::new();
        first.insert(key("a"), live("a", 1, "s-b", 0));
        first.insert(key("b"), live("b", 1, "s-a", 1));
        let mut second: BTreeMap<DocumentKey, KeyRow> = BTreeMap::new();
        second.insert(key("b"), live("b", 1, "s-a", 1));
        second.insert(key("a"), live("a", 1, "s-b", 0));
        let left = encode(&MutationStateV1::from_parts(first, BTreeMap::new()), false);
        let right = encode(&MutationStateV1::from_parts(second, BTreeMap::new()), false);
        assert_eq!(left, right);
        assert_eq!(
            table_of(body(&left)),
            vec!["s-a".to_owned(), "s-b".to_owned()]
        );
    }

    #[test]
    fn u04_empty_state_round_trips() {
        let state = MutationStateV1::empty();
        let bytes = encode(&state, false);
        let payload = body(&bytes);
        assert_eq!(
            u32::from_le_bytes([payload[2], payload[3], payload[4], payload[5]]),
            0
        );
        let (decoded, version) = decode(&bytes);
        assert_eq!(version, 3);
        assert_eq!(decoded, state);
        assert_eq!(decoded.row_count(), 0);
        assert_eq!(decoded.replay_count(), 0);
        assert_eq!(decoded.batch_replay_count(), 0);
    }

    #[test]
    fn u05_deleted_only_rows_have_an_empty_table_and_keep_tombstones() {
        let state = state_of(vec![deleted("a", 3), deleted("b", 2)]);
        let bytes = encode(&state, false);
        assert!(table_of(body(&bytes)).is_empty());
        let (decoded, _) = decode(&bytes);
        assert_eq!(decoded, state);
        assert_eq!(decoded.revision(&key("a")), 3);
        assert!(!decoded.is_live(&key("a")));
        assert!(decoded.rows().iter().all(|row| row.segment_id.is_none()));
    }

    #[test]
    fn u06_live_and_deleted_rows_share_one_table_entry() {
        let state = state_of(vec![live("a", 2, "s-1", 0), deleted("b", 1)]);
        let bytes = encode(&state, false);
        assert_eq!(table_of(body(&bytes)), vec!["s-1".to_owned()]);
        let (decoded, _) = decode(&bytes);
        assert_eq!(decoded, state);
        assert_eq!(decoded.rows()[0].segment_id.as_deref(), Some("s-1"));
        assert!(decoded.rows()[1].segment_id.is_none());
    }

    // ---------------- U07-U12: malformed dictionary / ordinal table ---------

    #[test]
    fn u07_out_of_range_ordinal_is_corruption() {
        let mut payload = v3_payload(&[b"s-a"]);
        payload.u32(1);
        live_row(&mut payload, "a", 1, 1, 0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u08_duplicate_table_ids_are_corruption() {
        let mut payload = v3_payload(&[b"s-a", b"s-a"]);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u09_descending_table_ids_are_corruption() {
        let mut payload = v3_payload(&[b"s-b", b"s-a"]);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u10_unreferenced_table_entries_are_corruption() {
        let mut payload = v3_payload(&[b"s-a", b"s-b"]);
        payload.u32(1);
        live_row(&mut payload, "a", 1, 0, 0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u11_empty_table_ids_are_corruption() {
        let mut payload = v3_payload(&[b""]);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u12_invalid_utf8_table_entries_are_rejected_even_when_unused() {
        let mut payload = v3_payload(&[&[0xFF]]);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::InvalidUtf8 { .. }
        ));
    }

    // ---------------- U13-U17: canonical varints ---------------------------

    #[test]
    fn u13_ordinal_127_is_one_byte() {
        let state = many_segments(128);
        let bytes = encode(&state, false);
        let payload = body(&bytes);
        assert_eq!(payload[payload.len() - 10], 0x7F);
        assert_eq!(decode(&bytes).0, state);
    }

    #[test]
    fn u14_ordinal_128_is_two_bytes() {
        let state = many_segments(129);
        let bytes = encode(&state, false);
        let payload = body(&bytes);
        assert_eq!(payload[payload.len() - 11], 0x80);
        assert_eq!(payload[payload.len() - 10], 0x01);
        assert_eq!(decode(&bytes).0, state);
    }

    #[test]
    fn u15_ordinal_casting_never_wraps() {
        for ordinal in [1u64, 2, u64::from(u32::MAX), u64::from(u32::MAX) + 1] {
            let mut payload = v3_payload(&[b"s-a"]);
            payload.u32(1);
            live_row(&mut payload, "a", 1, ordinal, 0);
            payload.u32(0);
            payload.u32(0);
            assert!(
                matches!(decode_err(&crafted(payload)), SegmentError::Corrupt { .. }),
                "ordinal {ordinal} must be typed corruption"
            );
        }
    }

    #[test]
    fn u16_noncanonical_ordinal_varints_are_rejected() {
        for ordinal in [&[0x80u8, 0x00][..], &[0x80u8; 11][..]] {
            let mut payload = v3_payload(&[b"s-a"]);
            payload.u32(1);
            live_row_raw_ordinal(&mut payload, "a", 1, ordinal, 0);
            payload.u32(0);
            payload.u32(0);
            assert!(matches!(
                decode_err(&crafted(payload)),
                SegmentError::InvalidVarint { .. }
            ));
        }
    }

    #[test]
    fn u17_physical_doc_ids_round_trip_at_boundaries() {
        let state = state_of(vec![
            live("a", 1, "s-1", 0),
            live("b", 1, "s-1", 127),
            live("c", 1, "s-1", 128),
            live("d", 1, "s-1", u64::MAX),
        ]);
        let bytes = encode(&state, false);
        let (decoded, _) = decode(&bytes);
        assert_eq!(decoded, state);
        assert_eq!(
            decoded
                .rows()
                .iter()
                .filter_map(|row| row.doc_id)
                .collect::<Vec<_>>(),
            vec![0, 127, 128, u64::MAX]
        );
    }

    // ---------------- U18-U20: encoder/decoder pointer integrity -----------

    #[test]
    fn u18_encoder_rejects_status_pointer_mismatch() {
        let rows = vec![
            KeyRow {
                key: key("a"),
                revision: 1,
                status: KeyStatus::Live,
                segment_id: Some("s-1".to_owned()),
                doc_id: None,
            },
            KeyRow {
                key: key("b"),
                revision: 1,
                status: KeyStatus::Deleted,
                segment_id: Some("s-1".to_owned()),
                doc_id: Some(3),
            },
        ];
        for row in rows {
            let state = MutationStateV1::from_parts(
                BTreeMap::from([(row.key.clone(), row)]),
                BTreeMap::new(),
            );
            assert!(matches!(
                state.encode_v3(false, &SegmentLimits::default()),
                Err(SegmentError::Corrupt { .. })
            ));
        }
    }

    #[test]
    fn u19_noncanonical_doc_id_varints_are_rejected() {
        let crafted_ids: [&[u8]; 3] = [
            &[0x80, 0x00],
            &[
                0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01,
            ],
            &[0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x02],
        ];
        for doc_ids in crafted_ids {
            let mut payload = v3_payload(&[b"s-a"]);
            payload.u32(1);
            payload.len_prefixed_u16(b"a").unwrap();
            payload.u64(1);
            payload.u8(1);
            payload.varint(0);
            payload.bytes(doc_ids);
            payload.u32(0);
            payload.u32(0);
            assert!(matches!(
                decode_err(&crafted(payload)),
                SegmentError::InvalidVarint { .. }
            ));
        }
    }

    #[test]
    fn u20_truncation_and_trailing_bytes_never_yield_partial_state() {
        let state = state_of_all(
            vec![live("a", 2, "s-1", 0), deleted("b", 1)],
            vec![replay_row("tok", "a", 2)],
            vec![batch_row("btok", 4, simple_batch_response())],
        );
        let bytes = encode(&state, true);
        for cut in 0..bytes.len() {
            assert!(
                MutationStateV1::decode(&bytes[..cut], &SegmentLimits::default()).is_err(),
                "cut {cut} must not yield state"
            );
        }
        // A valid container whose payload has one extra byte fails EOF.
        let mut payload = v3_payload(&[b"s-1"]);
        payload.u32(1);
        live_row(&mut payload, "a", 1, 0, 0);
        payload.u32(0);
        payload.u32(0);
        payload.u8(0xFF);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    // ---------------- U21-U25: logical equivalence and replay --------------

    #[test]
    fn u21_v1_and_v3_decode_to_the_same_logical_state() {
        let state = state_of(vec![live("a", 2, "s-1", 4), deleted("b", 1)]);
        let v1 = state.encode().unwrap();
        let v3 = encode(&state, false);
        let (v1_state, v1_version) = decode(&v1);
        let (v3_state, v3_version) = decode(&v3);
        assert_eq!(v1_version, MUTATION_STATE_VERSION);
        assert_eq!(v3_version, MUTATION_STATE_VERSION_COMPACT);
        assert_eq!(v1_state, v3_state);
        assert_eq!(v3_state, state);
    }

    #[test]
    fn u22_v2_and_v3_preserve_batch_replay() {
        let state = state_of_all(
            vec![live("a", 2, "s-1", 0), deleted("b", 1)],
            vec![replay_row("tok", "a", 2)],
            vec![batch_row("btok", 5, simple_batch_response())],
        );
        let v2 = state.encode_with_mode(true).unwrap();
        let v3 = encode(&state, true);
        let (v2_state, v2_version) = decode(&v2);
        let (v3_state, v3_version) = decode(&v3);
        assert_eq!(v2_version, MUTATION_STATE_VERSION_BATCH);
        assert_eq!(v3_version, MUTATION_STATE_VERSION_COMPACT);
        assert_eq!(v2_state, v3_state);
        assert_eq!(v3_state, state);
    }

    #[test]
    fn u23_v2_and_v3_replay_suffix_bytes_are_identical() {
        let replay = vec![replay_row("tok-a", "a", 2), replay_row("tok-b", "b", 3)];
        let batch = vec![batch_row("btok", 9, simple_batch_response())];
        let state = state_of_all(vec![], replay, batch);
        let v2 = state.encode_with_mode(true).unwrap();
        let v3 = encode(&state, true);
        // V2 body: version u16 then an empty row count u32, then the replay block.
        let v2_suffix = &body(&v2)[2 + 4..];
        // V3 body: version u16 then an empty table u32, empty row count u32, replay.
        let v3_suffix = &body(&v3)[2 + 4 + 4..];
        assert!(v3_suffix.len() > 8);
        assert_eq!(v2_suffix, v3_suffix);
    }

    #[test]
    fn u24_distinct_query_fingerprints_survive_encoding() {
        use crate::contract::mutation::QueryMutationSelector;
        use crate::contract::query::Query;
        let make = |max_matches: u64| {
            MutationBatch::new(vec![MutationCommand::new(
                MutationTarget::Query(QueryMutationSelector {
                    query: Query::MatchAll,
                    max_matches,
                    expected_generation: Some(3),
                }),
                MutationAction::Delete,
            )])
        };
        let first = batch_fingerprint(&make(7)).unwrap();
        let second = batch_fingerprint(&make(8)).unwrap();
        assert_ne!(first, second);
        let state = state_of_all(
            vec![],
            vec![],
            vec![
                BatchReplayRow {
                    token: token("t-1"),
                    fingerprint: first,
                    response: simple_batch_response(),
                },
                BatchReplayRow {
                    token: token("t-2"),
                    fingerprint: second,
                    response: simple_batch_response(),
                },
            ],
        );
        let (decoded, _) = decode(&encode(&state, true));
        let rows = decoded.batch_replay_rows();
        assert_eq!(rows[0].fingerprint, first);
        assert_eq!(rows[1].fingerprint, second);
        assert_ne!(rows[0].fingerprint, rows[1].fingerprint);
    }

    #[test]
    fn u25_replayed_response_preserves_ordinals_matched_and_flags() {
        let response = MutationBatchResponse {
            outcomes: vec![
                MutationCommandOutcome {
                    command_index: 0,
                    matched: 2,
                    keys: vec![
                        MutationKeyOutcome {
                            key: key("a"),
                            intent: MutationIntent::Insert,
                            revision: Some(3),
                            replayed: false,
                        },
                        MutationKeyOutcome {
                            key: key("b"),
                            intent: MutationIntent::Delete,
                            revision: Some(1),
                            replayed: false,
                        },
                    ],
                },
                MutationCommandOutcome {
                    command_index: 1,
                    matched: 0,
                    keys: vec![MutationKeyOutcome {
                        key: key("c"),
                        intent: MutationIntent::Insert,
                        revision: Some(1),
                        replayed: false,
                    }],
                },
            ],
            replayed: false,
        };
        let state = state_of_all(vec![], vec![], vec![batch_row("tok", 2, response.clone())]);
        let (decoded, _) = decode(&encode(&state, true));
        let stored = decoded.batch_replay_entry(&token("tok")).unwrap();
        assert_eq!(stored.response.outcomes[0].command_index, 0);
        assert_eq!(stored.response.outcomes[1].command_index, 1);
        assert_eq!(stored.response.outcomes[0].matched, 2);
        assert_eq!(stored.response.outcomes[1].matched, 0);
        let replayed = stored.replay_response();
        assert!(replayed.replayed);
        assert!(
            replayed
                .outcomes
                .iter()
                .flat_map(|command| command.keys.iter())
                .all(|outcome| outcome.replayed)
        );
        assert_eq!(replayed.outcomes[0].keys[0].revision, Some(3));
        assert_eq!(replayed.outcomes[0].keys[1].intent, MutationIntent::Delete);
        assert_eq!(replayed.outcomes[1].keys[0].key, key("c"));
    }

    // ---------------- U26-U33: version and feature compatibility -----------

    #[test]
    fn u26_frozen_v1_fixture_is_unchanged() {
        const V1_FIXTURE: &[u8] = include_bytes!("../../tests/fixtures/m1/mutation_state_v1.bin");
        assert_eq!(
            ContentDigest::sha256_v1(V1_FIXTURE).to_hex(),
            "753094d07734fbbebf5b535d585af83107d241c917e7e731462d2af972efc469"
        );
        let (decoded, version) =
            MutationStateV1::decode_with_version(V1_FIXTURE, &SegmentLimits::default()).unwrap();
        assert_eq!(version, MUTATION_STATE_VERSION);
        assert_eq!(decoded.encode().unwrap(), V1_FIXTURE);
    }

    #[test]
    fn u27_valid_v2_with_the_v2_marker_still_reads() {
        let state = state_of_all(
            vec![live("a", 1, "s-1", 0)],
            vec![],
            vec![batch_row("tok", 1, simple_batch_response())],
        );
        let bytes = state.encode_with_mode(true).unwrap();
        let view = parse_container(&bytes, &SegmentLimits::default()).unwrap();
        assert!(view.required_features().contains(&V2_FEATURE));
        assert!(!view.required_features().contains(&V3_FEATURE));
        let (decoded, version) = decode(&bytes);
        assert_eq!(version, MUTATION_STATE_VERSION_BATCH);
        assert_eq!(decoded, state);
    }

    #[test]
    fn u28_v3_payload_without_the_required_v3_feature_is_corruption() {
        let mut payload = v3_payload(&[]);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&v3_container(payload.into_vec(), false, false)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u29_v3_feature_in_optional_only_is_rejected() {
        let mut payload = v3_payload(&[]);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&v3_container(payload.into_vec(), false, true)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u30_required_v3_feature_with_a_legacy_payload_is_corruption() {
        for version in [MUTATION_STATE_VERSION, MUTATION_STATE_VERSION_BATCH] {
            let mut payload = ByteWriter::new();
            payload.u16(version);
            payload.u32(0);
            payload.u32(0);
            if version == MUTATION_STATE_VERSION_BATCH {
                payload.u32(0);
            }
            assert!(matches!(
                decode_err(&v3_container(payload.into_vec(), true, false)),
                SegmentError::Corrupt { .. }
            ));
        }
    }

    #[test]
    fn u31_unknown_required_features_fail_before_payload_decode() {
        let mut builder = ContainerBuilder::new(ContainerKind::MutationState, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.require_feature(0x7FFF, 1);
        builder.section(SectionKind::MutationState, 0, 0, vec![0xFF, 0xFF]);
        let bytes = builder.build().unwrap();
        assert!(matches!(
            decode_err(&bytes),
            SegmentError::UnsupportedFeature {
                feature_id: 0x7FFF,
                ..
            }
        ));
    }

    #[test]
    fn u32_unknown_payload_version_is_corruption() {
        let mut payload = ByteWriter::new();
        payload.u16(4);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u33_a_pre_v3_reader_rejects_the_v3_required_feature() {
        let bytes = encode(&state_of(vec![live("a", 1, "s-1", 0)]), false);
        let view = parse_container(&bytes, &SegmentLimits::default()).unwrap();
        assert!(view.required_features().contains(&V3_FEATURE));
        let pre_v3_table: Vec<(u16, u16)> = crate::segment::format::SUPPORTED_FEATURES
            .iter()
            .copied()
            .filter(|(id, _)| *id < FEATURE_MUTATION_STATE_V3)
            .collect();
        assert!(!pre_v3_table.contains(&V3_FEATURE));
        assert!(
            view.required_features()
                .iter()
                .any(|feature| !pre_v3_table.contains(feature)),
            "a pre-V3 reader must fail closed on the V3 required feature"
        );
    }

    // ---------------- U34-U41: resource budgets ----------------------------

    #[test]
    fn u34_entry_limit_is_checked_before_table_allocation() {
        let mut payload = v3_payload(&[]);
        let mut payload_writer = payload_for_count(&mut payload, 3);
        payload_writer.u32(0);
        payload_writer.u32(0);
        let limits = SegmentLimits::default().with_max_decoded_entries(2);
        assert!(matches!(
            MutationStateV1::decode(&crafted(payload_writer), &limits),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    /// Replace the just-written table count/entries with a bare declared count.
    fn payload_for_count(payload: &mut ByteWriter, declared: u32) -> ByteWriter {
        let _ = payload;
        let mut crafted = ByteWriter::new();
        crafted.u16(MUTATION_STATE_VERSION_COMPACT);
        crafted.u32(declared);
        for index in 0..declared {
            crafted
                .len_prefixed_u16(&[b'a' + (index % 26) as u8])
                .unwrap();
        }
        crafted
    }

    #[test]
    fn u35_dictionary_allocation_boundary_is_exact() {
        let section_entry = std::mem::size_of::<SectionEntry>() as u64;
        let limit = section_entry.div_ceil(16) * 16;
        let exact = (limit / 16) as u32;
        let ids: Vec<Vec<u8>> = (0..exact).map(|index| vec![b'a' + index as u8]).collect();
        let borrowed: Vec<&[u8]> = ids.iter().map(Vec::as_slice).collect();
        let mut payload = v3_payload(&borrowed);
        payload.u32(0);
        payload.u32(0);
        payload.u32(0);
        let limits = SegmentLimits::default().with_max_single_allocation(limit);
        // Exactly at the per-allocation limit the dictionary check passes and
        // the decode fails later for the semantically invalid empty row set.
        assert!(matches!(
            MutationStateV1::decode(&crafted(payload), &limits),
            Err(SegmentError::Corrupt { .. })
        ));

        let over_ids: Vec<Vec<u8>> = (0..=exact).map(|index| vec![b'a' + index as u8]).collect();
        let over_borrowed: Vec<&[u8]> = over_ids.iter().map(Vec::as_slice).collect();
        let mut over = v3_payload(&over_borrowed);
        over.u32(0);
        over.u32(0);
        over.u32(0);
        assert!(matches!(
            MutationStateV1::decode(&crafted(over), &limits),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn u36_usage_bitmap_allocation_boundary_is_exact() {
        // The `&str` table check subsumes the byte-per-entry usage bitmap
        // (`size_of::<&str>() > size_of::<u8>()`), so the bitmap boundary is
        // asserted on the exact call the decoder makes.
        let limits = SegmentLimits::default().with_max_single_allocation(3);
        assert!(limits.check_alloc::<u8>(3).is_ok());
        assert!(matches!(
            limits.check_alloc::<u8>(4),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn u37_row_capacity_boundary_is_exact() {
        let row_bytes = std::mem::size_of::<KeyRow>() as u64;
        let limit = row_bytes * 2;
        let mut payload = v3_payload(&[]);
        payload.u32(2);
        deleted_row(&mut payload, "a", 1);
        deleted_row(&mut payload, "b", 1);
        payload.u32(0);
        payload.u32(0);
        let exact = SegmentLimits::default().with_max_single_allocation(limit);
        assert!(MutationStateV1::decode(&crafted(payload), &exact).is_ok());
        let one_over = SegmentLimits::default().with_max_single_allocation(limit - 1);
        let mut payload = v3_payload(&[]);
        payload.u32(2);
        deleted_row(&mut payload, "a", 1);
        deleted_row(&mut payload, "b", 1);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            MutationStateV1::decode(&crafted(payload), &one_over),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn u38_cumulative_decode_charge_boundary_is_exact() {
        let exact = std::mem::size_of::<KeyRow>() as u64 + 1;
        let build = || {
            let mut payload = v3_payload(&[]);
            payload.u32(1);
            deleted_row(&mut payload, "a", 1);
            payload.u32(0);
            payload.u32(0);
            crafted(payload)
        };
        assert!(
            MutationStateV1::decode(
                &build(),
                &SegmentLimits::default().with_max_section_decode_bytes(exact)
            )
            .is_ok()
        );
        assert!(matches!(
            MutationStateV1::decode(
                &build(),
                &SegmentLimits::default().with_max_section_decode_bytes(exact - 1)
            ),
            Err(SegmentError::LimitExceeded { .. })
        ));
    }

    #[test]
    fn u39_impossible_counts_do_not_allocate() {
        let mut crafted_count = ByteWriter::new();
        crafted_count.u16(MUTATION_STATE_VERSION_COMPACT);
        crafted_count.u32(u32::MAX);
        let error = decode_err(&crafted(crafted_count));
        assert!(matches!(
            error,
            SegmentError::LimitExceeded { .. } | SegmentError::Truncated { .. }
        ));

        let mut crafted_rows = ByteWriter::new();
        crafted_rows.u16(MUTATION_STATE_VERSION_COMPACT);
        crafted_rows.u32(0);
        crafted_rows.u32(u32::MAX);
        let error = decode_err(&crafted(crafted_rows));
        assert!(matches!(
            error,
            SegmentError::LimitExceeded { .. } | SegmentError::Truncated { .. }
        ));
    }

    #[test]
    fn u40_invalid_revisions_and_ordering_are_typed_rejections() {
        // Zero revision.
        let mut payload = v3_payload(&[]);
        payload.u32(1);
        deleted_row(&mut payload, "a", 0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));

        // Unsorted and duplicated keys.
        for keys in [("b", "a"), ("a", "a")] {
            let mut payload = v3_payload(&[]);
            payload.u32(2);
            deleted_row(&mut payload, keys.0, 1);
            deleted_row(&mut payload, keys.1, 1);
            payload.u32(0);
            payload.u32(0);
            assert!(matches!(
                decode_err(&crafted(payload)),
                SegmentError::Corrupt { .. }
            ));
        }

        // Zero replay revision.
        let mut payload = v3_payload(&[]);
        payload.u32(0);
        payload.u32(1);
        payload.len_prefixed_u16(b"tok").unwrap();
        payload.bytes(&[0u8; 32]);
        payload.len_prefixed_u16(b"a").unwrap();
        payload.u8(1);
        payload.u64(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));

        // Unsorted replay tokens.
        let mut payload = v3_payload(&[]);
        payload.u32(0);
        payload.u32(2);
        for tok in ["z", "a"] {
            payload.len_prefixed_u16(tok.as_bytes()).unwrap();
            payload.bytes(&[0u8; 32]);
            payload.len_prefixed_u16(b"a").unwrap();
            payload.u8(1);
            payload.u64(1);
        }
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u41_segment_id_length_boundary() {
        let max = "s".repeat(usize::from(u16::MAX));
        let state = state_of(vec![live("a", 1, &max, 0)]);
        let bytes = encode(&state, false);
        assert_eq!(decode(&bytes).0, state);

        let too_long = "s".repeat(usize::from(u16::MAX) + 1);
        let state = state_of(vec![live("a", 1, &too_long, 0)]);
        assert!(matches!(
            state.encode_v3(false, &SegmentLimits::default()),
            Err(SegmentError::LengthMismatch { .. })
        ));
    }

    // ---------------- U42-U43: container integrity and full-row validation -

    #[test]
    fn u42_container_integrity_precedes_row_processing() {
        let mut bytes = encode(&state_of(vec![live("a", 1, "s-1", 0)]), false);
        let last = bytes.len() - 1;
        bytes[last] ^= 0xFF;
        assert!(matches!(
            decode_err(&bytes),
            SegmentError::DigestMismatch { .. }
        ));

        let mut builder = ContainerBuilder::new(ContainerKind::Segment, 0);
        builder.require_feature(FEATURE_MUTATION_STATE, 1);
        builder.section(SectionKind::MutationState, 0, 0, vec![0, 0]);
        assert!(matches!(
            decode_err(&builder.build().unwrap()),
            SegmentError::Corrupt { .. }
        ));
    }

    #[test]
    fn u43_noncanonical_bytes_are_rejected_in_every_row() {
        // The first row is valid; the second uses an overlong ordinal varint and
        // must be rejected rather than skipped.
        let mut payload = v3_payload(&[b"s-a", b"s-b"]);
        payload.u32(2);
        live_row(&mut payload, "a", 1, 0, 0);
        live_row_raw_ordinal(&mut payload, "b", 1, &[0x81, 0x00], 0);
        payload.u32(0);
        payload.u32(0);
        assert!(matches!(
            decode_err(&crafted(payload)),
            SegmentError::InvalidVarint { .. }
        ));
    }
}
