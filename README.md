# AI Agent Web

Reusable operating rules and workspace bootstrap material for AI assistants across runtimes.

This repository helps an assistant discover an existing workspace, distinguish evidence from assumptions, verify its available tools and report whether an action actually succeeded.

**Status:** public operating contract and bootstrap tooling. Runtime instructions require the assistant's actual tool access; they do not grant web access, memory or execution capabilities.

## Start here

1. Read or paste [MASTER_PROMPT.md](MASTER_PROMPT.md) into your assistant environment.
2. For a file workspace, follow [AI_START_HERE.md](AI_START_HERE.md) and adapt [STORAGE_MANIFEST.md](STORAGE_MANIFEST.md) to the existing structure.
3. Inspect [the bootstrap installer](scripts/install_storage_bootstrap.py) before using it with your storage root.

## Package contents

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

## Evidence and limitations

The [contract tests](tests/test_master_prompt_contract.py) model protocol behavior with synthetic cases. They are not a benchmark of live AI providers. Compatibility pointers document entry mechanisms; successful execution still depends on each runtime's verified capabilities.

## Related public work

- [Aljoša Oblak — selected systems and technical focus](https://github.com/aoblak/aljosa-oblak)
- [State Transition Engine — explicit transitions and auditable outcomes](https://github.com/aoblak/state-transition-engine)
- [The Dog Park Finder — a lightweight application baseline](https://github.com/aoblak/thedogparkfinder)

## Feedback

[Open an issue](https://github.com/aoblak/ai-agent-web/issues) with the runtime, relevant contract section, expected behavior and observed result. Remove credentials and private workspace data before sharing examples.
