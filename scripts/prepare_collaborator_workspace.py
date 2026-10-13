#!/usr/bin/env python3
"""Prepare an isolated memory workspace using existing, pinned public OOS code.

Local preparation only. Does not authenticate, create a GitHub repository, upload,
or install the private OOS application runtime. Existing destinations are refused.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

PACKAGE = Path(__file__).resolve().parents[1]
SOURCE = "4a71d44acf4f402ceee16fc3a0f4172555e70785"
PUBLIC_REPO = "https://github.com/aoblak/ai-agent-web"
COPY = ("MASTER_PROMPT.md", "scripts/oos_context.py", "docs/GOVERNANCE.md",
        "docs/GLOSSARY.md", "docs/OOS_CONTEXT_PROTOCOL.md")
PRIORITY = ["SOURCE OF TRUTH", "JOURNAL", "PROJECT STATE", "GLOBAL KNOWLEDGE", "INDEX/LINKS"]
ORDER = ["docs/INDEX.md", "docs/GOVERNANCE.md", "docs/GLOSSARY.md",
         "docs/PROJECT_STATE.md", "docs/MASTER_JOURNAL.md"]


def source_bytes(path):
    return subprocess.check_output(["git", "-C", str(PACKAGE), "show", SOURCE + ":" + path])


def prepare(destination, repository):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected owner/repository, not a URL or unresolved placeholder")
    if repository.split("/")[1] in {".", ".."}:
        raise ValueError("Invalid repository name")
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Destination exists: map and reuse its canonical files manually; no overwrite")
    if not destination.parent.is_dir() or destination.parent.is_symlink():
        raise ValueError("Destination needs an existing non-symlink parent")
    owner = repository.split("/")[0]
    files = {path: source_bytes(path) for path in COPY}
    text = {
        "AI_START_HERE.md": f"""# Independent OOS workspace
Owner: {owner}; intended private repository: https://github.com/{repository}
These are requested identities, not proof of authenticated access.
Read MASTER_PROMPT.md, AGENTS.md and docs/INDEX.json; then retrieve the relevant
primary evidence and journal entries. Refresh the shared contract at its maintained
public URL and record the resolved revision. Never import another owner's memory.
Local preparation is not remote persistence. Confirm private destination and owner
approval, use branch/PR/review, fetch the saved commit and verify its exact bytes.
For an existing workspace reuse its canonical homes instead of running this generator.
""",
        "AGENTS.md": """# Workspace rules
Read AI_START_HERE.md and MASTER_PROMPT.md. Use docs/INDEX.json for navigation.
SOURCE OF TRUTH > JOURNAL > PROJECT STATE > GLOBAL KNOWLEDGE > INDEX/LINKS.
Canonical journal: docs/MASTER_JOURNAL.md. Canonical project state: docs/PROJECT_STATE.md.
Do not create JOURNAL.md or registry/state.yaml as competing copies in this workspace.
Use GitHub Issues for tasks. Preserve originals and append source-linked corrections.
Run integrity, independent-evidence and adverse checks before promoting claims.
Update the derived index with scripts/oos_context.py reindex --write, then validate.
Keep private evidence private; use only approved task-scoped material for cooperation.
Invoke guarded_continue only behind an authenticated adapter with its own transaction
and delivery idempotency. Recorded actor strings are not authenticated identities.
""",
        "docs/INDEX.md": """# Memory navigation
- Primary evidence: docs/SOURCES.md and the exact source artifacts/commits it references.
- Decisions and chronology: docs/MASTER_JOURNAL.md (this owner's sole initial journal).
- Current projection: docs/PROJECT_STATE.md.
- Reusable knowledge: docs/KNOWLEDGE.md; each entry must link to supporting evidence.
- Derived navigation/hashes: docs/INDEX.json. An index never overrides a source.
""",
        "docs/SOURCES.md": """# Source of Truth register
No personal sources imported. Add only this owner's approved originals or exact
provider/file/commit references, with visibility, revision and evidence status.
This register points to primary evidence; it does not replace the originals.
""",
        "docs/MASTER_JOURNAL.md": """# Owner's canonical journal
No inherited decisions or execution events. Append actual observations using the
event schema in GOVERNANCE.md. Never fabricate prior history or successful setup.
""",
        "docs/PROJECT_STATE.md": f"""# Current state
Intended owner: {owner}; repository: {repository}; intended visibility: PRIVATE.
Remote identity, visibility, access and writes: UNVERIFIED.
Projects and tasks: none supplied. Knowledge and personal history: not imported.
Local OOS Context code: pinned to {SOURCE}; source PR #10 remains under review.
Full OOS application runtime: NOT_INSTALLED; requires an approved clean distribution,
verified source revision, dependency setup and its own tests. Do not mark setup complete
until that requirement is fulfilled or the owner explicitly accepts a narrower scope.
Live provider communication: NOT_CONNECTED. No credentials or background jobs installed.
""",
        "docs/KNOWLEDGE.md": """# Reusable knowledge
No inherited knowledge. Add confirmed reusable conclusions with original source,
journal reference, scope, status and last verification. Retain superseded versions.
""",
    }
    files.update({path: value.encode() for path, value in text.items()})
    source_index = json.loads(source_bytes("docs/INDEX.json"))
    index = dict(protocol="OOS Context Protocol", version="0.1.0",
                 project=dict(id="UNKNOWN", name=repository,
                              repository="https://github.com/" + repository,
                              visibility="PRIVATE", lifecycle="BUILDING", review_status="PROPOSED"),
                 bootstrap_order=ORDER, source_priority=PRIORITY,
                 documents=[dict(path=p, visibility="PRIVATE", sha256=hashlib.sha256(b).hexdigest())
                            for p, b in files.items()], glossary=source_index["glossary"],
                 sources=[dict(id="public-oos-context-code", locator=PUBLIC_REPO + "/tree/" + SOURCE,
                               revision=SOURCE, status="VERIFIED", visibility="PUBLIC")], journal_entries=[])
    files["docs/INDEX.json"] = (json.dumps(index, ensure_ascii=False, indent=2) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix="oos-prepare-", dir=destination.parent) as staging:
        stage = Path(staging)
        for path, data in files.items():
            target = stage / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        subprocess.run([sys.executable, str(stage / "scripts/oos_context.py"),
                        "--root", str(stage), "validate"], check=True, capture_output=True)
        # Exclusive claim: a racing setup or existing owner store is never replaced.
        destination.mkdir()
        for path, data in files.items():
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(data)
        for path, data in files.items():
            if (destination / path).read_bytes() != data:
                raise ValueError("Local readback failed: " + path)
    return dict(status="LOCAL_CONTEXT_PREPARED", path=str(destination), source_commit=SOURCE,
                files=len(files), remote_persistence="UNVERIFIED", full_oos_runtime="NOT_INSTALLED",
                live_handoff="NOT_CONNECTED")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", help="New local staging directory, never an existing memory store")
    parser.add_argument("--repository", required=True, help="Owner-approved intended private owner/repo")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.destination, args.repository), indent=2))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, "Preparation failed; no remote setup claimed: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
