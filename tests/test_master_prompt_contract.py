#!/usr/bin/env python3
"""Deterministic contract suite: 44 runtime/storage scenarios × 10 invariants = 440 checks.

This validates the protocol model; it does not impersonate or call commercial AI models.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT = (Path(__file__).resolve().parents[1] / "MASTER_PROMPT.md").read_text(encoding="utf-8")

@dataclass(frozen=True)
class Scenario:
    name: str
    session: bool
    durable_files: bool
    indexed_memory: bool
    repo_read: bool
    repo_write: bool
    provider_pending: bool
    existing_canon: bool
    high_impact: bool

BASES = [
    ("stateless", False, False, False, False, False),
    ("session_only", True, False, False, False, False),
    ("file_readonly", True, False, False, True, False),
    ("file_backed", True, True, False, False, False),
    ("file_backed_repo_read", True, True, False, True, False),
    ("file_backed_repo_write", True, True, False, True, True),
    ("native_memory", True, True, True, False, False),
    ("native_repo_read", True, True, True, True, False),
    ("native_repo_write", True, True, True, True, True),
    ("session_repo_read", True, False, False, True, False),
    ("session_repo_write", True, False, False, True, True),
]

SCENARIOS = []
for name, session, files, native, rr, rw in BASES:
    for existing in (False, True):
        for high in (False, True):
            SCENARIOS.append(Scenario(
                name=f"{name}__canon_{int(existing)}__risk_{int(high)}",
                session=session,
                durable_files=files,
                indexed_memory=native,
                repo_read=rr,
                repo_write=rw,
                provider_pending=(files and not native and existing),
                existing_canon=existing,
                high_impact=high,
            ))
assert len(SCENARIOS) == 44


def mode(s: Scenario) -> str:
    if s.indexed_memory:
        return "M3"
    if s.durable_files:
        return "M2"
    if s.session:
        return "M1"
    return "M0"


def simulate(s: Scenario):
    m = mode(s)
    persistence = "NONE" if m in {"M0", "M1"} else ("READBACK_VERIFIED" if s.provider_pending else "PROVIDER_VERIFIED")
    repo_write_status = "AVAILABLE" if s.repo_write else "UNAVAILABLE"
    action_gate = "HUMAN_APPROVAL_REQUIRED" if s.high_impact else "NORMAL_AUTHORIZATION"
    canon_action = "REUSE" if s.existing_canon else "DISCOVER_OR_MINIMAL_BOOTSTRAP"
    return {
        "mode": m,
        "persistence": persistence,
        "repo_write_status": repo_write_status,
        "action_gate": action_gate,
        "canon_action": canon_action,
    }


def checks(s: Scenario):
    d = simulate(s)
    return [
        ("valid_mode", d["mode"] in {"M0", "M1", "M2", "M3"}),
        ("m3_requires_index", (d["mode"] != "M3") or s.indexed_memory),
        ("m2_m3_require_durable_files", (d["mode"] not in {"M2", "M3"}) or s.durable_files),
        ("repo_write_status_truthful", d["repo_write_status"] == ("AVAILABLE" if s.repo_write else "UNAVAILABLE")),
        ("provider_pending_not_provider_verified", (not s.provider_pending) or d["persistence"] == "READBACK_VERIFIED"),
        ("existing_canon_reuse", (not s.existing_canon) or d["canon_action"] == "REUSE"),
        ("five_questions_present", all(q in PROMPT for q in ["Who are you?", "next 6–12 months", "currently working on?", "How should I work with you?", "never forget?"])),
        ("done_and_write_gates_present", "DONE + VERIFIED EVIDENCE" in PROMPT and "write accepted ≠ write verified" in PROMPT and "READBACK_VERIFIED" in PROMPT),
        ("high_impact_fail_closed", (not s.high_impact) or (d["action_gate"] == "HUMAN_APPROVAL_REQUIRED" and "fail closed" in PROMPT.lower())),
        ("no_parallel_default_canon", "competing master journal" in PROMPT.lower() and "one canonical home per fact" in PROMPT.lower()),
    ]


def main() -> int:
    total = passed = 0
    failures = []
    for s in SCENARIOS:
        for name, ok in checks(s):
            total += 1
            if ok:
                passed += 1
            else:
                failures.append((s.name, name))
    print(f"scenarios={len(SCENARIOS)} invariants=10 checks={total} passed={passed} failed={len(failures)}")
    if failures:
        for f in failures[:50]:
            print("FAIL", *f)
        return 1
    assert total == 440
    return 0

if __name__ == "__main__":
    raise SystemExit(main())