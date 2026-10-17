"""Evidence-derived execution state machine for consequential OOS actions.

The LLM/agent is not an authority over execution truth.  Executors and verifiers
produce bound receipts; this module validates evidence and derives state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping, Protocol


class ExecutionState(str, Enum):
    REQUESTED = "REQUESTED"
    CAPABILITY_VERIFIED = "CAPABILITY_VERIFIED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"


class PersistenceState(str, Enum):
    PENDING = "PERSISTENCE_PENDING"
    RECORDED = "RECORDED"
    RECORD_FAILED = "RECORD_FAILED"


class TransitionError(ValueError):
    pass


class AdmissionStore(Protocol):
    def acquire(self, operation_id: str, authority_id: str) -> bool: ...


class InMemoryAdmissionStore:
    """Test/reference admission store.

    Production adapters must provide the same acquire contract using an atomic,
    durable compare-and-set or equivalent primitive shared by all workers.
    """
    def __init__(self) -> None:
        self._owners: dict[str, str] = {}

    def acquire(self, operation_id: str, authority_id: str) -> bool:
        if operation_id in self._owners:
            return False
        self._owners[operation_id] = authority_id
        return True


class ClaimLevel(str, Enum):
    INTENT = "INTENT"
    ADMITTED = "ADMITTED"
    ATTEMPT = "ATTEMPT"
    EXECUTION_EVIDENCED = "EXECUTION_EVIDENCED"
    VERIFIED = "VERIFIED"
    UNCERTAIN = "UNCERTAIN"
    FAILURE = "FAILURE"


def canonical_digest(value: Mapping[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + sha256(raw).hexdigest()


@dataclass(frozen=True)
class Operation:
    request_id: str
    operation_id: str
    principal: str
    target: str
    action: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    session_id: str = ""
    expected_state: str = ""

    @property
    def input_digest(self) -> str:
        return canonical_digest({
            "request_id": self.request_id,
            "operation_id": self.operation_id,
            "principal": self.principal,
            "target": self.target,
            "action": self.action,
            "parameters": dict(self.parameters),
            "session_id": self.session_id,
            "expected_state": self.expected_state,
        })


@dataclass(frozen=True)
class CapabilityEvidence:
    operation_id: str
    principal: str
    target: str
    allowed_action: str
    verified_at: str
    valid: bool = True
    valid_until: str | None = None


@dataclass(frozen=True)
class AuthorizationEvidence:
    operation_id: str
    principal: str
    decision: str
    policy_ref: str
    session_id: str = ""
    input_digest: str = ""


@dataclass(frozen=True)
class ExecutionReceipt:
    receipt_id: str
    request_id: str
    operation_id: str
    executor_id: str
    target: str
    action: str
    input_digest: str
    timestamp: str
    result: str
    evidence_reference: str


@dataclass(frozen=True)
class VerificationReceipt:
    receipt_id: str
    execution_receipt_id: str
    operation_id: str
    expected_state: str
    observed_state: str
    verification_method: str
    result: str
    timestamp: str
    evidence_reference: str


@dataclass
class ExecutionRecord:
    operation: Operation
    state: ExecutionState = ExecutionState.REQUESTED
    persistence: PersistenceState = PersistenceState.PENDING
    capability: CapabilityEvidence | None = None
    authorization: AuthorizationEvidence | None = None
    execution_receipt: ExecutionReceipt | None = None
    verification_receipt: VerificationReceipt | None = None
    execution_authority: str | None = None
    transition_log: list[tuple[str, str]] = field(default_factory=list)

    def verify_capability(self, evidence: CapabilityEvidence) -> None:
        self._require(ExecutionState.REQUESTED)
        if (
            not evidence.valid
            or evidence.operation_id != self.operation.operation_id
            or not self.operation.principal
            or evidence.principal != self.operation.principal
        ):
            self._advance(ExecutionState.BLOCKED, "policy_or_capability_block")
            return
        if evidence.target != self.operation.target or evidence.allowed_action != self.operation.action:
            self._advance(ExecutionState.BLOCKED, "policy_or_capability_block")
            return
        self.capability = evidence
        self._advance(ExecutionState.CAPABILITY_VERIFIED, "capability_evidence")

    def authorize(self, evidence: AuthorizationEvidence) -> None:
        self._require(ExecutionState.CAPABILITY_VERIFIED)
        if not isinstance(self.operation.expected_state, str) or not self.operation.expected_state.strip():
            self._advance(ExecutionState.BLOCKED, "missing_authorized_postcondition")
            return
        if not self.operation.session_id or evidence.session_id != self.operation.session_id:
            self._advance(ExecutionState.BLOCKED, "session_authority_mismatch")
            return
        if evidence.input_digest != self.operation.input_digest:
            self._advance(ExecutionState.BLOCKED, "authorization_binding_mismatch")
            return
        if (
            evidence.operation_id != self.operation.operation_id
            or not self.operation.principal
            or evidence.principal != self.operation.principal
            or evidence.decision != "ALLOW"
            or not evidence.policy_ref
        ):
            self._advance(ExecutionState.BLOCKED, "policy_or_capability_block")
            return
        self.authorization = evidence
        self._advance(ExecutionState.AUTHORIZED, "authorization_evidence")

    def admit_execution(
        self,
        authority_id: str,
        *,
        current_session_id: str | None = None,
        current_capability: CapabilityEvidence | None = None,
        admission_store: AdmissionStore | None = None,
        as_of: datetime | None = None,
    ) -> None:
        self._require(ExecutionState.AUTHORIZED)
        if not authority_id:
            raise TransitionError("execution authority required")
        if (
            not current_session_id
            or not self.operation.session_id
            or current_session_id != self.operation.session_id
            or self.authorization is None
            or self.authorization.session_id != current_session_id
        ):
            self._advance(ExecutionState.BLOCKED, "session_authority_mismatch")
            return
        if self.authorization.input_digest != self.operation.input_digest:
            self._advance(ExecutionState.BLOCKED, "authorization_binding_mismatch")
            return
        if self.execution_authority is not None:
            raise TransitionError("operation already admitted")
        # Admission requires fresh capability evidence.  Falling back to the
        # earlier discovery check would re-open a TOCTOU window.
        evidence = current_capability
        if evidence is None or not evidence.valid:
            self._advance(ExecutionState.BLOCKED, "policy_or_capability_block")
            return
        if not self._capability_fresh(evidence, as_of=as_of):
            self._advance(ExecutionState.BLOCKED, "stale_capability")
            return
        if (
            evidence.operation_id != self.operation.operation_id
            or evidence.principal != self.operation.principal
            or evidence.target != self.operation.target
            or evidence.allowed_action != self.operation.action
        ):
            self._advance(ExecutionState.BLOCKED, "policy_or_capability_block")
            return
        # Consequential execution must always cross an atomic admission boundary.
        # An absent store is not equivalent to successful admission: failing open
        # here would allow concurrent workers to execute the same operation.
        if admission_store is None:
            self._advance(ExecutionState.BLOCKED, "missing_admission_store")
            return
        if not admission_store.acquire(self.operation.operation_id, authority_id):
            self._advance(ExecutionState.BLOCKED, "duplicate_execution_admission")
            return
        self.capability = evidence
        self.execution_authority = authority_id
        self._advance(ExecutionState.EXECUTING, "atomic_execution_admission")

    def accept_execution_receipt(self, receipt: ExecutionReceipt) -> None:
        self._require(ExecutionState.EXECUTING, ExecutionState.RECONCILING)
        if not self._execution_receipt_valid(receipt):
            raise TransitionError("execution receipt is not bound to this operation")
        self.execution_receipt = receipt
        if receipt.result == "EXECUTED":
            self._advance(ExecutionState.EXECUTED, "execution_receipt")
        elif receipt.result == "PARTIAL":
            self._advance(ExecutionState.PARTIAL, "partial_execution_receipt")
        elif receipt.result == "FAILED":
            self._advance(ExecutionState.FAILED, "failed_execution_receipt")
        elif receipt.result == "UNKNOWN":
            self._advance(ExecutionState.UNKNOWN, "unknown_execution_receipt")
        else:
            raise TransitionError("unsupported execution result")

    def mark_indeterminate(self) -> None:
        self._require(ExecutionState.EXECUTING)
        self._advance(ExecutionState.UNKNOWN, "indeterminate_outcome")

    def reconcile(self) -> None:
        self._require(ExecutionState.UNKNOWN, ExecutionState.PARTIAL)
        self._advance(ExecutionState.RECONCILING, "authoritative_reconciliation")

    def verify(self, receipt: VerificationReceipt) -> None:
        self._require(ExecutionState.EXECUTED, ExecutionState.RECONCILING)
        er = self.execution_receipt
        if er is None or er.result != "EXECUTED":
            raise TransitionError("verification requires an EXECUTED receipt")
        if (self.authorization is None
                or self.authorization.input_digest != self.operation.input_digest
                or er.input_digest != self.authorization.input_digest):
            raise TransitionError("verification requires the authorized operation binding")
        if (
            not receipt.receipt_id
            or receipt.execution_receipt_id != er.receipt_id
            or receipt.operation_id != self.operation.operation_id
            or not self.operation.expected_state
            or receipt.expected_state != self.operation.expected_state
            or not receipt.observed_state
            or not receipt.verification_method
            or not receipt.timestamp
            or not receipt.evidence_reference
        ):
            raise TransitionError("verification receipt mismatch")
        if receipt.result == "PASS" and receipt.observed_state != self.operation.expected_state:
            raise TransitionError("PASS requires observed state to match expected state")
        self.verification_receipt = receipt
        if receipt.result == "PASS":
            self._advance(ExecutionState.VERIFIED, "verification_pass")
        elif receipt.result == "FAIL":
            self._advance(ExecutionState.FAILED, "verification_fail")
        elif receipt.result == "UNKNOWN":
            self._advance(ExecutionState.UNKNOWN, "verification_unknown")
        else:
            raise TransitionError("unsupported verification result")

    def mark_recorded(self) -> None:
        if self.state is not ExecutionState.VERIFIED:
            raise TransitionError("only verified execution may be recorded as verified state")
        self.persistence = PersistenceState.RECORDED

    def mark_record_failed(self) -> None:
        if self.state is not ExecutionState.VERIFIED:
            raise TransitionError("record failure applies only after verified execution")
        self.persistence = PersistenceState.RECORD_FAILED

    def retry_recording(self) -> None:
        if self.persistence is not PersistenceState.RECORD_FAILED:
            raise TransitionError("recording retry requires RECORD_FAILED")
        self.persistence = PersistenceState.PENDING

    @property
    def claim_level(self) -> ClaimLevel:
        return {
            ExecutionState.REQUESTED: ClaimLevel.INTENT,
            ExecutionState.CAPABILITY_VERIFIED: ClaimLevel.INTENT,
            ExecutionState.AUTHORIZED: ClaimLevel.ADMITTED,
            ExecutionState.EXECUTING: ClaimLevel.ATTEMPT,
            ExecutionState.EXECUTED: ClaimLevel.EXECUTION_EVIDENCED,
            ExecutionState.VERIFIED: ClaimLevel.VERIFIED,
            ExecutionState.BLOCKED: ClaimLevel.FAILURE,
            ExecutionState.FAILED: ClaimLevel.FAILURE,
            ExecutionState.PARTIAL: ClaimLevel.UNCERTAIN,
            ExecutionState.UNKNOWN: ClaimLevel.UNCERTAIN,
            ExecutionState.RECONCILING: ClaimLevel.UNCERTAIN,
        }[self.state]

    def permits_success_claim(self) -> bool:
        return self.claim_level is ClaimLevel.VERIFIED

    def claim(self) -> str:
        return {
            ExecutionState.REQUESTED: "requested",
            ExecutionState.CAPABILITY_VERIFIED: "capability verified",
            ExecutionState.AUTHORIZED: "authorized",
            ExecutionState.EXECUTING: "execution started; outcome not yet proven",
            ExecutionState.EXECUTED: "execution receipt accepted; result not independently verified",
            ExecutionState.VERIFIED: "result independently verified",
            ExecutionState.BLOCKED: "blocked",
            ExecutionState.FAILED: "operation proven failed",
            ExecutionState.PARTIAL: "operation partially executed",
            ExecutionState.UNKNOWN: "outcome unknown",
            ExecutionState.RECONCILING: "reconciling authoritative state",
        }[self.state]

    @property
    def safe_to_retry_business_action(self) -> bool:
        """Retry only when non-execution is positively evidenced.

        A verifier FAIL means the postcondition failed; it does not prove that the
        mutation did not happen, so it is deliberately not retryable here.
        """
        return (
            self.state is ExecutionState.FAILED
            and self.execution_receipt is not None
            and self.execution_receipt.result == "FAILED"
        )

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _capability_fresh(cls, evidence: CapabilityEvidence, *, as_of: datetime | None = None) -> bool:
        verified_at = cls._parse_time(evidence.verified_at)
        valid_until = cls._parse_time(evidence.valid_until)
        if verified_at is None or valid_until is None or valid_until < verified_at:
            return False
        now = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return verified_at <= now <= valid_until

    def _execution_receipt_valid(self, r: ExecutionReceipt) -> bool:
        op = self.operation
        return bool(
            r.receipt_id
            and self.execution_authority
            and r.executor_id == self.execution_authority
            and r.timestamp
            and r.evidence_reference
            and r.result in {"EXECUTED", "PARTIAL", "FAILED", "UNKNOWN"}
        ) and (
            self.authorization is not None
            and self.authorization.input_digest == op.input_digest
            and r.request_id == op.request_id
            and r.operation_id == op.operation_id
            and r.target == op.target
            and r.action == op.action
            and r.input_digest == op.input_digest
        )

    def _require(self, *allowed: ExecutionState) -> None:
        if self.state not in allowed:
            raise TransitionError(f"illegal transition from {self.state.value}")

    def _advance(self, new_state: ExecutionState, evidence_kind: str) -> None:
        old = self.state
        self.transition_log.append((f"{old.value}->{new_state.value}", evidence_kind))
        self.state = new_state


__all__ = [
    "AdmissionStore", "AuthorizationEvidence", "CapabilityEvidence", "ClaimLevel",
    "ExecutionReceipt", "InMemoryAdmissionStore",
    "ExecutionRecord", "ExecutionState", "Operation", "PersistenceState",
    "TransitionError", "VerificationReceipt", "canonical_digest",
]
