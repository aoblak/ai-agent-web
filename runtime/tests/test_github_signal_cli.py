import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from oos.github_signal_ingester import GitHubSignalStore, RawGitHubEvent

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("signal_sync_cli", ROOT / "scripts/github_signal_sync.py")
sync_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_cli)


class SignalCliTests(unittest.TestCase):
    def test_wrong_actor_blocks_before_creating_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(db=Path(tmp) / "signals.sqlite", actor="WrongOwner",
                                      stars=False, follows=True, watch=[])
            client = Mock()
            client.authenticated_login.return_value = "ActualOwner"
            with patch.object(sync_cli, "parse_args", return_value=args), \
                    patch.object(sync_cli, "GitHubRestClient", return_value=client), \
                    patch.object(sync_cli, "GitHubSignalStore") as store, \
                    patch("sys.stderr"):
                self.assertEqual(sync_cli.main(), 2)
                store.assert_not_called()
                client.list_following.assert_not_called()
                self.assertFalse(args.db.exists())

    def test_case_insensitive_actor_uses_canonical_provider_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(db=Path(tmp) / "signals.sqlite", actor="actualowner",
                                      stars=False, follows=True, watch=[])
            client = Mock()
            client.authenticated_login.return_value = "ActualOwner"
            client.list_following.return_value = {}
            original = sync_cli.GitHubSignalSynchronizer
            with patch.object(sync_cli, "parse_args", return_value=args), \
                    patch.object(sync_cli, "GitHubRestClient", return_value=client), \
                    patch.object(sync_cli, "GitHubSignalSynchronizer", wraps=original) as sync, \
                    patch("sys.stdout"):
                self.assertEqual(sync_cli.main(), 0)
                self.assertEqual(sync.call_args.kwargs["actor"], "ActualOwner")

    def test_analysis_cli_excludes_withdrawn_patterns_but_retains_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "signals.sqlite"

            def ingest(event_type, action, when):
                with GitHubSignalStore(db) as store:
                    store.ingest(RawGitHubEvent(
                        transport="poller", event_type=event_type, action=action,
                        actor="me", object_type="repository", object_id="owner/repo",
                        occurred_at=when, payload={}))

            def run():
                result = subprocess.run([sys.executable, str(ROOT / "scripts/github_signal_analyze.py"),
                                         "--db", str(db)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)

            ingest("star", "added", "2026-09-25T01:00:00Z")
            ingest("watch", "added", "2026-09-25T01:01:00Z")
            self.assertEqual(len(run()["patterns"]), 1)
            ingest("star", "removed", "2026-09-25T01:02:00Z")
            result = run()
            self.assertEqual(result["detected"], 0)
            self.assertEqual(result["patterns"], [])
            with GitHubSignalStore(db) as store:
                self.assertEqual(len(store.patterns()), 1)
                self.assertEqual(len(store.signal_rows()), 3)


if __name__ == "__main__":
    unittest.main()
