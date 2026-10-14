//! Deterministic segment fixture builder (Phases A–D).
//!
//! This is explicitly **not** a production `IndexWriter`: it validates an input
//! document set and composes immutable sections. It performs no commit,
//! publication, refresh or recovery.

use std::collections::BTreeMap;

use crate::analysis::{
    AnalysisLimits, AnalyzerRegistry, AnalyzerRole, NeverCancel, POSITION_GAP,
    SchemaAnalyzerBindings, Token,
};
use crate::contract::budget::Budgets;
use crate::contract::document::{Document, FieldValues};
use crate::contract::schema::Schema;
use crate::contract::value::{FieldType, FieldValue};

use super::bounds::{GeoBounds, TimeBounds, presence_of};
use super::column::encode_columns;
use super::dictionary::{DictionaryEntry, encode_dictionary};
use super::error::{SegmentError, SegmentResult};
use super::format::{
    ContainerBuilder, ContainerKind, FEATURE_BASELINE, FEATURE_BOUNDS, FEATURE_COLUMNS,
    FEATURE_FIELD_NORMS, FEATURE_JSON_PATHS, FEATURE_POSITIONAL, FEATURE_REMAP, FEATURE_STORED,
    SectionKind,
};
use super::json_paths::{JsonFieldOccurrences, encode_json_paths, extract_field_paths};
use super::limits::SegmentLimits;
use super::model::SegmentDocument;
use super::norms::{encode_field_norms, scoring_field_ids};
use super::postings::{Occurrence, Posting, encode_postings_block};
use super::remap::DocRemap;
use super::schema::CodecSchema;
use super::stored::encode_stored;

/// A built immutable segment and its validated remap.
#[derive(Debug, Clone)]
pub struct BuiltSegment {
    /// Encoded container bytes.
    pub bytes: Vec<u8>,
    /// Canonical schema.
    pub schema: CodecSchema,
    /// Physical↔original doc-id remap.
    pub remap: DocRemap,
}

/// Whether the builder sorts documents by their primary timestamp.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Layout {
    /// Keep insertion order.
    Insertion,
    /// Sort by primary timestamp ascending, then logical key bytes.
    TimestampSorted,
}

/// A deterministic segment builder over validated documents.
pub struct SegmentBuilder {
    contract_schema: Schema,
    schema: CodecSchema,
    registry: AnalyzerRegistry,
    docs: Vec<SegmentDocument>,
    limits: SegmentLimits,
    analysis_limits: AnalysisLimits,
    block_docs: u32,
    layout: Layout,
}

