//! Bounded segment reader over the real `Directory` seam (Phase E).
//!
//! The reader validates the full envelope, exposes typed accessors, and never
//! publishes a generation or implements PR 6 lifecycle.

use std::cell::RefCell;
use std::rc::Rc;

use trawler_objectstore::ContentDescriptor;

use crate::storage::{Directory, ReadHandle, StorageKey};

use super::bounds::{GeoBounds, TimeBounds};
use super::column::ColumnReader;
use super::dictionary::DictionaryReader;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ContainerKind, SectionEntry, SectionKind, parse_container};
use super::limits::SegmentLimits;
use super::postings::PostingsReader;
use super::remap::DocRemap;
use super::schema::CodecSchema;
use super::stored::{StoredRecord, decode_stored};

/// A validated, bounded reader over an immutable segment container.
pub struct SegmentReader {
    bytes: Vec<u8>,
    limits: SegmentLimits,
    doc_count: u64,
    sections: Vec<SectionEntry>,
    required: Vec<(u16, u16)>,
    optional: Vec<(u16, u16)>,
    schema: CodecSchema,
    remap: DocRemap,
    dictionary: Option<DictionaryReader>,
    time_bounds: Option<TimeBounds>,
    geo_bounds: Vec<GeoBounds>,
    stored_cache: RefCell<Option<Rc<Vec<StoredRecord>>>>,
}

impl SegmentReader {
    /// Parse and validate a segment from owned bytes.
    pub fn open(bytes: Vec<u8>, limits: SegmentLimits) -> SegmentResult<Self> {
        if bytes.len() as u64 > limits.accepted_segment_bytes() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.accepted_segment_bytes(),
                requested: bytes.len() as u64,
            });
        }
        let view = parse_container(&bytes, &limits)?;
        if view.kind() != ContainerKind::Segment {
            return Err(SegmentError::Corrupt {
                context: "segment",
                detail: "not a segment container".to_owned(),
            });
        }
        view.ensure_supported_features()?;
        let doc_count = view.doc_count();
        let sections = view.sections().to_vec();
        let required = view.required_features().to_vec();
        let optional = view.optional_features().to_vec();
        let schema = CodecSchema::decode(
            view.body(SectionKind::Schema)
                .ok_or(SegmentError::MissingSection {
                    kind: SectionKind::Schema as u16,
                })?,
            &limits,
        )?;
        let remap = match view.body(SectionKind::SortedRemap) {
            Some(body) => DocRemap::decode(body, doc_count as usize, &limits)?,
            None => DocRemap::identity(doc_count as usize),
        };
        let dictionary = match view.body(SectionKind::Dictionary) {
            Some(body) => Some(DictionaryReader::new(body, &limits)?),
            None => None,
        };
        let time_bounds = match view.body(SectionKind::TimeBounds) {
            Some(body) => Some(TimeBounds::decode(body)?),
            None => None,
        };
        let geo_bounds = match view.body(SectionKind::GeoBounds) {
            Some(body) => decode_geo_bounds(body)?,
            None => Vec::new(),
        };
        drop(view);
        Ok(Self {
            bytes,
            limits,
            doc_count,
            sections,
            required,
            optional,
            schema,
            remap,
            dictionary,
            time_bounds,
            geo_bounds,
            stored_cache: RefCell::new(None),
        })
    }

    /// Read an entire segment from a `Directory` with bounded positional reads.
    pub fn open_directory(
        directory: &dyn Directory,
        key: &StorageKey,
        limits: SegmentLimits,
    ) -> SegmentResult<Self> {
        let bytes = read_all(directory, key, &limits)?;
        Self::open(bytes, limits)
    }

    /// Verify the whole file (including trailer) against a trusted descriptor.
    pub fn verify_content_descriptor(&self, expected: &ContentDescriptor) -> SegmentResult<()> {
        verify_bytes(&self.bytes, expected)
    }

    /// Declared document count.
    #[must_use]
    pub const fn doc_count(&self) -> u64 {
        self.doc_count
    }

    /// Canonical schema.
    #[must_use]
    pub const fn schema(&self) -> &CodecSchema {
        &self.schema
    }

    /// Doc-id remap.
    #[must_use]
    pub const fn remap(&self) -> &DocRemap {
        &self.remap
    }

    /// Raw container bytes.
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// Required features.
    #[must_use]
    pub fn required_features(&self) -> &[(u16, u16)] {
        &self.required
    }

    /// Optional features.
    #[must_use]
    pub fn optional_features(&self) -> &[(u16, u16)] {
        &self.optional
    }

    /// Parsed section entries.
    #[must_use]
    pub fn sections(&self) -> &[SectionEntry] {
        &self.sections
    }

    /// The term dictionary, if present.
    #[must_use]
    pub const fn dictionary(&self) -> Option<&DictionaryReader> {
        self.dictionary.as_ref()
    }

    /// Temporal bounds, if present.
    #[must_use]
    pub const fn time_bounds(&self) -> Option<&TimeBounds> {
        self.time_bounds.as_ref()
    }

    /// Geographic bounds.
    #[must_use]
    pub fn geo_bounds(&self) -> &[GeoBounds] {
        &self.geo_bounds
    }

    /// Lazily decode and cache all stored records.
    pub fn stored(&self) -> SegmentResult<Rc<Vec<StoredRecord>>> {
        if let Some(records) = self.stored_cache.borrow().as_ref() {
            return Ok(Rc::clone(records));
        }
        let body = self
            .body(SectionKind::Stored)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Stored as u16,
            })?;
        let records = Rc::new(decode_stored(&self.schema, body, &self.limits)?);
        *self.stored_cache.borrow_mut() = Some(Rc::clone(&records));
        Ok(records)
    }

    /// Decode one document's stored record.
    pub fn stored_doc(&self, doc_id: u64) -> SegmentResult<StoredRecord> {
        let records = self.stored()?;
        records
            .get(doc_id as usize)
            .cloned()
            .ok_or(SegmentError::Corrupt {
                context: "stored",
                detail: "doc id out of range".to_owned(),
            })
    }

    /// Decode one document's column value for a field.
    pub fn column_value(
        &self,
        field_id: u32,
        doc_id: u64,
    ) -> SegmentResult<Option<crate::contract::document::FieldValues>> {
        let Some(body) = self.body(SectionKind::Columns) else {
            return Ok(None);
        };
        let reader = ColumnReader::open(&self.schema, body, &self.limits)?;
        reader.value(field_id, doc_id)
    }

    /// Open a bounded postings reader for `(field, term)`.
    pub fn postings(&self, field_id: u32, term: &str) -> SegmentResult<Option<PostingsReader<'_>>> {
        let Some(dictionary) = &self.dictionary else {
            return Ok(None);
        };
        let Some(entry) = dictionary.lookup(field_id, term) else {
            return Ok(None);
        };
        let body = self
            .body(SectionKind::Postings)
            .ok_or(SegmentError::MissingSection {
                kind: SectionKind::Postings as u16,
            })?;
        let start = entry.postings_offset as usize;
        let end =
            start
                .checked_add(entry.postings_length as usize)
                .ok_or(SegmentError::Corrupt {
                    context: "postings",
                    detail: "posting extent overflow".to_owned(),
                })?;
        let slice = body.get(start..end).ok_or(SegmentError::Corrupt {
            context: "postings",
            detail: "posting extent out of range".to_owned(),
        })?;
        Ok(Some(PostingsReader::new(
            slice,
            self.doc_count,
            &self.limits,
        )?))
    }

    fn body(&self, kind: SectionKind) -> Option<&[u8]> {
        let entry = self.sections.iter().find(|entry| entry.kind == kind)?;
        let start = entry.offset as usize;
        let end = start + entry.length as usize;
        self.bytes.get(start..end)
    }
}

