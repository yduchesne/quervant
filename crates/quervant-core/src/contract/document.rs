//! Logical document identity, values and mutation request shapes (A01/A02/A04).

use std::collections::BTreeMap;
use std::fmt;

use super::error::{DocumentError, QueryError, ValueError};
use super::value::FieldValue;

/// Field cardinality (A04).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Cardinality {
    Single,
    Multi,
}

/// The state of a field on a document (A04/A09).
#[derive(Debug, Clone, PartialEq)]
pub enum FieldValues {
    /// The field is not present.
    Absent,
    /// The field is present with an explicit null value.
    ExplicitNull,
    /// The field is present as a zero-element multi-value.
    Empty,
    /// Exactly one value.
    Single(FieldValue),
    /// One or more values.
    Multi(Vec<FieldValue>),
}

impl FieldValues {
    #[must_use]
    pub fn is_absent(&self) -> bool {
        matches!(self, Self::Absent)
    }

    #[must_use]
    pub fn is_explicit_null(&self) -> bool {
        matches!(self, Self::ExplicitNull)
    }

    #[must_use]
    pub fn is_empty_multi(&self) -> bool {
        matches!(self, Self::Empty)
    }

    /// Iterates the non-null scalar values, ignoring explicit null and absence.
    pub fn values(&self) -> impl Iterator<Item = &FieldValue> {
        let slice: &[FieldValue] = match self {
            Self::Single(value) => std::slice::from_ref(value),
            Self::Multi(values) => values,
            Self::Absent | Self::ExplicitNull | Self::Empty => &[],
        };
        slice.iter()
    }

    #[must_use]
    pub fn len(&self) -> usize {
        match self {
            Self::Single(_) => 1,
            Self::Multi(values) => values.len(),
            Self::Absent | Self::ExplicitNull | Self::Empty => 0,
        }
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn validate(&self, field: &str) -> Result<(), QueryError> {
        match self {
            Self::Single(value) => value.validate().map_err(|error| value_error(field, error)),
            Self::Multi(values) => {
                for value in values {
                    value
                        .validate()
                        .map_err(|error| value_error(field, error))?;
                }
                Ok(())
            }
            Self::Absent | Self::ExplicitNull | Self::Empty => Ok(()),
        }
    }

    pub(crate) fn approx_size(&self) -> usize {
        match self {
            Self::Single(value) => value.approx_size(),
            Self::Multi(values) => values.iter().map(FieldValue::approx_size).sum(),
            Self::Absent | Self::ExplicitNull | Self::Empty => 1,
        }
    }
}

fn value_error(field: &str, error: ValueError) -> QueryError {
    QueryError::document_value(field, error)
}

/// A stable, byte-exact logical document key (A01).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct DocumentKey(String);

impl DocumentKey {
    pub const MAX_BYTES: usize = 1024;

