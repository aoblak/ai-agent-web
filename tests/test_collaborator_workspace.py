"""Clean-owner isolation and non-destructive local preparation."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("collaborator", ROOT / "scripts/prepare_collaborator_workspace.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CollaboratorChecks(unittest.TestCase):
    def test_clean_owner_full_hierarchy_and_executable_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            result = module.prepare(target, "Fiskalna123/oos-workspace")
            self.assertEqual(result["full_oos_runtime"], "OFFLINE_TESTED_CANDIDATE")
            self.assertEqual(result["runtime_verification"]["status"], "OFFLINE_RUNTIME_TESTED")
            self.assertGreaterEqual(result["runtime_verification"]["tests"], 288)
            self.assertEqual(result["live_handoff"], "NOT_CONNECTED")
            self.assertEqual(len(list((target / "runtime/oos").glob("*.py"))), 17)
            for path, data in module.runtime_payload().items():
                self.assertEqual((target / "runtime" / path).read_bytes(), data)
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

    def test_partial_copy_is_removed_and_the_same_destination_can_be_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            keep = Path(tmp) / "keep.txt"
            keep.write_bytes(b"unrelated")
            files = {"first.txt": b"first", "nested/fail.txt": b"last"}
            original = Path.open
            def fail(path, mode="r", *args, **kwargs):
                if path == target / "nested/fail.txt" and mode == "xb":
                    raise OSError("disk full")
                return original(path, mode, *args, **kwargs)
            with patch.object(Path, "open", new=fail):
                with self.assertRaisesRegex(OSError, "disk full"):
                    module._publish_workspace(target, files)
            self.assertFalse(target.exists())
            self.assertEqual(keep.read_bytes(), b"unrelated")
            module._publish_workspace(target, files)
            self.assertEqual((target / "nested/fail.txt").read_bytes(), b"last")

    def test_readback_failure_removes_only_the_newly_claimed_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            original = Path.read_bytes
            def incorrect(path):
                return b"wrong" if path == target / "file.txt" else original(path)
            with patch.object(Path, "read_bytes", new=incorrect):
                with self.assertRaisesRegex(ValueError, "readback failed"):
                    module._publish_workspace(target, {"file.txt": b"expected"})
            self.assertFalse(target.exists())

    def test_existing_destination_is_not_removed_by_publication_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            history = target / "history.txt"
            history.write_bytes(b"owner history")
            with self.assertRaises(FileExistsError):
                module._publish_workspace(target, {"history.txt": b"overwrite"})
            self.assertEqual(history.read_bytes(), b"owner history")

    def test_replaced_destination_is_not_deleted_during_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "workspace"
            abandoned = Path(tmp) / "original-claim"
            original = Path.open
            def replace_destination(path, mode="r", *args, **kwargs):
                if path == target / "file.txt" and mode == "xb":
                    target.rename(abandoned)
                    target.mkdir()
                    with original(target / "owner.txt", "wb") as out:
                        out.write(b"other writer")
                    raise OSError("interrupted after replacement")
                return original(path, mode, *args, **kwargs)
            with patch.object(Path, "open", new=replace_destination):
                with self.assertRaisesRegex(ValueError, "ownership changed"):
                    module._publish_workspace(target, {"file.txt": b"expected"})
            self.assertEqual((target / "owner.txt").read_bytes(), b"other writer")
            self.assertTrue(abandoned.is_dir())

    def test_tampered_distribution_blocks_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            shutil.copytree(module.RUNTIME_ROOT, runtime, ignore=shutil.ignore_patterns("__pycache__"))
            target = Path(tmp) / "workspace"
            (runtime / "oos/execution.py").write_text("# altered payload\n")
            with patch.object(module, "RUNTIME_ROOT", runtime):
                with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                    module.prepare(target, "Fiskalna123/oos-workspace")
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
