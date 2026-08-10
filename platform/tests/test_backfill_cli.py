import io
import json
import unittest
from contextlib import redirect_stdout

from a_share_platform.workers.backfill import main


class BackfillCliTest(unittest.TestCase):
    def test_default_mode_is_read_only_dry_run_with_license_blockers(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["--end", "2026-08-08"])
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertFalse(payload["writes_performed"])
        self.assertFalse(payload["qualified_for_bulk_persistence"])
        self.assertTrue(payload["blockers"])


if __name__ == "__main__":
    unittest.main()
