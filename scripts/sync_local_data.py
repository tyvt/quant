"""Run the foundation raw-data synchronizer from a source checkout."""

from __future__ import annotations

from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from turtle_quant.storage.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
