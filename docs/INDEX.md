# Context index

Protocol: **OOS Context Protocol 0.1.0**.

This is a navigation view. [INDEX.json](INDEX.json) is the machine-readable locator and integrity manifest. Neither index establishes factual authority.

| Order | Document | Purpose |
| --- | --- | --- |
| 1 | [This index](INDEX.md) / [machine index](INDEX.json) | Scope, paths and entry lookup |
| 2 | [Governance](GOVERNANCE.md) | Verification, privacy, recording and rollback |
| 3 | [Glossary](GLOSSARY.md) | Accepted and unresolved terms |
| 4 | [Project state](PROJECT_STATE.md) | Current facts, gaps and next action |
| 5 | [Local journal / controlled excerpt](MASTER_JOURNAL.md) | Relevant dated entries |

Supplemental public-safe records:

| Document | Purpose |
| --- | --- |
| [Code Journal](CODE_JOURNAL.md) | Repository-level implementation, test and rollback context |
| [Architect bootstrap prompt](ARCHITECT_BOOTSTRAP_PROMPT.md) | Read-only bootstrap and self-correction prompt for an assistant without Git integration |
| [Protocol notes](OOS_CONTEXT_PROTOCOL.md) | Package commands, adoption path and limits |

Run `python3 scripts/oos_context.py --root . bootstrap --topic "topic"` from the repository root. It validates the manifest, prints the required startup documents in order and returns only matching local journal entries. Inspect their primary evidence before acting. Use `--max-entries` for a bounded larger selection.

The JSON index records document hashes and journal entry IDs, titles, topics and byte-content hashes. Journal content remains in the Markdown source; editing the index cannot change what the journal says. External sources are recorded as locators and must be fetched explicitly when needed.

An unresolved portfolio locator, abbreviation or historical record does not authorize inventing one. Record `UNKNOWN` or `NEEDS-REVIEW`, and continue tasks that do not depend on it.

Each fact has one canonical home. Other documents link to it and may carry a short status summary, but must not create a competing history. The index is generated navigation, never factual authority.
