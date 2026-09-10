# OOS Context Protocol v0.1

Implementation package for the existing accepted OOS Context Protocol v0.1, adding a machine-readable index and local validation for agents and humans. Root AGENTS.md routes work through a small indexed context packet; SHA-256 checks detect missing or stale context artifacts. Journals retain evidence and project state records what is currently known.

## Package

The core consists of AGENTS.md and docs/INDEX.md, GOVERNANCE.md, GLOSSARY.md, PROJECT_STATE.md, MASTER_JOURNAL.md. docs/INDEX.json supplies machine-readable paths, classifications, hashes and journal entry locators. scripts/oos_context.py provides bootstrap, validation and index regeneration using Python 3 standard-library modules only.

## Commands

Run from a repository containing the package:

    python3 scripts/oos_context.py --root . validate
    python3 scripts/oos_context.py --root . bootstrap --topic context
    python3 scripts/oos_context.py --root . reindex
    python3 scripts/oos_context.py --root . reindex --write

Reindex defaults to a preview; `--write` atomically replaces only the derived JSON index. It does not alter journal history or create a background writer. Run validation again after reindex.

## Adoption

Inspect the target and existing AGENTS.md/overrides, journals, registry and deployment rules first. Preserve all existing instructions and source files. Copy missing protocol files, merge an OOS section into an existing AGENTS.md if necessary, and customize project identity, evidence sources and state. A colliding governance, state or journal file requires a reviewed merge; never overwrite it with the template. Keep the old journal and its history.

Use a review branch. Record the base commit, source locators, actor, timestamp, validation and rollback. Commit journal/state/index with the change. Until merged, label adoption as prepared in a branch. Public repositories receive public-safe context only. A portfolio-wide inventory belongs in private/local storage.

## Limits

The manifest verifies structural consistency, not factual truth, authorization, semantic privacy or the honesty of an actor. Explicit classifications and human/agent review remain necessary. SHA-256 detects accidental changes; without a trusted Git revision or signature it is not an authentication mechanism. No external source is fetched automatically. An absent topic match does not establish absence of history. No recovery of the original inbox_wizard session is claimed.

Codex discovers AGENTS.md once when a run starts, with directory overrides and a default combined size limit. Existing sessions must explicitly read a newly installed contract; linked Markdown files are loaded because the contract instructs the agent to read them, not because they are automatically included by filename. See [official OpenAI documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

This package adds no repository license or change to existing licensing. Distribution rights follow the target repository's existing policy; a separate license decision is required if releasing the protocol as an independent product.
