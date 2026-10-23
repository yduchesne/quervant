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
    FEATURE_MUTATION_STATE_V2, SectionKind, parse_container,
};
use super::super::segment::schema::field_type_tag;
use super::super::segment::value::{encode_scalar, state_of};
use super::super::segment::{SegmentError, SegmentLimits, SegmentResult};

/// Payload version 1: key rows plus the single-key idempotency replay ledger.
pub(crate) const MUTATION_STATE_VERSION: u16 = 1;
/// Payload version 2: version 1 plus durable atomic-batch replay records.
pub(crate) const MUTATION_STATE_VERSION_BATCH: u16 = 2;
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
        if version != MUTATION_STATE_VERSION && version != MUTATION_STATE_VERSION_BATCH {
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
        let batch_replay = if version == MUTATION_STATE_VERSION_BATCH {
            decode_batch_replay(&mut reader, limits)?
        } else {
            Vec::new()
        };
        reader.expect_end("mutation state")?;
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
) -> SegmentResult<Vec<BatchReplayRow>> {
    let count = reader.u32("mutation-state batch replay count")?;
    limits.check_entries(u64::from(count))?;
    limits.check_alloc::<BatchReplayRow>(u64::from(count))?;
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
        previous_token = Some(token.clone());
        let fingerprint = reader.bytes(32, "mutation-state batch fingerprint")?;
        let mut fingerprint_array = [0u8; 32];
        fingerprint_array.copy_from_slice(fingerprint);
        let response = decode_batch_response(reader, limits)?;
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
) -> SegmentResult<MutationBatchResponse> {
    let command_count = reader.u32("mutation-state batch command count")?;
    limits.check_entries(u64::from(command_count))?;
    limits.check_alloc::<MutationCommandOutcome>(u64::from(command_count))?;
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
