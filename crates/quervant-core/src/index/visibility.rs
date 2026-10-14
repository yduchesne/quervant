//! Generation-specific effective live-mask construction (PR 9).
//!
//! A committed generation's logical state is authoritative through its
//! mutation-state sidecar. A physical document is live in a snapshot iff its
//! segment's own live bitmap is set **and** the generation state has a `LIVE`
//! winner row pointing at exactly that `(segment_id, doc_id)`.
//!
//! Masks are immutable, owned by the [`ReaderSnapshot`] that built them, and
//! never mutate `SegmentReader::live_docs()`. Old snapshots keep their mask; a
//! new generation gets a fresh mask.
//!
//! When a generation state is built, every live pointer is validated against
//! the referenced segment before the snapshot is published: the segment must
//! exist, the doc id must be in range, the physical key at that doc id must
//! equal the row key, and no two live rows may claim the same physical document.
//!
//! [`ReaderSnapshot`]: super::snapshot::ReaderSnapshot

use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use crate::segment::{SegmentLimits, SegmentReader};

use super::error::{IndexError, IndexResult};
use super::mutation_state::MutationStateV1;
use super::snapshot::SegmentSnapshot;

/// Build effective live masks from a state and matching segment readers.
///
/// `segments[i]` and `readers[i]` must describe the same segment.
pub(crate) fn build_masks_from_readers(
    state: &MutationStateV1,
    segments: &[SegmentSnapshot],
    readers: &[SegmentReader],
) -> IndexResult<Vec<Option<Arc<Vec<bool>>>>> {
    if segments.len() != readers.len() {
        return Err(IndexError::CorruptCommittedState {
            detail: "mask input segment/reader count mismatch".to_owned(),
        });
    }
    let mut index_by_id: BTreeMap<&str, usize> = BTreeMap::new();
    for (index, segment) in segments.iter().enumerate() {
        if index_by_id
            .insert(segment.meta().segment_id(), index)
            .is_some()
        {
            return Err(IndexError::CorruptCommittedState {
                detail: "duplicate segment id in snapshot".to_owned(),
            });
        }
    }
    let mut masks: Vec<Vec<bool>> = Vec::new();
    masks
        .try_reserve_exact(segments.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: segments.len() as u64,
            requested: u64::MAX,
        })?;
    for segment in segments {
        let len = usize::try_from(segment.doc_count()).map_err(|_| IndexError::ResourceLimit {
            limit: segment.doc_count(),
            requested: u64::MAX,
        })?;
        masks.push(vec![false; len]);
    }
    let mut claimed: BTreeSet<(usize, u64)> = BTreeSet::new();
    for row in state.rows() {
        if !row.is_live() {
            continue;
        }
        let (Some(segment_id), Some(doc_id)) = (row.segment_id.as_ref(), row.doc_id) else {
            return Err(IndexError::CorruptCommittedState {
                detail: "live state row is missing its physical pointer".to_owned(),
            });
        };
        let index = *index_by_id.get(segment_id.as_str()).ok_or_else(|| {
            IndexError::CorruptCommittedState {
                detail: format!("state points to absent segment {segment_id}"),
            }
        })?;
        let reader = &readers[index];
        if doc_id >= reader.doc_count() {
            return Err(IndexError::CorruptCommittedState {
                detail: format!("state doc id {doc_id} is out of range for {segment_id}"),
            });
        }
        if !claimed.insert((index, doc_id)) {
            return Err(IndexError::CorruptCommittedState {
                detail: "two live rows point to the same physical document".to_owned(),
            });
        }
        let key = reader.doc_key(doc_id)?;
        if key != row.key {
            return Err(IndexError::CorruptCommittedState {
                detail: "state pointer key does not match the physical document key".to_owned(),
            });
        }
        masks[index][usize::try_from(doc_id).unwrap_or(usize::MAX)] = true;
    }
    Ok(masks.into_iter().map(|mask| Some(Arc::new(mask))).collect())
}

