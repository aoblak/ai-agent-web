from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from oos.github_signal_adapter import GitHubRestClient
from oos.github_signal_ingester import GitHubSignalStore
from oos.signals import Signal, SignalType


@dataclass(frozen=True)
class EvidencePattern:
    pattern_type: str
    actor: str
    object_id: str
    claim_class: str
    evidence_signal_ids: tuple[int, ...]
    proposed_action: str

    def fingerprint(self) -> str:
        payload = {
            "pattern_type": self.pattern_type,
            "actor": self.actor,
            "object_id": self.object_id,
            "claim_class": self.claim_class,
            "evidence_signal_ids": sorted(self.evidence_signal_ids),
            "proposed_action": self.proposed_action,
        }
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


STRONG_SKILL_PATTERN_TYPES = frozenset({"INTEREST_TO_EXPERIMENT"})


@dataclass(frozen=True)
class SkillCandidate:
    candidate_id: str
    review_state: str
    actor: str
    object_id: str
    source_pattern_type: str
    pattern_fingerprint: str
    evidence_signal_ids: tuple[int, ...]
    authority_home: str = "registry/company-os.json"


def project_github_behavior_signals(
    store: GitHubSignalStore,
    *,
    experiment_id: str = "github-signal-ingester",
    question_version: str = "v0.4",
) -> list[Signal]:
    """Project provider-observed GitHub behavior into the generic signal model.

    These are behavioral observations, not motive, quality, endorsement or truth
    judgments. Exact GitHub signal IDs remain in provenance references.
    """

    projected: list[Signal] = []
    for row in store.signal_rows():
        signal_id = int(row["signal_id"])
        projected.append(
            Signal(
                signal_id=f"github:{signal_id}",
                experiment_id=experiment_id,
                question_version=question_version,
                signal_type=SignalType.HUMAN_BEHAVIOR_SIGNAL,
                source_id=str(row["actor"]),
                response={
                    "canonical_action": str(row["canonical_action"]),
                    "semantic_class": str(row["semantic_class"]),
                    "object_type": str(row["object_type"]),
                    "object_id": str(row["object_id"]),
                    "actor_relation": str(row["actor_relation"]),
                    "evaluation": row["evaluation"],
                },
                timestamp=str(row["occurred_at"]),
                context_ref=f"github:{row['object_type']}:{row['object_id']}",
                provenance_ref=f"github-signal:{signal_id}",
                sampling_method="github_provider_observation",
            )
        )
    return projected


def project_pattern_inferences(
    patterns: Iterable[EvidencePattern],
    *,
    detected_at: str,
    experiment_id: str = "github-signal-ingester",
    question_version: str = "v0.4",
) -> list[Signal]:
    """Project deterministic evidence chains as SYSTEM_INFERENCE, never EVIDENCE."""

    projected: list[Signal] = []
    for pattern in patterns:
        fingerprint = pattern.fingerprint()
        projected.append(
            Signal(
                signal_id=f"github-inference:{fingerprint}",
                experiment_id=experiment_id,
                question_version=question_version,
                signal_type=SignalType.SYSTEM_INFERENCE,
                source_id="oos.github_signal_analysis",
                response={
                    "pattern_type": pattern.pattern_type,
                    "actor": pattern.actor,
                    "object_id": pattern.object_id,
                    "claim_class": pattern.claim_class,
                    "proposed_action": pattern.proposed_action,
                    "evidence_signal_ids": list(pattern.evidence_signal_ids),
                },
                timestamp=detected_at,
                context_ref=f"github-pattern:{fingerprint}",
                provenance_ref="github-signals:" + ",".join(
                    str(signal_id) for signal_id in pattern.evidence_signal_ids
                ),
                sampling_method="deterministic_evidence_chain",
            )
        )
    return projected


def build_skill_candidates(
    patterns: Iterable[EvidencePattern],
) -> list[SkillCandidate]:
    """Create review-only candidates from bounded strong patterns.

    Candidate generation is intentionally non-mutating. It does not edit the
    Company OS or skill registries and cannot promote a candidate to implemented
    or published state.
    """

    candidates: list[SkillCandidate] = []
    for pattern in patterns:
        if pattern.pattern_type not in STRONG_SKILL_PATTERN_TYPES:
            continue
        fingerprint = pattern.fingerprint()
        candidates.append(
            SkillCandidate(
                candidate_id="skill-candidate:" + fingerprint,
                review_state="REVIEW_REQUIRED",
                actor=pattern.actor,
                object_id=pattern.object_id,
                source_pattern_type=pattern.pattern_type,
                pattern_fingerprint=fingerprint,
                evidence_signal_ids=tuple(sorted(pattern.evidence_signal_ids)),
            )
        )
    return candidates


@dataclass(frozen=True)
class AnalysisSummary:
    detected: int
    persisted: int
    enriched: int


def _first_signal_id(rows: Iterable[dict[str, Any]], action: str) -> int | None:
    ids = [
        int(row["signal_id"])
        for row in rows
        if row["canonical_action"] == action
    ]
    return min(ids) if ids else None


