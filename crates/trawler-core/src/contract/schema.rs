//! Field definitions and schema validation (A05, A06, A13).

use std::collections::BTreeMap;

use super::budget::{BudgetKind, Budgets};
use super::document::{Cardinality, Document, FieldValues};
use super::error::{DocumentError, QueryError, SchemaError};
use super::value::{FieldType, FieldValue};

/// Per-field capability flags.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FieldOptions {
    pub indexed: bool,
    pub stored: bool,
    pub columnar: bool,
}

impl FieldOptions {
    #[must_use]
    pub const fn new(indexed: bool, stored: bool, columnar: bool) -> Self {
        Self {
            indexed,
            stored,
            columnar,
        }
    }

    #[must_use]
    pub const fn indexed_stored() -> Self {
        Self {
            indexed: true,
            stored: true,
            columnar: false,
        }
    }

    #[must_use]
    pub const fn is_useless(self) -> bool {
        !self.indexed && !self.stored && !self.columnar
    }
}

/// A versioned field descriptor (A05).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FieldDefinition {
    pub name: String,
    pub field_type: FieldType,
    pub cardinality: Cardinality,
    pub options: FieldOptions,
    pub analyzer: Option<String>,
    pub normalizer: Option<String>,
}

impl FieldDefinition {
    #[must_use]
    pub fn new(
        name: impl Into<String>,
        field_type: FieldType,
        cardinality: Cardinality,
        options: FieldOptions,
    ) -> Self {
        Self {
            name: name.into(),
            field_type,
            cardinality,
            options,
            analyzer: None,
            normalizer: None,
        }
    }

    #[must_use]
    pub fn with_analyzer(mut self, analyzer: impl Into<String>) -> Self {
        self.analyzer = Some(analyzer.into());
        self
    }

    #[must_use]
    pub fn with_normalizer(mut self, normalizer: impl Into<String>) -> Self {
        self.normalizer = Some(normalizer.into());
        self
    }

    fn validate(&self) -> Result<(), QueryError> {
        if self.options.is_useless() {
            return Err(SchemaError::UselessField {
                field: self.name.clone(),
            }
            .into());
        }
        if self.analyzer.is_some() && self.field_type != FieldType::Text {
            return Err(SchemaError::AnalyzerTypeMismatch {
                field: self.name.clone(),
            }
            .into());
        }
        if self.normalizer.is_some() && self.field_type != FieldType::Keyword {
            return Err(SchemaError::NormalizerTypeMismatch {
                field: self.name.clone(),
            }
            .into());
        }
        if self.options.columnar && matches!(self.field_type, FieldType::Text | FieldType::Json) {
            return Err(SchemaError::ColumnarTypeUnsupported {
                field: self.name.clone(),
            }
            .into());
        }
        Ok(())
    }
}

/// An index schema.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Schema {
    fields: BTreeMap<String, FieldDefinition>,
    primary_timestamp: Option<String>,
}

impl Schema {
    pub fn new(
        definitions: Vec<FieldDefinition>,
        primary_timestamp: Option<String>,
    ) -> Result<Self, QueryError> {
        let mut fields = BTreeMap::new();
        for definition in definitions {
            definition.validate()?;
            if fields.contains_key(&definition.name) {
                return Err(SchemaError::DuplicateField {
                    field: definition.name,
                }
                .into());
            }
            fields.insert(definition.name.clone(), definition);
        }
        if let Some(name) = &primary_timestamp {
            let definition = fields.get(name).ok_or_else(|| {
                QueryError::from(SchemaError::InvalidPrimaryTimestamp {
                    field: name.clone(),
                })
            })?;
            if definition.field_type != FieldType::Timestamp
                || definition.cardinality != Cardinality::Single
                || !definition.options.indexed
            {
                return Err(SchemaError::InvalidPrimaryTimestamp {
                    field: name.clone(),
                }
                .into());
            }
        }
        Ok(Self {
            fields,
            primary_timestamp,
        })
    }

    #[must_use]
    pub fn get(&self, name: &str) -> Option<&FieldDefinition> {
        self.fields.get(name)
    }

    pub fn require(&self, name: &str) -> Result<&FieldDefinition, QueryError> {
        self.fields.get(name).ok_or_else(|| {
            QueryError::InvalidDocument(DocumentError::UnknownField {
                field: name.to_owned(),
            })
        })
    }

    #[must_use]
    pub fn primary_timestamp(&self) -> Option<&str> {
        self.primary_timestamp.as_deref()
    }

    #[must_use]
    pub fn field_count(&self) -> usize {
        self.fields.len()
    }

    pub fn fields(&self) -> impl Iterator<Item = &FieldDefinition> {
        self.fields.values()
    }

