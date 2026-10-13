import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from oos.github_signal_adapter import (
    GitHubAdapterError,
    GitHubRestClient,
    GitHubSignalSynchronizer,
    HttpResponse,
    ingest_webhook,
    raw_event_from_webhook,
)
from oos.github_signal_ingester import GitHubSignalStore


class FakeTransport:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, method, url, headers):
        self.calls.append((method, url, dict(headers)))
        return self.handler(method, url, headers)


def response(payload, status=200):
    return HttpResponse(
        status=status,
        headers={},
        body=json.dumps(payload).encode("utf-8"),
    )


class GitHubRestClientTests(unittest.TestCase):
    def test_star_endpoint_is_read_only_and_requests_timestamp_media_type(self):
        def handler(method, url, headers):
            self.assertEqual(method, "GET")
            self.assertIn("/user/starred", url)
            self.assertEqual(headers["Accept"], "application/vnd.github.star+json")
            return response(
                [
                    {
                        "starred_at": "2026-09-01T10:00:00Z",
                        "repo": {"full_name": "x/y"},
                    }
                ]
            )

        fake = FakeTransport(handler)
        client = GitHubRestClient("token", transport=fake)
        starred = client.list_starred()
        self.assertIn("x/y", starred)
        self.assertEqual(starred["x/y"]["starred_at"], "2026-09-01T10:00:00Z")
        self.assertTrue(all(call[0] == "GET" for call in fake.calls))

    def test_following_uses_authenticated_endpoint(self):
        def handler(method, url, headers):
            self.assertEqual(urlparse(url).path, "/user/following")
            return response([{"login": "person-a"}])

        client = GitHubRestClient("token", transport=FakeTransport(handler))
        self.assertEqual(set(client.list_following()), {"person-a"})

    def test_repository_enrichment_is_read_only(self):
        def handler(method, url, headers):
            self.assertEqual(method, "GET")
            self.assertEqual(urlparse(url).path, "/repos/a/b")
            return response(
                {
                    "full_name": "a/b",
                    "owner": {"login": "a"},
                    "private": False,
                    "fork": False,
                    "archived": False,
                    "disabled": False,
                    "visibility": "public",
                    "language": "Python",
                    "topics": [],
                    "license": {"spdx_id": "MIT"},
                    "stargazers_count": 1,
                    "forks_count": 0,
                    "open_issues_count": 0,
                    "pushed_at": None,
                    "updated_at": None,
                }
            )

        client = GitHubRestClient("token", transport=FakeTransport(handler))
        metadata = client.get_repository("a/b")
        self.assertEqual(metadata["license_spdx"], "MIT")
        self.assertNotIn("license_compatible", metadata)

    def test_watch_is_checked_per_repository(self):
        def handler(method, url, headers):
            self.assertEqual(urlparse(url).path, "/repos/a/b/subscription")
            return response({"subscribed": True})

        client = GitHubRestClient("token", transport=FakeTransport(handler))
        self.assertTrue(client.is_watching("a/b"))

    def test_watch_404_means_not_subscribed(self):
        def handler(method, url, headers):
            return response({"message": "Not Found"}, status=404)

        client = GitHubRestClient("token", transport=FakeTransport(handler))
        self.assertFalse(client.is_watching("a/b"))

    def test_token_is_required(self):
        with self.assertRaises(GitHubAdapterError):
            GitHubRestClient("")


class GitHubSignalSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = GitHubSignalStore(Path(self.temp.name) / "signals.sqlite")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_star_baseline_uses_starred_at_and_emits_historical_marker(self):
        class Client:
            def list_starred(self):
                return {
                    "owner/repo": {
                        "starred_at": "2026-09-01T10:00:00Z",
                        "item": {"repo": {"full_name": "owner/repo"}},
                    }
                }

        summary = GitHubSignalSynchronizer(
            Client(), self.store, actor="example-owner"
        ).sync_stars(observed_at="2026-09-25T01:00:00Z")
        self.assertTrue(summary.baseline)
        self.assertEqual(summary.emitted, 1)
        row = self.store.conn.execute(
            "SELECT occurred_at FROM github_raw_events"
        ).fetchone()
        self.assertEqual(row["occurred_at"], "2026-09-01T10:00:00Z")

    def test_follow_baseline_does_not_fabricate_history(self):
        class Client:
            def list_following(self):
                return {"person": {"item": {"login": "person"}}}

        sync = GitHubSignalSynchronizer(Client(), self.store, actor="example-owner")
        first = sync.sync_following(observed_at="2026-09-25T01:00:00Z")
        self.assertTrue(first.baseline)
        self.assertEqual(first.emitted, 0)
        count = self.store.conn.execute(
            "SELECT COUNT(*) FROM github_signals"
        ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_follow_diff_emits_follow_and_unfollow(self):
        class Client:
            following = {"one": {"item": {"login": "one"}}}
            def list_following(self):
                return self.following

        client = Client()
        sync = GitHubSignalSynchronizer(client, self.store, actor="example-owner")
        sync.sync_following(observed_at="2026-09-25T01:00:00Z")
        client.following = {"two": {"item": {"login": "two"}}}
        second = sync.sync_following(observed_at="2026-09-25T02:00:00Z")
        self.assertEqual(second.emitted, 2)
        actions = {
            row["canonical_action"]
            for row in self.store.conn.execute(
                "SELECT canonical_action FROM github_signals"
            ).fetchall()
        }
        self.assertEqual(actions, {"FOLLOW", "UNFOLLOW"})

    def test_watch_baseline_then_change(self):
        class Client:
            watched = False
            def is_watching(self, repository):
                return self.watched

        client = Client()
        sync = GitHubSignalSynchronizer(client, self.store, actor="example-owner")
        first = sync.sync_watch_targets(
            ["owner/repo"], observed_at="2026-09-25T01:00:00Z"
        )
        self.assertEqual(first.emitted, 0)
        client.watched = True
        second = sync.sync_watch_targets(
            ["owner/repo"], observed_at="2026-09-25T02:00:00Z"
        )
        self.assertEqual(second.emitted, 1)
        action = self.store.conn.execute(
            "SELECT canonical_action FROM github_signals"
        ).fetchone()[0]
        self.assertEqual(action, "WATCH")


class WebhookTests(unittest.TestCase):
    def base_payload(self):
        return {
            "repository": {"full_name": "example-owner/repo"},
            "sender": {"login": "someone"},
        }

    def test_fork_webhook_has_no_provider_action_but_maps_to_creation(self):
        payload = self.base_payload()
        payload["forkee"] = {"full_name": "someone/repo"}
        event = raw_event_from_webhook(
            "fork",
            payload,
            delivery_id="delivery-1",
            received_at="2026-09-25T01:00:00Z",
        )
        self.assertEqual(event.action, "created")
        self.assertNotIn("action", event.payload)

    def test_star_delete_is_marker_removal_not_negative_review(self):
        payload = self.base_payload()
        payload.update({"action": "deleted", "starred_at": None})
        with tempfile.TemporaryDirectory() as temp:
            store = GitHubSignalStore(Path(temp) / "signals.sqlite")
            try:
                stored = ingest_webhook(
                    store,
                    "star",
                    payload,
                    delivery_id="delivery-2",
                    received_at="2026-09-25T01:00:00Z",
                )
                self.assertEqual(stored.normalized.canonical_action, "UNSTAR")
                self.assertEqual(
                    stored.normalized.semantic_class,
                    "OBJECT_UNMARKED",
                )
                self.assertIsNone(stored.normalized.evaluation)
            finally:
                store.close()

    def test_review_uses_submitted_timestamp(self):
        payload = self.base_payload()
        payload.update(
            {
                "action": "submitted",
                "pull_request": {"number": 42},
                "review": {
                    "state": "approved",
                    "submitted_at": "2026-09-25T00:55:00Z",
                },
            }
        )
        event = raw_event_from_webhook(
            "pull_request_review",
            payload,
            delivery_id="delivery-3",
            received_at="2026-09-25T01:00:00Z",
        )
        self.assertEqual(event.object_id, "example-owner/repo#42")
        self.assertEqual(event.occurred_at, "2026-09-25T00:55:00Z")


if __name__ == "__main__":
    unittest.main()
