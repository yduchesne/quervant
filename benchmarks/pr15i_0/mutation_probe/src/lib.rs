//! PR15I-0 benchmark-only **read-only** mutation-state sidecar byte attribution probe.
//!
//! This crate is deliberately not part of the production workspace. It observes
//! already-committed bytes through the public `quervant-core` API and never
//! writes, repairs or re-encodes an index. It is a *physical* accounting probe,
//! not a second mutation-state decoder:
//!
//! * the payload version-2 batch replay block is **not** decoded; the whole
//!   remaining span from the batch count onwards is attributed as opaque bytes;
//! * logical keys, idempotency tokens and segment ids are validated with the
//!   public production constructors where those are reachable, and are never
//!   published;
//! * SHA-256 is obtained only from `quervant_objectstore::ContentDigest`, which
//!   wraps the audited RustCrypto `sha2` crate. No cryptography is implemented
//!   here.
//!
//! The authoritative active sidecar is located through the public
//! `CURRENT -> Manifest -> MutationStateRef` chain — never by listing
//! `index/state/` and guessing from file names, modification times or digests.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Component, Path, PathBuf};

use quervant_core::contract::document::{DocumentKey, IdempotencyKey};
use quervant_core::index::{CURRENT_KEY, CURRENT_MAX_BYTES, CurrentPointer};
use quervant_core::segment::format::{
    ByteReader, ContainerKind, FEATURE_MUTATION_STATE, FEATURE_MUTATION_STATE_V2, SectionKind,
    parse_container,
};
use quervant_core::segment::{Manifest, SegmentError, SegmentLimits};
use quervant_objectstore::ContentDigest;
use serde_json::{Map, Value};

/// Schema identifier of the emitted breakdown.
pub const BREAKDOWN_SCHEMA: &str = "pr15i-0-mutation-breakdown-v1";
/// Hard upper bound on a sidecar file, fixed by the measurement contract.
pub const MAX_SIDECAR_BYTES: u64 = 268_435_456;
/// Payload versions this probe is allowed to interpret.
pub const SUPPORTED_PAYLOAD_VERSIONS: [u16; 2] = [1, 2];
/// Explicit disclosure attached to every version-2 breakdown.
pub const BATCH_DETAIL_LABEL: &str = "SEMANTIC_BATCH_DETAIL_NOT_VERIFIED";
/// Explicit disclosure used when public key constructors cannot be reached.
pub const KEY_VALIDATION_LABEL: &str = "SEMANTIC_KEY_VALIDATION_NOT_PROVEN";

const EXIT_USAGE: i32 = 2;

/// Typed, fail-closed probe failure. The class is a stable lowercase token so a
/// controller can classify an affected capture without parsing prose.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ProbeError {
    class: &'static str,
    detail: String,
}

impl ProbeError {
    /// Construct a classified failure. Used by the CLI for non-payload errors.
    #[must_use]
    pub fn classified(class: &'static str, detail: impl Into<String>) -> Self {
        Self {
            class,
            detail: detail.into(),
        }
    }

    fn new(class: &'static str, detail: impl Into<String>) -> Self {
        Self::classified(class, detail)
    }

    /// The stable failure class.
    #[must_use]
    pub const fn class(&self) -> &'static str {
        self.class
    }

    /// Human-readable detail. Never contains a raw key, token or segment id.
    #[must_use]
    pub fn detail(&self) -> &str {
        &self.detail
    }

    /// Process exit code associated with this class.
    #[must_use]
    pub fn exit_code(&self) -> i32 {
        if matches!(self.class, "usage") {
            EXIT_USAGE
        } else {
            3
        }
    }
}

impl std::fmt::Display for ProbeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{}: {}", self.class, self.detail)
    }
}

impl std::error::Error for ProbeError {}

fn usage(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("usage", detail)
}

fn invalid_path(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("invalid_path", detail)
}

fn too_large(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("too_large", detail)
}

fn bad_container(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("bad_container", detail)
}

fn wrong_kind(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("wrong_kind", detail)
}

fn unsupported_feature(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("unsupported_feature", detail)
}

fn unsupported_payload(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("unsupported_payload", detail)
}

