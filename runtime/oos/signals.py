"""Minimal OOS signal/experiment data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    EVIDENCE = "EVIDENCE"
    MODEL_JUDGMENT = "MODEL_JUDGMENT"
    HUMAN_STATED_SIGNAL = "HUMAN_STATED_SIGNAL"
    HUMAN_BEHAVIOR_SIGNAL = "HUMAN_BEHAVIOR_SIGNAL"
    SYSTEM_INFERENCE = "SYSTEM_INFERENCE"


class ResultAction(str, Enum):
    NONE = "NONE"
    PROMPT_CANDIDATE = "PROMPT_CANDIDATE"
    PROMPT_REVISION = "PROMPT_REVISION"
    SKILL_CANDIDATE = "SKILL_CANDIDATE"
    SKILL_REVISION = "SKILL_REVISION"
    FURTHER_EXPERIMENT = "FURTHER_EXPERIMENT"


@dataclass(frozen=True)
class Signal:
    signal_id: str
    experiment_id: str
    question_version: str
    signal_type: SignalType
    source_id: str
    response: Any
    timestamp: str
    context_ref: str | None = None
    provenance_ref: str | None = None
    population_or_model: str | None = None
    sampling_method: str | None = None


@dataclass
class Experiment:
    experiment_id: str
    purpose: str
    question: str
    question_version: str
    evidence_ref: str | None = None
    signals: list[Signal] = field(default_factory=list)
    resulting_action: ResultAction = ResultAction.NONE

    def add_signal(self, signal: Signal) -> None:
        if signal.experiment_id != self.experiment_id:
            raise ValueError("signal_experiment_mismatch")
        if signal.question_version != self.question_version:
            raise ValueError("signal_question_version_mismatch")
        if (
            signal.signal_type is SignalType.HUMAN_STATED_SIGNAL
            and signal.population_or_model is None
        ):
            raise ValueError("human_signal_population_required")
        self.signals.append(signal)

    def by_type(self, signal_type: SignalType) -> list[Signal]:
        return [s for s in self.signals if s.signal_type is signal_type]

    def signal_vector(self) -> dict[str, int]:
        return {
            signal_type.value: len(self.by_type(signal_type))
            for signal_type in SignalType
        }

    def truth_score(self) -> float:
        raise RuntimeError("heterogeneous_signals_must_not_be_collapsed_to_truth_score")
