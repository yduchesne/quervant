//! Deterministic analyzer registry and schema bindings (T05, A4-10/A4-18/A4-19).

use std::collections::BTreeMap;

use crate::contract::schema::{FieldDefinition, Schema};
use crate::contract::value::FieldType;

use super::analyzer::{AnalyzerDefinition, AnalyzerFingerprint};
use super::config::{
    DomainConfig, NormalizationForm, Pipeline, PslPrivateSuffixPolicy, StemmerAlgorithm,
    StopwordDataset, TokenFilter, TokenizerKind,
};
use super::error::AnalysisError;

/// Built-in analyzer/normalizer version for the initial release.
pub const BUILTIN_VERSION: &str = "1.0.0";

/// A deterministic registry of named analyzer definitions.
#[derive(Debug, Clone, Default)]
pub struct AnalyzerRegistry {
    definitions: BTreeMap<String, AnalyzerDefinition>,
}

impl AnalyzerRegistry {
    /// Builds the registry with the approved built-in analyzers and normalizers.
    #[must_use]
    pub fn builtin() -> Self {
        let mut registry = Self::default();
        for definition in builtin_definitions() {
            // Built-ins are constructed from validated literals; ignore duplicate results.
            let _ = registry.register(definition);
        }
        registry
    }

    /// Registers a definition, rejecting duplicate ids (fail closed, no silent override).
    pub fn register(&mut self, definition: AnalyzerDefinition) -> Result<(), AnalysisError> {
        let id = definition.id().to_owned();
        if self.definitions.contains_key(&id) {
            return Err(AnalysisError::InvalidConfiguration {
                reason: format!("duplicate analyzer id: {id}"),
            });
        }
        self.definitions.insert(id, definition);
        Ok(())
    }

    /// Resolves a definition by name, failing closed for unknown names.
    pub fn get(&self, name: &str) -> Result<&AnalyzerDefinition, AnalysisError> {
        self.definitions
            .get(name)
            .ok_or_else(|| AnalysisError::UnknownAnalyzer {
                name: name.to_owned(),
            })
    }

    /// Resolves a definition and verifies the expected semantic version.
    pub fn resolve_compatible(
        &self,
        name: &str,
        expected_version: &str,
    ) -> Result<&AnalyzerDefinition, AnalysisError> {
        let definition = self.get(name)?;
        if definition.version() != expected_version {
            return Err(AnalysisError::AnalyzerVersionMismatch {
                expected: expected_version.to_owned(),
                found: definition.version().to_owned(),
            });
        }
        Ok(definition)
    }

    #[must_use]
    pub fn contains(&self, name: &str) -> bool {
        self.definitions.contains_key(name)
    }

    #[must_use]
    pub fn len(&self) -> usize {
        self.definitions.len()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.definitions.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &AnalyzerDefinition)> {
        self.definitions
            .iter()
            .map(|(name, definition)| (name.as_str(), definition))
    }
}

