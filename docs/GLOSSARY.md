# OOS Governance Glossary

Status: **ACCEPTED OPERATING SHORTHAND**
Date: **2026-09-07**

These terms are canonical unless superseded by a later accepted governance decision.

- **MJ — Master Journal**: cross-project chronology, constitutional rules, shared architecture decisions and concise traceable summaries.
- **PJ — Project Journal**: detailed dated project-level decisions, implementation, tests, results, evidence, risks and next actions.
- **CJ — Code Journal**: repository-level explanation of implementation changes, tests, migrations, deployment evidence, risks and rollback; it complements but never replaces Git history or executable evidence.
- **XJ — Cross-Journal / Cross-Source Check**: inspect all materially related journals and authoritative sources before consequential decisions or promotion.
- **SOT — Source of Truth**: type-specific authoritative source for a fact.
- **UM — Unified Memory update with verification**: review current context and related evidence, then retain only durable, verified decisions/corrections/open items without unnecessary duplication. UM is not permission to override higher-authority repo/provider evidence.
- **FMU — Folder Memory Update**: update the durable memory/journal representation associated with a scoped project/folder after verification; preserve provenance and avoid duplicate authority.
- **GS — Git State**: report the relevant repository/branch, working tree when observable, latest commit, changed/uncommitted files when observable, ahead/behind or remote sync when observable, and relevant open PR/issues if available. Clearly separate confirmed from unavailable/unknown state.
- **UNKNOWN**: evidence is absent or insufficient. Do not guess.
- **NEEDS-REVIEW**: evidence conflicts, verification failed, or a consequential claim/action requires human or additional source review.
- **Public-safe/private split**: public artifacts may contain reusable architecture, generic schemas, anonymized examples, public-safe UI/docs/code; private material includes secrets, credentials, real leads/customers, personal data, sensitive pricing/offers, private outreach, private deployment configuration and other commercially sensitive internal data.

If an abbreviation is not defined here or in another accepted governance file, treat it as `UNKNOWN` rather than inventing a meaning.


## Architecture taxonomy

- **OOS / Oblak Operating System**: the platform-level governance and operating system for shared architecture, security, policy, capability orchestration, evidence, deployment and project integration.
- **OOS Core**: the minimal reusable runtime/governance core shared across OOS-governed projects.
- **Capability**: a reusable functional ability exposed by OOS governance/contracts; it should not imply a standalone product.
- **Module**: a bounded implementation unit that provides one or more capabilities and can evolve/version independently within OOS rules.
- **Adapter**: an integration boundary translating OOS contracts to an external provider, platform, protocol, CMS, model or service.
- **Vertical application**: a project/product applying OOS capabilities to a concrete domain, such as NERA or ArcaNina.
- **Content OS / Game Studio**: working capability/module families within OOS unless a later accepted ADR explicitly promotes them to a different architectural class. They are not parallel operating systems by default.

## Lifecycle

Primary lifecycle:
`IDEA → VALIDATED → BUILDING → TESTED → PRODUCTION`

Control states:
- **BLOCKED**: advancement is prevented by an explicit dependency, defect, policy, resource or evidence gap.
- **SUPERSEDED**: retained for history but replaced by a newer accepted decision/version/state.

`UNKNOWN` and `NEEDS-REVIEW` remain defined above and may interrupt any lifecycle phase.

## Evidence terms

- **EVIDENCE**: retained source/context that can support reconstruction or verification but is not itself an accepted decision.
- **MEMORY SNAPSHOT**: dated AI-memory/context capture retained for continuity; never an implementation authority.
- **PROMOTED MEMORY REFERENCE**: pointer showing that a memory/evidence item was verified and promoted into Journal/ADR/SOT. The promoted target, not the snapshot, becomes authoritative.


## Snapshot provenance

This is the controlled public repository-local glossary. The historical upstream locator recorded during the first context import is currently unavailable and must not be presented as live evidence. Until a valid upstream revision is recovered and reviewed, this glossary is authoritative only for this public repository; it does not replace the private portfolio glossary or create a new authority over other projects.
