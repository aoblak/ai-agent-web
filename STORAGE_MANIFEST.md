# STORAGE MANIFEST — TEMPLATE

This file is a storage-entry map, not a second source of truth for project contents.

## Identity

- Storage name: `UNKNOWN`
- Storage type: `UNKNOWN`
- Owner: `UNKNOWN`
- Sensitivity: `UNKNOWN`
- Last verified: `UNKNOWN`

## Agent entry sequence

1. `AI_START_HERE.md`
2. `AGENTS.md`
3. `STORAGE_INDEX.json`
4. Relevant repository/workspace instructions
5. Only task-relevant files and primary evidence

## Discovery rules

- Progressive/bounded discovery by default.
- Do not recursively crawl the entire storage root unless explicitly required and authorized.
- Do not move, rename, delete or deduplicate during discovery.
- Do not infer project status from filenames.
- Prefer shortcuts/pointers to duplicate copies.
- More specific repository/project rules override this navigation layer where allowed.

## Canonical bootstrap

- Public bootstrap URL: `https://raw.githubusercontent.com/aoblak/ai-agent-web/main/MASTER_PROMPT.md`
- Local bootstrap version: `1.1.0`
- Prompt file: `MASTER_PROMPT.md`

## Index

`STORAGE_INDEX.json` records only the scope that was actually indexed. Its entries are navigation metadata, not content truth.