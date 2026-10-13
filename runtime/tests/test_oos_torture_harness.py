import json
from pathlib import Path
import unittest

from oos.torture import (
    aggregate_campaign,
    evaluate_agent_conflict,
    evaluate_conflicting_context,
    evaluate_stale_state,
    evaluate_success_claim,
    recover_interrupted_write,
    validate_search_receipt,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "benchmarks" / "oos-torture-test-v0.1" / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class OOSTortureHarnessTest(unittest.TestCase):
    def test_t1_conflicting_context_blocks_action(self) -> None:
        result = evaluate_conflicting_context(load("T1-conflicting-context.json"))
        self.assertEqual(result.status, "CONFLICT")
        self.assertFalse(result.action_allowed)
        self.assertEqual(result.unsafe_action_escapes, 0)

    def test_t2_stale_state_is_rejected(self) -> None:
        result = evaluate_stale_state(load("T2-stale-state.json"))
        self.assertEqual(result.status, "STALE_STATE")
        self.assertFalse(result.action_allowed)

    def test_t3_resume_is_idempotent(self) -> None:
        result = recover_interrupted_write(load("T3-interrupted-write.json"))
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.evidence["resume"], "skip_already_completed")
        self.assertEqual(result.duplicate_side_effects, 0)

    def test_t4_false_success_is_not_promoted(self) -> None:
        result = evaluate_success_claim(load("T4-false-success.json"))
        self.assertEqual(result.status, "NEEDS_CHANGES")
        self.assertFalse(result.action_allowed)
        self.assertIn("ci_green", result.evidence["failed_postconditions"])

    def test_t5_unverified_agent_conflict_is_not_integrated(self) -> None:
        result = evaluate_agent_conflict(load("T5-agent-conflict.json"))
        self.assertEqual(result.status, "NEEDS_REVIEW")
        self.assertFalse(result.action_allowed)
        self.assertIsNone(result.selected)

    def test_negative_search_evidence_requires_complete_scope(self) -> None:
        incomplete = validate_search_receipt(load("SEARCHED-incomplete.json"))
        complete = validate_search_receipt(load("SEARCHED-complete.json"))

        self.assertEqual(incomplete.status, "UNVERIFIED")
        self.assertFalse(incomplete.action_allowed)
        self.assertEqual(complete.status, "PASS")
        self.assertTrue(complete.evidence["negative_evidence"])

    def test_campaign_primary_safety_kpis_remain_zero(self) -> None:
        evaluations = [
            evaluate_conflicting_context(load("T1-conflicting-context.json")),
            evaluate_stale_state(load("T2-stale-state.json")),
            recover_interrupted_write(load("T3-interrupted-write.json")),
            evaluate_success_claim(load("T4-false-success.json")),
            evaluate_agent_conflict(load("T5-agent-conflict.json")),
        ]
        summary = aggregate_campaign(evaluations)
        self.assertTrue(summary["pass"])
        self.assertEqual(summary["unsafe_action_escapes"], 0)
        self.assertEqual(summary["duplicate_side_effects"], 0)


if __name__ == "__main__":
    unittest.main()
