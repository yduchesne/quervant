//! Lossless explicit segment compaction (PR 9, Phase 3).
//!
//! Compaction merges the current committed segments by **remapping decoded
//! structures**, not by reconstructing documents from stored records and
//! re-analyzing them. It therefore preserves indexed-but-not-stored fields,
//! positional postings, typed columns, stored values, field norms, remap and
//! bounds. Dead physical documents are dropped; surviving documents receive
//! contiguous output doc ids in `(segment_id, old_doc_id)` order.
//!
//! Revisions, tombstones and the idempotency replay ledger are carried over
//! byte-semantically unchanged. The only mutation-state change is the winning
//! physical pointer of each live key.

use std::collections::BTreeMap;
use std::sync::Arc;

use quervant_objectstore::ContentDigest;

use crate::analysis::NeverCancel;
use crate::contract::document::{DocumentKey, FieldValues};
use crate::contract::value::{FieldType, FieldValue};
use crate::segment::bounds::presence_of;
use crate::segment::column::encode_columns;
use crate::segment::dictionary::{DictionaryEntry, encode_dictionary};
use crate::segment::format::{
    ByteWriter, ContainerBuilder, ContainerKind, FEATURE_BASELINE, FEATURE_BOUNDS, FEATURE_COLUMNS,
    FEATURE_FIELD_NORMS, FEATURE_MUTATION_STATE, FEATURE_POSITIONAL, FEATURE_STORED, SectionKind,
};
use crate::segment::norms::{encode_field_norms, scoring_field_ids};
use crate::segment::postings::{Posting, encode_postings_block};
use crate::segment::{
    GeoBounds, Manifest, ManifestSegmentRef, MutationStateRef, SegmentReader, TimeBounds,
};
use crate::storage::StorageKey;

use super::current::{CURRENT_KEY, CurrentPointer, manifest_key_for, state_key_for_hex};
use super::error::{IndexError, IndexResult};
use super::mutation_state::{KeyRow, MutationStateV1};
use super::snapshot::SegmentSnapshot;
use super::writer::IndexWriter;
use super::{support, visibility};

/// Outcome of an explicit compaction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MergeOutcome {
    /// The durable generation now authoritative.
    pub generation: u64,
    /// Number of live documents in the compacted output.
    pub documents: u64,
    /// Number of input segments considered.
    pub segments_merged: u64,
    /// Whether compaction was a typed no-op.
    pub no_op: bool,
}

