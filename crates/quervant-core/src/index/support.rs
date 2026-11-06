//! Internal helpers shared by the index opener and writer.
//!
//! These helpers perform bounded reads, content verification and durable
//! immutable installation against the existing [`Directory`] seam. They never
//! trust persisted lengths or digests.

use std::sync::Arc;

use quervant_objectstore::{ContentDescriptor, ContentDigest};

use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
use crate::contract::schema::Schema;
use crate::segment::{
    BuiltSegment, CodecSchema, SegmentBuilder, SegmentDocument, SegmentLimits, SegmentReader,
};
use crate::storage::{Directory, StorageError, StorageKey};

use super::current::{CURRENT_KEY, CURRENT_MAX_BYTES, CurrentPointer};
use super::error::{IndexError, IndexResult};
use super::snapshot::SegmentMeta;

/// The local index directory prefixes, created on demand.
const LAYOUT_PREFIXES: [&str; 4] = ["index", "index/manifests", "index/segments", "index/state"];

/// Create the local index layout if it does not already exist.
pub(crate) fn ensure_layout(directory: &dyn Directory) -> IndexResult<()> {
    for prefix in LAYOUT_PREFIXES {
        directory.create_dir_all(prefix)?;
    }
    Ok(())
}

/// Resolve the exact canonical codec schema for a contract schema + registry.
pub(crate) fn expected_codec_schema(
    schema: &Schema,
    registry: &AnalyzerRegistry,
) -> IndexResult<CodecSchema> {
    let bindings = SchemaAnalyzerBindings::resolve(schema, registry)?;
    Ok(CodecSchema::from_contract(schema, &bindings)?)
}

/// Read at most `max` bytes from `key`, failing closed on a short read.
pub(crate) fn read_bounded(
    directory: &dyn Directory,
    key: &StorageKey,
    max: u64,
) -> IndexResult<Vec<u8>> {
    let handle = directory.open_read(key)?;
    let len = handle.len();
    if len > max {
        return Err(IndexError::ResourceLimit {
            limit: max,
            requested: len,
        });
    }
    let capacity = usize::try_from(len).map_err(|_| IndexError::ResourceLimit {
        limit: max,
        requested: len,
    })?;
    let mut buffer = vec![0u8; capacity];
    let mut offset = 0usize;
    while offset < capacity {
        let read = handle.read_at(offset as u64, &mut buffer[offset..])?;
        if read == 0 {
            return Err(IndexError::CorruptCommittedState {
                detail: format!("short read at offset {offset} for {key}"),
            });
        }
        offset = offset
            .checked_add(read)
            .ok_or(IndexError::CorruptCommittedState {
                detail: "read offset overflow".to_owned(),
            })?;
    }
    Ok(buffer)
}

/// Read exactly `expected.length` bytes and verify the content digest.
pub(crate) fn read_verified(
    directory: &dyn Directory,
    key: &StorageKey,
    expected: ContentDescriptor,
    max: u64,
) -> IndexResult<Vec<u8>> {
    if expected.length > max {
        return Err(IndexError::ResourceLimit {
            limit: max,
            requested: expected.length,
        });
    }
    let handle = directory.open_read(key)?;
    let actual = handle.len();
    if actual != expected.length {
        return Err(IndexError::CorruptCommittedState {
            detail: format!(
                "length mismatch for {key}: expected {}, found {actual}",
                expected.length
            ),
        });
    }
    let capacity = usize::try_from(actual).map_err(|_| IndexError::ResourceLimit {
        limit: max,
        requested: actual,
    })?;
    let mut buffer = vec![0u8; capacity];
    let mut offset = 0usize;
    while offset < capacity {
        let read = handle.read_at(offset as u64, &mut buffer[offset..])?;
        if read == 0 {
            return Err(IndexError::CorruptCommittedState {
                detail: format!("short read at offset {offset} for {key}"),
            });
        }
        offset = offset
            .checked_add(read)
            .ok_or(IndexError::CorruptCommittedState {
                detail: "read offset overflow".to_owned(),
            })?;
    }
    if !expected.matches(&buffer) {
        return Err(IndexError::CorruptCommittedState {
            detail: format!("digest mismatch for {key}"),
        });
    }
    Ok(buffer)
}

/// Read and strictly parse `index/CURRENT`, if present.
pub(crate) fn read_current(directory: &dyn Directory) -> IndexResult<Option<CurrentPointer>> {
    let key = StorageKey::parse(CURRENT_KEY)?;
    if !directory.exists(&key)? {
        return Ok(None);
    }
    let bytes =
        read_bounded(directory, &key, CURRENT_MAX_BYTES as u64).map_err(|error| match error {
            IndexError::ResourceLimit { requested, .. } => IndexError::InvalidCurrent {
                detail: format!("encoded length {requested} exceeds {CURRENT_MAX_BYTES}"),
            },
            other => other,
        })?;
    Ok(Some(CurrentPointer::parse(&bytes)?))
}

