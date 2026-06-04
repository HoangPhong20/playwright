"""Small thread-safe console logging helpers."""
from contextlib import contextmanager
import threading
from typing import Iterator, Optional


_print_lock = threading.Lock()
_state = threading.local()


def current_log_prefix() -> str:
    return getattr(_state, "prefix", "")


@contextmanager
def log_prefix(prefix: Optional[str]) -> Iterator[None]:
    previous = current_log_prefix()
    _state.prefix = prefix or ""
    try:
        yield
    finally:
        _state.prefix = previous


def log(message: str = "") -> None:
    prefix = current_log_prefix()
    line = f"[{prefix}] {message}" if prefix else message
    with _print_lock:
        print(line, flush=True)


def log_ignored_error(context: str, exc: Exception) -> None:
    error_text = str(exc).splitlines()[0].strip()
    if not error_text:
        error_text = type(exc).__name__
    log(f"{context}: ignored {type(exc).__name__}: {error_text}")
