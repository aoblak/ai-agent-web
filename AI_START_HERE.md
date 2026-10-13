# AI START HERE

This storage/workspace uses a universal, capability-first AI operating contract.

1. Read `MASTER_PROMPT.md` when present locally, otherwise use the canonical public copy referenced in `STORAGE_MANIFEST.md`.
2. Perform a runtime capability handshake. Never assume memory, Git, filesystem, connector or write access.
3. Discover and reuse the existing canonical structure. Do not create duplicate journals, indexes, task ledgers or memory trees.
4. Read `STORAGE_MANIFEST.md` and `STORAGE_INDEX.json` only as navigation aids.
5. For Git repositories, follow the repository's own `AGENTS.md`, current state, Journal, Issues/PRs and Git history.
6. Do not recursively scan, move, rename or delete storage content during discovery unless explicitly authorized.
7. Never claim DONE until the requested effect is verified.

8. Follow MASTER_PROMPT.md sections 14.1–14.9 for existing-chat routing, scoped journal identity, task ownership, concurrent writes and verified handoff returns. A dependent stage remains blocked until the preceding result is returned and verified. Record the exact bootstrap commit read.

9. Refresh the shared bootstrap on task start/resume/handoff; check clarity internally, retrieve existing answers before asking, and record unresolved questions in the existing task ledger. Publication is not delivery or acceptance by another chat.
