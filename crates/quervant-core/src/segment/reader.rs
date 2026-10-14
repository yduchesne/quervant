//! Bounded segment reader over the real `Directory` seam (Phase E).
//!
//! The reader validates the full envelope, exposes typed accessors, and never
//! publishes a generation or implements PR 6 lifecycle.

use std::cell::RefCell;
use std::rc::Rc;

use quervant_objectstore::ContentDescriptor;

use crate::contract::document::DocumentKey;
use crate::storage::{Directory, ReadHandle, StorageKey};

use super::bounds::{GeoBounds, TimeBounds};
use super::column::ColumnReader;
use super::dictionary::{DictionaryEntry, DictionaryReader};
use super::error::{SegmentError, SegmentResult};
use super::format::{
    ByteReader, ContainerKind, FEATURE_FIELD_NORMS, FEATURE_JSON_PATHS, SectionEntry, SectionKind,
    parse_container,
};
use super::json_paths::{JsonPathDirectory, JsonPathsReader};
use super::limits::SegmentLimits;
use super::norms::FieldNormsReader;
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
    norms: Option<FieldNormsReader>,
    time_bounds: Option<TimeBounds>,
    geo_bounds: Vec<GeoBounds>,
    json_paths: Option<Rc<JsonPathDirectory>>,
    stored_cache: RefCell<Option<Rc<Vec<StoredRecord>>>>,
    doc_keys_cache: RefCell<Option<Rc<Vec<DocumentKey>>>>,
    live_docs_cache: RefCell<Option<Rc<Vec<bool>>>>,
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
        // BM25 field norms: section and required feature must agree. Neither is a
        // valid legacy segment; both must be validated; a mismatch is corruption.
        let norms = match (
            view.body(SectionKind::FieldNorms),
            required.contains(&(FEATURE_FIELD_NORMS, 1)),
        ) {
            (None, false) => None,
            (Some(body), true) => {
                Some(FieldNormsReader::decode(body, doc_count, &schema, &limits)?)
            }
            _ => {
                return Err(SegmentError::Corrupt {
                    context: "field norms",
                    detail: "section/feature presence mismatch".to_owned(),
                });
            }
        };
        let remap = match view.body(SectionKind::SortedRemap) {
            Some(body) => DocRemap::decode(body, doc_count as usize, &limits)?,
            None => DocRemap::identity(doc_count as usize),
        };
        let dictionary = match view.body(SectionKind::Dictionary) {
            Some(body) => Some(DictionaryReader::new(body, &limits)?),
            None => None,
        };
        match (dictionary.as_ref(), view.body(SectionKind::Postings)) {
            (Some(dictionary), Some(postings_body)) => {
                let postings_len = postings_body.len() as u64;
                for (_, entries) in dictionary.fields() {
                    for entry in entries {
                        let end = entry
                            .postings_offset
                            .checked_add(entry.postings_length)
                            .ok_or(SegmentError::Corrupt {
                                context: "dictionary",
                                detail: "posting extent overflow".to_owned(),
                            })?;
                        if end > postings_len {
                            return Err(SegmentError::Corrupt {
                                context: "dictionary",
                                detail: "posting extent out of range".to_owned(),
                            });
                        }
                    }
                }
            }
            (Some(_), None) => {
                return Err(SegmentError::MissingSection {
                    kind: SectionKind::Postings as u16,
                });
            }
            (None, Some(_)) => {
                return Err(SegmentError::MissingSection {
                    kind: SectionKind::Dictionary as u16,
                });
            }
            (None, None) => {}
        }
        // Eager structural validation: column geometry is checked at open while
        // individual column values remain lazily decoded.
        if let Some(body) = view.body(SectionKind::Columns) {
            let _ = ColumnReader::open_with_doc_count(&schema, body, &limits, Some(doc_count))?;
        }
        // Stored count must agree with the container doc count.
        if let Some(body) = view.body(SectionKind::Stored) {
            validate_stored_header(body, doc_count)?;
        }
        let time_bounds = match view.body(SectionKind::TimeBounds) {
            Some(body) => Some(TimeBounds::decode(body)?),
            None => None,
        };
        let geo_bounds = match view.body(SectionKind::GeoBounds) {
            Some(body) => decode_geo_bounds(body, &limits)?,
            None => Vec::new(),
        };
        // JSON-path section and required feature must agree: neither alone is a
        // valid segment. A declared but malformed section fails closed here and
        // is never bypassed by a source fallback.
        let json_paths = match (
            view.body(SectionKind::JsonPaths),
            required.contains(&(FEATURE_JSON_PATHS, 1)),
        ) {
            (None, false) => None,
            (Some(body), true) => Some(Rc::new(JsonPathsReader::decode_directory(
                body, doc_count, &schema, &limits,
            )?)),
            _ => {
                return Err(SegmentError::Corrupt {
                    context: "json paths",
                    detail: "section/feature presence mismatch".to_owned(),
                });
            }
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
            norms,
            time_bounds,
            geo_bounds,
            json_paths,
            stored_cache: RefCell::new(None),
            doc_keys_cache: RefCell::new(None),
            live_docs_cache: RefCell::new(None),
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

    /// Persistent BM25 field norms, or `None` for a legacy segment.
    #[must_use]
    pub const fn field_norms(&self) -> Option<&FieldNormsReader> {
        self.norms.as_ref()
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

    /// Lazily decode and cache the byte-exact logical document keys.
    ///
    /// This is a read-only accessor over the existing `DOC_KEYS` section; it does
    /// not alter the on-disk encoding.
    pub fn doc_keys(&self) -> SegmentResult<Rc<Vec<DocumentKey>>> {
        if let Some(keys) = self.doc_keys_cache.borrow().as_ref() {
            return Ok(Rc::clone(keys));
        }
        let keys = Rc::new(decode_doc_keys(self)?);
        *self.doc_keys_cache.borrow_mut() = Some(Rc::clone(&keys));
        Ok(keys)
    }

    /// The logical key for one physical doc id.
    pub fn doc_key(&self, doc_id: u64) -> SegmentResult<DocumentKey> {
        let index = usize::try_from(doc_id).map_err(|_| SegmentError::Corrupt {
            context: "doc keys",
            detail: "doc id out of range".to_owned(),
        })?;
        self.doc_keys()?
            .get(index)
            .cloned()
            .ok_or(SegmentError::Corrupt {
                context: "doc keys",
                detail: "doc id out of range".to_owned(),
            })
    }

    /// Lazily decode and cache the live-doc bitmap.
    ///
    /// This is a read-only accessor over the existing `LIVE_DOCS` section; it does
    /// not alter the on-disk encoding.
    pub fn live_docs(&self) -> SegmentResult<Rc<Vec<bool>>> {
        if let Some(live) = self.live_docs_cache.borrow().as_ref() {
            return Ok(Rc::clone(live));
        }
        let live = Rc::new(decode_live_docs(self)?);
        *self.live_docs_cache.borrow_mut() = Some(Rc::clone(&live));
        Ok(live)
    }

    /// Whether one physical doc id is live.
    pub fn is_live(&self, doc_id: u64) -> SegmentResult<bool> {
        let index = usize::try_from(doc_id).map_err(|_| SegmentError::Corrupt {
            context: "live docs",
            detail: "doc id out of range".to_owned(),
        })?;
        self.live_docs()?
            .get(index)
            .copied()
            .ok_or(SegmentError::Corrupt {
                context: "live docs",
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

    /// Segment codec limits.
    #[must_use]
    pub(crate) const fn limits(&self) -> &SegmentLimits {
        &self.limits
    }

    /// Open a bounded reader over this segment's `JSON_PATHS` section.
    ///
    /// Returns `None` for a legacy segment without a JSON-path index. The
    /// validated offset directory is decoded once at segment open and reused for
    /// every query over this reader; no wire bytes are changed.
    pub(crate) fn open_json_paths(&self) -> SegmentResult<Option<JsonPathsReader<'_>>> {
        match &self.json_paths {
            None => Ok(None),
            Some(directory) => {
                let body =
                    self.body(SectionKind::JsonPaths)
                        .ok_or(SegmentError::MissingSection {
                            kind: SectionKind::JsonPaths as u16,
                        })?;
                Ok(Some(JsonPathsReader::new(
                    body,
                    Rc::clone(directory),
                    self.limits,
                )))
            }
        }
    }

    /// Open a bounded column reader over this segment's `COLUMNS` section.
    ///
    /// Returns `None` for a legacy segment without typed columns. This is a
    /// read-only accessor; callers that read many values should open once and
    /// reuse the reader instead of calling [`SegmentReader::column_value`] per
    /// value (which re-parses the column geometry each time). No wire bytes are
    /// changed.
    pub fn open_columns(&self) -> SegmentResult<Option<ColumnReader<'_>>> {
        match self.body(SectionKind::Columns) {
            Some(body) => Ok(Some(ColumnReader::open(&self.schema, body, &self.limits)?)),
            None => Ok(None),
        }
    }

    /// Open a bounded postings reader for `(field, term)`.
    pub fn postings(&self, field_id: u32, term: &str) -> SegmentResult<Option<PostingsReader<'_>>> {
        let Some(dictionary) = &self.dictionary else {
            return Ok(None);
        };
        let Some(entry) = dictionary.lookup(field_id, term) else {
            return Ok(None);
        };
        Ok(Some(self.postings_for_entry(entry)?))
    }

    /// Open a bounded postings reader for an already-resolved dictionary entry.
    ///
    /// This avoids a redundant linear dictionary lookup when a caller is already
    /// iterating `dictionary().field(field_id)` (for example BM25 field-length and
    /// document-frequency preparation). It is a read-only accessor; the posting
    /// encoding is unchanged.
    pub fn postings_for_entry(&self, entry: &DictionaryEntry) -> SegmentResult<PostingsReader<'_>> {
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
        let reader = PostingsReader::new(slice, self.doc_count, &self.limits)?;
        if reader.posting_doc_count() != entry.doc_freq {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "dictionary doc_freq does not match posting count".to_owned(),
            });
        }
        Ok(reader)
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
    let max_read = limits.max_read_bytes();
    if len > 0 && max_read == 0 {
        return Err(SegmentError::LimitExceeded {
            limit: 0,
            requested: 1,
        });
    }
    let capacity = usize::try_from(len).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::from(u32::MAX),
        requested: len,
    })?;
    let max_read_usize = usize::try_from(max_read).unwrap_or(usize::MAX);
    let mut bytes = vec![0u8; capacity];
    let mut offset = 0usize;
    while offset < capacity {
        let remaining = capacity - offset;
        let request = remaining.min(max_read_usize);
        if request == 0 {
            return Err(SegmentError::LimitExceeded {
                limit: max_read,
                requested: 1,
            });
        }
        let read = handle.read_at(offset as u64, &mut bytes[offset..offset + request])?;
        if read > request {
            return Err(SegmentError::Corrupt {
                context: "directory read",
                detail: "read_at returned more bytes than requested".to_owned(),
            });
        }
        if read == 0 {
            return Err(SegmentError::LengthMismatch {
                context: "directory read",
                expected: len,
                actual: offset as u64,
            });
        }
        offset = offset.checked_add(read).ok_or(SegmentError::Corrupt {
            context: "directory read",
            detail: "read offset overflow".to_owned(),
        })?;
    }
    Ok(bytes)
}

