import tempfile
import unittest
from pathlib import Path

from oos.github_signal_ingester import (
    GitHubSignalError,
    GitHubSignalStore,
    RawGitHubEvent,
    normalize_github_event,
)


class GitHubSignalIngesterTests(unittest.TestCase):
    def event(
        self,
        *,
        transport="webhook",
        event_type="star",
        action="created",
        actor="someone",
        object_type="repository",
        object_id="example-owner/repo",
        payload=None,
    ):
        return RawGitHubEvent(
            transport=transport,
            event_type=event_type,
            action=action,
            actor=actor,
            object_type=object_type,
            object_id=object_id,
            occurred_at="2026-09-25T00:00:00Z",
            payload=payload or {},
        )

    def test_events_api_watchevent_is_star_not_watch(self):
        signal = normalize_github_event(
            self.event(
                transport="events_api",
                event_type="WatchEvent",
                action="started",
            )
        )
        self.assertEqual(signal.canonical_action, "STAR")
        self.assertEqual(signal.semantic_class, "OBJECT_MARKED")

    def test_webhook_watch_is_stream_subscription(self):
        signal = normalize_github_event(
            self.event(event_type="watch", action="started")
        )
        self.assertEqual(signal.canonical_action, "WATCH")
        self.assertEqual(signal.semantic_class, "STREAM_SUBSCRIBED")

    def test_star_removal_is_not_a_negative_evaluation(self):
        signal = normalize_github_event(
            self.event(
                transport="poller",
                event_type="star",
                action="removed",
            )
        )
        self.assertEqual(signal.canonical_action, "UNSTAR")
        self.assertEqual(signal.semantic_class, "OBJECT_UNMARKED")
        self.assertIsNone(signal.evaluation)

    def test_follow_poller_marks_person(self):
        signal = normalize_github_event(
            self.event(
                transport="poller",
                event_type="follow",
                action="added",
                object_type="user",
                object_id="danielmiessler",
            )
        )
        self.assertEqual(signal.canonical_action, "FOLLOW")
        self.assertEqual(signal.semantic_class, "PERSON_MARKED")
        self.assertEqual(signal.actor_relation, "UNKNOWN")

    def test_fork_is_work_intent_marker_not_adoption(self):
        signal = normalize_github_event(
            self.event(event_type="fork", action="created")
        )
        self.assertEqual(signal.canonical_action, "FORK")
        self.assertEqual(signal.semantic_class, "WORK_INTENT_MARKER")
        self.assertNotIn("ADOPT", signal.semantic_class)

    def test_review_is_concrete_evaluation(self):
        signal = normalize_github_event(
            self.event(
                event_type="pull_request_review",
                action="submitted",
                object_type="pull_request",
                object_id="example-owner/repo#42",
                payload={"review": {"state": "approved"}},
            )
        )
        self.assertEqual(signal.canonical_action, "REVIEW")
        self.assertEqual(signal.semantic_class, "CONCRETE_EVALUATION")
        self.assertEqual(signal.evaluation, "APPROVED")

    def test_self_star_is_marker_not_independent_evaluation(self):
        signal = normalize_github_event(
            self.event(actor="example-owner", object_id="example-owner/repo")
        )
        self.assertEqual(signal.actor_relation, "SELF")
        self.assertEqual(signal.canonical_action, "STAR")
        self.assertIsNone(signal.evaluation)

    def test_external_star_is_external_interest_edge(self):
        signal = normalize_github_event(
            self.event(actor="example-user", object_id="example-owner/repo")
        )
        self.assertEqual(signal.actor_relation, "EXTERNAL")
        self.assertEqual(signal.semantic_class, "OBJECT_MARKED")

    def test_unknown_event_fails_closed(self):
        with self.assertRaises(GitHubSignalError):
            normalize_github_event(
                self.event(event_type="mystery", action="created")
            )

    def test_unknown_event_can_be_preserved_without_asserting_signal(self):
        with tempfile.TemporaryDirectory() as temp:
            store = GitHubSignalStore(Path(temp) / "signals.sqlite")
            try:
                event = self.event(event_type="mystery", action="created")
                with self.assertRaises(GitHubSignalError):
                    store.ingest(event)
                count = store.conn.execute(
                    "SELECT COUNT(*) FROM github_raw_events"
                ).fetchone()[0]
                signal_count = store.conn.execute(
                    "SELECT COUNT(*) FROM github_signals"
                ).fetchone()[0]
                self.assertEqual(count, 1)
                self.assertEqual(signal_count, 0)
            finally:
                store.close()

    def test_non_submitted_review_fails_closed(self):
        with self.assertRaises(GitHubSignalError):
            normalize_github_event(
                self.event(
                    event_type="pull_request_review",
                    action="edited",
                    object_type="pull_request",
                    object_id="example-owner/repo#1",
                    payload={"review": {"state": "approved"}},
                )
            )

    def test_store_preserves_raw_event_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            store = GitHubSignalStore(Path(temp) / "signals.sqlite")
            try:
                event = self.event(
                    actor="example-user",
                    payload={"repository": {"full_name": "example-owner/repo"}},
                )
                first = store.ingest(event)
                second = store.ingest(event)

                self.assertFalse(first.duplicate)
                self.assertTrue(second.duplicate)
                self.assertEqual(first.raw_event_id, second.raw_event_id)
                self.assertEqual(first.signal_id, second.signal_id)

                raw = store.raw_event(first.raw_event_id)
                signal = store.signal(first.signal_id)
                self.assertEqual(raw["event_type"], "star")
                self.assertEqual(raw["payload"]["repository"]["full_name"], "example-owner/repo")
                self.assertEqual(signal["canonical_action"], "STAR")
                self.assertNotIn("score", signal)
                self.assertNotIn("intent", raw)
            finally:
                store.close()

    def test_poll_snapshot_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            store = GitHubSignalStore(Path(temp) / "signals.sqlite")
            try:
                initialized, snapshot = store.poll_snapshot("follow")
                self.assertFalse(initialized)
                self.assertEqual(snapshot, {})
                store.replace_poll_snapshot(
                    "follow",
                    {"person": {"login": "person"}},
                    observed_at="2026-09-25T01:00:00Z",
                )
                initialized, snapshot = store.poll_snapshot("follow")
                self.assertTrue(initialized)
                self.assertEqual(snapshot["person"]["login"], "person")
            finally:
                store.close()

    def test_payload_must_be_json_serializable(self):
        event = self.event(payload={"bad": object()})
        with self.assertRaises(GitHubSignalError):
            event.canonical_payload_json()


if __name__ == "__main__":
    unittest.main()
