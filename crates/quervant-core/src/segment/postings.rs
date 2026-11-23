//! Positional postings: encoding, lazy bounded reader, `next`/`advance` (F05).
//!
//! Layout per posting block (interleaved per document):
//! `occurrence_kind:u8`, `posting_doc_count:u64`, `freq_total:u64`, then for
//! each document: doc-id delta varint (first absolute), frequency varint, and
//! `freq` occurrence records when positional.

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use crate::analysis::{Cancellation, NeverCancel};

/// Postings carry doc ids and frequencies only.
pub const OCCURRENCE_DOC_ONLY: u8 = 0;
/// Postings carry positional records.
pub const OCCURRENCE_POSITIONAL: u8 = 1;

/// Split payload version (PERF-06-A3). Exactly one version exists.
const SPLIT_PAYLOAD_VERSION: u8 = 1;
/// Split doc-only occurrence marker.
const SPLIT_OCCURRENCE_DOC_ONLY: u8 = 2;
/// Split positional occurrence marker.
const SPLIT_OCCURRENCE_POSITIONAL: u8 = 3;
/// Fixed documents per split-postings block directory entry.
const SPLIT_BLOCK_DOCS: u32 = 128;
/// Fixed documents per block as a `u64` for ordinal arithmetic.
const SPLIT_BLOCK_DOCS_U64: u64 = SPLIT_BLOCK_DOCS as u64;
/// Exact byte length of the split per-term header.
const SPLIT_HEADER_BYTES: usize = 56;
/// Exact byte length of one split block-directory entry.
const SPLIT_DIRECTORY_ENTRY_BYTES: usize = 40;
/// Bounded error context for every split-postings structural failure.
const SPLIT_CONTEXT: &str = "split postings";

/// A typed split-postings corruption with a fixed, bounded detail string.
fn split_corrupt(detail: &'static str) -> SegmentError {
    SegmentError::Corrupt {
        context: SPLIT_CONTEXT,
        detail: detail.to_owned(),
    }
}

/// One token occurrence within a document.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Occurrence {
    /// Absolute position within the field.
    pub position: u64,
    /// Number of positions spanned (>= 1).
    pub position_length: u64,
    /// Index of the source field value.
    pub value_index: u64,
    /// Original-source start byte offset within the value.
    pub start_offset: u64,
    /// Original-source end byte offset within the value (exclusive).
    pub end_offset: u64,
}

/// One document's postings for a term.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Posting {
    /// Physical doc id.
    pub doc_id: u64,
    /// Term frequency in the document.
    pub freq: u64,
    /// Positional occurrences (empty for doc-only postings).
    pub occurrences: Vec<Occurrence>,
}

/// An already validated physical posting's identity and frequency.
///
/// Produced by [`DocFreqPostingsReader`], which validates every positional field
/// of the posting but never materializes the occurrence vector.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DocFreqPosting {
    /// Physical doc id.
    pub doc_id: u64,
    /// Term frequency in the document.
    pub freq: u64,
}

/// Owns one existing postings cursor in validated doc/freq-only mode.
///
/// Created by [`PostingsReader::into_doc_freq`]; the original cursor is consumed
/// so a single hande can never mix full and lean decoding.
#[derive(Debug)]
pub struct DocFreqPostingsReader<'a> {
    inner: PostingsReader<'a>,
}

/// Validated source shape shared by both encoders.
struct PostingsSource {
    positional: bool,
    posting_doc_count: u64,
    freq_total: u64,
}

