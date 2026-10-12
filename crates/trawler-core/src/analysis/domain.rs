//! Optional domain-oriented analysis (T06).
//!
//! Canonical DNS identity, reversed labels, PSL decomposition and the UTS #39 confusable
//! skeleton are **separate** derived representations. A skeleton match never implies
//! canonical identity equality.

use idna::uts46::{AsciiDenyList, DnsLength, Hyphens, Uts46};
use publicsuffix::Psl;

use super::cancellation::Cancellation;
use super::config::{DomainConfig, PslPrivateSuffixPolicy};
use super::domain_data;
use super::error::AnalysisError;
use super::limits::AnalysisLimits;
use super::work::WorkBudget;

/// The registration type of a matched public suffix.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SuffixKind {
    /// An ICANN-managed suffix.
    Icann,
    /// A private (non-ICANN) suffix.
    Private,
}

impl SuffixKind {
    #[must_use]
    pub const fn id(self) -> &'static str {
        match self {
            Self::Icann => "icann",
            Self::Private => "private",
        }
    }
}

/// Derived domain representations for one input value.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DomainRepresentations {
    canonical_ascii: String,
    canonical_unicode: String,
    root_dot: bool,
    reversed_labels: String,
    public_suffix: Option<String>,
    public_suffix_type: Option<SuffixKind>,
    registered_domain: Option<String>,
    skeleton: String,
}

impl DomainRepresentations {
    /// Canonical UTS #46 (nontransitional) ASCII identity — never equal to the skeleton.
    #[must_use]
    pub fn canonical_ascii(&self) -> &str {
        &self.canonical_ascii
    }

    /// Canonical Unicode representation.
    #[must_use]
    pub fn canonical_unicode(&self) -> &str {
        &self.canonical_unicode
    }

    /// Whether the input ended with a root dot.
    #[must_use]
    pub const fn has_root_dot(&self) -> bool {
        self.root_dot
    }

    /// Labels in reverse order (no trailing root dot).
    #[must_use]
    pub fn reversed_labels(&self) -> &str {
        &self.reversed_labels
    }

    /// The matched public suffix, if any.
    #[must_use]
    pub fn public_suffix(&self) -> Option<&str> {
        self.public_suffix.as_deref()
    }

    /// The registration type of the matched public suffix.
    #[must_use]
    pub const fn public_suffix_type(&self) -> Option<SuffixKind> {
        self.public_suffix_type
    }

    /// The registrable (registered) domain, if derivable.
    #[must_use]
    pub fn registered_domain(&self) -> Option<&str> {
        self.registered_domain.as_deref()
    }

    /// The UTS #39 skeleton (a similarity artifact, not an identity).
    #[must_use]
    pub fn skeleton(&self) -> &str {
        &self.skeleton
    }
}

/// Analyzes one domain value into its pinned derived representations.
///
/// Domain identity is canonical UTS #46 nontransitional; the skeleton is computed separately
/// and must never be treated as identity.
pub fn analyze_domain(
    input: &str,
    config: DomainConfig,
    limits: &AnalysisLimits,
    cancellation: &dyn Cancellation,
) -> Result<DomainRepresentations, AnalysisError> {
    let mut budget = WorkBudget::new(limits.max_work_units(), cancellation);
    budget.check_cancelled()?;
    let input_bytes = u64::try_from(input.len()).unwrap_or(u64::MAX);
    if input_bytes > limits.max_input_bytes() {
        return Err(AnalysisError::InputTooLarge {
            limit: limits.max_input_bytes(),
            actual: input_bytes,
        });
    }
    budget.charge(u64::try_from(input.chars().count()).unwrap_or(u64::MAX))?;

    let root_dot = input.ends_with('.');
    let canonical_ascii = Uts46::new()
        .to_ascii(
            input.as_bytes(),
            AsciiDenyList::STD3,
            Hyphens::Allow,
            DnsLength::VerifyAllowRootDot,
        )
        .map_err(|_| AnalysisError::MalformedDomain {
            reason: format!("input {input:?} is not valid UTS #46"),
        })?
        .into_owned();

    // Explicitly reject empty interior labels (UTS #46 permits some of these).
    let label_source = canonical_ascii
        .strip_suffix('.')
        .unwrap_or(&canonical_ascii);
    if label_source.is_empty() {
        return Err(AnalysisError::MalformedDomain {
            reason: "domain has no labels".to_owned(),
        });
    }
    if label_source.split('.').any(str::is_empty) {
        return Err(AnalysisError::MalformedDomain {
            reason: "domain contains an empty label".to_owned(),
        });
    }

    let (canonical_unicode, unicode_result) = idna::domain_to_unicode(&canonical_ascii);
    unicode_result.map_err(|_| AnalysisError::MalformedDomain {
        reason: "canonical domain is not valid UTS #46 ToUnicode".to_owned(),
    })?;

    let reversed_labels = label_source.split('.').rev().collect::<Vec<_>>().join(".");

    let (public_suffix, public_suffix_type, registered_domain) =
        match config.psl_private_suffix_policy {
            PslPrivateSuffixPolicy::IncludePrivate => {
                let list = domain_data::psl().full();
                resolve_psl(
                    list.suffix(label_source.as_bytes()),
                    list.domain(label_source.as_bytes()),
                )
            }
            PslPrivateSuffixPolicy::IcannOnly => {
                let list = domain_data::psl().icann();
                resolve_psl(
                    list.suffix(label_source.as_bytes()),
                    list.domain(label_source.as_bytes()),
                )
            }
        };

    let skeleton: String = unicode_security::skeleton(&canonical_unicode).collect();
    budget.check_cancelled()?;

    Ok(DomainRepresentations {
        canonical_ascii,
        canonical_unicode,
        root_dot,
        reversed_labels,
        public_suffix,
        public_suffix_type,
        registered_domain,
        skeleton,
    })
}

