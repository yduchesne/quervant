//! Bounded compressed random-access STORED blocks (PR 15I-B, payload version 2).
//!
//! The v2 STORED section is a 22-byte header, a 40-byte entry per 128-document
//! block, and concatenated compressed blocks. Every block body is an ordinary
//! STORED v1 payload for exactly 128 consecutive physical documents (the final
//! block may hold 1..128). The outer section digest and segment digest remain
//! authoritative; there is no per-block checksum.
//!
//! Codec selection is a compile-time candidate property: exactly one of the
//! `stored-lz4` / `stored-zstd1` features must be enabled. There is no runtime
//! codec switch and no adaptive mixing.

#![allow(unexpected_cfgs)]

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::ByteReader;
use super::limits::SegmentLimits;
use super::model::SegmentDocument;
use super::schema::CodecSchema;
use super::stored::{
    StoredRecord, decode_stored_from_validated_offsets, encode_stored, scan_stored_v1_with_budget,
};

/// Documents per STORED v2 block.
pub(crate) const STORED_BLOCK_DOCS: u64 = 128;
/// STORED v2 payload version.
pub(crate) const STORED_BLOCKS_PAYLOAD_VERSION: u16 = 2;
/// Fixed v2 header length.
pub(crate) const BLOCKS_HEADER_LEN: u64 = 22;
/// Fixed directory entry length.
pub(crate) const BLOCK_ENTRY_LEN: u64 = 40;
/// Minimum valid v1 block body (`version` + zero count).
pub(crate) const MIN_BLOCK_BODY_LEN: u64 = 10;

#[cfg(all(feature = "stored-lz4", feature = "stored-zstd1"))]
compile_error!("enable at most one STORED codec feature");
#[cfg(not(any(feature = "stored-lz4", feature = "stored-zstd1")))]
compile_error!("enable exactly one STORED codec feature (stored-lz4 or stored-zstd1)");

/// The single codec compiled into this candidate.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum CodecId {
    /// LZ4 block format.
    Lz4 = 1,
    /// Zstandard level 1.
    Zstd1 = 2,
}

impl CodecId {
    /// The compile-time selected codec.
    pub(crate) const fn selected() -> Self {
        #[cfg(feature = "stored-lz4")]
        {
            Self::Lz4
        }
        #[cfg(feature = "stored-zstd1")]
        {
            Self::Zstd1
        }
    }

    /// The compile-time selected codec name.
    pub(crate) const fn name(self) -> &'static str {
        match self {
            Self::Lz4 => "lz4",
            Self::Zstd1 => "zstd1",
        }
    }

    const fn from_wire(value: u8) -> Option<Self> {
        match value {
            1 => Some(Self::Lz4),
            2 => Some(Self::Zstd1),
            _ => None,
        }
    }
}

/// One validated directory entry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct BlockEntry {
    /// First physical doc id (exactly `block_index * 128`).
    pub first_doc_id: u64,
    /// Documents in the block (128 except the final block).
    pub doc_count: u32,
    /// Compressed block offset relative to the STORED payload.
    pub compressed_offset: u64,
    /// Compressed block length (> 0).
    pub compressed_length: u64,
    /// Declared uncompressed v1 block length (>= 10).
    pub uncompressed_length: u64,
}

/// Parsed, fully checked v2 geometry.
#[derive(Debug, Clone)]
pub(crate) struct ParsedStoredV2 {
    /// Codec declared by the section (must equal the compiled codec).
    pub codec: CodecId,
    /// Total documents (must equal the segment doc count).
    pub total_doc_count: u64,
    /// Directory entries in increasing first-doc-id order.
    pub entries: Vec<BlockEntry>,
}

#[cfg(test)]
thread_local! {
    static DECOMPRESSED_BLOCKS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
}

#[cfg(test)]
pub(crate) fn reset_decompressed_blocks() {
    DECOMPRESSED_BLOCKS.with(|value| value.set(0));
}

#[cfg(test)]
pub(crate) fn decompressed_blocks() -> u64 {
    DECOMPRESSED_BLOCKS.with(std::cell::Cell::get)
}

#[cfg(test)]
pub(crate) static FAIL_STORED_BLOCKS_BUILD: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

#[cfg(test)]
pub(crate) static CERTIFICATE_BUILDS: std::sync::atomic::AtomicU64 =
    std::sync::atomic::AtomicU64::new(0);

#[cfg(test)]
pub(crate) static COUNTER_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

/// Serialize counter-sensitive tests across modules; recover from poison.
#[cfg(test)]
pub(crate) fn test_serial() -> std::sync::MutexGuard<'static, ()> {
    COUNTER_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

#[cfg(test)]
pub(crate) fn set_fail_stored_blocks_build(value: bool) {
    FAIL_STORED_BLOCKS_BUILD.store(value, std::sync::atomic::Ordering::SeqCst);
}

fn corrupt(context: &'static str, detail: impl Into<String>) -> SegmentError {
    SegmentError::Corrupt {
        context,
        detail: detail.into(),
    }
}

fn checked_ceil_blocks(doc_count: u64) -> SegmentResult<u64> {
    doc_count
        .checked_add(STORED_BLOCK_DOCS - 1)
        .map(|value| value / STORED_BLOCK_DOCS)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })
}

fn checked_directory_len(block_count: u64) -> SegmentResult<u64> {
    block_count
        .checked_mul(BLOCK_ENTRY_LEN)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })
}