/// The single source-data validator used by the legacy and split encoders.
///
/// Validation order is the historical per-posting order, so legacy error values
/// are preserved exactly. Invalid source data is never sorted or repaired.
fn validate_source_postings(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<PostingsSource> {
    let positional = postings
        .iter()
        .any(|posting| !posting.occurrences.is_empty());
    let posting_doc_count = postings.len() as u64;
    if posting_doc_count > limits.max_postings_per_term() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_postings_per_term(),
            requested: posting_doc_count,
        });
    }
    if posting_doc_count == 0 {
        return Err(SegmentError::Corrupt {
            context: "postings",
            detail: "empty term postings".to_owned(),
        });
    }
    if posting_doc_count > segment_doc_count {
        return Err(SegmentError::Corrupt {
            context: "postings",
            detail: "posting count exceeds segment doc count".to_owned(),
        });
    }
    let freq_total: u64 = postings
        .iter()
        .try_fold(0u64, |acc, posting| acc.checked_add(posting.freq))
        .ok_or(SegmentError::Corrupt {
            context: "postings",
            detail: "frequency total overflow".to_owned(),
        })?;

    let mut previous_doc: Option<u64> = None;
    for posting in postings {
        if posting.doc_id >= segment_doc_count {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "doc id out of range".to_owned(),
            });
        }
        if posting.freq == 0 {
            return Err(SegmentError::ZeroFrequency {
                doc_id: posting.doc_id,
            });
        }
        if let Some(previous) = previous_doc {
            if posting.doc_id <= previous {
                return Err(SegmentError::NonMonotoneDocId {
                    previous,
                    next: posting.doc_id,
                });
            }
        }
        if positional {
            if posting.freq != posting.occurrences.len() as u64 {
                return Err(SegmentError::Corrupt {
                    context: "postings",
                    detail: "frequency does not match occurrence count".to_owned(),
                });
            }
            let mut previous_position: Option<u64> = None;
            let mut previous_value_index = 0u64;
            for occurrence in &posting.occurrences {
                if occurrence.position_length == 0 {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "zero position length".to_owned(),
                    });
                }
                if occurrence.start_offset > occurrence.end_offset {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "start offset exceeds end offset".to_owned(),
                    });
                }
                if occurrence.value_index < previous_value_index {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "value index decreased".to_owned(),
                    });
                }
                previous_value_index = occurrence.value_index;
                if let Some(previous) = previous_position {
                    if occurrence.position <= previous {
                        return Err(SegmentError::NonMonotonePosition {
                            doc_id: posting.doc_id,
                        });
                    }
                }
                previous_position = Some(occurrence.position);
            }
        }
        previous_doc = Some(posting.doc_id);
    }

    Ok(PostingsSource {
        positional,
        posting_doc_count,
        freq_total,
    })
}

/// Encode one term's posting block.
///
/// `segment_doc_count` is the container's document count, used to reject
/// out-of-range doc ids. It is distinct from `posting_doc_count`, the number of
/// documents containing this term.
pub fn encode_postings_block(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let source = validate_source_postings(segment_doc_count, postings, limits)?;
    let positional = source.positional;
    let posting_doc_count = source.posting_doc_count;
    let freq_total = source.freq_total;

    let mut writer = ByteWriter::new();
    writer.u8(if positional {
        OCCURRENCE_POSITIONAL
    } else {
        OCCURRENCE_DOC_ONLY
    });
    writer.u64(posting_doc_count);
    writer.u64(freq_total);

    let mut previous_doc: Option<u64> = None;
    for posting in postings {
        let delta = match previous_doc {
            None => posting.doc_id,
            Some(previous) => posting.doc_id - previous,
        };
        writer.varint(delta);
        writer.varint(posting.freq);
        if positional {
            let mut previous_position: Option<u64> = None;
            for occurrence in &posting.occurrences {
                let position_delta = match previous_position {
                    None => occurrence.position,
                    Some(previous) => occurrence.position - previous,
                };
                writer.varint(position_delta);
                writer.varint(occurrence.position_length);
                writer.varint(occurrence.value_index);
                writer.varint(occurrence.start_offset);
                writer.varint(occurrence.end_offset);
                previous_position = Some(occurrence.position);
            }
        }
        previous_doc = Some(posting.doc_id);
    }
    Ok(writer.into_vec())
}

