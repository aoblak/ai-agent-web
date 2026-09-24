# ai-agent-web
Private AI Agent with access to world wide web

## Universal AI Bootstrap

This public repository distributes one platform-neutral initial assistant contract:

- [MASTER_PROMPT.md](MASTER_PROMPT.md) — canonical copy/paste prompt.
- [AI_START_HERE.md](AI_START_HERE.md) — storage/workspace arrival entrypoint.
- [STORAGE_MANIFEST.md](STORAGE_MANIFEST.md) — storage navigation template.
- [CLAUDE.md](CLAUDE.md), [GEMINI.md](GEMINI.md), and [.github/copilot-instructions.md](.github/copilot-instructions.md) — compatibility pointers only; they do not define separate protocols.
- [scripts/install_storage_bootstrap.py](scripts/install_storage_bootstrap.py) — non-destructive storage-root bootstrap/index installer.
- [tests/test_master_prompt_contract.py](tests/test_master_prompt_contract.py) — deterministic 44 × 10 = 440 contract checks; not 440 live provider calls.

The private OOS implementation remains separate. This public package contains only reusable, public-safe operating rules.