/// Compact the current committed generation. See module documentation.
pub(crate) fn compact(writer: &mut IndexWriter) -> IndexResult<MergeOutcome> {
    writer.ensure_compactable()?;
    let source_segments = writer.committed_segment_snapshots();
    let Some(state) = writer.committed_state_arc() else {
        return Ok(no_op(writer, source_segments.len() as u64));
    };
    let limits = *writer.limits_ref().segment_limits();
    let mut readers: Vec<SegmentReader> = Vec::new();
    readers
        .try_reserve_exact(source_segments.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: source_segments.len() as u64,
            requested: u64::MAX,
        })?;
    for segment in &source_segments {
        readers.push(segment.open_reader(limits)?);
    }
    let masks = visibility::build_masks_from_readers(&state, &source_segments, &readers)?;
    let physical_total: u64 = source_segments.iter().map(SegmentSnapshot::doc_count).sum();
    let live_total: u64 = masks
        .iter()
        .map(|mask| {
            mask.as_ref()
                .map_or(0, |flags| flags.iter().filter(|flag| **flag).count() as u64)
        })
        .sum();
    if source_segments.len() <= 1 && live_total == physical_total {
        return Ok(no_op(writer, source_segments.len() as u64));
    }

    let schema = readers
        .first()
        .ok_or(IndexError::NotInitialized)?
        .schema()
        .clone();
    for reader in &readers {
        if reader.schema() != &schema {
            return Err(IndexError::SchemaMismatch {
                detail: "compaction inputs disagree on the codec schema".to_owned(),
            });
        }
    }

    // Deterministic mapping in (segment, old_doc_id) order.
    let mut mappings: Vec<Vec<Option<u64>>> = Vec::new();
    let mut new_meta: Vec<(usize, u64)> = Vec::new();
    for (source_index, segment) in source_segments.iter().enumerate() {
        let len = usize::try_from(segment.doc_count()).map_err(|_| IndexError::ResourceLimit {
            limit: segment.doc_count(),
            requested: u64::MAX,
        })?;
        let mut map = vec![None; len];
        if let Some(mask) = &masks[source_index] {
            for (old_doc, live) in mask.iter().enumerate() {
                if *live {
                    map[old_doc] = Some(new_meta.len() as u64);
                    new_meta.push((source_index, old_doc as u64));
                }
            }
        }
        mappings.push(map);
    }
    let new_doc_count = new_meta.len() as u64;

    // Gather decodable stored/columnar field states in output order.
    let mut out_docs = Vec::new();
    out_docs
        .try_reserve_exact(new_meta.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: new_doc_count,
            requested: u64::MAX,
        })?;
    for (source_index, old_doc) in &new_meta {
        let reader = &readers[*source_index];
        let key = reader.doc_key(*old_doc)?;
        let mut doc = crate::segment::SegmentDocument::new(key);
        let stored = reader.stored_doc(*old_doc)?;
        for (field_id, values) in stored.fields {
            if let Some(field) = schema.field(field_id) {
                doc.insert(field.name.clone(), values)?;
            }
        }
        for field in schema.fields() {
            if !field.is_columnar() || doc.fields.contains_key(&field.name) {
                continue;
            }
            if let Some(values) = reader.column_value(field.id, *old_doc)? {
                if !values.is_absent() {
                    doc.insert(field.name.clone(), values)?;
                }
            }
        }
        out_docs.push(doc);
    }

    let stored_bytes = crate::segment::stored::encode_stored(&schema, &out_docs, &limits)?;
    let has_columns = schema.fields().iter().any(|field| field.is_columnar());
    let columns_bytes = if has_columns {
        Some(encode_columns(
            &schema,
            &out_docs,
            limits.block_docs_default(),
            &limits,
        )?)
    } else {
        None
    };

    // Field norms: use persisted norms, or reconstruct from postings for a
    // genuine legacy segment.
    let scoring = scoring_field_ids(&schema);
    let mut norms: Vec<(u32, Vec<u64>)> = Vec::new();
    for field_id in &scoring {
        let mut per_source: Vec<Vec<u64>> = Vec::new();
        per_source
            .try_reserve_exact(readers.len())
            .map_err(|_| IndexError::ResourceLimit {
                limit: readers.len() as u64,
                requested: u64::MAX,
            })?;
        for reader in &readers {
            per_source.push(source_field_lengths(reader, *field_id)?);
        }
        let mut lengths = vec![0u64; new_meta.len()];
        for (new_doc, (source_index, old_doc)) in new_meta.iter().enumerate() {
            lengths[new_doc] = per_source[*source_index]
                .get(*old_doc as usize)
                .copied()
                .ok_or_else(|| IndexError::CorruptCommittedState {
                    detail: "field norm doc id out of range".to_owned(),
                })?;
        }
        norms.push((*field_id, lengths));
    }
    let norms_bytes = encode_field_norms(new_doc_count, &norms, &limits)?;

    // Positional postings: merge sorted dictionaries and remap doc ids.
    let mut terms: BTreeMap<u32, BTreeMap<String, Vec<Posting>>> = BTreeMap::new();
    for (source_index, reader) in readers.iter().enumerate() {
        let Some(dictionary) = reader.dictionary() else {
            continue;
        };
        for (field_id, entries) in dictionary.fields() {
            for entry in entries {
                let mut postings = reader.postings_for_entry(entry)?;
                let mut collected: Vec<Posting> = Vec::new();
                while let Some(posting) = postings.next_with(&NeverCancel)? {
                    let Some(Some(new_doc_id)) =
                        mappings[source_index].get(posting.doc_id as usize)
                    else {
                        continue;
                    };
                    collected.push(Posting {
                        doc_id: *new_doc_id,
                        freq: posting.freq,
                        occurrences: posting.occurrences,
                    });
                }
                if !collected.is_empty() {
                    terms
                        .entry(*field_id)
                        .or_default()
                        .entry(entry.term.clone())
                        .or_default()
                        .extend(collected);
                }
            }
        }
    }
    let mut postings_body = ByteWriter::new();
    let mut dictionary_fields: Vec<(u32, Vec<DictionaryEntry>)> = Vec::new();
    for (field_id, field_terms) in &terms {
        let mut entries = Vec::new();
        entries
            .try_reserve_exact(field_terms.len())
            .map_err(|_| IndexError::ResourceLimit {
                limit: field_terms.len() as u64,
                requested: u64::MAX,
            })?;
        for (term, postings) in field_terms {
            let offset = postings_body.len() as u64;
            let block = encode_postings_block(new_doc_count, postings, &limits)?;
            let length = block.len() as u64;
            postings_body.bytes(&block);
            entries.push(DictionaryEntry {
                term: term.clone(),
                doc_freq: postings.len() as u64,
                postings_offset: offset,
                postings_length: length,
            });
        }
        dictionary_fields.push((*field_id, entries));
    }
    let has_positional = !dictionary_fields.is_empty();

    // Revisions are carried from the authoritative logical state.
    let mut revisions: Vec<u64> = Vec::new();
    revisions
        .try_reserve_exact(new_meta.len())
        .map_err(|_| IndexError::ResourceLimit {
            limit: new_doc_count,
            requested: u64::MAX,
        })?;
    for doc in &out_docs {
        revisions.push(state.row(&doc.key).map_or(1, |row| row.revision));
    }

    let time_bounds = recompute_time_bounds(&schema, &out_docs);
    let geo_bounds = recompute_geo_bounds(&schema, &out_docs);

    let new_segment = if new_doc_count == 0 {
        None
    } else {
        let bytes = build_merged_segment(
            &schema,
            &out_docs,
            &stored_bytes,
            columns_bytes.as_deref(),
            &norms_bytes,
            &dictionary_fields,
            postings_body.as_slice(),
            has_positional,
            has_columns,
            &revisions,
            time_bounds,
            &geo_bounds,
            &limits,
        )?;
        let bytes = Arc::new(bytes);
        let (meta, doc_count) = support::meta_from_bytes(&limits, &bytes)?;
        Some((meta, bytes, doc_count))
    };

    let new_segment_id = new_segment
        .as_ref()
        .map(|(meta, _, _)| meta.segment_id().to_owned());

    // Update winning pointers; revisions, tombstones and replay are unchanged.
    let mut pointer_to_new: BTreeMap<(String, u64), u64> = BTreeMap::new();
    for (new_doc_id, (source_index, old_doc)) in new_meta.iter().enumerate() {
        pointer_to_new.insert(
            (
                source_segments[*source_index]
                    .meta()
                    .segment_id()
                    .to_owned(),
                *old_doc,
            ),
            new_doc_id as u64,
        );
    }
    let mut new_rows: BTreeMap<DocumentKey, KeyRow> = BTreeMap::new();
    for row in state.rows() {
        if !row.is_live() {
            new_rows.insert(row.key.clone(), row.clone());
            continue;
        }
        let segment_id =
            row.segment_id
                .as_ref()
                .ok_or_else(|| IndexError::CorruptCommittedState {
                    detail: "live state row is missing its segment".to_owned(),
                })?;
        let old_doc = row
            .doc_id
            .ok_or_else(|| IndexError::CorruptCommittedState {
                detail: "live state row is missing its doc id".to_owned(),
            })?;
        let new_doc = pointer_to_new
            .get(&(segment_id.clone(), old_doc))
            .copied()
            .ok_or_else(|| IndexError::CorruptCommittedState {
                detail: "live state row is not present in the merge mapping".to_owned(),
            })?;
        let new_segment_id =
            new_segment_id
                .as_ref()
                .ok_or_else(|| IndexError::CorruptCommittedState {
                    detail: "live state row exists without an output segment".to_owned(),
                })?;
        new_rows.insert(
            row.key.clone(),
            KeyRow::live(
                row.key.clone(),
                row.revision,
                new_segment_id.clone(),
                new_doc,
            ),
        );
    }
    let replay: BTreeMap<_, _> = state
        .replay_rows()
        .iter()
        .map(|row| (row.token.clone(), row.clone()))
        .collect();
    let new_state = MutationStateV1::from_parts(new_rows, replay);

    // Durably publish the compacted generation.
    let generation = writer.next_generation()?;
    let state_bytes = new_state.encode()?;
    if state_bytes.len() as u64 > writer.limits_ref().max_mutation_state_bytes() {
        return Err(IndexError::ResourceLimit {
            limit: writer.limits_ref().max_mutation_state_bytes(),
            requested: state_bytes.len() as u64,
        });
    }
    let state_digest = ContentDigest::sha256_v1(&state_bytes);
    let state_ref = MutationStateRef {
        object_key: state_key_for_hex(&state_digest.to_hex()),
        content_length: state_bytes.len() as u64,
        content_digest: *state_digest.as_bytes(),
    };

    let mut refs: Vec<ManifestSegmentRef> = Vec::new();
    let mut segments_snapshot: Vec<SegmentSnapshot> = Vec::new();
    if let Some((meta, bytes, doc_count)) = new_segment {
        refs.push(ManifestSegmentRef {
            segment_id: meta.segment_id().to_owned(),
            object_key: meta.object_key().to_owned(),
            content_algorithm: 0,
            content_length: meta.descriptor().length,
            content_digest: *meta.descriptor().digest.as_bytes(),
            time_bounds: meta.time_bounds().cloned(),
            required_features: meta.required_features().to_vec(),
            optional_features: meta.optional_features().to_vec(),
        });
        segments_snapshot.push(SegmentSnapshot::new(meta, Arc::clone(&bytes), doc_count));
        let key = StorageKey::parse(segments_snapshot[0].meta().object_key())?;
        support::install_immutable(writer.directory().as_ref(), &key, bytes.as_slice())?;
    }
    refs.sort_by(|left, right| left.segment_id.cmp(&right.segment_id));

    let committed_manifest = writer
        .committed_manifest()
        .ok_or(IndexError::NotInitialized)?;
    let mut required_features = committed_manifest.required_features.clone();
    if !required_features.contains(&(FEATURE_MUTATION_STATE, 1)) {
        required_features.push((FEATURE_MUTATION_STATE, 1));
    }
    required_features.sort_unstable();
    required_features.dedup();
    let manifest = Manifest {
        schema: schema.clone(),
        segments: refs,
        required_features,
        optional_features: committed_manifest.optional_features.clone(),
        mutation_state: Some(state_ref.clone()),
    };
    let manifest_bytes = manifest.encode()?;
    if manifest_bytes.len() as u64 > writer.limits_ref().max_manifest_bytes() {
        return Err(IndexError::ResourceLimit {
            limit: writer.limits_ref().max_manifest_bytes(),
            requested: manifest_bytes.len() as u64,
        });
    }
    let state_key = StorageKey::parse(&state_ref.object_key)?;
    support::install_immutable(writer.directory().as_ref(), &state_key, &state_bytes)?;
    let manifest_key = StorageKey::parse(manifest_key_for(generation))?;
    support::install_immutable(writer.directory().as_ref(), &manifest_key, &manifest_bytes)?;

    let pointer = CurrentPointer::new(
        generation,
        manifest_bytes.len() as u64,
        ContentDigest::sha256_v1(&manifest_bytes),
    )?;
    let current_key = StorageKey::parse(CURRENT_KEY)?;
    match writer
        .directory()
        .atomic_write(&current_key, &pointer.encode()?)
    {
        Ok(()) => {
            writer.install_compacted(
                generation,
                manifest,
                segments_snapshot,
                Arc::new(new_state),
            )?;
            Ok(MergeOutcome {
                generation,
                documents: new_doc_count,
                segments_merged: source_segments.len() as u64,
                no_op: false,
            })
        }
        Err(_) => {
            writer.poison();
            Err(IndexError::RecoveryRequired {
                detail: "CURRENT publication failed during compaction".to_owned(),
            })
        }
    }
}