fn corrupt_payload(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("corrupt_payload", detail)
}

fn unverified(detail: impl Into<String>) -> ProbeError {
    ProbeError::new("stale_or_unverified", detail)
}

fn io_error(context: &'static str, error: std::io::Error) -> ProbeError {
    ProbeError::new("io", format!("{context}: {error}"))
}

fn segment_error(context: &'static str, error: SegmentError) -> ProbeError {
    match error {
        SegmentError::LimitExceeded { .. } => too_large(format!("{context}: {error}")),
        SegmentError::UnsupportedFeature { .. } | SegmentError::UnsupportedFormatVersion { .. } => {
            unsupported_feature(format!("{context}: {error}"))
        }
        other => bad_container(format!("{context}: {other}")),
    }
}

// ---------------------------------------------------------------------------
// Checked byte accounting
// ---------------------------------------------------------------------------

/// Every physical byte category of one mutation-state payload.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Components {
    pub state_header_bytes: u64,
    pub row_key_prefix_bytes: u64,
    pub row_key_bytes: u64,
    pub row_revision_bytes: u64,
    pub row_status_bytes: u64,
    pub live_pointer_prefix_bytes: u64,
    pub live_pointer_id_bytes: u64,
    pub live_doc_id_bytes: u64,
    pub replay_header_bytes: u64,
    pub replay_token_prefix_bytes: u64,
    pub replay_token_bytes: u64,
    pub replay_fingerprint_bytes: u64,
    pub replay_key_prefix_bytes: u64,
    pub replay_key_bytes: u64,
    pub replay_intent_bytes: u64,
    pub replay_revision_bytes: u64,
    pub batch_replay_opaque_bytes: u64,
}

impl Components {
    /// Ordered `(name, bytes)` pairs. The order is stable for reports.
    #[must_use]
    pub const fn fields(&self) -> [(&'static str, u64); 17] {
        [
            ("state_header_bytes", self.state_header_bytes),
            ("row_key_prefix_bytes", self.row_key_prefix_bytes),
            ("row_key_bytes", self.row_key_bytes),
            ("row_revision_bytes", self.row_revision_bytes),
            ("row_status_bytes", self.row_status_bytes),
            ("live_pointer_prefix_bytes", self.live_pointer_prefix_bytes),
            ("live_pointer_id_bytes", self.live_pointer_id_bytes),
            ("live_doc_id_bytes", self.live_doc_id_bytes),
            ("replay_header_bytes", self.replay_header_bytes),
            ("replay_token_prefix_bytes", self.replay_token_prefix_bytes),
            ("replay_token_bytes", self.replay_token_bytes),
            ("replay_fingerprint_bytes", self.replay_fingerprint_bytes),
            ("replay_key_prefix_bytes", self.replay_key_prefix_bytes),
            ("replay_key_bytes", self.replay_key_bytes),
            ("replay_intent_bytes", self.replay_intent_bytes),
            ("replay_revision_bytes", self.replay_revision_bytes),
            ("batch_replay_opaque_bytes", self.batch_replay_opaque_bytes),
        ]
    }

    /// Checked sum of every component.
    pub fn total(&self) -> Result<u64, ProbeError> {
        let mut total = 0u64;
        for (name, value) in self.fields() {
            total = total
                .checked_add(value)
                .ok_or_else(|| corrupt_payload(format!("component total overflow at {name}")))?;
        }
        Ok(total)
    }

    /// Every component as a JSON object with stable, sorted keys.
    #[must_use]
    pub fn to_json(&self) -> Map<String, Value> {
        let sorted: BTreeMap<String, Value> = self
            .fields()
            .into_iter()
            .map(|(name, value)| (name.to_owned(), Value::from(value)))
            .collect();
        sorted.into_iter().collect()
    }
}

fn charge(slot: &mut u64, delta: u64, name: &'static str) -> Result<(), ProbeError> {
    *slot = slot
        .checked_add(delta)
        .ok_or_else(|| corrupt_payload(format!("component overflow at {name}")))?;
    Ok(())
}

fn span(before: usize, after: usize, context: &'static str) -> Result<u64, ProbeError> {
    let delta = after
        .checked_sub(before)
        .ok_or_else(|| corrupt_payload(format!("{context}: reader moved backwards")))?;
    u64::try_from(delta).map_err(|_| corrupt_payload(format!("{context}: span overflow")))
}

/// The verified physical accounting of one sidecar.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Breakdown {
    pub payload_version: u16,
    pub row_count: u32,
    pub replay_count: u32,
    pub live_count: u64,
    pub deleted_count: u64,
    pub components: Components,
    pub payload_bytes: u64,
    pub container_overhead_bytes: u64,
    pub sidecar_file_bytes: u64,
    pub container_section_count: usize,
    pub section_flags: u16,
    pub required_features: Vec<(u16, u16)>,
    pub key_validation: &'static str,
}