fn decode_geo_bounds(body: &[u8], limits: &SegmentLimits) -> SegmentResult<Vec<GeoBounds>> {
    let mut reader = ByteReader::new(body);
    let count = reader.u32("geo bound count")?;
    limits.check_entries(u64::from(count))?;
    limits.check_alloc::<GeoBounds>(u64::from(count))?;
    super::format::count_min_bytes(
        "geo bounds",
        u64::from(count),
        GEO_BOUNDS_ENTRY_LEN as u64,
        reader.remaining() as u64,
    )?;
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

fn decode_doc_keys(reader: &SegmentReader) -> SegmentResult<Vec<DocumentKey>> {
    let body = reader
        .body(SectionKind::DocKeys)
        .ok_or(SegmentError::MissingSection {
            kind: SectionKind::DocKeys as u16,
        })?;
    let mut bytes = ByteReader::new(body);
    let version = bytes.u16("doc keys version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "doc keys version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = bytes.u64("doc keys count")?;
    if count != reader.doc_count {
        return Err(SegmentError::Corrupt {
            context: "doc keys",
            detail: "doc key count does not match segment doc_count".to_owned(),
        });
    }
    reader.limits.check_entries(count)?;
    let capacity = usize::try_from(count).map_err(|_| SegmentError::LimitExceeded {
        limit: reader.limits.max_single_allocation(),
        requested: count,
    })?;
    // Minimum entry: a 2-byte length prefix plus at least one key byte.
    super::format::count_min_bytes("doc keys", count, 3, bytes.remaining() as u64)?;
    let mut keys: Vec<DocumentKey> = Vec::new();
    keys.try_reserve_exact(capacity)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: reader.limits.max_single_allocation(),
            requested: count,
        })?;
    for _ in 0..count {
        let key_bytes = bytes.len_prefixed_u16("doc key")?;
        let key_ref = std::str::from_utf8(key_bytes)
            .map_err(|_| SegmentError::InvalidUtf8 { context: "doc key" })?;
        let key = DocumentKey::new(key_ref).map_err(|_| SegmentError::Corrupt {
            context: "doc key",
            detail: "invalid document key".to_owned(),
        })?;
        keys.push(key);
    }
    bytes.expect_end("doc keys")?;
    Ok(keys)
}

