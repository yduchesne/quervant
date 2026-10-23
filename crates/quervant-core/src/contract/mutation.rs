//! Atomic mutation batch contracts (QMA-001 / M1).
//!
//! These types describe an **ordered, all-or-nothing** mutation batch over
//! explicit logical keys. They validate shapes and types only: revision
//! allocation, admission, durability and replay are writer concerns.
//!
//! M2 activates the patch [`MutationAction::Update`] for exactly one explicit
//! logical key per command. M3 activates [`MutationTarget::Query`] **only** with
//! [`MutationAction::Delete`]; every other query action (update/replace/upsert)
//! remains reserved for M4 and is rejected with a typed
//! [`MutationRejection::UnsupportedTargetAction`] before any admission.

use super::document::{Document, DocumentKey, FieldValues, IdempotencyKey, MutationIntent};
use super::query::Query;

/// What a mutation command targets.
#[derive(Debug, Clone, PartialEq)]
pub enum MutationTarget {
    /// Exactly one logical key.
    Key(DocumentKey),
    /// An explicit, ordered list of logical keys.
    ///
    /// M1 rejects an empty list. The caller-supplied length is charged against
    /// `IndexLimits::max_batch_keys` **as raw occurrences, including
    /// duplicates**, before any processing; only after that admission-work
    /// ceiling passes is the list deduplicated in first-occurrence order for
    /// execution, with per-key outcomes reported in ascending [`DocumentKey`]
    /// order. Multiple unique keys are only valid for
    /// [`MutationAction::Delete`].
    Keys(Vec<DocumentKey>),
    /// A query selector.
    ///
    /// M3 admits this target only with [`MutationAction::Delete`]. The selector
    /// resolves every live logical key matching its query on one committed
    /// batch-initial snapshot. Other query actions remain reserved for M4.
    Query(QueryMutationSelector),
}

/// A query-based mutation selector.
///
/// There is deliberately **no** public selection token in v0.1 (M0 decision
/// D2). Selection is bound to the committed snapshot observed when the batch is
/// planned. `max_matches` must be greater than zero; the effective per-selector
/// bound is the minimum of this value, `IndexLimits::max_query_matches` and
/// `IndexLimits::max_batch_keys`. `expected_generation` is a committed-generation
/// assertion, not a request for a volatile view.
#[derive(Debug, Clone, PartialEq)]
pub struct QueryMutationSelector {
    /// The selector query.
    pub query: Query,
    /// Maximum number of matching documents the selector may resolve.
    pub max_matches: u64,
    /// Optional expected committed generation.
    pub expected_generation: Option<u64>,
}

/// What a mutation command does to its target keys.
#[derive(Debug, Clone, PartialEq)]
pub enum MutationAction {
    /// Create a document, rejecting a live key.
    Insert(Document),
    /// Create or replace a document for one logical key.
    Upsert(Document),
    /// Replace a live document, rejecting an absent or tombstoned key.
    Replace(Document),
    /// Partially update the live document for one explicit logical key.
    ///
    /// The patch is applied to a complete reconstructed source document and the
    /// result is validated, staged and reindexed as a whole. Query targets and
    /// multi-unique-key targets are rejected.
    Update(DocumentPatch),
    /// Tombstone the target keys.
    Delete,
}

/// A deterministic, ordered set of patch operations.
#[derive(Debug, Clone, PartialEq)]
pub struct DocumentPatch {
    /// Ordered operations, applied in order.
    pub operations: Vec<PatchOperation>,
}

/// One patch operation.
#[derive(Debug, Clone, PartialEq)]
pub enum PatchOperation {
    /// Set a field to an explicit value state.
    Set {
        /// The target field name.
        field: String,
        /// The new field state.
        values: FieldValues,
    },
    /// Remove a field.
    Unset {
        /// The target field name.
        field: String,
    },
}

/// A precondition evaluated against the prospective (staged) key state.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MutationPrecondition {
    /// No precondition.
    None,
    /// The key must be live.
    MustExist,
    /// The key must be absent or tombstoned.
    MustNotExist,
    /// The key's recorded revision must equal this value.
    ExpectedRevision(u64),
}

/// One ordered command in a [`MutationBatch`].
#[derive(Debug, Clone, PartialEq)]
pub struct MutationCommand {
    /// The command's target.
    pub target: MutationTarget,
    /// The command's action.
    pub action: MutationAction,
    /// The command's precondition.
    pub precondition: MutationPrecondition,
}

