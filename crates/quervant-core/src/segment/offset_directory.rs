//! Persistent, uncompressed record-start offset directories for segment 1.1.

use std::ops::Range;

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter, sha256};
use super::limits::SegmentLimits;

/// Fixed directory header length.
pub const DIRECTORY_HEADER_LEN: u64 = 50;
/// Directory body version.
pub const DIRECTORY_VERSION: u16 = 1;

/// Borrowed, structurally validated offset directory.
#[derive(Debug, Clone, Copy)]
pub(crate) struct OffsetDirectoryView<'a> {
    body: &'a [u8],
    doc_count: u64,
    source_digest: [u8; 32],
}

impl<'a> OffsetDirectoryView<'a> {
    /// Declared document count.
    pub(crate) const fn doc_count(&self) -> u64 {
        self.doc_count
    }

    /// Declared source body digest bound by this directory.
    pub(crate) const fn source_digest(&self) -> [u8; 32] {
        self.source_digest
    }

    fn boundary_bytes(&self, index: u64) -> SegmentResult<&'a [u8; 8]> {
        let entries = self
            .doc_count
            .checked_add(1)
            .ok_or_else(|| corrupt("offset directory", "entry count overflow"))?;
        if index >= entries {
            return Err(corrupt("offset directory", "boundary index out of range"));
        }
        let start = DIRECTORY_HEADER_LEN
            .checked_add(
                index
                    .checked_mul(8)
                    .ok_or_else(|| corrupt("offset directory", "boundary offset overflow"))?,
            )
            .ok_or_else(|| corrupt("offset directory", "boundary offset overflow"))?;
        let start = usize::try_from(start)
            .map_err(|_| corrupt("offset directory", "boundary offset not representable"))?;
        let end = start
            .checked_add(8)
            .ok_or_else(|| corrupt("offset directory", "boundary extent overflow"))?;
        self.body
            .get(start..end)
            .and_then(|slice| <&[u8; 8]>::try_from(slice).ok())
            .ok_or_else(|| corrupt("offset directory", "boundary truncated"))
    }

    /// Read one boundary.
    pub(crate) fn boundary(&self, index: u64) -> SegmentResult<u64> {
        Ok(u64::from_le_bytes(*self.boundary_bytes(index)?))
    }

    /// Checked absolute range for one document, relative to its source body.
    pub(crate) fn range(&self, doc_id: u64) -> SegmentResult<Range<usize>> {
        if doc_id >= self.doc_count {
            return Err(corrupt("offset directory", "doc id out of range"));
        }
        let start = self.boundary(doc_id)?;
        let end = self.boundary(doc_id + 1)?;
        if start >= end {
            return Err(corrupt(
                "offset directory",
                "record range is not strictly increasing",
            ));
        }
        let start = usize::try_from(start)
            .map_err(|_| corrupt("offset directory", "start not representable"))?;
        let end = usize::try_from(end)
            .map_err(|_| corrupt("offset directory", "end not representable"))?;
        Ok(start..end)
    }

    /// Compare every persisted boundary with a complete semantic scan.
    pub(crate) fn compare_boundaries(&self, scanned: &[u64]) -> SegmentResult<()> {
        let expected = self
            .doc_count
            .checked_add(1)
            .ok_or_else(|| corrupt("offset directory", "entry count overflow"))?;
        let expected = usize::try_from(expected)
            .map_err(|_| corrupt("offset directory", "entry count not representable"))?;
        if scanned.len() != expected {
            return Err(corrupt(
                "offset directory",
                "scanned boundary count mismatch",
            ));
        }
        for (index, value) in scanned.iter().copied().enumerate() {
            let index_u64 = u64::try_from(index)
                .map_err(|_| corrupt("offset directory", "boundary index not representable"))?;
            if self.boundary(index_u64)? != value {
                return Err(corrupt(
                    "offset directory",
                    "persisted boundary differs from scan",
                ));
            }
        }
        Ok(())
    }
}

fn corrupt(context: &'static str, detail: &str) -> SegmentError {
    SegmentError::Corrupt {
        context,
        detail: detail.to_owned(),
    }
}

