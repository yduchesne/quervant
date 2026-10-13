//! UTF-8 sorted term dictionary (F05).
//!
//! v1 lookup is sequential and work-budgeted: entries are variable-length with
//! no term-offset index, so sorted order alone provides no random-access
//! guarantee.

use super::error::{SegmentError, SegmentResult};
use super::format::{ByteReader, ByteWriter};
use super::limits::SegmentLimits;

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
    pub fn new(bytes: &[u8], limits: &SegmentLimits) -> SegmentResult<Self> {
        let mut reader = ByteReader::new(bytes);
        let version = reader.u16("dictionary version")?;
        if version != 1 {
            return Err(SegmentError::Corrupt {
                context: "dictionary version",
                detail: format!("unsupported {version}"),
            });
        }
        let field_count = reader.u32("dictionary field count")?;
        let mut fields = Vec::with_capacity(field_count as usize);
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
            let mut entries = Vec::with_capacity(term_count.min(1024) as usize);
            let mut previous_term: Option<String> = None;
            for _ in 0..term_count {
                let term_bytes = reader.len_prefixed_u16("dictionary term")?;
                let term = std::str::from_utf8(term_bytes)
                    .map_err(|_| SegmentError::InvalidUtf8 {
                        context: "dictionary term",
                    })?
                    .to_owned();
                if term.is_empty() || term.len() > 4096 {
                    return Err(SegmentError::Corrupt {
                        context: "dictionary",
                        detail: "invalid term length".to_owned(),
                    });
                }
                if let Some(previous) = &previous_term {
                    if previous.as_bytes() >= term.as_bytes() {
                        return Err(SegmentError::DuplicateTerm { field_id, term });
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
                previous_term = Some(term.clone());
                entries.push(DictionaryEntry {
                    term,
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
