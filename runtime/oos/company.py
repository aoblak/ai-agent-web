from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DECISION_ALLOW = "ALLOW"
DECISION_NEEDS_APPROVAL = "NEEDS_APPROVAL"
DECISION_DENY = "DENY"

SKILL_STATUSES = {"implemented", "planned", "external", "disabled"}

# Mirrors the consequential-action boundary in ORCHESTRATION.md. Company OS does
# not execute these actions; it only decides whether a request is eligible to
# proceed to the existing OOS authority/verification flow.
CONSEQUENTIAL_ACTIONS = frozenset(
    {
        "production_write",
        "external_communication",
        "financial_transaction",
        "legal_commitment",
        "permission_change",
        "security_policy_change",
        "sensitive_data_action",
        "publication",
    }
)


@dataclass(frozen=True)
class CompanyDecision:
    state: str
    reason: str
    department_id: str | None
    skill_id: str | None
    capability: str
    action: str

    @property
    def allowed(self) -> bool:
        return self.state == DECISION_ALLOW


class CompanyRegistryError(ValueError):
    """Raised when Company OS registry data violates the executable contract."""


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_company_registry(registry: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation errors for a Company OS registry."""
    errors: list[str] = []

    for field in ("schema_version", "company_id", "name", "departments"):
        if field not in registry:
            errors.append(f"missing:{field}")

    if "departments" in registry and not isinstance(registry.get("departments"), list):
        errors.append("invalid:departments_not_list")
        return errors

    departments = registry.get("departments", [])
    department_ids: set[str] = set()
    skill_ids: set[str] = set()

    for department_index, department in enumerate(departments):
        prefix = f"departments[{department_index}]"
        if not isinstance(department, Mapping):
            errors.append(f"invalid:{prefix}_not_object")
            continue

        department_id = department.get("id")
        if not _nonempty_string(department_id):
            errors.append(f"invalid:{prefix}.id")
            continue
        if department_id in department_ids:
            errors.append(f"duplicate:department:{department_id}")
        department_ids.add(str(department_id))

        if not _nonempty_string(department.get("name")):
            errors.append(f"invalid:{prefix}.name")

        skills = department.get("skills")
        if not isinstance(skills, list):
            errors.append(f"invalid:{prefix}.skills_not_list")
            continue

        for skill_index, skill in enumerate(skills):
            skill_prefix = f"{prefix}.skills[{skill_index}]"
            if not isinstance(skill, Mapping):
                errors.append(f"invalid:{skill_prefix}_not_object")
                continue

            skill_id = skill.get("id")
            if not _nonempty_string(skill_id):
                errors.append(f"invalid:{skill_prefix}.id")
                continue
            if skill_id in skill_ids:
                errors.append(f"duplicate:skill:{skill_id}")
            skill_ids.add(str(skill_id))

            status = skill.get("status")
            if status not in SKILL_STATUSES:
                errors.append(f"invalid:{skill_prefix}.status:{status}")

            for list_field in ("capabilities", "allowed_actions", "tools", "component_refs"):
                value = skill.get(list_field, [])
                if not isinstance(value, list) or any(not _nonempty_string(item) for item in value):
                    errors.append(f"invalid:{skill_prefix}.{list_field}")

    return errors


def load_company_registry(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CompanyRegistryError("company registry root must be an object")

    errors = validate_company_registry(data)
    if errors:
        raise CompanyRegistryError("; ".join(errors))
    return data


def _find_skill(
    registry: Mapping[str, Any], skill_id: str
) -> tuple[Mapping[str, Any], Mapping[str, Any]] | None:
    for department in registry.get("departments", []):
        if not isinstance(department, Mapping):
            continue
        for skill in department.get("skills", []):
            if isinstance(skill, Mapping) and skill.get("id") == skill_id:
                return department, skill
    return None


def decide_company_request(
    registry: Mapping[str, Any],
    *,
    skill_id: str,
    capability: str,
    action: str,
    human_approved: bool = False,
) -> CompanyDecision:
    """Fail-closed policy decision for a requested Company OS operation.

    This function deliberately does not execute tools. It answers only whether a
    declared skill/capability/action may proceed to the normal OOS execution and
    verification path.
    """
    validation_errors = validate_company_registry(registry)
    if validation_errors:
        return CompanyDecision(
            DECISION_DENY,
            "invalid_registry",
            None,
            skill_id or None,
            capability,
            action,
        )

    match = _find_skill(registry, skill_id)
    if match is None:
        return CompanyDecision(
            DECISION_DENY,
            "unknown_skill",
            None,
            skill_id or None,
            capability,
            action,
        )

    department, skill = match
    department_id = str(department["id"])
    status = str(skill["status"])

    if status != "implemented":
        return CompanyDecision(
            DECISION_DENY,
            f"skill_not_implemented:{status}",
            department_id,
            skill_id,
            capability,
            action,
        )

    if capability not in skill.get("capabilities", []):
        return CompanyDecision(
            DECISION_DENY,
            "capability_not_allowlisted",
            department_id,
            skill_id,
            capability,
            action,
        )

    if action not in skill.get("allowed_actions", []):
        return CompanyDecision(
            DECISION_DENY,
            "action_not_allowlisted",
            department_id,
            skill_id,
            capability,
            action,
        )

    if action in CONSEQUENTIAL_ACTIONS and human_approved is not True:
        return CompanyDecision(
            DECISION_NEEDS_APPROVAL,
            "human_approval_required",
            department_id,
            skill_id,
            capability,
            action,
        )

    return CompanyDecision(
        DECISION_ALLOW,
        "allowlisted",
        department_id,
        skill_id,
        capability,
        action,
    )
