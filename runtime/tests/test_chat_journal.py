import json
import tempfile
import unittest
from pathlib import Path

from oos.chat_journal import ChatJournalWriter, PromotionGate, ChatJournalIngress

class ChatJournalTests(unittest.TestCase):
    def test_append_chain_and_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-1")
            a = j.append_event("user", "message", "hello")
            b = j.append_event("assistant", "message", "world")
            c = j.checkpoint()
            self.assertEqual((a.seq, b.seq, c.seq), (1, 2, 3))
            ok, err = j.verify_chain()
            self.assertTrue(ok, err)

    def test_correction_is_append_only(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-2")
            j.append_event("user", "message", "wrong")
            j.correction(1, "correct", reason="user correction")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["content"], "wrong")
            self.assertEqual(rows[1]["event_type"], "correction")
            self.assertEqual(rows[1]["metadata"]["supersedes_seq"], 1)
            ok, err = j.verify_chain()
            self.assertTrue(ok, err)

    def test_tamper_is_detected(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-3")
            j.append_event("user", "message", "original")
            j.append_event("assistant", "message", "reply")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            rows[0]["content"] = "tampered"
            p.write_text("\n".join(json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for x in rows) + "\n", encoding="utf-8")
            ok, err = j.verify_chain()
            self.assertFalse(ok)
            self.assertIn("hash mismatch", err)

    def test_red_code_c_crash_truncated_tail_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-crash-c")
            j.append_event("user", "message", "before crash")
            good_prefix = p.read_text(encoding="utf-8")
            p.write_text(good_prefix + '{"seq":2,"timestamp":"CRASH', encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                j.verify_chain()

    def test_red_code_c_restart_from_last_valid_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-crash-recover")
            first = j.append_event("user", "message", "before crash")
            good_prefix = p.read_text(encoding="utf-8")
            p.write_text(good_prefix + '{"partial":', encoding="utf-8")

            # Recovery is explicit: preserve damaged bytes separately, restore the
            # last complete newline-terminated prefix, then continue by append.
            damaged = p.read_bytes()
            crash_copy = Path(td) / "chat.ndjson.crash-tail"
            crash_copy.write_bytes(damaged)
            p.write_text(good_prefix, encoding="utf-8")

            j2 = ChatJournalWriter(p, "chat-crash-recover")
            second = j2.append_event("assistant", "message", "after restart")
            self.assertEqual(first.seq, 1)
            self.assertEqual(second.seq, 2)
            ok, err = j2.verify_chain()
            self.assertTrue(ok, err)
            self.assertTrue(crash_copy.exists())

    def test_red_code_d_semantic_laundering_is_blocked_at_write_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-d")
            j.append_event(
                "user",
                "message",
                "Simplify duplicate governance, but preserve legitimate distinct layers: SOT, Journal, Project State, Evidence and Index.",
            )
            j.append_event(
                "assistant",
                "summary",
                "User wants the repository simplified to a minimal canon.",
                metadata={"source_seqs": [1]},
            )
            with self.assertRaisesRegex(ValueError, "direct user event|contradiction_check"):
                j.append_event(
                    "system-event",
                    "promotion",
                    {"accepted_state": "Only a minimal canon remains."},
                    metadata={
                        "source_seqs": [2],
                        "contradiction_check": "not_run",
                        "changes_canon": True,
                        "authorized_by_user": False,
                    },
                )
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)

    def test_red_code_d_summary_only_promotion_never_persists(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-d2")
            j.append_event("user", "message", "Do not remove the Master Journal.")
            j.append_event("assistant", "summary", "Reduce documentation surface.")
            with self.assertRaisesRegex(ValueError, "direct user event"):
                j.append_event(
                    "system-event",
                    "promotion",
                    "Master Journal removed as redundant.",
                    metadata={
                        "source_seqs": [2],
                        "contradiction_check": "pass",
                        "changes_canon": True,
                        "authorized_by_user": True,
                    },
                )

    def test_red_code_d_promotion_gate_rejects_summary_only_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-gate")
            j.append_event("user", "message", "Preserve the Master Journal.")
            j.append_event("assistant", "summary", "Reduce documentation surface.")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            candidate = {
                "event_type": "promotion",
                "metadata": {
                    "source_seqs": [2],
                    "contradiction_check": "pass",
                    "changes_canon": True,
                    "authorized_by_user": True,
                },
            }
            ok, err = PromotionGate.validate(rows, candidate)
            self.assertFalse(ok)
            self.assertIn("direct user event", err)

    def test_red_code_d_canon_change_cannot_omit_earlier_user_directive(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-omit")
            j.append_event("user", "message", "Preserve the Master Journal.")
            j.append_event("user", "message", "Proceed with the cleanup.")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            candidate = {
                "event_type": "promotion",
                "content": "Master Journal removed as redundant.",
                "metadata": {
                    "source_seqs": [2],
                    "contradiction_check": "pass",
                    "changes_canon": True,
                    "authorized_by_user": True,
                },
            }
            ok, err = PromotionGate.validate(rows, candidate)
            self.assertFalse(ok)
            self.assertIn("omits prior user events", err)

            with self.assertRaisesRegex(ValueError, "omits prior user events"):
                j.append_event(
                    "system-event",
                    "promotion",
                    candidate["content"],
                    metadata=candidate["metadata"],
                )
            persisted = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(persisted), 2)

    def test_red_code_d_canon_change_accepts_complete_user_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-complete")
            j.append_event("user", "message", "Preserve the Master Journal.")
            j.append_event("user", "message", "Also preserve the Evidence layer.")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            candidate = {
                "event_type": "promotion",
                "metadata": {
                    "source_seqs": [1, 2],
                    "contradiction_check": "pass",
                    "changes_canon": True,
                    "authorized_by_user": True,
                    "external_state_claim": False,
                },
            }
            ok, err = PromotionGate.validate(rows, candidate)
            self.assertTrue(ok, err)

    def test_red_code_d_promotion_gate_requires_contradiction_check(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-gate-2")
            j.append_event("user", "message", "Preserve legitimate distinct layers.")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            candidate = {
                "event_type": "promotion",
                "metadata": {
                    "source_seqs": [1],
                    "contradiction_check": "not_run",
                    "changes_canon": True,
                    "authorized_by_user": True,
                },
            }
            ok, err = PromotionGate.validate(rows, candidate)
            self.assertFalse(ok)
            self.assertIn("contradiction_check", err)

    def test_red_code_d_promotion_gate_requires_user_authorization_for_canon_change(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-gate-3")
            j.append_event("user", "message", "Review this proposal.")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            candidate = {
                "event_type": "promotion",
                "metadata": {
                    "source_seqs": [1],
                    "contradiction_check": "pass",
                    "changes_canon": True,
                    "authorized_by_user": False,
                },
            }
            ok, err = PromotionGate.validate(rows, candidate)
            self.assertFalse(ok)
            self.assertIn("authorization", err)

    def test_red_code_d_promotion_gate_accepts_fully_bound_authorized_promotion(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "chat.ndjson"
            j = ChatJournalWriter(p, "chat-semantic-gate-4")
            j.append_event("user", "message", "Promote this exact rule into canon.")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            candidate = {
                "event_type": "promotion",
                "metadata": {
                    "source_seqs": [1],
                    "contradiction_check": "pass",
                    "changes_canon": True,
                    "authorized_by_user": True,
                    "external_state_claim": False,
                },
            }
            ok, err = PromotionGate.validate(rows, candidate)
            self.assertTrue(ok, err)

    def test_ingress_auto_creates_journal_on_first_event(self):
        with tempfile.TemporaryDirectory() as td:
            ingress = ChatJournalIngress(td)
            result = ingress.ingest("chat-new", "user", "message", "first")
            p = ingress.journal_path("chat-new")
            self.assertTrue(p.exists())
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows[0]["event_type"], "session_open")
            self.assertEqual(rows[1]["content"], "first")
            self.assertEqual(result.seq, 2)
            ok, err = ingress.verify_chat("chat-new")
            self.assertTrue(ok, err)

    def test_ingress_reuses_same_journal_without_second_session_open(self):
        with tempfile.TemporaryDirectory() as td:
            ingress = ChatJournalIngress(td)
            ingress.ingest("chat-same", "user", "message", "one")
            ingress.ingest("chat-same", "assistant", "message", "two")
            rows = [json.loads(x) for x in ingress.journal_path("chat-same").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["event_type"] for r in rows].count("session_open"), 1)
            self.assertEqual([r["seq"] for r in rows], [1,2,3])

    def test_ingress_separates_different_chat_ids(self):
        with tempfile.TemporaryDirectory() as td:
            ingress = ChatJournalIngress(td)
            ingress.ingest("chat-a", "user", "message", "A")
            ingress.ingest("chat-b", "user", "message", "B")
            self.assertNotEqual(ingress.journal_path("chat-a"), ingress.journal_path("chat-b"))
            self.assertTrue(ingress.verify_chat("chat-a")[0])
            self.assertTrue(ingress.verify_chat("chat-b")[0])

    def test_ingress_refuses_append_to_corrupted_existing_journal(self):
        with tempfile.TemporaryDirectory() as td:
            ingress = ChatJournalIngress(td)
            ingress.ingest("chat-corrupt", "user", "message", "good")
            p = ingress.journal_path("chat-corrupt")
            rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
            rows[1]["content"] = "tampered"
            p.write_text("\n".join(json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for x in rows)+"\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing append to corrupted journal"):
                ingress.ingest("chat-corrupt", "assistant", "message", "must not append")

    def test_lossy_chat_ids_and_matching_safe_labels_remain_separate(self):
        with tempfile.TemporaryDirectory() as td:
            ingress = ChatJournalIngress(td)
            ids = ("chat/a", "chat?a", "chat_a")
            for chat_id in ids:
                ingress.ingest(chat_id, "user", "message", {"text": chat_id})
            paths = [ingress.journal_path(chat_id) for chat_id in ids]
            self.assertEqual(len(set(paths)), 3)
            for chat_id, path in zip(ids, paths):
                self.assertTrue(ChatJournalWriter(path, chat_id).verify_chain()[0])

    def test_legacy_journal_is_reused_only_by_its_original_identity(self):
        with tempfile.TemporaryDirectory() as td:
            legacy = Path(td) / "chat_a.ndjson"
            writer = ChatJournalWriter(legacy, "chat/a")
            writer.append_event("user", "message", {"text": "original"})
            before = legacy.read_bytes()
            ingress = ChatJournalIngress(td)
            self.assertEqual(ingress.journal_path("chat/a"), legacy)
            ingress.ingest("chat?a", "user", "message", {"text": "other chat"})
            self.assertEqual(legacy.read_bytes(), before)
            self.assertNotEqual(ingress.journal_path("chat?a"), legacy)
            ingress.ingest("chat/a", "user", "message", {"text": "continuation"})
            self.assertTrue(legacy.read_bytes().startswith(before))

    def test_long_chat_identity_produces_a_bounded_filename(self):
        with tempfile.TemporaryDirectory() as td:
            ingress = ChatJournalIngress(td)
            chat_id = "long/" + "x" * 1000
            ingress.ingest(chat_id, "user", "message", {"text": "record"})
            path = ingress.journal_path(chat_id)
            self.assertLess(len(path.name.encode()), 255)
            self.assertTrue(ChatJournalWriter(path, chat_id).verify_chain()[0])

    def test_no_update_or_delete_api(self):
        self.assertFalse(hasattr(ChatJournalWriter, "update"))
        self.assertFalse(hasattr(ChatJournalWriter, "delete"))

if __name__ == "__main__":
    unittest.main()
