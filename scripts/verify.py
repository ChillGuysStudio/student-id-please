#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13", "websockets>=13"]
# ///
"""Verify the running stack against the course grades. Run `uv run scripts/verify.py --help` for the options."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_suite.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
