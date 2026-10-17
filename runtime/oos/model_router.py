"""Capability-based model routing with evidence-first escalation.

The router is provider-neutral. It selects configured model identifiers, asks the
lowest-cost worker for a bounded evidence packet when escalation may be needed,
and invokes the selected execution model. Model output never grants authority or
proves that work succeeded; callers must verify returned work independently.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping, Protocol
from urllib import error, request
from urllib.parse import urlparse


class RoutingError(RuntimeError):
    """Raised when routing or model execution cannot complete safely."""


class Capability(str, Enum):
    FAST = "fast"
    GENERAL = "general"
    HIGH = "high"


@dataclass(frozen=True)
class ModelCatalog:
    fast: str
    general: str
    high: str

    def __post_init__(self) -> None:
        for value in (self.fast, self.general, self.high):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("every capability tier requires a model identifier")

    def model_for(self, capability: Capability) -> str:
        return getattr(self, capability.value)


@dataclass(frozen=True)
class TaskProfile:
    objective: str
    task_type: str
    relevant_files: tuple[str, ...] = ()
    relevant_commits: tuple[str, ...] = ()
    observed_tests: tuple[str, ...] = ()
    conflicting_evidence: tuple[str, ...] = ()
    attempted_solutions: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    failed_attempts: int = 0
    consequential: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("objective must be a non-empty string")
        if self.task_type not in {
            "discovery", "documentation", "routine_test", "mechanical_refactor",
            "implementation", "integration", "debugging", "architecture",
            "security", "migration", "incident", "orchestration",
        }:
            raise ValueError("unsupported task_type")
        if type(self.failed_attempts) is not int or self.failed_attempts < 0:
            raise ValueError("failed_attempts must be a non-negative integer")
        if not isinstance(self.consequential, bool):
            raise ValueError("consequential must be boolean")
        for values in (
            self.relevant_files, self.relevant_commits, self.observed_tests,
            self.conflicting_evidence, self.attempted_solutions, self.risks,
        ):
            if not isinstance(values, tuple) or len(values) > 50:
                raise ValueError("task evidence collections must be bounded tuples")
            if any(not isinstance(value, str) or len(value) > 2000 for value in values):
                raise ValueError("task evidence entries must be bounded strings")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TaskProfile":
        values = dict(data)
        for key in (
            "relevant_files", "relevant_commits", "observed_tests",
            "conflicting_evidence", "attempted_solutions", "risks",
        ):
            if key in values:
                if not isinstance(values[key], list):
                    raise ValueError(f"{key} must be a JSON array")
                values[key] = tuple(values[key])
        try:
            return cls(**values)
        except TypeError as exc:
            raise ValueError("task profile schema mismatch") from exc


@dataclass(frozen=True)
class EvidencePacket:
    problem: str
    branch: str
    head: str
    relevant_files: tuple[str, ...]
    relevant_commits: tuple[str, ...]
    tests_and_results: tuple[str, ...]
    observed_behavior: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    attempted_solutions: tuple[str, ...]
    unresolved_question: str
    confidence: float

    @classmethod
    def from_json(cls, raw: str) -> "EvidencePacket":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RoutingError("evidence worker returned invalid JSON") from exc
        expected = {
            "problem", "branch", "head", "relevant_files", "relevant_commits",
            "tests_and_results", "observed_behavior", "conflicting_evidence",
            "attempted_solutions", "unresolved_question", "confidence",
        }
        if not isinstance(data, dict) or set(data) != expected:
            raise RoutingError("evidence packet schema mismatch")
        for key in (
            "relevant_files", "relevant_commits", "tests_and_results",
            "observed_behavior", "conflicting_evidence", "attempted_solutions",
        ):
            values = data[key]
            if not isinstance(values, list) or len(values) > 50 or any(
                not isinstance(value, str) or len(value) > 2000 for value in values
            ):
                raise RoutingError(f"invalid evidence packet field: {key}")
            data[key] = tuple(values)
        for key in ("problem", "branch", "head", "unresolved_question"):
            if not isinstance(data[key], str) or len(data[key]) > 4000:
                raise RoutingError(f"invalid evidence packet field: {key}")
        confidence = data["confidence"]
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise RoutingError("evidence confidence must be numeric")
        if not 0 <= float(confidence) <= 1:
            raise RoutingError("evidence confidence must be between zero and one")
        data["confidence"] = float(confidence)
        return cls(**data)


@dataclass(frozen=True)
class ModelResponse:
    model: str
    output_text: str
    response_id: str | None = None


class ModelExecutor(Protocol):
    def run(self, *, model: str, instructions: str, input_text: str) -> ModelResponse: ...


@dataclass(frozen=True)
class RouteResult:
    capability: Capability
    model: str
    reason: str
    evidence_model: str | None
    evidence: EvidencePacket | None
    response: ModelResponse
    requires_human_authority: bool


class ModelRouter:
    """Run evidence-first model selection using explicit task metadata."""

    _FAST_TYPES = {"discovery", "documentation", "routine_test", "mechanical_refactor"}
    _HIGH_TYPES = {"architecture", "security", "migration", "incident", "orchestration"}
    _SENSITIVE = (
        re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----", re.IGNORECASE),
        re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{10,}"),
        re.compile(
            r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|secret)"
            r"\s*[\"']?\s*[:=]\s*[^\s,;]+",
            re.IGNORECASE,
        ),
        re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    )

    def __init__(
        self,
        catalog: ModelCatalog,
        executor: ModelExecutor,
        *,
        evidence_confidence_threshold: float = 0.85,
    ) -> None:
        if (
            isinstance(evidence_confidence_threshold, bool)
            or not isinstance(evidence_confidence_threshold, (int, float))
            or not 0 <= evidence_confidence_threshold <= 1
        ):
            raise ValueError("evidence_confidence_threshold must be numeric between zero and one")
        self.catalog = catalog
        self.executor = executor
        self.evidence_confidence_threshold = evidence_confidence_threshold

    def _provisional_capability(self, task: TaskProfile) -> Capability:
        if task.task_type in self._FAST_TYPES and not task.risks and task.failed_attempts < 2:
            return Capability.FAST
        if task.task_type in self._HIGH_TYPES or task.failed_attempts >= 2:
            return Capability.HIGH
        return Capability.GENERAL

    def _needs_evidence(self, task: TaskProfile, provisional: Capability) -> bool:
        return bool(
            task.conflicting_evidence
            or task.risks
            or task.failed_attempts
            or provisional is Capability.HIGH
        )

    @staticmethod
    def _evidence_input(task: TaskProfile, branch: str, head: str) -> str:
        payload = asdict(task) | {"branch": branch, "head": head}
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    @staticmethod
    def _execution_input(task: TaskProfile, evidence: EvidencePacket | None) -> str:
        payload: dict[str, Any] = {"task": asdict(task)}
        if evidence is not None:
            payload["evidence_packet"] = asdict(evidence)
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    @classmethod
    def _assert_safe_outbound(cls, value: str) -> None:
        if len(value.encode("utf-8")) > 100_000:
            raise RoutingError("outbound model context exceeds size limit")
        if any(pattern.search(value) for pattern in cls._SENSITIVE):
            raise RoutingError("suspected credential in outbound model context")

    def run(self, task: TaskProfile, *, branch: str, head: str) -> RouteResult:
        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("branch must be provided")
        if not isinstance(head, str) or not head.strip():
            raise ValueError("head must be provided")

        provisional = self._provisional_capability(task)
        evidence: EvidencePacket | None = None
        evidence_model: str | None = None
        capability = provisional
        reason = f"task type {task.task_type} maps to {provisional.value} capability"

        if self._needs_evidence(task, provisional):
            evidence_model = self.catalog.fast
            evidence_input = self._evidence_input(task, branch, head)
            self._assert_safe_outbound(evidence_input)
            raw = self.executor.run(
                model=evidence_model,
                instructions=(
                    "Produce only a JSON evidence packet with exactly these fields: problem, "
                    "branch, head, relevant_files, relevant_commits, tests_and_results, "
                    "observed_behavior, conflicting_evidence, attempted_solutions, "
                    "unresolved_question, confidence. Use UNKNOWN when evidence is absent. "
                    "Do not propose or execute changes."
                ),
                input_text=evidence_input,
            )
            evidence = EvidencePacket.from_json(raw.output_text)
            if evidence.branch != branch or evidence.head != head:
                raise RoutingError("evidence packet branch or HEAD does not match routed task")
            unresolved = bool(evidence.unresolved_question.strip())
            weak = evidence.confidence < self.evidence_confidence_threshold
            conflicts_remain = bool(evidence.conflicting_evidence)
            mandatory_high = task.task_type in {"security", "migration", "incident"} or task.consequential

            if mandatory_high or unresolved or weak or conflicts_remain or task.failed_attempts >= 2:
                capability = Capability.HIGH
                reason = "evidence packet retains material uncertainty or high-risk scope"
            elif provisional is Capability.HIGH:
                capability = Capability.GENERAL
                reason = "bounded evidence resolved the initial escalation trigger"
            else:
                capability = provisional
                reason = "evidence packet supports the provisional capability"

        model = self.catalog.model_for(capability)
        execution_input = self._execution_input(task, evidence)
        self._assert_safe_outbound(execution_input)
        response = self.executor.run(
            model=model,
            instructions=(
                "Perform the scoped task using only supplied evidence. Mark missing facts "
                "UNKNOWN or UNVERIFIED. Do not claim tests, writes, approvals, deployments, "
                "or authority that are not present in the input. Return work for independent verification."
            ),
            input_text=execution_input,
        )
        return RouteResult(
            capability=capability,
            model=model,
            reason=reason,
            evidence_model=evidence_model,
            evidence=evidence,
            response=response,
            requires_human_authority=task.consequential,
        )


class OpenAIResponsesExecutor:
    """Minimal OpenAI Responses API adapter with explicit per-call model selection."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 300.0,
        allow_custom_base_url: bool = False,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("OPENAI_API_KEY is required")
        if not isinstance(allow_custom_base_url, bool):
            raise ValueError("allow_custom_base_url must be boolean")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("OpenAI base_url must be a non-empty string")
        normalized_base = base_url.strip().rstrip("/")
        parsed = urlparse(normalized_base)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OpenAI base_url must be a clean absolute HTTPS URL")
        if normalized_base != "https://api.openai.com/v1" and not allow_custom_base_url:
            raise ValueError("custom OpenAI base_url requires explicit opt-in")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            raise ValueError("timeout must be a positive number")
        self.api_key = key.strip()
        self.base_url = normalized_base
        self.timeout = float(timeout)

    def run(self, *, model: str, instructions: str, input_text: str) -> ModelResponse:
        body = json.dumps(
            {
                "model": model,
                "instructions": instructions,
                "input": input_text,
                "store": False,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/responses",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (error.HTTPError, error.URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RoutingError("OpenAI Responses request failed") from exc
        if not isinstance(payload, Mapping):
            raise RoutingError("OpenAI response must be a JSON object")
        output_text = payload.get("output_text")
        if not isinstance(output_text, str):
            output_text = self._extract_output_text(payload)
        returned_model = payload.get("model")
        if not isinstance(returned_model, str) or not returned_model:
            raise RoutingError("OpenAI response omitted model identity")
        response_id = payload.get("id")
        return ModelResponse(
            model=returned_model,
            output_text=output_text,
            response_id=response_id if isinstance(response_id, str) else None,
        )

    @staticmethod
    def _extract_output_text(payload: Mapping[str, Any]) -> str:
        parts: list[str] = []
        output = payload.get("output")
        if not isinstance(output, list):
            raise RoutingError("OpenAI response omitted output text")
        for item in output:
            if not isinstance(item, Mapping):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "output_text":
                    text = block.get("text")
                    if isinstance(text, str):
                        parts.append(text)
        if not parts:
            raise RoutingError("OpenAI response omitted output text")
        return "".join(parts)