    /// Validates a document against this schema and the applicable budgets.
    pub fn validate_document(
        &self,
        document: &Document,
        budgets: &Budgets,
    ) -> Result<(), QueryError> {
        if let Some(max) = budgets.get(BudgetKind::Fields)
            && u64::try_from(document.field_count()).unwrap_or(u64::MAX) > max
        {
            return Err(DocumentError::TooManyFields {
                count: document.field_count(),
            }
            .into());
        }
        if let Some(max) = budgets.get(BudgetKind::DocumentBytes)
            && u64::try_from(document.approx_size()).unwrap_or(u64::MAX) > max
        {
            return Err(DocumentError::DocumentTooLarge {
                bytes: document.approx_size(),
            }
            .into());
        }
        for (name, values) in document.fields() {
            let definition = self.require(name)?;
            self.validate_values(definition, name, values, budgets)?;
        }
        Ok(())
    }

    fn validate_values(
        &self,
        definition: &FieldDefinition,
        name: &str,
        values: &FieldValues,
        budgets: &Budgets,
    ) -> Result<(), QueryError> {
        if let Some(max) = budgets.get(BudgetKind::ArrayElements)
            && u64::try_from(values.len()).unwrap_or(u64::MAX) > max
        {
            return Err(DocumentError::ArrayTooLong {
                field: name.to_owned(),
                len: values.len(),
            }
            .into());
        }
        match values {
            FieldValues::Absent => Ok(()),
            FieldValues::ExplicitNull => Ok(()),
            FieldValues::Empty => {
                if definition.cardinality == Cardinality::Single {
                    Err(DocumentError::CardinalityMismatch {
                        field: name.to_owned(),
                    }
                    .into())
                } else {
                    Ok(())
                }
            }
            FieldValues::Single(value) => self.validate_value(definition, name, value, budgets),
            FieldValues::Multi(values) => {
                if definition.cardinality == Cardinality::Single && values.len() > 1 {
                    return Err(DocumentError::CardinalityMismatch {
                        field: name.to_owned(),
                    }
                    .into());
                }
                for value in values {
                    self.validate_value(definition, name, value, budgets)?;
                }
                Ok(())
            }
        }
    }

    fn validate_value(
        &self,
        definition: &FieldDefinition,
        name: &str,
        value: &FieldValue,
        budgets: &Budgets,
    ) -> Result<(), QueryError> {
        if value.field_type() != definition.field_type {
            return Err(DocumentError::TypeMismatch {
                field: name.to_owned(),
            }
            .into());
        }
        if let FieldValue::Json(json) = value {
            if let Some(max) = budgets.get(BudgetKind::JsonDepth)
                && u64::try_from(json.max_depth()).unwrap_or(u64::MAX) > max
            {
                return Err(DocumentError::JsonDepthExceeded {
                    field: name.to_owned(),
                }
                .into());
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::document::DocumentKey;

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "title",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                )
                .with_analyzer("en_default"),
                FieldDefinition::new(
                    "tags",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::new(true, true, true),
                )
                .with_normalizer("lowercase"),
                FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            Some("ts".into()),
        )
        .unwrap()
    }

