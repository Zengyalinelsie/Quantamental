"""Structured logging and request/run correlation context."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)


@contextmanager
def log_context(*, trace_id: str | None = None, run_id: str | None = None) -> Iterator[None]:
    trace_token = _trace_id.set(trace_id)
    run_token = _run_id.set(run_id)
    try:
        yield
    finally:
        _trace_id.reset(trace_token)
        _run_id.reset(run_token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if trace_id := _trace_id.get():
            payload["trace_id"] = trace_id
        if run_id := _run_id.get():
            payload["run_id"] = run_id
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
