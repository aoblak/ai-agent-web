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

- Recorded: 2026-09-16T03:47:46Z
- Task: OOS-PUBLIC-CONTEXT-20260916
- Status: VERIFIED
- Base: `e1f790b93db2ec7ac7d68cc7336693615f82f67e`
- Branch/Patch: `docs/public-architect-bootstrap-20260916`; PR [#2](https://github.com/aoblak/ai-agent-web/pull/2)
- Scope: README, AGENTS, public governance/index/glossary/state/journals and bootstrap prompt
- Before: Public context existed and validated structurally, but the README described a private agent, no Code Journal was routed, and historical upstream links were malformed or unavailable.
- Change: Clarified public/copy-safe scope, added CJ routing and a no-Git bootstrap prompt, and replaced unsupported live-source claims with explicit repository-local scope.
- Tests: Context reindex and validation completed; all 16 unit tests passed. The first local diff check missed an untracked new file; provider-branch verification found its trailing whitespace, which was repaired and fully rechecked in the follow-up commit.
- Three passes: Integrity PASS — manifest/hashes and journal locators regenerated and validated; independent PASS — GitHub metadata, MIT license and all public source URLs checked separately; adverse PASS — remote base-to-head diff, current tree and Git history were checked, the bounded scan found no credential-shaped patterns, and merge/deployment remain explicitly unclaimed.
- Migration/Deployment: NOT-RUN; documentation review branch only.
- Risks: Public-safety review is necessarily bounded; the package must never be treated as private portfolio history.
- Rollback: Close the PR or revert its commits without changing unrelated history.
- Evidence: Commits `dc49de101faa29d97dc23a7d707a4eed8ff09e05` and `ef447b76d745375216e2a729684b0e55dfa6f482`; GitHub PR #2; validator/test output; provider read-back and correction entry CTX-20260916-002.
- Next: Review PR #2, merge only after owner review, then read back `main` before reporting adoption.