fn decode_live_docs(reader: &SegmentReader) -> SegmentResult<Vec<bool>> {
    let body = reader
        .body(SectionKind::LiveDocs)
        .ok_or(SegmentError::MissingSection {
            kind: SectionKind::LiveDocs as u16,
        })?;
    let mut bytes = ByteReader::new(body);
    let version = bytes.u16("live docs version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "live docs version",
            detail: format!("unsupported {version}"),
        });
    }
    let present = bytes.u8("live docs present")?;
    if present != 1 {
        return Err(SegmentError::Corrupt {
            context: "live docs",
            detail: "unexpected presence tag".to_owned(),
        });
    }
    let count = bytes.u64("live docs count")?;
    if count != reader.doc_count {
        return Err(SegmentError::Corrupt {
            context: "live docs",
            detail: "live-doc count does not match segment doc_count".to_owned(),
        });
    }
    let count_usize = usize::try_from(count).map_err(|_| SegmentError::LimitExceeded {
        limit: reader.limits.max_single_allocation(),
        requested: count,
    })?;
    let bitmap_len = count_usize.div_ceil(8);
    let bitmap = bytes.bytes(bitmap_len, "live docs bitmap")?;
    bytes.expect_end("live docs")?;
    let mut live = Vec::new();
    live.try_reserve_exact(count_usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: reader.limits.max_single_allocation(),
            requested: count,
        })?;
    for index in 0..count_usize {
        live.push(bitmap[index / 8] & (1 << (index % 8)) != 0);
    }
    Ok(live)
}

fn validate_stored_header(body: &[u8], expected_doc_count: u64) -> SegmentResult<()> {
    let mut reader = ByteReader::new(body);
    let version = reader.u16("stored version")?;
    if version != 1 {
        return Err(SegmentError::Corrupt {
            context: "stored version",
            detail: format!("unsupported {version}"),
        });
    }
    let count = reader.u64("stored count")?;
    if count != expected_doc_count {
        return Err(SegmentError::Corrupt {
            context: "stored",
            detail: "stored count does not match segment doc_count".to_owned(),
        });
    }
    Ok(())
}
