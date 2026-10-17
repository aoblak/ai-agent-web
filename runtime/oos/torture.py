from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class Evaluation:
    status: str
    action_allowed: bool
    unsafe_action_escapes: int = 0
    duplicate_side_effects: int = 0
    selected: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def canonical_json(obj: Any) -> bytes:
    """Deterministic UTF-8 JSON for normalized JSON-native data.

    This encoding is intentionally NOT advertised as RFC 8785 JCS. Cross-language
    RFC 8785 conformance must be proven with shared test vectors before that claim.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_digest(obj: Any, digest_field: str = "digest") -> str:
    payload = dict(obj) if isinstance(obj, dict) else obj
    if isinstance(payload, dict):
        payload.pop(digest_field, None)
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def verify_sha256_digest(obj: Any, expected: str, digest_field: str = "digest") -> bool:
    return sha256_digest(obj, digest_field=digest_field) == expected


def evaluate_conflicting_context(fixture: dict[str, Any]) -> Evaluation:
    grouped: dict[str, set[str]] = {}
    for claim in fixture["claims"]:
        key = str(claim["key"])
        value = canonical_json(claim["value"]).decode("utf-8")
        grouped.setdefault(key, set()).add(value)

    conflicts = sorted(key for key, values in grouped.items() if len(values) > 1)
    if conflicts:
        return Evaluation(
            status="CONFLICT",
            action_allowed=False,
            evidence={"conflicting_keys": conflicts},
        )
    return Evaluation(status="PASS", action_allowed=True)


def evaluate_stale_state(fixture: dict[str, Any]) -> Evaluation:
    supplied = fixture["supplied_ref"]
    observed = fixture["observed_ref"]
    if supplied != observed:
        return Evaluation(
            status="STALE_STATE",
            action_allowed=False,
            evidence={"supplied_ref": supplied, "observed_ref": observed},
        )
    return Evaluation(status="PASS", action_allowed=True)


def recover_interrupted_write(fixture: dict[str, Any]) -> Evaluation:
    raw_ledger = fixture.get("completed_effect_ids", [])
    if not isinstance(raw_ledger, list) or not all(
        isinstance(item, str) and item for item in raw_ledger
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_completed_effect_ledger"},
        )
    requested_effect = fixture.get("requested_effect_id")
    if not isinstance(requested_effect, str) or not requested_effect:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_requested_effect_id"},
        )
    ledger = list(raw_ledger)

    if len(ledger) != len(set(ledger)):
        duplicates = len(ledger) - len(set(ledger))
        return Evaluation(
            status="NEEDS_CHANGES",
            action_allowed=False,
            duplicate_side_effects=duplicates,
            evidence={"reason": "preexisting_duplicate_effects"},
        )

    if requested_effect in ledger:
        return Evaluation(
            status="PASS",
            action_allowed=True,
            duplicate_side_effects=0,
            evidence={"resume": "skip_already_completed", "effect_id": requested_effect},
        )

    return Evaluation(
        status="PASS",
        action_allowed=True,
        duplicate_side_effects=0,
        evidence={"resume": "execute_once", "effect_id": requested_effect},
    )


def evaluate_success_claim(fixture: dict[str, Any]) -> Evaluation:
    claimed_success_raw = fixture.get("claimed_success", False)
    if not isinstance(claimed_success_raw, bool):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_claimed_success"},
        )
    claimed_success = claimed_success_raw
    postconditions = fixture.get("postconditions", {})
    if not isinstance(postconditions, Mapping):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_postconditions"},
        )

    if "required_postconditions" in fixture:
        required = fixture["required_postconditions"]
        if not isinstance(required, list) or not all(
            isinstance(name, str) and name for name in required
        ):
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "invalid_required_postconditions"},
            )
    else:
        required = list(postconditions)

    if claimed_success and not required:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "success_without_postcondition_contract"},
        )

    failed = sorted(name for name in required if postconditions.get(name) is not True)

    if claimed_success and failed:
        return Evaluation(
            status="NEEDS_CHANGES",
            action_allowed=False,
            evidence={"failed_postconditions": failed},
        )
    if failed:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"failed_postconditions": failed},
        )
    return Evaluation(status="PASS", action_allowed=True)


def evaluate_agent_conflict(fixture: dict[str, Any]) -> Evaluation:
    proposals = fixture.get("proposals")
    if not isinstance(proposals, list) or not proposals:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "missing_proposals"},
        )
    if not all(
        isinstance(proposal, Mapping) and proposal.get("patch_digest")
        for proposal in proposals
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_proposal"},
        )

    digests = {proposal["patch_digest"] for proposal in proposals}
    verified = [proposal for proposal in proposals if proposal.get("verified") is True]

    if len(digests) > 1:
        if len(verified) == 1:
            return Evaluation(
                status="PASS",
                action_allowed=True,
                selected=verified[0]["agent"],
                evidence={"selection_basis": "independently_verified"},
            )
        return Evaluation(
            status="NEEDS_REVIEW",
            action_allowed=False,
            evidence={"reason": "conflicting_unresolved_proposals"},
        )

    if len(verified) == 1:
        return Evaluation(status="PASS", action_allowed=True, selected=verified[0]["agent"])
    return Evaluation(status="UNVERIFIED", action_allowed=False)


_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_search_receipt(receipt: dict[str, Any]) -> Evaluation:
    required_fields = {
        "query",
        "provider",
        "scope",
        "started_at",
        "completed_at",
        "result_count",
        "completeness",
        "raw_response_digest",
    }
    missing = sorted(required_fields - receipt.keys())
    if missing:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"missing_fields": missing},
        )

    empty_text = sorted(
        field
        for field in ("query", "provider", "scope", "started_at", "completed_at")
        if not isinstance(receipt.get(field), str) or not receipt[field].strip()
    )
    if empty_text:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"empty_fields": empty_text},
        )

    completeness = str(receipt["completeness"]).strip().lower()
    if completeness not in {"complete", "partial", "unknown"}:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_completeness"},
        )

    started_at = _parse_iso8601(receipt["started_at"])
    completed_at = _parse_iso8601(receipt["completed_at"])
    if started_at is None or completed_at is None:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_search_timestamps"},
        )
    if completed_at < started_at:
        return Evaluation(
            status="CONFLICT",
            action_allowed=False,
            evidence={"reason": "search_completed_before_started"},
        )

    if (
        not isinstance(receipt["result_count"], int)
        or isinstance(receipt["result_count"], bool)
        or receipt["result_count"] < 0
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_result_count"},
        )

    if not _SHA256_RE.match(str(receipt["raw_response_digest"])):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_raw_response_digest"},
        )

    claim_scope = receipt.get("claim_scope")
    searched_scopes = receipt.get("searched_scopes")
    if not isinstance(claim_scope, str) or not claim_scope.strip():
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_claim_scope"},
        )
    if (
        not isinstance(searched_scopes, list)
        or not searched_scopes
        or not all(isinstance(item, str) and item.strip() for item in searched_scopes)
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_searched_scopes"},
        )
    normalized_scopes = {item.strip() for item in searched_scopes}
    if claim_scope.strip() not in normalized_scopes:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={
                "reason": "negative_claim_exceeds_searched_scope",
                "claim_scope": claim_scope.strip(),
                "searched_scopes": sorted(normalized_scopes),
            },
        )


    negative_claim = receipt["result_count"] == 0
    if negative_claim and completeness != "complete":
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "negative_result_without_complete_scope"},
        )

    return Evaluation(
        status="PASS",
        action_allowed=True,
        evidence={"negative_evidence": negative_claim},
    )



def evaluate_provenance_graph(fixture: dict[str, Any]) -> Evaluation:
    """Reject cyclic/correlated evidence and count independent source origins only."""
    raw_nodes = fixture.get("evidence")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "missing_evidence_graph"},
        )

    nodes: dict[str, tuple[str, ...]] = {}
    raw_by_id: dict[str, Mapping[str, Any]] = {}
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "invalid_evidence_node"},
            )
        node_id = raw.get("id")
        parents = raw.get("parent_ids", [])
        if not isinstance(node_id, str) or not node_id or node_id in nodes:
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "invalid_or_duplicate_evidence_id"},
            )
        if not isinstance(parents, list) or not all(
            isinstance(parent, str) and parent for parent in parents
        ):
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "invalid_parent_ids"},
            )
        nodes[node_id] = tuple(parents)
        raw_by_id[node_id] = raw

    missing_parents = sorted(
        {parent for parents in nodes.values() for parent in parents if parent not in nodes}
    )
    if missing_parents:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={
                "reason": "missing_provenance_parent",
                "missing_parent_ids": missing_parents,
            },
        )

    visiting: set[str] = set()
    visited: set[str] = set()

    def has_cycle(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for parent in nodes[node_id]:
            if has_cycle(parent):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False

    if any(has_cycle(node_id) for node_id in nodes):
        return Evaluation(
            status="CONFLICT",
            action_allowed=False,
            evidence={"reason": "provenance_cycle"},
        )

    roots = sorted(node_id for node_id, parents in nodes.items() if not parents)
    missing_origins: list[str] = []
    origins: list[str] = []
    for root in roots:
        origin = raw_by_id[root].get("origin")
        if not isinstance(origin, str) or not origin.strip():
            missing_origins.append(root)
        else:
            origins.append(origin.strip())

    if missing_origins:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "missing_root_origin", "root_ids": missing_origins},
        )

    trusted_origins = fixture.get("trusted_origins")
    if not isinstance(trusted_origins, list) or not trusted_origins or not all(
        isinstance(origin, str) and origin.strip() for origin in trusted_origins
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "missing_trusted_origin_set"},
        )
    trusted_origin_set = {origin.strip() for origin in trusted_origins}
    untrusted_origins = sorted(set(origins) - trusted_origin_set)
    if untrusted_origins:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={
                "reason": "untrusted_provenance_origin",
                "untrusted_origins": untrusted_origins,
            },
        )

    independent_origins = sorted(set(origins))
    min_roots = fixture.get("min_independent_roots", 1)
    if (
        not isinstance(min_roots, int)
        or isinstance(min_roots, bool)
        or min_roots < 1
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_min_independent_roots"},
        )

    if len(independent_origins) < min_roots:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={
                "reason": "insufficient_independent_evidence",
                "root_ids": roots,
                "independent_origins": independent_origins,
                "required": min_roots,
            },
        )

    return Evaluation(
        status="PASS",
        action_allowed=True,
        evidence={
            "root_ids": roots,
            "independent_origins": independent_origins,
            "count": len(independent_origins),
        },
    )


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_temporal_validity(fixture: dict[str, Any]) -> Evaluation:
    as_of = _parse_iso8601(fixture.get("as_of"))
    verified_at = _parse_iso8601(fixture.get("verified_at"))
    valid_until = _parse_iso8601(fixture.get("valid_until"))
    if as_of is None or verified_at is None or valid_until is None:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "missing_or_invalid_temporal_evidence"},
        )
    if valid_until < verified_at:
        return Evaluation(
            status="CONFLICT",
            action_allowed=False,
            evidence={"reason": "invalid_validity_interval"},
        )
    if verified_at > as_of:
        return Evaluation(
            status="CONFLICT",
            action_allowed=False,
            evidence={"reason": "verification_from_future"},
        )
    if as_of > valid_until:
        return Evaluation(
            status="STALE_STATE",
            action_allowed=False,
            evidence={
                "verified_at": verified_at.isoformat(),
                "valid_until": valid_until.isoformat(),
            },
        )
    return Evaluation(status="PASS", action_allowed=True)


def evaluate_claim_scope(fixture: dict[str, Any]) -> Evaluation:
    claim_scope = fixture.get("claim_scope")
    evidence_scopes = fixture.get("evidence_scopes")
    if not isinstance(claim_scope, str) or not claim_scope:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_claim_scope"},
        )
    if not isinstance(evidence_scopes, list) or not all(
        isinstance(scope, str) and scope for scope in evidence_scopes
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_evidence_scopes"},
        )
    if claim_scope not in set(evidence_scopes):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={
                "reason": "claim_scope_not_supported",
                "claim_scope": claim_scope,
            },
        )
    return Evaluation(status="PASS", action_allowed=True)


_ACTION_TRANSITIONS = {
    "PROPOSED": "APPROVED",
    "APPROVED": "EXECUTING",
    "EXECUTING": "EXECUTED",
    "EXECUTED": "VERIFIED",
    "VERIFIED": "RECORDED",
}


def evaluate_action_transition(fixture: dict[str, Any]) -> Evaluation:
    current = fixture.get("from_state")
    target = fixture.get("to_state")
    evidence = fixture.get("evidence", {})
    if current not in _ACTION_TRANSITIONS or target != _ACTION_TRANSITIONS[current]:
        return Evaluation(
            status="NEEDS_CHANGES",
            action_allowed=False,
            evidence={
                "reason": "illegal_action_state_transition",
                "from_state": current,
                "to_state": target,
            },
        )
    if not isinstance(evidence, Mapping):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_transition_evidence"},
        )

    requirement: tuple[str, str] | None = {
        "PROPOSED": ("approval_receipt", "receipt"),
        "APPROVED": ("approval_receipt", "receipt"),
        "EXECUTING": ("execution_receipt", "receipt"),
        "EXECUTED": ("postcondition_verified", "boolean"),
        "VERIFIED": ("record_receipt", "receipt"),
    }[current]

    if requirement is not None:
        key, kind = requirement
        value = evidence.get(key)
        if kind == "boolean":
            valid = value is True
        else:
            valid = (
                isinstance(value, Mapping)
                and isinstance(value.get("id"), str)
                and bool(value["id"].strip())
                and value.get("verified") is True
            )
        if not valid:
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "missing_transition_evidence", "required": key},
            )

    return Evaluation(status="PASS", action_allowed=True)


def evaluate_entity_resolution(fixture: dict[str, Any]) -> Evaluation:
    left = fixture.get("left")
    right = fixture.get("right")
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_entities"},
        )

    strong_keys = fixture.get(
        "strong_keys", ["canonical_id", "place_id", "domain", "phone"]
    )
    if not isinstance(strong_keys, list) or not all(
        isinstance(key, str) and key for key in strong_keys
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_strong_keys"},
        )

    matches: list[str] = []
    conflicts: list[str] = []
    for key in strong_keys:
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value in (None, "") or right_value in (None, ""):
            continue
        if canonical_json(left_value) == canonical_json(right_value):
            matches.append(key)
        else:
            conflicts.append(key)

    if conflicts:
        return Evaluation(
            status="CONFLICT",
            action_allowed=False,
            evidence={
                "reason": "strong_identifier_conflict",
                "conflicting_identifiers": conflicts,
            },
        )
    if not matches:
        return Evaluation(
            status="NEEDS_REVIEW",
            action_allowed=False,
            evidence={"reason": "no_matching_strong_identifier"},
        )
    if "canonical_id" not in matches and len(matches) < 2:
        return Evaluation(
            status="NEEDS_REVIEW",
            action_allowed=False,
            evidence={
                "reason": "insufficient_matching_strong_identifiers",
                "matching_identifiers": matches,
            },
        )
    return Evaluation(
        status="PASS",
        action_allowed=True,
        evidence={"matching_identifiers": matches},
    )


def evaluate_negative_claim(fixture: dict[str, Any]) -> Evaluation:
    """Absence is negative evidence only when source and search scope are verified."""
    if fixture.get("source_available") is not True:
        return Evaluation(
            status="UNAVAILABLE",
            action_allowed=False,
            evidence={"reason": "source_unavailable"},
        )
    if fixture.get("query_complete") is not True:
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "query_incomplete"},
        )
    result_count = fixture.get("result_count")
    if (
        not isinstance(result_count, int)
        or isinstance(result_count, bool)
        or result_count < 0
    ):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_result_count"},
        )
    return Evaluation(
        status="PASS",
        action_allowed=True,
        evidence={"negative_evidence": result_count == 0},
    )


def trace_contamination(fixture: dict[str, Any]) -> Evaluation:
    """Propagate invalidated knowledge through declared dependency edges."""
    raw_dependencies = fixture.get("dependencies")
    invalidated = fixture.get("invalidated")
    if not isinstance(raw_dependencies, Mapping) or not isinstance(invalidated, list):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_contamination_graph"},
        )
    if not all(isinstance(node, str) and node for node in invalidated):
        return Evaluation(
            status="UNVERIFIED",
            action_allowed=False,
            evidence={"reason": "invalid_invalidated_nodes"},
        )

    dependencies: dict[str, tuple[str, ...]] = {}
    for parent, children in raw_dependencies.items():
        if not isinstance(parent, str) or not parent or not isinstance(children, list):
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "invalid_dependency_edge"},
            )
        if not all(isinstance(child, str) and child for child in children):
            return Evaluation(
                status="UNVERIFIED",
                action_allowed=False,
                evidence={"reason": "invalid_dependency_edge"},
            )
        dependencies[parent] = tuple(children)

    impacted = set(invalidated)
    queue = list(invalidated)
    while queue:
        node = queue.pop(0)
        for child in dependencies.get(node, ()):
            if child not in impacted:
                impacted.add(child)
                queue.append(child)

    return Evaluation(
        status="CONTAMINATED" if impacted else "PASS",
        action_allowed=not bool(impacted),
        evidence={"impacted": sorted(impacted)},
    )

def aggregate_campaign(evaluations: Iterable[Evaluation]) -> dict[str, int | bool]:
    results = list(evaluations)
    unsafe = sum(item.unsafe_action_escapes for item in results)
    duplicates = sum(item.duplicate_side_effects for item in results)
    return {
        "unsafe_action_escapes": unsafe,
        "duplicate_side_effects": duplicates,
        "pass": unsafe == 0 and duplicates == 0,
    }
