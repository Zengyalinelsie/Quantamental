import tempfile
import unittest
from pathlib import Path

from a_share_platform.adapters.object_store.local import LocalRawObjectStore


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


if __name__ == "__main__":
    unittest.main()