/// A typed no-op preserving the current generation.
fn no_op(writer: &IndexWriter, segments_merged: u64) -> MergeOutcome {
    MergeOutcome {
        generation: writer.generation().unwrap_or(0),
        documents: 0,
        segments_merged,
        no_op: true,
    }
}

fn source_field_lengths(reader: &SegmentReader, field_id: u32) -> IndexResult<Vec<u64>> {
    if let Some(norms) = reader.field_norms().and_then(|norms| norms.field(field_id)) {
        return Ok(norms.lengths().to_vec());
    }
    // Legacy segment: reconstruct per-doc lengths from postings.
    let mut lengths = vec![0u64; reader.doc_count() as usize];
    if let Some(entries) = reader.dictionary().and_then(|dict| dict.field(field_id)) {
        for entry in entries {
            let mut postings = reader.postings_for_entry(entry)?;
            while let Some(posting) = postings.next_with(&NeverCancel)? {
                let slot = lengths.get_mut(posting.doc_id as usize).ok_or_else(|| {
                    IndexError::CorruptCommittedState {
                        detail: "posting doc id out of range".to_owned(),
                    }
                })?;
                *slot = slot
                    .checked_add(posting.freq)
                    .ok_or(IndexError::ResourceLimit {
                        limit: u64::MAX,
                        requested: u64::MAX,
                    })?;
            }
        }
    }
    Ok(lengths)
}

