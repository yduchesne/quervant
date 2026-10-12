//! Deterministic, versioned, bounded text and domain analysis (PR 4).
//!
//! This module turns schema-bound field values into reproducible token streams with original
//! UTF-8 source offsets, absolute positions, position increments and position lengths, for
//! use by later positional postings (PR 5) and phrase/highlighting queries.
//!
//! # Dominant invariant
//!
//! Identical input plus pinned analyzer definition/data versions produces identical token
//! terms, positions, increments, lengths and original-input offsets. Mismatches and resource
//! exhaustion fail explicitly; committed data is never silently reinterpreted.
//!
//! # Boundaries
//!
//! * Terms are valid UTF-8 ([`Token`]); binary terms are a separately-versioned future.
//! * Offsets always reference the original source value, even when a token filter changes the
//!   term length ([`AnalyzerDefinition::analyze`]).
//! * Length-changing character filters are rejected, not approximated ([`config::CharacterFilter`]).
//! * Analysis is bounded by [`AnalysisLimits`] and cooperative [`cancellation::Cancellation`].
//! * Analyzer identity is a canonical SHA-256 [`AnalyzerFingerprint`] (T05).
//! * No segment codec, writer, reader, postings, automaton or query executor lives here.

pub mod analyzer;
pub mod cancellation;
pub mod config;
pub mod domain;
pub mod error;
pub mod limits;
pub mod registry;
pub mod term;
pub mod token;

pub(crate) mod domain_data;
pub(crate) mod filters;
pub(crate) mod tokenizer;
pub(crate) mod work;

pub use analyzer::{
    AnalysisCursor, AnalyzerDefinition, AnalyzerFingerprint, AnalyzerRole, POSITION_GAP,
};
pub use cancellation::{Cancellation, CancellationFlag, NeverCancel};
pub use config::{
    CharacterFilter, DomainConfig, NormalizationForm, Pipeline, PslPrivateSuffixPolicy,
    StemmerAlgorithm, StopwordDataset, TokenFilter, TokenizerKind,
};
pub use domain::{DomainRepresentations, SuffixKind, analyze_domain};
pub use domain_data::{DomainDatasetIdentity, domain_dataset_identity};
pub use error::AnalysisError;
pub use limits::AnalysisLimits;
pub use registry::{
    AnalyzerBinding, AnalyzerRegistry, BUILTIN_VERSION, FieldAnalyzerBinding,
    SchemaAnalyzerBindings,
};
pub use term::{
    GlobSegment, PreparedGlob, PreparedPrefix, PreparedRegex, PreparedTerm, TermMetadata,
    prepare_glob, prepare_prefix, prepare_regex, prepare_term,
};
pub use token::Token;
