//! PR 4 domain-analysis integration tests (A4-14…A4-17, I4-02).

use quervant_core::analysis::{
    AnalysisError, AnalysisLimits, AnalyzerRegistry, DomainConfig, NeverCancel,
    PslPrivateSuffixPolicy, SuffixKind, analyze_domain, domain_dataset_identity,
};

fn limits() -> AnalysisLimits {
    AnalysisLimits::default()
}

fn analyze(
    input: &str,
    policy: PslPrivateSuffixPolicy,
) -> quervant_core::analysis::DomainRepresentations {
    analyze_domain(
        input,
        DomainConfig {
            psl_private_suffix_policy: policy,
        },
        &limits(),
        &NeverCancel,
    )
    .expect("domain analysis")
}

#[test]
fn a4_14_idna_canonicalization_and_invalid_labels() {
    let unicode = analyze("BÜCHER.example", PslPrivateSuffixPolicy::IncludePrivate);
    let ascii = analyze(
        "xn--bcher-kva.example",
        PslPrivateSuffixPolicy::IncludePrivate,
    );
    assert_eq!(unicode.canonical_ascii(), "xn--bcher-kva.example");
    assert_eq!(unicode.canonical_ascii(), ascii.canonical_ascii());
    assert_eq!(unicode.canonical_unicode(), "bücher.example");

    for invalid in ["bad domain", "a..b", ""] {
        assert!(
            matches!(
                analyze_domain(invalid, DomainConfig::default(), &limits(), &NeverCancel),
                Err(AnalysisError::MalformedDomain { .. })
            ),
            "expected malformed-domain error for {invalid:?}"
        );
    }
}

#[test]
fn a4_15_root_dot_reversed_labels_and_psl_private_policy() {
    let with_dot = analyze("WWW.Example.COM.", PslPrivateSuffixPolicy::IncludePrivate);
    assert!(with_dot.has_root_dot());
    assert_eq!(with_dot.reversed_labels(), "com.example.www");
    assert_eq!(with_dot.public_suffix(), Some("com"));
    assert_eq!(with_dot.registered_domain(), Some("example.com"));

    let private = analyze("www.foo.github.io", PslPrivateSuffixPolicy::IncludePrivate);
    assert_eq!(private.public_suffix(), Some("github.io"));
    assert_eq!(private.public_suffix_type(), Some(SuffixKind::Private));
    assert_eq!(private.registered_domain(), Some("foo.github.io"));

    let icann = analyze("www.foo.github.io", PslPrivateSuffixPolicy::IcannOnly);
    assert_eq!(icann.public_suffix(), Some("io"));
    assert_eq!(icann.registered_domain(), Some("github.io"));
}

#[test]
fn a4_16_skeleton_may_collide_while_identity_stays_distinct() {
    // U+0430 CYRILLIC SMALL LETTER A visually collides with Latin 'a'.
    let spoof = analyze("аpple.com", PslPrivateSuffixPolicy::IncludePrivate);
    let genuine = analyze("apple.com", PslPrivateSuffixPolicy::IncludePrivate);

    assert_eq!(spoof.skeleton(), genuine.skeleton());
    assert_ne!(spoof.canonical_ascii(), genuine.canonical_ascii());
    assert_ne!(spoof.canonical_unicode(), genuine.canonical_unicode());
}

#[test]
fn a4_17_pinned_domain_dataset_identity_is_verifiable() {
    let identity = domain_dataset_identity();
    assert!(identity.matches_embedded());
    assert_eq!(identity.psl_sha256.len(), 64);
    assert!(!identity.psl_version.is_empty());
    assert!(!identity.psl_commit.is_empty());
    assert!(!identity.icu4x_dataset.is_empty());
    assert_eq!(identity.uts39_unicode_version, (16, 0, 0));

    // Policy is part of the fingerprint: private and ICANN-only differ.
    let registry = AnalyzerRegistry::builtin();
    assert_ne!(
        registry.get("domain").expect("domain").fingerprint(),
        registry
            .get("domain_icann")
            .expect("domain_icann")
            .fingerprint()
    );
}

#[test]
fn i4_02_domain_field_produces_separate_representations() {
    let registry = AnalyzerRegistry::builtin();
    let definition = registry.get("domain").expect("domain");
    let config = definition.domain().expect("domain config");

    let representations = analyze_domain("sub.Example.co.uk.", config, &limits(), &NeverCancel)
        .expect("domain analysis");

    // Canonical identity, reversed labels, PSL decomposition and skeleton are distinct.
    assert_eq!(representations.canonical_ascii(), "sub.example.co.uk.");
    assert_eq!(representations.reversed_labels(), "uk.co.example.sub");
    assert_eq!(representations.public_suffix(), Some("co.uk"));
    assert_eq!(
        representations.public_suffix_type(),
        Some(SuffixKind::Icann)
    );
    assert_eq!(representations.registered_domain(), Some("example.co.uk"));
    // The UTS #39 skeleton is a separate similarity artifact (e.g. it folds confusables),
    // never the canonical identity.
    assert!(!representations.skeleton().is_empty());
    assert_ne!(
        representations.skeleton(),
        representations.canonical_ascii()
    );
    assert!(!definition.fingerprint().to_hex().is_empty());
}