impl Breakdown {
    /// The exact byte identity of the accounted payload.
    #[must_use]
    pub const fn payload_bytes(&self) -> u64 {
        self.payload_bytes
    }
}

// ---------------------------------------------------------------------------
// Path validation
// ---------------------------------------------------------------------------

/// Validate an index root: absolute, no `..`, no symlink on any component.
pub fn validate_index_root(raw: &Path) -> Result<PathBuf, ProbeError> {
    if !raw.is_absolute() {
        return Err(invalid_path("index root must be an absolute path"));
    }
    for component in raw.components() {
        if matches!(component, Component::ParentDir) {
            return Err(invalid_path(
                "index root may not contain a parent-directory component",
            ));
        }
    }
    let mut current = PathBuf::new();
    for component in raw.components() {
        current.push(component);
        let metadata = fs::symlink_metadata(&current)
            .map_err(|error| io_error("cannot stat index root component", error))?;
        if metadata.file_type().is_symlink() {
            return Err(invalid_path("symlink in the index root path"));
        }
    }
    let metadata =
        fs::metadata(raw).map_err(|error| io_error("index root is unavailable", error))?;
    if !metadata.is_dir() {
        return Err(invalid_path("index root is not a directory"));
    }
    fs::canonicalize(raw).map_err(|error| io_error("cannot resolve the index root", error))
}

/// Resolve a `/`-separated relative storage key below `root`, refusing absolute
/// paths, traversal, and symlinks on any component.
fn resolve_under(root: &Path, relative: &str) -> Result<PathBuf, ProbeError> {
    if relative.is_empty() {
        return Err(invalid_path("empty storage key"));
    }
    let candidate = Path::new(relative);
    if candidate.is_absolute() {
        return Err(invalid_path("storage key must be relative"));
    }
    let mut current = root.to_path_buf();
    for component in candidate.components() {
        let Component::Normal(part) = component else {
            return Err(invalid_path(
                "storage key contains a non-normal path component",
            ));
        };
        current.push(part);
        let metadata = fs::symlink_metadata(&current)
            .map_err(|error| invalid_path(format!("storage key component missing: {error}")))?;
        if metadata.file_type().is_symlink() {
            return Err(invalid_path("symlink in the resolved storage key"));
        }
    }
    if !current.starts_with(root) {
        return Err(invalid_path("storage key escapes the index root"));
    }
    Ok(current)
}

fn read_bounded(path: &Path, max_bytes: u64, context: &'static str) -> Result<Vec<u8>, ProbeError> {
    let metadata = fs::symlink_metadata(path).map_err(|error| io_error(context, error))?;
    if metadata.file_type().is_symlink() {
        return Err(invalid_path(format!("{context}: path is a symlink")));
    }
    if !metadata.file_type().is_file() {
        return Err(invalid_path(format!(
            "{context}: path is not a regular file"
        )));
    }
    if metadata.len() > max_bytes {
        return Err(too_large(format!(
            "{context}: file length {} exceeds {max_bytes}",
            metadata.len()
        )));
    }
    let bytes = fs::read(path).map_err(|error| io_error(context, error))?;
    let observed = u64::try_from(bytes.len())
        .map_err(|_| too_large(format!("{context}: file length is not addressable")))?;
    if observed != metadata.len() {
        return Err(io_error(
            context,
            std::io::Error::other("file changed while being read"),
        ));
    }
    if observed > max_bytes {
        return Err(too_large(format!(
            "{context}: file length {observed} exceeds {max_bytes}"
        )));
    }
    Ok(bytes)
}

