#!/usr/bin/env python3
"""Rewrite only the version: line in plugin/plugin.yaml (and pyproject). Refuses duplicate keys."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "plugin.yaml"
PYPROJECT = ROOT / "pyproject.toml"


def _strict_load(text: str):
    from ruamel.yaml import YAML
    from ruamel.yaml.constructor import DuplicateKeyError

    yaml = YAML(typ="safe")
    yaml.allow_duplicate_keys = False
    try:
        return yaml.load(text), None
    except DuplicateKeyError as exc:
        return None, exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help='New SemVer, e.g. 0.1.1 (quotes optional)')
    args = parser.parse_args()
    version = args.version.strip().strip('"').strip("'")
    if not re.match(r"^\d+\.\d+\.\d+([.-][A-Za-z0-9.-]+)?$", version):
        print("version must look like 0.1.0", file=sys.stderr)
        return 2
    text = MANIFEST.read_text(encoding="utf-8")
    data, err = _strict_load(text)
    if err is not None:
        print(f"duplicate key in plugin.yaml: {err}", file=sys.stderr)
        return 1
    if not isinstance(data, dict) or data.get("name") != "assetrizz":
        print("plugin.yaml name must be assetrizz", file=sys.stderr)
        return 1
    if sum(1 for line in text.splitlines() if line.startswith("version:")) != 1:
        print("plugin.yaml must have exactly one version: line", file=sys.stderr)
        return 1
    updated, n = re.subn(
        r'^version:\s*"[^"]+"',
        f'version: "{version}"',
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        print("failed to rewrite plugin.yaml version:", file=sys.stderr)
        return 1
    MANIFEST.write_text(updated, encoding="utf-8")
    if PYPROJECT.is_file():
        py = PYPROJECT.read_text(encoding="utf-8")
        py2, pn = re.subn(
            r'^version\s*=\s*"[^"]+"',
            f'version = "{version}"',
            py,
            count=1,
            flags=re.M,
        )
        if pn != 1:
            print("failed to rewrite pyproject.toml version", file=sys.stderr)
            return 1
        PYPROJECT.write_text(py2, encoding="utf-8")
    init = ROOT / "assetrizz_plugin" / "__init__.py"
    if init.is_file():
        body = init.read_text(encoding="utf-8")
        body2, bn = re.subn(
            r'^__version__\s*=\s*"[^"]+"',
            f'__version__ = "{version}"',
            body,
            count=1,
            flags=re.M,
        )
        if bn == 1:
            init.write_text(body2, encoding="utf-8")
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
