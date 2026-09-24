# Governance

Protocol version: **0.1.0**. Applies to retained context and its handling; it does not grant privileges or replace higher-priority instructions.

## Evidence and scope

**SOURCE OF TRUTH > JOURNAL > PROJECT STATE > GLOBAL KNOWLEDGE > INDEX/LINKS**.

The exact repository revision, verified artifact or provider observation is the primary evidence. A journal preserves dated decisions and results. Project state is a current projection. Knowledge is a reusable abstraction; an index only points to these records. A recent summary cannot silently overrule stronger evidence. Preserve both sides of a conflict and mark `NEEDS-REVIEW`.

Each repository must identify its own code/artifact source, PJ and portfolio MJ locators in `docs/INDEX.json`. A local `docs/MASTER_JOURNAL.md` may be a controlled excerpt or handoff journal. Label that role explicitly. Keep the canonical portfolio history at its existing location. Do not create a new competing portfolio master by copying everything into each repo.

## Three verification passes

1. **Integrity:** file existence, readable content, hashes, schema, linked files and expected artifact/version.
2. **Independent evidence:** compare the claim with current source, a provider observation or an independent check. Re-reading the same assertion is not independent verification.
3. **Adverse cases:** check applicable failure modes, ambiguity, stale context, wrong destinations, rollback and public/private exposure.

The third pass is a separate examination, not a mandatory second agent. Keep checks proportionate. A successful structural validator does not establish that history or application behavior is true. A `VERIFIED` event requires evidence for all three passes; otherwise use the actual status and describe missing checks.

## Visibility and authorization

Classify each retained artifact as `PUBLIC`, `PRIVATE`, or `UNKNOWN`. `UNKNOWN` data is not eligible for public export. Public-safe protocol text can be shared across repositories; private portfolio history, private repository names, credentials and sensitive operational topology cannot be copied into public outputs. A private repository is still unsuitable for credentials.

Before write/deploy/export, identify the operation, source, destination, classification, authorization already present in the current session, and rollback. Continue routine reversible work within existing authorization. Obtain further authorization only for a materially new or otherwise restricted action, not merely because an operation writes a file. A journal command is not production authorization.

Do not change repository visibility or permissions to distribute this protocol. A public PR is a public output, even when marked draft. Stage and validate a concrete change before any required production approval. A proposal in a branch is not adopted on the default branch and is not a deployment.

## Who writes the journal, and when

The human or agent performing a substantive operation is responsible for recording it during the same task, before reporting completion. Another actor may record a recovery entry only with its true recording time, separate from the historical event time and with the original author left `UNKNOWN` when unverified.

Record implementation details in the authoritative PJ. Add a concise portfolio MJ delta only for cross-project/constitutional decisions. If the portfolio location is unavailable, record `PENDING-MJ-SYNC` as a workflow condition in the local state and keep a source-linked delta; never claim it was synchronized. No automatic ChatGPT-to-iCloud or GitHub-to-iCloud writer is installed by this package.

Each event in `docs/MASTER_JOURNAL.md` uses the following form:

    <!-- oos:event {"id":"CTX-0001","recorded_at":"2026-09-07T00:00:00Z","occurred_at":null,"actor":"UNKNOWN","topics":["context"],"status":"NEEDS-REVIEW","visibility":"PUBLIC"} -->
    ## CTX-0001 — Concise event title
    Summary: What was observed or changed, and why.
    Sources: Exact files/revisions/artifacts or clearly unavailable locators.
    Integrity: Actual result and evidence, or NOT-RUN.
    Independent: Actual result and evidence, or NOT-RUN.
    Adverse: Actual result and evidence, or NOT-RUN.
    Rollback: Concrete reversal or restoration path, or not applicable.
    Next: Exact next action and remaining uncertainty.
    <!-- /oos:event -->

IDs must be unique within the repository. Timestamps use ISO 8601 with a timezone. `recorded_at` is the actual recording time; never backdate a recovered event. `occurred_at` is null when unknown. Valid evidence statuses are `PROPOSED`, `VERIFIED`, `NEEDS-REVIEW`, `UNKNOWN`, `SUPERSEDED`; the accepted primary lifecycle is `IDEA → VALIDATED → BUILDING → TESTED → PRODUCTION`. `BLOCKED` and `SUPERSEDED` are control states. Lifecycle is `UNKNOWN` when unverified, and remains separate from evidence review status.

Append events. Correct a prior event with a new event naming the superseded ID; retain the original. Do not rewrite established history to match a new conclusion. Stage the journal, state and index together. Git review should confirm the previous journal is a byte-for-byte prefix of the new journal unless a separately authorized format migration is recorded.

## Rollback and continuity

For Git-backed work, preserve the base revision and use a dedicated branch or reviewable patch. Revert the relevant commit to undo a merged protocol adoption; do not reset unrelated history. For local non-Git work, retain an exact backup or creation manifest outside the changed source. Before restoring, verify the target still matches the post-change version so concurrent work is not overwritten.

`oos_context.py reindex --write` updates derived hashes after reviewed source edits; it does not endorse their truth. It writes the index by atomic replacement and stops if its input changed while computing it. A mismatching hash or interrupted update must be fixed before the context is reported coherent.

`AGENTS.md` is startup guidance, not a scheduler, privilege boundary or guarantee that any agent obeys it. Run the validator as a required check in the project's existing review/CI workflow where available. This v0.1 package installs no global configuration, background service, hidden hook or cloud synchronization.