def detect_evidence_patterns(store: GitHubSignalStore) -> list[EvidencePattern]:
    rows = store.signal_rows()
    # Reconstruct active reversible interests by event time, not insertion order.
    # Raw observations and earlier persisted inferences remain historical evidence.
    positive = {"STAR", "WATCH", "FOLLOW"}
    removals = {"UNSTAR": "STAR", "UNWATCH": "WATCH", "UNFOLLOW": "FOLLOW"}
    active: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    historical: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (
        datetime.fromisoformat(str(item["occurred_at"]).replace("Z", "+00:00")),
        int(item["signal_id"]),
    )):
        action = str(row["canonical_action"])
        key = (str(row["actor"]), str(row["object_type"]), str(row["object_id"]),
               removals.get(action, action))
        if action in removals:
            active.pop(key, None)
        elif action in positive:
            active.setdefault(key, row)
        else:
            historical.append(row)
    rows = historical + list(active.values())
    by_actor_repo: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    follows: dict[tuple[str, str], list[int]] = defaultdict(list)
    stars_by_actor_owner: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for row in rows:
        actor = str(row["actor"])
        action = str(row["canonical_action"])
        object_type = str(row["object_type"])
        object_id = str(row["object_id"])

        if object_type == "repository" and "/" in object_id:
            by_actor_repo[(actor, object_id)].append(row)
            if action == "STAR":
                owner = object_id.split("/", 1)[0]
                stars_by_actor_owner[(actor, owner)][object_id].append(
                    int(row["signal_id"])
                )
        elif object_type == "user" and action == "FOLLOW":
            follows[(actor, object_id)].append(int(row["signal_id"]))

    patterns: list[EvidencePattern] = []

    for (actor, repository), repo_rows in sorted(by_actor_repo.items()):
        star_id = _first_signal_id(repo_rows, "STAR")
        watch_id = _first_signal_id(repo_rows, "WATCH")
        fork_id = _first_signal_id(repo_rows, "FORK")
        if star_id is not None and watch_id is not None:
            patterns.append(
                EvidencePattern(
                    "SUSTAINED_ATTENTION",
                    actor,
                    repository,
                    "INFERRED",
                    tuple(sorted({star_id, watch_id})),
                    "KEEP_MONITORING",
                )
            )
        if star_id is not None and fork_id is not None:
            patterns.append(
                EvidencePattern(
                    "INTEREST_TO_EXPERIMENT",
                    actor,
                    repository,
                    "INFERRED",
                    tuple(sorted({star_id, fork_id})),
                    "INSPECT_WORKING_COPY",
                )
            )
        if star_id is not None:
            owner = repository.split("/", 1)[0]
            follow_ids = follows.get((actor, owner), [])
            if follow_ids:
                patterns.append(
                    EvidencePattern(
                        "PERSON_PROJECT_LINK",
                        actor,
                        repository,
                        "SUPPORTED",
                        tuple(sorted({star_id, min(follow_ids)})),
                        "INSPECT",
                    )
                )

    for (actor, owner), repositories in sorted(stars_by_actor_owner.items()):
        if len(repositories) < 2:
            continue
        evidence = sorted(
            {
                signal_id
                for ids in repositories.values()
                for signal_id in ids
            }
        )
        patterns.append(
            EvidencePattern(
                "OWNER_CLUSTER_INTEREST",
                actor,
                owner,
                "INFERRED",
                tuple(evidence),
                "INSPECT_OWNER",
            )
        )

    unique: dict[str, EvidencePattern] = {}
    for pattern in patterns:
        unique[pattern.fingerprint()] = pattern
    return [unique[key] for key in sorted(unique)]


def persist_evidence_patterns(
    store: GitHubSignalStore,
    patterns: Iterable[EvidencePattern],
    *,
    detected_at: str,
) -> int:
    before = len(store.patterns())
    for pattern in patterns:
        store.record_pattern(
            fingerprint=pattern.fingerprint(),
            pattern_type=pattern.pattern_type,
            actor=pattern.actor,
            object_id=pattern.object_id,
            claim_class=pattern.claim_class,
            evidence_signal_ids=list(pattern.evidence_signal_ids),
            proposed_action=pattern.proposed_action,
            detected_at=detected_at,
        )
    return len(store.patterns()) - before


def enrich_repositories(
    client: GitHubRestClient,
    store: GitHubSignalStore,
    repositories: Iterable[str],
    *,
    observed_at: str,
) -> int:
    count = 0
    for repository in sorted(set(repositories)):
        metadata = client.get_repository(repository)
        store.record_entity_observation(
            "repository",
            repository,
            metadata,
            observed_at=observed_at,
        )
        count += 1
    return count


def analyze(
    store: GitHubSignalStore,
    *,
    detected_at: str,
) -> AnalysisSummary:
    patterns = detect_evidence_patterns(store)
    persisted = persist_evidence_patterns(
        store,
        patterns,
        detected_at=detected_at,
    )
    return AnalysisSummary(
        detected=len(patterns),
        persisted=persisted,
        enriched=0,
    )
