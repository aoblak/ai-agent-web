# OOS reusable Python runtime — collaborator candidate

This is executable software, distributed under the included MIT license. It contains
all 17 Python files in the source OOS package plus VITA verification, generic command
line adapters, schemas and offline regression tests. Python 3.11+ (with SQLite) is
required. The runtime has no third-party Python dependencies and needs no API key
for installation or offline verification.

## Install and verify

Use the repository's `scripts/prepare_collaborator_workspace.py` to prepare a new
owner-approved workspace with this runtime and the five-layer memory structure.
It refuses existing destinations. For an existing workspace inspect and map its
canonical homes, then review a scoped integration; do not generate a second master.

From the resulting workspace run:

```sh
python3 runtime/check_install.py
python3 scripts/oos_context.py --root . validate
python3 runtime/scripts/route_model_task.py --help
```

`OFFLINE_RUNTIME_TESTED` means checksums and included offline tests passed on that
machine. It does not mean a live provider, remote archive, GitHub write channel or
publishing service is connected. Review this candidate before main/production
integration. Configuration and authentication belong to the new owner.
Obtain the entire package from one verified Git commit. The manifest detects changed
files relative to that package; it is not a signature or proof of sender identity.

## Components and their actual boundaries

| Component | Implemented behavior | Setup still required |
| --- | --- | --- |
| `oos/retrieval.py` | SQLite corpus isolation, source/chunk hashes, local search | Index only the owner's approved sources; cache is derived, not a new SOT |
| `oos/chat_journal.py` | Append-only hashed chat evidence and promotion checks | Bind authenticated inputs and serialize writers; do not replace the canonical decision journal |
| `oos/execution.py` | Principal/capability/authorization and receipt state machine | Adapter-owned durable admission and actual tool integration |
| `oos/artifact_ingestion.py` | Artifact fingerprinting, quarantine and verification | Owner's archive/index sinks; no provider UI upload interception |
| `oos/company.py` | Fail-closed skill/capability policy and routing | Owner-specific registry; no tool execution by this module |
| `oos/model_router.py`, `providers.py` | Configurable model routing, OpenAI/Ollama transports | Owner's keys/model IDs or separately installed local provider; potential API charges |
| GitHub signal modules | Read-only source sync, SQLite records and non-executing proposals | Owner's approved token, repository scope and database |
| Prompt/reliability/torture modules | Version/digest checks and evidence evaluation | Actual evidence; synthetic fixtures never count as live success |
| `vita/` | Trusted action and location/time/provenance checks | Real sensors/evidence and separately authorized executors |

The companion Context gate is installed at `scripts/oos_context.py` in the workspace.
It requires recorded predecessor results and acknowledgement; authenticated transport
and exactly-once delivery remain adapter responsibilities.

## Source and privacy

`DISTRIBUTION.json` records exact source commits, source SHA-256 and distributed
SHA-256 per file. Source code is unchanged except for documented fixture/configuration
sanitization. Artifact ingestion uses the separately tested hardening candidate
`201a597134428f6c982f3ec69907346cbc733578`, which remains under review. Other source
modules use `1f3903d27f2d248d5879a8ac8e41bb7b4bb84507`. This combined distribution has
its own offline tests; it is not a claim that either candidate was merged or released.

Personal journals, source chat history, evidence archives, customer data, deployment
targets, credentials and Git history are excluded. Company identity is a neutral
template; optional prompt skills are disabled, not falsely marked installed. All
included tests use synthetic fixtures; historical benchmark records are replaced
with synthetic equivalents. The source author's MIT attribution is preserved.

Project-specific website plugins, rental publishing rules/data and deployment services
are outside this general runtime. They are not needed for independent chat memory.
No inactive PHP architecture described in older notes is claimed as installed.

## Persistence and recovery

GitHub persistence requires a private destination approved by its owner, an authorized
write, and readback of the resulting commit. A local folder alone is not remote memory.
Never commit tokens, environment files, raw private uploads or SQLite caches. Preserve
source records and append corrections; rebuild derived indexes from their primary
sources. Keep evidence-level chat journals separate from accepted decision authority.

To roll back a proposed installation, discard its unmerged branch. To undo an accepted
installation, revert its installation commit while preserving subsequent owner data.


## Reviewed-candidate corrections (2026-10-17)

This distribution contains local corrections to the pinned upstream sources, not a
claim that the upstream repositories have adopted them. Original source hashes remain
in DISTRIBUTION.json; distributed hashes identify the corrected bytes.

- Successful directory ingestion transactionally reconciles that root's source namespace
  in the selected corpus. Deleted or newly disallowed files and their chunks are removed;
  unrelated roots/corpora and explicit single-file ingestions are preserved. Failed
  replacements roll back pruning.
- Webhook deliveries with non-null source_event_id reuse the first stored raw event and
  signal even when receipt-derived timestamps change. Conflicting evidence under an
  existing delivery ID is rejected. Sources without delivery IDs retain fingerprint
  deduplication. Database serialization covers the delivery lookup and raw insert.
- Pattern detection reconstructs reversible STAR/WATCH/FOLLOW state by occurrence time
  and applies UNSTAR/UNWATCH/UNFOLLOW before deriving current interest patterns. Raw
  observations and previously persisted inferences remain historical evidence.

The corrected Context gate is pinned to PR #10 commit
`b0a19bfebe9eeb9d507c1f6f33f959d34e44da33`. Both candidates still require current-head
review and acceptance. No live provider transport or production deployment is implied.

Further review corrections bind the sync CLI actor to authenticated GET /user before
opening the local store, exclude withdrawn historical patterns from current CLI output,
and average token totals per execution. Token totals sum observed components per run;
missing components contribute zero and runs with neither token metric are excluded.
Partial telemetry is not an estimate of unobserved consumption. The Context pin also
rejects replayed message IDs across attempts and caps journal/index reads before allocation.
