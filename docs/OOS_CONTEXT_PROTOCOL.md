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

## Executable handoff gate

`validate` continues to check structural integrity only. For dependent execution use the separate `handoff-gate` command or `guarded_continue(root, policy, continuation)` in `scripts/oos_context.py`. The latter raises `ContextError` without calling the supplied continuation on invalid evidence. A continuation exception propagates; it is never converted into a successful handoff. Journal content cannot specify code or commands to execute.

The gate reads **the existing** `docs/MASTER_JOURNAL.md` and its current index; it creates no journal, queue, task database, master prompt or background service. An authenticated adapter can append observed events to that existing store through its established write/review rules. Legacy prose alone never authorizes continuation. GitHub Issues remain the shared task record; adapter events must retain their issue/message locators.

The trusted caller supplies policy from the approved task record, independently of worker output:

```python
policy = {
    "task_id": "TASK-9", "attempt_id": "ATTEMPT-1",
    "owner": "worker-session", "reviewer": "review-session",
    "coordinator": "coordinator-session", "next_owner": "recipient-session",
    "source_commit": "<40 lowercase hexadecimal characters>",
    "journal_sha256": "<64 lowercase hexadecimal characters>"
}
# Obtain real identities/revisions from the trusted store, not these placeholders.
# guarded_continue(root, policy, existing_dispatcher_continuation)
```

The CLI takes those same required fields with hyphenated names, for example `--task-id`, `--attempt-id`, `--source-commit` and `--journal-sha256`. Exit 0 with `HANDOFF_VERIFIED` means the recorded evidence passed; any missing/invalid field exits nonzero. A shell caller must gate its next command with `&&`, never `;`. The gate does not mark work executed merely because it allows continuation.

Each observed journal event retains the normal OOS metadata/body and adds a `handoff` metadata object with `schema: "oos-handoff/1"`, all policy fields **except** `journal_sha256`, plus `state`, `role` and a nonempty, stable, unique `criteria` list. Policy binds the entire journal separately to avoid a self-referential hash. The outer actor must match the assigned role. Outer evidence status must be `VERIFIED`, including the existing three recorded checks; occurrence time must be known, timezone-aware, nondecreasing and no later than recording time. Synthetic fixtures stay in tests; do not manufacture observations for live records.

| Order | State | Actor role | Additional evidence in `handoff` |
| --- | --- | --- | --- |
| 1 | READY | coordinator | Approved task bindings and criteria |
| 2 | ASSIGNED | coordinator | Observed dispatch `message_id` |
| 3 | ACCEPTED | owner | Receipt `message_id`, `in_reply_to` assignment event ID |
| 4 | IN_PROGRESS | owner | Same task/attempt/actors/source/criteria |
| 5 | RESULT_RETURNED | owner | Return `message_id`; nonempty `artifacts` with unique `id`, relative `path`, SHA-256 |
| 6 | VERIFIED | reviewer | Review `message_id`, `result_event_id`; `checks` covering each criterion exactly once, literal `ok: true`, and nonempty `evidence` lists of returned artifact IDs |
| 7 | VERIFIED | coordinator | Confirmation `message_id`, `review_event_id` |
| 8 | HANDED_OFF | next_owner | Receipt `message_id`, `confirmation_event_id` |

The two VERIFIED events are separate review and coordinator attestations at the same lifecycle stage. The reviewer must differ from the result author. The coordinator remains responsible until the final observed receipt. Unique event/message IDs and an exact ordered sequence reject duplicate delivery, skipped stages and conflicting owners. A later event in that attempt (including BLOCKED) invalidates authorization; recovery uses a new explicit attempt. A newer attempt supersedes the old receipt; interleaved/reopened attempts fail. Independent tasks may progress separately.

The gate reads each returned artifact under the existing root, rejects traversal/symlinks, compares actual SHA-256 bytes, and rechecks journal/artifacts before returning. Missing results, failed or incomplete checks, wrong source, changed criteria, wrong actor, missing confirmation, stale journal revision and wrong acknowledgement all fail closed. It compares the declared immutable source against caller policy; this does **not** prove where an arbitrary artifact was generated.

### Integration boundary

This is a precondition check for trusted callers, not authentication or an exactly-once transport. Journal text and actor strings cannot prove a real provider sent a message. The adapter must authenticate writers, validate receipts against provider responses, independently check acceptance criteria, derive policy from the approved task, and hold its transaction/lock across fresh gate evaluation and dispatch. Do not accept the policy/journal hash from an untrusted worker. Read-only rechecks detect changes during verification but cannot prevent a mutation after checking; use immutable artifact snapshots or transactional storage in a live dispatcher. Repeated calls may invoke the continuation again; dispatch idempotency belongs to the existing transport/task ledger. No Claude/Grok/Manus adapter is installed here. Provider access, production approvals and independent human/agent review remain separate gates.

## Adoption

Inspect the target and existing AGENTS.md/overrides, journals, registry and deployment rules first. Preserve all existing instructions and source files. Copy missing protocol files, merge an OOS section into an existing AGENTS.md if necessary, and customize project identity, evidence sources and state. A colliding governance, state or journal file requires a reviewed merge; never overwrite it with the template. Keep the old journal and its history.

Use a review branch. Record the base commit, source locators, actor, timestamp, validation and rollback. Commit journal/state/index with the change. Until merged, label adoption as prepared in a branch. Public repositories receive public-safe context only. A portfolio-wide inventory belongs in private/local storage.

## Limits

The manifest verifies structural consistency, not factual truth, authorization, semantic privacy or the honesty of an actor. Explicit classifications and human/agent review remain necessary. SHA-256 detects accidental changes; without a trusted Git revision or signature it is not an authentication mechanism. No external source is fetched automatically. An absent topic match does not establish absence of history. No recovery of the original inbox_wizard session is claimed.

Codex discovers AGENTS.md once when a run starts, with directory overrides and a default combined size limit. Existing sessions must explicitly read a newly installed contract; linked Markdown files are loaded because the contract instructs the agent to read them, not because they are automatically included by filename. See [official OpenAI documentation](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

This package adds no repository license or change to existing licensing. Distribution rights follow the target repository's existing policy; a separate license decision is required if releasing the protocol as an independent product.
