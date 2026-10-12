//! Pinned dataset identities and loaded Public Suffix List (D-GATE-2, D-GATE-3).
//!
//! The datasets are embedded at compile time; nothing is fetched at runtime. A unit test
//! re-verifies the recorded SHA-256 digests so accidental edits fail the build.

use std::sync::OnceLock;

use publicsuffix::{IcannList, List};
use sha2::{Digest, Sha256};

/// Exact ICU4X data identity embedded in `icu_casemap` / `idna_adapter` (from the shipped
/// `icu_*_data` crate READMEs: "generated with CLDR version 47.0.0, ICU version
/// icu4x/2025-05-01/77.x").
pub const ICU4X_DATASET_ID: &str = "cldr-47.0.0+icu4x-2025-05-01-77.x";

/// Version string from the pinned Public Suffix List header.
pub const PSL_DATASET_VERSION: &str = "2026-10-07_07-28-19_UTC";
/// Commit hash from the pinned Public Suffix List header.
pub const PSL_DATASET_COMMIT: &str = "3929462652695bad04f0a27afb600974014a3c8b";
/// Retrieval date of the pinned Public Suffix List.
pub const PSL_DATASET_RETRIEVED: &str = "2026-10-12";

/// Identity of the pinned Snowball English stopword list.
pub const STOPWORDS_DATASET_VERSION: &str = "snowball-english-stop.txt@2026-10-12";
/// Exact reviewed `rust-stemmers` version.
pub const RUST_STEMMERS_VERSION: &str = "1.2.0";
/// Exact reviewed `unicode-security` version providing UTS #39 data.
pub const UNICODE_SECURITY_VERSION: &str = "0.1.2";
/// Exact reviewed `idna` version.
pub const IDNA_VERSION: &str = "1.1.0";
/// Exact reviewed `publicsuffix` version.
pub const PUBLICSUFFIX_VERSION: &str = "2.3.0";

/// Embedded pinned Public Suffix List.
pub(crate) const PUBLIC_SUFFIX_LIST: &str = include_str!("data/public_suffix_list.dat");

/// Parsed Public Suffix List views.
pub(crate) struct PslData {
    full: List,
    icann: IcannList,
}

impl PslData {
    /// The full list (ICANN + private rules).
    pub(crate) fn full(&self) -> &List {
        &self.full
    }

    /// The ICANN-only view.
    pub(crate) fn icann(&self) -> &IcannList {
        &self.icann
    }
}

/// Returns the lazily parsed, process-wide Public Suffix List.
pub(crate) fn psl() -> &'static PslData {
    static PSL: OnceLock<PslData> = OnceLock::new();
    PSL.get_or_init(|| {
        let full = List::from_bytes(PUBLIC_SUFFIX_LIST.as_bytes()).unwrap_or_else(|_| {
            // The embedded list is pinned and validated by tests; an empty list keeps this
            // function panic-free while still failing closed (no suffix matches).
            List::new()
        });
        let icann = full.clone().into();
        PslData { full, icann }
    })
}

/// Verifies the embedded dataset headers match the recorded pinned version/commit.
#[cfg(test)]
pub(crate) fn psl_header_matches(expected_version: &str, expected_commit: &str) -> bool {
    PUBLIC_SUFFIX_LIST
        .lines()
        .any(|line| line.trim() == format!("// VERSION: {expected_version}"))
        && PUBLIC_SUFFIX_LIST
            .lines()
            .any(|line| line.trim() == format!("// COMMIT: {expected_commit}"))
}

/// Convenience: is the embedded list non-empty and usable?
#[cfg(test)]
pub(crate) fn psl_is_usable() -> bool {
    let data = psl();
    !data.full.is_empty() || !data.icann.is_empty()
}