// ---------------------------------------------------------------------------
// Authoritative active-sidecar resolution
// ---------------------------------------------------------------------------

/// The authoritative generation state object, resolved through public APIs.
#[derive(Debug, Clone)]
pub struct ActiveState {
    /// Relative, `/`-separated storage key (private evidence only).
    pub relative_key: String,
    /// Exact object length from the committed manifest.
    pub length: u64,
    /// Lowercase hex SHA-256 of the exact bytes.
    pub digest_hex: String,
    /// The exact bytes, read once.
    pub bytes: Vec<u8>,
}

/// Walk `CURRENT -> Manifest -> MutationStateRef` and return the verified bytes.
pub fn resolve_active_state(root: &Path, max_bytes: u64) -> Result<ActiveState, ProbeError> {
    let current_path = resolve_under(root, CURRENT_KEY)?;
    let current_bytes = read_bounded(
        &current_path,
        u64::try_from(CURRENT_MAX_BYTES).map_err(|_| too_large("CURRENT bound"))?,
        "index/CURRENT",
    )?;
    let pointer = CurrentPointer::parse(&current_bytes)
        .map_err(|error| bad_container(format!("CURRENT is not a valid pointer: {error}")))?;

    let manifest_key = pointer.manifest_key().as_str();
    let manifest_path = resolve_under(root, manifest_key)?;
    let manifest_bytes = read_bounded(&manifest_path, max_bytes, "manifest")?;
    let manifest_len = u64::try_from(manifest_bytes.len())
        .map_err(|_| too_large("manifest length is not addressable"))?;
    if manifest_len != pointer.manifest_length() {
        return Err(unverified(format!(
            "manifest length {manifest_len} does not match CURRENT {}",
            pointer.manifest_length()
        )));
    }
    let observed_manifest_digest = ContentDigest::sha256_v1(&manifest_bytes);
    if observed_manifest_digest != pointer.manifest_digest() {
        return Err(unverified(
            "manifest digest does not match the committed CURRENT pointer",
        ));
    }

    let manifest = Manifest::decode(&manifest_bytes, &SegmentLimits::default())
        .map_err(|error| segment_error("manifest decode", error))?;
    let reference = manifest
        .mutation_state
        .ok_or_else(|| unverified("the committed manifest references no mutation-state sidecar"))?;
    let state_path = resolve_under(root, &reference.object_key)?;
    let state_bytes = read_bounded(&state_path, max_bytes, "mutation-state sidecar")?;
    let state_len = u64::try_from(state_bytes.len())
        .map_err(|_| too_large("sidecar length is not addressable"))?;
    if state_len != reference.content_length {
        return Err(unverified(format!(
            "sidecar length {state_len} does not match the manifest {}",
            reference.content_length
        )));
    }
    let observed_state_digest = ContentDigest::sha256_v1(&state_bytes);
    if observed_state_digest != ContentDigest::from_sha256_v1_bytes(reference.content_digest) {
        return Err(unverified(
            "sidecar digest does not match the committed manifest reference",
        ));
    }

    Ok(ActiveState {
        relative_key: reference.object_key,
        length: state_len,
        digest_hex: observed_state_digest.to_hex(),
        bytes: state_bytes,
    })
}

// ---------------------------------------------------------------------------
// Payload accounting
// ---------------------------------------------------------------------------

fn read_u8(reader: &mut ByteReader<'_>, context: &'static str) -> Result<(u8, u64), ProbeError> {
    let before = reader.position();
    let value = reader
        .u8(context)
        .map_err(|error| segment_error(context, error))?;
    Ok((value, span(before, reader.position(), context)?))
}

fn read_u16(reader: &mut ByteReader<'_>, context: &'static str) -> Result<(u16, u64), ProbeError> {
    let before = reader.position();
    let value = reader
        .u16(context)
        .map_err(|error| segment_error(context, error))?;
    Ok((value, span(before, reader.position(), context)?))
}

