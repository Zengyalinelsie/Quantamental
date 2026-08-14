import hashlib
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from a_share_platform.adapters.object_store.local import LocalArtifactReader, LocalRawObjectStore
from a_share_platform.domain.governance import Artifact
from a_share_platform.ports.governance import ArtifactIntegrityError


class LocalRawObjectStoreTest(unittest.TestCase):
    def test_bytes_are_content_addressed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalRawObjectStore(Path(directory))
            payload = b"official disclosure bytes"
            first = store.put(payload)
            second = store.put(payload)

            self.assertEqual(first, second)
            path = Path(first.removeprefix("file://"))
            self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(path.parent.name, "sha256")

    def test_existing_content_address_is_never_silently_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalRawObjectStore(Path(directory))
            stored = store.put(b"expected")
            path = Path(stored.removeprefix("file://"))
            path.write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "content-addressed object mismatch"):
                store.put(b"expected")

    def test_concurrent_equivalent_creator_reuses_the_winning_object(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalRawObjectStore(Path(directory))
            payload = b"same immutable bytes"
            stored = store.put(payload)
            with patch.object(Path, "exists", return_value=False):
                self.assertEqual(store.put(payload), stored)

    def test_reader_rejects_scheme_path_shape_percent_escape_and_symlink_escape(self) -> None:
        payload = b"immutable Artifact"
        digest = hashlib.sha256(payload).hexdigest()
        content_hash = "sha256:" + digest

        def artifact(uri: str) -> Artifact:
            return Artifact(
                artifact_id="artifact:reader-security:001",
                run_id="run:reader-security:001",
                content_hash=content_hash,
                media_type="application/json",
                storage_uri=uri,
                created_at=datetime(2026, 8, 14, tzinfo=UTC),
            )

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "objects"
            outside = parent / "outside.json"
            outside.write_bytes(payload)
            reader = LocalArtifactReader(root)
            invalid_uris = (
                f"https://objects.invalid/sha256/{digest}",
                (root / "not-sha256" / digest).resolve().as_uri(),
                f"file://{root.resolve()}/sha256/%2e%2e/%2e%2e/outside.json",
            )
            for uri in invalid_uris:
                with self.subTest(uri=uri), self.assertRaises(ArtifactIntegrityError):
                    reader.read(artifact(uri))

            symlink = root / "sha256" / digest
            symlink.parent.mkdir(parents=True)
            symlink.symlink_to(outside)
            with self.assertRaises(ArtifactIntegrityError):
                reader.read(artifact(symlink.absolute().as_uri()))

            parent_link_root = parent / "linked-objects"
            external_sha = parent / "external-sha256"
            external_sha.mkdir()
            (external_sha / digest).write_bytes(payload)
            parent_link_root.mkdir()
            (parent_link_root / "sha256").symlink_to(external_sha)
            with self.assertRaises(ArtifactIntegrityError):
                LocalArtifactReader(parent_link_root).read(
                    artifact((parent_link_root / "sha256" / digest).absolute().as_uri())
                )

    def test_reader_rejects_non_regular_and_oversized_objects(self) -> None:
        payload = b"12345"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "sha256" / digest
            path.parent.mkdir(parents=True)
            path.write_bytes(payload)
            value = Artifact(
                artifact_id="artifact:size:001",
                run_id="run:size:001",
                content_hash="sha256:" + digest,
                media_type="application/json",
                storage_uri=path.resolve().as_uri(),
                created_at=datetime(2026, 8, 14, tzinfo=UTC),
            )
            with self.assertRaisesRegex(ArtifactIntegrityError, "size limit"):
                LocalArtifactReader(root, max_bytes=4).read(value)


if __name__ == "__main__":
    unittest.main()
