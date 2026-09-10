"""Regression checks for context loss, accidental disclosure and stale manifests."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("oos_context", PACKAGE / "scripts/oos_context.py")
context = importlib.util.module_from_spec(spec)
spec.loader.exec_module(context)


class ContextChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        manifest = json.loads((PACKAGE / context.INDEX).read_text())
        for name in [d["path"] for d in manifest["documents"]] + [context.INDEX]:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PACKAGE / name, target)

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, str(self.root / "scripts/oos_context.py"),
                               "--root", str(self.root), *args], capture_output=True, text=True)

    def alter_index(self, update):
        p = self.root / context.INDEX
        data = json.loads(p.read_text())
        update(data)
        p.write_text(json.dumps(data))

    def add_event(self, **updates):
        meta = dict(id="TEST-0001", recorded_at="2026-09-08T10:00:00Z", occurred_at=None,
                    actor="unit-test", topics=["example"], status="NEEDS-REVIEW", visibility="PUBLIC")
        meta.update(updates)
        text = "<!-- oos:event " + json.dumps(meta) + " -->\n"
        text += "## " + meta["id"] + " — Recorded example\n"
        for field in context.FIELDS:
            text += field + ": NOT-RUN; test fixture only.\n"
        text += "<!-- /oos:event -->\n"
        with (self.root / "docs/MASTER_JOURNAL.md").open("a") as stream:
            stream.write(text)

    def test_pristine_package_validates(self):
        result = self.cli("validate")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_missing_document_is_reported(self):
        (self.root / "docs/GLOSSARY.md").unlink()
        result = self.cli("validate")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Missing context file", result.stdout)

    def test_manual_edit_requires_index_refresh(self):
        p = self.root / "docs/PROJECT_STATE.md"
        p.write_text(p.read_text() + "\nA new reviewed next action.\n")
        self.assertNotEqual(0, self.cli("validate").returncode)
        self.assertEqual(0, self.cli("reindex", "--write").returncode)
        self.assertEqual(0, self.cli("validate").returncode)

    def test_reindex_preview_is_read_only(self):
        before = (self.root / context.INDEX).read_bytes()
        result = self.cli("reindex")
        self.assertEqual(0, result.returncode)
        self.assertEqual(before, (self.root / context.INDEX).read_bytes())

    def test_unknown_topic_is_explicit_gap(self):
        result = self.cli("bootstrap", "--topic", "no-such-topic-7bd9")
        self.assertEqual(0, result.returncode)
        self.assertIn("UNKNOWN", json.loads(result.stdout)["context_gap"])

    def test_public_context_rejects_private_event_even_during_refresh(self):
        self.alter_index(lambda index: index["project"].update(visibility="PUBLIC"))
        self.add_event(visibility="PRIVATE")
        result = self.cli("reindex", "--write")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("non-public journal entry", result.stdout)

    def test_public_context_rejects_private_source_locator(self):
        self.alter_index(lambda index: (index["project"].update(visibility="PUBLIC"),
                         index["sources"].append(dict(id="private", status="UNKNOWN", visibility="PRIVATE", locator=None))))
        self.assertNotEqual(0, self.cli("validate").returncode)

    def test_duplicate_event_ids_fail(self):
        self.add_event()
        self.add_event()
        result = self.cli("reindex", "--write")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("duplicate journal event ID", result.stdout)

    def test_verified_event_requires_three_recorded_checks(self):
        self.add_event(status="VERIFIED")
        result = self.cli("reindex", "--write")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("VERIFIED requires PASS", result.stdout)

    def test_naive_recording_time_fails(self):
        self.add_event(recorded_at="2026-09-08T10:00:00")
        self.assertNotEqual(0, self.cli("reindex", "--write").returncode)

    def test_external_path_is_not_read(self):
        self.alter_index(lambda index: index["documents"].append(
            dict(path="../outside.txt", visibility="PUBLIC", sha256="ignored")))
        result = self.cli("validate")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Path escapes", result.stdout)

    def test_symlink_is_rejected(self):
        original = self.root / "docs/GLOSSARY.md"
        backup = self.root / "glossary-copy.md"
        original.rename(backup)
        original.symlink_to(backup)
        result = self.cli("validate")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("symlinks", result.stdout)

    def test_unresolved_command_cannot_be_marked_verified_without_definition(self):
        self.alter_index(lambda index: index["glossary"]["GS"].update(status="VERIFIED", meaning=None))
        self.assertNotEqual(0, self.cli("validate").returncode)

    def test_unterminated_event_is_not_ignored(self):
        with (self.root / "docs/MASTER_JOURNAL.md").open("a") as stream:
            stream.write('<!-- oos:event {"id":"TEST-9999"} -->\n')
        self.assertNotEqual(0, self.cli("reindex", "--write").returncode)

    def test_conflicting_writer_lock_leaves_index_unchanged(self):
        before = (self.root / context.INDEX).read_bytes()
        (self.root / "docs/.oos-index.lock").write_text("active writer")
        self.assertNotEqual(0, self.cli("reindex", "--write").returncode)
        self.assertEqual(before, (self.root / context.INDEX).read_bytes())

    def test_matching_events_are_bounded_and_indexed_from_journal(self):
        self.add_event(id="TEST-0001")
        self.add_event(id="TEST-0002", recorded_at="2026-09-08T11:00:00Z")
        self.assertEqual(0, self.cli("reindex", "--write").returncode)
        result = self.cli("bootstrap", "--topic", "example", "--max-entries", "1")
        data = json.loads(result.stdout)
        self.assertEqual(2, data["matching_entries"])
        self.assertTrue(data["truncated"])
        self.assertEqual("TEST-0002", data["journal_matches"][0]["locator"]["id"])


if __name__ == "__main__":
    unittest.main()
