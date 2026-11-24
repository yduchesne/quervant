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

/// Adaptive compact payload version (PERF-06-A5). Exactly one version exists.
const ADAPTIVE_PAYLOAD_VERSION: u8 = 1;
/// Compact singleton doc-only marker.
const COMPACT_SINGLETON_DOC_ONLY: u8 = 4;
/// Compact singleton positional marker.
const COMPACT_SINGLETON_POSITIONAL: u8 = 5;
/// Compact short (2..=128 documents) doc-only marker.
const COMPACT_SHORT_DOC_ONLY: u8 = 6;
/// Compact short (2..=128 documents) positional marker.
const COMPACT_SHORT_POSITIONAL: u8 = 7;
/// Largest posting count encoded by the compact representation.
const ADAPTIVE_COMPACT_MAX_DOCS: u64 = 128;
/// Fixed payload version selector width plus the version byte itself.
const ADAPTIVE_MARKER_VERSION_BYTES: u64 = 2;
/// Bounded error context for every adaptive-postings structural failure.
const ADAPTIVE_CONTEXT: &str = "adaptive postings";

/// A typed adaptive-postings corruption with a fixed, bounded detail string.
fn adaptive_corrupt(detail: &'static str) -> SegmentError {
    SegmentError::Corrupt {
        context: ADAPTIVE_CONTEXT,
        detail: detail.to_owned(),
    }
}

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
    /// Compact stream lengths measured during the same validation walk.
    ///
    /// `None` when the caller's const parameter disabled measurement (the legacy
    /// and split encoders never pay for compact arithmetic).
    compact_lengths: Option<CompactLengths>,
}

/// Compact document/frequency/positional stream lengths in bytes.
#[derive(Clone, Copy, Default)]
struct CompactLengths {
    docs: u64,
    freqs: u64,
    positions: u64,
}

/// Canonical LEB128 width of `value` in bytes.
///
/// The `| 1` makes zero one byte wide. This helper only *sizes* a value;
/// `ByteWriter::varint` remains the sole production emitter.
fn compact_varint_len(value: u64) -> u64 {
    #[cfg(test)]
    encode_observation::record_width_call();
    u64::from((u64::BITS - (value | 1).leading_zeros()).div_ceil(7))
}

/// Sum the compact header and measured stream lengths with checked arithmetic.
fn compact_total_len(header_len: u64, lengths: CompactLengths) -> SegmentResult<u64> {
    let mut total = header_len;
    for part in [lengths.docs, lengths.freqs, lengths.positions] {
        total = total
            .checked_add(part)
            .ok_or_else(|| adaptive_corrupt("length overflow"))?;
    }
    Ok(total)
}

/// Add a measured width, remembering (not yet reporting) arithmetic overflow.
fn accumulate_width(accumulator: &mut u64, width: u64, overflow: &mut bool) {
    match accumulator.checked_add(width) {
        Some(next) => *accumulator = next,
        None => *overflow = true,
    }
}

