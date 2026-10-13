//! Resource budget contracts and effective-limit resolution (A20).

use std::collections::BTreeMap;

use super::error::{InvalidQueryReason, QueryError};

/// The stable kinds of bounded query resource.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum BudgetKind {
    JsonDepth,
    QueryDepth,
    Fields,
    ArrayElements,
    DocumentBytes,
    ResultWindow,
    Groups,
    GroupKeyFields,
    GroupExpansions,
    DistinctKeys,
    TermExpansion,
    MemoryBytes,
    Elapsed,
    ResponseBytes,
    QueriesPerBatch,
    BatchMemoryBytes,
    BatchResponseBytes,
    BatchAggregate,
}

impl BudgetKind {
    /// Whether this kind is a legal batch-wide aggregate limit (A20/A25).
    ///
    /// Aggregate limits cover total query count, work/memory and response size.
    /// Per-query kinds (result window, group cardinality, etc.) are not legal
    /// batch-level limits and must be carried on the individual query request.
    #[must_use]
    pub const fn is_batch_aggregate(self) -> bool {
        matches!(
            self,
            Self::QueriesPerBatch
                | Self::BatchMemoryBytes
                | Self::BatchResponseBytes
                | Self::BatchAggregate
        )
    }
}

/// A sparse set of positive, bounded budget values.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Budgets {
    limits: BTreeMap<BudgetKind, u64>,
}

impl Budgets {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Inserts a positive limit. A value of `0` is rejected.
    pub fn set(&mut self, kind: BudgetKind, value: u64) -> Result<(), QueryError> {
        if value == 0 {
            return Err(QueryError::InvalidQuery(InvalidQueryReason::ZeroBudget {
                kind,
            }));
        }
        self.limits.insert(kind, value);
        Ok(())
    }

    /// Builder form of [`Budgets::set`].
    pub fn with(mut self, kind: BudgetKind, value: u64) -> Result<Self, QueryError> {
        self.set(kind, value)?;
        Ok(self)
    }

    #[must_use]
    pub fn get(&self, kind: BudgetKind) -> Option<u64> {
        self.limits.get(&kind).copied()
    }

    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.limits.is_empty()
    }

    pub fn iter(&self) -> impl Iterator<Item = (BudgetKind, u64)> + '_ {
        self.limits.iter().map(|(kind, value)| (*kind, *value))
    }
}

/// Server, index, tenant hard ceilings, and published defaults (A20).
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BudgetPolicy {
    server: Budgets,
    index: Budgets,
    tenant: Budgets,
    defaults: Budgets,
}

impl BudgetPolicy {
    #[must_use]
    pub fn new(server: Budgets, index: Budgets, tenant: Budgets, defaults: Budgets) -> Self {
        Self {
            server,
            index,
            tenant,
            defaults,
        }
    }

    /// A policy with only server hard ceilings.
    #[must_use]
    pub fn with_server(server: Budgets) -> Self {
        Self {
            server,
            index: Budgets::new(),
            tenant: Budgets::new(),
            defaults: Budgets::new(),
        }
    }

    #[must_use]
    pub fn server(&self) -> &Budgets {
        &self.server
    }

    #[must_use]
    pub fn index(&self) -> &Budgets {
        &self.index
    }

    #[must_use]
    pub fn tenant(&self) -> &Budgets {
        &self.tenant
    }

    #[must_use]
    pub fn defaults(&self) -> &Budgets {
        &self.defaults
    }