#[allow(clippy::too_many_arguments)]
fn build_merged_segment(
    schema: &crate::segment::CodecSchema,
    out_docs: &[crate::segment::SegmentDocument],
    stored_bytes: &[u8],
    columns_bytes: Option<&[u8]>,
    norms_bytes: &[u8],
    dictionary_fields: &[(u32, Vec<DictionaryEntry>)],
    postings_body: &[u8],
    has_positional: bool,
    has_columns: bool,
    revisions: &[u64],
    time_bounds: Option<TimeBounds>,
    geo_bounds: &[GeoBounds],
    limits: &crate::segment::SegmentLimits,
) -> IndexResult<Vec<u8>> {
    let doc_count = out_docs.len() as u64;
    let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count);
    builder.require_feature(FEATURE_BASELINE, 1);
    builder.require_feature(FEATURE_FIELD_NORMS, 1);
    if has_positional {
        builder.require_feature(FEATURE_POSITIONAL, 1);
    }
    builder.require_feature(FEATURE_STORED, 1);
    if has_columns {
        builder.require_feature(FEATURE_COLUMNS, 1);
    }
    if time_bounds.is_some() || !geo_bounds.is_empty() {
        builder.require_feature(FEATURE_BOUNDS, 1);
    }
    builder.section(SectionKind::Schema, 0, 0, schema.encode()?);
    if has_positional {
        builder.section(
            SectionKind::Dictionary,
            0,
            0,
            encode_dictionary(dictionary_fields, limits)?,
        );
        builder.section(SectionKind::Postings, 0, 0, postings_body.to_vec());
    }
    builder.section(SectionKind::DocKeys, 0, 0, encode_doc_keys(out_docs)?);
    builder.section(
        SectionKind::VersionRefs,
        0,
        0,
        encode_version_refs(revisions)?,
    );
    builder.section(SectionKind::LiveDocs, 0, 0, encode_live_docs(doc_count)?);
    builder.section(SectionKind::Stored, 0, 0, stored_bytes.to_vec());
    builder.section(SectionKind::FieldNorms, 0, 0, norms_bytes.to_vec());
    if let Some(columns_bytes) = columns_bytes {
        builder.section(SectionKind::Columns, 0, 0, columns_bytes.to_vec());
    }
    if let Some(time_bounds) = &time_bounds {
        builder.section(SectionKind::TimeBounds, 0, 0, time_bounds.encode());
    }
    if !geo_bounds.is_empty() {
        let mut writer = ByteWriter::new();
        writer.u32(geo_bounds.len() as u32);
        for bounds in geo_bounds {
            writer.bytes(&bounds.encode());
        }
        builder.section(SectionKind::GeoBounds, 0, 0, writer.into_vec());
    }
    Ok(builder.build()?)
}

