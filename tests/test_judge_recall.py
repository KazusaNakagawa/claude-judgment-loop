"""Integration tests for the `judge-recall` SessionStart hook.

Each test runs the real hook via subprocess against a throwaway data dir
(JUDGMENT_LOOP_DIR), then inspects stdout — i.e. real behavior, no mocks.
"""

import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

RECALL = str(Path(__file__).resolve().parent.parent / "bin" / "judge-recall")


class RecallCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.log = self.data_dir / "judgments.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def run_recall(self):
        env = dict(os.environ, JUDGMENT_LOOP_DIR=str(self.data_dir))
        proc = subprocess.run(
            [sys.executable, RECALL],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode, 0,
            f"expected success, got rc={proc.returncode}\nstderr={proc.stderr}",
        )
        return proc.stdout.strip()

    def write_log(self, ts):
        self.log.write_text(json.dumps({"id": "j_x", "ts": ts}) + "\n")

    def test_nags_when_no_log_exists(self):
        out = self.run_recall()
        payload = json.loads(out)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("judge", payload["hookSpecificOutput"]["additionalContext"])

    def test_silent_when_recent_judgment(self):
        self.write_log(datetime.now(timezone.utc).isoformat())
        self.assertEqual(self.run_recall(), "")

    def test_nags_when_last_judgment_is_stale(self):
        stale = datetime.now(timezone.utc) - timedelta(hours=48)
        self.write_log(stale.isoformat())
        self.assertNotEqual(self.run_recall(), "")

    def test_nags_at_most_once_per_interval(self):
        self.assertNotEqual(self.run_recall(), "")
        self.assertEqual(self.run_recall(), "")

    def test_ignores_malformed_log_lines(self):
        self.log.write_text("not json\n")
        self.assertNotEqual(self.run_recall(), "")


if __name__ == "__main__":
    unittest.main()