// Built one definition at a time for readability; the collected vector is small and fixed.
#[allow(clippy::vec_init_then_push)]
fn builtin_definitions() -> Vec<AnalyzerDefinition> {
    let mut definitions = Vec::new();
    definitions.push(
        AnalyzerDefinition::uniform(
            "keyword",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::Keyword,
                vec![TokenFilter::Normalize(NormalizationForm::Nfc)],
            )
            .expect("keyword pipeline"),
        )
        .expect("keyword definition"),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "keyword_noop",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::Keyword,
                vec![TokenFilter::Normalize(NormalizationForm::None)],
            )
            .expect("keyword_noop pipeline"),
        )
        .expect("keyword_noop definition"),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "standard",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::UnicodeWord,
                vec![TokenFilter::Normalize(NormalizationForm::Nfc)],
            )
            .expect("standard pipeline"),
        )
        .expect("standard definition"),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "standard_folded",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::UnicodeWord,
                vec![
                    TokenFilter::Normalize(NormalizationForm::Nfc),
                    TokenFilter::CaseFold,
                ],
            )
            .expect("standard_folded pipeline"),
        )
        .expect("standard_folded definition"),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "english",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::UnicodeWord,
                vec![
                    TokenFilter::Normalize(NormalizationForm::Nfc),
                    TokenFilter::CaseFold,
                    TokenFilter::Stopwords(StopwordDataset::EnglishSnowball),
                    TokenFilter::Stem(StemmerAlgorithm::English),
                ],
            )
            .expect("english pipeline"),
        )
        .expect("english definition"),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "whitespace",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::Whitespace,
                vec![TokenFilter::Normalize(NormalizationForm::Nfc)],
            )
            .expect("whitespace pipeline"),
        )
        .expect("whitespace definition"),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "domain",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::Keyword,
                vec![
                    TokenFilter::Normalize(NormalizationForm::Nfc),
                    TokenFilter::CaseFold,
                ],
            )
            .expect("domain pipeline"),
        )
        .expect("domain definition")
        .with_domain(DomainConfig::default()),
    );
    definitions.push(
        AnalyzerDefinition::uniform(
            "domain_icann",
            BUILTIN_VERSION,
            Pipeline::simple(
                TokenizerKind::Keyword,
                vec![
                    TokenFilter::Normalize(NormalizationForm::Nfc),
                    TokenFilter::CaseFold,
                ],
            )
            .expect("domain_icann pipeline"),
        )
        .expect("domain_icann definition")
        .with_domain(DomainConfig {
            psl_private_suffix_policy: PslPrivateSuffixPolicy::IcannOnly,
        }),
    );
    definitions
}

/// A resolved analyzer reference captured for a field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnalyzerBinding {
    /// Analyzer id.
    pub id: String,
    /// Analyzer semantic version.
    pub version: String,
    /// Canonical fingerprint.
    pub fingerprint: AnalyzerFingerprint,
}

impl AnalyzerBinding {
    fn from_definition(definition: &AnalyzerDefinition) -> Self {
        Self {
            id: definition.id().to_owned(),
            version: definition.version().to_owned(),
            fingerprint: definition.fingerprint(),
        }
    }
}

/// The index/search analyzer bindings for one schema field.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldAnalyzerBinding {
    /// Field name.
    pub field: String,
    /// Index-time analyzer binding, if configured.
    pub index: Option<AnalyzerBinding>,
    /// Search-time analyzer binding, if configured.
    pub search: Option<AnalyzerBinding>,
    /// Optional domain configuration (carried on the analyzer definition).
    pub domain: Option<DomainConfig>,
}

/// Resolved analyzer bindings for every field in a schema.
#[derive(Debug, Clone, Default)]
pub struct SchemaAnalyzerBindings {
    fields: BTreeMap<String, FieldAnalyzerBinding>,
}

impl SchemaAnalyzerBindings {
    /// Resolves analyzer/normalizer references from a schema against a registry.
    ///
    /// Unresolved names fail closed; a normalizer bound to a non-keyword field is rejected
    /// (defensive — the schema contract already prevents it).
    pub fn resolve(schema: &Schema, registry: &AnalyzerRegistry) -> Result<Self, AnalysisError> {
        let mut fields = BTreeMap::new();
        for definition in schema.fields() {
            let binding = resolve_field(definition, registry)?;
            fields.insert(definition.name.clone(), binding);
        }
        Ok(Self { fields })
    }

    #[must_use]
    pub fn get(&self, field: &str) -> Option<&FieldAnalyzerBinding> {
        self.fields.get(field)
    }

    pub fn iter(&self) -> impl Iterator<Item = &FieldAnalyzerBinding> {
        self.fields.values()
    }
}

