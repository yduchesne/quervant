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

    let mut writer = ByteWriter::new();
    writer.u8(if positional {
        OCCURRENCE_POSITIONAL
    } else {
        OCCURRENCE_DOC_ONLY
    });
    writer.u64(posting_doc_count);
    let freq_total: u64 = postings
        .iter()
        .try_fold(0u64, |acc, posting| acc.checked_add(posting.freq))
        .ok_or(SegmentError::Corrupt {
            context: "postings",
            detail: "frequency total overflow".to_owned(),
        })?;
    writer.u64(freq_total);

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
        let delta = match previous_doc {
            None => posting.doc_id,
            Some(previous) => {
                if posting.doc_id <= previous {
                    return Err(SegmentError::NonMonotoneDocId {
                        previous,
                        next: posting.doc_id,
                    });
                }
                posting.doc_id - previous
            }
        };
        writer.varint(delta);
        writer.varint(posting.freq);
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
                let position_delta = match previous_position {
                    None => occurrence.position,
                    Some(previous) => {
                        if occurrence.position <= previous {
                            return Err(SegmentError::NonMonotonePosition {
                                doc_id: posting.doc_id,
                            });
                        }
                        occurrence.position - previous
                    }
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

/// A lazy, bounded postings reader.
#[derive(Debug)]
pub struct PostingsReader<'a> {
    reader: ByteReader<'a>,
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
            reader,
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
            self.reader.expect_end("postings")?;
            self.finished = true;
            self.current = None;
            return Ok(None);
        }
        self.limits.check_entries(self.docs_read + 1)?;
        let delta = self.reader.varint("doc id delta")?;
        let doc_id = match self.previous_doc {
            None => delta,
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
                })?
            }
        };
        if doc_id >= self.segment_doc_count {
            return Err(SegmentError::Corrupt {
                context: "postings",
                detail: "doc id out of range".to_owned(),
            });
        }
        let freq = self.reader.varint("frequency")?;
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
                let position_delta = self.reader.varint("position delta")?;
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
                let position_length = self.reader.varint("position length")?;
                if position_length == 0 {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "zero position length".to_owned(),
                    });
                }
                let value_index = self.reader.varint("value index")?;
                if value_index < previous_value_index {
                    return Err(SegmentError::Corrupt {
                        context: "postings",
                        detail: "value index decreased".to_owned(),
                    });
                }
                previous_value_index = value_index;
                let start_offset = self.reader.varint("start offset")?;
                let end_offset = self.reader.varint("end offset")?;
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
        Ok(Some((DocFreqPosting { doc_id, freq }, occurrences)))
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
