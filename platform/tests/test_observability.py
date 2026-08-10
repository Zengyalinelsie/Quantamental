import json
import logging
import unittest

from a_share_platform.application.observability import JsonFormatter, log_context


class ObservabilityTest(unittest.TestCase):
    def test_json_formatter_includes_trace_and_run_context(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "completed", (), None)
        with log_context(trace_id="trace:001", run_id="run:001"):
            payload = json.loads(formatter.format(record))
        self.assertEqual(payload["message"], "completed")
        self.assertEqual(payload["trace_id"], "trace:001")
        self.assertEqual(payload["run_id"], "run:001")

    def test_context_is_reset_after_scope(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "outside", (), None)
        with log_context(trace_id="trace:001", run_id="run:001"):
            pass
        payload = json.loads(formatter.format(record))
        self.assertNotIn("trace_id", payload)
        self.assertNotIn("run_id", payload)


if __name__ == "__main__":
    unittest.main()
