#!/usr/bin/env python3
"""Verify the complete distribution inventory and run its offline unit tests."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import socket
import sys
import unittest


def verified_payload(root):
    root = Path(root)
    manifest_path = root / "DISTRIBUTION.json"
    if manifest_path.is_symlink():
        raise ValueError("Symlink distribution manifest")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("schema") != "oos-runtime-distribution/1":
        raise ValueError("Unsupported distribution schema")
    files = {"DISTRIBUTION.json": manifest_bytes}
    for item in manifest["files"]:
        path = item["path"]
        pure = PurePosixPath(path)
        if (not path or pure.is_absolute() or ".." in pure.parts or "\\" in path
                or pure.as_posix() != path or path in files):
            raise ValueError("Invalid/duplicate distribution path")
        target = root
        for part in pure.parts:
            target = target / part
            if target.is_symlink():
                raise ValueError("Symlink in distribution: " + path)
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise ValueError("Distribution checksum mismatch: " + path)
        files[path] = data
    if not manifest["files"]:
        raise ValueError("Empty distribution")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*")
              if p.is_file() and "__pycache__" not in p.parts}
    if actual != set(files):
        raise ValueError("Unexpected or missing distribution files")
    return files


def main():
    root = Path(__file__).resolve().parent
    try:
        payload = verified_payload(root)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc)}))
        return 1
    # Offline tests must not consume credentials or opt into live provider calls.
    for name in list(os.environ):
        if name.startswith(("OOS_", "OPENAI_", "GITHUB_", "GH_", "OLLAMA_")):
            del os.environ[name]
    def no_network(*args, **kwargs):
        raise RuntimeError("Network disabled during offline installation verification")
    socket.create_connection = no_network
    socket.socket.connect = no_network
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    success = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
    print(json.dumps({"status": "OFFLINE_RUNTIME_TESTED" if success else "FAILED",
                      "tests": result.testsRun, "skipped": len(result.skipped),
                      "verified_files": len(payload), "live_services": "NOT_CONNECTED"}))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
