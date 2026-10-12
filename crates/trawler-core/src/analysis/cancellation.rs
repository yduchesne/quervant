//! Cooperative cancellation for bounded analysis (T07, V4).

use std::sync::atomic::{AtomicBool, Ordering};

/// A cooperative cancellation source.
///
/// Implementations must be cheap to poll and safe to share; analysis polls at most every
/// [`super::limits::CANCELLATION_POLL_INTERVAL`] work units.
pub trait Cancellation {
    /// Returns `true` once analysis must stop.
    fn is_cancelled(&self) -> bool;
}

/// A canceller that never cancels.
#[derive(Debug, Clone, Copy, Default)]
pub struct NeverCancel;

impl Cancellation for NeverCancel {
    fn is_cancelled(&self) -> bool {
        false
    }
}

/// A thread-safe cancellation flag backed by an atomic boolean.
#[derive(Debug, Default)]
pub struct CancellationFlag {
    cancelled: AtomicBool,
}

impl CancellationFlag {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Requests cancellation. Idempotent and lock-free.
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
    }

    #[must_use]
    pub fn is_cancelled_flag(&self) -> bool {
        self.cancelled.load(Ordering::SeqCst)
    }
}

impl Cancellation for CancellationFlag {
    fn is_cancelled(&self) -> bool {
        self.is_cancelled_flag()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn never_cancel_never_cancels() {
        assert!(!NeverCancel.is_cancelled());
    }

    #[test]
    fn flag_transitions_once_cancelled() {
        let flag = CancellationFlag::new();
        assert!(!flag.is_cancelled());
        flag.cancel();
        assert!(flag.is_cancelled());
        flag.cancel();
        assert!(flag.is_cancelled());
    }
}
