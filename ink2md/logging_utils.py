"""Shared logging utilities for Ink2MD."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable


class DailyLogFileHandler(logging.Handler):
    """Write log records to a per-day file while pruning older logs."""

    terminator = "\n"

    def __init__(self, log_dir: Path, *, keep_days: int = 7) -> None:
        super().__init__()
        self.log_dir = log_dir
        self.keep_days = max(keep_days, 1)
        self._current_day: date | None = None
        self._stream = None

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - thin wrapper
        try:
            self._ensure_stream()
            msg = self.format(record)
            stream = self._stream
            if stream is None:
                return
            stream.write(msg + self.terminator)
            stream.flush()
        except Exception:  # noqa: PIE786 - standard logging pattern
            self.handleError(record)

    def close(self) -> None:  # pragma: no cover - trivial
        try:
            if self._stream:
                self._stream.close()
        finally:
            self._stream = None
            super().close()

    # Internal helpers -------------------------------------------------

    def _ensure_stream(self) -> None:
        today = datetime.now().date()
        if self._stream is None or self._current_day != today:
            self._open_stream(today)

    def _open_stream(self, for_day: date) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._purge_old_logs(for_day)
        path = self.log_dir / f"{for_day.isoformat()}.log"
        self._stream = path.open("a", encoding="utf-8")
        self._current_day = for_day

    def _purge_old_logs(self, today: date) -> None:
        cutoff = today - timedelta(days=self.keep_days - 1)
        for path in self._iter_log_files():
            try:
                file_day = date.fromisoformat(path.stem)
            except ValueError:
                continue
            if file_day < cutoff:
                try:
                    path.unlink()
                except OSError:
                    continue

    def _iter_log_files(self) -> Iterable[Path]:
        if not self.log_dir.exists():
            return []
        return sorted(self.log_dir.glob("*.log"))


def configure_logging(verbose: bool, log_dir: Path | None = None) -> None:
    """Initialise root logging for both CLI runs and the systemd service."""

    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    root.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    log_directory = log_dir or Path.cwd() / "log"
    file_handler = DailyLogFileHandler(log_directory)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    logging.captureWarnings(True)


__all__ = ["configure_logging", "DailyLogFileHandler"]