/// Validate the v2 header and directory without retaining them.
pub(crate) fn validate_stored_v2_header(
    body: &[u8],
    doc_count: u64,
    limits: &SegmentLimits,
) -> SegmentResult<CodecId> {
    let parsed = parse_stored_v2(body, doc_count, limits, false)?;
    Ok(parsed.codec)
}

fn parse_stored_v2(
    body: &[u8],
    doc_count: u64,
    limits: &SegmentLimits,
    retain: bool,
) -> SegmentResult<ParsedStoredV2> {
    let mut reader = ByteReader::new(body);
    let version = reader.u16("stored blocks version")?;
    if version != STORED_BLOCKS_PAYLOAD_VERSION {
        return Err(corrupt(
            "stored blocks version",
            format!("unsupported {version}"),
        ));
    }
    let total = reader.u64("stored blocks doc count")?;
    if total != doc_count {
        return Err(corrupt(
            "stored blocks doc count",
            "section doc count differs from the segment",
        ));
    }
    if total > limits.max_docs() {
        return Err(SegmentError::LimitExceeded {
            limit: limits.max_docs(),
            requested: total,
        });
    }
    let block_docs = reader.u16("stored blocks block size")?;
    if u64::from(block_docs) != STORED_BLOCK_DOCS {
        return Err(corrupt("stored blocks block size", "must be 128"));
    }
    let raw_codec = reader.u8("stored blocks codec")?;
    let codec = CodecId::from_wire(raw_codec).ok_or_else(|| {
        corrupt(
            "stored blocks codec",
            format!("unknown codec id {raw_codec}"),
        )
    })?;
    if codec != CodecId::selected() {
        return Err(corrupt(
            "stored blocks codec",
            format!("codec {} is not this reader's codec", codec.name()),
        ));
    }
    let flags = reader.u8("stored blocks flags")?;
    if flags != 0 {
        return Err(corrupt("stored blocks flags", "unknown flag bits"));
    }
    let block_count = reader.u64("stored blocks count")?;
    let expected_blocks = checked_ceil_blocks(total)?;
    if block_count != expected_blocks {
        return Err(corrupt(
            "stored blocks count",
            format!("declared {block_count}, expected {expected_blocks}"),
        ));
    }
    limits.check_entries(block_count)?;
    limits.check_alloc::<BlockEntry>(block_count)?;
    let directory_len = checked_directory_len(block_count)?;
    let directory_end =
        BLOCKS_HEADER_LEN
            .checked_add(directory_len)
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
    if directory_end > body.len() as u64 {
        return Err(SegmentError::Truncated {
            context: "stored blocks directory",
            needed: directory_end,
            available: body.len() as u64,
        });
    }
    let mut entries = Vec::new();
    if retain {
        entries
            .try_reserve_exact(block_count as usize)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: block_count,
            })?;
    }
    let mut expected_offset = directory_end;
    for index in 0..block_count {
        let first = reader.u64("stored block first doc id")?;
        let expected_first =
            index
                .checked_mul(STORED_BLOCK_DOCS)
                .ok_or(SegmentError::LimitExceeded {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
        if first != expected_first {
            return Err(corrupt(
                "stored blocks first doc id",
                format!("block {index} starts at {first}, expected {expected_first}"),
            ));
        }
        let count = reader.u32("stored block doc count")?;
        let remaining = total - expected_first;
        let expected_count = remaining.min(STORED_BLOCK_DOCS);
        if u64::from(count) != expected_count || count == 0 || count > 128 {
            return Err(corrupt(
                "stored blocks doc count",
                format!("block {index} has {count} docs, expected {expected_count}"),
            ));
        }
        let reserved = reader.u32("stored block reserved")?;
        if reserved != 0 {
            return Err(corrupt("stored blocks reserved", "must be zero"));
        }
        let offset = reader.u64("stored block offset")?;
        if offset != expected_offset {
            return Err(corrupt(
                "stored blocks offset",
                format!("block {index} offset {offset}, expected {expected_offset}"),
            ));
        }
        let compressed_length = reader.u64("stored block compressed length")?;
        if compressed_length == 0 {
            return Err(corrupt(
                "stored blocks compressed length",
                "must be positive",
            ));
        }
        let uncompressed_length = reader.u64("stored block uncompressed length")?;
        if uncompressed_length < MIN_BLOCK_BODY_LEN {
            return Err(corrupt(
                "stored blocks uncompressed length",
                "smaller than a v1 block header",
            ));
        }
        if uncompressed_length > limits.max_single_allocation()
            || uncompressed_length > limits.max_section_decode_bytes()
        {
            return Err(SegmentError::LimitExceeded {
                limit: limits
                    .max_single_allocation()
                    .min(limits.max_section_decode_bytes()),
                requested: uncompressed_length,
            });
        }
        expected_offset =
            expected_offset
                .checked_add(compressed_length)
                .ok_or(SegmentError::LimitExceeded {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
        if expected_offset > body.len() as u64 {
            return Err(SegmentError::Truncated {
                context: "stored blocks payload",
                needed: expected_offset,
                available: body.len() as u64,
            });
        }
        if retain {
            entries.push(BlockEntry {
                first_doc_id: first,
                doc_count: count,
                compressed_offset: offset,
                compressed_length,
                uncompressed_length,
            });
        }
    }
    if expected_offset != body.len() as u64 {
        return Err(corrupt(
            "stored blocks payload",
            format!(
                "compressed payload ends at {expected_offset}, section is {}",
                body.len()
            ),
        ));
    }
    Ok(ParsedStoredV2 {
        codec,
        total_doc_count: total,
        entries,
    })
}

/// Parse and retain the validated v2 directory.
pub(crate) fn parse_stored_v2_directory(
    body: &[u8],
    doc_count: u64,
    limits: &SegmentLimits,
) -> SegmentResult<ParsedStoredV2> {
    parse_stored_v2(body, doc_count, limits, true)
}

#[cfg(feature = "stored-lz4")]
fn lz4_compress(input: &[u8], limits: &SegmentLimits) -> SegmentResult<Vec<u8>> {
    let bound = lz4_flex::block::get_maximum_output_size(input.len());
    let mut output = Vec::new();
    output
        .try_reserve_exact(bound)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: bound as u64,
        })?;
    output.resize(bound, 0);
    let written = lz4_flex::block::compress_into(input, &mut output)
        .map_err(|error| corrupt("stored blocks lz4 compress", error.to_string()))?;
    output.truncate(written);
    Ok(output)
}

#[cfg(feature = "stored-zstd1")]
fn zstd_compress(input: &[u8], limits: &SegmentLimits) -> SegmentResult<Vec<u8>> {
    let bound = zstd::zstd_safe::compress_bound(input.len());
    let mut output = Vec::new();
    output
        .try_reserve_exact(bound)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: bound as u64,
        })?;
    output.resize(bound, 0);
    let written = zstd::bulk::compress_to_buffer(input, &mut output, 1)
        .map_err(|error| corrupt("stored blocks zstd compress", error.to_string()))?;
    output.truncate(written);
    Ok(output)
}

