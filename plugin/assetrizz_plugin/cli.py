"""User-facing CLI for local library install, status, and removal.

This is not a Hermes tool. Run it yourself:

    python -m assetrizz_plugin.cli status
    python -m assetrizz_plugin.cli download --style pixel_32
    python -m assetrizz_plugin.cli download --all --yes
    python -m assetrizz_plugin.cli cancel
    python -m assetrizz_plugin.cli remove --yes
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _print(data: dict) -> int:
    ok = data.get("ok", True)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    print(text)
    return 0 if ok and data.get("status") not in {"error"} else 1


def _add_dest(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dest",
        help="Directory for the local library (default: local_library_dir setting or the plugin data library/ folder).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m assetrizz_plugin.cli",
        description=(
            "Download or remove a local Assetrizz library. This command is for you to run; "
            "the agent cannot trigger a bulk download as a tool."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="Show asset mode, pack sizes, disk usage, and any download job.")

    download = sub.add_parser("download", help="Download the full library or selected style packs (SHA-256 verified).")
    download.add_argument("--style", action="append", dest="styles", default=[], help="Style pack to download (repeatable).")
    download.add_argument("--all", action="store_true", help="Download every style pack (~1.6 GB).")
    download.add_argument(
        "--yes",
        action="store_true",
        help="Confirm a large download without an interactive prompt.",
    )
    _add_dest(download)

    sub.add_parser("cancel", help="Cancel a running pane/CLI download. Verified files are kept so you can resume.")

    remove = sub.add_parser("remove", help="Delete the local library directory (confirmation required).")
    remove.add_argument("--yes", action="store_true", help="Confirm deletion.")
    _add_dest(remove)

    cache = sub.add_parser("clear-cache", help="Delete on-demand cached PNGs (confirmation required).")
    cache.add_argument("--yes", action="store_true", help="Confirm cache deletion.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from assetrizz_plugin import install
    from assetrizz_plugin.config import local_library_dir

    if args.cmd == "status":
        return _print(install.library_status())

    if args.cmd == "download":
        packs = ["*"] if args.all else list(args.styles or [])
        if not packs:
            parser.error("Pass --all or one or more --style NAME flags.")
        estimate = install.estimate_packs(packs)
        if (estimate["all"] or estimate["bytes"] >= 50 * 1024 * 1024) and not args.yes and sys.stdin.isatty():
            prompt = (
                f"Download {estimate['count']} assets (~{estimate['label']}) "
                f"into {args.dest or local_library_dir()}? [y/N] "
            )
            answer = input(prompt)
            if answer.strip().lower() not in {"y", "yes"}:
                print("Cancelled.")
                return 1
        elif (estimate["all"] or estimate["bytes"] >= 50 * 1024 * 1024) and not args.yes:
            parser.error("This is a large download. Re-run with --yes to confirm.")
        dest = Path(args.dest).expanduser() if args.dest else None
        try:
            result = install.run_download(packs, dest=dest)
        except Exception as exc:
            return _print(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": getattr(exc, "code", "fetch_failed"),
                    "fix": getattr(exc, "fix", ""),
                }
            )
        return _print(result)

    if args.cmd == "cancel":
        return _print(install.cancel_download())

    if args.cmd == "remove":
        if not args.yes:
            parser.error("Deletion needs confirmation. Re-run with --yes.")
        dest = Path(args.dest).expanduser() if args.dest else None
        try:
            return _print(install.remove_local_library(confirm=True, dest=dest))
        except Exception as exc:
            return _print(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": getattr(exc, "code", "path_escape"),
                    "fix": getattr(exc, "fix", ""),
                }
            )

    if args.cmd == "clear-cache":
        if not args.yes:
            parser.error("Clearing the cache needs confirmation. Re-run with --yes.")
        try:
            return _print(install.clear_cache(confirm=True))
        except Exception as exc:
            return _print(
                {
                    "ok": False,
                    "error": str(exc),
                    "code": getattr(exc, "code", "path_escape"),
                    "fix": getattr(exc, "fix", ""),
                }
            )

    parser.error(f"Unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