fn expected_directory_len(doc_count: u64) -> SegmentResult<u64> {
    let entries = doc_count
        .checked_add(1)
        .ok_or_else(|| corrupt("offset directory", "entry count overflow"))?;
    DIRECTORY_HEADER_LEN
        .checked_add(
            entries
                .checked_mul(8)
                .ok_or_else(|| corrupt("offset directory", "directory length overflow"))?,
        )
        .ok_or_else(|| corrupt("offset directory", "directory length overflow"))
}

/// Encode one canonical directory body.
pub(crate) fn encode_offset_directory(
    boundaries: &[u64],
    doc_count: u64,
    source_body: &[u8],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let entries = doc_count
        .checked_add(1)
        .ok_or_else(|| corrupt("offset directory", "entry count overflow"))?;
    let expected_len = expected_directory_len(doc_count)?;
    limits.check_entries(doc_count)?;
    limits.check_allocation_bytes(expected_len)?;
    if boundaries.len() as u64 != entries {
        return Err(corrupt(
            "offset directory",
            "boundary count does not match doc count",
        ));
    }
    let source_len = u64::try_from(source_body.len())
        .map_err(|_| corrupt("offset directory", "source length not representable"))?;
    if boundaries.first().copied() != Some(10) || boundaries.last().copied() != Some(source_len) {
        return Err(corrupt("offset directory", "first/last boundary mismatch"));
    }
    if boundaries.windows(2).any(|pair| pair[0] >= pair[1]) {
        return Err(corrupt(
            "offset directory",
            "boundaries are not strictly increasing",
        ));
    }
    let capacity = usize::try_from(expected_len)
        .map_err(|_| corrupt("offset directory", "directory length not representable"))?;
    let mut writer = ByteWriter::with_capacity(capacity);
    writer.u16(DIRECTORY_VERSION);
    writer.u64(doc_count);
    writer.u64(source_len);
    writer.bytes(&sha256(source_body));
    for boundary in boundaries {
        writer.u64(*boundary);
    }
    if writer.len() as u64 != expected_len {
        return Err(corrupt("offset directory", "encoded length mismatch"));
    }
    Ok(writer.into_vec())
}