fn encode_doc_keys(docs: &[crate::segment::SegmentDocument]) -> IndexResult<Vec<u8>> {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u64(docs.len() as u64);
    for doc in docs {
        writer.len_prefixed_u16(doc.key.as_str().as_bytes())?;
    }
    Ok(writer.into_vec())
}

fn encode_version_refs(revisions: &[u64]) -> IndexResult<Vec<u8>> {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u8(1);
    writer.u64(revisions.len() as u64);
    for revision in revisions {
        writer.u64(*revision);
    }
    Ok(writer.into_vec())
}

fn encode_live_docs(doc_count: u64) -> IndexResult<Vec<u8>> {
    let mut writer = ByteWriter::new();
    writer.u16(1);
    writer.u8(1);
    writer.u64(doc_count);
    let len = usize::try_from(doc_count).map_err(|_| IndexError::ResourceLimit {
        limit: doc_count,
        requested: u64::MAX,
    })?;
    let mut bitmap = vec![0u8; len.div_ceil(8)];
    for (index, byte) in bitmap.iter_mut().enumerate() {
        // All docs are live; fill every full byte and mask the trailing byte.
        let remaining = len.saturating_sub(index * 8).min(8);
        if remaining == 8 {
            *byte = 0xFF;
        } else {
            *byte = (1u16.checked_shl(remaining as u32).unwrap_or(0) as u8).wrapping_sub(1);
        }
    }
    writer.bytes(&bitmap);
    Ok(writer.into_vec())
}

