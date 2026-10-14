//! Byte-level container primitives, header/footer/trailer and integrity (F02).
//!
//! All fixed-width integers are little-endian. Varints are canonical unsigned
//! LEB128. Every read is bounds-checked; no allocation is made from an
//! unvalidated count. Integrity uses the vetted RustCrypto `sha2` SHA-256.

use sha2::{Digest, Sha256};

use super::error::{SegmentError, SegmentResult};
use super::limits::SegmentLimits;

/// ASCII container magic for a segment file.
pub const SEGMENT_MAGIC: [u8; 8] = *b"TRWSEG01";
/// ASCII container magic for a manifest file.
pub const MANIFEST_MAGIC: [u8; 8] = *b"TRWMAN01";
/// ASCII container magic for an index mutation-state sidecar (PR 9).
pub const MUTATION_STATE_MAGIC: [u8; 8] = *b"TRWMSV01";
/// ASCII trailer magic.
pub const TRAILER_MAGIC: [u8; 8] = *b"TRWSTR01";

/// Supported major format version.
pub const FORMAT_MAJOR: u16 = 1;
/// Supported minor format version.
pub const FORMAT_MINOR: u16 = 0;
/// Fixed header length.
pub const HEADER_LEN: u64 = 24;
/// Fixed trailer length.
pub const TRAILER_LEN: u64 = 64;
/// Little-endian marker byte.
pub const ENDIAN_LE: u8 = 0x01;
/// Minimum possible container length (`header + empty footer + trailer`).
pub const MIN_FILE_LEN: u64 = 102;

/// Baseline feature every v1 container requires.
pub const FEATURE_BASELINE: u16 = 0x0001;
/// Stored source documents are present.
pub const FEATURE_STORED: u16 = 0x0002;
/// Positional postings are present.
pub const FEATURE_POSITIONAL: u16 = 0x0003;
/// Typed columns are present.
pub const FEATURE_COLUMNS: u16 = 0x0004;
/// Temporal/geo bounds are present.
pub const FEATURE_BOUNDS: u16 = 0x0005;
/// An explicit sorted doc-id remap is present.
pub const FEATURE_REMAP: u16 = 0x0006;
/// Persistent per-document BM25 field norms are present.
pub const FEATURE_FIELD_NORMS: u16 = 0x0007;
/// A referenced generation mutation-state sidecar is authoritative (PR 9).
pub const FEATURE_MUTATION_STATE: u16 = 0x0008;

/// Features this reader supports (id, version). Unknown *required* features fail.
pub const SUPPORTED_FEATURES: &[(u16, u16)] = &[
    (FEATURE_BASELINE, 1),
    (FEATURE_STORED, 1),
    (FEATURE_POSITIONAL, 1),
    (FEATURE_COLUMNS, 1),
    (FEATURE_BOUNDS, 1),
    (FEATURE_REMAP, 1),
    (FEATURE_FIELD_NORMS, 1),
    (FEATURE_MUTATION_STATE, 1),
];

/// Section kind identifiers.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(u16)]
pub enum SectionKind {
    /// Canonical schema.
    Schema = 0x0001,
    /// Sorted term dictionary.
    Dictionary = 0x0002,
    /// Positional postings.
    Postings = 0x0003,
    /// Byte-exact logical document keys.
    DocKeys = 0x0004,
    /// Revision references.
    VersionRefs = 0x0005,
    /// Live-doc bitmap.
    LiveDocs = 0x0006,
    /// Stored source documents.
    Stored = 0x0007,
    /// Typed columnar blocks.
    Columns = 0x0008,
    /// Temporal bounds.
    TimeBounds = 0x0009,
    /// Geographic bounds.
    GeoBounds = 0x000A,
    /// Sorted doc-id permutation.
    SortedRemap = 0x000B,
    /// Segment capability metadata.
    SegmentMeta = 0x000C,
    /// Manifest payload.
    Manifest = 0x000D,
    /// Persistent per-document BM25 field norms (PR 7 Amendment 05).
    FieldNorms = 0x000E,
    /// Index mutation-state sidecar payload (PR 9).
    MutationState = 0x000F,
}