/// A public, verifiable record of the exact domain datasets compiled into this build.
///
/// Consumers (and PR 5 segment metadata) can record these identities; a mismatch is a
/// reindex event, never a silent reinterpretation (D-GATE-3, A4-17).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DomainDatasetIdentity {
    /// `idna` crate version.
    pub idna_version: &'static str,
    /// ICU4X embedded data identity used by `idna` and case mapping.
    pub icu4x_dataset: &'static str,
    /// Pinned Public Suffix List version header.
    pub psl_version: &'static str,
    /// Pinned Public Suffix List commit header.
    pub psl_commit: &'static str,
    /// Pinned Public Suffix List retrieval date.
    pub psl_retrieved: &'static str,
    /// Recorded SHA-256 of the embedded Public Suffix List.
    pub psl_sha256: &'static str,
    /// `publicsuffix` crate version.
    pub publicsuffix_version: &'static str,
    /// Unicode version of the UTS #39 data.
    pub uts39_unicode_version: (u64, u64, u64),
    /// `unicode-security` crate version.
    pub unicode_security_version: &'static str,
}

impl DomainDatasetIdentity {
    /// Re-verifies the embedded dataset still matches the recorded identity.
    #[must_use]
    pub fn matches_embedded(&self) -> bool {
        let digest = Sha256::digest(PUBLIC_SUFFIX_LIST.as_bytes());
        let mut hex = String::with_capacity(64);
        for byte in digest {
            hex.push(char::from_digit(u32::from(byte >> 4), 16).unwrap_or('0'));
            hex.push(char::from_digit(u32::from(byte & 0x0f), 16).unwrap_or('0'));
        }
        hex == self.psl_sha256
            && PUBLIC_SUFFIX_LIST
                .lines()
                .any(|line| line.trim() == format!("// VERSION: {}", self.psl_version))
            && PUBLIC_SUFFIX_LIST
                .lines()
                .any(|line| line.trim() == format!("// COMMIT: {}", self.psl_commit))
    }
}

/// Returns the exact domain dataset identities pinned in this build.
#[must_use]
pub fn domain_dataset_identity() -> DomainDatasetIdentity {
    DomainDatasetIdentity {
        idna_version: IDNA_VERSION,
        icu4x_dataset: ICU4X_DATASET_ID,
        psl_version: PSL_DATASET_VERSION,
        psl_commit: PSL_DATASET_COMMIT,
        psl_retrieved: PSL_DATASET_RETRIEVED,
        psl_sha256: crate::analysis::filters::PSL_SHA256,
        publicsuffix_version: PUBLICSUFFIX_VERSION,
        uts39_unicode_version: unicode_security::UNICODE_VERSION,
        unicode_security_version: UNICODE_SECURITY_VERSION,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::filters::{PSL_SHA256, STOPWORDS_SHA256, raw_stopwords};
    use publicsuffix::Psl;
    use sha2::{Digest, Sha256};

    fn sha256_hex(bytes: &[u8]) -> String {
        let digest = Sha256::digest(bytes);
        let mut out = String::with_capacity(64);
        for byte in digest {
            out.push(char::from_digit(u32::from(byte >> 4), 16).unwrap_or('0'));
            out.push(char::from_digit(u32::from(byte & 0x0f), 16).unwrap_or('0'));
        }
        out
    }

    #[test]
    fn psl_digest_matches_recorded_provenance() {
        assert_eq!(sha256_hex(PUBLIC_SUFFIX_LIST.as_bytes()), PSL_SHA256);
    }

    #[test]
    fn stopwords_digest_matches_recorded_provenance() {
        assert_eq!(sha256_hex(raw_stopwords().as_bytes()), STOPWORDS_SHA256);
    }

    #[test]
    fn psl_header_matches_recorded_version() {
        assert!(psl_header_matches(PSL_DATASET_VERSION, PSL_DATASET_COMMIT));
        assert!(!psl_header_matches(
            "1900-01-01_00-00-00_UTC",
            PSL_DATASET_COMMIT
        ));
    }

    #[test]
    fn psl_parses_and_contains_known_suffixes() {
        assert!(psl_is_usable());
        let full = psl().full();
        assert!(full.suffix(b"example.com").is_some());
        // A private suffix exists in the full list.
        assert!(full.suffix(b"foo.github.io").is_some());
        // A registrable domain is derived.
        assert!(full.domain(b"www.example.com").is_some());
    }
}