fn read_u32(reader: &mut ByteReader<'_>, context: &'static str) -> Result<(u32, u64), ProbeError> {
    let before = reader.position();
    let value = reader
        .u32(context)
        .map_err(|error| segment_error(context, error))?;
    Ok((value, span(before, reader.position(), context)?))
}

fn read_u64(reader: &mut ByteReader<'_>, context: &'static str) -> Result<(u64, u64), ProbeError> {
    let before = reader.position();
    let value = reader
        .u64(context)
        .map_err(|error| segment_error(context, error))?;
    Ok((value, span(before, reader.position(), context)?))
}

fn read_len_prefixed<'a>(
    reader: &mut ByteReader<'a>,
    context: &'static str,
) -> Result<(&'a [u8], u64, u64), ProbeError> {
    let before = reader.position();
    let value = reader
        .len_prefixed_u16(context)
        .map_err(|error| segment_error(context, error))?;
    let used = span(before, reader.position(), context)?;
    let body = u64::try_from(value.len())
        .map_err(|_| corrupt_payload(format!("{context}: length is not addressable")))?;
    let prefix = used
        .checked_sub(body)
        .ok_or_else(|| corrupt_payload(format!("{context}: inconsistent prefix length")))?;
    Ok((value, prefix, body))
}

fn read_fixed(
    reader: &mut ByteReader<'_>,
    count: u64,
    context: &'static str,
) -> Result<u64, ProbeError> {
    let before = reader.position();
    let count = usize::try_from(count)
        .map_err(|_| corrupt_payload(format!("{context}: count is not addressable")))?;
    reader
        .bytes(count, context)
        .map_err(|error| segment_error(context, error))?;
    span(before, reader.position(), context)
}

fn decode_utf8<'a>(bytes: &'a [u8], context: &'static str) -> Result<&'a str, ProbeError> {
    std::str::from_utf8(bytes).map_err(|_| corrupt_payload(format!("{context}: invalid UTF-8")))
}