impl SectionKind {
    /// Parse a raw kind value.
    #[must_use]
    pub const fn from_raw(raw: u16) -> Option<Self> {
        Some(match raw {
            0x0001 => Self::Schema,
            0x0002 => Self::Dictionary,
            0x0003 => Self::Postings,
            0x0004 => Self::DocKeys,
            0x0005 => Self::VersionRefs,
            0x0006 => Self::LiveDocs,
            0x0007 => Self::Stored,
            0x0008 => Self::Columns,
            0x0009 => Self::TimeBounds,
            0x000A => Self::GeoBounds,
            0x000B => Self::SortedRemap,
            0x000C => Self::SegmentMeta,
            0x000D => Self::Manifest,
            0x000E => Self::FieldNorms,
            0x000F => Self::MutationState,
            _ => return None,
        })
    }
}

/// Container kind.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContainerKind {
    /// Immutable segment.
    Segment,
    /// Manifest.
    Manifest,
    /// Index mutation-state sidecar (PR 9).
    MutationState,
}

impl ContainerKind {
    fn magic(self) -> [u8; 8] {
        match self {
            Self::Segment => SEGMENT_MAGIC,
            Self::Manifest => MANIFEST_MAGIC,
            Self::MutationState => MUTATION_STATE_MAGIC,
        }
    }
}

// ---------------------------------------------------------------------------
// Primitive writer
// ---------------------------------------------------------------------------

/// A little-endian, length-checked byte writer.
#[derive(Debug, Default, Clone)]
pub struct ByteWriter {
    buf: Vec<u8>,
}

impl ByteWriter {
    /// Create an empty writer.
    #[must_use]
    pub const fn new() -> Self {
        Self { buf: Vec::new() }
    }

