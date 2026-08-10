"""Local content-addressed raw-object store for development and tests."""

from __future__ import annotations

import hashlib
from pathlib import Path


class LocalRawObjectStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    def put(self, payload: bytes) -> str:
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        digest = hashlib.sha256(payload).hexdigest()
        path = self._root / "sha256" / digest
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != payload:
                raise RuntimeError("content-addressed object mismatch")
            return path.as_uri()
        with path.open("xb") as stream:
            stream.write(payload)
        return path.as_uri()