/// Account every payload byte of one envelope-verified mutation-state container.
pub fn analyze_breakdown(bytes: &[u8]) -> Result<Breakdown, ProbeError> {
    let observed_bytes = u64::try_from(bytes.len())
        .map_err(|_| too_large("sidecar exceeds the fixed 256 MiB defect bound"))?;
    if observed_bytes > MAX_SIDECAR_BYTES {
        return Err(too_large("sidecar exceeds the fixed 256 MiB defect bound"));
    }
    let view = parse_container(bytes, &SegmentLimits::default())
        .map_err(|error| segment_error("container envelope", error))?;
    if view.kind() != ContainerKind::MutationState {
        return Err(wrong_kind("container is not a mutation-state container"));
    }
    view.ensure_supported_features()
        .map_err(|error| segment_error("required features", error))?;

    let state_sections: Vec<_> = view
        .sections()
        .iter()
        .filter(|entry| entry.kind == SectionKind::MutationState)
        .collect();
    if state_sections.len() != 1 {
        return Err(wrong_kind(format!(
            "expected exactly one MutationState section, found {}",
            state_sections.len()
        )));
    }
    let entry = state_sections[0];
    let body = view
        .body(SectionKind::MutationState)
        .ok_or_else(|| wrong_kind("MutationState section body is unavailable"))?;
    let body_bytes = u64::try_from(body.len())
        .map_err(|_| too_large("mutation-state payload length is not addressable"))?;
    let file_bytes =
        u64::try_from(bytes.len()).map_err(|_| too_large("sidecar length is not addressable"))?;
    let container_overhead_bytes = file_bytes
        .checked_sub(body_bytes)
        .ok_or_else(|| corrupt_payload("container overhead is negative"))?;

    let mut reader = ByteReader::new(body);
    let mut components = Components::default();

    let (payload_version, header) = read_u16(&mut reader, "mutation-state version")?;
    if !SUPPORTED_PAYLOAD_VERSIONS.contains(&payload_version) {
        return Err(unsupported_payload(format!(
            "payload version {payload_version} is not in {SUPPORTED_PAYLOAD_VERSIONS:?}"
        )));
    }
    charge(
        &mut components.state_header_bytes,
        header,
        "state_header_bytes",
    )?;
    let (row_count, header) = read_u32(&mut reader, "mutation-state row count")?;
    charge(
        &mut components.state_header_bytes,
        header,
        "state_header_bytes",
    )?;

    let mut live_count = 0u64;
    let mut deleted_count = 0u64;
    let mut previous_key: Option<String> = None;

    for _ in 0..row_count {
        let (key_bytes, prefix, body) = read_len_prefixed(&mut reader, "mutation-state key")?;
        charge(
            &mut components.row_key_prefix_bytes,
            prefix,
            "row_key_prefix_bytes",
        )?;
        charge(&mut components.row_key_bytes, body, "row_key_bytes")?;
        let key_ref = decode_utf8(key_bytes, "mutation-state key")?;
        let key = DocumentKey::new(key_ref)
            .map_err(|_| corrupt_payload("mutation-state key: invalid document key"))?;
        if let Some(previous) = &previous_key {
            if previous.as_bytes() >= key.as_str().as_bytes() {
                return Err(corrupt_payload(
                    "mutation-state rows are not strictly ascending",
                ));
            }
        }
        previous_key = Some(key.as_str().to_owned());

        let (revision, used) = read_u64(&mut reader, "mutation-state revision")?;
        if revision == 0 {
            return Err(corrupt_payload("mutation-state row revision is zero"));
        }
        charge(
            &mut components.row_revision_bytes,
            used,
            "row_revision_bytes",
        )?;

        let (status, used) = read_u8(&mut reader, "mutation-state status")?;
        charge(&mut components.row_status_bytes, used, "row_status_bytes")?;
        match status {
            0 => {
                deleted_count = deleted_count
                    .checked_add(1)
                    .ok_or_else(|| corrupt_payload("deleted row count overflow"))?;
            }
            1 => {
                live_count = live_count
                    .checked_add(1)
                    .ok_or_else(|| corrupt_payload("live row count overflow"))?;
                let (segment_bytes, prefix, body) =
                    read_len_prefixed(&mut reader, "mutation-state segment id")?;
                charge(
                    &mut components.live_pointer_prefix_bytes,
                    prefix,
                    "live_pointer_prefix_bytes",
                )?;
                charge(
                    &mut components.live_pointer_id_bytes,
                    body,
                    "live_pointer_id_bytes",
                )?;
                let segment_ref = decode_utf8(segment_bytes, "mutation-state segment id")?;
                if segment_ref.is_empty() {
                    return Err(corrupt_payload("mutation-state segment id is empty"));
                }
                let (_, used) = read_u64(&mut reader, "mutation-state doc id")?;
                charge(&mut components.live_doc_id_bytes, used, "live_doc_id_bytes")?;
            }
            other => {
                return Err(corrupt_payload(format!(
                    "mutation-state status {other} is invalid"
                )));
            }
        }
    }

    let (replay_count, header) = read_u32(&mut reader, "mutation-state replay count")?;
    charge(
        &mut components.replay_header_bytes,
        header,
        "replay_header_bytes",
    )?;
    let mut previous_token: Option<String> = None;
    for _ in 0..replay_count {
        let (token_bytes, prefix, body) = read_len_prefixed(&mut reader, "mutation-state token")?;
        charge(
            &mut components.replay_token_prefix_bytes,
            prefix,
            "replay_token_prefix_bytes",
        )?;
        charge(
            &mut components.replay_token_bytes,
            body,
            "replay_token_bytes",
        )?;
        let token_ref = decode_utf8(token_bytes, "mutation-state token")?;
        let token = IdempotencyKey::new(token_ref)
            .map_err(|_| corrupt_payload("mutation-state token: invalid idempotency token"))?;
        if let Some(previous) = &previous_token {
            if previous.as_bytes() >= token.as_str().as_bytes() {
                return Err(corrupt_payload(
                    "mutation-state replay entries are not strictly ascending",
                ));
            }
        }
        previous_token = Some(token.as_str().to_owned());

        let fingerprint = read_fixed(&mut reader, 32, "mutation-state fingerprint")?;
        charge(
            &mut components.replay_fingerprint_bytes,
            fingerprint,
            "replay_fingerprint_bytes",
        )?;

        let (key_bytes, prefix, body) =
            read_len_prefixed(&mut reader, "mutation-state replay key")?;
        charge(
            &mut components.replay_key_prefix_bytes,
            prefix,
            "replay_key_prefix_bytes",
        )?;
        charge(&mut components.replay_key_bytes, body, "replay_key_bytes")?;
        let key_ref = decode_utf8(key_bytes, "mutation-state replay key")?;
        DocumentKey::new(key_ref)
            .map_err(|_| corrupt_payload("mutation-state replay key: invalid document key"))?;

        let (intent, used) = read_u8(&mut reader, "mutation-state replay intent")?;
        charge(
            &mut components.replay_intent_bytes,
            used,
            "replay_intent_bytes",
        )?;
        if intent > 2 {
            return Err(corrupt_payload(format!(
                "mutation-state replay intent {intent} is invalid"
            )));
        }

        let (revision, used) = read_u64(&mut reader, "mutation-state replay revision")?;
        if revision == 0 {
            return Err(corrupt_payload("mutation-state replay revision is zero"));
        }
        charge(
            &mut components.replay_revision_bytes,
            used,
            "replay_revision_bytes",
        )?;
    }

    if payload_version == 1 {
        reader
            .expect_end("mutation state")
            .map_err(|error| segment_error("mutation-state trailing bytes", error))?;
    } else {
        let remaining = reader.remaining();
        let opaque = u64::try_from(remaining)
            .map_err(|_| corrupt_payload("batch replay span is not addressable"))?;
        if opaque < 4 {
            return Err(corrupt_payload(
                "version-2 batch replay span is shorter than its count prefix",
            ));
        }
        charge(
            &mut components.batch_replay_opaque_bytes,
            opaque,
            "batch_replay_opaque_bytes",
        )?;
    }

    let payload_bytes = components.total()?;
    if payload_bytes != body_bytes {
        return Err(corrupt_payload(format!(
            "component total {payload_bytes} does not equal the section body {body_bytes}"
        )));
    }
    let reconciled_file_bytes = payload_bytes
        .checked_add(container_overhead_bytes)
        .ok_or_else(|| corrupt_payload("file byte total overflow"))?;
    if reconciled_file_bytes != file_bytes {
        return Err(corrupt_payload(format!(
            "payload {payload_bytes} plus overhead {container_overhead_bytes} \
             does not equal the file length {file_bytes}"
        )));
    }

    let mut required_features = view.required_features().to_vec();
    required_features.sort_unstable();
    if !required_features.contains(&(FEATURE_MUTATION_STATE, 1)) {
        return Err(unsupported_feature(
            "mutation-state container does not require FEATURE_MUTATION_STATE",
        ));
    }
    if payload_version == 2 && !required_features.contains(&(FEATURE_MUTATION_STATE_V2, 1)) {
        return Err(unsupported_feature(
            "version-2 payload does not require FEATURE_MUTATION_STATE_V2",
        ));
    }

    Ok(Breakdown {
        payload_version,
        row_count,
        replay_count,
        live_count,
        deleted_count,
        components,
        payload_bytes,
        container_overhead_bytes,
        sidecar_file_bytes: file_bytes,
        container_section_count: view.sections().len(),
        section_flags: entry.flags,
        required_features,
        key_validation: "PUBLIC_CONSTRUCTOR_VALIDATED",
    })
}

