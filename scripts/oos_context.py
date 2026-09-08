#!/usr/bin/env python3
"""OOS Context Protocol 0.1.0: local-only bootstrap and integrity checks."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from datetime import datetime

VERSION = "0.1.0"
INDEX = "docs/INDEX.json"
ORDER = ["docs/INDEX.md", "docs/GOVERNANCE.md", "docs/GLOSSARY.md",
         "docs/PROJECT_STATE.md", "docs/MASTER_JOURNAL.md"]
REQUIRED = ["AGENTS.md"] + ORDER + ["scripts/oos_context.py"]
PRIORITY = ["SOURCE OF TRUTH", "JOURNAL", "PROJECT STATE",
            "GLOBAL KNOWLEDGE", "INDEX/LINKS"]
STATUSES = {"PROPOSED", "VERIFIED", "NEEDS-REVIEW", "UNKNOWN", "SUPERSEDED"}
VISIBILITIES = {"PUBLIC", "PRIVATE", "UNKNOWN"}
FIELDS = ["Summary", "Sources", "Integrity", "Independent", "Adverse", "Rollback", "Next"]
EVENT = re.compile(r'<!-- oos:event (\{[^\n]+\}) -->\n(.*?)<!-- /oos:event -->', re.S)
ID = re.compile(r"[A-Z][A-Z0-9._-]{2,79}\Z")


class ContextError(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContextError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def decode_json(data):
    try:
        return json.loads(data, object_pairs_hook=unique_object)
    except (ValueError, UnicodeError) as exc:
        raise ContextError("Invalid JSON: " + str(exc)) from exc


def local_file(root, relative):
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ContextError("Invalid repository-relative path")
    p = PurePosixPath(relative)
    if p.is_absolute() or any(part in {"..", "."} for part in p.parts):
        raise ContextError("Path escapes or ambiguously addresses repository: " + relative)
    target = root
    for part in p.parts:
        target = target / part
        if target.is_symlink():
            raise ContextError("Context paths cannot be symlinks: " + relative)
    if not target.is_file():
        raise ContextError("Missing context file: " + relative)
    return target


def load_manifest(root):
    data = local_file(root, INDEX).read_bytes()
    if len(data) > 2_000_000:
        raise ContextError("Context index exceeds 2 MB")
    manifest = decode_json(data)
    if not isinstance(manifest, dict):
        raise ContextError("Index must be a JSON object")
    return manifest, data


def timestamp(value, name, nullable=False):
    if value is None and nullable:
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone missing")
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContextError("Invalid timezone-aware timestamp: " + name) from exc


def parse_events(text):
    events = []
    ids = set()
    matches = list(EVENT.finditer(text))
    if text.count("<!-- oos:event ") != len(matches) or text.count("<!-- /oos:event -->") != len(matches):
        raise ContextError("Malformed or unterminated journal event")
    for match in matches:
        meta = decode_json(match.group(1))
        body = match.group(2)
        if not isinstance(meta, dict):
            raise ContextError("Journal event metadata must be an object")
        event_id = meta.get("id")
        if not isinstance(event_id, str) or not ID.fullmatch(event_id) or event_id in ids:
            raise ContextError("Invalid or duplicate journal event ID: " + str(event_id))
        ids.add(event_id)
        timestamp(meta.get("recorded_at"), event_id + ".recorded_at")
        if "occurred_at" not in meta:
            raise ContextError("Missing occurred_at (use null if unknown): " + event_id)
        timestamp(meta["occurred_at"], event_id + ".occurred_at", nullable=True)
        if not isinstance(meta.get("actor"), str) or not meta["actor"].strip():
            raise ContextError("Missing journal actor: " + event_id)
        topics = meta.get("topics")
        if not isinstance(topics, list) or not topics or not all(isinstance(t, str) and t.strip() for t in topics):
            raise ContextError("Missing journal topics: " + event_id)
        if meta.get("status") not in STATUSES or meta.get("visibility") not in VISIBILITIES:
            raise ContextError("Invalid status or visibility: " + event_id)
        heading = re.search(r"^## (.+)$", body, re.M)
        if not heading or not heading.group(1).startswith(event_id + " — "):
            raise ContextError("Event heading must start with its ID: " + event_id)
        for field in FIELDS:
            line = re.search(r"^" + field + r":\s*(\S[^\n]*)$", body, re.M)
            if not line:
                raise ContextError("Missing event field " + field + ": " + event_id)
            if meta["status"] == "VERIFIED" and field in {"Integrity", "Independent", "Adverse"}:
                if not line.group(1).startswith("PASS — ") or len(line.group(1)[7:].strip()) < 12:
                    raise ContextError("VERIFIED requires PASS with evidence for " + field + ": " + event_id)
        locator = {"id": event_id, "title": heading.group(1), "topics": topics,
                   "recorded_at": meta["recorded_at"], "status": meta["status"],
                   "visibility": meta["visibility"], "path": "docs/MASTER_JOURNAL.md",
                   "sha256": sha(match.group(0).encode("utf-8"))}
        events.append((locator, match.group(0)))
    return events


def check_links(root, relative, text):
    errors = []
    for link in re.findall(r"\]\(([^)]+)\)", text):
        target = link.split("#", 1)[0].strip().strip("<>")
        if not target or re.match(r"https?://", target):
            continue
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target):
            errors.append("Unsupported context link scheme in " + relative)
            continue
        candidate = Path(os.path.normpath(str(Path(relative).parent / target)))
        try:
            local_file(root, candidate.as_posix())
        except ContextError as exc:
            errors.append(str(exc) + " (linked from " + relative + ")")
    return errors


def inspect(root, manifest, compare_hashes=True):
    errors, warnings = [], []
    snapshots = {}
    if manifest.get("protocol") != "OOS Context Protocol" or manifest.get("version") != VERSION:
        errors.append("Unsupported protocol/version")
    if manifest.get("bootstrap_order") != ORDER:
        errors.append("Bootstrap order differs from protocol")
    if manifest.get("source_priority") != PRIORITY:
        errors.append("Evidence priority differs from protocol")
    project = manifest.get("project")
    if not isinstance(project, dict):
        errors.append("Missing project identity")
        project = {}
    if not project.get("id") or not project.get("name"):
        errors.append("Project ID and name are required; use UNKNOWN when unverified")
    if project.get("visibility") not in VISIBILITIES:
        errors.append("Invalid project visibility")
    if project.get("lifecycle") not in {"IDEA", "VALIDATED", "BUILDING", "TESTED", "PRODUCTION", "UNKNOWN"}:
        errors.append("Invalid project lifecycle")
    if project.get("review_status") not in STATUSES:
        errors.append("Invalid project review status")
    docs = manifest.get("documents")
    if not isinstance(docs, list):
        return ["documents must be a list"] + errors, warnings, snapshots, []
    paths = []
    for document in docs:
        if not isinstance(document, dict):
            errors.append("Invalid document record")
            continue
        path = document.get("path")
        if not isinstance(path, str):
            errors.append("Document path must be a string")
            continue
        if path in paths or path == INDEX:
            errors.append("Duplicate or self-referential document: " + path)
        paths.append(path)
        visibility = document.get("visibility")
        if visibility not in VISIBILITIES:
            errors.append("Invalid document visibility: " + path)
        if project.get("visibility") == "PUBLIC" and visibility != "PUBLIC":
            errors.append("Public context contains non-public document: " + path)
        try:
            data = local_file(root, path).read_bytes()
            if len(data) > 4_000_000:
                raise ContextError("Context file exceeds 4 MB: " + path)
            snapshots[path] = data
            if compare_hashes and document.get("sha256") != sha(data):
                errors.append("Stale SHA-256: " + path)
            if path.endswith(".md"):
                errors.extend(check_links(root, path, data.decode("utf-8")))
        except (ContextError, OSError, UnicodeError) as exc:
            errors.append(str(exc))
    for path in REQUIRED:
        if path not in paths:
            errors.append("Required document is not indexed: " + path)
    glossary = manifest.get("glossary", {})
    if not isinstance(glossary, dict):
        errors.append("Invalid glossary")
        glossary = {}
    for term in ["MJ", "PJ", "XJ", "UM", "FMU", "GS", "SOT", "NEEDS-REVIEW", "UNKNOWN"]:
        record = glossary.get(term)
        if not isinstance(record, dict) or record.get("status") not in STATUSES:
            errors.append("Missing or invalid glossary term: " + term)
        elif record["status"] == "VERIFIED" and (not record.get("meaning") or not record.get("source")):
            errors.append("Verified abbreviation lacks meaning/source: " + term)
        elif record["status"] in {"UNKNOWN", "NEEDS-REVIEW"}:
            warnings.append("Unresolved abbreviation: " + term)
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        errors.append("Source registry must be a list")
        sources = []
    for source in sources:
        if not isinstance(source, dict) or source.get("status") not in STATUSES or source.get("visibility") not in VISIBILITIES:
            errors.append("Invalid source record")
            continue
        if project.get("visibility") == "PUBLIC" and source["visibility"] != "PUBLIC":
            errors.append("Public index discloses a non-public source locator")
        if source["status"] in {"UNKNOWN", "NEEDS-REVIEW"}:
            warnings.append("Unresolved source: " + str(source.get("id")))
        if source["status"] != "UNKNOWN" and (not source.get("locator") or not source.get("revision")):
            errors.append("Known source needs locator and revision: " + str(source.get("id")))
    try:
        events = parse_events(snapshots.get("docs/MASTER_JOURNAL.md", b"").decode("utf-8"))
        if project.get("visibility") == "PUBLIC" and any(e[0]["visibility"] != "PUBLIC" for e in events):
            errors.append("Public context contains a non-public journal entry")
        if compare_hashes and manifest.get("journal_entries") != [e[0] for e in events]:
            errors.append("Journal entry index is stale")
    except (ContextError, UnicodeError) as exc:
        errors.append(str(exc))
        events = []
    return errors, warnings, snapshots, events


def run(args):
    root = Path(args.root).resolve()
    manifest, index_before = load_manifest(root)
    errors, warnings, snapshots, events = inspect(root, manifest, compare_hashes=args.command != "reindex")
    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors, "warnings": warnings}, indent=2))
        return 1
    if args.command == "reindex":
        for doc in manifest["documents"]:
            doc["sha256"] = sha(snapshots[doc["path"]])
        manifest["journal_entries"] = [entry[0] for entry in events]
        output = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if not args.write:
            print(output.decode("utf-8"), end="")
            return 0
        index_path = local_file(root, INDEX)
        lock_path = index_path.with_name(".oos-index.lock")
        try:
            lock = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ContextError("Index update already in progress; inspect stale lock before recovery") from exc
        temporary = None
        try:
            os.close(lock)
            if index_path.read_bytes() != index_before:
                raise ContextError("Index changed during reindex; retry from current state")
            for path, data in snapshots.items():
                if local_file(root, path).read_bytes() != data:
                    raise ContextError("Source changed during reindex: " + path)
            with tempfile.NamedTemporaryFile(dir=index_path.parent, prefix=".oos-index-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, index_path.stat().st_mode & 0o777)
            os.replace(temporary, index_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
            lock_path.unlink()
        print(json.dumps({"status": "REINDEXED", "index": INDEX, "journal_entries": len(events)}))
        return 0
    if args.command == "validate":
        print(json.dumps({"status": "VALID", "scope": "structural-integrity-only", "documents": len(snapshots),
                          "journal_entries": len(events), "warnings": warnings}, indent=2))
        return 0
    topic = args.topic.casefold().strip()
    if not topic:
        raise ContextError("bootstrap requires a non-empty topic")
    matches = [entry for entry in events if topic in (entry[0]["title"] + " " + " ".join(entry[0]["topics"])).casefold()]
    matches = sorted(matches, key=lambda e: datetime.fromisoformat(e[0]["recorded_at"].replace("Z", "+00:00")), reverse=True)
    selected = matches[:args.max_entries]
    payload = {"status": "CONTEXT_READY", "project": manifest["project"], "source_priority": PRIORITY,
               "warnings": warnings, "sources": manifest["sources"], "glossary": manifest["glossary"],
               "bootstrap_documents": [{"path": p, "content": snapshots[p].decode("utf-8")} for p in ORDER[:-1]],
               "journal_matches": [{"locator": e[0], "content": e[1]} for e in selected],
               "matching_entries": len(matches), "truncated": len(matches) > len(selected)}
    if not selected:
        payload["context_gap"] = "UNKNOWN: no local matching event; inspect source locators before inferring history"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    boot = commands.add_parser("bootstrap")
    boot.add_argument("--topic", required=True)
    boot.add_argument("--max-entries", type=int, choices=range(1, 21), default=5)
    reindex = commands.add_parser("reindex")
    reindex.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        return run(args)
    except (ContextError, OSError, KeyError, TypeError, UnicodeError) as exc:
        print(json.dumps({"status": "INVALID", "errors": [str(exc)]}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
