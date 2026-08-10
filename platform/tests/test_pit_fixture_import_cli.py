import io
import json
import unittest
from contextlib import redirect_stdout

from a_share_platform.workers.pit_fixture_import import main


class PITFixtureImportCLITest(unittest.TestCase):
    def test_default_mode_is_database_free_dry_run(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main([])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["mode"], "dry_run")
        self.assertFalse(payload["writes_performed"])
        self.assertEqual(payload["company_count"], 4)
        self.assertEqual(payload["official_fact_count"], 12)

    def test_execute_without_ack_and_local_database_is_blocked(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--execute"])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["mode"], "execute_requested")
        self.assertIn("private-local", " ".join(payload["blockers"]))
        self.assertIn("database", " ".join(payload["blockers"]))
        self.assertFalse(payload["writes_performed"])


if __name__ == "__main__":
    unittest.main()