impl MutationCommand {
    /// Build a command with [`MutationPrecondition::None`].
    #[must_use]
    pub fn new(target: MutationTarget, action: MutationAction) -> Self {
        Self {
            target,
            action,
            precondition: MutationPrecondition::None,
        }
    }

    /// Replace the precondition.
    #[must_use]
    pub fn with_precondition(mut self, precondition: MutationPrecondition) -> Self {
        self.precondition = precondition;
        self
    }
}

/// An ordered, atomic mutation batch.
#[derive(Debug, Clone, PartialEq)]
pub struct MutationBatch {
    /// Commands in request order.
    pub commands: Vec<MutationCommand>,
    /// Optional idempotency token covering the whole batch.
    pub idempotency_key: Option<IdempotencyKey>,
}

impl MutationBatch {
    /// Build an untokened batch.
    #[must_use]
    pub fn new(commands: Vec<MutationCommand>) -> Self {
        Self {
            commands,
            idempotency_key: None,
        }
    }

    /// Attach a whole-batch idempotency token.
    #[must_use]
    pub fn with_idempotency_key(mut self, key: IdempotencyKey) -> Self {
        self.idempotency_key = Some(key);
        self
    }
}

/// The outcome for one logical key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationKeyOutcome {
    /// The logical key this outcome describes.
    pub key: DocumentKey,
    /// The intent that was applied.
    pub intent: MutationIntent,
    /// The assigned revision, if one was allocated.
    pub revision: Option<u64>,
    /// Whether this key outcome came from the durable replay ledger.
    pub replayed: bool,
}

/// The outcome for one command, in original command order.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationCommandOutcome {
    /// The command's ordinal in the request batch.
    pub command_index: u32,
    /// How many logical keys the command resolved to.
    pub matched: u64,
    /// Per-key outcomes in ascending [`DocumentKey`] order.
    pub keys: Vec<MutationKeyOutcome>,
}

/// The deterministic outcome of a whole batch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MutationBatchResponse {
    /// One outcome per command, in original command order.
    pub outcomes: Vec<MutationCommandOutcome>,
    /// Whether the whole response came from the durable replay ledger.
    pub replayed: bool,
}

/// Fixed per-response overhead in the durable response encoding:
/// a `u32` command count plus one replay flag byte.
pub const MUTATION_RESPONSE_HEADER_BYTES: u64 = 5;
/// Fixed per-command overhead: ordinal `u32`, matched `u64`, key count `u32`.
pub const MUTATION_RESPONSE_COMMAND_BYTES: u64 = 16;
/// Fixed per-key overhead: length prefix `u16`, intent, revision presence,
/// revision `u64`, replay flag.
pub const MUTATION_RESPONSE_KEY_FIXED_BYTES: u64 = 13;

impl MutationBatchResponse {
    /// Exact size of the canonical durable encoding, or `None` on overflow.
    ///
    /// This is the authoritative admission-time bound for
    /// `IndexLimits::max_batch_response_bytes`; it is not a saturation point.
    #[must_use]
    pub fn encoded_len(&self) -> Option<u64> {
        let mut total = MUTATION_RESPONSE_HEADER_BYTES;
        for command in &self.outcomes {
            total = total.checked_add(MUTATION_RESPONSE_COMMAND_BYTES)?;
            for outcome in &command.keys {
                total = total.checked_add(MUTATION_RESPONSE_KEY_FIXED_BYTES)?;
                total = total.checked_add(u64::try_from(outcome.key.as_str().len()).ok()?)?;
            }
        }
        Some(total)
    }

    /// Number of per-key outcomes across every command.
    #[must_use]
    pub fn key_outcome_count(&self) -> usize {
        self.outcomes.iter().map(|command| command.keys.len()).sum()
    }
}

