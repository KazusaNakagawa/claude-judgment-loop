"""Integration tests for the `judge` capture CLI.

Each test runs the real CLI via subprocess against a throwaway data dir
(JUDGMENT_LOOP_DIR), then inspects judgments.jsonl — i.e. real behavior, no mocks.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

JUDGE = str(Path(__file__).resolve().parent.parent / "bin" / "judge")


class JudgeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.log = self.data_dir / "judgments.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def run_judge(self, *args, expect_ok=True):
        env = dict(os.environ, JUDGMENT_LOOP_DIR=str(self.data_dir))
        proc = subprocess.run(
            [sys.executable, JUDGE, *args],
            env=env,
            capture_output=True,
            text=True,
        )
        if expect_ok:
            self.assertEqual(
                proc.returncode, 0,
                f"expected success, got rc={proc.returncode}\nstderr={proc.stderr}",
            )
        return proc

    def read_log(self):
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]


class TestReject(JudgeCase):
    def test_reject_appends_one_event_with_required_fields(self):
        self.run_judge(
            "reject", "--domain", "code-review",
            "--reason", "設計ドキュメントより先に実装を始めた",
        )
        events = self.read_log()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["domain"], "code-review")
        self.assertEqual(ev["verdict"], "rejected")
        self.assertEqual(ev["reason"], "設計ドキュメントより先に実装を始めた")
        self.assertTrue(ev["id"].startswith("j_"))
        self.assertIn("ts", ev)

    def test_reason_is_required(self):
        proc = self.run_judge(
            "reject", "--domain", "code-review", expect_ok=False
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_fix_is_recorded_as_correction(self):
        self.run_judge(
            "reject", "--domain", "x", "--reason", "r", "--fix", "設計ドキュメントを先に起こす",
        )
        self.assertEqual(self.read_log()[0]["correction"], "設計ドキュメントを先に起こす")


class TestVerdictMapping(JudgeCase):
    def test_revise_maps_to_revised(self):
        self.run_judge("revise", "--domain", "x", "--reason", "r")
        self.assertEqual(self.read_log()[0]["verdict"], "revised")

    def test_note_maps_to_accepted_with_note(self):
        self.run_judge("note", "--domain", "x", "--reason", "r")
        self.assertEqual(self.read_log()[0]["verdict"], "accepted-with-note")


class TestIdAutonumber(JudgeCase):
    def test_ids_increment_per_day(self):
        for _ in range(3):
            self.run_judge("reject", "--domain", "x", "--reason", "r")
        ids = [e["id"] for e in self.read_log()]
        self.assertEqual(len(set(ids)), 3, f"ids not unique: {ids}")
        # each id ends with a zero-padded counter
        seqs = [i.rsplit("_", 1)[1] for i in ids]
        self.assertEqual(seqs, ["001", "002", "003"])


class TestDomainInheritance(JudgeCase):
    def test_domain_inherited_from_last_event_when_omitted(self):
        self.run_judge("reject", "--domain", "code-review", "--reason", "first")
        self.run_judge("reject", "--reason", "second")  # no --domain
        events = self.read_log()
        self.assertEqual(events[1]["domain"], "code-review")

    def test_domain_required_when_no_prior_event(self):
        proc = self.run_judge("reject", "--reason", "r", expect_ok=False)
        self.assertNotEqual(proc.returncode, 0)


class TestTags(JudgeCase):
    def test_tags_split_on_comma(self):
        self.run_judge(
            "reject", "--domain", "x", "--reason", "r",
            "--tags", "設計,手順",
        )
        self.assertEqual(self.read_log()[0]["tags"], ["設計", "手順"])


class TestStats(JudgeCase):
    def test_stats_reports_total_and_per_domain(self):
        self.run_judge("reject", "--domain", "code-review", "--reason", "a")
        self.run_judge("reject", "--domain", "code-review", "--reason", "b")
        self.run_judge("note", "--domain", "writing", "--reason", "c")
        proc = self.run_judge("stats")
        out = proc.stdout
        self.assertIn("3", out)                 # cumulative total — the reward signal
        self.assertIn("code-review", out)
        self.assertIn("writing", out)

    def test_stats_on_empty_log_reports_zero(self):
        proc = self.run_judge("stats")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("0", proc.stdout)


class TestCorruptLogTolerance(JudgeCase):
    """A read-only append log must stay capturable even if a hand-edit corrupts
    one line. Skip bad lines (warn on stderr); never let history break capture."""

    def write_raw(self, text):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text(text)

    def test_stats_skips_corrupt_line_and_counts_valid(self):
        good = json.dumps({"id": "j_20260101_001", "ts": "t", "domain": "x",
                           "verdict": "rejected", "reason": "r"}, ensure_ascii=False)
        self.write_raw(good + "\n{ this is broken json\n" + good.replace("_001", "_002") + "\n")
        proc = self.run_judge("stats")
        self.assertIn("2", proc.stdout)            # 2 valid counted
        self.assertIn("line 2", proc.stderr)       # warned which line was skipped

    def test_capture_still_works_with_corrupt_history(self):
        self.write_raw("{ broken\n")
        self.run_judge("reject", "--domain", "code-review", "--reason", "still works")
        # the new event was appended after the broken line
        lines = self.log.read_text().splitlines()
        self.assertEqual(lines[-1] and json.loads(lines[-1])["reason"], "still works")


if __name__ == "__main__":
    unittest.main()
