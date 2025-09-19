"""Processing state tracking utilities."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict


@dataclass(slots=True)
class ProcessingState:
    """Persist IDs of documents that have already been processed."""

    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = self.path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_state({"processed": {}})

    def _read_state(self) -> Dict[str, Dict[str, str]]:
        with self.path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_state(self, state: Dict[str, Dict[str, str]]) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
        tmp_path.replace(self.path)

    def has_processed(self, document_id: str) -> bool:
        with self._lock:
            state = self._read_state()
            return document_id in state.get("processed", {})

    def mark_processed(self, document_id: str, *, name: str | None = None) -> None:
        with self._lock:
            state = self._read_state()
            processed = state.setdefault("processed", {})
            processed[document_id] = {
                "name": name or document_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._write_state(state)


__all__ = ["ProcessingState"]
