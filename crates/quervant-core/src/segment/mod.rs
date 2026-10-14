//! Immutable versioned segment and manifest codecs (PR 5).
//!
//! This module owns byte-level encoding/decoding for immutable segments,
//! manifests, positional postings, typed columns, stored source, conservative
//! bounds and sorted doc-id remapping. It deliberately does **not** implement a
//! production writer, commit/publication protocol, reader generation, refresh,
//! recovery, PIT, query execution, remote ObjectStore/RustFS bootstrap, or
//! distributed/vector functionality.

pub mod bounds;
pub mod build;
pub mod column;
mod decode_budget;
pub mod dictionary;
pub mod error;
pub mod format;
pub mod limits;
pub mod manifest;
pub mod model;
pub mod norms;
pub mod postings;
pub mod reader;
pub mod remap;
pub mod schema;
pub mod stored;
pub mod value;

#[cfg(test)]
mod tests;

pub use bounds::{GeoBounds, TimeBounds};
pub use build::{BuiltSegment, Layout, SegmentBuilder};
pub use column::{
    ColumnReader, GROUP_STATE_MISSING, GROUP_STATE_NULL, GROUP_STATE_VALUE, GroupComponent,
    encode_group_key,
};
pub use dictionary::{DictionaryEntry, DictionaryReader};
pub use error::{SegmentError, SegmentResult};
pub use format::{
    ContainerBuilder, ContainerKind, ContainerView, SectionEntry, SectionInput, SectionKind,
    parse_container,
};
pub use limits::SegmentLimits;
pub use manifest::{Manifest, ManifestSegmentRef};
pub use model::SegmentDocument;
pub use norms::{
    FIELD_NORMS_PAYLOAD_VERSION, FieldNorms, FieldNormsReader, encode_field_norms,
    scoring_field_ids,
};
pub use postings::{Occurrence, Posting, PostingsReader};
pub use reader::{SegmentReader, verify_bytes};
pub use remap::DocRemap;
pub use schema::{CodecField, CodecSchema, FieldBinding};
pub use stored::StoredRecord;
pub use value::{STATE_ABSENT, STATE_EMPTY_MULTI, STATE_EXPLICIT_NULL, STATE_MULTI, STATE_SINGLE};
