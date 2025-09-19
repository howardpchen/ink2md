#!/usr/bin/env python3
"""Health checks for the cloud-monitor-pdf2md processor."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate processor health based on state files and optional journal logs.")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("/var/lib/cloud-monitor/state.json"),
        help="Path to the processing state JSON file.",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=120,
        help="Maximum allowed age in minutes since the last processed document.",
    )
    parser.add_argument(
        "--journal-unit",
        type=str,
        help="Optional systemd unit name whose recent error logs should be displayed.",
    )
    parser.add_argument(
        "--journal-since",
        type=str,
        default="1 hour ago",
        help="journalctl --since window to inspect when --journal-unit is provided.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress informational output; only emit errors.",
    )
    return parser.parse_args()


def load_latest_event(state_path: Path) -> Tuple[str, datetime] | None:
    if not state_path.exists():
        return None

    with state_path.open("r", encoding="utf-8") as handle:
        payload: Dict[str, Any] = json.load(handle)

    processed = payload.get("processed", {})
    latest_event: Tuple[str, datetime] | None = None
    for document_id, metadata in processed.items():
        timestamp_raw = metadata.get("timestamp")
        if not isinstance(timestamp_raw, str):
            continue
        try:
            timestamp = datetime.fromisoformat(timestamp_raw)
        except ValueError:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if latest_event is None or timestamp > latest_event[1]:
            latest_event = (metadata.get("name", document_id), timestamp)
    return latest_event


def print_journal(unit: str, since: str) -> None:
    cmd = ["journalctl", "-u", unit, "--since", since, "--priority", "err"]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(f"Failed to read journal for {unit}: {result.stderr.strip()}\n")
        return
    if not result.stdout.strip():
        return
    sys.stdout.write(f"Recent journalctl entries for {unit} (priority err):\n{result.stdout}\n")


def main() -> int:
    args = parse_args()
    latest_event = load_latest_event(args.state_file)
    if latest_event is None:
        sys.stderr.write(f"No processed entries found in {args.state_file}.\n")
        return 2

    name, timestamp = latest_event
    age = datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)
    limit = timedelta(minutes=args.max_age)

    if not args.quiet:
        sys.stdout.write(
            f"Most recent document: {name}\n"
            f"Timestamp: {timestamp.isoformat()}\n"
            f"Age: {age.total_seconds() / 60:.1f} minutes\n"
            f"Threshold: {limit.total_seconds() / 60:.1f} minutes\n"
        )

    if age > limit:
        sys.stderr.write(
            "Last processed document is older than the permitted threshold.\n"
        )
        if args.journal_unit:
            print_journal(args.journal_unit, args.journal_since)
        return 2

    if args.journal_unit:
        print_journal(args.journal_unit, args.journal_since)

    return 0


if __name__ == "__main__":
    sys.exit(main())
