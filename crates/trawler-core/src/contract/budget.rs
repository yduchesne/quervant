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

/// Server hard ceilings, optional index/tenant ceilings, and published defaults.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct BudgetPolicy {
    server: Budgets,
    tenant: Budgets,
    defaults: Budgets,
}

impl BudgetPolicy {
    #[must_use]
    pub fn new(server: Budgets, tenant: Budgets, defaults: Budgets) -> Self {
        Self {
            server,
            tenant,
            defaults,
        }
    }

    /// A policy with only server hard ceilings.
    #[must_use]
    pub fn with_server(server: Budgets) -> Self {
        Self {
            server,
            tenant: Budgets::new(),
            defaults: Budgets::new(),
        }
    }

    #[must_use]
    pub fn server(&self) -> &Budgets {
        &self.server
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
    /// The effective limit is the minimum of the server hard ceiling, the
    /// applicable index/tenant ceiling and the caller-requested-or-default
    /// limit. A caller request above the ceiling is rejected with
    /// [`QueryError::BudgetPolicyViolation`] and never silently clamped.
    pub fn effective(&self, kind: BudgetKind, requested: Option<u64>) -> Result<u64, QueryError> {
        let server = self.server.get(kind).ok_or(QueryError::InvalidQuery(
            InvalidQueryReason::UnconfiguredBudget { kind },
        ))?;
        let ceiling = match self.tenant.get(kind) {
            Some(tenant) => server.min(tenant),
            None => server,
        };
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
            Budgets::new().with(BudgetKind::ResultWindow, 40).unwrap(),
            Budgets::new().with(BudgetKind::ResultWindow, 10).unwrap(),
        );
        assert_eq!(policy.server().get(BudgetKind::Groups), Some(50));
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