    /// Resolves the effective limit for `kind`.
    ///
    /// The applicable hard ceiling is the minimum of the present server, index
    /// and tenant ceilings. The caller-requested (or published default) limit
    /// must not exceed that ceiling; it is rejected with
    /// [`QueryError::BudgetPolicyViolation`] and never silently clamped. When
    /// the caller omits a value and the published default exceeds the ceiling,
    /// the error reports the default as `requested`.
    pub fn effective(&self, kind: BudgetKind, requested: Option<u64>) -> Result<u64, QueryError> {
        let server = self.server.get(kind).ok_or(QueryError::InvalidQuery(
            InvalidQueryReason::UnconfiguredBudget { kind },
        ))?;
        let mut ceiling = server;
        if let Some(index) = self.index.get(kind) {
            ceiling = ceiling.min(index);
        }
        if let Some(tenant) = self.tenant.get(kind) {
            ceiling = ceiling.min(tenant);
        }
        match requested.or_else(|| self.defaults.get(kind)) {
            Some(value) => {
                if value == 0 {
                    return Err(QueryError::InvalidQuery(InvalidQueryReason::ZeroBudget {
                        kind,
                    }));
                }
                if value > ceiling {
                    return Err(QueryError::BudgetPolicyViolation {
                        kind,
                        requested: value,
                        ceiling,
                    });
                }
                Ok(value)
            }
            None => Ok(ceiling),
        }
    }
}

/// Multiply prospective per-document expansions using checked arithmetic.
///
/// Overflow is a typed budget failure, never a wrap-around or truncation.
pub fn checked_product(values: &[u64]) -> Result<u64, QueryError> {
    let mut product: u64 = 1;
    for value in values {
        product = product
            .checked_mul(*value)
            .ok_or(QueryError::BudgetExceeded {
                kind: BudgetKind::GroupExpansions,
            })?;
    }
    Ok(product)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn server() -> Budgets {
        Budgets::new()
            .with(BudgetKind::ResultWindow, 100)
            .unwrap()
            .with(BudgetKind::Groups, 50)
            .unwrap()
    }

    #[test]
    fn budgets_are_sparse_and_positive() {
        let mut budgets = Budgets::new();
        assert!(budgets.is_empty());
        assert!(Budgets::new().with(BudgetKind::Fields, 0).is_err());
        budgets.set(BudgetKind::Fields, 8).unwrap();
        assert_eq!(budgets.get(BudgetKind::Fields), Some(8));
        assert_eq!(budgets.get(BudgetKind::Groups), None);
        assert_eq!(budgets.iter().count(), 1);
    }

    #[test]
    fn effective_uses_strictest_ceiling_and_defaults() {
        let policy = BudgetPolicy::new(
            server(),
            Budgets::new().with(BudgetKind::ResultWindow, 60).unwrap(),
            Budgets::new().with(BudgetKind::ResultWindow, 40).unwrap(),
            Budgets::new().with(BudgetKind::ResultWindow, 10).unwrap(),
        );
        assert_eq!(policy.server().get(BudgetKind::Groups), Some(50));
        assert_eq!(policy.index().get(BudgetKind::ResultWindow), Some(60));
        assert_eq!(policy.tenant().get(BudgetKind::ResultWindow), Some(40));
        assert_eq!(policy.defaults().get(BudgetKind::ResultWindow), Some(10));
        assert_eq!(
            policy.effective(BudgetKind::ResultWindow, None).unwrap(),
            10
        );
        assert_eq!(
            policy
                .effective(BudgetKind::ResultWindow, Some(30))
                .unwrap(),
            30
        );
        assert!(matches!(
            policy.effective(BudgetKind::ResultWindow, Some(41)),
            Err(QueryError::BudgetPolicyViolation { .. })
        ));
        assert!(matches!(
            policy.effective(BudgetKind::ResultWindow, Some(0)),
            Err(QueryError::InvalidQuery(_))
        ));
        assert_eq!(policy.effective(BudgetKind::Groups, None).unwrap(), 50);
        assert!(matches!(
            policy.effective(BudgetKind::MemoryBytes, None),
            Err(QueryError::InvalidQuery(
                InvalidQueryReason::UnconfiguredBudget { .. }
            ))
        ));
    }

    #[test]
    fn checked_product_detects_overflow() {
        assert_eq!(checked_product(&[2, 3, 4]).unwrap(), 24);
        assert_eq!(checked_product(&[]).unwrap(), 1);
        assert!(matches!(
            checked_product(&[u64::MAX, 2]),
            Err(QueryError::BudgetExceeded {
                kind: BudgetKind::GroupExpansions
            })
        ));
    }
}

#[cfg(test)]
mod policy_hierarchy_tests {
    use super::*;