    /// Create a writer with a pre-reserved capacity (bounded by the caller).
    #[must_use]
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            buf: Vec::with_capacity(capacity),
        }
    }

    /// Number of bytes written.
    #[must_use]
    pub fn len(&self) -> usize {
        self.buf.len()
    }

    /// Whether nothing has been written.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.buf.is_empty()
    }

    /// Consume the writer, returning the bytes.
    #[must_use]
    pub fn into_vec(self) -> Vec<u8> {
        self.buf
    }

    /// Borrow the written bytes.
    #[must_use]
    pub fn as_slice(&self) -> &[u8] {
        &self.buf
    }

    /// Write one byte.
    pub fn u8(&mut self, value: u8) {
        self.buf.push(value);
    }

    /// Write a little-endian `u16`.
    pub fn u16(&mut self, value: u16) {
        self.buf.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a little-endian `u32`.
    pub fn u32(&mut self, value: u32) {
        self.buf.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a little-endian `u64`.
    pub fn u64(&mut self, value: u64) {
        self.buf.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a little-endian `i64`.
    pub fn i64(&mut self, value: i64) {
        self.buf.extend_from_slice(&value.to_le_bytes());
    }

    /// Write a little-endian IEEE-754 `f64`.
    pub fn f64(&mut self, value: f64) {
        self.buf.extend_from_slice(&value.to_le_bytes());
    }

    /// Write raw bytes.
    pub fn bytes(&mut self, value: &[u8]) {
        self.buf.extend_from_slice(value);
    }

    /// Write a canonical unsigned LEB128 varint.
    pub fn varint(&mut self, mut value: u64) {
        loop {
            let mut byte = (value & 0x7f) as u8;
            value >>= 7;
            if value != 0 {
                byte |= 0x80;
            }
            self.buf.push(byte);
            if value == 0 {
                break;
            }
        }
    }

    /// Write a `u16` length prefix followed by the bytes.
    ///
    /// Fails if the slice is longer than `u16::MAX`.
    pub fn len_prefixed_u16(&mut self, value: &[u8]) -> SegmentResult<()> {
        let len = u16::try_from(value.len()).map_err(|_| SegmentError::LengthMismatch {
            context: "u16 length prefix",
            expected: u64::from(u16::MAX),
            actual: value.len() as u64,
        })?;
        self.u16(len);
        self.bytes(value);
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Primitive reader
// ---------------------------------------------------------------------------

/// A bounds-checked little-endian byte reader.
#[derive(Debug, Clone, Copy)]
pub struct ByteReader<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> ByteReader<'a> {
    /// Create a reader over `data`.
    #[must_use]
    pub const fn new(data: &'a [u8]) -> Self {
        Self { data, pos: 0 }
    }

    /// Bytes not yet consumed.
    #[must_use]
    pub fn remaining(&self) -> usize {
        self.data.len().saturating_sub(self.pos)
    }

    /// Whether the reader is exhausted.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.remaining() == 0
    }

    /// Current offset.
    #[must_use]
    pub fn position(&self) -> usize {
        self.pos
    }

    fn take(&mut self, n: usize, context: &'static str) -> SegmentResult<&'a [u8]> {
        let end = self.pos.checked_add(n).ok_or(SegmentError::Truncated {
            context,
            needed: n as u64,
            available: self.remaining() as u64,
        })?;
        if end > self.data.len() {
            return Err(SegmentError::Truncated {
                context,
                needed: n as u64,
                available: self.remaining() as u64,
            });
        }
        let slice = &self.data[self.pos..end];
        self.pos = end;
        Ok(slice)
    }

    /// Read one byte.
    pub fn u8(&mut self, context: &'static str) -> SegmentResult<u8> {
        Ok(self.take(1, context)?[0])
    }

    /// Read a little-endian `u16`.
    pub fn u16(&mut self, context: &'static str) -> SegmentResult<u16> {
        let bytes = self.take(2, context)?;
        Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
    }

    /// Read a little-endian `u32`.
    pub fn u32(&mut self, context: &'static str) -> SegmentResult<u32> {
        let bytes = self.take(4, context)?;
        Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
    }

    /// Read a little-endian `u64`.
    pub fn u64(&mut self, context: &'static str) -> SegmentResult<u64> {
        let bytes = self.take(8, context)?;
        let mut array = [0u8; 8];
        array.copy_from_slice(bytes);
        Ok(u64::from_le_bytes(array))
    }

    /// Read a little-endian `i64`.
    pub fn i64(&mut self, context: &'static str) -> SegmentResult<i64> {
        Ok(self.u64(context)? as i64)
    }

    /// Read a little-endian IEEE-754 `f64`.
    pub fn f64(&mut self, context: &'static str) -> SegmentResult<f64> {
        let bits = self.u64(context)?;
        let value = f64::from_bits(bits);
        if !value.is_finite() {
            return Err(SegmentError::NonFiniteFloat { context });
        }
        Ok(value)
    }

    /// Read exactly `n` bytes.
    pub fn bytes(&mut self, n: usize, context: &'static str) -> SegmentResult<&'a [u8]> {
        self.take(n, context)
    }

    /// Read a canonical unsigned LEB128 varint.
    ///
    /// Overlong encodings, encodings longer than 10 bytes, and values above
    /// `u64::MAX` are rejected.
    pub fn varint(&mut self, context: &'static str) -> SegmentResult<u64> {
        let mut result: u64 = 0;
        let mut shift: u32 = 0;
        let mut count: usize = 0;
        loop {
            let byte = self.u8(context)?;
            count += 1;
            if count > 10 {
                return Err(SegmentError::InvalidVarint { context });
            }
            let low = u64::from(byte & 0x7f);
            if shift == 63 && low > 1 {
                return Err(SegmentError::InvalidVarint { context });
            }
            result |= low
                .checked_shl(shift)
                .ok_or(SegmentError::InvalidVarint { context })?;
            if byte & 0x80 == 0 {
                if count > 1 && byte == 0 {
                    return Err(SegmentError::InvalidVarint { context });
                }
                return Ok(result);
            }
            shift = shift
                .checked_add(7)
                .ok_or(SegmentError::InvalidVarint { context })?;
        }
    }

    /// Read a `u16`-length-prefixed byte slice.
    pub fn len_prefixed_u16(&mut self, context: &'static str) -> SegmentResult<&'a [u8]> {
        let len = self.u16(context)? as usize;
        self.bytes(len, context)
    }

    /// Require the reader to be fully consumed.
    pub fn expect_end(&self, context: &'static str) -> SegmentResult<()> {
        if self.is_empty() {
            Ok(())
        } else {
            Err(SegmentError::Corrupt {
                context,
                detail: format!("{} trailing bytes", self.remaining()),
            })
        }
    }
}

/// Fail unless every required feature is supported by this reader.
pub fn ensure_features_supported(required: &[(u16, u16)]) -> SegmentResult<()> {
    for (id, version) in required {
        if !SUPPORTED_FEATURES.contains(&(*id, *version)) {
            return Err(SegmentError::UnsupportedFeature {
                feature_id: *id,
                version: *version,
            });
        }
    }
    Ok(())
}

/// Compute the SHA-256 digest of `data`.
#[must_use]
pub fn sha256(data: &[u8]) -> [u8; 32] {
    let digest = Sha256::digest(data);
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    out
}

/// Preflight that `count` items each need at least `min_per_item` bytes against
/// `available` remaining source bytes, using checked arithmetic.
pub(crate) fn count_min_bytes(
    context: &'static str,
    count: u64,
    min_per_item: u64,
    available: u64,
) -> SegmentResult<()> {
    let needed = count
        .checked_mul(min_per_item)
        .ok_or(SegmentError::Corrupt {
            context,
            detail: "count overflow".to_owned(),
        })?;
    if needed > available {
        return Err(SegmentError::Truncated {
            context,
            needed,
            available,
        });
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Container construction
// ---------------------------------------------------------------------------

/// A section body to encode.
#[derive(Debug, Clone)]
pub struct SectionInput {
    /// Section kind.
    pub kind: SectionKind,
    /// Section flags.
    pub flags: u16,
    /// Auxiliary value (column field id or zero).
    pub aux: u64,
    /// Exact body bytes.
    pub body: Vec<u8>,
}

/// Builder for an immutable container.
#[derive(Debug)]
pub struct ContainerBuilder {
    kind: ContainerKind,
    doc_count: u64,
    required: Vec<(u16, u16)>,
    optional: Vec<(u16, u16)>,
    sections: Vec<SectionInput>,
    max_sections: usize,
}

impl ContainerBuilder {
    /// Create a builder for `kind` with `doc_count` documents.
    #[must_use]
    pub fn new(kind: ContainerKind, doc_count: u64) -> Self {
        Self {
            kind,
            doc_count,
            required: vec![(FEATURE_BASELINE, 1)],
            optional: Vec::new(),
            sections: Vec::new(),
            max_sections: SegmentLimits::default().max_sections(),
        }
    }

    /// Add a required feature.
    pub fn require_feature(&mut self, feature_id: u16, version: u16) {
        self.required.push((feature_id, version));
    }

    /// Add an optional feature.
    pub fn optional_feature(&mut self, feature_id: u16, version: u16) {
        self.optional.push((feature_id, version));
    }

    /// Append a section body.
    pub fn section(&mut self, kind: SectionKind, flags: u16, aux: u64, body: Vec<u8>) {
        self.sections.push(SectionInput {
            kind,
            flags,
            aux,
            body,
        });
    }

    /// Encode the container to bytes.
    pub fn build(mut self) -> SegmentResult<Vec<u8>> {
        if self.sections.len() > self.max_sections {
            return Err(SegmentError::LimitExceeded {
                limit: self.max_sections as u64,
                requested: self.sections.len() as u64,
            });
        }
        self.sections.sort_by_key(|section| section.kind);
        for pair in self.sections.windows(2) {
            if pair[0].kind == pair[1].kind {
                return Err(SegmentError::DuplicateSection {
                    kind: pair[0].kind as u16,
                });
            }
        }

        let mut writer = ByteWriter::new();
        // Header.
        writer.bytes(&self.kind.magic());
        writer.u16(FORMAT_MAJOR);
        writer.u16(FORMAT_MINOR);
        writer.u8(ENDIAN_LE);
        writer.u8(HEADER_LEN as u8);
        writer.u16(0);
        writer.u64(self.doc_count);

        // Section bodies (contiguous).
        let mut directory: Vec<(SectionKind, u16, u64, u64, u64, [u8; 32])> =
            Vec::with_capacity(self.sections.len());
        for section in &self.sections {
            let offset = writer.len() as u64;
            let length = section.body.len() as u64;
            let digest = sha256(&section.body);
            writer.bytes(&section.body);
            directory.push((
                section.kind,
                section.flags,
                section.aux,
                offset,
                length,
                digest,
            ));
        }
        let footer_offset = writer.len() as u64;

        // Footer.
        writer.u16(1); // footer_version
        writer.u32(
            u32::try_from(directory.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: directory.len() as u64,
            })?,
        );
        self.required.sort_unstable();
        self.optional.sort_unstable();
        writer.u32(u32::try_from(self.required.len()).map_err(|_| {
            SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.required.len() as u64,
            }
        })?);
        for (id, version) in &self.required {
            writer.u16(*id);
            writer.u16(*version);
        }
        writer.u32(u32::try_from(self.optional.len()).map_err(|_| {
            SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: self.optional.len() as u64,
            }
        })?);
        for (id, version) in &self.optional {
            writer.u16(*id);
            writer.u16(*version);
        }
        for (kind, flags, aux, offset, length, digest) in &directory {
            writer.u16(*kind as u16);
            writer.u16(*flags);
            writer.u64(*aux);
            writer.u64(*offset);
            writer.u64(*length);
            writer.bytes(digest);
        }
        let footer_len = writer.len() as u64 - footer_offset;

        // Trailer + envelope digest.
        let trailer_offset = writer.len() as u64;
        let envelope_digest = sha256(&writer.as_slice()[..trailer_offset as usize]);
        writer.bytes(&TRAILER_MAGIC);
        writer.u64(footer_offset);
        writer.u64(footer_len);
        writer.u32(
            u32::try_from(directory.len()).map_err(|_| SegmentError::LimitExceeded {
                limit: u64::from(u32::MAX),
                requested: directory.len() as u64,
            })?,
        );
        writer.u16(1); // trailer_version
        writer.u16(0); // trailer_flags
        writer.bytes(&envelope_digest);
        debug_assert_eq!(writer.len() as u64, trailer_offset + TRAILER_LEN);
        Ok(writer.into_vec())
    }
}

// ---------------------------------------------------------------------------
// Parsed container view
// ---------------------------------------------------------------------------

/// A parsed and structurally validated section directory entry.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SectionEntry {
    /// Section kind.
    pub kind: SectionKind,
    /// Section flags.
    pub flags: u16,
    /// Auxiliary value.
    pub aux: u64,
    /// Absolute body offset.
    pub offset: u64,
    /// Body length.
    pub length: u64,
    /// SHA-256 of the body.
    pub digest: [u8; 32],
}

/// A structurally validated container backed by borrowed bytes.
#[derive(Debug)]
pub struct ContainerView<'a> {
    kind: ContainerKind,
    doc_count: u64,
    bytes: &'a [u8],
    sections: Vec<SectionEntry>,
    required: Vec<(u16, u16)>,
    optional: Vec<(u16, u16)>,
}

impl<'a> ContainerView<'a> {
    /// Container kind.
    #[must_use]
    pub const fn kind(&self) -> ContainerKind {
        self.kind
    }

    /// Declared document count (zero for a manifest).
    #[must_use]
    pub const fn doc_count(&self) -> u64 {
        self.doc_count
    }

    /// The borrowed container bytes.
    #[must_use]
    pub const fn bytes(&self) -> &'a [u8] {
        self.bytes
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

    /// All section entries in ascending kind order.
    #[must_use]
    pub fn sections(&self) -> &[SectionEntry] {
        &self.sections
    }

    /// Look up a section entry by kind.
    #[must_use]
    pub fn entry(&self, kind: SectionKind) -> Option<&SectionEntry> {
        self.sections.iter().find(|entry| entry.kind == kind)
    }

    /// Borrow a section body by kind.
    #[must_use]
    pub fn body(&self, kind: SectionKind) -> Option<&'a [u8]> {
        self.entry(kind).map(|entry| {
            let start = entry.offset as usize;
            let end = start + entry.length as usize;
            &self.bytes[start..end]
        })
    }

    /// Fail unless every required feature is supported.
    pub fn ensure_supported_features(&self) -> SegmentResult<()> {
        ensure_features_supported(&self.required)
    }
}

/// Parse and structurally validate a container, including the envelope digest.
pub fn parse_container<'a>(
    bytes: &'a [u8],
    limits: &SegmentLimits,
) -> SegmentResult<ContainerView<'a>> {
    let file_len = bytes.len() as u64;
    if file_len < MIN_FILE_LEN {
        return Err(SegmentError::Truncated {
            context: "container",
            needed: MIN_FILE_LEN,
            available: file_len,
        });
    }
    let trailer_offset = file_len - TRAILER_LEN;

    // Header.
    let mut header = ByteReader::new(bytes);
    let magic = header.bytes(8, "header magic")?;
    let kind = if magic == SEGMENT_MAGIC {
        ContainerKind::Segment
    } else if magic == MANIFEST_MAGIC {
        ContainerKind::Manifest
    } else if magic == MUTATION_STATE_MAGIC {
        ContainerKind::MutationState
    } else {
        return Err(SegmentError::InvalidMagic { context: "header" });
    };
    let major = header.u16("format major")?;
    let minor = header.u16("format minor")?;
    if major != FORMAT_MAJOR || minor != FORMAT_MINOR {
        return Err(SegmentError::UnsupportedFormatVersion { major, minor });
    }
    let endian = header.u8("endian")?;
    if endian != ENDIAN_LE {
        return Err(SegmentError::Corrupt {
            context: "endian marker",
            detail: format!("unsupported endian 0x{endian:02x}"),
        });
    }
    let header_len = header.u8("header length")?;
    if u64::from(header_len) != HEADER_LEN {
        return Err(SegmentError::Corrupt {
            context: "header length",
            detail: format!("expected {HEADER_LEN}, found {header_len}"),
        });
    }
    let header_flags = header.u16("header flags")?;
    if header_flags != 0 {
        return Err(SegmentError::UnknownFlags {
            context: "header",
            flags: u64::from(header_flags),
        });
    }
    let doc_count = header.u64("doc count")?;

    // Trailer.
    let mut trailer = ByteReader::new(&bytes[trailer_offset as usize..]);
    let trailer_magic = trailer.bytes(8, "trailer magic")?;
    if trailer_magic != TRAILER_MAGIC {
        return Err(SegmentError::InvalidMagic { context: "trailer" });
    }
    let footer_offset = trailer.u64("footer offset")?;
    let footer_len = trailer.u64("footer length")?;
    let trailer_section_count = trailer.u32("trailer section count")?;
    let trailer_version = trailer.u16("trailer version")?;
    if trailer_version != 1 {
        return Err(SegmentError::Corrupt {
            context: "trailer version",
            detail: format!("unsupported {trailer_version}"),
        });
    }
    let trailer_flags = trailer.u16("trailer flags")?;
    if trailer_flags != 0 {
        return Err(SegmentError::UnknownFlags {
            context: "trailer",
            flags: u64::from(trailer_flags),
        });
    }
    let envelope_digest = trailer.bytes(32, "envelope digest")?;
    trailer.expect_end("trailer")?;

    if footer_offset < HEADER_LEN {
        return Err(SegmentError::InvalidExtent {
            context: "footer offset",
            offset: footer_offset,
            length: footer_len,
            limit: trailer_offset,
        });
    }
    if footer_len > limits.max_footer_bytes() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_footer_bytes(),
            requested: footer_len,
        });
    }
    let footer_end = footer_offset
        .checked_add(footer_len)
        .ok_or(SegmentError::InvalidExtent {
            context: "footer extent",
            offset: footer_offset,
            length: footer_len,
            limit: trailer_offset,
        })?;
    if footer_end != trailer_offset {
        return Err(SegmentError::Corrupt {
            context: "footer extent",
            detail: format!("footer ends at {footer_end}, trailer starts at {trailer_offset}"),
        });
    }

    // Envelope digest over [0, trailer_offset).
    let computed = sha256(&bytes[..trailer_offset as usize]);
    if computed != envelope_digest {
        return Err(SegmentError::DigestMismatch {
            context: "envelope",
        });
    }

    // Footer.
    let footer_bytes = &bytes[footer_offset as usize..trailer_offset as usize];
    let mut footer = ByteReader::new(footer_bytes);
    let footer_version = footer.u16("footer version")?;
    if footer_version != 1 {
        return Err(SegmentError::Corrupt {
            context: "footer version",
            detail: format!("unsupported {footer_version}"),
        });
    }
    let section_count = footer.u32("section count")?;
    if section_count != trailer_section_count {
        return Err(SegmentError::Corrupt {
            context: "section count",
            detail: format!("footer {section_count}, trailer {trailer_section_count}"),
        });
    }
    if section_count as usize > limits.max_sections() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_sections() as u64,
            requested: u64::from(section_count),
        });
    }
    let required = read_features(&mut footer, "required features", limits)?;
    let optional = read_features(&mut footer, "optional features", limits)?;

    limits.check_alloc::<SectionEntry>(u64::from(section_count))?;
    let mut sections = Vec::with_capacity(section_count as usize);
    let mut expected_offset = HEADER_LEN;
    let mut previous_kind: Option<u16> = None;
    for _ in 0..section_count {
        let raw_kind = footer.u16("section kind")?;
        let kind = SectionKind::from_raw(raw_kind).ok_or(SegmentError::Corrupt {
            context: "section kind",
            detail: format!("unknown kind 0x{raw_kind:04x}"),
        })?;
        if let Some(previous) = previous_kind {
            if (kind as u16) <= previous {
                return Err(SegmentError::DuplicateSection { kind: raw_kind });
            }
        }
        previous_kind = Some(kind as u16);
        let flags = footer.u16("section flags")?;
        let aux = footer.u64("section aux")?;
        let offset = footer.u64("section offset")?;
        let length = footer.u64("section length")?;
        let digest = footer.bytes(32, "section digest")?;
        let mut digest_array = [0u8; 32];
        digest_array.copy_from_slice(digest);
        if offset != expected_offset {
            return Err(SegmentError::NonContiguousSections {
                expected: expected_offset,
                found: offset,
            });
        }
        let end = offset
            .checked_add(length)
            .ok_or(SegmentError::InvalidExtent {
                context: "section extent",
                offset,
                length,
                limit: footer_offset,
            })?;
        if end > footer_offset {
            return Err(SegmentError::InvalidExtent {
                context: "section extent",
                offset,
                length,
                limit: footer_offset,
            });
        }
        expected_offset = end;
        sections.push(SectionEntry {
            kind,
            flags,
            aux,
            offset,
            length,
            digest: digest_array,
        });
    }
    footer.expect_end("footer")?;
    if expected_offset != footer_offset {
        return Err(SegmentError::Corrupt {
            context: "section tiling",
            detail: format!("sections end at {expected_offset}, footer at {footer_offset}"),
        });
    }

    // Verify per-section digests.
    for entry in &sections {
        let start = entry.offset as usize;
        let end = start + entry.length as usize;
        if sha256(&bytes[start..end]) != entry.digest {
            return Err(SegmentError::DigestMismatch { context: "section" });
        }
    }

    Ok(ContainerView {
        kind,
        doc_count,
        bytes,
        sections,
        required,
        optional,
    })
}

fn read_features(
    reader: &mut ByteReader<'_>,
    context: &'static str,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<(u16, u16)>> {
    let count = reader.u32(context)?;
    if count as usize > limits.max_features() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_features() as u64,
            requested: u64::from(count),
        });
    }
    limits.check_alloc::<(u16, u16)>(u64::from(count))?;
    let mut features = Vec::with_capacity(count as usize);
    for _ in 0..count {
        let id = reader.u16(context)?;
        let version = reader.u16(context)?;
        features.push((id, version));
    }
    Ok(features)
}
