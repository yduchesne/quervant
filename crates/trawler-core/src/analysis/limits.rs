//! Bounded analysis limits (T07).
//!
//! The defaults are the approved hard ceilings. Callers may lower them but may not exceed
//! them without a separately approved extension; over-ceiling configuration is a typed error,
//! never a silent clamp.

use super::error::AnalysisError;

/// Hard ceiling for the number of bytes in a single source value (1 MiB).
pub const HARD_MAX_INPUT_BYTES: u64 = 1 << 20;
/// Hard ceiling for emitted tokens **per source value** (100,000).
pub const HARD_MAX_TOKENS: u64 = 100_000;
/// Hard ceiling for one emitted term (4 KiB).
pub const HARD_MAX_TERM_BYTES: u64 = 4 * 1024;
/// Hard ceiling for deterministic work units in one analysis call.
pub const HARD_MAX_WORK_UNITS: u64 = 8_000_000;
/// Cancellation is polled at most every this many consumed work units.
pub const CANCELLATION_POLL_INTERVAL: u64 = 1024;

/// Concrete, enforceable analysis limits.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AnalysisLimits {
    max_input_bytes: u64,
    max_tokens: u64,
    max_term_bytes: u64,
    max_work_units: u64,
}

impl Default for AnalysisLimits {
    fn default() -> Self {
        Self {
            max_input_bytes: HARD_MAX_INPUT_BYTES,
            max_tokens: HARD_MAX_TOKENS,
            max_term_bytes: HARD_MAX_TERM_BYTES,
            max_work_units: HARD_MAX_WORK_UNITS,
        }
    }
}

impl AnalysisLimits {
    /// Builds limits, rejecting any value above the approved hard ceiling.
    pub fn new(
        max_input_bytes: u64,
        max_tokens: u64,
        max_term_bytes: u64,
        max_work_units: u64,
    ) -> Result<Self, AnalysisError> {
        let limits = Self {
            max_input_bytes,
            max_tokens,
            max_term_bytes,
            max_work_units,
        };
        limits.validate()?;
        Ok(limits)
    }

    fn validate(&self) -> Result<(), AnalysisError> {
        check_ceiling(
            "max_input_bytes",
            self.max_input_bytes,
            HARD_MAX_INPUT_BYTES,
        )?;
        check_ceiling("max_tokens", self.max_tokens, HARD_MAX_TOKENS)?;
        check_ceiling("max_term_bytes", self.max_term_bytes, HARD_MAX_TERM_BYTES)?;
        check_ceiling("max_work_units", self.max_work_units, HARD_MAX_WORK_UNITS)
    }

    /// Lowers the per-value input-byte budget.
    pub fn with_max_input_bytes(mut self, value: u64) -> Result<Self, AnalysisError> {
        check_ceiling("max_input_bytes", value, HARD_MAX_INPUT_BYTES)?;
        self.max_input_bytes = value;
        Ok(self)
    }

    /// Lowers the **per-value** emitted-token budget.
    pub fn with_max_tokens(mut self, value: u64) -> Result<Self, AnalysisError> {
        check_ceiling("max_tokens", value, HARD_MAX_TOKENS)?;
        self.max_tokens = value;
        Ok(self)
    }

    /// Lowers the per-term byte budget.
    pub fn with_max_term_bytes(mut self, value: u64) -> Result<Self, AnalysisError> {
        check_ceiling("max_term_bytes", value, HARD_MAX_TERM_BYTES)?;
        self.max_term_bytes = value;
        Ok(self)
    }

    /// Lowers the deterministic work budget.
    pub fn with_max_work_units(mut self, value: u64) -> Result<Self, AnalysisError> {
        check_ceiling("max_work_units", value, HARD_MAX_WORK_UNITS)?;
        self.max_work_units = value;
        Ok(self)
    }

    #[must_use]
    pub const fn max_input_bytes(&self) -> u64 {
        self.max_input_bytes
    }

    #[must_use]
    pub const fn max_tokens(&self) -> u64 {
        self.max_tokens
    }

    #[must_use]
    pub const fn max_term_bytes(&self) -> u64 {
        self.max_term_bytes
    }

    #[must_use]
    pub const fn max_work_units(&self) -> u64 {
        self.max_work_units
    }
}

fn check_ceiling(name: &str, value: u64, ceiling: u64) -> Result<(), AnalysisError> {
    if value == 0 {
        return Err(AnalysisError::InvalidConfiguration {
            reason: format!("{name} must be greater than zero"),
        });
    }
    if value > ceiling {
        return Err(AnalysisError::InvalidConfiguration {
            reason: format!("{name}={value} exceeds approved ceiling {ceiling}"),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_are_the_hard_ceilings() {
        let limits = AnalysisLimits::default();
        assert_eq!(limits.max_input_bytes(), HARD_MAX_INPUT_BYTES);
        assert_eq!(limits.max_tokens(), HARD_MAX_TOKENS);
        assert_eq!(limits.max_term_bytes(), HARD_MAX_TERM_BYTES);
        assert_eq!(limits.max_work_units(), HARD_MAX_WORK_UNITS);
    }

    #[test]
    fn lowering_is_allowed_and_zero_is_rejected() {
        let lowered = AnalysisLimits::default()
            .with_max_tokens(10)
            .expect("lowering tokens is allowed");
        assert_eq!(lowered.max_tokens(), 10);
        assert!(lowered.with_max_tokens(0).is_err());
    }

    #[test]
    fn exceeding_ceiling_is_rejected() {
        assert!(AnalysisLimits::new(HARD_MAX_INPUT_BYTES + 1, 1, 1, 1).is_err());
        assert!(AnalysisLimits::new(1, HARD_MAX_TOKENS + 1, 1, 1).is_err());
        assert!(AnalysisLimits::new(1, 1, HARD_MAX_TERM_BYTES + 1, 1).is_err());
        assert!(AnalysisLimits::new(1, 1, 1, HARD_MAX_WORK_UNITS + 1).is_err());
    }
}