    #[test]
    fn rejects_invalid_field_definitions() {
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "x",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::new(false, false, false)
                )],
                None
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![
                    FieldDefinition::new(
                        "a",
                        FieldType::I64,
                        Cardinality::Single,
                        FieldOptions::indexed_stored()
                    ),
                    FieldDefinition::new(
                        "a",
                        FieldType::I64,
                        Cardinality::Single,
                        FieldOptions::indexed_stored()
                    )
                ],
                None
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "t",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::indexed_stored()
                )],
                Some("missing".into())
            )
            .is_err()
        );
    }

    #[test]
    fn validates_documents() {
        let schema = schema();
        let budgets = Budgets::new()
            .with(BudgetKind::Fields, 8)
            .unwrap()
            .with(BudgetKind::ArrayElements, 4)
            .unwrap();
        let mut document = Document::new(DocumentKey::new("d1").unwrap());
        document
            .insert("title", FieldValues::Single(FieldValue::Text("a".into())))
            .unwrap();
        document
            .insert(
                "tags",
                FieldValues::Multi(vec![FieldValue::Keyword("x".into())]),
            )
            .unwrap();
        assert!(schema.validate_document(&document, &budgets).is_ok());

        let mut unknown = Document::new(DocumentKey::new("d2").unwrap());
        unknown
            .insert("nope", FieldValues::Single(FieldValue::Bool(true)))
            .unwrap();
        assert!(schema.validate_document(&unknown, &budgets).is_err());

        let mut wrong_type = Document::new(DocumentKey::new("d3").unwrap());
        wrong_type
            .insert("title", FieldValues::Single(FieldValue::I64(1)))
            .unwrap();
        assert!(schema.validate_document(&wrong_type, &budgets).is_err());

        let mut single_multi = Document::new(DocumentKey::new("d4").unwrap());
        single_multi
            .insert(
                "title",
                FieldValues::Multi(vec![
                    FieldValue::Text("a".into()),
                    FieldValue::Text("b".into()),
                ]),
            )
            .unwrap();
        assert!(schema.validate_document(&single_multi, &budgets).is_err());

        let mut too_many = Document::new(DocumentKey::new("d5").unwrap());
        too_many
            .insert(
                "tags",
                FieldValues::Multi(vec![
                    FieldValue::Keyword("a".into()),
                    FieldValue::Keyword("b".into()),
                    FieldValue::Keyword("c".into()),
                    FieldValue::Keyword("d".into()),
                    FieldValue::Keyword("e".into()),
                ]),
            )
            .unwrap();
        assert!(schema.validate_document(&too_many, &budgets).is_err());
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;
    use crate::contract::document::DocumentKey;
    use crate::contract::value::JsonValue;

    #[test]
    fn invalid_field_options_and_bindings() {
        assert!(
            Schema::new(
                vec![
                    FieldDefinition::new(
                        "k",
                        FieldType::Keyword,
                        Cardinality::Single,
                        FieldOptions::indexed_stored()
                    )
                    .with_analyzer("x")
                ],
                None
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![
                    FieldDefinition::new(
                        "t",
                        FieldType::Text,
                        Cardinality::Single,
                        FieldOptions::indexed_stored()
                    )
                    .with_normalizer("x")
                ],
                None
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "t",
                    FieldType::Text,
                    Cardinality::Single,
                    FieldOptions::new(true, false, true)
                )],
                None
            )
            .is_err()
        );
    }

    #[test]
    fn primary_timestamp_rules() {
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::new(false, true, false)
                )],
                Some("ts".into())
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "ts",
                    FieldType::I64,
                    Cardinality::Single,
                    FieldOptions::indexed_stored()
                )],
                Some("ts".into())
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Multi,
                    FieldOptions::indexed_stored()
                )],
                Some("ts".into())
            )
            .is_err()
        );
        assert!(
            Schema::new(
                vec![FieldDefinition::new(
                    "ts",
                    FieldType::Timestamp,
                    Cardinality::Single,
                    FieldOptions::indexed_stored()
                )],
                Some("other".into())
            )
            .is_err()
        );
    }

    fn schema() -> Schema {
        Schema::new(
            vec![
                FieldDefinition::new(
                    "host",
                    FieldType::Keyword,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "tags",
                    FieldType::Keyword,
                    Cardinality::Multi,
                    FieldOptions::indexed_stored(),
                ),
                FieldDefinition::new(
                    "body",
                    FieldType::Json,
                    Cardinality::Single,
                    FieldOptions::indexed_stored(),
                ),
            ],
            None,
        )
        .unwrap()
    }

    #[test]
    fn document_budget_and_state_boundaries() {
        let schema = schema();
        let budgets = Budgets::new()
            .with(BudgetKind::Fields, 2)
            .unwrap()
            .with(BudgetKind::DocumentBytes, 1000)
            .unwrap()
            .with(BudgetKind::JsonDepth, 1)
            .unwrap();

        let mut document = Document::new(DocumentKey::new("d").unwrap());
        document.insert("host", FieldValues::ExplicitNull).unwrap();
        document
            .insert(
                "tags",
                FieldValues::Multi(vec![FieldValue::Keyword("x".into())]),
            )
            .unwrap();
        assert!(schema.validate_document(&document, &budgets).is_ok());

        let mut empty_single = Document::new(DocumentKey::new("d").unwrap());
        empty_single.insert("host", FieldValues::Empty).unwrap();
        assert!(schema.validate_document(&empty_single, &budgets).is_err());

        let mut too_many = Document::new(DocumentKey::new("d").unwrap());
        too_many
            .insert("host", FieldValues::Single(FieldValue::Keyword("a".into())))
            .unwrap();
        too_many
            .insert("tags", FieldValues::Single(FieldValue::Keyword("b".into())))
            .unwrap();
        too_many
            .insert(
                "body",
                FieldValues::Single(FieldValue::Json(JsonValue::Null)),
            )
            .unwrap();
        assert!(schema.validate_document(&too_many, &budgets).is_err());

        let mut too_deep = Document::new(DocumentKey::new("d").unwrap());
        too_deep
            .insert(
                "body",
                FieldValues::Single(FieldValue::Json(JsonValue::Array(vec![JsonValue::Array(
                    vec![JsonValue::Null],
                )]))),
            )
            .unwrap();
        let depth_budgets = Budgets::new().with(BudgetKind::JsonDepth, 1).unwrap();
        assert!(schema.validate_document(&too_deep, &depth_budgets).is_err());

        let mut too_large = Document::new(DocumentKey::new("d").unwrap());
        too_large
            .insert(
                "host",
                FieldValues::Single(FieldValue::Keyword("x".repeat(2000))),
            )
            .unwrap();
        assert!(schema.validate_document(&too_large, &budgets).is_err());

        assert_eq!(schema.field_count(), 3);
        assert_eq!(schema.fields().count(), 3);
        assert!(schema.primary_timestamp().is_none());
        assert!(schema.require("host").is_ok());
        assert!(schema.require("missing").is_err());
    }

    #[test]
    fn cardinality_single_accepts_single_element_multi() {
        let schema = schema();
        let mut document = Document::new(DocumentKey::new("d").unwrap());
        document
            .insert(
                "host",
                FieldValues::Multi(vec![FieldValue::Keyword("a".into())]),
            )
            .unwrap();
        assert!(schema.validate_document(&document, &Budgets::new()).is_ok());
    }
}
