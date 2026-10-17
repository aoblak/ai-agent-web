"""Executable handoff safety cases; all actors and receipts are synthetic."""
import copy
import importlib.util
import json
import io
from types import SimpleNamespace
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("context_gate", PACKAGE / "scripts/oos_context.py")
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


class HandoffGateChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        manifest = json.loads((PACKAGE / context.INDEX).read_text())
        for name in [d["path"] for d in manifest["documents"]] + [context.INDEX]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACKAGE / name, target)
        self.journal = self.root / "docs/MASTER_JOURNAL.md"
        self.original = self.journal.read_bytes()
        self.artifact = self.root / "result.txt"
        self.artifact.write_text("Synthetic returned output and check evidence.\n")
        self.policy = dict(task_id="TASK-9", attempt_id="ATTEMPT-1", owner="worker",
                           reviewer="auditor", coordinator="coordinator", next_owner="recipient",
                           source_commit="a" * 40)
        self.events = []
        expected_steps = [("READY", "coordinator"), ("ASSIGNED", "coordinator"),
                          ("ACCEPTED", "owner"), ("IN_PROGRESS", "owner"),
                          ("RESULT_RETURNED", "owner"), ("VERIFIED", "reviewer"),
                          ("VERIFIED", "coordinator"), ("HANDED_OFF", "next_owner")]
        for i, (state, role) in enumerate(expected_steps):
            h = dict(schema="oos-handoff/1", **self.policy, state=state, role=role,
                     criteria=["OUTPUT-CORRECT"], message_id="synthetic-message-" + str(i))
            meta = dict(id="GATE-EVENT-" + str(i), actor=self.policy[role],
                        recorded_at=f"2026-10-13T08:00:0{i}Z", occurred_at=f"2026-10-13T08:00:0{i}Z",
                        topics=["synthetic-test"], status="VERIFIED", visibility="PUBLIC", handoff=h)
            self.events.append(meta)
        self.events[2]["handoff"]["in_reply_to"] = self.events[1]["id"]
        self.events[4]["handoff"]["artifacts"] = [dict(id="OUTPUT-1", path="result.txt",
                                                             sha256=context.sha(self.artifact.read_bytes()))]
        self.events[5]["handoff"].update(result_event_id=self.events[4]["id"], checks=[
            dict(criterion="OUTPUT-CORRECT", ok=True, evidence=["OUTPUT-1"])])
        self.events[6]["handoff"]["review_event_id"] = self.events[5]["id"]
        self.events[7]["handoff"]["confirmation_event_id"] = self.events[6]["id"]

    def persist(self, events=None):
        events = self.events if events is None else events
        text = ""
        for meta in events:
            text += "\n<!-- oos:event " + json.dumps(meta) + " -->\n"
            text += "## " + meta["id"] + " — Synthetic gate fixture\n"
            for field in context.FIELDS:
                text += field + ": PASS — synthetic fixture observation, not live provider evidence.\n"
            text += "<!-- /oos:event -->\n"
        self.journal.write_bytes(self.original + text.encode())
        self.policy["journal_sha256"] = context.sha(self.journal.read_bytes())
        result = self.cli("reindex", "--write")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(self.root / "scripts/oos_context.py"),
                               "--root", str(self.root), *args], capture_output=True, text=True)

    def gate_cli(self):
        args = ["handoff-gate"]
        for key, value in self.policy.items():
            args += ["--" + key.replace("_", "-"), value]
        return self.cli(*args)

    def assert_blocked(self):
        calls = []
        with self.assertRaises(context.ContextError):
            context.guarded_continue(self.root, self.policy, calls.append)
        self.assertEqual(calls, [], "Blocked evidence invoked the downstream continuation")

    def test_complete_chain_invokes_continuation_with_verified_artifact(self):
        self.persist()
        calls = []
        context.guarded_continue(self.root, self.policy, calls.append)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["status"], "HANDOFF_VERIFIED")
        self.assertEqual(calls[0]["receipt_event_id"], self.events[7]["id"])
        self.assertEqual(calls[0]["artifacts"][0]["sha256"], context.sha(self.artifact.read_bytes()))
        self.assertEqual(self.gate_cli().returncode, 0)

    def test_unrelated_task_with_new_schema_does_not_block_valid_chain(self):
        unrelated = copy.deepcopy(self.events[0])
        unrelated["id"] = "UNRELATED-NEW-SCHEMA"
        unrelated["handoff"].update(task_id="OTHER-TASK", schema="oos-handoff/2")
        self.persist([unrelated] + self.events)
        calls = []
        context.guarded_continue(self.root, self.policy, calls.append)
        self.assertEqual(len(calls), 1)

    def test_requested_task_with_unsupported_schema_blocks(self):
        self.events[0]["handoff"]["schema"] = "oos-handoff/2"
        self.persist()
        self.assert_blocked()

    def test_unidentifiable_handoff_record_blocks(self):
        for handoff in ({"schema": "oos-handoff/2"}, "invalid"):
            with self.subTest(handoff=handoff):
                unrelated = copy.deepcopy(self.events[0])
                unrelated["id"] = "UNIDENTIFIABLE-HANDOFF"
                unrelated["handoff"] = handoff
                self.persist([unrelated] + self.events)
                self.assert_blocked()

    def test_each_missing_stage_blocks_callback(self):
        for i in range(len(self.events)):
            with self.subTest(missing_stage=i):
                self.persist(self.events[:i] + self.events[i + 1:])
                self.assert_blocked()

    def test_missing_required_bindings_block(self):
        for field in context.HANDOFF_BINDINGS:
            with self.subTest(field=field):
                events = copy.deepcopy(self.events)
                del events[4]["handoff"][field]
                self.persist(events)
                self.assert_blocked()

    def test_wrong_actors_block(self):
        for i in range(len(self.events)):
            with self.subTest(stage=i):
                events = copy.deepcopy(self.events)
                events[i]["actor"] = "unassigned-actor"
                self.persist(events)
                self.assert_blocked()

    def test_premature_next_stage_blocks(self):
        events = copy.deepcopy(self.events)
        events[3]["handoff"].update(state="IN_PROGRESS", role="next_owner")
        self.persist(events)
        self.assert_blocked()

    def test_two_owners_same_attempt_block(self):
        self.events[4]["handoff"]["owner"] = "other-worker"
        self.persist()
        self.assert_blocked()

    def test_source_mismatch_blocks_even_if_all_records_agree(self):
        for e in self.events:
            e["handoff"]["source_commit"] = "b" * 40
        self.persist()
        self.assert_blocked()

    def test_duplicate_stage_or_delivery_blocks(self):
        extra = copy.deepcopy(self.events[3])
        extra["id"] = "GATE-EXTRA"
        self.persist(self.events[:4] + [extra] + self.events[4:])
        self.assert_blocked()
        self.events[7]["handoff"]["message_id"] = self.events[1]["handoff"]["message_id"]
        self.persist()
        self.assert_blocked()

    def test_wrong_receipt_or_review_references_block(self):
        for i, field in [(2,"in_reply_to"),(5,"result_event_id"),(6,"review_event_id"),(7,"confirmation_event_id")]:
            with self.subTest(field=field):
                events = copy.deepcopy(self.events)
                events[i]["handoff"][field] = "ANOTHER-ATTEMPT"
                self.persist(events)
                self.assert_blocked()

    def test_absent_result_missing_file_and_wrong_hash_block(self):
        original = copy.deepcopy(self.events)
        for artifacts in [[], [dict(id="X",path="missing.txt",sha256="0"*64)],
                          [dict(id="X",path="result.txt",sha256="0"*64)]]:
            self.events = copy.deepcopy(original)
            self.events[4]["handoff"]["artifacts"] = artifacts
            self.persist()
            self.assert_blocked()

    def test_changed_artifact_after_receipt_blocks(self):
        self.persist()
        self.artifact.write_text("different result")
        self.assert_blocked()

    def test_failed_missing_or_truthy_non_boolean_checks_block(self):
        original = copy.deepcopy(self.events[5]["handoff"])
        for checks in [[], [dict(criterion="OUTPUT-CORRECT",ok=False,evidence=["OUTPUT-1"])],
                       [dict(criterion="OUTPUT-CORRECT",ok=1,evidence=["OUTPUT-1"])],
                       [dict(criterion="OUTPUT-CORRECT",ok=True,evidence=[])],
                       [dict(criterion="OUTPUT-CORRECT",ok=True,evidence=["MISSING"])]]:
            self.events[5]["handoff"] = dict(original, checks=checks)
            self.persist()
            self.assert_blocked()

    def test_self_review_blocks(self):
        self.policy["reviewer"] = self.policy["owner"]
        for e in self.events:
            e["handoff"]["reviewer"] = self.policy["owner"]
        self.events[5]["actor"] = self.policy["owner"]
        self.persist()
        self.assert_blocked()

    def test_criteria_drift_blocks(self):
        self.events[5]["handoff"]["criteria"] = ["DIFFERENT"]
        self.persist()
        self.assert_blocked()

    def test_proposed_receipt_is_not_observed_acceptance(self):
        self.events[7]["status"] = "PROPOSED"
        self.persist()
        self.assert_blocked()

    def test_unknown_or_out_of_order_occurrence_blocks(self):
        for time in [None, "2026-10-12T00:00:00Z"]:
            self.events[7]["occurred_at"] = time
            self.persist()
            self.assert_blocked()

    def test_journal_lease_mismatch_blocks(self):
        self.persist()
        self.policy["journal_sha256"] = "0" * 64
        self.assert_blocked()
        self.assertNotEqual(self.gate_cli().returncode, 0)

    def test_new_attempt_revokes_old_receipt(self):
        newer = copy.deepcopy(self.events[0])
        newer["id"] = "GATE-NEW-ATTEMPT"
        newer["handoff"]["attempt_id"] = "ATTEMPT-2"
        self.persist(self.events + [newer])
        self.assert_blocked()

    def test_later_blocker_revokes_completed_sequence(self):
        blocked = copy.deepcopy(self.events[-1])
        blocked["id"] = "GATE-BLOCKED"
        blocked["handoff"]["state"] = "BLOCKED"
        self.persist(self.events + [blocked])
        self.assert_blocked()

    def test_legacy_prose_cannot_authorize_handoff(self):
        for e in self.events:
            del e["handoff"]
        self.persist()
        self.assert_blocked()

    def test_external_path_and_symlink_block(self):
        self.events[4]["handoff"]["artifacts"][0]["path"] = "../outside.txt"
        self.persist()
        self.assert_blocked()
        self.events[4]["handoff"]["artifacts"][0]["path"] = "linked.txt"
        (self.root / "linked.txt").symlink_to(self.artifact)
        self.persist()
        self.assert_blocked()

    def test_unresolved_policy_blocks(self):
        self.persist()
        self.policy["owner"] = "UNKNOWN"
        self.assert_blocked()

    def test_journal_change_during_check_blocks_callback(self):
        self.persist()
        original_reader = context.local_file
        reads = 0

        def read(root, relative):
            nonlocal reads
            file = original_reader(root, relative)
            if relative == "docs/MASTER_JOURNAL.md":
                reads += 1
                if reads == 2:
                    file.write_bytes(file.read_bytes() + b"\nconcurrent change\n")
            return file

        with patch.object(context, "local_file", side_effect=read):
            self.assert_blocked()

    def test_artifact_change_during_check_blocks_callback(self):
        self.persist()
        original_reader = context.local_file
        reads = 0

        def read(root, relative):
            nonlocal reads
            file = original_reader(root, relative)
            if relative == "result.txt":
                reads += 1
                if reads == 2:
                    file.write_text("concurrently replaced result")
            return file

        with patch.object(context, "local_file", side_effect=read):
            self.assert_blocked()

    def test_artifact_growth_during_recheck_is_capped_and_blocks_callback(self):
        self.persist()
        original_reader = context.local_file
        reads = 0

        def read(root, relative):
            nonlocal reads
            file = original_reader(root, relative)
            if relative == "result.txt":
                reads += 1
                if reads == 2:
                    file.write_bytes(b"x" * 129)
            return file

        with patch.object(context, "HANDOFF_ARTIFACT_LIMIT", 128), \
                patch.object(context, "local_file", side_effect=read):
            calls = []
            with self.assertRaisesRegex(context.ContextError, "exceeds"):
                context.guarded_continue(self.root, self.policy, calls.append)
            self.assertEqual(calls, [])

    def test_artifact_read_remains_capped_with_stale_stat(self):
        sizes = []

        class GrowingStream(io.BytesIO):
            def read(self, size=-1):
                sizes.append(size)
                if size < 0:
                    raise AssertionError("Unbounded artifact read")
                return super().read(size)

        class StaleFile:
            def stat(self):
                return SimpleNamespace(st_size=1)

            def open(self, mode):
                return GrowingStream(b"x" * 1024)

        with patch.object(context, "HANDOFF_ARTIFACT_LIMIT", 128):
            with self.assertRaisesRegex(context.ContextError, "exceeds"):
                context.read_handoff_artifact(StaleFile())
        self.assertEqual(sizes, [129])

    def test_message_ids_cannot_be_replayed_from_previous_attempt(self):
        previous = copy.deepcopy(self.events)
        current = copy.deepcopy(self.events)
        self.policy["attempt_id"] = "ATTEMPT-2"
        for item in current:
            item["id"] += "-RETRY"
            item["handoff"]["attempt_id"] = "ATTEMPT-2"
            for field in ("in_reply_to", "result_event_id", "review_event_id", "confirmation_event_id"):
                if field in item["handoff"]:
                    item["handoff"][field] += "-RETRY"
        self.persist(previous + current)
        self.assert_blocked()
        # Fresh messages permit the explicit retry with the same valid artifact.
        for item in current:
            item["handoff"]["message_id"] += "-RETRY"
        self.persist(previous + current)
        calls = []
        context.guarded_continue(self.root, self.policy, calls.append)
        self.assertEqual(len(calls), 1)

    def test_journal_growth_during_final_read_is_bounded(self):
        self.persist()
        original_reader = context.local_file
        reads = 0
        limit = len(self.journal.read_bytes()) + 128

        def read(root, relative):
            nonlocal reads
            file = original_reader(root, relative)
            if relative == "docs/MASTER_JOURNAL.md":
                reads += 1
                if reads == 2:
                    file.write_bytes(b"x" * (limit + 1))
            return file

        with patch.object(context, "CONTEXT_FILE_LIMIT", limit), \
                patch.object(context, "local_file", side_effect=read):
            calls = []
            with self.assertRaisesRegex(context.ContextError, "exceeds 4 MB"):
                context.guarded_continue(self.root, self.policy, calls.append)
            self.assertEqual(calls, [])

    def test_callback_exception_is_not_reported_as_success(self):
        self.persist()

        def failed_callback(evidence):
            raise RuntimeError("downstream failed")

        with self.assertRaisesRegex(RuntimeError, "downstream failed"):
            context.guarded_continue(self.root, self.policy, failed_callback)

    def test_interleaved_attempts_block(self):
        other = copy.deepcopy(self.events[0])
        other["id"] = "GATE-INTERLEAVED"
        other["handoff"]["attempt_id"] = "ATTEMPT-2"
        self.persist(self.events[:3] + [other] + self.events[3:])
        self.assert_blocked()

    def test_malformed_optional_handoff_blocks(self):
        for value in [None, [], {}, {"schema":"future-unknown"}]:
            events = copy.deepcopy(self.events)
            events[4]["handoff"] = value
            self.persist(events)
            self.assert_blocked()

    def test_independent_task_does_not_block_valid_chain(self):
        other = copy.deepcopy(self.events[0])
        other["id"] = "GATE-OTHER-TASK"
        other["handoff"]["task_id"] = "TASK-INDEPENDENT"
        self.persist(self.events + [other])
        calls = []
        context.guarded_continue(self.root, self.policy, calls.append)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
