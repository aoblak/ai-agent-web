#!/usr/bin/env python3
"""Synthetic protocol-model matrix: 44 runtime/storage scenarios × 10 Boolean invariants = 440 evaluations.

This is deterministic model-level checking, not 440 independent runtime tests and not live calls to commercial AI systems.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PROMPT = (Path(__file__).resolve().parents[1] / "MASTER_PROMPT.md").read_text(encoding="utf-8")

EXPECTED_ONBOARDING = [
    "Who are you?",
    "What are you trying to achieve in the next 6–12 months?",
    "What are you currently working on?",
    "How should I work with you?",
    "What should I know or never forget?",
]


def onboarding_questions() -> list[str]:
    m = re.search(
        r"^## 7\. First-run onboarding — exactly five questions\s*$([\s\S]*?)^## 8\.",
        PROMPT,
        flags=re.MULTILINE,
    )
    if not m:
        return []
    raw_items = re.findall(r"^\d+\.\s+(.+?)$", m.group(1), flags=re.MULTILINE)
    questions = []
    for item in raw_items:
        bold = re.match(r"^\*\*(.+?\?)\*\*", item.strip())
        questions.append(bold.group(1) if bold else item.strip())
    return questions


@dataclass(frozen=True)
class Scenario:
    name: str
    session: bool
    durable_files: bool
    indexed_memory: bool
    repo_read: bool
    repo_write: bool
    provider_verified: bool
    existing_canon: bool
    high_impact: bool


# 11 capability profiles × existing-canon yes/no × high-impact yes/no = 44.
# Provider verification is modeled independently from file-backed/native persistence.
BASES = [
    ("stateless", False, False, False, False, False, False),
    ("session_only", True, False, False, False, False, False),
    ("file_readonly", True, False, False, True, False, False),
    ("file_backed", True, True, False, False, False, False),
    ("file_backed_provider_verified", True, True, False, False, False, True),
    ("file_backed_repo_write", True, True, False, True, True, False),
    ("native_memory_no_files", True, False, True, False, False, False),
    ("native_memory_file_backed", True, True, True, False, False, False),
    ("native_provider_verified_no_files", True, False, True, False, False, True),
    ("native_repo_write", True, True, True, True, True, False),
    ("session_repo_write", True, False, False, True, True, False),
]

SCENARIOS = []
for name, session, files, native, rr, rw, provider_verified in BASES:
    for existing in (False, True):
        for high in (False, True):
            SCENARIOS.append(
                Scenario(
                    name=f"{name}__canon_{int(existing)}__risk_{int(high)}",
                    session=session,
                    durable_files=files,
                    indexed_memory=native,
                    repo_read=rr,
                    repo_write=rw,
                    provider_verified=provider_verified,
                    existing_canon=existing,
                    high_impact=high,
                )
            )
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
    if m in {"M0", "M1"}:
        persistence = "NONE"
    elif s.provider_verified:
        persistence = "PROVIDER_VERIFIED"
    else:
        persistence = "READBACK_VERIFIED"
    return {
        "mode": m,
        "persistence": persistence,
        "repo_write_status": "AVAILABLE" if s.repo_write else "UNAVAILABLE",
        "action_gate": "HUMAN_APPROVAL_REQUIRED" if s.high_impact else "NORMAL_AUTHORIZATION",
        "canon_action": "REUSE" if s.existing_canon else "DISCOVER_OR_MINIMAL_BOOTSTRAP",
    }


def checks(s: Scenario):
    d = simulate(s)
    questions = onboarding_questions()
    return [
        ("valid_mode", d["mode"] in {"M0", "M1", "M2", "M3"}),
        ("m3_requires_index", (d["mode"] != "M3") or s.indexed_memory),
        ("m2_requires_durable_files", (d["mode"] != "M2") or s.durable_files),
        ("repo_write_status_truthful", d["repo_write_status"] == ("AVAILABLE" if s.repo_write else "UNAVAILABLE")),
        ("provider_verified_requires_explicit_proof", (d["persistence"] != "PROVIDER_VERIFIED") or s.provider_verified),
        ("existing_canon_reuse", (not s.existing_canon) or d["canon_action"] == "REUSE"),
        ("exactly_five_questions", questions == EXPECTED_ONBOARDING and len(questions) == 5),
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