fn compress(input: &[u8], limits: &SegmentLimits) -> SegmentResult<Vec<u8>> {
    #[cfg(feature = "stored-lz4")]
    {
        lz4_compress(input, limits)
    }
    #[cfg(feature = "stored-zstd1")]
    {
        zstd_compress(input, limits)
    }
}

/// Decompress one block into an exactly sized bounded buffer.
pub(crate) fn decompress_block(
    input: &[u8],
    uncompressed_length: u64,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let length = usize::try_from(uncompressed_length).map_err(|_| SegmentError::LimitExceeded {
        limit: limits.max_single_allocation(),
        requested: uncompressed_length,
    })?;
    let mut output = Vec::new();
    output
        .try_reserve_exact(length)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: uncompressed_length,
        })?;
    output.resize(length, 0);
    #[cfg(feature = "stored-lz4")]
    let written = lz4_flex::block::decompress_into(input, &mut output)
        .map_err(|error| corrupt("stored blocks lz4 decompress", error.to_string()))?;
    #[cfg(feature = "stored-zstd1")]
    let written = zstd::bulk::decompress_to_buffer(input, &mut output)
        .map_err(|error| corrupt("stored blocks zstd decompress", error.to_string()))?;
    if written != length {
        return Err(corrupt(
            "stored blocks decompress",
            format!("produced {written} bytes, declared {length}"),
        ));
    }
    #[cfg(test)]
    DECOMPRESSED_BLOCKS.with(|value| value.set(value.get() + 1));
    Ok(output)
}

fn push_u16(out: &mut Vec<u8>, value: u16) {
    out.extend_from_slice(&value.to_le_bytes());
}
fn push_u32(out: &mut Vec<u8>, value: u32) {
    out.extend_from_slice(&value.to_le_bytes());
}
fn push_u64(out: &mut Vec<u8>, value: u64) {
    out.extend_from_slice(&value.to_le_bytes());
}