/// Inspect and structurally validate one persistent directory.
pub(crate) fn inspect_offset_directory<'a>(
    body: &'a [u8],
    doc_count: u64,
    source_body_len: u64,
    source_digest: [u8; 32],
    limits: &SegmentLimits,
) -> SegmentResult<OffsetDirectoryView<'a>> {
    let expected_len = expected_directory_len(doc_count)?;
    limits.check_entries(doc_count)?;
    limits.check_allocation_bytes(expected_len)?;
    if body.len() as u64 != expected_len {
        return Err(corrupt("offset directory", "unexpected directory length"));
    }
    let mut reader = ByteReader::new(body);
    let version = reader.u16("offset directory version")?;
    if version != DIRECTORY_VERSION {
        return Err(corrupt("offset directory", "unsupported directory version"));
    }
    let encoded_count = reader.u64("offset directory doc count")?;
    if encoded_count != doc_count {
        return Err(corrupt("offset directory", "doc count mismatch"));
    }
    let encoded_source_len = reader.u64("offset directory source length")?;
    if encoded_source_len != source_body_len {
        return Err(corrupt("offset directory", "source length mismatch"));
    }
    let digest = reader.bytes(32, "offset directory source digest")?;
    if digest != source_digest {
        return Err(corrupt("offset directory", "source digest mismatch"));
    }
    let entries = doc_count
        .checked_add(1)
        .ok_or_else(|| corrupt("offset directory", "entry count overflow"))?;
    let mut previous = None;
    let mut index = 0u64;
    while index < entries {
        let value = reader.u64("offset directory boundary")?;
        if index == 0 {
            if value != 10 {
                return Err(corrupt("offset directory", "first boundary is not 10"));
            }
        } else if previous.is_some_and(|prev| value <= prev) {
            return Err(corrupt(
                "offset directory",
                "boundaries are not strictly increasing",
            ));
        }
        previous = Some(value);
        index += 1;
    }
    if previous != Some(source_body_len) {
        return Err(corrupt(
            "offset directory",
            "terminal boundary is not source length",
        ));
    }
    reader.expect_end("offset directory")?;
    Ok(OffsetDirectoryView {
        body,
        doc_count,
        source_digest,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn body(n: usize) -> Vec<u8> {
        let mut out = vec![0u8; 10];
        for index in 0..n {
            out.extend_from_slice(&(index as u64).to_le_bytes());
        }
        out
    }

    fn boundaries(n: usize, source_len: usize) -> Vec<u64> {
        let mut values = vec![10u64];
        for index in 0..n {
            values.push(10 + ((index + 1) * (source_len - 10) / n.max(1)) as u64);
        }
        if let Some(last) = values.last_mut() {
            *last = source_len as u64;
        }
        values
    }

    #[test]
    fn round_trips_empty_one_two_and_many() {
        for n in [0usize, 1, 2, 1024] {
            let source = body(n * 8);
            let bounds = boundaries(n, source.len());
            let encoded =
                encode_offset_directory(&bounds, n as u64, &source, &SegmentLimits::default())
                    .expect("encode");
            assert_eq!(encoded.len() as u64, 50 + 8 * (n as u64 + 1));
            let view = inspect_offset_directory(
                &encoded,
                n as u64,
                source.len() as u64,
                sha256(&source),
                &SegmentLimits::default(),
            )
            .expect("inspect");
            for (index, expected) in bounds.iter().enumerate() {
                assert_eq!(view.boundary(index as u64).unwrap(), *expected);
            }
            if n > 0 {
                let range = view.range(0).unwrap();
                assert_eq!(range.start, 10);
            }
        }
    }

    #[test]
    fn rejects_bad_geometry() {
        let source = body(2 * 8);
        let bounds = boundaries(2, source.len());
        let encoded =
            encode_offset_directory(&bounds, 2, &source, &SegmentLimits::default()).unwrap();
        let limits = SegmentLimits::default();
        let cases = [
            encoded[..encoded.len() - 1].to_vec(),
            {
                let mut value = encoded.clone();
                value.push(0);
                value
            },
            {
                let mut value = encoded.clone();
                value[0] = 2;
                value
            },
            {
                let mut value = encoded.clone();
                value[8] = 3;
                value
            },
            {
                let mut value = encoded.clone();
                value[16] ^= 1;
                value
            },
            {
                let mut value = encoded.clone();
                value[48] ^= 1;
                value
            },
        ];
        for mutated in cases {
            assert!(
                inspect_offset_directory(
                    &mutated,
                    2,
                    source.len() as u64,
                    sha256(&source),
                    &limits,
                )
                .is_err()
            );
        }
        assert!(
            inspect_offset_directory(&encoded, 2, source.len() as u64, [0u8; 32], &limits).is_err()
        );
    }

    #[test]
    fn rejects_nonmonotone_and_bad_terminals() {
        let source = body(3 * 8);
        let limits = SegmentLimits::default();
        let mut bounds = boundaries(3, source.len());
        bounds[2] = bounds[1];
        assert!(encode_offset_directory(&bounds, 3, &source, &limits).is_err());
        let mut bounds = boundaries(3, source.len());
        bounds[0] = 11;
        assert!(encode_offset_directory(&bounds, 3, &source, &limits).is_err());
        let mut bounds = boundaries(3, source.len());
        *bounds.last_mut().unwrap() -= 1;
        assert!(encode_offset_directory(&bounds, 3, &source, &limits).is_err());
    }

    #[test]
    fn enforces_allocation_and_entry_caps() {
        let source = body(8);
        let bounds = boundaries(1, source.len());
        let small = SegmentLimits::default().with_max_single_allocation(10);
        assert!(encode_offset_directory(&bounds, 1, &source, &small).is_err());
        let entries = SegmentLimits::default().with_max_decoded_entries(0);
        assert!(encode_offset_directory(&bounds, 1, &source, &entries).is_err());
    }
}
