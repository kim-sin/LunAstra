from __future__ import annotations
import copy
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from luna_astra.evidence import Evidence
from luna_astra.util import HarnessError, snapshot

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.ws = self.base / "source"
        self.ws.mkdir()
        (self.ws / "app.py").write_text("answer = 42\n")
        (self.ws / "check.py").write_text("import app\nassert app.answer == 42\nprint('behavior passed')\n")
        self.ev = Evidence(self.base / "receipt", self.ws)
        self.task = {"task_id": "one", "design": "Preserve answer=42 and module interface", "requirements": ["answer is 42"],
                     "allowed_paths": ["app.py"], "protected_paths": [],
                     "checks": [{"id": "behavior", "purpose": "Evaluate actual module behavior", "argv": [sys.executable, "check.py"],
                                 "dependencies": ["app.py", "check.py"], "covers": [0]}]}
        self.ev.begin(self.task)

    def runpass(self):
        r = self.ev.run("behavior")
        self.assertEqual(r["status"], "PASS", r)
        return r

    def test_actual_command_pass(self):
        r = self.runpass()
        self.assertIn("behavior passed", Path(r["stdout"]).read_text())
        self.assertTrue(self.ev.status()["passed"])

    def test_never_run_is_not_verified(self):
        self.assertFalse(self.ev.status()["passed"])
        self.assertEqual(self.ev.status()["checks"][0]["status"], "NOT_RUN")

    def test_failed_exit_is_recorded(self):
        (self.ws / "app.py").write_text("answer=41\n")
        r = self.ev.run("behavior")
        self.assertEqual(r["status"], "FAIL")
        self.assertNotEqual(r["exit_code"], 0)
        self.assertFalse(self.ev.status()["passed"])

    def test_newer_failure_overrides_old_success_even_same_dependency_snapshot(self):
        # The marker is intentionally outside declared dependencies to prove newest-attempt precedence.
        check = "from pathlib import Path\nassert not Path('FAIL').exists()\n"
        (self.ws / "check.py").write_text(check)
        self.runpass()
        (self.ws / "FAIL").touch()
        self.assertEqual(self.ev.run("behavior")["status"], "FAIL")
        (self.ws / "FAIL").unlink()
        self.assertEqual(self.ev.status()["checks"][0]["status"], "FAIL")
        self.assertFalse(self.ev.status()["passed"])

    def test_newer_success_can_resolve_failure(self):
        (self.ws / "app.py").write_text("answer=0\n")
        self.ev.run("behavior")
        (self.ws / "app.py").write_text("answer=42\n")
        self.runpass()
        self.assertTrue(self.ev.status()["passed"])

    def test_changed_source_invalidates_success(self):
        self.runpass()
        (self.ws / "app.py").write_text("answer=43\n")
        self.assertEqual(self.ev.status()["checks"][0]["status"], "STALE")

    def test_changed_test_invalidates_success(self):
        self.runpass()
        (self.ws / "check.py").write_text("raise AssertionError('new contract')\n")
        self.assertFalse(self.ev.status()["passed"])

    def test_test_that_changes_dependency_is_stale(self):
        (self.ws / "check.py").write_text("from pathlib import Path\nPath('app.py').write_text('answer=42 # changed\\n')\n")
        self.assertEqual(self.ev.run("behavior")["status"], "STALE")
        self.assertFalse(self.ev.status()["passed"])

    def test_missing_log_invalidates_success(self):
        r = self.runpass()
        Path(r["stdout"]).unlink()
        self.assertFalse(self.ev.status()["passed"])

    def test_tampered_log_invalidates_success(self):
        r = self.runpass()
        Path(r["stderr"]).write_text("changed")
        self.assertFalse(self.ev.status()["passed"])

    def test_missing_dependency_records_error(self):
        (self.ws / "app.py").unlink()
        r = self.ev.run("behavior")
        self.assertEqual(r["status"], "ERROR")
        self.assertFalse(self.ev.status()["passed"])

    def test_missing_executable_records_error(self):
        self.task["checks"][0]["argv"] = [str(self.base / "missing-program")]
        self.ev.begin(self.task)
        self.assertEqual(self.ev.run("behavior")["status"], "ERROR")

    def test_check_definition_change_requires_new_evidence(self):
        self.runpass()
        self.task["checks"][0]["purpose"] = "Changed acceptance obligation"
        self.ev.begin(self.task)
        self.assertFalse(self.ev.status()["passed"])

    def test_task_identity_change_requires_new_evidence(self):
        self.runpass()
        self.task["task_id"] = "second"
        self.ev.begin(self.task)
        self.assertFalse(self.ev.status()["passed"])

    def test_external_identity_change_requires_new_evidence(self):
        self.runpass()
        self.task["checks"][0]["identity"] = {"dataset_sha256": "new-value"}
        self.ev.begin(self.task)
        self.assertFalse(self.ev.status()["passed"])

    def test_identical_begin_preserves_current_evidence(self):
        self.runpass()
        self.assertFalse(self.ev.begin(self.task)["changed"])
        self.assertTrue(self.ev.status()["passed"])

    def test_all_requirements_need_coverage(self):
        self.task["requirements"].append("second condition")
        self.ev.begin(self.task)
        self.runpass()
        self.assertEqual(self.ev.status()["missing_requirements"], [1])
        self.assertFalse(self.ev.status()["passed"])

    def test_all_registered_checks_are_required(self):
        second = copy.deepcopy(self.task["checks"][0]); second["id"] = "regression"
        self.task["checks"].append(second)
        self.ev.begin(self.task)
        self.runpass()
        self.assertFalse(self.ev.status()["passed"])
        self.ev.run("regression")
        self.assertTrue(self.ev.status()["passed"])

    def test_empty_checks_not_a_success(self):
        self.task["checks"] = []
        self.ev.begin(self.task)
        self.assertFalse(self.ev.status()["passed"])

    def test_duplicate_ids_rejected(self):
        self.task["checks"].append(copy.deepcopy(self.task["checks"][0]))
        with self.assertRaises(HarnessError): self.ev.begin(self.task)

    def test_malformed_contract_rejected(self):
        cases = [None, {}, {"task_id": "x", "design": "y", "requirements": []},
                 {**self.task, "requirements": ["x", "x"]},
                 {**self.task, "allowed_paths": "app.py"}]
        for task in cases:
            with self.subTest(task=task), self.assertRaises(HarnessError): self.ev.begin(task)

    def test_malformed_check_rejected(self):
        changes = [{"argv": "python check.py"}, {"argv": []}, {"dependencies": []},
                   {"covers": [True]}, {"covers": [999]}, {"purpose": ""}, {"identity": []}]
        for change in changes:
            task = copy.deepcopy(self.task); task["checks"][0].update(change)
            with self.subTest(change=change), self.assertRaises(HarnessError): self.ev.begin(task)

    def test_dependency_escape_rejected(self):
        for value in ("../outside", "/tmp/source", "C:/Users/x", "..\\outside", "."):
            task = copy.deepcopy(self.task); task["checks"][0]["dependencies"] = [value]
            with self.subTest(value=value), self.assertRaises(HarnessError): self.ev.begin(task)

    def test_changed_dependency_directory_membership_is_detected(self):
        (self.ws / "src").mkdir(); (self.ws / "src" / "a.py").write_text("x=1\n")
        self.task["checks"][0]["dependencies"].append("src")
        self.ev.begin(self.task); self.runpass()
        (self.ws / "src" / "new.py").write_text("x=2\n")
        self.assertFalse(self.ev.status()["passed"])

    def test_deleted_directory_file_is_detected(self):
        (self.ws / "src").mkdir(); path = self.ws / "src" / "a.py"; path.write_text("x=1\n")
        self.task["checks"][0]["dependencies"].append("src")
        self.ev.begin(self.task); self.runpass(); path.unlink()
        self.assertFalse(self.ev.status()["passed"])

    def test_pycache_is_not_a_source_change(self):
        (self.ws / "src").mkdir(); (self.ws / "src" / "a.py").write_text("x=1\n")
        self.task["checks"][0]["dependencies"].append("src")
        self.ev.begin(self.task); self.runpass()
        (self.ws / "src" / "__pycache__").mkdir(); (self.ws / "src" / "__pycache__" / "a.pyc").write_bytes(b"x")
        self.assertTrue(self.ev.status()["passed"])

    def test_symlink_dependency_rejected(self):
        target = self.base / "outside"; target.write_text("secret")
        (self.ws / "link").symlink_to(target)
        self.task["checks"][0]["dependencies"] = ["link"]
        with self.assertRaises(HarnessError): self.ev.begin(self.task)

    def test_evidence_cannot_be_inside_workspace(self):
        with self.assertRaises(HarnessError): Evidence(self.ws / "state", self.ws)

    def test_worker_workspace_binding_cannot_change(self):
        other = self.base / "other"; other.mkdir()
        with self.assertRaises(HarnessError): Evidence(self.base / "receipt", other)

    def test_tested_completion_requires_fresh_checks(self):
        with self.assertRaises(HarnessError): self.ev.finish("tested", "done", "review", "none")
        self.runpass()
        claim = self.ev.finish("tested", "done", "review", "declared scope only")
        self.assertTrue(claim["valid"])
        (self.ws / "app.py").write_text("answer=0\n")
        self.assertFalse(self.ev.status()["finish"]["valid"])

    def test_partial_handback_is_not_tested_completion(self):
        claim = self.ev.finish("partial", "patch saved", "design preserved", "integration environment unavailable")
        self.assertFalse(claim["evidence"]["passed"])
        self.assertEqual(claim["kind"], "partial")

    def test_empty_handback_fields_rejected(self):
        for args in [("partial", "", "r", "l"), ("partial", "s", "", "l"), ("partial", "s", "r", ""), ("pass", "s", "r", "l")]:
            with self.subTest(args=args), self.assertRaises(HarnessError): self.ev.finish(*args)

    def test_new_run_invalidates_previous_finish(self):
        self.runpass(); self.ev.finish("tested", "done", "review", "scope")
        self.runpass()
        self.assertIsNone(self.ev.status()["finish"])

    def test_newer_running_check_overrides_old_pass_and_blocks_reconfigure(self):
        (self.ws / "check.py").write_text("from pathlib import Path\nimport time\nif Path('SLOW').exists():\n Path('READY').touch()\n while not Path('RELEASE').exists(): time.sleep(.01)\n")
        self.runpass()
        (self.ws / "SLOW").touch()
        errors = []
        def work():
            try: self.ev.run("behavior")
            except Exception as e: errors.append(e)
        thread = threading.Thread(target=work); thread.start()
        try:
            deadline = time.monotonic() + 5
            while not (self.ws / "READY").exists() and time.monotonic() < deadline: time.sleep(.01)
            self.assertTrue((self.ws / "READY").exists())
            self.assertFalse(self.ev.status()["passed"])
            self.assertEqual(self.ev.status()["active"], 1)
            changed = copy.deepcopy(self.task); changed["task_id"] = "new"
            with self.assertRaises(HarnessError): self.ev.begin(changed)
            with self.assertRaises(HarnessError): self.ev.finish("tested", "s", "r", "l")
        finally:
            (self.ws / "RELEASE").touch(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(self.ev.status()["passed"])

    def test_parallel_worker_receipts_do_not_share_status(self):
        other = Evidence(self.base / "receipt2", self.ws); other.begin(self.task)
        self.runpass()
        self.assertFalse(other.status()["passed"])
        self.assertTrue(self.ev.status()["passed"])

    def test_log_paths_cannot_escape_evidence_directory(self):
        self.runpass()
        with self.ev._transaction() as db:
            db.execute("UPDATE attempts SET stdout_path='../outside'")
        self.assertFalse(self.ev.status()["passed"])

    def test_shell_metacharacters_are_literal_arguments(self):
        self.task["checks"][0]["argv"] = [sys.executable, "-c", "import sys; assert sys.argv[1] == '; touch HACKED'", "; touch HACKED"]
        self.ev.begin(self.task); self.runpass()
        self.assertFalse((self.ws / "HACKED").exists())

if __name__ == "__main__": unittest.main()
