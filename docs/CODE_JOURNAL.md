# Code Journal

Role: Repository-local technical journal for implementation context. Git history, current source, tests and observed runtime/provider state remain the implementation evidence. This file explains why a substantive change was made, how it was checked and how it can be reversed; it does not duplicate every commit or terminal action.

## Routing rules

- Record code, tests, schemas, migrations, build/release behavior, deployment evidence and technical rollback here.
- Record project priorities, business decisions and non-technical outcomes in the authoritative Project Journal.
- Promote only cross-project or constitutional deltas to the portfolio Master Journal.
- Link to an ADR for durable architecture decisions instead of restating the full decision.
- Do not create a subjournal unless the workstream has a distinct lifecycle, ownership or sustained evidence volume.
- Use `UNKNOWN`, `NOT-RUN`, `BLOCKED` or `NEEDS-REVIEW` literally. Expected behavior is not test evidence.

## Entry template

```text
## CJ-YYYYMMDD-NNN — Short title
Recorded: ISO-8601 timestamp with timezone
Task: Stable task ID or issue/PR locator
Status: PROPOSED | VERIFIED | NEEDS-REVIEW | UNKNOWN | SUPERSEDED
Base: Exact revision
Branch/Patch: Exact branch, PR or patch locator
Scope: Affected paths/components
Before: Observed behavior before the change
Change: Implemented behavior and reason
Tests: Exact commands and actual results, or NOT-RUN
Three passes: Integrity; independent evidence; adverse cases
Migration/Deployment: Actual state, or NOT-RUN
Risks: Known limitations and unresolved facts
Rollback: Concrete safe reversal
Evidence: Commits, PR, files, logs or provider observations
Next: Exact next action
```

## CJ-20260916-001 — Public context and journal routing repair

Recorded: 2026-09-16T03:47:46Z  
Task: OOS-PUBLIC-CONTEXT-20260916  
Status: VERIFIED  
Base: `e1f790b93db2ec7ac7d68cc7336693615f82f67e`  
Branch/Patch: `docs/public-architect-bootstrap-20260916`  
Scope: README, AGENTS, public governance/index/glossary/state/journals and bootstrap prompt  
Before: Public context existed and validated structurally, but the README described a private agent, no Code Journal was routed, and historical upstream links were malformed or unavailable.  
Change: Clarified public/copy-safe scope, added CJ routing and a no-Git bootstrap prompt, and replaced unsupported live-source claims with explicit repository-local scope.  
Tests: `python3 scripts/oos_context.py --root . reindex --write` completed; `validate` returned `VALID` for 13 indexed documents and 2 journal events; all 16 unit tests passed; `git diff --check` passed.  
Three passes: Integrity PASS — manifest/hashes and journal locators regenerated and validated; independent PASS — GitHub metadata, MIT license and all public source URLs checked separately; adverse PASS — current tree and Git history showed no credential-shaped patterns in the bounded scan, public/private boundaries were reviewed, and merge/deployment remain explicitly unclaimed.  
Migration/Deployment: NOT-RUN; documentation branch only.  
Risks: Public-safety review is necessarily bounded; the package must never be treated as private portfolio history.  
Rollback: Close the PR or revert its commit without changing unrelated history.  
Evidence: Base revision, changed files, validator/test output and resulting GitHub PR.  
Next: Commit and push the review branch, open a PR, then read back the provider state before reporting the durable Git result.
