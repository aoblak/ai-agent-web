import tempfile
import unittest
from pathlib import Path

from oos.turboai_security import (
    TurboAISecurityError,
    require_session_owner,
    resolve_upload_destination,
    validate_production_secret,
)


class TurboAISecurityTests(unittest.TestCase):
    def test_default_secret_is_rejected(self) -> None:
        with self.assertRaises(TurboAISecurityError):
            validate_production_secret("change-me")

    def test_short_secret_is_rejected(self) -> None:
        with self.assertRaises(TurboAISecurityError):
            validate_production_secret("not-long-enough")

    def test_strong_secret_is_accepted(self) -> None:
        secret = "a-unique-production-secret-with-more-than-32-characters"
        self.assertEqual(validate_production_secret(secret), secret)

    def test_cross_owner_session_access_is_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            require_session_owner(actor_id="bob", owner_id="alice")

    def test_session_owner_is_allowed(self) -> None:
        require_session_owner(actor_id="alice", owner_id="alice")

    def test_traversal_and_nested_upload_paths_are_rejected(self) -> None:
        filenames = [
            "../../escaped.txt",
            "../escaped.txt",
            "/tmp/escaped.txt",
            "nested/file.txt",
            r"nested\file.txt",
            "..",
            ".",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "uploads"
            for filename in filenames:
                with self.subTest(filename=filename):
                    with self.assertRaises(TurboAISecurityError):
                        resolve_upload_destination(root, filename)

    def test_safe_upload_stays_under_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "uploads"
            destination = resolve_upload_destination(root, "document.txt")
            self.assertEqual(destination, root.resolve() / "document.txt")
            self.assertTrue(destination.is_relative_to(root.resolve()))


if __name__ == "__main__":
    unittest.main()