fn resolve_psl(
    suffix: Option<publicsuffix::Suffix<'_>>,
    domain: Option<publicsuffix::Domain<'_>>,
) -> (Option<String>, Option<SuffixKind>, Option<String>) {
    let suffix_kind = suffix.and_then(|value| {
        value.typ().map(|typ| match typ {
            publicsuffix::Type::Icann => SuffixKind::Icann,
            publicsuffix::Type::Private => SuffixKind::Private,
        })
    });
    let suffix_text = suffix.map(|value| String::from_utf8_lossy(value.as_bytes()).into_owned());
    let domain_text = domain.map(|value| String::from_utf8_lossy(value.as_bytes()).into_owned());
    (suffix_text, suffix_kind, domain_text)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::analysis::cancellation::NeverCancel;

    fn analyze(input: &str, policy: PslPrivateSuffixPolicy) -> DomainRepresentations {
        analyze_domain(
            input,
            DomainConfig {
                psl_private_suffix_policy: policy,
            },
            &AnalysisLimits::default(),
            &NeverCancel,
        )
        .expect("domain analysis")
    }

    #[test]
    fn canonicalization_is_case_and_unicode_insensitive() {
        let lower = analyze("Example.COM", PslPrivateSuffixPolicy::IncludePrivate);
        let mixed = analyze("eXaMpLe.com", PslPrivateSuffixPolicy::IncludePrivate);
        assert_eq!(lower.canonical_ascii(), mixed.canonical_ascii());
        assert_eq!(lower.canonical_ascii(), "example.com");
    }

    #[test]
    fn root_dot_is_explicit() {
        let with_dot = analyze("example.com.", PslPrivateSuffixPolicy::IncludePrivate);
        let without_dot = analyze("example.com", PslPrivateSuffixPolicy::IncludePrivate);
        assert!(with_dot.has_root_dot());
        assert!(!without_dot.has_root_dot());
        assert_eq!(with_dot.reversed_labels(), "com.example");
    }

    #[test]
    fn psl_registered_domain_and_private_policy() {
        let include = analyze("www.foo.github.io", PslPrivateSuffixPolicy::IncludePrivate);
        assert_eq!(include.public_suffix(), Some("github.io"));
        assert_eq!(include.public_suffix_type(), Some(SuffixKind::Private));
        assert_eq!(include.registered_domain(), Some("foo.github.io"));

        let icann = analyze("www.foo.github.io", PslPrivateSuffixPolicy::IcannOnly);
        assert_eq!(icann.public_suffix(), Some("io"));
        assert_eq!(icann.registered_domain(), Some("github.io"));
    }

    #[test]
    fn invalid_labels_fail_typed() {
        assert!(matches!(
            analyze_domain(
                "a..b",
                DomainConfig::default(),
                &AnalysisLimits::default(),
                &NeverCancel
            ),
            Err(AnalysisError::MalformedDomain { .. })
        ));
        assert!(matches!(
            analyze_domain(
                "bad domain",
                DomainConfig::default(),
                &AnalysisLimits::default(),
                &NeverCancel
            ),
            Err(AnalysisError::MalformedDomain { .. })
        ));
    }
}
