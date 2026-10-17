from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


CLAIM_STATUSES = {
    "VERIFIED",
    "SUPPORTED",
    "INFERRED",
    "UNSUPPORTED",
    "CONTRADICTED",
    "UNKNOWN",
}

EVIDENCE_STATUSES = {"VERIFIED", "SUPPORTED", "CONTRADICTED"}
SOURCE_FIDELITIES = {"RAW", "PARTIAL", "SUMMARY", "RECONSTRUCTED"}
OUTPUT_ARTIFACT_FIELDS = ("raw_output", "raw_output_ref", "output_digest")
BACKFILL_ARTIFACT_FIELDS = ("raw_excerpt", "raw_output_ref")
REQUIRED_RUN_FIELDS = {
    "run_id",
    "prompt_id",
    "prompt_version",
    "prompt_source",
    "model",
    "context_version",
    "test_suite",
    "claims",
}
REQUIRED_NONEMPTY_RUN_FIELDS = REQUIRED_RUN_FIELDS - {"claims"}


@dataclass(frozen=True)
class ReliabilitySummary:
    total_claims: int
    verifiable_claims: int
    verified_claims: int
    supported_claims: int
    inferred_claims: int
    unsupported_claims: int
    contradicted_claims: int
    unknown_claims: int
    factual_hallucination_rate: float
    unsupported_claim_rate: float
    verified_claim_rate: float
    evidence_coverage: float
    safe_abstention_rate: float | None

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "total_claims": self.total_claims,
            "verifiable_claims": self.verifiable_claims,
            "verified_claims": self.verified_claims,
            "supported_claims": self.supported_claims,
            "inferred_claims": self.inferred_claims,
            "unsupported_claims": self.unsupported_claims,
            "contradicted_claims": self.contradicted_claims,
            "unknown_claims": self.unknown_claims,
            "factual_hallucination_rate": self.factual_hallucination_rate,
            "unsupported_claim_rate": self.unsupported_claim_rate,
            "verified_claim_rate": self.verified_claim_rate,
            "evidence_coverage": self.evidence_coverage,
            "safe_abstention_rate": self.safe_abstention_rate,
        }


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bytes, bytearray, list, tuple, dict, set)):
        return bool(value)
    return True


def _has_artifact_value(value: Any) -> bool:
    """Raw-output evidence must be actual preserved text/bytes or a stable text ref/digest."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bytes, bytearray)):
        return bool(value)
    return False


def _has_usable_reference(value: Any) -> bool:
    """Return True only when a reference collection contains a non-empty string ref."""
    if not isinstance(value, (list, tuple, set)):
        return False
    return any(isinstance(item, str) and bool(item.strip()) for item in value)


def validate_run_metadata(run: Mapping[str, Any]) -> list[str]:
    """Return missing/invalid metadata fields for a benchmark run.

    A run is only auditable when required identity/provenance values are non-empty and
    the evaluated output itself, a stable reference to it, or a digest is preserved
    alongside the claim annotations.
    """
    errors = [f"missing:{name}" for name in sorted(REQUIRED_RUN_FIELDS - run.keys())]

    for name in sorted(REQUIRED_NONEMPTY_RUN_FIELDS & run.keys()):
        if not _has_value(run.get(name)):
            errors.append(f"invalid:empty:{name}")

    claims = run.get("claims")
    if "claims" in run and not isinstance(claims, list):
        errors.append("invalid:claims_not_list")

    if not any(_has_artifact_value(run.get(field)) for field in OUTPUT_ARTIFACT_FIELDS):
        errors.append("missing:output_artifact")

    return errors


def backfill_eligibility(record: Mapping[str, Any]) -> dict[str, Any]:
    """Decide whether a historical record may contribute to numeric reliability KPIs."""
    fidelity = str(record.get("source_fidelity", "")).upper()
    if fidelity not in SOURCE_FIDELITIES:
        return {"eligible": False, "reason": "invalid_source_fidelity", "scope": None}
    if fidelity in {"SUMMARY", "RECONSTRUCTED"}:
        return {"eligible": False, "reason": "non_raw_historical_source", "scope": None}
    if record.get("source_verified") is not True:
        return {"eligible": False, "reason": "source_not_verified", "scope": None}
    if not any(_has_artifact_value(record.get(field)) for field in BACKFILL_ARTIFACT_FIELDS):
        return {"eligible": False, "reason": "raw_output_not_preserved", "scope": None}
    claims = record.get("claims")
    if not isinstance(claims, list) or not claims:
        return {"eligible": False, "reason": "no_scored_claims", "scope": None}
    if fidelity == "PARTIAL":
        if record.get("claim_scope_bounded") is not True:
            return {"eligible": False, "reason": "partial_scope_not_bounded", "scope": None}
        return {"eligible": True, "reason": "bounded_verified_partial", "scope": "bounded_partial"}
    return {"eligible": True, "reason": "verified_raw", "scope": "raw"}


def summarize_claims(claims: Iterable[Mapping[str, Any]]) -> ReliabilitySummary:
    items = list(claims)
    counts = {status: 0 for status in CLAIM_STATUSES}
    verifiable = 0
    verifiable_contradicted = 0
    evidence_covered = 0
    expected_unknown = 0
    correct_unknown = 0

    for claim in items:
        if not isinstance(claim, Mapping):
            raise ValueError("claim must be an object")
        status = str(claim.get("status", "")).upper()
        if status not in CLAIM_STATUSES:
            raise ValueError(f"invalid claim status: {status or '<empty>'}")
        counts[status] += 1

        is_verifiable = claim.get("verifiable", True)
        if not isinstance(is_verifiable, bool):
            raise ValueError("claim.verifiable must be boolean")
        expected_unknown_flag = claim.get("expected_unknown", False)
        if not isinstance(expected_unknown_flag, bool):
            raise ValueError("claim.expected_unknown must be boolean")

        if is_verifiable:
            verifiable += 1
            if status == "CONTRADICTED":
                verifiable_contradicted += 1
            if status in EVIDENCE_STATUSES and _has_usable_reference(claim.get("evidence_refs")):
                evidence_covered += 1
        if expected_unknown_flag:
            expected_unknown += 1
            if status == "UNKNOWN":
                correct_unknown += 1

    total = len(items)
    return ReliabilitySummary(
        total_claims=total,
        verifiable_claims=verifiable,
        verified_claims=counts["VERIFIED"],
        supported_claims=counts["SUPPORTED"],
        inferred_claims=counts["INFERRED"],
        unsupported_claims=counts["UNSUPPORTED"],
        contradicted_claims=counts["CONTRADICTED"],
        unknown_claims=counts["UNKNOWN"],
        factual_hallucination_rate=verifiable_contradicted / verifiable if verifiable else 0.0,
        unsupported_claim_rate=counts["UNSUPPORTED"] / total if total else 0.0,
        verified_claim_rate=counts["VERIFIED"] / total if total else 0.0,
        evidence_coverage=evidence_covered / verifiable if verifiable else 0.0,
        safe_abstention_rate=correct_unknown / expected_unknown if expected_unknown else None,
    )


def evaluate_backfill(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Evaluate only historically eligible records and preserve exclusion reasons."""
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    aggregate_claims: list[Mapping[str, Any]] = []

    for record in records:
        record_id = str(record.get("record_id", "<missing>"))
        eligibility = backfill_eligibility(record)
        if not eligibility["eligible"]:
            excluded.append({"record_id": record_id, **eligibility})
            continue

        claims = list(record["claims"])
        summary = summarize_claims(claims)
        included.append(
            {
                "record_id": record_id,
                "scope": eligibility["scope"],
                "metrics": summary.as_dict(),
            }
        )
        aggregate_claims.extend(claims)

    aggregate = summarize_claims(aggregate_claims)
    return {
        "included_records": len(included),
        "excluded_records": len(excluded),
        "included": included,
        "excluded": excluded,
        "aggregate": aggregate.as_dict(),
    }


