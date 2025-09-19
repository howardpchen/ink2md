#!/usr/bin/env python3
"""Delete processor outputs older than a retention window."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional, Set


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove generated files older than the retention window.")
    parser.add_argument(
        "directory",
        type=Path,
        help="Output directory containing generated Markdown, PDFs, or rendered assets.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days of history to retain.",
    )
    parser.add_argument(
        "--extensions",
        type=str,
        nargs="*",
        help="Optional list of file extensions to target (for example .md .pdf .png). If omitted, all files are eligible.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recurse into subdirectories when purging.",
    )
    parser.add_argument(
        "--remove-empty-dirs",
        action="store_true",
        help="Remove directories left empty after deleting old files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan the purge without deleting files.",
    )
    return parser.parse_args()


def iter_files(directory: Path, recursive: bool) -> Iterable[Path]:
    if recursive:
        yield from (path for path in directory.rglob("*") if path.is_file())
    else:
        yield from (path for path in directory.iterdir() if path.is_file())


def should_consider(path: Path, extensions: Optional[Set[str]]) -> bool:
    if extensions is None:
        return True
    return path.suffix.lower() in extensions


def remove_empty_directories(root: Path) -> None:
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def main() -> int:
    args = parse_args()
    target_dir = args.directory.expanduser().resolve()
    if not target_dir.exists():
        sys.stderr.write(f"Directory does not exist: {target_dir}\n")
        return 1

    extensions = None
    if args.extensions:
        extensions = {ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in args.extensions}

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    removed_files = 0

    for path in iter_files(target_dir, args.recursive):
        if not should_consider(path, extensions):
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            continue
        if args.dry_run:
            print(f"Would remove {path}")
            removed_files += 1
            continue
        path.unlink()
        print(f"Removed {path}")
        removed_files += 1

    if args.remove_empty_dirs and not args.dry_run:
        remove_empty_directories(target_dir)

    print(
        "Finished purge. Files "
        + ("planned for removal" if args.dry_run else "removed")
        + f": {removed_files}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