/// Encode a complete STORED v2 payload for `docs` using the selected codec.
pub(crate) fn encode_stored_blocks(
    schema: &CodecSchema,
    docs: &[SegmentDocument],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let total = u64::try_from(docs.len()).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    limits.check_entries(total)?;
    let block_count = checked_ceil_blocks(total)?;
    limits.check_entries(block_count)?;
    limits.check_alloc::<BlockEntry>(block_count)?;
    let directory_len = checked_directory_len(block_count)?;
    let mut blocks: Vec<(Vec<u8>, u64)> = Vec::new();
    blocks
        .try_reserve_exact(block_count as usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: block_count,
        })?;
    let mut payload_bytes: u64 = 0;
    for chunk in docs.chunks(STORED_BLOCK_DOCS as usize) {
        let v1 = encode_stored(schema, chunk, limits)?;
        let uncompressed_length = v1.len() as u64;
        let compressed = compress(&v1, limits)?;
        payload_bytes = payload_bytes.checked_add(compressed.len() as u64).ok_or(
            SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            },
        )?;
        blocks.push((compressed, uncompressed_length));
    }
    let total_len = BLOCKS_HEADER_LEN
        .checked_add(directory_len)
        .and_then(|value| value.checked_add(payload_bytes))
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    limits.check_allocation_bytes(total_len)?;
    let mut out = Vec::new();
    out.try_reserve_exact(total_len as usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: total_len,
        })?;
    push_u16(&mut out, STORED_BLOCKS_PAYLOAD_VERSION);
    push_u64(&mut out, total);
    push_u16(&mut out, STORED_BLOCK_DOCS as u16);
    out.push(CodecId::selected() as u8);
    out.push(0);
    push_u64(&mut out, block_count);
    let mut offset = BLOCKS_HEADER_LEN + directory_len;
    for (index, (compressed, uncompressed_length)) in blocks.iter().enumerate() {
        let first = index as u64 * STORED_BLOCK_DOCS;
        let count = (total - first).min(STORED_BLOCK_DOCS);
        push_u64(&mut out, first);
        push_u32(&mut out, count as u32);
        push_u32(&mut out, 0);
        push_u64(&mut out, offset);
        push_u64(&mut out, compressed.len() as u64);
        push_u64(&mut out, *uncompressed_length);
        offset =
            offset
                .checked_add(compressed.len() as u64)
                .ok_or(SegmentError::LimitExceeded {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?;
    }
    for (compressed, _) in &blocks {
        out.extend_from_slice(compressed);
    }
    debug_assert_eq!(out.len() as u64, total_len);
    Ok(out)
}

/// Validate every v2 block with one shared full-decode budget.
pub(crate) fn validate_all_blocks(
    schema: &CodecSchema,
    body: &[u8],
    parsed: &ParsedStoredV2,
    limits: &SegmentLimits,
    budget: &mut DecodeBudget<'_>,
    mut captured: Option<&mut Vec<u64>>,
) -> SegmentResult<()> {
    debug_assert!(budget.retained() > 0 || parsed.total_doc_count == 0);
    let expected_total = if captured.is_some() {
        Some(
            parsed
                .total_doc_count
                .checked_add(parsed.entries.len() as u64)
                .ok_or(SegmentError::LimitExceeded {
                    limit: u64::MAX,
                    requested: u64::MAX,
                })?,
        )
    } else {
        None
    };
    if let Some(flat) = captured.as_deref() {
        if !flat.is_empty() || flat.capacity() < expected_total.unwrap_or(0) as usize {
            return Err(corrupt(
                "stored blocks offsets",
                "offset table must be empty with sufficient capacity",
            ));
        }
    }
    for entry in &parsed.entries {
        let before = captured.as_deref().map_or(0, Vec::len);
        let start = usize::try_from(entry.compressed_offset)
            .map_err(|_| corrupt("stored blocks offset", "not representable"))?;
        let end = start
            .checked_add(
                usize::try_from(entry.compressed_length)
                    .map_err(|_| corrupt("stored blocks compressed length", "not representable"))?,
            )
            .ok_or_else(|| corrupt("stored blocks extent", "overflow"))?;
        let compressed = body
            .get(start..end)
            .ok_or_else(|| corrupt("stored blocks extent", "out of range"))?;
        let block = decompress_block(compressed, entry.uncompressed_length, limits)?;
        let read = scan_stored_v1_with_budget(
            schema,
            &block,
            limits,
            budget,
            &[],
            captured.as_deref_mut(),
        )?;
        if !read.is_empty() {
            return Err(corrupt(
                "stored blocks validation",
                "unselected validation materialized records",
            ));
        }
        if let Some(flat) = captured.as_deref() {
            let added = flat.len().saturating_sub(before);
            if added != entry.doc_count as usize + 1 {
                return Err(corrupt(
                    "stored blocks offsets",
                    "captured boundary count disagrees with the directory",
                ));
            }
            validate_offset_slice(&flat[before..], entry, block.len())?;
        }
        let mut header = ByteReader::new(&block);
        let version = header.u16("stored block version")?;
        let declared = header.u64("stored block count")?;
        if version != 1 || declared != u64::from(entry.doc_count) {
            return Err(corrupt(
                "stored blocks validation",
                "block header disagrees with the directory",
            ));
        }
    }
    if let (Some(flat), Some(expected)) = (captured.as_deref(), expected_total) {
        if flat.len() as u64 != expected {
            return Err(corrupt(
                "stored blocks offsets",
                "captured offset count is not N + block_count",
            ));
        }
    }
    Ok(())
}

fn validate_offset_slice(slice: &[u64], entry: &BlockEntry, block_len: usize) -> SegmentResult<()> {
    if slice.len() != entry.doc_count as usize + 1 {
        return Err(corrupt(
            "stored blocks offsets",
            "boundary count disagrees with the block doc count",
        ));
    }
    if slice[0] != MIN_BLOCK_BODY_LEN {
        return Err(corrupt(
            "stored blocks offsets",
            "first boundary is not the v1 header length",
        ));
    }
    for pair in slice.windows(2) {
        #[cfg(test)]
        crate::segment::stored::test_observation::record_full_offset_pair_check();
        if pair[0] >= pair[1] {
            return Err(corrupt(
                "stored blocks offsets",
                "boundaries are not strictly increasing",
            ));
        }
    }
    let last = *slice.last().unwrap_or(&0);
    if last != entry.uncompressed_length || last > block_len as u64 {
        return Err(corrupt(
            "stored blocks offsets",
            "terminal boundary disagrees with the uncompressed length",
        ));
    }
    Ok(())
}

/// Decode only selected record slices using the flat boundary certificate.
///
/// The hot path computes `block_index = doc_id / 128`, inspects exactly one
/// directory entry per touched block and decodes only the selected local record
/// slices through the existing v1 validated-offset decoder.
pub(crate) fn decode_selected_with_offsets(
    schema: &CodecSchema,
    body: &[u8],
    parsed: &ParsedStoredV2,
    limits: &SegmentLimits,
    record_ends: &[u64],
    selected_doc_ids: &[u64],
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    for pair in selected_doc_ids.windows(2) {
        if pair[0] >= pair[1] {
            return Err(corrupt(
                "stored selection",
                "selected doc ids must be strictly increasing",
            ));
        }
    }
    if selected_doc_ids
        .last()
        .is_some_and(|last| *last >= parsed.total_doc_count)
    {
        return Err(corrupt("stored", "doc id out of range"));
    }
    let expected = parsed
        .total_doc_count
        .checked_add(parsed.entries.len() as u64)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    if record_ends.len() as u64 != expected {
        return Err(corrupt(
            "stored blocks offsets",
            "certificate offset table length is invalid",
        ));
    }
    let selected_count =
        u64::try_from(selected_doc_ids.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    limits.check_alloc::<(u64, StoredRecord)>(selected_count)?;
    if selected_doc_ids.is_empty() {
        return Ok(Vec::new());
    }
    let first_block = usize::try_from(selected_doc_ids[0] / STORED_BLOCK_DOCS)
        .map_err(|_| corrupt("stored blocks offset", "block index not representable"))?;
    let last_block =
        usize::try_from(selected_doc_ids[selected_doc_ids.len() - 1] / STORED_BLOCK_DOCS)
            .map_err(|_| corrupt("stored blocks offset", "block index not representable"))?;
    if first_block == last_block {
        // R3: the decoder-owned result vector is returned directly.
        let mut scratch: Vec<u64> = Vec::new();
        return decode_certified_block(
            schema,
            body,
            parsed,
            limits,
            record_ends,
            first_block,
            selected_doc_ids,
            &mut scratch,
        );
    }
    let mut result: Vec<(u64, StoredRecord)> = Vec::new();
    result
        .try_reserve_exact(selected_doc_ids.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: selected_count,
        })?;
    #[cfg(test)]
    crate::segment::stored::test_observation::record_extra_outer_allocation();
    let mut scratch: Vec<u64> = Vec::new();
    let mut cursor = 0usize;
    while cursor < selected_doc_ids.len() {
        let global_id = selected_doc_ids[cursor];
        let block_index = usize::try_from(global_id / STORED_BLOCK_DOCS)
            .map_err(|_| corrupt("stored blocks offset", "block index not representable"))?;
        let entry = parsed
            .entries
            .get(block_index)
            .ok_or_else(|| corrupt("stored blocks directory", "block index out of range"))?;
        let last_id = entry
            .first_doc_id
            .checked_add(u64::from(entry.doc_count))
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
        let start_cursor = cursor;
        while cursor < selected_doc_ids.len() && selected_doc_ids[cursor] < last_id {
            cursor += 1;
        }
        if cursor == start_cursor {
            return Err(corrupt(
                "stored blocks directory",
                "selected doc id is not covered by its block",
            ));
        }
        let decoded = decode_certified_block(
            schema,
            body,
            parsed,
            limits,
            record_ends,
            block_index,
            &selected_doc_ids[start_cursor..cursor],
            &mut scratch,
        )?;
        result.extend(decoded);
    }
    if cursor != selected_doc_ids.len() || result.len() != selected_doc_ids.len() {
        return Err(corrupt(
            "stored selection",
            "selected records were not all decoded",
        ));
    }
    Ok(result)
}

/// Validate only the endpoints and the selected record boundaries of a
/// certificate table whose complete monotonicity was proven at publication.
fn validate_certified_selected_slice(
    slice: &[u64],
    entry: &BlockEntry,
    local_ids: &[u64],
) -> SegmentResult<()> {
    let expected = usize::try_from(entry.doc_count)
        .ok()
        .and_then(|count| count.checked_add(1))
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    if slice.len() != expected {
        return Err(corrupt(
            "stored blocks offsets",
            "boundary count disagrees with the block doc count",
        ));
    }
    if slice.first().copied() != Some(MIN_BLOCK_BODY_LEN)
        || slice.last().copied() != Some(entry.uncompressed_length)
    {
        return Err(corrupt(
            "stored blocks offsets",
            "certified endpoints disagree with the block",
        ));
    }
    let doc_count = usize::try_from(entry.doc_count).map_err(|_| SegmentError::LimitExceeded {
        limit: u64::MAX,
        requested: u64::MAX,
    })?;
    for local_id in local_ids {
        let index = usize::try_from(*local_id).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
        if index >= doc_count {
            return Err(corrupt(
                "stored blocks offsets",
                "local doc id out of range",
            ));
        }
        let next = index.checked_add(1).ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
        let start = slice.get(index).copied().ok_or_else(|| {
            corrupt(
                "stored blocks offsets",
                "selected start offset out of range",
            )
        })?;
        let end = slice
            .get(next)
            .copied()
            .ok_or_else(|| corrupt("stored blocks offsets", "selected end offset out of range"))?;
        if !(MIN_BLOCK_BODY_LEN <= start && start < end && end <= entry.uncompressed_length) {
            return Err(corrupt(
                "stored blocks offsets",
                "selected record boundaries are invalid",
            ));
        }
        #[cfg(test)]
        crate::segment::stored::test_observation::record_selected_boundary_check();
    }
    Ok(())
}

// The prescribed helper takes schema/body/parsed/limits/offsets/block/selection/
// scratch explicitly; bundling would hide the trust boundary and add indirection.
#[allow(clippy::too_many_arguments)]
fn decode_certified_block(
    schema: &CodecSchema,
    body: &[u8],
    parsed: &ParsedStoredV2,
    limits: &SegmentLimits,
    record_ends: &[u64],
    block_index: usize,
    selected_global_ids: &[u64],
    local_scratch: &mut Vec<u64>,
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    if selected_global_ids.is_empty() {
        return Err(corrupt("stored selection", "empty block selection"));
    }
    #[cfg(test)]
    crate::segment::stored::test_observation::record_hot_block_lookup();
    let entry = parsed
        .entries
        .get(block_index)
        .ok_or_else(|| corrupt("stored blocks directory", "block index out of range"))?;
    let expected_first =
        (block_index as u64)
            .checked_mul(STORED_BLOCK_DOCS)
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
    if entry.first_doc_id != expected_first {
        return Err(corrupt(
            "stored blocks directory",
            "block first doc id disagrees with the geometry",
        ));
    }
    let first_id = entry.first_doc_id;
    let last_id =
        first_id
            .checked_add(u64::from(entry.doc_count))
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
    for pair in selected_global_ids.windows(2) {
        if pair[0] >= pair[1] {
            return Err(corrupt(
                "stored selection",
                "selected doc ids must be strictly increasing",
            ));
        }
    }
    for global_id in selected_global_ids {
        if *global_id < first_id || *global_id >= last_id {
            return Err(corrupt(
                "stored blocks directory",
                "selected doc id is not covered by its block",
            ));
        }
    }
    let single = [selected_global_ids[0]
        .checked_sub(first_id)
        .ok_or_else(|| corrupt("stored", "doc id out of range"))?];
    let local_ids: &[u64] = if selected_global_ids.len() == 1 {
        &single
    } else {
        #[cfg(test)]
        crate::segment::stored::test_observation::record_local_id_reservation();
        local_scratch.clear();
        local_scratch
            .try_reserve_exact(selected_global_ids.len())
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: selected_global_ids.len() as u64,
            })?;
        for global_id in selected_global_ids {
            local_scratch.push(
                global_id
                    .checked_sub(first_id)
                    .ok_or_else(|| corrupt("stored", "doc id out of range"))?,
            );
        }
        local_scratch.as_slice()
    };
    let offset_start =
        first_id
            .checked_add(block_index as u64)
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
    let offset_end = offset_start
        .checked_add(u64::from(entry.doc_count) + 1)
        .ok_or(SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    let slice = record_ends
        .get(offset_start as usize..offset_end as usize)
        .ok_or_else(|| corrupt("stored blocks offsets", "offset slice out of range"))?;
    validate_certified_selected_slice(slice, entry, local_ids)?;
    let start = usize::try_from(entry.compressed_offset)
        .map_err(|_| corrupt("stored blocks offset", "not representable"))?;
    let end = start
        .checked_add(
            usize::try_from(entry.compressed_length)
                .map_err(|_| corrupt("stored blocks compressed length", "not representable"))?,
        )
        .ok_or_else(|| corrupt("stored blocks extent", "overflow"))?;
    let block = decompress_block(
        body.get(start..end)
            .ok_or_else(|| corrupt("stored blocks extent", "out of range"))?,
        entry.uncompressed_length,
        limits,
    )?;
    let mut records =
        decode_stored_from_validated_offsets(schema, &block, limits, slice, local_ids)?;
    for (local_id, _) in &mut records {
        *local_id = first_id
            .checked_add(*local_id)
            .ok_or(SegmentError::LimitExceeded {
                limit: u64::MAX,
                requested: u64::MAX,
            })?;
    }
    if records.len() != selected_global_ids.len()
        || records.windows(2).any(|pair| pair[0].0 >= pair[1].0)
    {
        return Err(corrupt(
            "stored selection",
            "selected records were not all decoded in order",
        ));
    }
    Ok(records)
}