/// Durably install immutable content at `key`.
///
/// A pre-existing byte-identical file is reused; a pre-existing file with
/// different bytes is a typed conflict and is never overwritten.
pub(crate) fn install_immutable(
    directory: &dyn Directory,
    key: &StorageKey,
    bytes: &[u8],
) -> IndexResult<()> {
    if directory.exists(key)? {
        return verify_existing(directory, key, bytes);
    }
    match directory.create(key) {
        Ok(mut handle) => {
            handle.write_all(bytes)?;
            handle.sync_all()?;
            directory.sync()?;
            Ok(())
        }
        Err(StorageError::AlreadyExists { .. }) => verify_existing(directory, key, bytes),
        Err(error) => Err(error.into()),
    }
}

fn verify_existing(directory: &dyn Directory, key: &StorageKey, bytes: &[u8]) -> IndexResult<()> {
    let existing_len = directory.file_len(key)?;
    if existing_len != bytes.len() as u64 {
        return Err(IndexError::ContentConflict {
            key: key.as_str().to_owned(),
        });
    }
    let existing = read_bounded(directory, key, existing_len)?;
    if existing == bytes {
        Ok(())
    } else {
        Err(IndexError::ContentConflict {
            key: key.as_str().to_owned(),
        })
    }
}

/// Canonicalize a feature declaration list: ascending and duplicate-free.
fn canonical_features(features: &[(u16, u16)]) -> Vec<(u16, u16)> {
    let mut canonical = features.to_vec();
    canonical.sort_unstable();
    canonical.dedup();
    canonical
}

/// Checked total of declared segment lengths.
///
/// Every length must fit `per_segment_limit`, and the running total must never
/// exceed `total_limit`. Both an individual overage and `u64` overflow are
/// typed [`IndexError::ResourceLimit`] failures, so a caller can reject a
/// committed snapshot before allocating or opening any segment.
pub(crate) fn bounded_segment_total(
    lengths: impl IntoIterator<Item = u64>,
    per_segment_limit: u64,
    total_limit: u64,
) -> IndexResult<u64> {
    let mut total: u64 = 0;
    for length in lengths {
        if length > per_segment_limit {
            return Err(IndexError::ResourceLimit {
                limit: per_segment_limit,
                requested: length,
            });
        }
        total = total.checked_add(length).ok_or(IndexError::ResourceLimit {
            limit: total_limit,
            requested: u64::MAX,
        })?;
        if total > total_limit {
            return Err(IndexError::ResourceLimit {
                limit: total_limit,
                requested: total,
            });
        }
    }
    Ok(total)
}

/// Build one immutable segment from validated documents.
pub(crate) fn build_segment(
    schema: &Schema,
    registry: &AnalyzerRegistry,
    docs: &[SegmentDocument],
) -> IndexResult<BuiltSegment> {
    let mut builder = SegmentBuilder::new(schema.clone(), registry.clone())?;
    for doc in docs {
        builder.add_document(doc.clone())?;
    }
    Ok(builder.build()?)
}

/// Derive the content-addressed segment descriptor from freshly built bytes.
pub(crate) fn meta_from_bytes(
    limits: &SegmentLimits,
    bytes: &Arc<Vec<u8>>,
) -> IndexResult<(SegmentMeta, u64)> {
    let digest = ContentDigest::sha256_v1(bytes);
    let hex = digest.to_hex();
    let descriptor = ContentDescriptor::new(bytes.len() as u64, digest);
    let object_key = super::current::segment_key_for_hex(&hex);
    let segment_id = format!("s-{hex}");
    let reader = SegmentReader::open(bytes.as_ref().clone(), *limits)?;
    let doc_count = reader.doc_count();
    // The segment container may carry the baseline feature more than once (it is
    // added by both `ContainerBuilder::new` and `SegmentBuilder`). Manifest
    // feature sets are strictly ascending and duplicate-free, so canonicalize.
    let required = canonical_features(reader.required_features());
    let optional = canonical_features(reader.optional_features());
    let time_bounds = reader.time_bounds().cloned();
    Ok((
        SegmentMeta::new(
            segment_id,
            object_key,
            descriptor,
            required,
            optional,
            time_bounds,
        ),
        doc_count,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_total_accepts_exact_and_rejects_one_over() {
        assert_eq!(bounded_segment_total([40, 60], 100, 100).unwrap(), 100);
        assert!(matches!(
            bounded_segment_total([40, 61], 100, 100),
            Err(IndexError::ResourceLimit { .. })
        ));
        assert!(matches!(
            bounded_segment_total([101], 100, u64::MAX),
            Err(IndexError::ResourceLimit { .. })
        ));
    }

    #[test]
    fn bounded_total_detects_overflow() {
        assert!(matches!(
            bounded_segment_total([u64::MAX, 1], u64::MAX, u64::MAX),
            Err(IndexError::ResourceLimit { .. })
        ));
    }
}