/// A typed batch-mutation rejection.
///
/// These failures are always reported **before** any writer state changes.
#[derive(Debug, Clone, PartialEq)]
pub enum MutationRejection {
    /// The batch is structurally invalid (empty commands or empty key list).
    InvalidBatch {
        /// Bounded human-readable detail.
        detail: String,
    },
    /// A staged or committed key state does not satisfy the precondition.
    PreconditionFailed {
        /// The logical key.
        key: DocumentKey,
        /// The precondition that failed.
        expected: MutationPrecondition,
    },
    /// The target/action combination is not supported at all.
    ///
    /// The payload is boxed because both are large public contract types; the
    /// error type stays small enough to return by value cheaply.
    UnsupportedTargetAction {
        /// The requested target.
        target: Box<MutationTarget>,
        /// The requested action.
        action: Box<MutationAction>,
    },
    /// The action cannot be applied to the key's current state.
    ActionNotApplicable {
        /// The logical key.
        key: DocumentKey,
        /// The action that was rejected.
        action: Box<MutationAction>,
    },
    /// A query selector matched more distinct documents than the effective
    /// configured limit.
    MatchLimitExceeded {
        /// The configured limit.
        limit: u64,
        /// The number of matches observed.
        matched: u64,
    },
    /// A query upsert matched more than one document. Reserved for M4.
    AmbiguousQueryUpsert {
        /// The number of matches observed.
        matched: u64,
    },
    /// The selector's `expected_generation` does not match the committed
    /// generation (including an empty index with no committed generation).
    StaleSelection,
    /// A live target document could not be reconstructed losslessly.
    ///
    /// This is always reported before any writer state changes. `field` is
    /// present only for an unrecoverable schema field; raw document values are
    /// never exposed in the error.
    ReconstructionUnavailable {
        /// The logical key whose source could not be reconstructed.
        key: DocumentKey,
        /// The offending schema field, when the failure is field-specific.
        field: Option<String>,
        /// The classified reconstruction failure.
        reason: ReconstructionFailure,
    },
}

/// Why a physical source document could not be reconstructed losslessly.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReconstructionFailure {
    /// A schema field has no stored or columnar source (`indexed` only).
    UnrecoverableField,
    /// A required source section, column or pointer is absent.
    MissingSource,
    /// The physical or in-memory source does not match the expected key/shape.
    SourceMismatch,
}

impl MutationRejection {
    /// Build an [`Self::UnsupportedTargetAction`] rejection.
    #[must_use]
    pub fn unsupported_target_action(target: MutationTarget, action: MutationAction) -> Self {
        Self::UnsupportedTargetAction {
            target: Box::new(target),
            action: Box::new(action),
        }
    }

    /// Build an [`Self::ActionNotApplicable`] rejection.
    #[must_use]
    pub fn action_not_applicable(key: DocumentKey, action: MutationAction) -> Self {
        Self::ActionNotApplicable {
            key,
            action: Box::new(action),
        }
    }

    /// Build a [`Self::ReconstructionUnavailable`] rejection.
    #[must_use]
    pub fn reconstruction_unavailable(
        key: DocumentKey,
        field: Option<String>,
        reason: ReconstructionFailure,
    ) -> Self {
        Self::ReconstructionUnavailable { key, field, reason }
    }
}

impl std::fmt::Display for MutationRejection {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::InvalidBatch { detail } => write!(f, "invalid mutation batch: {detail}"),
            Self::PreconditionFailed { key, expected } => {
                write!(
                    f,
                    "mutation precondition failed for key {key}: {expected:?}"
                )
            }
            Self::UnsupportedTargetAction { target, action } => {
                write!(
                    f,
                    "unsupported mutation target/action: {target:?} / {action:?}"
                )
            }
            Self::ActionNotApplicable { key, action } => {
                write!(f, "mutation action {action:?} not applicable to key {key}")
            }
            Self::MatchLimitExceeded { limit, matched } => {
                write!(
                    f,
                    "query mutation match limit exceeded: {matched} > {limit}"
                )
            }
            Self::AmbiguousQueryUpsert { matched } => {
                write!(f, "query upsert is ambiguous: {matched} matches")
            }
            Self::StaleSelection => f.write_str("mutation selection is stale"),
            Self::ReconstructionUnavailable { key, field, reason } => match field {
                Some(field) => write!(
                    f,
                    "document reconstruction unavailable for key {key} field {field}: {reason:?}"
                ),
                None => write!(
                    f,
                    "document reconstruction unavailable for key {key}: {reason:?}"
                ),
            },
        }
    }
}

impl std::error::Error for MutationRejection {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::value::FieldValue;

    fn key(value: &str) -> DocumentKey {
        DocumentKey::new(value).expect("key")
    }

    fn action(value: &str) -> MutationAction {
        MutationAction::Upsert(Document::new(key(value)))
    }

