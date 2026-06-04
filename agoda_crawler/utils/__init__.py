"""Shared utilities for crawler output and text cleanup."""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_JSONL_LOCKS: Dict[Path, threading.Lock] = {}
_JSONL_LOCKS_GUARD = threading.Lock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned if cleaned else None


def make_output_path(base_dir: str = "data") -> Path:
    today = datetime.now().date().isoformat()
    path = Path(base_dir) / f"agoda_hotels_{today}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def make_daily_output_path(base_dir: str, check_in: str) -> Path:
    path = Path(base_dir) / f"agoda_hotels_{check_in}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    resolved_path = path.resolve()
    with _JSONL_LOCKS_GUARD:
        lock = _JSONL_LOCKS.setdefault(resolved_path, threading.Lock())

    with lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def as_json(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=True)