    pub fn new(value: impl Into<String>) -> Result<Self, QueryError> {
        let value = value.into();
        if value.is_empty() {
            return Err(QueryError::InvalidDocument(DocumentError::EmptyKey));
        }
        if value.len() > Self::MAX_BYTES {
            return Err(QueryError::InvalidDocument(DocumentError::KeyTooLong {
                len: value.len(),
            }));
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for DocumentKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// A document: a key plus validated field states.
#[derive(Debug, Clone, PartialEq)]
pub struct Document {
    key: DocumentKey,
    fields: BTreeMap<String, FieldValues>,
}

impl Document {
    #[must_use]
    pub fn new(key: DocumentKey) -> Self {
        Self {
            key,
            fields: BTreeMap::new(),
        }
    }

    /// Inserts a field state. `Absent` removes the field.
    pub fn insert(
        &mut self,
        field: impl Into<String>,
        values: FieldValues,
    ) -> Result<(), QueryError> {
        let field = field.into();
        values.validate(&field)?;
        if values.is_absent() {
            self.fields.remove(&field);
        } else {
            self.fields.insert(field, values);
        }
        Ok(())
    }

    #[must_use]
    pub fn key(&self) -> &DocumentKey {
        &self.key
    }

    #[must_use]
    pub fn get(&self, field: &str) -> FieldValues {
        self.fields
            .get(field)
            .cloned()
            .unwrap_or(FieldValues::Absent)
    }

    #[must_use]
    pub fn field_count(&self) -> usize {
        self.fields.len()
    }

    pub fn fields(&self) -> impl Iterator<Item = (&str, &FieldValues)> {
        self.fields
            .iter()
            .map(|(name, values)| (name.as_str(), values))
    }

    /// Approximate serialized size used for document-size budgets.
    #[must_use]
    pub fn approx_size(&self) -> usize {
        self.key.as_str().len()
            + self
                .fields
                .values()
                .map(FieldValues::approx_size)
                .sum::<usize>()
    }
}

/// An opaque, nonempty idempotency key (A02.1).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct IdempotencyKey(String);

impl IdempotencyKey {
    pub fn new(value: impl Into<String>) -> Result<Self, QueryError> {
        let value = value.into();
        if value.is_empty() {
            return Err(QueryError::InvalidDocument(DocumentError::EmptyKey));
        }
        Ok(Self(value))
    }

    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Mutation intent (A02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MutationIntent {
    Insert,
    Upsert,
    Delete,
}

/// A mutation request. Revision allocation and durability are writer concerns.
#[derive(Debug, Clone, PartialEq)]
pub struct MutationRequest {
    pub key: DocumentKey,
    pub intent: MutationIntent,
    pub document: Option<Document>,
    pub idempotency_key: Option<IdempotencyKey>,
}

impl MutationRequest {
    #[must_use]
    pub fn insert(document: Document) -> Self {
        Self {
            key: document.key().clone(),
            intent: MutationIntent::Insert,
            document: Some(document),
            idempotency_key: None,
        }
    }

    #[must_use]
    pub fn upsert(document: Document) -> Self {
        Self {
            key: document.key().clone(),
            intent: MutationIntent::Upsert,
            document: Some(document),
            idempotency_key: None,
        }
    }

    #[must_use]
    pub fn delete(key: DocumentKey) -> Self {
        Self {
            key,
            intent: MutationIntent::Delete,
            document: None,
            idempotency_key: None,
        }
    }

    #[must_use]
    pub fn with_idempotency_key(mut self, key: IdempotencyKey) -> Self {
        self.idempotency_key = Some(key);
        self
    }

    pub fn validate(&self) -> Result<(), QueryError> {
        match self.intent {
            MutationIntent::Insert | MutationIntent::Upsert => {
                let document = self
                    .document
                    .as_ref()
                    .ok_or(QueryError::InvalidDocument(DocumentError::MissingDocument))?;
                if document.key() != &self.key {
                    return Err(QueryError::InvalidDocument(DocumentError::TypeMismatch {
                        field: "document.key".into(),
                    }));
                }
                Ok(())
            }
            MutationIntent::Delete => {
                if self.document.is_some() {
                    return Err(QueryError::InvalidDocument(
                        DocumentError::UnexpectedDocument,
                    ));
                }
                Ok(())
            }
        }
    }
}

/// A mutation outcome shape. PR 2 does not allocate revisions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationResponse {
    pub key: DocumentKey,
    pub intent: MutationIntent,
    pub revision: Option<u64>,
    pub replayed: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn document_key_validation() {
        assert!(DocumentKey::new("").is_err());
        assert!(DocumentKey::new("a".repeat(DocumentKey::MAX_BYTES + 1)).is_err());
        assert_eq!(DocumentKey::new("doc-7").unwrap().as_str(), "doc-7");
    }

    #[test]
    fn field_states_are_distinct() {
        let mut document = Document::new(DocumentKey::new("d").unwrap());
        document.insert("a", FieldValues::ExplicitNull).unwrap();
        document.insert("b", FieldValues::Empty).unwrap();
        document
            .insert(
                "c",
                FieldValues::Multi(vec![FieldValue::I64(1), FieldValue::I64(1)]),
            )
            .unwrap();
        assert!(document.get("a").is_explicit_null());
        assert!(document.get("b").is_empty_multi());
        assert!(document.get("missing").is_absent());
        assert_eq!(document.field_count(), 3);
    }

    #[test]
    fn absent_insert_removes_field() {
        let mut document = Document::new(DocumentKey::new("d").unwrap());
        document
            .insert("a", FieldValues::Single(FieldValue::Bool(true)))
            .unwrap();
        document.insert("a", FieldValues::Absent).unwrap();
        assert!(document.get("a").is_absent());
    }

    #[test]
    fn non_finite_values_rejected() {
        let mut document = Document::new(DocumentKey::new("d").unwrap());
        assert!(
            document
                .insert("f", FieldValues::Single(FieldValue::F64(f64::NAN)))
                .is_err()
        );
    }

    #[test]
    fn mutation_shape_validation() {
        let document = Document::new(DocumentKey::new("d").unwrap());
        assert!(MutationRequest::insert(document.clone()).validate().is_ok());
        assert!(
            MutationRequest::delete(DocumentKey::new("d").unwrap())
                .validate()
                .is_ok()
        );
        assert!(
            MutationRequest::delete(DocumentKey::new("d").unwrap())
                .with_idempotency_key(IdempotencyKey::new("K").unwrap())
                .validate()
                .is_ok()
        );
        let mut mismatched = MutationRequest::insert(document);
        mismatched.key = DocumentKey::new("other").unwrap();
        assert!(mismatched.validate().is_err());
    }
}

#[cfg(test)]
mod coverage_tests {
    use super::*;

    #[test]
    fn idempotency_key_validation() {
        assert!(IdempotencyKey::new("").is_err());
        assert_eq!(IdempotencyKey::new("K").unwrap().as_str(), "K");
    }

    #[test]
    fn field_values_iteration_and_size() {
        let multi = FieldValues::Multi(vec![FieldValue::I64(1), FieldValue::I64(2)]);
        assert_eq!(multi.values().count(), 2);
        assert_eq!(multi.len(), 2);
        assert!(!multi.is_empty());
        assert!(!multi.is_absent());
        assert!(!multi.is_explicit_null());
        assert!(!multi.is_empty_multi());
        let single = FieldValues::Single(FieldValue::I64(1));
        assert_eq!(single.len(), 1);
        assert_eq!(FieldValues::Empty.len(), 0);
        assert!(FieldValues::Empty.is_empty());
        assert_eq!(FieldValues::ExplicitNull.approx_size(), 1);
        assert_eq!(
            FieldValues::Multi(vec![FieldValue::I64(1)]).approx_size(),
            8
        );
    }

    #[test]
    fn document_iteration_and_size() {
        let mut document = Document::new(DocumentKey::new("doc").unwrap());
        document
            .insert("a", FieldValues::Single(FieldValue::Bool(true)))
            .unwrap();
        document
            .insert("b", FieldValues::Single(FieldValue::I64(1)))
            .unwrap();
        assert_eq!(document.fields().count(), 2);
        assert!(document.approx_size() > 0);
        assert_eq!(document.key().as_str(), "doc");
    }

    #[test]
    fn mutation_shape_errors() {
        let key = DocumentKey::new("k").unwrap();
        let mut insert = MutationRequest::insert(Document::new(key.clone()));
        insert.document = None;
        assert!(matches!(
            insert.validate(),
            Err(QueryError::InvalidDocument(DocumentError::MissingDocument))
        ));
        let mut delete = MutationRequest::delete(key.clone());
        delete.document = Some(Document::new(key));
        assert!(matches!(
            delete.validate(),
            Err(QueryError::InvalidDocument(
                DocumentError::UnexpectedDocument
            ))
        ));
        assert_eq!(MutationIntent::Upsert, MutationIntent::Upsert);
        let response = MutationResponse {
            key: DocumentKey::new("k").unwrap(),
            intent: MutationIntent::Upsert,
            revision: Some(1),
            replayed: false,
        };
        assert_eq!(response.revision, Some(1));
    }
}