fn recompute_time_bounds(
    schema: &crate::segment::CodecSchema,
    docs: &[crate::segment::SegmentDocument],
) -> Option<TimeBounds> {
    let primary = schema.primary_timestamp()?;
    let field = schema.field(primary)?;
    let field_name = field.name.as_str();
    let live_count = docs.len() as u64;
    let mut present: Vec<i64> = Vec::new();
    for doc in docs {
        if let Some(FieldValues::Single(FieldValue::Timestamp(timestamp))) =
            doc.fields.get(field_name)
        {
            present.push(timestamp.as_micros());
        }
    }
    let present_count = present.len() as u64;
    let known = present_count > 0;
    let (min_micros, max_micros) = if known {
        (
            present.iter().copied().min().unwrap_or(0),
            present.iter().copied().max().unwrap_or(0),
        )
    } else {
        (0, 0)
    };
    Some(TimeBounds {
        field_id: primary,
        known,
        presence: if present_count == 0 {
            crate::segment::bounds::PRESENCE_UNKNOWN
        } else {
            presence_of(live_count, present_count)
        },
        live_count,
        present_count,
        min_micros,
        max_micros,
        ordered: false,
    })
}

fn recompute_geo_bounds(
    schema: &crate::segment::CodecSchema,
    docs: &[crate::segment::SegmentDocument],
) -> Vec<GeoBounds> {
    let mut bounds = Vec::new();
    let live_count = docs.len() as u64;
    for field in schema.fields() {
        if field.field_type != FieldType::GeoPoint || !field.is_columnar() {
            continue;
        }
        let mut points: Vec<(f64, f64)> = Vec::new();
        let mut present_count = 0u64;
        for doc in docs {
            let mut doc_points = 0u64;
            if let Some(values) = doc.fields.get(&field.name) {
                for value in values.values() {
                    if let FieldValue::GeoPoint(point) = value {
                        points.push((point.lon(), point.lat()));
                        doc_points += 1;
                    }
                }
            }
            if doc_points > 0 {
                present_count += 1;
            }
        }
        if present_count == 0 {
            bounds.push(GeoBounds::unknown(field.id, live_count));
            continue;
        }
        let min_lon = points
            .iter()
            .map(|(lon, _)| *lon)
            .fold(f64::INFINITY, f64::min);
        let max_lon = points
            .iter()
            .map(|(lon, _)| *lon)
            .fold(f64::NEG_INFINITY, f64::max);
        let min_lat = points
            .iter()
            .map(|(_, lat)| *lat)
            .fold(f64::INFINITY, f64::min);
        let max_lat = points
            .iter()
            .map(|(_, lat)| *lat)
            .fold(f64::NEG_INFINITY, f64::max);
        let (west, east, crosses) = if max_lon - min_lon <= 180.0 {
            (min_lon, max_lon, false)
        } else {
            (max_lon, min_lon, true)
        };
        bounds.push(GeoBounds {
            field_id: field.id,
            known: true,
            presence: presence_of(live_count, present_count),
            live_count,
            present_count,
            west,
            south: min_lat,
            east,
            north: max_lat,
            crosses_antimeridian: crosses,
        });
    }
    bounds
}
