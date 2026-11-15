"""Quervant benchmarking contracts.

This package is the ``v0.1-bench`` contract foundation only. It parses, validates,
canonicalises and inspects declarative experiment definitions. It deliberately
contains **no acquisition engine**, no timer, no scheduler and no adapter
implementation. Real timed acquisition is reserved for BM-09.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
