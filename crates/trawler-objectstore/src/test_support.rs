//! Minimal `std`-only executor for deterministic unit tests.
//!
//! PR 3 deliberately introduces no async runtime. Test futures here complete
//! without I/O waits, so a simple yield-based executor is sufficient.

use std::future::Future;
use std::task::{Context, Poll};

/// Drive `future` to completion on the current thread.
pub fn block_on<F: Future>(future: F) -> F::Output {
    let mut context = Context::from_waker(std::task::Waker::noop());
    let mut future = Box::pin(future);
    loop {
        match future.as_mut().poll(&mut context) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::yield_now(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn block_on_ready_and_pending() {
        assert_eq!(block_on(async { 1 + 1 }), 2);
        let mut polls = 0;
        let value = block_on(std::future::poll_fn(|cx| {
            polls += 1;
            if polls < 3 {
                cx.waker().wake_by_ref();
                Poll::Pending
            } else {
                Poll::Ready(7)
            }
        }));
        assert_eq!(value, 7);
    }
}
