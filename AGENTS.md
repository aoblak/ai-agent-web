# Agent Entry Pointer

Read `AI_START_HERE.md` and `MASTER_PROMPT.md` before substantial work in this storage root.

For this repository, reuse the existing OOS Context Protocol instead of bypassing it:
1. Run `python scripts/oos_context.py validate`.
2. Read the indexed bootstrap sequence in order: `docs/INDEX.md`, `docs/GOVERNANCE.md`, `docs/GLOSSARY.md`, `docs/PROJECT_STATE.md`, then task-relevant entries from `docs/MASTER_JOURNAL.md`.
3. For topic-scoped history, use `python scripts/oos_context.py bootstrap --topic "<topic>"` rather than inferring missing context.
4. Treat `docs/INDEX.json` as integrity/navigation metadata, not a replacement for the indexed sources.

If a child repository/project has its own `AGENTS.md`, follow the more specific instructions for that scope. Reuse existing canonical state/journal/task systems. Do not create parallel governance or memory structures.