    #[test]
    fn batch_shape_is_constructible_and_comparable() {
        let batch = MutationBatch::new(vec![
            MutationCommand::new(MutationTarget::Key(key("a")), action("a"))
                .with_precondition(MutationPrecondition::MustExist),
            MutationCommand::new(
                MutationTarget::Keys(vec![key("b"), key("c")]),
                MutationAction::Delete,
            ),
        ])
        .with_idempotency_key(IdempotencyKey::new("tok").expect("token"));
        assert_eq!(batch.commands.len(), 2);
        assert_eq!(
            batch.commands[0].precondition,
            MutationPrecondition::MustExist
        );
        assert_eq!(batch.clone(), batch);
        assert!(batch.idempotency_key.is_some());

        let other = MutationBatch::new(vec![MutationCommand::new(
            MutationTarget::Key(key("a")),
            action("a"),
        )]);
        assert_ne!(batch, other);
    }

    #[test]
    fn targets_are_distinct_by_shape() {
        let single = MutationTarget::Key(key("a"));
        let listed = MutationTarget::Keys(vec![key("a")]);
        assert_ne!(single, listed);
        let selector = MutationTarget::Query(QueryMutationSelector {
            query: Query::MatchAll,
            max_matches: 1,
            expected_generation: Some(3),
        });
        assert_ne!(single, selector);
    }

    #[test]
    fn patch_contract_is_ordered_and_five_state() {
        let patch = DocumentPatch {
            operations: vec![
                PatchOperation::Set {
                    field: "a".to_owned(),
                    values: FieldValues::Single(FieldValue::I64(1)),
                },
                PatchOperation::Set {
                    field: "a".to_owned(),
                    values: FieldValues::Absent,
                },
                PatchOperation::Unset {
                    field: "b".to_owned(),
                },
            ],
        };
        assert_eq!(patch.operations.len(), 3);
        assert_ne!(patch.operations[0], patch.operations[1]);
    }

    #[test]
    fn response_encoded_len_matches_arithmetic() {
        let response = MutationBatchResponse {
            outcomes: vec![MutationCommandOutcome {
                command_index: 0,
                matched: 2,
                keys: vec![
                    MutationKeyOutcome {
                        key: key("a"),
                        intent: MutationIntent::Delete,
                        revision: Some(1),
                        replayed: false,
                    },
                    MutationKeyOutcome {
                        key: key("bb"),
                        intent: MutationIntent::Delete,
                        revision: None,
                        replayed: false,
                    },
                ],
            }],
            replayed: false,
        };
        assert_eq!(response.key_outcome_count(), 2);
        assert_eq!(
            response.encoded_len(),
            Some(
                MUTATION_RESPONSE_HEADER_BYTES
                    + MUTATION_RESPONSE_COMMAND_BYTES
                    + 2 * MUTATION_RESPONSE_KEY_FIXED_BYTES
                    + 3
            )
        );
    }

    #[test]
    fn response_encoded_len_reports_overflow() {
        let huge = "k".repeat(DocumentKey::MAX_BYTES);
        let response = MutationBatchResponse {
            outcomes: vec![MutationCommandOutcome {
                command_index: 0,
                matched: 1,
                keys: vec![MutationKeyOutcome {
                    key: DocumentKey::new(huge).expect("key"),
                    intent: MutationIntent::Insert,
                    revision: Some(1),
                    replayed: false,
                }],
            }],
            replayed: false,
        };
        assert!(response.encoded_len().is_some());
    }

    #[test]
    fn rejection_display_is_bounded() {
        let errors = [
            MutationRejection::InvalidBatch {
                detail: "empty".to_owned(),
            },
            MutationRejection::PreconditionFailed {
                key: key("a"),
                expected: MutationPrecondition::MustExist,
            },
            MutationRejection::unsupported_target_action(
                MutationTarget::Key(key("a")),
                MutationAction::Delete,
            ),
            MutationRejection::action_not_applicable(key("a"), MutationAction::Delete),
            MutationRejection::MatchLimitExceeded {
                limit: 1,
                matched: 2,
            },
            MutationRejection::AmbiguousQueryUpsert { matched: 2 },
            MutationRejection::StaleSelection,
            MutationRejection::reconstruction_unavailable(
                key("a"),
                Some("title".to_owned()),
                ReconstructionFailure::UnrecoverableField,
            ),
            MutationRejection::reconstruction_unavailable(
                key("b"),
                None,
                ReconstructionFailure::MissingSource,
            ),
        ];
        for error in &errors {
            assert!(!error.to_string().is_empty());
        }
    }
}
