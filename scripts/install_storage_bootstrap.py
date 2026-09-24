#!/usr/bin/env python3
"""Non-destructive storage bootstrap installer.

Creates a minimal agent-arrival layer and bounded storage index. It does not recurse by
Default, does not delete/move/rename existing content, and never follows an existing
bootstrap symlink for writes.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.1.0"
CANONICAL_PUBLIC_PROMPT_URL = (
    "https://raw.githubusercontent.com/aoblak/ai-agent-web/"
    "395c197617c505708236af65418fb96bbce78784/MASTER_PROMPT.md"
)
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_MASTER_PROMPT = PACKAGE_ROOT / "MASTER_PROMPT.md"

START = f"""# AI START HERE

This storage/workspace uses the Universal Personal & Business AI Assistant contract v{VERSION}.

1. Read `MASTER_PROMPT.md` when present locally. If it is not present, use the immutable public copy: {CANONICAL_PUBLIC_PROMPT_URL}
2. Read `STORAGE_MANIFEST.md`, `STORAGE_INDEX.json`, and any more specific repository/project `AGENTS.md`.
3. Perform a runtime capability handshake. Never assume memory, Git, filesystem, connector or write access.
4. Use progressive discovery. Do not move, rename, delete, deduplicate or reorganize during discovery without explicit authorization.
5. Reuse existing canonical journals/state/task systems; do not create parallel ones.
6. Never claim DONE until the requested effect is verified.
"""

AGENTS = """# Storage Agent Pointer

Start with `AI_START_HERE.md` and `MASTER_PROMPT.md` when available locally. This file is only a pointer. More specific project/repository instructions govern their own scope. Reuse existing canonical state/journal/task systems. Do not infer memory, Git or write capabilities. Do not claim completion without verified postconditions.
"""

MANIFEST = f"""# STORAGE MANIFEST

- Bootstrap version: {VERSION}
- Canonical immutable public prompt: {CANONICAL_PUBLIC_PROMPT_URL}
- Local prompt file: `MASTER_PROMPT.md`
- Index: `STORAGE_INDEX.json`
- Discovery: bounded/progressive by default
- Mutation during discovery: forbidden unless explicitly authorized
- Canonical rule: one home per fact; reuse existing project/repository structures

`STORAGE_INDEX.json` is navigation metadata only; it is not authority over file contents or project state.
"""


def occupied(path: Path) -> bool:
    """True for ordinary entries and dangling symlinks."""
    return path.exists() or path.is_symlink()


def bounded_entries(root: Path, depth: int) -> list[dict]:
    out: list[dict] = []
    root = root.resolve()
    for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
        try:
            stat = p.lstat()
        except OSError as e:
            out.append({"name": p.name, "type": "UNREADABLE", "error": str(e)})
            continue
        is_link = p.is_symlink()
        item = {
            "name": p.name,
            "type": "symlink" if is_link else "directory" if p.is_dir() else "file",
            "size": None if (not is_link and p.is_dir()) else stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
        if depth > 1 and not is_link and p.is_dir():
            try:
                children = [c.name for c in sorted(p.iterdir(), key=lambda x: x.name.lower())]
                item["children"] = children[:500]
                item["children_truncated"] = len(children) > 500
            except OSError as e:
                item["children_error"] = str(e)
        out.append(item)
    return out


def write_if_allowed(path: Path, content: str, force: bool) -> str:
    # Never follow symlinks, even with --force. A separate explicit migration can handle them.
    if path.is_symlink():
        return "SKIPPED_SYMLINK"
    if path.exists() and path.is_dir():
        return "SKIPPED_NONFILE"
    if path.exists() and not force:
        return "SKIPPED_EXISTS"
    path.write_text(content, encoding="utf-8")
    return "WRITTEN"


def copy_prompt_if_available(path: Path, force: bool) -> str:
    if path.is_symlink():
        return "SKIPPED_SYMLINK"
    if path.exists() and path.is_dir():
        return "SKIPPED_NONFILE"
    if path.exists() and not force:
        return "SKIPPED_EXISTS"
    if not SOURCE_MASTER_PROMPT.is_file():
        return "SOURCE_UNAVAILABLE_USE_PUBLIC_URL"
    shutil.copyfile(SOURCE_MASTER_PROMPT, path)
    return "WRITTEN"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Mounted storage root")
    ap.add_argument("--depth", type=int, default=1, choices=[1, 2], help="Index depth; default 1")
    ap.add_argument("--force", action="store_true", help="Overwrite regular bootstrap files; symlinks are still never followed")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    results = {}
    results["MASTER_PROMPT.md"] = copy_prompt_if_available(root / "MASTER_PROMPT.md", args.force)
    results["AI_START_HERE.md"] = write_if_allowed(root / "AI_START_HERE.md", START, args.force)
    results["AGENTS.md"] = write_if_allowed(root / "AGENTS.md", AGENTS, args.force)
    results["STORAGE_MANIFEST.md"] = write_if_allowed(root / "STORAGE_MANIFEST.md", MANIFEST, args.force)

    index_path = root / "STORAGE_INDEX.json"
    if index_path.is_symlink():
        results["STORAGE_INDEX.json"] = "SKIPPED_SYMLINK"
    elif index_path.exists() and index_path.is_dir():
        results["STORAGE_INDEX.json"] = "SKIPPED_NONFILE"
    elif index_path.exists() and not args.force:
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

    print(json.dumps({"root": str(root), "canonical_prompt_url": CANONICAL_PUBLIC_PROMPT_URL, "results": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())