def evaluate_run(run: Mapping[str, Any]) -> ReliabilitySummary:
    errors = validate_run_metadata(run)
    if errors:
        raise ValueError("; ".join(errors))
    return summarize_claims(run["claims"])


def promotion_gate(
    summary: ReliabilitySummary,
    *,
    max_factual_hallucination_rate: float = 0.0,
    max_unsupported_claim_rate: float = 0.05,
    min_evidence_coverage: float = 0.90,
    min_safe_abstention_rate: float | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if summary.factual_hallucination_rate > max_factual_hallucination_rate:
        failures.append("factual_hallucination_rate")
    if summary.unsupported_claim_rate > max_unsupported_claim_rate:
        failures.append("unsupported_claim_rate")
    if summary.evidence_coverage < min_evidence_coverage:
        failures.append("evidence_coverage")
    if min_safe_abstention_rate is not None:
        value = summary.safe_abstention_rate
        if value is None or value < min_safe_abstention_rate:
            failures.append("safe_abstention_rate")
    return {"promote": not failures, "failures": failures, "metrics": summary.as_dict()}


def compare_runs(
    baseline: ReliabilitySummary,
    candidate: ReliabilitySummary,
    *,
    hallucination_tolerance: float = 0.0,
    unsupported_tolerance: float = 0.0,
    evidence_coverage_tolerance: float = 0.0,
    safe_abstention_tolerance: float = 0.0,
) -> dict[str, Any]:
    """Detect candidate regressions against a baseline run.

    Lower is better for hallucination/unsupported rates. Higher is better for evidence
    coverage and safe abstention. If the baseline contains expected-unknown cases, a
    candidate that stops reporting an abstention metric is itself a regression because
    the benchmark is expected to be materially comparable.
    """
    regressions: list[str] = []
    if candidate.factual_hallucination_rate > baseline.factual_hallucination_rate + hallucination_tolerance:
        regressions.append("factual_hallucination_rate")
    if candidate.unsupported_claim_rate > baseline.unsupported_claim_rate + unsupported_tolerance:
        regressions.append("unsupported_claim_rate")
    if candidate.evidence_coverage < baseline.evidence_coverage - evidence_coverage_tolerance:
        regressions.append("evidence_coverage")

    if baseline.safe_abstention_rate is not None:
        candidate_abstention = candidate.safe_abstention_rate
        if (
            candidate_abstention is None
            or candidate_abstention < baseline.safe_abstention_rate - safe_abstention_tolerance
        ):
            regressions.append("safe_abstention_rate")

    return {
        "regression": bool(regressions),
        "regressions": regressions,
        "baseline": baseline.as_dict(),
        "candidate": candidate.as_dict(),
    }