/// Decode selected global doc ids from an already validated v2 directory.
pub(crate) fn decode_selected_from_validated(
    schema: &CodecSchema,
    body: &[u8],
    parsed: &ParsedStoredV2,
    limits: &SegmentLimits,
    selected_doc_ids: &[u64],
) -> SegmentResult<Vec<(u64, StoredRecord)>> {
    let selected_count =
        u64::try_from(selected_doc_ids.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::MAX,
            requested: u64::MAX,
        })?;
    limits.check_alloc::<(u64, StoredRecord)>(selected_count)?;
    let mut result: Vec<(u64, StoredRecord)> = Vec::new();
    result
        .try_reserve_exact(selected_doc_ids.len())
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: selected_count,
        })?;
    let mut cursor = 0usize;
    for entry in &parsed.entries {
        let first = entry.first_doc_id;
        let last = first + u64::from(entry.doc_count);
        if cursor < selected_doc_ids.len() && selected_doc_ids[cursor] < first {
            return Err(corrupt("stored", "doc id out of range"));
        }
        let start_index = cursor;
        while cursor < selected_doc_ids.len() && selected_doc_ids[cursor] < last {
            cursor += 1;
        }
        if start_index == cursor {
            continue;
        }
        let local: Vec<u64> = selected_doc_ids[start_index..cursor]
            .iter()
            .map(|doc_id| doc_id - first)
            .collect();
        let start = usize::try_from(entry.compressed_offset)
            .map_err(|_| corrupt("stored blocks offset", "not representable"))?;
        let end = start
            .checked_add(
                usize::try_from(entry.compressed_length)
                    .map_err(|_| corrupt("stored blocks compressed length", "not representable"))?,
            )
            .ok_or_else(|| corrupt("stored blocks extent", "overflow"))?;
        let block = decompress_block(
            body.get(start..end)
                .ok_or_else(|| corrupt("stored blocks extent", "out of range"))?,
            entry.uncompressed_length,
            limits,
        )?;
        let mut local_budget = DecodeBudget::new(limits);
        local_budget.reserve_vec::<StoredRecord>(u64::from(entry.doc_count))?;
        let records =
            scan_stored_v1_with_budget(schema, &block, limits, &mut local_budget, &local, None)?;
        for (local_id, record) in records {
            result.push((first + local_id, record));
        }
    }
    if cursor != selected_doc_ids.len() {
        return Err(corrupt("stored", "doc id out of range"));
    }
    if result.len() != selected_doc_ids.len() {
        return Err(corrupt(
            "stored selection",
            "selected doc id was not present in the stored section",
        ));
    }
    Ok(result)
}