/// Encode one term's versioned split postings payload (PERF-06-A3 v1).
///
/// Layout: a fixed 56-byte header, the document-id stream, the frequency
/// stream, the positional stream and finally one 40-byte directory entry per
/// 128 documents. The document stream encodes an absolute id at each block
/// start and a strictly positive delta otherwise. Positional history resets at
/// every posting, never at a block boundary.
pub fn encode_split_postings_block(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let source = validate_source_postings(segment_doc_count, postings, limits)?;
    let block_count_value = source.posting_doc_count.div_ceil(SPLIT_BLOCK_DOCS_U64);
    let block_count =
        u32::try_from(block_count_value).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: block_count_value,
        })?;

    let mut doc_stream = ByteWriter::new();
    let mut freq_stream = ByteWriter::new();
    let mut pos_stream = ByteWriter::new();
    let mut directory = ByteWriter::new();

    for (index, posting) in postings.iter().enumerate() {
        let ordinal = index as u64;
        if ordinal % SPLIT_BLOCK_DOCS_U64 == 0 {
            directory.u64(posting.doc_id);
            directory.u64(ordinal);
            directory.u64(doc_stream.len() as u64);
            directory.u64(freq_stream.len() as u64);
            directory.u64(pos_stream.len() as u64);
            doc_stream.varint(posting.doc_id);
        } else {
            // Strictly positive: source validation proved a strict increase.
            doc_stream.varint(posting.doc_id - postings[index - 1].doc_id);
        }
        freq_stream.varint(posting.freq);
        if source.positional {
            let mut previous_position: Option<u64> = None;
            for occurrence in &posting.occurrences {
                let position_delta = match previous_position {
                    None => occurrence.position,
                    Some(previous) => occurrence.position - previous,
                };
                pos_stream.varint(position_delta);
                pos_stream.varint(occurrence.position_length);
                pos_stream.varint(occurrence.value_index);
                pos_stream.varint(occurrence.start_offset);
                pos_stream.varint(occurrence.end_offset);
                previous_position = Some(occurrence.position);
            }
        }
    }

    let doc_len = doc_stream.len() as u64;
    let freq_len = freq_stream.len() as u64;
    let pos_len = pos_stream.len() as u64;
    let directory_len = u64::from(block_count)
        .checked_mul(SPLIT_DIRECTORY_ENTRY_BYTES as u64)
        .ok_or_else(|| split_corrupt("length overflow"))?;
    let mut total = SPLIT_HEADER_BYTES as u64;
    for part in [doc_len, freq_len, pos_len, directory_len] {
        total = total
            .checked_add(part)
            .ok_or_else(|| split_corrupt("length overflow"))?;
    }
    if total > limits.max_single_allocation() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: total,
        });
    }
    let total = usize::try_from(total).map_err(|_| SegmentError::LimitExceeded {
        limit: limits.max_single_allocation(),
        requested: total,
    })?;

    let mut header = ByteWriter::new();
    header.u8(if source.positional {
        SPLIT_OCCURRENCE_POSITIONAL
    } else {
        SPLIT_OCCURRENCE_DOC_ONLY
    });
    header.u8(SPLIT_PAYLOAD_VERSION);
    header.u16(0);
    header.u32(SPLIT_BLOCK_DOCS);
    header.u32(block_count);
    header.u32(0);
    header.u64(source.posting_doc_count);
    header.u64(source.freq_total);
    header.u64(doc_len);
    header.u64(freq_len);
    header.u64(pos_len);
    debug_assert_eq!(header.len(), SPLIT_HEADER_BYTES);

    let mut out: Vec<u8> = Vec::new();
    out.try_reserve_exact(total)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: total as u64,
        })?;
    out.extend_from_slice(header.as_slice());
    out.extend_from_slice(doc_stream.as_slice());
    out.extend_from_slice(freq_stream.as_slice());
    out.extend_from_slice(pos_stream.as_slice());
    out.extend_from_slice(directory.as_slice());
    debug_assert_eq!(out.len(), total);
    Ok(out)
}

/// Where the shared decoder currently reads posting fields from.
///
/// Rust does not permit enum items inside an `impl` block, so this private
/// module-level item sits beside [`PostingsReader`].
enum PostingStreams<'a> {
    Legacy(ByteReader<'a>),
    Split(SplitStreams<'a>),
}

impl std::fmt::Debug for PostingStreams<'_> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Legacy(_) => formatter.write_str("PostingStreams::Legacy"),
            Self::Split(_) => formatter.write_str("PostingStreams::Split"),
        }
    }
}

/// Borrowed split-postings streams plus the validated block directory.
struct SplitStreams<'a> {
    docs: ByteReader<'a>,
    freqs: ByteReader<'a>,
    positions: ByteReader<'a>,
    block_directory: &'a [u8],
    block_count: u32,
    observed_freq_total: u64,
}

impl std::fmt::Debug for SplitStreams<'_> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("SplitStreams")
            .field("block_count", &self.block_count)
            .field("observed_freq_total", &self.observed_freq_total)
            .finish_non_exhaustive()
    }
}

/// One 40-byte block-directory entry, parsed on demand (never retained).
#[derive(Debug, Clone, Copy)]
struct SplitBlockEntry {
    first_doc_id: u64,
    first_posting_ordinal: u64,
    doc_byte_offset: u64,
    freq_byte_offset: u64,
    pos_byte_offset: u64,
}

impl SplitStreams<'_> {
    /// Parse one directory entry from the borrowed directory bytes.
    fn block_entry(&self, index: u32) -> SegmentResult<SplitBlockEntry> {
        if index >= self.block_count {
            return Err(split_corrupt("block directory index out of range"));
        }
        let base = (index as usize)
            .checked_mul(SPLIT_DIRECTORY_ENTRY_BYTES)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        let end = base
            .checked_add(SPLIT_DIRECTORY_ENTRY_BYTES)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        let slice = self
            .block_directory
            .get(base..end)
            .ok_or_else(|| split_corrupt("block directory truncated"))?;
        let mut reader = ByteReader::new(slice);
        Ok(SplitBlockEntry {
            first_doc_id: reader.u64("block first doc id")?,
            first_posting_ordinal: reader.u64("block posting ordinal")?,
            doc_byte_offset: reader.u64("block doc offset")?,
            freq_byte_offset: reader.u64("block frequency offset")?,
            pos_byte_offset: reader.u64("block position offset")?,
        })
    }
}

