# ai-agent-web
Private AI Agent with access to world wide web

## Universal AI Bootstrap

This public repository distributes one platform-neutral initial assistant contract:

- [MASTER_PROMPT.md](MASTER_PROMPT.md) — canonical copy/paste prompt.
- [AI_START_HERE.md](AI_START_HERE.md) — storage/workspace arrival entrypoint.
- [STORAGE_MANIFEST.md](STORAGE_MANIFEST.md) — storage navigation template.
- [scripts/install_storage_bootstrap.py](scripts/install_storage_bootstrap.py) — non-destructive storage-root bootstrap/index installer.
- [tests/test_master_prompt_contract.py](tests/test_master_prompt_contract.py) — deterministic 44 × 10 = 440 synthetic protocol-model evaluations; not 440 live provider calls.

### Runtime compatibility

Every runtime uses the same `MASTER_PROMPT.md`. Provider-specific files exist only when a verified tool convention makes them useful; they are pointers, not separate protocols.

| Runtime / product | Entry mechanism in this repository |
| --- | --- |
| ChatGPT / OpenAI | Open or paste `MASTER_PROMPT.md` explicitly. No provider-specific repo file is assumed. |
| Claude Code | `CLAUDE.md` points to `MASTER_PROMPT.md`. |
| Gemini CLI / compatible Gemini developer tooling | `GEMINI.md` points to `MASTER_PROMPT.md`. |
| GitHub Copilot | `.github/copilot-instructions.md` points to `MASTER_PROMPT.md`. |
| Manus | Open or provide `MASTER_PROMPT.md` explicitly. No `MANUS.md` auto-load convention is assumed. |
| Meta AI | Open or provide `MASTER_PROMPT.md` explicitly. No `META.md` auto-load convention is assumed. |
| Microsoft Copilot | Open or provide `MASTER_PROMPT.md` explicitly. This is distinct from GitHub Copilot; no repo auto-load filename is assumed here. |
| Other AI runtimes | Use `MASTER_PROMPT.md` explicitly unless that runtime has a verified native instruction-file convention. |

The private OOS implementation remains separate. This public package contains only reusable, public-safe operating rules.