/// Build effective live masks, opening a fresh reader per segment.
pub(crate) fn build_masks(
    state: &MutationStateV1,
    segments: &[SegmentSnapshot],
    limits: SegmentLimits,
) -> IndexResult<Vec<Option<Arc<Vec<bool>>>>> {
    let mut readers: Vec<SegmentReader> = Vec::new();
    readers
        .try_reserve_exact(segments.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: segments.len() as u64,
            requested: u64::MAX,
        })?;
    for segment in segments {
        readers.push(segment.open_reader(limits)?);
    }
    build_masks_from_readers(state, segments, &readers)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::AnalyzerRegistry;
    use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::index::SegmentMeta;
    use crate::index::mutation_state::KeyRow;
    use crate::segment::{SegmentBuilder, SegmentDocument};
    use quervant_objectstore::ContentDescriptor;

    fn segment() -> (SegmentSnapshot, SegmentReader) {
        let schema = Schema::new(
            vec![FieldDefinition::new(
                "title",
                FieldType::Text,
                Cardinality::Single,
                FieldOptions::indexed_stored(),
            )],
            None,
        )
        .unwrap();
        let registry = AnalyzerRegistry::builtin();
        let mut builder = SegmentBuilder::new(schema, registry).unwrap();
        for key in ["a", "b"] {
            let mut document = SegmentDocument::new(DocumentKey::new(key).unwrap());
            document
                .insert(
                    "title",
                    FieldValues::Single(FieldValue::Text(key.to_owned())),
                )
                .unwrap();
            builder.add_document(document).unwrap();
        }
        let built = builder.build().unwrap();
        let bytes = std::sync::Arc::new(built.bytes);
        let reader = SegmentReader::open(bytes.as_ref().clone(), SegmentLimits::default()).unwrap();
        let descriptor = ContentDescriptor::of(bytes.as_ref());
        let meta = SegmentMeta::new(
            "s-test",
            "index/segments/test.seg",
            descriptor,
            Vec::new(),
            Vec::new(),
            None,
        );
        (SegmentSnapshot::new(meta, bytes, 2), reader)
    }

    #[test]
    fn valid_live_pointers_build_masks() {
        let (segment, reader) = segment();
        let rows = [KeyRow::live(DocumentKey::new("a").unwrap(), 1, "s-test", 0)];
        let state = MutationStateV1::from_parts(
            rows.into_iter().map(|row| (row.key.clone(), row)).collect(),
            BTreeMap::new(),
        );
        let masks = build_masks_from_readers(
            &state,
            std::slice::from_ref(&segment),
            std::slice::from_ref(&reader),
        )
        .unwrap();
        assert!(masks[0].as_ref().unwrap()[0]);
        assert!(!masks[0].as_ref().unwrap()[1]);
    }

    #[test]
    fn key_mismatch_and_duplicate_pointers_are_rejected() {
        let (segment, reader) = segment();
        let wrong = KeyRow::live(DocumentKey::new("b").unwrap(), 1, "s-test", 0);
        let state = MutationStateV1::from_parts(
            [(wrong.key.clone(), wrong)].into_iter().collect(),
            BTreeMap::new(),
        );
        assert!(
            build_masks_from_readers(
                &state,
                std::slice::from_ref(&segment),
                std::slice::from_ref(&reader)
            )
            .is_err()
        );

        let first = KeyRow::live(DocumentKey::new("a").unwrap(), 1, "s-test", 0);
        let second = KeyRow::live(DocumentKey::new("b").unwrap(), 1, "s-test", 0);
        let state = MutationStateV1::from_parts(
            [(first.key.clone(), first), (second.key.clone(), second)]
                .into_iter()
                .collect(),
            BTreeMap::new(),
        );
        assert!(
            build_masks_from_readers(
                &state,
                std::slice::from_ref(&segment),
                std::slice::from_ref(&reader)
            )
            .is_err()
        );

        // Dangling segment id.
        let dangling = KeyRow::live(DocumentKey::new("a").unwrap(), 1, "other", 0);
        let state = MutationStateV1::from_parts(
            [(dangling.key.clone(), dangling)].into_iter().collect(),
            BTreeMap::new(),
        );
        assert!(
            build_masks_from_readers(
                &state,
                std::slice::from_ref(&segment),
                std::slice::from_ref(&reader)
            )
            .is_err()
        );
    }
}