/// Verify whole-file bytes against a trusted content descriptor.
pub fn verify_bytes(bytes: &[u8], expected: &ContentDescriptor) -> SegmentResult<()> {
    if expected.length != bytes.len() as u64 {
        return Err(SegmentError::LengthMismatch {
            context: "content descriptor",
            expected: expected.length,
            actual: bytes.len() as u64,
        });
    }
    if !expected.matches(bytes) {
        return Err(SegmentError::DigestMismatch {
            context: "content descriptor",
        });
    }
    Ok(())
}

fn read_all(
    directory: &dyn Directory,
    key: &StorageKey,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let handle: Box<dyn ReadHandle> = directory.open_read(key)?;
    let len = handle.len();
    if len > limits.accepted_segment_bytes() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.accepted_segment_bytes(),
            requested: len,
        });
    }
    let capacity = usize::try_from(len).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::from(u32::MAX),
        requested: len,
    })?;
    let mut bytes = vec![0u8; capacity];
    let mut offset = 0usize;
    while offset < capacity {
        let read = handle.read_at(offset as u64, &mut bytes[offset..])?;
        if read == 0 {
            return Err(SegmentError::LengthMismatch {
                context: "directory read",
                expected: len,
                actual: offset as u64,
            });
        }
        offset += read;
    }
    Ok(bytes)
}

fn decode_geo_bounds(body: &[u8]) -> SegmentResult<Vec<GeoBounds>> {
    let mut reader = ByteReader::new(body);
    let count = reader.u32("geo bound count")?;
    let mut bounds = Vec::with_capacity(count as usize);
    for _ in 0..count {
        let entry = reader.bytes(GEO_BOUNDS_ENTRY_LEN, "geo bounds entry")?;
        bounds.push(GeoBounds::decode(entry)?);
    }
    reader.expect_end("geo bounds")?;
    Ok(bounds)
}

/// Byte width of one encoded `GeoBounds` entry.
const GEO_BOUNDS_ENTRY_LEN: usize = 55;