/// The single source-data validator used by the legacy, split and adaptive
/// encoders.
///
/// Validation order is the historical per-posting order, so legacy error values
/// are preserved exactly. Invalid source data is never sorted or repaired.
/// `MEASURE_COMPACT` fuses compact stream-length accounting into the same walk:
/// it adds no traversal, no allocation and no work to the `false` specialization.
fn validate_source_postings<const MEASURE_COMPACT: bool>(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<PostingsSource> {
    #[cfg(test)]
    encode_observation::record_validation_call();
    if MEASURE_COMPACT {
        #[cfg(test)]
        encode_observation::record_compact_validation_call();
    }
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
        .ok_or_else(|| SegmentError::Corrupt {
            context: "postings",
            detail: "frequency total overflow".to_owned(),
        })?;

    let mut measurement = CompactLengths::default();
    let mut measurement_overflow = false;
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
        if positional && posting.freq != posting.occurrences.len() as u64 {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "frequency does not match occurrence count".to_owned(),
            });
        }
        if MEASURE_COMPACT {
            let doc_width = match previous_doc {
                None => posting.doc_id,
                Some(previous) => posting.doc_id - previous,
            };
            accumulate_width(
                &mut measurement.docs,
                compact_varint_len(doc_width),
                &mut measurement_overflow,
            );
            accumulate_width(
                &mut measurement.freqs,
                compact_varint_len(posting.freq),
                &mut measurement_overflow,
            );
        }
        if positional {
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
                if MEASURE_COMPACT {
                    let position_delta = match previous_position {
                        None => occurrence.position,
                        Some(previous) => occurrence.position - previous,
                    };
                    for width in [
                        compact_varint_len(position_delta),
                        compact_varint_len(occurrence.position_length),
                        compact_varint_len(occurrence.value_index),
                        compact_varint_len(occurrence.start_offset),
                        compact_varint_len(occurrence.end_offset),
                    ] {
                        accumulate_width(
                            &mut measurement.positions,
                            width,
                            &mut measurement_overflow,
                        );
                    }
                }
                previous_position = Some(occurrence.position);
            }
        }
        previous_doc = Some(posting.doc_id);
    }

    if measurement_overflow {
        return Err(adaptive_corrupt("length overflow"));
    }
    Ok(PostingsSource {
        positional,
        posting_doc_count,
        freq_total,
        compact_lengths: if MEASURE_COMPACT {
            Some(measurement)
        } else {
            None
        },
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
    let source = validate_source_postings::<false>(segment_doc_count, postings, limits)?;
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
    let source = validate_source_postings::<false>(segment_doc_count, postings, limits)?;
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

/// Encode one term's posting block with the adaptive postings family
/// (PERF-06-A5 v1).
///
/// Lists of 1-128 documents use the compact framed representation; longer
/// lists delegate to [`encode_split_postings_block`] before any compact
/// validation, sizing or allocation, so their bytes stay identical to A3.
///
/// The compact path validates the source once while fusing stream-length
/// measurement into the same walk, then admits and reserves exactly one output
/// buffer and emits the three streams into it. No scratch stream buffers, no
/// occurrence traversal solely for sizing and no capacity growth are involved.
pub fn encode_adaptive_postings_block(
    segment_doc_count: u64,
    postings: &[Posting],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    if postings.len() as u64 > ADAPTIVE_COMPACT_MAX_DOCS {
        return encode_split_postings_block(segment_doc_count, postings, limits);
    }
    let source = validate_source_postings::<true>(segment_doc_count, postings, limits)?;
    let Some(lengths) = source.compact_lengths else {
        // Only reachable if the enabled validator failed to measure.
        return Err(adaptive_corrupt("length overflow"));
    };
    let positional = source.positional;
    let short = source.posting_doc_count != 1;

    let mut header_len = ADAPTIVE_MARKER_VERSION_BYTES;
    if short {
        header_len += compact_varint_len(source.posting_doc_count);
    }
    header_len += compact_varint_len(source.freq_total);
    header_len += compact_varint_len(lengths.docs);
    header_len += compact_varint_len(lengths.freqs);
    header_len += compact_varint_len(lengths.positions);
    let total = compact_total_len(header_len, lengths)?;
    if total > limits.max_single_allocation() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: total,
        });
    }
    let total_bytes = usize::try_from(total).map_err(|_| SegmentError::LimitExceeded {
        limit: limits.max_single_allocation(),
        requested: total,
    })?;
    let mut writer =
        ByteWriter::try_with_capacity(total_bytes).map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: total,
        })?;
    #[cfg(test)]
    encode_observation::record_compact_output_buffer(writer.capacity_for_test());

    writer.u8(match (short, positional) {
        (false, false) => COMPACT_SINGLETON_DOC_ONLY,
        (false, true) => COMPACT_SINGLETON_POSITIONAL,
        (true, false) => COMPACT_SHORT_DOC_ONLY,
        (true, true) => COMPACT_SHORT_POSITIONAL,
    });
    writer.u8(ADAPTIVE_PAYLOAD_VERSION);
    if short {
        writer.varint(source.posting_doc_count);
    }
    writer.varint(source.freq_total);
    writer.varint(lengths.docs);
    writer.varint(lengths.freqs);
    writer.varint(lengths.positions);
    let header_end = writer.len();

    let mut previous_doc: Option<u64> = None;
    for posting in postings {
        let delta = match previous_doc {
            None => posting.doc_id,
            Some(previous) => posting.doc_id - previous,
        };
        writer.varint(delta);
        previous_doc = Some(posting.doc_id);
    }
    let docs_end = writer.len();
    for posting in postings {
        writer.varint(posting.freq);
    }
    let freqs_end = writer.len();
    if positional {
        for posting in postings {
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
    }
    debug_assert_eq!(header_end as u64, header_len);
    debug_assert_eq!((docs_end - header_end) as u64, lengths.docs);
    debug_assert_eq!((freqs_end - docs_end) as u64, lengths.freqs);
    debug_assert_eq!((writer.len() - freqs_end) as u64, lengths.positions);
    debug_assert_eq!(writer.len() as u64, total);
    #[cfg(test)]
    encode_observation::record_final_capacity(writer.capacity_for_test());
    Ok(writer.into_vec())
}

