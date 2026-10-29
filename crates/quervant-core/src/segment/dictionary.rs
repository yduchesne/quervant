//! UTF-8 sorted term dictionary (F05).
//!
//! v1 lookup is sequential and work-budgeted: entries are variable-length with
//! no term-offset index, so sorted order alone provides no random-access
//! guarantee.

use super::decode_budget::DecodeBudget;
use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;
use super::metadata::{MetadataMeter, accumulate, capacity_bytes};
use super::schema::copy_str_fallible;

/// One dictionary entry for a term.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DictionaryEntry {
    /// Term bytes (UTF-8).
    pub term: String,
    /// Number of documents containing the term.
    pub doc_freq: u64,
    /// Offset of the posting block relative to the POSTINGS body.
    pub postings_offset: u64,
    /// Exact posting block length.
    pub postings_length: u64,
}

/// Encode the DICTIONARY section body.
pub fn encode_dictionary(
    fields: &[(u32, Vec<DictionaryEntry>)],
    limits: &SegmentLimits,
) -> SegmentResult<Vec<u8>> {
    let mut writer = ByteWriter::new();
    writer.u16(1); // dictionary_version
    writer.u32(
        u32::try_from(fields.len()).map_err(|_| SegmentError::LimitExceeded {
            limit: u64::from(u32::MAX),
            requested: fields.len() as u64,
        })?,
    );
    for (field_id, entries) in fields {
        writer.u32(*field_id);
        writer.u64(entries.len() as u64);
        let mut previous: Option<&str> = None;
        for entry in entries {
            if entry.term.is_empty() || entry.term.len() > 4096 {
                return Err(SegmentError::Corrupt {
                    context: "dictionary",
                    detail: "invalid term length".to_owned(),
                });
            }
            if entry.doc_freq == 0 || entry.postings_length == 0 {
                return Err(SegmentError::Corrupt {
                    context: "dictionary",
                    detail: "zero doc_freq or posting length".to_owned(),
                });
            }
            if let Some(previous) = previous {
                if previous.as_bytes() >= entry.term.as_bytes() {
                    return Err(SegmentError::DuplicateTerm {
                        field_id: *field_id,
                        term: entry.term.clone(),
                    });
                }
            }
            previous = Some(&entry.term);
            writer.len_prefixed_u16(entry.term.as_bytes())?;
            writer.u64(entry.doc_freq);
            writer.u64(entry.postings_offset);
            writer.u64(entry.postings_length);
        }
    }
    limits.check_entries(fields.iter().map(|(_, e)| e.len() as u64).sum())?;
    Ok(writer.into_vec())
}

/// A decoded term dictionary view.
#[derive(Debug, Default)]
pub struct DictionaryReader {
    fields: Vec<(u32, Vec<DictionaryEntry>)>,
}