fn resolve_field(
    definition: &FieldDefinition,
    registry: &AnalyzerRegistry,
) -> Result<FieldAnalyzerBinding, AnalysisError> {
    match definition.field_type {
        FieldType::Text => match &definition.analyzer {
            Some(name) => {
                let analyzer = registry.get(name)?;
                Ok(FieldAnalyzerBinding {
                    field: definition.name.clone(),
                    index: Some(AnalyzerBinding::from_definition(analyzer)),
                    search: Some(AnalyzerBinding::from_definition(analyzer)),
                    domain: analyzer.domain(),
                })
            }
            None => Ok(empty_binding(definition)),
        },
        FieldType::Keyword => match &definition.normalizer {
            Some(name) => {
                let analyzer = registry.get(name)?;
                if analyzer.index_pipeline().tokenizer() != TokenizerKind::Keyword
                    || analyzer.search_pipeline().tokenizer() != TokenizerKind::Keyword
                {
                    return Err(AnalysisError::InvalidConfiguration {
                        reason: format!(
                            "normalizer {name} must use the keyword tokenizer for field {}",
                            definition.name
                        ),
                    });
                }
                Ok(FieldAnalyzerBinding {
                    field: definition.name.clone(),
                    index: Some(AnalyzerBinding::from_definition(analyzer)),
                    search: Some(AnalyzerBinding::from_definition(analyzer)),
                    domain: analyzer.domain(),
                })
            }
            None => Ok(empty_binding(definition)),
        },
        _ => {
            if definition.analyzer.is_some() || definition.normalizer.is_some() {
                return Err(AnalysisError::InvalidConfiguration {
                    reason: format!(
                        "field {} has an analyzer/normalizer but is not Text/Keyword",
                        definition.name
                    ),
                });
            }
            Ok(empty_binding(definition))
        }
    }
}

fn empty_binding(definition: &FieldDefinition) -> FieldAnalyzerBinding {
    FieldAnalyzerBinding {
        field: definition.name.clone(),
        index: None,
        search: None,
        domain: None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::Cardinality;
    use crate::contract::schema::FieldOptions;

    fn text_field(name: &str, analyzer: Option<&str>) -> FieldDefinition {
        let mut field = FieldDefinition::new(
            name,
            FieldType::Text,
            Cardinality::Single,
            FieldOptions::indexed_stored(),
        );
        if let Some(analyzer) = analyzer {
            field = field.with_analyzer(analyzer);
        }
        field
    }

    #[test]
    fn builtin_registry_has_expected_entries() {
        let registry = AnalyzerRegistry::builtin();
        for name in [
            "keyword",
            "keyword_noop",
            "standard",
            "standard_folded",
            "english",
            "whitespace",
            "domain",
            "domain_icann",
        ] {
            assert!(registry.contains(name), "missing {name}");
        }
    }

    #[test]
    fn duplicate_registration_is_rejected() {
        let mut registry = AnalyzerRegistry::builtin();
        let duplicate = registry.get("standard").expect("standard").clone();
        assert!(registry.register(duplicate).is_err());
    }

    #[test]
    fn unknown_analyzer_fails_closed() {
        let registry = AnalyzerRegistry::builtin();
        assert!(matches!(
            registry.get("does-not-exist"),
            Err(AnalysisError::UnknownAnalyzer { .. })
        ));
    }

    #[test]
    fn version_mismatch_is_typed() {
        let registry = AnalyzerRegistry::builtin();
        assert!(matches!(
            registry.resolve_compatible("standard", "9.9.9"),
            Err(AnalysisError::AnalyzerVersionMismatch { .. })
        ));
    }

    #[test]
    fn schema_bindings_resolve_analyzer_and_normalizer() {
        let schema = Schema::new(
            vec![
                text_field("body", Some("english")),
                FieldDefinition::new(
                    "tag",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_normalizer("keyword"),
                text_field("raw", None),
            ],
            None,
        )
        .expect("schema");
        let registry = AnalyzerRegistry::builtin();
        let bindings = SchemaAnalyzerBindings::resolve(&schema, &registry).expect("bindings");
        assert!(bindings.get("body").expect("body").index.is_some());
        assert!(bindings.get("tag").expect("tag").index.is_some());
        assert!(bindings.get("raw").expect("raw").index.is_none());
    }

    #[test]
    fn schema_unknown_analyzer_fails() {
        let schema = Schema::new(vec![text_field("body", Some("nope"))], None).expect("schema");
        let registry = AnalyzerRegistry::builtin();
        assert!(SchemaAnalyzerBindings::resolve(&schema, &registry).is_err());
    }
}
