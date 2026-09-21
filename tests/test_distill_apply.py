"""Integration tests for `distill-apply`.

Applies a human-approved structured patch (JSONL of ops) to rules.jsonl
*deterministically*: counts evidence by source_ids, never lets an LLM rewrite
the file. Unrelated existing rules must survive untouched.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

APPLY = str(Path(__file__).resolve().parent.parent / "bin" / "distill-apply")


class ApplyCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.rules = self.data_dir / "rules.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def seed_rules(self, *rules):
        self.rules.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rules))

    def write_patch(self, *ops):
        p = self.data_dir / "patch.jsonl"
        p.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in ops))
        return str(p)

    def run_apply(self, patch_path, expect_ok=True):
        env = dict(os.environ, JUDGMENT_LOOP_DIR=str(self.data_dir))
        proc = subprocess.run(
            [sys.executable, APPLY, patch_path],
            env=env, capture_output=True, text=True,
        )
        if expect_ok:
            self.assertEqual(proc.returncode, 0, f"rc={proc.returncode}\n{proc.stderr}")
        return proc

    def read_rules(self):
        if not self.rules.exists():
            return []
        return [json.loads(l) for l in self.rules.read_text().splitlines() if l.strip()]

    def by_id(self):
        return {r["rule_id"]: r for r in self.read_rules()}


class TestNew(ApplyCase):
    def test_new_rule_added_as_tentative_with_evidence_from_source_ids(self):
        patch = self.write_patch({
            "op": "new", "domain": "code-review",
            "trigger": "新機能に着手するとき",
            "rule": "実装より先に設計ドキュメントを起こす", "rationale": "手戻りが大きい",
            "source_ids": ["j_20260621_001", "j_20260512_004"],
        })
        self.run_apply(patch)
        rules = self.read_rules()
        self.assertEqual(len(rules), 1)
        r = rules[0]
        self.assertEqual(r["status"], "tentative")
        self.assertEqual(r["evidence_count"], 2)  # derived, not LLM-claimed
        self.assertTrue(r["rule_id"].startswith("r_code_"))
        self.assertIn("updated_at", r)


class TestAddEvidence(ApplyCase):
    def test_evidence_count_is_unique_source_id_count(self):
        self.seed_rules({
            "rule_id": "r_code_001", "domain": "code-review",
            "trigger": "t", "rule": "x", "rationale": "y",
            "source_ids": ["j_20260101_001"], "evidence_count": 1,
            "status": "tentative", "updated_at": "2026-01-01T00:00:00+09:00",
        })
        # add one new + one duplicate source id
        patch = self.write_patch({
            "op": "add_evidence", "rule_id": "r_code_001",
            "source_ids": ["j_20260621_009", "j_20260101_001"],
        })
        self.run_apply(patch)
        r = self.by_id()["r_code_001"]
        self.assertEqual(sorted(r["source_ids"]), ["j_20260101_001", "j_20260621_009"])
        self.assertEqual(r["evidence_count"], 2)  # deduped, deterministic


class TestActivateRetire(ApplyCase):
    def setUp(self):
        super().setUp()
        self.seed_rules({
            "rule_id": "r_code_001", "domain": "code-review",
            "trigger": "t", "rule": "x", "rationale": "y",
            "source_ids": ["j_a", "j_b"], "evidence_count": 2,
            "status": "tentative", "updated_at": "2026-01-01T00:00:00+09:00",
        })

    def test_activate_sets_status_active(self):
        self.run_apply(self.write_patch({"op": "activate", "rule_id": "r_code_001"}))
        self.assertEqual(self.by_id()["r_code_001"]["status"], "active")

    def test_retire_sets_status_retired(self):
        self.run_apply(self.write_patch({"op": "retire", "rule_id": "r_code_001"}))
        self.assertEqual(self.by_id()["r_code_001"]["status"], "retired")


class TestUnrelatedRulesUntouched(ApplyCase):
    def test_existing_active_rule_survives_apply(self):
        keep = {
            "rule_id": "r_code_003", "domain": "code-review",
            "trigger": "PRレビュー時", "rule": "保つべき原則", "rationale": "理由",
            "source_ids": ["j_x", "j_y"], "evidence_count": 2,
            "status": "active", "updated_at": "2026-02-02T00:00:00+09:00",
        }
        self.seed_rules(keep)
        patch = self.write_patch({
            "op": "new", "domain": "writing", "trigger": "t",
            "rule": "別ルール", "rationale": "r", "source_ids": ["j_z"],
        })
        self.run_apply(patch)
        # the untouched rule must be byte-for-byte identical
        self.assertEqual(self.by_id()["r_code_003"], keep)
        self.assertEqual(len(self.read_rules()), 2)


class TestValidation(ApplyCase):
    def test_activate_unknown_rule_fails_and_writes_nothing(self):
        proc = self.run_apply(
            self.write_patch({"op": "activate", "rule_id": "r_nope_999"}),
            expect_ok=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.rules.exists())



class TestEmptySource(ApplyCase):
    def test_new_without_source_ids_is_rejected(self):
        # a rule with zero evidence is meaningless and untraceable
        proc = self.run_apply(
            self.write_patch({
                "op": "new", "domain": "code-review",
                "trigger": "t", "rule": "x", "rationale": "y", "source_ids": [],
            }),
            expect_ok=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.rules.exists())


class TestStrictAndBackup(ApplyCase):
    def test_corrupt_rules_aborts_with_line_number_and_no_write(self):
        # rules.jsonl is written back wholesale, so a corrupt line must ABORT —
        # silently skipping it would drop that rule on the next write.
        self.rules.write_text('{"rule_id":"r_code_001","status":"active"}\n{ broken\n')
        before = self.rules.read_text()
        proc = self.run_apply(
            self.write_patch({"op": "retire", "rule_id": "r_code_001"}),
            expect_ok=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("line 2", proc.stderr)
        self.assertEqual(self.rules.read_text(), before)  # untouched

    def test_backup_written_before_overwrite(self):
        self.seed_rules({
            "rule_id": "r_code_001", "domain": "code-review", "trigger": "t",
            "rule": "x", "rationale": "y", "source_ids": ["j_a"],
            "evidence_count": 1, "status": "tentative", "updated_at": "t",
        })
        original = self.rules.read_text()
        self.run_apply(self.write_patch({"op": "activate", "rule_id": "r_code_001"}))
        bak = self.data_dir / "rules.jsonl.bak"
        self.assertTrue(bak.exists())
        self.assertEqual(bak.read_text(), original)  # pre-apply snapshot for undo


if __name__ == "__main__":
    unittest.main()