/// Where the shared decoder currently reads posting fields from.
///
/// Rust does not permit enum items inside an `impl` block, so this private
/// module-level item sits beside [`PostingsReader`].
enum PostingStreams<'a> {
    Legacy(ByteReader<'a>),
    Split(SplitStreams<'a>),
    Compact(CompactStreams<'a>),
}

impl std::fmt::Debug for PostingStreams<'_> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Legacy(_) => formatter.write_str("PostingStreams::Legacy"),
            Self::Split(_) => formatter.write_str("PostingStreams::Split"),
            Self::Compact(_) => formatter.write_str("PostingStreams::Compact"),
        }
    }
}

/// Borrowed compact-postings streams (PERF-06-A5).
///
/// Every field borrows the verified segment bytes: constructing a compact cursor
/// parses only the bounded header and three checked extents.
struct CompactStreams<'a> {
    docs: ByteReader<'a>,
    freqs: ByteReader<'a>,
    positions: ByteReader<'a>,
    observed_freq_total: u64,
}

impl std::fmt::Debug for CompactStreams<'_> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("CompactStreams")
            .field("observed_freq_total", &self.observed_freq_total)
            .finish_non_exhaustive()
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

    /// Parse a required-feature-selected adaptive postings payload
    /// (PERF-06-A5 v1).
    ///
    /// Markers 2/3 are the unchanged A3 split payload: they delegate to
    /// [`Self::new_split`] once over the complete slice and are then rejected if
    /// their (already validated) posting count could have been compact. Markers
    /// 4-7 are the compact framing; only the bounded header and three checked
    /// extents are parsed here, so posting bodies stay lazy.
    pub(crate) fn new_adaptive(
        bytes: &'a [u8],
        segment_doc_count: u64,
        limits: &SegmentLimits,
    ) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let marker = reader.u8("adaptive occurrence marker")?;
        if marker == SPLIT_OCCURRENCE_DOC_ONLY || marker == SPLIT_OCCURRENCE_POSITIONAL {
            let split = Self::new_split(bytes, segment_doc_count, limits)?;
            if split.posting_doc_count <= ADAPTIVE_COMPACT_MAX_DOCS {
                return Err(adaptive_corrupt("noncanonical split posting count"));
            }
            return Ok(split);
        }
        let (singleton, positional) = match marker {
            COMPACT_SINGLETON_DOC_ONLY => (true, false),
            COMPACT_SINGLETON_POSITIONAL => (true, true),
            COMPACT_SHORT_DOC_ONLY => (false, false),
            COMPACT_SHORT_POSITIONAL => (false, true),
            _ => return Err(adaptive_corrupt("invalid occurrence marker")),
        };
        let payload_version = reader.u8("adaptive payload version")?;
        if payload_version != ADAPTIVE_PAYLOAD_VERSION {
            return Err(adaptive_corrupt("unsupported payload version"));
        }
        let posting_doc_count = if singleton {
            1
        } else {
            let declared = reader.varint("adaptive posting doc count")?;
            if !(2..=ADAPTIVE_COMPACT_MAX_DOCS).contains(&declared) {
                return Err(adaptive_corrupt("noncanonical compact posting count"));
            }
            declared
        };
        if posting_doc_count > limits.max_postings_per_term() {
            return Err(SegmentError::LimitExceeded {
                limit: limits.max_postings_per_term(),
                requested: posting_doc_count,
            });
        }
        if posting_doc_count > segment_doc_count {
            return Err(adaptive_corrupt("posting count exceeds segment doc count"));
        }
        let freq_total = reader.varint("adaptive freq total")?;
        if freq_total < posting_doc_count {
            return Err(adaptive_corrupt("frequency total below posting count"));
        }
        let doc_stream_len = reader.varint("adaptive doc stream length")?;
        let freq_stream_len = reader.varint("adaptive frequency stream length")?;
        let pos_stream_len = reader.varint("adaptive position stream length")?;
        if positional {
            // Five one-byte-minimum fields per occurrence.
            let minimum_positions = freq_total
                .checked_mul(5)
                .ok_or_else(|| adaptive_corrupt("length overflow"))?;
            if pos_stream_len < minimum_positions {
                return Err(adaptive_corrupt("position stream too short"));
            }
        } else if pos_stream_len != 0 {
            return Err(adaptive_corrupt("doc-only positional bytes"));
        }
        if doc_stream_len < posting_doc_count {
            return Err(adaptive_corrupt("doc stream too short"));
        }
        if freq_stream_len < posting_doc_count {
            return Err(adaptive_corrupt("frequency stream too short"));
        }
        let header_end = reader.position() as u64;
        let declared_total = compact_total_len(
            header_end,
            CompactLengths {
                docs: doc_stream_len,
                freqs: freq_stream_len,
                positions: pos_stream_len,
            },
        )?;
        if declared_total != bytes.len() as u64 {
            return Err(adaptive_corrupt("extent length mismatch"));
        }
        let doc_len =
            usize::try_from(doc_stream_len).map_err(|_| adaptive_corrupt("length overflow"))?;
        let freq_len =
            usize::try_from(freq_stream_len).map_err(|_| adaptive_corrupt("length overflow"))?;
        let pos_len =
            usize::try_from(pos_stream_len).map_err(|_| adaptive_corrupt("length overflow"))?;
        let header_end =
            usize::try_from(header_end).map_err(|_| adaptive_corrupt("length overflow"))?;
        let doc_end = header_end
            .checked_add(doc_len)
            .ok_or_else(|| adaptive_corrupt("length overflow"))?;
        let freq_end = doc_end
            .checked_add(freq_len)
            .ok_or_else(|| adaptive_corrupt("length overflow"))?;
        let pos_end = freq_end
            .checked_add(pos_len)
            .ok_or_else(|| adaptive_corrupt("length overflow"))?;
        if pos_end != bytes.len() {
            return Err(adaptive_corrupt("extent length mismatch"));
        }
        Ok(Self {
            streams: PostingStreams::Compact(CompactStreams {
                docs: ByteReader::new(&bytes[header_end..doc_end]),
                freqs: ByteReader::new(&bytes[doc_end..freq_end]),
                positions: ByteReader::new(&bytes[freq_end..pos_end]),
                observed_freq_total: 0,
            }),
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
                        previous.checked_add(position_delta).ok_or_else(|| {
                            SegmentError::Corrupt {
                                context: "postings",
                                detail: "position overflow".to_owned(),
                            }
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
        match &mut self.streams {
            PostingStreams::Split(split) => {
                split.observed_freq_total = split
                    .observed_freq_total
                    .checked_add(freq)
                    .ok_or_else(|| split_corrupt("frequency total overflow"))?;
            }
            PostingStreams::Compact(compact) => {
                compact.observed_freq_total = compact
                    .observed_freq_total
                    .checked_add(freq)
                    .ok_or_else(|| adaptive_corrupt("frequency total overflow"))?;
            }
            PostingStreams::Legacy(_) => {}
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
            PostingStreams::Legacy(reader)
            | PostingStreams::Compact(CompactStreams { docs: reader, .. }) => {
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
                        previous
                            .checked_add(delta)
                            .ok_or_else(|| SegmentError::Corrupt {
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
            PostingStreams::Compact(compact) => compact.freqs.varint("frequency"),
        }
    }

    /// Read one positional component from the active payload.
    fn position_varint(&mut self, context: &'static str) -> SegmentResult<u64> {
        match &mut self.streams {
            PostingStreams::Legacy(reader) => reader.varint(context),
            PostingStreams::Split(split) => split.positions.varint(context),
            PostingStreams::Compact(compact) => compact.positions.varint(context),
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
            PostingStreams::Compact(compact) => {
                if !compact.docs.is_empty() {
                    return Err(adaptive_corrupt("doc stream trailing bytes"));
                }
                if !compact.freqs.is_empty() {
                    return Err(adaptive_corrupt("frequency stream trailing bytes"));
                }
                if !compact.positions.is_empty() {
                    return Err(adaptive_corrupt("position stream trailing bytes"));
                }
                if compact.observed_freq_total != self.freq_total {
                    return Err(adaptive_corrupt("frequency total mismatch"));
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

/// Test-only witnesses for the adaptive compact encoder's structural cost
/// contract: one source validation, one enabled (measuring) validation, width
/// accounting calls, and exactly one admitted output buffer that never grows.
///
/// These prove named control-flow/allocation sites; they are not a heap
/// profiler and make no claim about total allocator activity. No production
/// counter, metric or tracing hook exists.
#[cfg(test)]
pub(crate) mod encode_observation {
    use std::cell::Cell;

    thread_local! {
        static STATE: Cell<Counts> = const { Cell::new(Counts {
            validation_calls: 0,
            compact_validation_calls: 0,
            width_calls: 0,
            compact_output_buffers: 0,
            initial_capacity: 0,
            final_capacity: 0,
        }) };
    }

    /// Accumulated encoder witnesses for the current thread.
    #[derive(Clone, Copy, Default, Debug, PartialEq, Eq)]
    pub(crate) struct Counts {
        /// Entries into the shared source validator (both specializations).
        pub validation_calls: u64,
        /// Entries into the measuring specialization of the source validator.
        pub compact_validation_calls: u64,
        /// Calls to the private compact varint-width helper.
        pub width_calls: u64,
        /// Successful compact output-buffer admissions.
        pub compact_output_buffers: u64,
        /// Capacity after the single reservation.
        pub initial_capacity: usize,
        /// Capacity at the end of compact emission.
        pub final_capacity: usize,
    }

    /// Reset every witness to zero for the current thread.
    pub(crate) fn reset() {
        STATE.with(|cell| cell.set(Counts::default()));
    }

    /// Current witnesses for this thread.
    pub(crate) fn counts() -> Counts {
        STATE.with(Cell::get)
    }

    pub(super) fn record_validation_call() {
        STATE.with(|cell| {
            let mut counts = cell.get();
            counts.validation_calls += 1;
            cell.set(counts);
        });
    }

    pub(super) fn record_compact_validation_call() {
        STATE.with(|cell| {
            let mut counts = cell.get();
            counts.compact_validation_calls += 1;
            cell.set(counts);
        });
    }

    pub(super) fn record_width_call() {
        STATE.with(|cell| {
            let mut counts = cell.get();
            counts.width_calls += 1;
            cell.set(counts);
        });
    }

    pub(super) fn record_compact_output_buffer(capacity: usize) {
        STATE.with(|cell| {
            let mut counts = cell.get();
            counts.compact_output_buffers += 1;
            counts.initial_capacity = capacity;
            cell.set(counts);
        });
    }

    pub(super) fn record_final_capacity(capacity: usize) {
        STATE.with(|cell| {
            let mut counts = cell.get();
            counts.final_capacity = capacity;
            cell.set(counts);
        });
    }

    /// Test-only access to the private varint-width helper.
    pub(crate) fn test_varint_len(value: u64) -> u64 {
        super::compact_varint_len(value)
    }

    /// Test-only access to the private checked-total helper.
    pub(crate) fn test_total_len(
        header: u64,
        docs: u64,
        freqs: u64,
        positions: u64,
    ) -> super::SegmentResult<u64> {
        super::compact_total_len(
            header,
            super::CompactLengths {
                docs,
                freqs,
                positions,
            },
        )
    }
}
