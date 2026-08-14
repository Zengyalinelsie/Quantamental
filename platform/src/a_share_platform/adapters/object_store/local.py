"""Local content-addressed raw-object store for development and tests."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path
from urllib.parse import unquote, urlparse

from a_share_platform.domain.governance import Artifact
from a_share_platform.ports.governance import (
    ArtifactIntegrityError,
    ArtifactObjectUnavailable,
)


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
        try:
            with path.open("xb") as stream:
                stream.write(payload)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise RuntimeError("content-addressed object mismatch") from None
        return path.as_uri()


class LocalArtifactReader:
    """Read only registered content-addressed objects below one private root."""

    def __init__(self, root: Path, *, max_bytes: int = 16 * 1024 * 1024) -> None:
        self._root = Path(root).resolve()
        if self._root == Path(self._root.anchor):
            raise ValueError("Artifact root must not be a filesystem root")
        if self._root.exists() and not self._root.is_dir():
            raise ValueError("Artifact root must be a directory")
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._max_bytes = max_bytes

    def read(self, value: Artifact) -> bytes:
        if not isinstance(value, Artifact):
            raise TypeError("value must be an Artifact")
        parsed = urlparse(value.storage_uri)
        if parsed.scheme != "file" or parsed.netloc or parsed.query or parsed.fragment:
            raise ArtifactIntegrityError(
                f"Artifact storage URI is not a controlled local object: {value.artifact_id}"
            )
        digest = value.content_hash.removeprefix("sha256:")
        path = Path(unquote(parsed.path))
        try:
            relative = path.relative_to(self._root)
        except ValueError as error:
            raise ArtifactIntegrityError(
                f"Artifact storage path escapes the controlled root: {value.artifact_id}"
            ) from error
        if relative.parts != ("sha256", digest):
            raise ArtifactIntegrityError(
                f"Artifact storage path is not content-addressed: {value.artifact_id}"
            )
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | no_follow
        file_flags = os.O_RDONLY | os.O_NONBLOCK | no_follow
        descriptors: list[int] = []
        try:
            root_descriptor = os.open(self._root, directory_flags)
            descriptors.append(root_descriptor)
            sha_descriptor = os.open(
                "sha256",
                directory_flags,
                dir_fd=root_descriptor,
            )
            descriptors.append(sha_descriptor)
            descriptor = os.open(digest, file_flags, dir_fd=sha_descriptor)
            descriptors.append(descriptor)
        except OSError as error:
            for opened in reversed(descriptors):
                os.close(opened)
            if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise ArtifactIntegrityError(
                    f"Artifact object path contains an unsafe link: {value.artifact_id}"
                ) from error
            raise ArtifactObjectUnavailable(
                f"Artifact object is unavailable: {value.artifact_id}"
            ) from error
        try:
            object_stat = os.fstat(descriptor)
            if not stat.S_ISREG(object_stat.st_mode):
                raise ArtifactIntegrityError(
                    f"Artifact object is not a regular file: {value.artifact_id}"
                )
            if object_stat.st_size > self._max_bytes:
                raise ArtifactIntegrityError(
                    f"Artifact object exceeds the size limit: {value.artifact_id}"
                )
            chunks: list[bytes] = []
            remaining = self._max_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > self._max_bytes:
                raise ArtifactIntegrityError(
                    f"Artifact object exceeds the size limit: {value.artifact_id}"
                )
        except OSError as error:
            raise ArtifactObjectUnavailable(
                f"Artifact object is unavailable: {value.artifact_id}"
            ) from error
        finally:
            for opened in reversed(descriptors):
                os.close(opened)
        actual = "sha256:" + hashlib.sha256(payload).hexdigest()
        if actual != value.content_hash:
            raise ArtifactIntegrityError(
                f"Artifact content hash mismatch: {value.artifact_id}"
            )
        return payload


class UnavailableArtifactReader:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    def read(self, value: Artifact) -> bytes:
        raise ArtifactObjectUnavailable(self._reason)