/// A lazy, bounded postings reader.
#[derive(Debug)]
pub struct PostingsReader<'a> {
    streams: PostingStreams<'a>,
    positional: bool,
    posting_doc_count: u64,
    freq_total: u64,
    docs_read: u64,
    previous_doc: Option<u64>,
    segment_doc_count: u64,
    limits: SegmentLimits,
    current: Option<Posting>,
    finished: bool,
}

/// Whether the shared decoder materializes positional occurrences.
///
/// The plan places this beside the decoder; Rust does not permit `enum` items
/// inside an `impl` block, so it is a private item of this module.
#[derive(Clone, Copy, PartialEq, Eq)]
enum DecodeDetail {
    Full,
    DocFreq,
}

impl<'a> PostingsReader<'a> {
    /// Parse the block header.
    pub fn new(
        bytes: &'a [u8],
        segment_doc_count: u64,
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let occurrence_kind = reader.u8("occurrence kind")?;
        let positional = match occurrence_kind {
            OCCURRENCE_DOC_ONLY => false,
            OCCURRENCE_POSITIONAL => true,
            value => {
                return Err(SegmentError::Corrupt {
                    context: "occurrence kind",
                    detail: format!("invalid {value}"),
                });
            }
        };
        let posting_doc_count = reader.u64("posting doc count")?;
        if posting_doc_count == 0 {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "zero posting count".to_owned(),
            });
        }
        if posting_doc_count > limits.max_postings_per_term() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.max_postings_per_term(),
                requested: posting_doc_count,
            });
        }
        if posting_doc_count > segment_doc_count {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "posting count exceeds segment doc count".to_owned(),
            });
        }
        let freq_total = reader.u64("freq total")?;
        Ok(Self {
            streams: PostingStreams::Legacy(reader),
            positional,
            posting_doc_count,
            freq_total,
            docs_read: 0,
            previous_doc: None,
            segment_doc_count,
            limits: *limits,
            current: None,
            finished: false,
        })
    }

    /// Parse and validate a versioned split postings payload (PERF-06-A3 v1).
    ///
    /// Every structural field, stream extent and block-directory entry is
    /// validated here using borrowed slices; no allocation is proportional to a
    /// declared (untrusted) block count. Legacy occurrence markers are rejected:
    /// the payload version is selected by the segment's required features, never
    /// by sniffing bytes.
    pub(crate) fn new_split(
        bytes: &'a [u8],
        segment_doc_count: u64,
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let marker = reader.u8("occurrence marker")?;
        let positional = match marker {
            SPLIT_OCCURRENCE_DOC_ONLY => false,
            SPLIT_OCCURRENCE_POSITIONAL => true,
            _ => return Err(split_corrupt("invalid occurrence marker")),
        };
        let payload_version = reader.u8("payload version")?;
        if payload_version != SPLIT_PAYLOAD_VERSION {
            return Err(split_corrupt("unsupported payload version"));
        }
        let flags = reader.u16("flags")?;
        if flags != 0 {
            return Err(SegmentError::UnknownFlags {
                context: SPLIT_CONTEXT,
                flags: u64::from(flags),
            });
        }
        let block_docs = reader.u32("block docs")?;
        if block_docs != SPLIT_BLOCK_DOCS {
            return Err(split_corrupt("invalid block_docs"));
        }
        let block_count = reader.u32("block count")?;
        let reserved = reader.u32("reserved")?;
        if reserved != 0 {
            return Err(split_corrupt("reserved field nonzero"));
        }
        let posting_doc_count = reader.u64("posting doc count")?;
        if posting_doc_count == 0 {
            return Err(split_corrupt("zero posting count"));
        }
        if posting_doc_count > limits.max_postings_per_term() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.max_postings_per_term(),
                requested: posting_doc_count,
            });
        }
        if posting_doc_count > segment_doc_count {
            return Err(split_corrupt("posting count exceeds segment doc count"));
        }
        let expected_blocks = posting_doc_count.div_ceil(SPLIT_BLOCK_DOCS_U64);
        if u64::from(block_count) != expected_blocks {
            return Err(split_corrupt("block count mismatch"));
        }
        let freq_total = reader.u64("freq total")?;
        if freq_total < posting_doc_count {
            return Err(split_corrupt("frequency total below posting count"));
        }
        let doc_stream_len = reader.u64("doc stream length")?;
        let freq_stream_len = reader.u64("frequency stream length")?;
        let pos_stream_len = reader.u64("position stream length")?;
        if positional {
            // Five one-byte-minimum fields per occurrence.
            let minimum_positions = freq_total
                .checked_mul(5)
                .ok_or_else(|| split_corrupt("length overflow"))?;
            if pos_stream_len < minimum_positions {
                return Err(split_corrupt("position stream too short"));
            }
        } else if pos_stream_len != 0 {
            return Err(split_corrupt(
                "position stream present for doc-only payload",
            ));
        }
        if doc_stream_len < posting_doc_count {
            return Err(split_corrupt("doc stream too short"));
        }
        if freq_stream_len < posting_doc_count {
            return Err(split_corrupt("frequency stream too short"));
        }
        let directory_len = u64::from(block_count)
            .checked_mul(SPLIT_DIRECTORY_ENTRY_BYTES as u64)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        let mut declared_total = SPLIT_HEADER_BYTES as u64;
        for part in [
            doc_stream_len,
            freq_stream_len,
            pos_stream_len,
            directory_len,
        ] {
            declared_total = declared_total
                .checked_add(part)
                .ok_or_else(|| split_corrupt("length overflow"))?;
        }
        if declared_total != bytes.len() as u64 {
            return Err(split_corrupt("extent length mismatch"));
        }
        let doc_len =
            usize::try_from(doc_stream_len).map_err(|_| split_corrupt("length overflow"))?;
        let freq_len =
            usize::try_from(freq_stream_len).map_err(|_| split_corrupt("length overflow"))?;
        let pos_len =
            usize::try_from(pos_stream_len).map_err(|_| split_corrupt("length overflow"))?;
        let dir_len =
            usize::try_from(directory_len).map_err(|_| split_corrupt("length overflow"))?;
        let doc_start = SPLIT_HEADER_BYTES;
        let doc_end = doc_start
            .checked_add(doc_len)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        let freq_start = doc_end;
        let freq_end = freq_start
            .checked_add(freq_len)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        let pos_start = freq_end;
        let pos_end = pos_start
            .checked_add(pos_len)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        let dir_start = pos_end;
        let dir_end = dir_start
            .checked_add(dir_len)
            .ok_or_else(|| split_corrupt("length overflow"))?;
        if dir_end != bytes.len() {
            return Err(split_corrupt("extent length mismatch"));
        }

        let streams = SplitStreams {
            docs: ByteReader::new(&bytes[doc_start..doc_end]),
            freqs: ByteReader::new(&bytes[freq_start..freq_end]),
            positions: ByteReader::new(&bytes[pos_start..pos_end]),
            block_directory: &bytes[dir_start..dir_end],
            block_count,
            observed_freq_total: 0,
        };
        Self::validate_split_directory(
            &streams,
            positional,
            segment_doc_count,
            doc_stream_len,
            freq_stream_len,
            pos_stream_len,
        )?;
        Ok(Self {
            streams: PostingStreams::Split(streams),
            positional,
            posting_doc_count,
            freq_total,
            docs_read: 0,
            previous_doc: None,
            segment_doc_count,
            limits: *limits,
            current: None,
            finished: false,
        })
    }

    /// Validate every block-directory entry using borrowed bytes only.
    fn validate_split_directory(
        streams: &SplitStreams<'a>,
        positional: bool,
        segment_doc_count: u64,
        doc_stream_len: u64,
        freq_stream_len: u64,
        pos_stream_len: u64,
    ) -> SegmentResult<()> {
        let mut previous: Option<SplitBlockEntry> = None;
        for index in 0..streams.block_count {
            let entry = streams.block_entry(index)?;
            let expected_ordinal = u64::from(index)
                .checked_mul(SPLIT_BLOCK_DOCS_U64)
                .ok_or_else(|| split_corrupt("length overflow"))?;
            if entry.first_posting_ordinal != expected_ordinal {
                return Err(split_corrupt("block ordinal mismatch"));
            }
            if entry.first_doc_id >= segment_doc_count {
                return Err(split_corrupt("block first doc id out of range"));
            }
            match previous {
                None => {
                    if entry.doc_byte_offset != 0 {
                        return Err(split_corrupt("block doc offset not canonical"));
                    }
                    if entry.freq_byte_offset != 0 {
                        return Err(split_corrupt("block frequency offset not canonical"));
                    }
                    if entry.pos_byte_offset != 0 {
                        return Err(split_corrupt("block position offset not canonical"));
                    }
                }
                Some(previous) => {
                    if entry.first_doc_id <= previous.first_doc_id {
                        return Err(split_corrupt("block first doc id not ascending"));
                    }
                    if entry.doc_byte_offset <= previous.doc_byte_offset {
                        return Err(split_corrupt("block doc offset not ascending"));
                    }
                    if entry.doc_byte_offset >= doc_stream_len {
                        return Err(split_corrupt("block doc offset out of range"));
                    }
                    if entry.freq_byte_offset <= previous.freq_byte_offset {
                        return Err(split_corrupt("block frequency offset not ascending"));
                    }
                    if entry.freq_byte_offset >= freq_stream_len {
                        return Err(split_corrupt("block frequency offset out of range"));
                    }
                    if positional {
                        if entry.pos_byte_offset <= previous.pos_byte_offset {
                            return Err(split_corrupt("block position offset not ascending"));
                        }
                        if entry.pos_byte_offset >= pos_stream_len {
                            return Err(split_corrupt("block position offset out of range"));
                        }
                    } else if entry.pos_byte_offset != 0 {
                        return Err(split_corrupt("block position offset not canonical"));
                    }
                }
            }
            previous = Some(entry);
        }
        Ok(())
    }

    /// Number of documents containing the term.
    #[must_use]
    pub const fn posting_doc_count(&self) -> u64 {
        self.posting_doc_count
    }

    /// Whether this posting block carries positional occurrences.
    #[must_use]
    pub const fn is_positional(&self) -> bool {
        self.positional
    }

    /// Sum of term frequencies.
    #[must_use]
    pub const fn freq_total(&self) -> u64 {
        self.freq_total
    }

    /// Consume this cursor and continue from its NEXT unread posting.
    ///
    /// Conversion may occur at the beginning or after a previous full read; the
    /// last full cached posting is NOT re-emitted.
    pub fn into_doc_freq(mut self) -> DocFreqPostingsReader<'a> {
        self.current = None; // drop any cached positional clone
        DocFreqPostingsReader { inner: self }
    }

    /// Return the next posting in ascending doc-id order.
    ///
    /// This is a domain-specific postings cursor, not an iterator adapter.
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> SegmentResult<Option<Posting>> {
        self.next_with(&NeverCancel)
    }

    /// Return the next posting, polling `cancel` at each posting boundary.
    pub fn next_with(&mut self, cancel: &dyn Cancellation) -> SegmentResult<Option<Posting>> {
        let Some((head, occurrences)) = self.read_one_with(cancel, DecodeDetail::Full)? else {
            return Ok(None);
        };
        let posting = Posting {
            doc_id: head.doc_id,
            freq: head.freq,
            occurrences,
        };
        #[cfg(test)]
        decode_observation::record_cached_posting_clone();
        self.current = Some(posting.clone());
        Ok(Some(posting))
    }

    /// The single validated decoder shared by the full and doc/freq-only readers.
    ///
    /// `detail` only selects whether positional occurrences are materialized into a
    /// vector; every positional field is parsed and validated in both modes, so a
    /// malformed posting is rejected identically either way.
    fn read_one_with(
        &mut self,
        cancel: &dyn Cancellation,
        detail: DecodeDetail,
    ) -> SegmentResult<Option<(DocFreqPosting, Vec<Occurrence>)>> {
        cancel_result(cancel)?;
        if self.finished {
            return Ok(None);
        }
        if self.docs_read == self.posting_doc_count {
            self.finish()?;
            return Ok(None);
        }
        self.limits.check_entries(self.docs_read + 1)?;
        let doc_id = self.read_doc_id()?;
        if doc_id >= self.segment_doc_count {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "doc id out of range".to_owned(),
            });
        }
        let freq = self.read_frequency()?;
        if freq == 0 {
            return Err(SegmentError::ZeroFrequency { doc_id });
        }
        if freq > self.limits.max_decoded_entries() {
            return Err(SegmentError::LimitExceeded {
                limit: self.limits.max_decoded_entries(),
                requested: freq,
            });
        }
        let mut occurrences = Vec::new();
        if self.positional {
            // Preserved historical preflight: the positional occurrence payload is
            // bounded by `freq * size_of::<Occurrence>()` even in doc/freq mode,
            // where the vector itself is never allocated.
            self.limits.check_alloc::<Occurrence>(freq)?;
            if detail == DecodeDetail::Full {
                #[cfg(test)]
                decode_observation::record_positional_vector_reserve();
                occurrences.reserve(freq as usize);
            }
            let mut previous_position: Option<u64> = None;
            let mut previous_value_index = 0u64;
            for _ in 0..freq {
                let position_delta = self.position_varint("position delta")?;
                let position = match previous_position {
                    None => position_delta,
                    Some(previous) => {
                        if position_delta == 0 {
                            return Err(SegmentError::NonMonotonePosition { doc_id });
                        }
                        previous
                            .checked_add(position_delta)
                            .ok_or(SegmentError::Corrupt {
                                context: "postings",
                                detail: "position overflow".to_owned(),
                            })?
                    }
                };
                let position_length = self.position_varint("position length")?;
                if position_length == 0 {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "zero position length".to_owned(),
                    });
                }
                let value_index = self.position_varint("value index")?;
                if value_index < previous_value_index {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "value index decreased".to_owned(),
                    });
                }
                previous_value_index = value_index;
                let start_offset = self.position_varint("start offset")?;
                let end_offset = self.position_varint("end offset")?;
                if start_offset > end_offset {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "start offset exceeds end offset".to_owned(),
                    });
                }
                if detail == DecodeDetail::Full {
                    occurrences.push(Occurrence {
                        position,
                        position_length,
                        value_index,
                        start_offset,
                        end_offset,
                    });
                }
                previous_position = Some(position);
            }
        }
        self.docs_read += 1;
        self.previous_doc = Some(doc_id);
        if let PostingStreams::Split(split) = &mut self.streams {
            split.observed_freq_total = split
                .observed_freq_total
                .checked_add(freq)
                .ok_or_else(|| split_corrupt("frequency total overflow"))?;
        }
        Ok(Some((DocFreqPosting { doc_id, freq }, occurrences)))
    }

    /// Read the next document id from the active payload.
    ///
    /// Legacy payloads encode an absolute first id and deltas afterwards. Split
    /// payloads encode an absolute id at every 128-posting block start and a
    /// strictly positive delta otherwise; the block boundary is also verified
    /// against the validated directory entry before the posting is returned.
    fn read_doc_id(&mut self) -> SegmentResult<u64> {
        match &mut self.streams {
            PostingStreams::Legacy(reader) => {
                let delta = reader.varint("doc id delta")?;
                match self.previous_doc {
                    None => Ok(delta),
                    Some(previous) => {
                        if delta == 0 {
                            return Err(SegmentError::NonMonotoneDocId {
                                previous,
                                next: previous,
                            });
                        }
                        previous.checked_add(delta).ok_or(SegmentError::Corrupt {
                            context: "postings",
                            detail: "doc id overflow".to_owned(),
                        })
                    }
                }
            }
            PostingStreams::Split(split) => {
                let at_block_start = self.docs_read % SPLIT_BLOCK_DOCS_U64 == 0;
                if at_block_start {
                    let block_index = u32::try_from(self.docs_read / SPLIT_BLOCK_DOCS_U64)
                        .map_err(|_| split_corrupt("block index overflow"))?;
                    let entry = split.block_entry(block_index)?;
                    let docs_position = u64::try_from(split.docs.position())
                        .map_err(|_| split_corrupt("length overflow"))?;
                    if docs_position != entry.doc_byte_offset {
                        return Err(split_corrupt("block doc offset mismatch"));
                    }
                    let freqs_position = u64::try_from(split.freqs.position())
                        .map_err(|_| split_corrupt("length overflow"))?;
                    if freqs_position != entry.freq_byte_offset {
                        return Err(split_corrupt("block frequency offset mismatch"));
                    }
                    let positions_position = u64::try_from(split.positions.position())
                        .map_err(|_| split_corrupt("length overflow"))?;
                    if positions_position != entry.pos_byte_offset {
                        return Err(split_corrupt("block position offset mismatch"));
                    }
                    let absolute = split.docs.varint("doc id delta")?;
                    if absolute != entry.first_doc_id {
                        return Err(split_corrupt("block first doc id mismatch"));
                    }
                    if let Some(previous) = self.previous_doc {
                        if absolute <= previous {
                            return Err(SegmentError::NonMonotoneDocId {
                                previous,
                                next: absolute,
                            });
                        }
                    }
                    Ok(absolute)
                } else {
                    let delta = split.docs.varint("doc id delta")?;
                    let previous = self
                        .previous_doc
                        .ok_or_else(|| split_corrupt("doc id delta without base"))?;
                    if delta == 0 {
                        return Err(SegmentError::NonMonotoneDocId {
                            previous,
                            next: previous,
                        });
                    }
                    previous.checked_add(delta).ok_or(SegmentError::Corrupt {
                        context: "postings",
                        detail: "doc id overflow".to_owned(),
                    })
                }
            }
        }
    }

    /// Read the next term frequency from the active payload.
    fn read_frequency(&mut self) -> SegmentResult<u64> {
        match &mut self.streams {
            PostingStreams::Legacy(reader) => reader.varint("frequency"),
            PostingStreams::Split(split) => split.freqs.varint("frequency"),
        }
    }

    /// Read one positional component from the active payload.
    fn position_varint(&mut self, context: &'static str) -> SegmentResult<u64> {
        match &mut self.streams {
            PostingStreams::Legacy(reader) => reader.varint(context),
            PostingStreams::Split(split) => split.positions.varint(context),
        }
    }

    /// Validate the end of the payload, then publish `finished`.
    fn finish(&mut self) -> SegmentResult<()> {
        match &mut self.streams {
            PostingStreams::Legacy(reader) => reader.expect_end("postings")?,
            PostingStreams::Split(split) => {
                if !split.docs.is_empty() {
                    return Err(split_corrupt("doc stream trailing bytes"));
                }
                if !split.freqs.is_empty() {
                    return Err(split_corrupt("frequency stream trailing bytes"));
                }
                if !split.positions.is_empty() {
                    return Err(split_corrupt("position stream trailing bytes"));
                }
                if split.observed_freq_total != self.freq_total {
                    return Err(split_corrupt("frequency total mismatch"));
                }
            }
        }
        self.finished = true;
        self.current = None;
        Ok(())
    }

    /// Advance to the first posting with `doc_id >= target`.
    ///
    /// Without a skip index this scans sequentially and is not guaranteed
    /// sublinear. It never moves backward; `target <=` the current doc id
    /// returns the current posting.
    pub fn advance(&mut self, target: u64) -> SegmentResult<Option<Posting>> {
        self.advance_with(target, &NeverCancel)
    }

    /// Advance with cooperative cancellation polling at each posting boundary.
    pub fn advance_with(
        &mut self,
        target: u64,
        cancel: &dyn Cancellation,
    ) -> SegmentResult<Option<Posting>> {
        if let Some(current) = &self.current {
            if target <= current.doc_id {
                return Ok(Some(current.clone()));
            }
        }
        loop {
            match self.next_with(cancel)? {
                Some(posting) if posting.doc_id >= target => return Ok(Some(posting)),
                Some(_) => continue,
                None => return Ok(None),
            }
        }
    }
}

