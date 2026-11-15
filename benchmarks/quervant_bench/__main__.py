"""Module entry point: ``python -m quervant_bench``."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    sys.exit(main())