impl DictionaryReader {
    /// Decode and validate the DICTIONARY section body.
    ///
    /// Counts are preflighted against remaining source bytes and both the
    /// per-allocation and cumulative decoded-byte budgets before any reserve.
    pub fn new(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<Self> {
        Self::new_metered(bytes, limits, &mut None)
    }

    /// Decode and validate the DICTIONARY section body, charging every retained
    /// allocation before it is made.
    pub(crate) fn new_metered(
        bytes: &[u8],
        limits: &SegmentLimits,
        meter: &mut Option<&mut MetadataMeter>,
    ) -> SegmentResult<Self> {
        /// Minimum encoded bytes for one field header: `field_id:u32` + `term_count:u64`.
        const MIN_FIELD_HEADER_BYTES: u64 = 12;
        /// Minimum encoded bytes for one term entry: `len:u16` + 1 term byte +
        /// `doc_freq:u64` + `postings_offset:u64` + `postings_length:u64`.
        const MIN_TERM_BYTES: u64 = 2 + 1 + 8 + 8 + 8;

        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("dictionary version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: "dictionary version",
                detail: format!("unsupported {version}"),
            });
        }
        let field_count = reader.u32("dictionary field count")?;
        let field_count_u64 = u64::from(field_count);
        limits.check_entries(field_count_u64)?;
        super::format::count_min_bytes(
            "dictionary field headers",
            field_count_u64,
            MIN_FIELD_HEADER_BYTES,
            reader.remaining() as u64,
        )?;
        let mut budget = DecodeBudget::new(limits);
        budget.reserve_vec::<(u32, Vec<DictionaryEntry>)>(field_count_u64)?;
        if let Some(meter) = meter.as_deref_mut() {
            meter.charge_vec::<(u32, Vec<DictionaryEntry>)>(field_count_u64)?;
        }
        let field_capacity =
            usize::try_from(field_count).map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: field_count_u64,
            })?;
        let mut fields: Vec<(u32, Vec<DictionaryEntry>)> = Vec::new();
        fields
            .try_reserve_exact(field_capacity)
            .map_err(|_| SegmentError::LimitExceeded {
                limit: limits.max_single_allocation(),
                requested: field_count_u64,
            })?;

        let mut total_terms: u64 = 0;
        let mut previous_field: Option<u32> = None;
        for _ in 0..field_count {
            let field_id = reader.u32("dictionary field id")?;
            if let Some(previous) = previous_field {
                if field_id <= previous {
                    return Err(SegmentError::Corrupt {
                        context: "dictionary",
                        detail: "field ids not ascending".to_owned(),
                    });
                }
            }
            previous_field = Some(field_id);
            let term_count = reader.u64("dictionary term count")?;
            total_terms = total_terms
                .checked_add(term_count)
                .ok_or(SegmentError::Corrupt {
                    context: "dictionary",
                    detail: "term count overflow".to_owned(),
                })?;
            if total_terms > limits.max_terms_total() {
                return Err(SegmentError::LimitExceeded {
                    limit: limits.max_terms_total(),
                    requested: total_terms,
                });
            }
            limits.check_entries(total_terms)?;
            super::format::count_min_bytes(
                "dictionary term entries",
                term_count,
                MIN_TERM_BYTES,
                reader.remaining() as u64,
            )?;
            budget.reserve_vec::<DictionaryEntry>(term_count)?;
            if let Some(meter) = meter.as_deref_mut() {
                meter.charge_vec::<DictionaryEntry>(term_count)?;
            }
            let entries_capacity =
                usize::try_from(term_count).map_err(|_| SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: term_count,
                })?;
            let mut entries: Vec<DictionaryEntry> = Vec::new();
            entries.try_reserve_exact(entries_capacity).map_err(|_| {
                SegmentError::LimitExceeded {
                    limit: limits.max_single_allocation(),
                    requested: term_count,
                }
            })?;
            for _ in 0..term_count {
                let term_bytes = reader.len_prefixed_u16("dictionary term")?;
                let term_ref =
                    std::str::from_utf8(term_bytes).map_err(|_| SegmentError::InvalidUtf8 {
                        context: "dictionary term",
                    })?;
                if term_ref.is_empty() || term_ref.len() > 4096 {
                    return Err(SegmentError::Corrupt {
                        context: "dictionary",
                        detail: "invalid term length".to_owned(),
                    });
                }
                if let Some(previous) = entries.last() {
                    if previous.term.as_bytes() >= term_ref.as_bytes() {
                        return Err(SegmentError::DuplicateTerm {
                            field_id,
                            term: term_ref.to_owned(),
                        });
                    }
                }
                let doc_freq = reader.u64("dictionary doc freq")?;
                let postings_offset = reader.u64("dictionary postings offset")?;
                let postings_length = reader.u64("dictionary postings length")?;
                if doc_freq == 0 || postings_length == 0 {
                    return Err(SegmentError::Corrupt {
                        context: "dictionary",
                        detail: "zero doc_freq or posting length".to_owned(),
                    });
                }
                budget.reserve_string(term_ref.len() as u64)?;
                if let Some(meter) = meter.as_deref_mut() {
                    meter.charge_str(term_ref.len() as u64)?;
                }
                entries.push(DictionaryEntry {
                    term: copy_str_fallible(term_ref, limits)?,
                    doc_freq,
                    postings_offset,
                    postings_length,
                });
            }
            fields.push((field_id, entries));
        }
        reader.expect_end("dictionary")?;
        Ok(Self { fields })
    }

    /// All fields in ascending id order.
    #[must_use]
    pub fn fields(&self) -> &[(u32, Vec<DictionaryEntry>)] {
        &self.fields
    }

    /// Measured retained-metadata charge of the field, entry and term payloads.
    pub(crate) fn metadata_charge(&self) -> SegmentResult<u64> {
        let mut total = capacity_bytes::<(u32, Vec<DictionaryEntry>)>(self.fields.capacity())?;
        for (_, entries) in &self.fields {
            total = accumulate(
                total,
                capacity_bytes::<DictionaryEntry>(entries.capacity())?,
            )?;
            for entry in entries {
                total = accumulate(total, entry.term.capacity() as u64)?;
            }
        }
        Ok(total)
    }

    /// Entries for one field.
    #[must_use]
    pub fn field(&self, field_id: u32) -> Option<&[DictionaryEntry]> {
        self.fields
            .iter()
            .find(|(id, _)| *id == field_id)
            .map(|(_, entries)| entries.as_slice())
    }

    /// Sequentially look up a term within a field.
    pub fn lookup(&self, field_id: u32, term: &str) -> Option<&DictionaryEntry> {
        self.field(field_id)?
            .iter()
            .find(|entry| entry.term == term)
    }
}