/// Materialize every record from a validated v2 directory.
pub(crate) fn decode_all_from_validated(
    schema: &CodecSchema,
    body: &[u8],
    parsed: &ParsedStoredV2,
    limits: &SegmentLimits,
) -> SegmentResult<Vec<StoredRecord>> {
    let mut result: Vec<StoredRecord> = Vec::new();
    result
        .try_reserve_exact(parsed.total_doc_count as usize)
        .map_err(|_| SegmentError::LimitExceeded {
            limit: limits.max_single_allocation(),
            requested: parsed.total_doc_count,
        })?;
    let mut budget = DecodeBudget::new(limits);
    budget.reserve_vec::<StoredRecord>(parsed.total_doc_count)?;
    for entry in &parsed.entries {
        let start = usize::try_from(entry.compressed_offset)
            .map_err(|_| corrupt("stored blocks offset", "not representable"))?;
        let end = start
            .checked_add(
                usize::try_from(entry.compressed_length)
                    .map_err(|_| corrupt("stored blocks compressed length", "not representable"))?,
            )
            .ok_or_else(|| corrupt("stored blocks extent", "overflow"))?;
        let block = decompress_block(
            body.get(start..end)
                .ok_or_else(|| corrupt("stored blocks extent", "out of range"))?,
            entry.uncompressed_length,
            limits,
        )?;
        let local: Vec<u64> = (0..u64::from(entry.doc_count)).collect();
        let records =
            scan_stored_v1_with_budget(schema, &block, limits, &mut budget, &local, None)?;
        for (_local_id, record) in records {
            result.push(record);
        }
    }
    if result.len() as u64 != parsed.total_doc_count {
        return Err(corrupt(
            "stored blocks materialize",
            "record count differs from the directory",
        ));
    }
    Ok(result)
}