fn cancel_result(cancel: &dyn Cancellation) -> SegmentResult<()> {
    if cancel.is_cancelled() {
        Err(SegmentError::Cancelled)
    } else {
        Ok(())
    }
}

impl DocFreqPostingsReader<'_> {
    /// Return the next `(doc_id, freq)` pair, discarding positional occurrences.
    ///
    /// All positional bytes are still parsed and validated before the record is
    /// returned.
    #[allow(clippy::should_implement_trait)]
    pub fn next(&mut self) -> SegmentResult<Option<DocFreqPosting>> {
        self.next_with(&NeverCancel)
    }

    /// Return the next `(doc_id, freq)` pair, polling `cancel` at each posting
    /// boundary.
    pub fn next_with(
        &mut self,
        cancel: &dyn Cancellation,
    ) -> SegmentResult<Option<DocFreqPosting>> {
        let result = self.inner.read_one_with(cancel, DecodeDetail::DocFreq)?;
        Ok(result.map(|(head, occurrences)| {
            debug_assert!(occurrences.is_empty());
            head
        }))
    }
}

/// Test-only witnesses counting the two full-mode occurrence-materialization
/// sites (positional vector reserve, cached full-posting clone).
///
/// These exist so unit tests can prove the doc/freq view performs neither. There
/// is no production counter, metric, tracing hook or allocator instrumentation.
#[cfg(test)]
pub(crate) mod decode_observation {
    use std::cell::Cell;

    thread_local! {
        static POSITIONAL_VECTOR_RESERVES: Cell<u64> = const { Cell::new(0) };
        static CACHED_POSTING_CLONES: Cell<u64> = const { Cell::new(0) };
    }

    /// Reset both witnesses to zero for the current thread.
    pub(crate) fn reset() {
        POSITIONAL_VECTOR_RESERVES.with(|cell| cell.set(0));
        CACHED_POSTING_CLONES.with(|cell| cell.set(0));
    }

    /// `(positional_vector_reserves, cached_posting_clones)` for this thread.
    pub(crate) fn counts() -> (u64, u64) {
        (
            POSITIONAL_VECTOR_RESERVES.with(Cell::get),
            CACHED_POSTING_CLONES.with(Cell::get),
        )
    }

    pub(super) fn record_positional_vector_reserve() {
        POSITIONAL_VECTOR_RESERVES.with(|cell| cell.set(cell.get() + 1));
    }

    pub(super) fn record_cached_posting_clone() {
        CACHED_POSTING_CLONES.with(|cell| cell.set(cell.get() + 1));
    }
}