// ---------------------------------------------------------------------------
// Report assembly
// ---------------------------------------------------------------------------

/// Full probe report for one prepared index.
#[derive(Debug, Clone)]
pub struct Report {
    pub active: ActiveState,
    pub breakdown: Breakdown,
}

/// Resolve and account one prepared index's authoritative active sidecar.
pub fn probe_index_root(
    raw_root: &Path,
    max_bytes: u64,
    source_sha: &str,
) -> Result<Report, ProbeError> {
    if max_bytes == 0 || max_bytes > MAX_SIDECAR_BYTES {
        return Err(usage(format!(
            "--max-bytes must be in 1..={MAX_SIDECAR_BYTES}"
        )));
    }
    if !is_lower_hex_sha(source_sha) {
        return Err(usage(
            "--source-sha must be 40 lowercase hexadecimal characters",
        ));
    }
    let root = validate_index_root(raw_root)?;
    let active = resolve_active_state(&root, max_bytes)?;
    let breakdown = analyze_breakdown(&active.bytes)?;
    Ok(Report { active, breakdown })
}

/// Whether `value` is a 40-character lowercase hexadecimal commit id.
#[must_use]
pub fn is_lower_hex_sha(value: &str) -> bool {
    value.len() == 40
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Serialize a report as a canonical (sorted-key) JSON object.
#[must_use]
pub fn report_json(report: &Report, source_sha: &str) -> Value {
    let mut map = Map::new();
    map.insert(
        "schema".to_owned(),
        Value::from(BREAKDOWN_SCHEMA.to_owned()),
    );
    map.insert("source_sha".to_owned(), Value::from(source_sha.to_owned()));
    map.insert(
        "qualified".to_owned(),
        Value::from(matches!(report.breakdown.payload_version, 1 | 2)),
    );
    map.insert(
        "active_state_key".to_owned(),
        Value::from(report.active.relative_key.clone()),
    );
    map.insert(
        "sidecar_sha256".to_owned(),
        Value::from(report.active.digest_hex.clone()),
    );
    map.insert(
        "sidecar_file_bytes".to_owned(),
        Value::from(report.breakdown.sidecar_file_bytes),
    );
    map.insert(
        "container_overhead_bytes".to_owned(),
        Value::from(report.breakdown.container_overhead_bytes),
    );
    map.insert(
        "payload_bytes".to_owned(),
        Value::from(report.breakdown.payload_bytes),
    );
    map.insert(
        "payload_version".to_owned(),
        Value::from(u64::from(report.breakdown.payload_version)),
    );
    map.insert(
        "row_count".to_owned(),
        Value::from(u64::from(report.breakdown.row_count)),
    );
    map.insert(
        "replay_count".to_owned(),
        Value::from(u64::from(report.breakdown.replay_count)),
    );
    map.insert(
        "live_count".to_owned(),
        Value::from(report.breakdown.live_count),
    );
    map.insert(
        "deleted_count".to_owned(),
        Value::from(report.breakdown.deleted_count),
    );
    map.insert(
        "container_section_count".to_owned(),
        Value::from(report.breakdown.container_section_count as u64),
    );
    map.insert(
        "section_flags".to_owned(),
        Value::from(u64::from(report.breakdown.section_flags)),
    );
    map.insert(
        "required_features".to_owned(),
        Value::Array(
            report
                .breakdown
                .required_features
                .iter()
                .map(|(id, version)| {
                    Value::Array(vec![
                        Value::from(u64::from(*id)),
                        Value::from(u64::from(*version)),
                    ])
                })
                .collect(),
        ),
    );
    map.insert(
        "key_validation".to_owned(),
        Value::from(report.breakdown.key_validation.to_owned()),
    );
    map.insert(
        "component_bytes".to_owned(),
        Value::Object(report.breakdown.components.to_json()),
    );
    map.insert(
        "batch_replay_detail".to_owned(),
        Value::from(if report.breakdown.payload_version == 2 {
            BATCH_DETAIL_LABEL
        } else {
            "NOT_APPLICABLE"
        }),
    );
    Value::Object(map)
}

/// Ordered list of every component name, for report code that must not drift.
#[must_use]
pub fn component_names() -> Vec<&'static str> {
    Components::default()
        .fields()
        .iter()
        .map(|(name, _)| *name)
        .collect()
}

/// Sum a caller-supplied component map with checked arithmetic.
pub fn sum_component_map(map: &BTreeMap<String, u64>) -> Result<u64, ProbeError> {
    let mut total = 0u64;
    for (name, value) in map {
        total = total
            .checked_add(*value)
            .ok_or_else(|| corrupt_payload(format!("component total overflow at {name}")))?;
    }
    Ok(total)
}