#[cfg(test)]
mod fallible_term_tests {
    //! F5 — retained dictionary terms are copied fallibly and remain byte-exact.

    use super::*;

    fn entry(term: &str, offset: u64) -> DictionaryEntry {
        DictionaryEntry {
            term: term.to_owned(),
            doc_freq: 1,
            postings_offset: offset,
            postings_length: 1,
        }
    }

    // T07 (dictionary half) — multibyte terms survive encoding/decoding byte for
    // byte, are reserved as bytes, and duplicate/unsorted terms keep their typed
    // error.
    #[test]
    fn f5_t07_dictionary_terms_are_byte_exact() {
        let limits = SegmentLimits::default();
        let fields = vec![(
            0u32,
            vec![entry("alpha", 0), entry("hôst", 1), entry("日本語", 2)],
        )];
        let body = encode_dictionary(&fields, &limits).expect("encode");
        let decoded = DictionaryReader::new(&body, &limits).expect("decode");
        assert_eq!(decoded.fields(), fields.as_slice());
        for (_, entries) in decoded.fields() {
            for (retained, source) in entries.iter().zip(fields[0].1.iter()) {
                assert_eq!(retained.term, source.term);
                assert_eq!(retained.term.capacity(), source.term.len());
            }
        }

        // The metered path yields the same directory and charges the term bytes.
        let budget = crate::segment::metadata::MetadataBudget::new(u64::MAX);
        let mut meter =
            crate::segment::metadata::MetadataMeter::reserve(&budget, 1 << 16).expect("allowance");
        let metered = {
            let mut slot = Some(&mut meter);
            DictionaryReader::new_metered(&body, &limits, &mut slot).expect("metered decode")
        };
        assert_eq!(metered.fields(), decoded.fields());

        // Duplicate/unsorted terms are still rejected with the typed error.
        let duplicate = vec![(0u32, vec![entry("beta", 0), entry("alpha", 1)])];
        let body = encode_dictionary(&duplicate, &limits).expect_err("unsorted terms");
        assert!(matches!(
            body,
            SegmentError::DuplicateTerm { field_id: 0, .. }
        ));

        // Malformed UTF-8 in a term keeps its typed error.
        let mut payload = encode_dictionary(&fields, &limits).expect("encode");
        let term_offset = 2 + 4 + 4 + 8 + 2; // version + field count + id + term count + len
        payload[term_offset] = 0xFF;
        assert!(matches!(
            DictionaryReader::new(&payload, &limits),
            Err(SegmentError::InvalidUtf8 { .. })
        ));
    }
}