    const K: BudgetKind = BudgetKind::ResultWindow;

    fn one(value: u64) -> Budgets {
        Budgets::new().with(K, value).unwrap()
    }

    fn policy(
        server: Option<u64>,
        index: Option<u64>,
        tenant: Option<u64>,
        default: Option<u64>,
    ) -> BudgetPolicy {
        BudgetPolicy::new(
            server.map(one).unwrap_or_default(),
            index.map(one).unwrap_or_default(),
            tenant.map(one).unwrap_or_default(),
            default.map(one).unwrap_or_default(),
        )
    }

    #[test]
    fn b_pol01_server_only() {
        assert_eq!(
            policy(Some(100), None, None, None)
                .effective(K, None)
                .unwrap(),
            100
        );
    }

    #[test]
    fn b_pol02_index_stricter_than_server() {
        assert_eq!(
            policy(Some(100), Some(50), None, None)
                .effective(K, None)
                .unwrap(),
            50
        );
    }

    #[test]
    fn b_pol03_tenant_stricter_than_index() {
        assert_eq!(
            policy(Some(100), Some(50), Some(20), None)
                .effective(K, None)
                .unwrap(),
            20
        );
    }

    #[test]
    fn b_pol04_server_stricter_than_both() {
        assert_eq!(
            policy(Some(10), Some(50), Some(20), None)
                .effective(K, None)
                .unwrap(),
            10
        );
    }

    #[test]
    fn b_pol05_request_at_strictest_ceiling_accepted() {
        let policy = policy(Some(100), Some(50), Some(20), None);
        assert_eq!(policy.effective(K, Some(20)).unwrap(), 20);
    }

    #[test]
    fn b_pol06_request_above_ceiling_rejected_not_clamped() {
        let policy = policy(Some(100), Some(50), Some(20), None);
        assert!(matches!(
            policy.effective(K, Some(21)),
            Err(QueryError::BudgetPolicyViolation {
                requested: 21,
                ceiling: 20,
                ..
            })
        ));
    }

    #[test]
    fn b_pol07_defaults_respect_the_ceiling() {
        let under = policy(Some(100), Some(50), Some(20), Some(10));
        assert_eq!(under.effective(K, None).unwrap(), 10);
        let over = policy(Some(100), Some(50), Some(20), Some(30));
        assert!(matches!(
            over.effective(K, None),
            Err(QueryError::BudgetPolicyViolation {
                requested: 30,
                ceiling: 20,
                ..
            })
        ));
    }

    #[test]
    fn b_pol08_missing_server_and_zero_request_are_distinct_errors() {
        let no_server = policy(None, Some(50), None, None);
        assert!(matches!(
            no_server.effective(K, None),
            Err(QueryError::InvalidQuery(
                InvalidQueryReason::UnconfiguredBudget { .. }
            ))
        ));
        let configured = policy(Some(100), None, None, None);
        assert!(matches!(
            configured.effective(K, Some(0)),
            Err(QueryError::InvalidQuery(
                InvalidQueryReason::ZeroBudget { .. }
            ))
        ));
    }

    #[test]
    fn b_pol09_absent_index_and_tenant_preserve_server_semantics() {
        let with_server = BudgetPolicy::with_server(one(42));
        assert!(with_server.index().is_empty());
        assert!(with_server.tenant().is_empty());
        assert_eq!(with_server.effective(K, None).unwrap(), 42);
        assert_eq!(with_server.effective(K, Some(40)).unwrap(), 40);
    }

    #[test]
    fn batch_aggregate_kinds_are_classified() {
        assert!(BudgetKind::QueriesPerBatch.is_batch_aggregate());
        assert!(BudgetKind::BatchMemoryBytes.is_batch_aggregate());
        assert!(BudgetKind::BatchResponseBytes.is_batch_aggregate());
        assert!(BudgetKind::BatchAggregate.is_batch_aggregate());
        assert!(!BudgetKind::ResultWindow.is_batch_aggregate());
        assert!(!BudgetKind::Groups.is_batch_aggregate());
    }
}
