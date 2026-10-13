from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from uuid import uuid4

CONSEQUENTIAL_ACTIONS = {
    "production.write",
    "deploy",
    "delete",
    "external.send",
    "spend",
    "permission.change",
}

ALLOWED_ACTIONS = {
    "compute.sum",
    "record.note",
    *CONSEQUENTIAL_ACTIONS,
}


@dataclass(frozen=True)
class ActionRequest:
    action: str
    actor: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    target: str = ""
    request_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class PolicyDecision:
    status: str
    reason: str
    requires_approval: bool


@dataclass(frozen=True)
class ExecutionResult:
    request_id: str
    status: str
    output: Any
    verified: bool
    audit: tuple[dict[str, Any], ...]


class TrustedActionEngine:
    """Small deterministic VITA 1 vertical slice.

    Request -> policy -> optional approval -> allowlisted execution -> verification -> audit.
    It intentionally provides no arbitrary shell, network, or production executor.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[Mapping[str, Any]], Any]] = {
            "compute.sum": self._compute_sum,
            "record.note": self._record_note,
        }

    @staticmethod
    def _event(kind: str, request: ActionRequest, **detail: Any) -> dict[str, Any]:
        return {
            "event": kind,
            "request_id": request.request_id,
            "action": request.action,
            "actor": request.actor,
            "target": request.target,
            "detail": detail,
        }

    def evaluate(self, request: ActionRequest) -> PolicyDecision:
        if not isinstance(request.actor, str) or not request.actor.strip():
            return PolicyDecision("DENY", "invalid_actor", False)
        if not isinstance(request.request_id, str) or not request.request_id.strip():
            return PolicyDecision("DENY", "invalid_request_id", False)
        if request.action not in ALLOWED_ACTIONS:
            return PolicyDecision("DENY", "action_not_allowlisted", False)
        if request.action in CONSEQUENTIAL_ACTIONS:
            return PolicyDecision("REQUIRE_APPROVAL", "consequential_action", True)
        if request.action not in self._handlers:
            return PolicyDecision("DENY", "no_executor_registered", False)
        return PolicyDecision("ALLOW", "allowlisted_non_consequential_action", False)

    def execute(
        self,
        request: ActionRequest,
        *,
        approval: bool = False,
        expected: Mapping[str, Any] | None = None,
    ) -> ExecutionResult:
        audit: list[dict[str, Any]] = [self._event("request.received", request)]
        decision = self.evaluate(request)
        audit.append(
            self._event(
                "policy.evaluated",
                request,
                status=decision.status,
                reason=decision.reason,
            )
        )

        if decision.status == "DENY":
            audit.append(self._event("execution.denied", request))
            return ExecutionResult(request.request_id, "DENIED", None, False, tuple(audit))

        if decision.requires_approval and approval is not True:
            audit.append(self._event("approval.required", request))
            return ExecutionResult(
                request.request_id, "WAITING_APPROVAL", None, False, tuple(audit)
            )

        handler = self._handlers.get(request.action)
        if handler is None:
            # Consequential actions deliberately have no production executor in this slice.
            audit.append(self._event("execution.blocked", request, reason="no_executor_registered"))
            return ExecutionResult(request.request_id, "BLOCKED", None, False, tuple(audit))

        audit.append(self._event("execution.started", request))
        output = handler(request.payload)
        audit.append(self._event("execution.completed", request, output=output))

        verified = self._verify(output, expected)
        audit.append(self._event("result.verified", request, verified=verified))
        return ExecutionResult(
            request.request_id,
            "COMPLETED" if verified else "VERIFICATION_FAILED",
            output,
            verified,
            tuple(audit),
        )

    @staticmethod
    def _compute_sum(payload: Mapping[str, Any]) -> dict[str, Any]:
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError("payload.values must be a non-empty list")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
            raise ValueError("payload.values must contain only numbers")
        return {"sum": sum(values)}

    @staticmethod
    def _record_note(payload: Mapping[str, Any]) -> dict[str, Any]:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("payload.text must be a non-empty string")
        return {"recorded": text.strip()}

    @staticmethod
    def _verify(output: Any, expected: Mapping[str, Any] | None) -> bool:
        if not isinstance(expected, Mapping) or not expected:
            return False
        if not isinstance(output, Mapping):
            return False
        return all(output.get(key) == value for key, value in expected.items())
