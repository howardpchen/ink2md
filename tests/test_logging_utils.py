"""Tests for the shared logging utilities."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from ink2md.logging_utils import configure_logging


def _shutdown_logging() -> None:
    logging.shutdown()
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()


def test_configure_logging_creates_daily_log(tmp_path) -> None:
    log_dir = tmp_path / "log"
    configure_logging(verbose=False, log_dir=log_dir)
    logging.getLogger("ink2md.test").info("hello world")

    expected = log_dir / f"{date.today().isoformat()}.log"
    contents = expected.read_text(encoding="utf-8")
    assert "hello world" in contents

    _shutdown_logging()


def test_daily_logs_prune_after_seven_days(tmp_path) -> None:
    log_dir = tmp_path / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()
    for days_ago in range(10, 0, -1):
        old_day = today - timedelta(days=days_ago)
        (log_dir / f"{old_day.isoformat()}.log").write_text("old", encoding="utf-8")

    configure_logging(verbose=False, log_dir=log_dir)
    logging.getLogger("ink2md.test").info("trigger new file")

    existing = sorted(p.name for p in log_dir.glob("*.log"))
    assert len(existing) == 7
    assert existing[-1] == f"{today.isoformat()}.log"

    _shutdown_logging()
