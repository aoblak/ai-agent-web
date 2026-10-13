"""Clean-owner isolation and non-destructive local preparation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collaborator", ROOT / "scripts/prepare_collaborator_workspace.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CollaboratorChecks(unittest.TestCase):
    def test_clean_owner_full_hierarchy_and_executable_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            result = module.prepare(target, "Fiskalna123/oos-workspace")
            self.assertEqual(result["full_oos_runtime"], "NOT_INSTALLED")
            index = json.loads((target / "docs/INDEX.json").read_text())
            self.assertEqual(index["source_priority"], module.PRIORITY)
            self.assertEqual(index["journal_entries"], [])
            self.assertEqual(index["project"]["name"], "Fiskalna123/oos-workspace")
            self.assertEqual(index["project"]["visibility"], "PRIVATE")
            self.assertEqual([s["id"] for s in index["sources"]], ["public-oos-context-code"])
            self.assertNotIn("CTX-2026", (target / "docs/MASTER_JOURNAL.md").read_text())
            self.assertFalse((target / "JOURNAL.md").exists())
            self.assertFalse((target / "registry/state.yaml").exists())
            self.assertEqual((target / "scripts/oos_context.py").read_bytes(), module.source_bytes("scripts/oos_context.py"))
            command = [sys.executable, str(target / "scripts/oos_context.py"), "--root", str(target)]
            self.assertEqual(subprocess.run(command + ["validate"], capture_output=True).returncode, 0)
            (target / "docs/KNOWLEDGE.md").write_text("unindexed change")
            self.assertNotEqual(subprocess.run(command + ["validate"], capture_output=True).returncode, 0)

    def test_existing_store_and_symlink_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "existing"
            target.mkdir()
            original = target / "JOURNAL.md"
            original.write_text("Owner history")
            link = root / "alias"
            link.symlink_to(target, target_is_directory=True)
            for path in (target, link):
                with self.assertRaises(ValueError):
                    module.prepare(path, "Fiskalna123/oos-workspace")
            self.assertEqual(original.read_text(), "Owner history")
            self.assertEqual(list(target.iterdir()), [original])

    def test_invalid_destination_identity_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            for name in ("https://github.com/user/repo", "user/..", "../x", "[OWNER]/[REPO]"):
                with self.assertRaises(ValueError):
                    module.prepare(target, name)
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
