# Grok handoff — OOS Integration Gate (2026-10-25)

Status: HANDOFF / NOT EXECUTED. Source: ChatGPT session on 2026-10-25 and user-provided OOS consolidation document. This is a task-oriented summary, **not** a verbatim or complete historical transcript and **not** the canonical Unified Memory journal.

## Bootstrap first
Read [AI_START_HERE.md](../../AI_START_HERE.md), [MASTER_PROMPT.md](../../MASTER_PROMPT.md), [AGENTS.md](../../AGENTS.md), and existing project state and journal. Refresh actual repository state before any conclusion. Grok is assigned independent audit/review under the current contract; changes to implementation roles need explicit coordination. Do not infer access from a public URL.

## User request and accepted decisions
The user asked to extract the OOS integration checklist, then said "dalje" (continue), and finally asked to record this chat in the bootstrap for Grok so they could continue there. The assistant extracted nine checkpoints from the attached consolidation and displayed an interactive checklist. None of those checkpoints was verified completed in this session. A preceding document described the wider architecture as partially verified.

Core decision: **one shared OOS Core, shared Research/Content/Competitive Intelligence, unified approval/provenance/journal; project-specific lightweight adapters**. Reuse existing code, storage, ownership and models; do not create a parallel AI Content Studio, CRM, governance or memory store. WordPress is one OOS client, not the architecture boundary. STOP → THINK → VERIFY → ACT → VERIFY → RECORD → STOP. Any unknown is UNKNOWN; no publication or destructive changes without relevant approval.

## OOS Integration Gate — nine checkpoints
1. Compare existing OOS and Content OS contracts; no duplication.
2. Identify owners of campaign, approval and journal models.
3. Verify existing Seed Bank WordPress tenant, data and API.
4. Verify OnlineTravels domain identity and deployment (onlinetravel.co.business / onlinetravels.co.business / onlinetravels.org must NOT be assumed identical).
5. Connect booking.co.place as first business adapter; reuse existing campaign and subscriber workflow where verified.
6. Implement one shared research + source/asset provenance flow.
7. Prove Draft → Approve → Publish → Verify → Journal in an end-to-end test.
8. Add SEO / AIO / GEO, competitor ranking and analytics learning loop.
9. Connect NERA, ArcaNina and Seed Bank without cloning OOS Core.

Priority: P0 trust, policy, core contracts, source verification, project memory, campaign manager, Seed Bank registry and asset provenance; P1 SEO, content increments, localization, media, adapters, analytics; P2 Game Studio.

## Common content contract (proposal only)
Extend existing models (do not instantiate a duplicate DB): ContentCampaign with project_id/tenant_id, source_records, source_provenance, topic/intent, locale, competitor_snapshot, keyword_gap, verified_claims, proposed_changes, content_variants, media_assets, budget, approval_state, publishing_receipts, analytics_baseline, measured_outcome, journal_event_id.

Asset provenance requested fields: asset_id, source, creator, AI_provider, model, prompt_hash, license, commercial_use, human_modified, approved, published_in_build. Add source reference, file checksum and revocation tracking only after checking current schema.

## Vertical notes
- booking.co.place: public catalog, profiles, leads, campaigns; do not confuse listing with verified availability/partner relationships.
- OnlineTravels: authoritative travel/booking sources, destination content, localization; deployment identity unverified.
- Dunja Apartments: Beds24/PriceLabs and local campaigns; pricing changes require approval.
- NERA: verified GPS, photos/provenance, dog park content and partners.
- ArcaNina: deterministic draw, multi-card contextual AI interpretation, assets with rights verified.
- Seed Bank: source registry, taxon/variety/accession, origin, native status, landrace, breeding method, evidence-bound GMO status, availability. Never infer GMO status from photo/name. Suggested external sources Genesys PGR, ECPGR, EURISCO; API and rights must be verified.

## Evidence discipline / next Grok action
Start READ-ONLY. Locate precise existing files, symbols, branch heads and PRs for checkpoints 1-4; provide source URLs and commit SHAs, statuses VERIFIED/PARTIAL/UNKNOWN, blockers and the smallest nonduplicative integration patch proposal. Verify tests and acceptance criteria before writing. Do not claim a running agent, live API, publication, completed checklist item, GitHub sync of canonical journal, or production integration without direct evidence.

The user's consolidated document reports partial verification and specifically states no GitHub or production mutations were made in that prior audit. This handoff itself is a documentation proposal branch, not task completion.