#[cfg(test)]
mod direct_offsets_tests {
    use super::*;
    use crate::analysis::{AnalyzerRegistry, SchemaAnalyzerBindings};
    use crate::contract::document::{Cardinality, DocumentKey, FieldValues};
    use crate::contract::schema::{FieldDefinition, FieldOptions, Schema};
    use crate::contract::value::{FieldType, FieldValue};
    use crate::segment::stored::test_observation;

    fn schema() -> CodecSchema {
        let contract = Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::new(true, true, false),
                ),
            ],
            None,
        )
        .expect("schema");
        let bindings = SchemaAnalyzerBindings::resolve(&contract, &AnalyzerRegistry::builtin())
            .expect("bindings");
        CodecSchema::from_contract(&contract, &bindings).expect("codec schema")
    }

    fn docs(count: usize) -> Vec<SegmentDocument> {
        (0..count)
            .map(|index| {
                let mut document =
                    SegmentDocument::new(DocumentKey::new(format!("k{index:06}")).unwrap());
                document.fields.insert(
                    "title".to_owned(),
                    FieldValues::Single(FieldValue::Text(format!("title {index}"))),
                );
                document.fields.insert(
                    "tag".to_owned(),
                    FieldValues::Single(FieldValue::Keyword(if index % 2 == 0 {
                        "even".to_owned()
                    } else {
                        "odd".to_owned()
                    })),
                );
                document
            })
            .collect()
    }

    fn build(count: usize) -> (CodecSchema, Vec<u8>, ParsedStoredV2, Vec<u64>) {
        let schema = schema();
        let limits = SegmentLimits::default();
        let body = encode_stored_blocks(&schema, &docs(count), &limits).expect("encode");
        let parsed = parse_stored_v2_directory(&body, count as u64, &limits).expect("parse");
        let count_offsets = count as u64 + parsed.entries.len() as u64;
        let mut offsets = Vec::new();
        offsets
            .try_reserve_exact(count_offsets as usize)
            .expect("reserve");
        let mut budget = DecodeBudget::new(&limits);
        budget
            .reserve_vec::<StoredRecord>(count as u64)
            .expect("budget");
        validate_all_blocks(
            &schema,
            &body,
            &parsed,
            &limits,
            &mut budget,
            Some(&mut offsets),
        )
        .expect("validate");
        (schema, body, parsed, offsets)
    }

    #[test]
    fn dr_u01_dr_u08_flat_offsets_geometry() {
        let _serial = test_serial();
        for count in [0usize, 1, 127, 128, 129, 255, 256, 257] {
            let (schema, body, parsed, offsets) = build(count);
            let limits = SegmentLimits::default();
            let blocks = (count as u64).div_ceil(STORED_BLOCK_DOCS) as usize;
            assert_eq!(offsets.len(), count + blocks, "N={count}");
            let full = decode_all_from_validated(&schema, &body, &parsed, &limits).expect("all");
            assert_eq!(full.len(), count);
            if count > 0 {
                let selected: Vec<u64> = if count == 1 {
                    vec![0]
                } else {
                    vec![0, count as u64 - 1]
                };
                let direct = decode_selected_with_offsets(
                    &schema, &body, &parsed, &limits, &offsets, &selected,
                )
                .expect("direct");
                assert_eq!(direct.len(), selected.len());
                for (doc_id, record) in direct {
                    assert_eq!(record, full[doc_id as usize]);
                }
            }
        }
    }

    #[test]
    fn dr_u05_dr_u07_cross_block_mapping() {
        let _serial = test_serial();
        let (schema, body, parsed, offsets) = build(129);
        let limits = SegmentLimits::default();
        let full = decode_all_from_validated(&schema, &body, &parsed, &limits).expect("all");
        let direct = decode_selected_with_offsets(
            &schema,
            &body,
            &parsed,
            &limits,
            &offsets,
            &[0, 127, 128],
        )
        .expect("direct");
        for (doc_id, record) in direct {
            assert_eq!(record, full[doc_id as usize]);
        }
        // Block 1 begins at flat index 128 + 1.
        let second_start = (parsed.entries[1].first_doc_id + 1) as usize;
        assert_eq!(offsets[second_start], 10);
    }

    #[test]
    fn dr_u19_dr_u22_forged_offset_tables_fail() {
        let _serial = test_serial();
        let (schema, body, parsed, offsets) = build(129);
        let limits = SegmentLimits::default();
        let selected = [0u64];
        let mut bad = offsets.clone();
        bad[0] = 9;
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        let mut bad = offsets.clone();
        bad[1] = bad[0];
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        let mut bad = offsets.clone();
        let last = parsed.entries[0].doc_count as usize;
        bad[last] += 1;
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        let mut short = offsets.clone();
        short.pop();
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &short, &selected)
                .is_err()
        );
    }

    #[test]
    fn dr_u18_bad_selection_is_rejected_before_decode() {
        let _serial = test_serial();
        let (schema, body, parsed, offsets) = build(129);
        let limits = SegmentLimits::default();
        for selected in [&[2u64, 1][..], &[1, 1][..], &[129][..]] {
            assert!(
                decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, selected)
                    .is_err()
            );
        }
    }

    #[test]
    fn res_u14_u17_singleton_and_single_block_fast_path() {
        let _serial = test_serial();
        let (schema, body, parsed, offsets) = build(300);
        let limits = SegmentLimits::default();
        test_observation::reset();
        let one = decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[0])
            .expect("singleton");
        assert_eq!(one.len(), 1);
        assert_eq!(test_observation::direct_records(), 1);
        assert_eq!(test_observation::hot_block_lookups(), 1);
        assert_eq!(test_observation::local_id_reservations(), 0);
        assert_eq!(test_observation::extra_outer_allocations(), 0);
        assert_eq!(test_observation::full_offset_pair_checks(), 0);
        assert_eq!(test_observation::selected_boundary_checks(), 1);
        test_observation::reset();
        let three =
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[0, 63, 127])
                .expect("single block");
        assert_eq!(three.len(), 3);
        assert_eq!(test_observation::hot_block_lookups(), 1);
        assert_eq!(test_observation::local_id_reservations(), 1);
        assert_eq!(test_observation::extra_outer_allocations(), 0);
        assert_eq!(test_observation::selected_boundary_checks(), 3);
        test_observation::reset();
        let _ = decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[0, 200])
            .expect("multi block");
        assert_eq!(test_observation::hot_block_lookups(), 2);
        assert_eq!(test_observation::extra_outer_allocations(), 1);
        // Each touched block has a single selected ID, so no local scratch heap
        // reservation is made even in the multi-block path.
        assert_eq!(test_observation::local_id_reservations(), 0);
    }

    #[test]
    fn res_u22_u25_selected_and_endpoint_corruption_is_rejected() {
        let _serial = test_serial();
        let (schema, body, parsed, offsets) = build(129);
        let limits = SegmentLimits::default();
        let selected = [0u64];
        // Selected record end boundary corrupted.
        let mut bad = offsets.clone();
        bad[1] += 1;
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        // First endpoint corrupted.
        let mut bad = offsets.clone();
        bad[0] = 9;
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        // Terminal endpoint corrupted.
        let mut bad = offsets.clone();
        let terminal = parsed.entries[0].doc_count as usize;
        bad[terminal] += 1;
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        // Short table.
        let mut bad = offsets.clone();
        bad.pop();
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected)
                .is_err()
        );
        // Selected id 127 uses the last selected pair of block 0.
        let selected_last = [127u64];
        let mut bad = offsets.clone();
        bad[127] += 1;
        assert!(
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &bad, &selected_last)
                .is_err()
        );
    }

    #[test]
    fn dr_u40_hot_counters_scale_with_touched_blocks() {
        let _serial = test_serial();
        let (schema, body, parsed, offsets) = build(300);
        let limits = SegmentLimits::default();
        test_observation::reset();
        let selected =
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[0])
                .expect("one");
        assert_eq!(selected.len(), 1);
        assert_eq!(test_observation::direct_records(), 1);
        assert_eq!(test_observation::hot_block_lookups(), 1);
        test_observation::reset();
        let selected =
            decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[1, 2])
                .expect("same block");
        assert_eq!(selected.len(), 2);
        assert_eq!(test_observation::direct_records(), 2);
        assert_eq!(test_observation::hot_block_lookups(), 1);
        test_observation::reset();
        let _ = decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[0, 200])
            .expect("two blocks");
        assert_eq!(test_observation::direct_records(), 2);
        assert_eq!(test_observation::hot_block_lookups(), 2);
        test_observation::reset();
        let empty = decode_selected_with_offsets(&schema, &body, &parsed, &limits, &offsets, &[])
            .expect("empty");
        assert!(empty.is_empty());
        assert_eq!(test_observation::direct_records(), 0);
        assert_eq!(test_observation::hot_block_lookups(), 0);
    }
}
