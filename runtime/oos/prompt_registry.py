from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from statistics import mean
from typing import Any, Iterable

from oos.torture import canonical_json


FAILURE_TAXONOMY = frozenset(
    {
        "HALLUCINATION",
        "WRONG_CONTEXT",
        "MISSING_CONTEXT",
        "POLICY_VIOLATION",
        "TOOL_ERROR",
        "MODEL_ERROR",
        "BAD_PROMPT",
        "AMBIGUOUS_INTENT",
        "SCHEMA_ERROR",
        "TIMEOUT",
        "HUMAN_REJECTED",
    }
)

PROMPT_STATUSES = frozenset({"draft", "test", "approved", "deprecated"})
EXECUTION_STATUSES = frozenset({"SUCCESS", "FAILED", "PARTIAL", "BLOCKED", "CANCELLED"})

# SemVer 2.0.0: core numeric identifiers reject leading zeroes; prerelease
# identifiers are non-empty and numeric prerelease identifiers also reject
# leading zeroes. Build metadata is valid but ignored for precedence.
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_PROMPT_IDENTITY_FIELDS = (
    "prompt_id",
    "version",
    "template",
    "variables_schema",
    "required_context",
    "allowed_tools",
    "policy_refs",
    "output_schema",
    "evaluation_refs",
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


def _digest(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(payload)).hexdigest()


def _parse_semver(version: str) -> tuple[tuple[int, int, int], tuple[str, ...] | None]:
    match = _SEMVER_RE.fullmatch(version)
    if not match:
        raise ValueError(f"invalid semantic version: {version}")
    core = tuple(int(match.group(i)) for i in (1, 2, 3))
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else None
    return core, prerelease


def _compare_semver(left: str, right: str) -> int:
    """Return -1/0/1 using SemVer 2.0.0 precedence rules."""
    left_core, left_pre = _parse_semver(left)
    right_core, right_pre = _parse_semver(right)

    if left_core != right_core:
        return -1 if left_core < right_core else 1

    # A normal version has higher precedence than a prerelease version.
    if left_pre is None and right_pre is None:
        return 0
    if left_pre is None:
        return 1
    if right_pre is None:
        return -1

    for left_id, right_id in zip(left_pre, right_pre):
        if left_id == right_id:
            continue
        left_numeric = left_id.isdigit()
        right_numeric = right_id.isdigit()
        if left_numeric and right_numeric:
            return -1 if int(left_id) < int(right_id) else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_id < right_id else 1

    if len(left_pre) == len(right_pre):
        return 0
    return -1 if len(left_pre) < len(right_pre) else 1


def prompt_identity_payload(definition: dict[str, Any]) -> dict[str, Any]:
    return {field: definition.get(field) for field in _PROMPT_IDENTITY_FIELDS}


def prompt_content_digest(definition: dict[str, Any]) -> str:
    return _digest(prompt_identity_payload(definition))


def validate_prompt_definition(definition: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    required = {
        "prompt_id",
        "name",
        "version",
        "status",
        "purpose",
        "template",
        "variables_schema",
        "required_context",
        "allowed_tools",
        "policy_refs",
        "output_schema",
        "evaluation_refs",
        "content_digest",
    }
    missing = sorted(required - definition.keys())
    if missing:
        errors.append("missing_fields:" + ",".join(missing))
        return ValidationResult(False, tuple(errors))

    try:
        _parse_semver(str(definition["version"]))
    except ValueError:
        errors.append("invalid_semver")

    if definition["status"] not in PROMPT_STATUSES:
        errors.append("invalid_status")

    digest = str(definition["content_digest"])
    if not _SHA256_RE.fullmatch(digest):
        errors.append("invalid_content_digest")
    elif digest != prompt_content_digest(definition):
        errors.append("content_digest_mismatch")

    if not isinstance(definition["required_context"], list):
        errors.append("required_context_must_be_list")
    if not isinstance(definition["allowed_tools"], list):
        errors.append("allowed_tools_must_be_list")
    if not isinstance(definition["policy_refs"], list):
        errors.append("policy_refs_must_be_list")
    if not isinstance(definition["evaluation_refs"], list):
        errors.append("evaluation_refs_must_be_list")
    if not isinstance(definition["variables_schema"], dict):
        errors.append("variables_schema_must_be_object")
    if not isinstance(definition["output_schema"], dict):
        errors.append("output_schema_must_be_object")

    return ValidationResult(not errors, tuple(errors))


def validate_version_transition(
    previous: dict[str, Any], candidate: dict[str, Any]
) -> ValidationResult:
    errors: list[str] = []

    if previous.get("prompt_id") != candidate.get("prompt_id"):
        return ValidationResult(False, ("prompt_id_changed",))

    prev_validation = validate_prompt_definition(previous)
    candidate_validation = validate_prompt_definition(candidate)
    if not prev_validation.valid:
        errors.append("previous_invalid")
    if not candidate_validation.valid:
        errors.append("candidate_invalid")
    if errors:
        return ValidationResult(False, tuple(errors))

    previous_version = str(previous["version"])
    candidate_version = str(candidate["version"])
    previous_digest = str(previous["content_digest"])
    candidate_digest = str(candidate["content_digest"])

    if previous_version == candidate_version:
        if previous_digest != candidate_digest:
            errors.append("VERSION_IMMUTABILITY_VIOLATION")
        return ValidationResult(not errors, tuple(errors))

    if _compare_semver(candidate_version, previous_version) <= 0:
        errors.append("version_not_incremented")

    if previous_digest != candidate_digest:
        expected = f"{previous['prompt_id']}@{previous_version}"
        if candidate.get("supersedes") != expected:
            errors.append("supersedes_mismatch")

    return ValidationResult(not errors, tuple(errors))


def execution_manifest_digest(manifest: dict[str, Any]) -> str:
    return _digest(manifest)


def validate_execution_manifest(manifest: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    required_sections = {
        "manifest_version",
        "prompt",
        "model",
        "context",
        "policy",
        "toolset",
        "output_schema",
    }
    missing = sorted(required_sections - manifest.keys())
    if missing:
        return ValidationResult(False, ("missing_sections:" + ",".join(missing),))

    prompt = manifest["prompt"]
    if not isinstance(prompt, dict) or not {"prompt_id", "version", "content_digest"} <= prompt.keys():
        errors.append("invalid_prompt_ref")
    elif not _SHA256_RE.fullmatch(str(prompt["content_digest"])):
        errors.append("invalid_prompt_digest")

    model = manifest["model"]
    if not isinstance(model, dict) or not {"provider", "name", "config"} <= model.keys():
        errors.append("invalid_model_ref")
    elif not isinstance(model["config"], dict):
        errors.append("model_config_must_be_object")

    context = manifest["context"]
    if not isinstance(context, dict) or not {"profile", "ref", "digest"} <= context.keys():
        errors.append("invalid_context_ref")
    elif not _SHA256_RE.fullmatch(str(context["digest"])):
        errors.append("invalid_context_digest")

    for key in ("policy", "toolset", "output_schema"):
        section = manifest[key]
        if not isinstance(section, dict) or not {"id", "version"} <= section.keys():
            errors.append(f"invalid_{key}_ref")

    return ValidationResult(not errors, tuple(errors))


def reproducibility_level(manifest: dict[str, Any]) -> str:
    validation = validate_execution_manifest(manifest)
    if not validation.valid:
        return "INSUFFICIENT"
    model = manifest["model"]
    return "STRONG" if model.get("revision") else "BOUNDED"


def validate_execution_record(record: dict[str, Any]) -> ValidationResult:
    errors: list[str] = []
    required = {
        "execution_id",
        "manifest_digest",
        "started_at",
        "completed_at",
        "status",
        "task_success",
        "policy_compliant",
        "verifiable",
        "failure_codes",
        "metrics",
    }
    missing = sorted(required - record.keys())
    if missing:
        return ValidationResult(False, ("missing_fields:" + ",".join(missing),))

    if not _SHA256_RE.fullmatch(str(record["manifest_digest"])):
        errors.append("invalid_manifest_digest")
    if record["status"] not in EXECUTION_STATUSES:
        errors.append("invalid_execution_status")
    for field in ("task_success", "policy_compliant", "verifiable"):
        if not isinstance(record[field], bool):
            errors.append(f"{field}_must_be_bool")

    codes = record["failure_codes"]
    if not isinstance(codes, list):
        errors.append("failure_codes_must_be_list")
    else:
        unknown = sorted(set(codes) - FAILURE_TAXONOMY)
        if unknown:
            errors.append("unknown_failure_codes:" + ",".join(unknown))

    metrics = record["metrics"]
    if not isinstance(metrics, dict):
        errors.append("metrics_must_be_object")
    else:
        for key in ("input_tokens", "output_tokens", "latency_ms", "cost"):
            if key in metrics:
                value = metrics[key]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    errors.append(f"invalid_metric:{key}")

    return ValidationResult(not errors, tuple(errors))


def summarize_executions(records: Iterable[dict[str, Any]]) -> dict[str, float | int | None]:
    rows = list(records)
    if not rows:
        return {
            "runs": 0,
            "task_success_rate": None,
            "policy_compliance_rate": None,
            "verifiability_rate": None,
            "avg_input_tokens": None,
            "avg_output_tokens": None,
            "avg_total_tokens": None,
            "avg_latency_ms": None,
            "avg_cost": None,
        }

    for row in rows:
        validation = validate_execution_record(row)
        if not validation.valid:
            raise ValueError("invalid execution record: " + ";".join(validation.errors))

    def avg_metric(name: str) -> float | None:
        values = [float(row["metrics"][name]) for row in rows if name in row["metrics"]]
        return mean(values) if values else None

    input_tokens = avg_metric("input_tokens")
    output_tokens = avg_metric("output_tokens")
    total_tokens = None
    if input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    count = len(rows)
    return {
        "runs": count,
        "task_success_rate": sum(row["task_success"] for row in rows) / count,
        "policy_compliance_rate": sum(row["policy_compliant"] for row in rows) / count,
        "verifiability_rate": sum(row["verifiable"] for row in rows) / count,
        "avg_input_tokens": input_tokens,
        "avg_output_tokens": output_tokens,
        "avg_total_tokens": total_tokens,
        "avg_latency_ms": avg_metric("latency_ms"),
        "avg_cost": avg_metric("cost"),
    }


def compare_execution_summaries(
    baseline: dict[str, float | int | None],
    candidate: dict[str, float | int | None],
) -> dict[str, float | None]:
    metrics = (
        "task_success_rate",
        "policy_compliance_rate",
        "verifiability_rate",
        "avg_input_tokens",
        "avg_output_tokens",
        "avg_total_tokens",
        "avg_latency_ms",
        "avg_cost",
    )
    deltas: dict[str, float | None] = {}
    for metric in metrics:
        before = baseline.get(metric)
        after = candidate.get(metric)
        deltas[f"{metric}_delta"] = (
            None if before is None or after is None else float(after) - float(before)
        )
    return deltas
