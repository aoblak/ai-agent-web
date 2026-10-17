import argparse
import hashlib
import hmac
import importlib.util
import json
import os
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
    def _run_webhook(self, db, body, *, secret=None, signature=None, payload_path=None):
        cmd = [sys.executable, str(ROOT / "scripts/github_signal_ingest_webhook.py"),
               "--db", str(db), "--event", "star", "--delivery", "signed-delivery-1"]
        if signature is not None:
            cmd.extend(["--signature", signature])
        if payload_path is not None:
            payload_path.write_bytes(body)
            cmd.extend(["--payload", str(payload_path)])
        env = os.environ.copy()
        env.pop("GITHUB_WEBHOOK_SECRET", None)
        if secret is not None:
            env["GITHUB_WEBHOOK_SECRET"] = secret
        return subprocess.run(cmd, input=None if payload_path is not None else body,
                              capture_output=True, env=env)

    def test_webhook_rejects_missing_secret_signature_or_tampered_bytes_before_write(self):
        body = (b'{  "action":"created", "sender":{"login":"visitor"}, '
                b'"repository":{"full_name":"owner/repo"},'
                b'"starred_at":"2026-09-01T00:00:00Z" }\\n')
        signature = "sha256=" + hmac.new(b"correct-secret", body, hashlib.sha256).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "signals.sqlite"
            for kwargs in (
                {"secret": None, "signature": signature},
                {"secret": "correct-secret", "signature": None},
                {"secret": "wrong-secret", "signature": signature},
                {"secret": "correct-secret", "signature": "sha256=not-a-digest"},
            ):
                result = self._run_webhook(db, body, **kwargs)
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertFalse(db.exists())
            changed = body.replace(b'"created"', b'"deleted"')
            result = self._run_webhook(db, changed, secret="correct-secret", signature=signature)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(db.exists())
            self.assertNotIn(b"correct-secret", result.stderr)

    def test_webhook_accepts_exact_raw_signed_bytes_and_deduplicates_delivery(self):
        body = (b'{  "action":"created", "sender":{"login":"visitor"}, '
                b'"repository":{"full_name":"owner/repo"},'
                b'"starred_at":"2026-09-01T00:00:00Z" }\\n')
        signature = "sha256=" + hmac.new(b"correct-secret", body, hashlib.sha256).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "signals.sqlite"
            path = Path(tmp) / "payload.json"
            for _ in range(2):
                result = self._run_webhook(db, body, secret="correct-secret",
                                           signature=signature, payload_path=path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["status"], "PASS")
            with GitHubSignalStore(db) as store:
                self.assertEqual(store.conn.execute(
                    "SELECT COUNT(*) FROM github_raw_events").fetchone()[0], 1)

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
