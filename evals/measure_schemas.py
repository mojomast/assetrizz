#!/usr/bin/env python3
"""Measure registered tool schema tokens (o200k_base and cl100k_base)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugin"
if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))

from assetrizz_plugin.tools import measure_schemas  # noqa: E402


def main() -> int:
    counts = measure_schemas()
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
