#!/usr/bin/env python3
"""Non-destructive storage bootstrap installer.

Creates minimal agent-arrival files and a bounded storage index. It does not recurse by
default, does not delete/move/rename existing content, and refuses to overwrite unless
--force is supplied.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.1.0"

START = """# AI START HERE\n\nRead `STORAGE_MANIFEST.md`, `STORAGE_INDEX.json`, and any more specific repository/project `AGENTS.md`. Perform a runtime capability handshake. Use progressive discovery. Do not move, rename, delete, deduplicate or reorganize during discovery without explicit authorization. Reuse existing canonical journals/state/task systems; do not create parallel ones.\n"""

AGENTS = """# Storage Agent Pointer\n\nStart with `AI_START_HERE.md`. This file is only a pointer. More specific project/repository instructions govern their own scope. Do not infer memory, Git or write capabilities. Do not claim completion without verified postconditions.\n"""

MANIFEST = """# STORAGE MANIFEST\n\n- Bootstrap version: 1.1.0\n- Canonical public prompt: PENDING_PUBLICATION\n- Index: `STORAGE_INDEX.json`\n- Discovery: bounded/progressive by default\n- Mutation during discovery: forbidden unless explicitly authorized\n- Canonical rule: one home per fact; reuse existing project/repository structures\n"""


def bounded_entries(root: Path, depth: int) -> list[dict]:
    out: list[dict] = []
    root = root.resolve()
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        try:
            stat = p.lstat()
        except OSError as e:
            out.append({"name": p.name, "type": "UNREADABLE", "error": str(e)})
            continue
        item = {
            "name": p.name,
            "type": "symlink" if p.is_symlink() else "directory" if p.is_dir() else "file",
            "size": None if p.is_dir() else stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
        if depth > 1 and p.is_dir() and not p.is_symlink():
            try:
                item["children"] = [c.name for c in sorted(p.iterdir(), key=lambda x: x.name.lower())][:500]
                item["children_truncated"] = len(item["children"]) >= 500
            except OSError as e:
                item["children_error"] = str(e)
        out.append(item)
    return out


def write_if_allowed(path: Path, content: str, force: bool) -> str:
    if path.exists() and not force:
        return "SKIPPED_EXISTS"
    path.write_text(content, encoding="utf-8")
    return "WRITTEN"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Mounted storage root")
    ap.add_argument("--depth", type=int, default=1, choices=[1, 2], help="Index depth; default 1")
    ap.add_argument("--force", action="store_true", help="Allow overwrite of bootstrap files")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    results = {}
    results["AI_START_HERE.md"] = write_if_allowed(root / "AI_START_HERE.md", START, args.force)
    results["AGENTS.md"] = write_if_allowed(root / "AGENTS.md", AGENTS, args.force)
    results["STORAGE_MANIFEST.md"] = write_if_allowed(root / "STORAGE_MANIFEST.md", MANIFEST, args.force)

    index_path = root / "STORAGE_INDEX.json"
    if index_path.exists() and not args.force:
        results["STORAGE_INDEX.json"] = "SKIPPED_EXISTS"
    else:
        payload = {
            "schema": "universal-storage-index/1",
            "bootstrap_version": VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "root": str(root),
            "scope": {"depth": args.depth, "recursive": False},
            "note": "Navigation metadata only; not authority over file contents or project state.",
            "entries": bounded_entries(root, args.depth),
        }
        index_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        results["STORAGE_INDEX.json"] = "WRITTEN"

    print(json.dumps({"root": str(root), "results": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())