impl SegmentBuilder {
    /// Create a builder, resolving analyzer bindings (fail closed).
    pub fn new(schema: Schema, registry: AnalyzerRegistry) -> SegmentResult<Self> {
        let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).map_err(|_| {
            SegmentError::Corrupt {
                context: "schema bindings",
                detail: "analyzer binding resolution failed".to_owned(),
            }
        })?;
        let codec_schema = CodecSchema::from_contract(&schema, &bindings)?;
        let limits = SegmentLimits::default();
        let block_docs = limits.block_docs_default();
        Ok(Self {
            contract_schema: schema,
            schema: codec_schema,
            registry,
            docs: Vec::new(),
            limits,
            analysis_limits: AnalysisLimits::default(),
            block_docs,
            layout: Layout::Insertion,
        })
    }

    /// Override decoder/encoder limits.
    #[must_use]
    pub fn with_limits(mut self, limits: SegmentLimits) -> Self {
        self.block_docs = limits.block_docs_default();
        self.limits = limits;
        self
    }

    /// Override the column block size policy.
    #[must_use]
    pub const fn with_block_docs(mut self, block_docs: u32) -> Self {
        self.block_docs = block_docs;
        self
    }

    /// Select the physical layout.
    #[must_use]
    pub const fn with_layout(mut self, layout: Layout) -> Self {
        self.layout = layout;
        self
    }

    /// Add and validate a document.
    pub fn add_document(&mut self, document: SegmentDocument) -> SegmentResult<()> {
        let budgets = Budgets::new();
        let mut contract_doc = Document::new(document.key.clone());
        for (name, values) in &document.fields {
            contract_doc
                .insert(name.clone(), values.clone())
                .map_err(|error| SegmentError::Corrupt {
                    context: "document",
                    detail: format!("invalid field value: {error}"),
                })?;
        }
        self.contract_schema
            .validate_document(&contract_doc, &budgets)
            .map_err(|error| SegmentError::Corrupt {
                context: "document",
                detail: format!("schema validation failed: {error}"),
            })?;
        self.docs.push(document);
        Ok(())
    }

    /// Number of added documents.
    #[must_use]
    pub fn len(&self) -> usize {
        self.docs.len()
    }

    /// Whether no documents have been added.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.docs.is_empty()
    }

    /// Build the immutable segment.
    pub fn build(self) -> SegmentResult<BuiltSegment> {
        if self.docs.len() as u64 > self.limits.max_docs() {
            return Err(SegmentError::LimitExceeded {
                limit: self.limits.max_docs(),
                requested: self.docs.len() as u64,
            });
        }
        let doc_count = self.docs.len();
        let remap = self.compute_remap()?;
        let ordered: Vec<&SegmentDocument> = (0..doc_count)
            .map(|physical| {
                let original = remap.physical_to_original(physical as u64).map_err(|_| {
                    SegmentError::InvalidRemap {
                        context: "physical index",
                    }
                })? as usize;
                Ok(&self.docs[original])
            })
            .collect::<SegmentResult<_>>()?;

        // Postings, dictionary and per-document field norms, collected in one
        // analysis pass. `norms` is initialized for every scoring field so an
        // all-zero field is still represented.
        let mut norms: Vec<(u32, Vec<u64>)> = Vec::new();
        for field_id in scoring_field_ids(&self.schema) {
            let mut lengths: Vec<u64> = Vec::new();
            lengths
                .try_reserve_exact(doc_count)
                .map_err(|_| SegmentError::LimitExceeded {
                    limit: self.limits.max_single_allocation(),
                    requested: doc_count as u64,
                })?;
            lengths.resize(doc_count, 0);
            norms.push((field_id, lengths));
        }
        let mut postings_map: BTreeMap<(u32, String), Vec<Posting>> = BTreeMap::new();
        for (physical, doc) in ordered.iter().enumerate() {
            let analyzed = self.analyze_document(doc)?;
            for (field_id, tokens) in analyzed {
                let token_count = tokens.len() as u64;
                if let Some((_, lengths)) = norms.iter_mut().find(|(id, _)| *id == field_id) {
                    let slot = lengths.get_mut(physical).ok_or(SegmentError::Corrupt {
                        context: "field norms",
                        detail: "physical doc index out of range".to_owned(),
                    })?;
                    *slot = slot
                        .checked_add(token_count)
                        .ok_or(SegmentError::LimitExceeded {
                            limit: u64::MAX,
                            requested: u64::MAX,
                        })?;
                }
                let mut groups: BTreeMap<String, Vec<Occurrence>> = BTreeMap::new();
                for token in tokens {
                    groups
                        .entry(token.term().to_owned())
                        .or_default()
                        .push(Occurrence {
                            position: u64::from(token.position()),
                            position_length: u64::from(token.position_length()),
                            value_index: u64::from(token.value_index()),
                            start_offset: u64::from(token.start_offset()),
                            end_offset: u64::from(token.end_offset()),
                        });
                }
                for (term, occurrences) in groups {
                    postings_map
                        .entry((field_id, term))
                        .or_default()
                        .push(Posting {
                            doc_id: physical as u64,
                            freq: occurrences.len() as u64,
                            occurrences,
                        });
                }
            }
        }
        let norms_bytes = encode_field_norms(doc_count as u64, &norms, &self.limits)?;

        let mut postings_body = super::format::ByteWriter::new();
        let mut dictionary_fields: Vec<(u32, Vec<DictionaryEntry>)> = Vec::new();
        {
            let mut by_field: BTreeMap<u32, Vec<(String, Vec<Posting>)>> = BTreeMap::new();
            for ((field_id, term), postings) in postings_map {
                by_field.entry(field_id).or_default().push((term, postings));
            }
            for (field_id, terms) in by_field {
                let mut entries = Vec::with_capacity(terms.len());
                for (term, postings) in terms {
                    let offset = postings_body.len() as u64;
                    let block = encode_postings_block(doc_count as u64, &postings, &self.limits)?;
                    let length = block.len() as u64;
                    postings_body.bytes(&block);
                    entries.push(DictionaryEntry {
                        term,
                        doc_freq: postings.len() as u64,
                        postings_offset: offset,
                        postings_length: length,
                    });
                }
                dictionary_fields.push((field_id, entries));
            }
        }
        let has_positional_postings = !dictionary_fields.is_empty();

        let stored_bytes = encode_stored(&self.schema, &ordered_docs(&ordered), &self.limits)?;
        let has_columns = self.schema.fields().iter().any(|field| field.is_columnar());
        let columns_bytes = if has_columns {
            Some(encode_columns(
                &self.schema,
                &ordered_docs(&ordered),
                self.block_docs,
                &self.limits,
            )?)
        } else {
            None
        };

        let doc_keys = encode_doc_keys(&ordered)?;
        let version_refs = encode_version_refs(&ordered)?;
        let live_docs = encode_live_docs(&ordered)?;
        let time_bounds = self.compute_time_bounds()?;
        let geo_bounds = self.compute_geo_bounds()?;

        // Immutable JSON-path occurrences, rebuilt from the physical document
        // ordering. This is a path/leaf-value index, never a second JSON source.
        let mut json_sections: Vec<JsonFieldOccurrences> = Vec::new();
        for field in self.schema.fields() {
            if field.field_type != FieldType::Json || !field.is_indexed() {
                continue;
            }
            let mut occurrences = Vec::new();
            for (physical, doc) in ordered.iter().enumerate() {
                let values = doc
                    .fields
                    .get(&field.name)
                    .cloned()
                    .unwrap_or(FieldValues::Absent);
                let mut doc_occurrences =
                    extract_field_paths(physical as u64, &values, &self.limits)?;
                occurrences.append(&mut doc_occurrences);
            }
            json_sections.push(JsonFieldOccurrences {
                field_id: field.id,
                occurrences,
            });
        }
        let has_json_paths = !json_sections.is_empty();
        let json_bytes = if has_json_paths {
            Some(encode_json_paths(
                doc_count as u64,
                &mut json_sections,
                &self.limits,
            )?)
        } else {
            None
        };

        let mut builder = ContainerBuilder::new(ContainerKind::Segment, doc_count as u64);
        builder.require_feature(FEATURE_BASELINE, 1);
        // New segments always self-describe their BM25 norms as a required feature.
        builder.require_feature(FEATURE_FIELD_NORMS, 1);
        if has_positional_postings {
            builder.require_feature(FEATURE_POSITIONAL, 1);
        }
        builder.require_feature(FEATURE_STORED, 1);
        if has_columns {
            builder.require_feature(FEATURE_COLUMNS, 1);
        }
        if time_bounds.is_some() || !geo_bounds.is_empty() {
            builder.require_feature(FEATURE_BOUNDS, 1);
        }
        if !remap.is_identity() {
            builder.require_feature(FEATURE_REMAP, 1);
        }
        if has_json_paths {
            builder.require_feature(FEATURE_JSON_PATHS, 1);
        }
        builder.section(SectionKind::Schema, 0, 0, self.schema.encode()?);
        if has_positional_postings {
            builder.section(
                SectionKind::Dictionary,
                0,
                0,
                encode_dictionary(&dictionary_fields, &self.limits)?,
            );
            builder.section(SectionKind::Postings, 0, 0, postings_body.into_vec());
        }
        builder.section(SectionKind::DocKeys, 0, 0, doc_keys);
        builder.section(SectionKind::VersionRefs, 0, 0, version_refs);
        builder.section(SectionKind::LiveDocs, 0, 0, live_docs);
        builder.section(SectionKind::Stored, 0, 0, stored_bytes);
        // The norms section is required to be present whenever the feature is
        // declared; both are emitted together for every new segment.
        builder.section(SectionKind::FieldNorms, 0, 0, norms_bytes);
        if let Some(columns_bytes) = columns_bytes {
            builder.section(SectionKind::Columns, 0, 0, columns_bytes);
        }
        if let Some(time_bounds) = &time_bounds {
            builder.section(SectionKind::TimeBounds, 0, 0, time_bounds.encode());
        }
        if !geo_bounds.is_empty() {
            let mut writer = super::format::ByteWriter::new();
            writer.u32(u32::try_from(geo_bounds.len()).map_err(|_| {
                SegmentError::LimitExceeded {
                    limit: u64::from(u32::MAX),
                    requested: geo_bounds.len() as u64,
                }
            })?);
            for bounds in &geo_bounds {
                writer.bytes(&bounds.encode());
            }
            builder.section(SectionKind::GeoBounds, 0, 0, writer.into_vec());
        }
        if !remap.is_identity() {
            builder.section(SectionKind::SortedRemap, 0, 0, remap.encode());
        }
        if let Some(json_bytes) = json_bytes {
            builder.section(SectionKind::JsonPaths, 0, 0, json_bytes);
        }

        Ok(BuiltSegment {
            bytes: builder.build()?,
            schema: self.schema,
            remap,
        })
    }

    fn compute_remap(&self) -> SegmentResult<DocRemap> {
        let doc_count = self.docs.len();
        match self.layout {
            Layout::Insertion => Ok(DocRemap::identity(doc_count)),
            Layout::TimestampSorted => {
                let primary = self
                    .schema
                    .primary_timestamp()
                    .ok_or(SegmentError::Corrupt {
                        context: "layout",
                        detail: "timestamp-sorted layout requires a primary timestamp".to_owned(),
                    })?;
                let field_name = self
                    .schema
                    .field(primary)
                    .map(|field| field.name.clone())
                    .ok_or(SegmentError::UnknownFieldId { field_id: primary })?;
                let mut order: Vec<u64> = (0..doc_count as u64).collect();
                let mut keys: Vec<(i64, &str)> = Vec::with_capacity(doc_count);
                for doc in &self.docs {
                    let timestamp =
                        timestamp_of(doc, &field_name).ok_or_else(|| SegmentError::Corrupt {
                            context: "layout",
                            detail: "timestamp-sorted layout requires a timestamp on every doc"
                                .to_owned(),
                        })?;
                    keys.push((timestamp, doc.key.as_str()));
                }
                order.sort_by(|a, b| {
                    let (ta, ka) = keys[*a as usize];
                    let (tb, kb) = keys[*b as usize];
                    ta.cmp(&tb).then_with(|| ka.as_bytes().cmp(kb.as_bytes()))
                });
                DocRemap::from_order(order)
            }
        }
    }

    fn analyze_document(&self, doc: &SegmentDocument) -> SegmentResult<Vec<(u32, Vec<Token>)>> {
        let mut result = Vec::new();
        for field in self.schema.fields() {
            if !field.is_indexed()
                || !matches!(field.field_type, FieldType::Text | FieldType::Keyword)
            {
                continue;
            }
            let values_state = doc
                .fields
                .get(&field.name)
                .cloned()
                .unwrap_or(FieldValues::Absent);
            let strings: Vec<&str> = values_state
                .values()
                .filter_map(|value| match value {
                    FieldValue::Text(text) | FieldValue::Keyword(text) => Some(text.as_str()),
                    _ => None,
                })
                .collect();
            if strings.is_empty() {
                continue;
            }
            let tokens = match self.definition_for(field) {
                Some(definition) => definition
                    .collect_tokens(
                        AnalyzerRole::Index,
                        &strings,
                        &self.analysis_limits,
                        &NeverCancel,
                    )
                    .map_err(|error| SegmentError::Corrupt {
                        context: "analysis",
                        detail: format!("analyzer failed: {error}"),
                    })?,
                None => exact_tokens(&strings)?,
            };
            result.push((field.id, tokens));
        }
        Ok(result)
    }

    fn definition_for(
        &self,
        field: &super::schema::CodecField,
    ) -> Option<&crate::analysis::AnalyzerDefinition> {
        let name = match field.field_type {
            FieldType::Text => field.analyzer.as_ref(),
            FieldType::Keyword => field.normalizer.as_ref(),
            _ => None,
        }?;
        self.registry.get(&name.id).ok()
    }

    fn live_doc_count(&self) -> u64 {
        self.docs.iter().filter(|doc| doc.live).count() as u64
    }

    fn compute_time_bounds(&self) -> SegmentResult<Option<TimeBounds>> {
        let Some(primary) = self.schema.primary_timestamp() else {
            return Ok(None);
        };
        let field = self
            .schema
            .field(primary)
            .ok_or(SegmentError::UnknownFieldId { field_id: primary })?;
        let field_name = field.name.clone();
        let live_count = self.live_doc_count();
        let mut present: Vec<i64> = Vec::new();
        for doc in self.docs.iter().filter(|doc| doc.live) {
            if let Some(timestamp) = timestamp_of(doc, &field_name) {
                present.push(timestamp);
            }
        }
        let present_count = present.len() as u64;
        let known = present_count > 0;
        let (min, max) = if known {
            (
                present.iter().copied().min().unwrap_or(0),
                present.iter().copied().max().unwrap_or(0),
            )
        } else {
            (0, 0)
        };
        Ok(Some(TimeBounds {
            field_id: primary,
            known,
            presence: presence_of(live_count, present_count),
            live_count,
            present_count,
            min_micros: min,
            max_micros: max,
            ordered: self.layout == Layout::TimestampSorted,
        }))
    }

    fn compute_geo_bounds(&self) -> SegmentResult<Vec<GeoBounds>> {
        let mut bounds = Vec::new();
        for field in self.schema.fields() {
            if field.field_type != FieldType::GeoPoint || !field.is_columnar() {
                continue;
            }
            let live_count = self.live_doc_count();
            let mut points: Vec<(f64, f64)> = Vec::new();
            let mut present_count = 0u64;
            for doc in self.docs.iter().filter(|doc| doc.live) {
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
        Ok(bounds)
    }
}

fn ordered_docs(ordered: &[&SegmentDocument]) -> Vec<SegmentDocument> {
    ordered.iter().map(|doc| (*doc).clone()).collect()
}

fn timestamp_of(doc: &SegmentDocument, field_name: &str) -> Option<i64> {
    match doc.fields.get(field_name) {
        Some(FieldValues::Single(FieldValue::Timestamp(timestamp))) => Some(timestamp.as_micros()),
        _ => None,
    }
}

fn exact_tokens(values: &[&str]) -> SegmentResult<Vec<Token>> {
    let mut tokens = Vec::new();
    let mut previous_position: Option<u32> = None;
    let mut position_cursor: Option<u32> = None;
    for (index, value) in values.iter().enumerate() {
        if value.is_empty() || value.len() > 4096 {
            return Err(SegmentError::Corrupt {
                context: "exact term",
                detail: "term must be 1..=4096 bytes".to_owned(),
            });
        }
        let value_index = u32::try_from(index).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: index as u64,
        })?;
        let base = match position_cursor {
            None => 0,
            Some(previous) => previous
                .checked_add(POSITION_GAP)
                .ok_or(SegmentError::Corrupt {
                    context: "exact term",
                    detail: "position overflow".to_owned(),
                })?,
        };
        let increment = match previous_position {
            None => base.checked_add(1).ok_or(SegmentError::Corrupt {
                context: "exact term",
                detail: "position overflow".to_owned(),
            })?,
            Some(previous) => base.checked_sub(previous).ok_or(SegmentError::Corrupt {
                context: "exact term",
                detail: "position overflow".to_owned(),
            })?,
        };
        let end = u32::try_from(value.len()).map_err(|_| SegmentError::Corrupt {
            context: "exact term",
            detail: "value too long".to_owned(),
        })?;
        tokens.push(
            Token::new(*value, value_index, base, increment, 1, 0, end).map_err(|error| {
                SegmentError::Corrupt {
                    context: "exact term",
                    detail: format!("invalid token: {error}"),
                }
            })?,
        );
        position_cursor = Some(base);
        previous_position = Some(base);
    }
    Ok(tokens)
}

fn encode_doc_keys(ordered: &[&SegmentDocument]) -> SegmentResult<Vec<u8>> {
    let mut writer = super::format::ByteWriter::new();
    writer.u16(1);
    writer.u64(ordered.len() as u64);
    for doc in ordered {
        writer.len_prefixed_u16(doc.key.as_str().as_bytes())?;
    }
    Ok(writer.into_vec())
}

fn encode_version_refs(ordered: &[&SegmentDocument]) -> SegmentResult<Vec<u8>> {
    let mut writer = super::format::ByteWriter::new();
    writer.u16(1);
    writer.u8(1);
    writer.u64(ordered.len() as u64);
    for doc in ordered {
        writer.u64(doc.revision);
    }
    Ok(writer.into_vec())
}

fn encode_live_docs(ordered: &[&SegmentDocument]) -> SegmentResult<Vec<u8>> {
    let mut writer = super::format::ByteWriter::new();
    writer.u16(1);
    writer.u8(1);
    writer.u64(ordered.len() as u64);
    let mut bitmap = vec![0u8; ordered.len().div_ceil(8)];
    for (index, doc) in ordered.iter().enumerate() {
        if doc.live {
            bitmap[index / 8] |= 1 << (index % 8);
        }
    }
    writer.bytes(&bitmap);
    Ok(writer.into_vec())
}
