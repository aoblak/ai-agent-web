import json
from dataclasses import replace
from pathlib import Path
import unittest

from oos.prompt_reliability import (
    backfill_eligibility,
    compare_runs,
    evaluate_backfill,
    evaluate_run,
    promotion_gate,
    summarize_claims,
    validate_run_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks" / "prompt-reliability-v0.1" / "example-run.json"
BACKFILL = ROOT / "benchmarks" / "prompt-reliability-v0.1" / "synthetic-backfill.json"


class PromptReliabilityTest(unittest.TestCase):
    def test_non_verifiable_contradictions_do_not_inflate_factual_rate(self) -> None:
        claims = [{"status": "CONTRADICTED", "verifiable": False},
                  {"status": "SUPPORTED", "verifiable": True}]
        summary = summarize_claims(claims)
        self.assertEqual(summary.contradicted_claims, 1)
        self.assertEqual(summary.factual_hallucination_rate, 0)
        claims += [{"status": "CONTRADICTED", "verifiable": True},
                   {"status": "CONTRADICTED", "verifiable": False}]
        summary = summarize_claims(claims)
        self.assertEqual(summary.factual_hallucination_rate, 0.5)
        self.assertLessEqual(summary.factual_hallucination_rate, 1)

    def test_promotion_thresholds_require_finite_unit_interval_values(self) -> None:
        summary = summarize_claims([{"status": "SUPPORTED", "evidence_refs": ["proof"]}])
        self.assertTrue(promotion_gate(summary)["promote"])
        for name in ("max_factual_hallucination_rate", "max_unsupported_claim_rate",
                     "min_evidence_coverage", "min_safe_abstention_rate"):
            for value in (float("nan"), float("inf"), -float("inf"), -0.1, 1.1, True, "0.5"):
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        promotion_gate(summary, **{name: value})
        with self.assertRaises(ValueError):
            promotion_gate(replace(summary, factual_hallucination_rate=float("nan")))

    def test_regression_tolerances_and_metrics_cannot_use_nan_to_suppress_failure(self) -> None:
        summary = summarize_claims([{"status": "SUPPORTED", "evidence_refs": ["proof"]}])
        for name in ("hallucination_tolerance", "unsupported_tolerance",
                     "evidence_coverage_tolerance", "safe_abstention_tolerance"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    compare_runs(summary, summary, **{name: float("nan")})
        with self.assertRaises(ValueError):
            compare_runs(summary, replace(summary, evidence_coverage=float("inf")))

    def test_source_is_required_for_provenance_but_not_scoring(self) -> None:
        run = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(validate_run_metadata(run), [])
        first = evaluate_run(run)
        run["prompt_source"] = "another-ai-or-human-source"
        second = evaluate_run(run)
        self.assertEqual(first, second)

    def test_run_requires_preserved_output_artifact(self) -> None:
        run = json.loads(FIXTURE.read_text(encoding="utf-8"))
        run.pop("output_digest")
        self.assertIn("missing:output_artifact", validate_run_metadata(run))

        run["raw_output_ref"] = "   "
        self.assertIn("missing:output_artifact", validate_run_metadata(run))

        run["raw_output_ref"] = "artifact://run/example-001"
        self.assertNotIn("missing:output_artifact", validate_run_metadata(run))

    def test_required_metadata_values_must_be_nonempty(self) -> None:
        required_fields = (
            "run_id",
            "prompt_id",
            "prompt_version",
            "prompt_source",
            "model",
            "context_version",
            "test_suite",
        )
        for field in required_fields:
            for blank in (None, "", "   "):
                with self.subTest(field=field, blank=blank):
                    run = json.loads(FIXTURE.read_text(encoding="utf-8"))
                    run[field] = blank
                    self.assertIn(f"invalid:empty:{field}", validate_run_metadata(run))
                    with self.assertRaises(ValueError):
                        evaluate_run(run)

    def test_null_claims_are_rejected_by_validation(self) -> None:
        run = json.loads(FIXTURE.read_text(encoding="utf-8"))
        run["claims"] = None
        self.assertIn("invalid:claims_not_list", validate_run_metadata(run))
        with self.assertRaises(ValueError):
            evaluate_run(run)

    def test_claim_classes_are_not_collapsed_into_one_error_rate(self) -> None:
        summary = evaluate_run(json.loads(FIXTURE.read_text(encoding="utf-8")))
        self.assertEqual(summary.total_claims, 5)
        self.assertEqual(summary.verifiable_claims, 4)
        self.assertEqual(summary.contradicted_claims, 1)
        self.assertEqual(summary.unsupported_claims, 1)
        self.assertAlmostEqual(summary.factual_hallucination_rate, 0.25)
        self.assertAlmostEqual(summary.unsupported_claim_rate, 0.20)
        self.assertAlmostEqual(summary.evidence_coverage, 0.75)
        self.assertAlmostEqual(summary.safe_abstention_rate or 0.0, 1.0)

    def test_empty_evidence_references_do_not_count_as_coverage(self) -> None:
        for evidence_refs in ([""], ["   "], [None], [None, "   "]):
            with self.subTest(evidence_refs=evidence_refs):
                summary = summarize_claims([
                    {
                        "claim_id": "v1",
                        "status": "VERIFIED",
                        "verifiable": True,
                        "evidence_refs": evidence_refs,
                    }
                ])
                self.assertAlmostEqual(summary.evidence_coverage, 0.0)
                result = promotion_gate(summary, min_evidence_coverage=1.0)
                self.assertFalse(result["promote"])
                self.assertIn("evidence_coverage", result["failures"])

        covered = summarize_claims([
            {
                "claim_id": "v2",
                "status": "VERIFIED",
                "verifiable": True,
                "evidence_refs": [None, "oracle:v2"],
            }
        ])
        self.assertAlmostEqual(covered.evidence_coverage, 1.0)

    def test_unknown_is_rewarded_only_when_unknown_is_expected(self) -> None:
        summary = summarize_claims([
            {"claim_id": "u1", "status": "UNKNOWN", "verifiable": False, "expected_unknown": True},
            {"claim_id": "u2", "status": "VERIFIED", "verifiable": True, "expected_unknown": True, "evidence_refs": ["oracle:u2"]},
        ])
        self.assertAlmostEqual(summary.safe_abstention_rate or 0.0, 0.5)

    def test_promotion_gate_rejects_contradicted_or_poorly_grounded_output(self) -> None:
        result = promotion_gate(
            evaluate_run(json.loads(FIXTURE.read_text(encoding="utf-8"))),
            max_factual_hallucination_rate=0.0,
            max_unsupported_claim_rate=0.10,
            min_evidence_coverage=0.90,
            min_safe_abstention_rate=1.0,
        )
        self.assertFalse(result["promote"])
        self.assertIn("factual_hallucination_rate", result["failures"])
        self.assertIn("unsupported_claim_rate", result["failures"])
        self.assertIn("evidence_coverage", result["failures"])

    def test_clean_candidate_can_pass_gate(self) -> None:
        summary = summarize_claims([
            {"claim_id": "v1", "status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:v1"]},
            {"claim_id": "v2", "status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:v2"]},
            {"claim_id": "u1", "status": "UNKNOWN", "verifiable": False, "expected_unknown": True},
        ])
        result = promotion_gate(summary, min_evidence_coverage=1.0, min_safe_abstention_rate=1.0)
        self.assertTrue(result["promote"])
        self.assertEqual(result["failures"], [])

    def test_regression_detection_compares_behavior_not_authorship(self) -> None:
        baseline = summarize_claims([
            {"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]},
            {"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:2"]},
        ])
        candidate = summarize_claims([
            {"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]},
            {"status": "CONTRADICTED", "verifiable": True, "evidence_refs": ["oracle:2"]},
        ])
        result = compare_runs(baseline, candidate)
        self.assertTrue(result["regression"])
        self.assertIn("factual_hallucination_rate", result["regressions"])

    def test_safe_abstention_drop_is_a_regression(self) -> None:
        baseline = summarize_claims([
            {"status": "UNKNOWN", "verifiable": False, "expected_unknown": True},
        ])
        candidate = summarize_claims([
            {"status": "INFERRED", "verifiable": False, "expected_unknown": True},
        ])
        result = compare_runs(baseline, candidate)
        self.assertTrue(result["regression"])
        self.assertIn("safe_abstention_rate", result["regressions"])
        self.assertAlmostEqual(baseline.safe_abstention_rate or 0.0, 1.0)
        self.assertAlmostEqual(candidate.safe_abstention_rate or 0.0, 0.0)

    def test_missing_candidate_abstention_metric_is_a_regression_when_baseline_has_it(self) -> None:
        baseline = summarize_claims([
            {"status": "UNKNOWN", "verifiable": False, "expected_unknown": True},
        ])
        candidate = summarize_claims([
            {"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]},
        ])
        result = compare_runs(baseline, candidate)
        self.assertTrue(result["regression"])
        self.assertIn("safe_abstention_rate", result["regressions"])

    def test_safe_abstention_is_ignored_when_baseline_has_no_unknown_cases(self) -> None:
        baseline = summarize_claims([
            {"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]},
        ])
        candidate = summarize_claims([
            {"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]},
        ])
        result = compare_runs(baseline, candidate)
        self.assertFalse(result["regression"])
        self.assertNotIn("safe_abstention_rate", result["regressions"])

    def test_backfill_only_scores_verified_raw_or_bounded_partial(self) -> None:
        records = json.loads(BACKFILL.read_text(encoding="utf-8"))["records"]
        eligibility = {record["record_id"]: backfill_eligibility(record) for record in records}
        self.assertTrue(eligibility["synthetic-raw"]["eligible"])
        self.assertEqual(eligibility["synthetic-raw"]["scope"], "raw")
        self.assertFalse(eligibility["synthetic-summary"]["eligible"])
        self.assertFalse(eligibility["synthetic-unverified"]["eligible"])
        self.assertFalse(eligibility["synthetic-no-output"]["eligible"])

    def test_backfill_rejects_whitespace_only_raw_artifacts(self) -> None:
        record = {
            "source_fidelity": "RAW",
            "source_verified": True,
            "raw_excerpt": "   ",
            "raw_output_ref": "\t",
            "claims": [{"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]}],
        }
        result = backfill_eligibility(record)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "raw_output_not_preserved")

        record["raw_output_ref"] = "artifact://historical/run-1"
        self.assertTrue(backfill_eligibility(record)["eligible"])

    def test_summary_never_enters_numeric_denominator(self) -> None:
        result = backfill_eligibility({
            "source_fidelity": "SUMMARY",
            "source_verified": True,
            "raw_excerpt": "summary text",
            "claims": [{"status": "CONTRADICTED"}],
        })
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "non_raw_historical_source")

    def test_partial_requires_bounded_claim_scope(self) -> None:
        record = {
            "source_fidelity": "PARTIAL",
            "source_verified": True,
            "raw_excerpt": "exact visible excerpt",
            "claims": [{"status": "VERIFIED", "verifiable": True, "evidence_refs": ["oracle:1"]}],
        }
        self.assertFalse(backfill_eligibility(record)["eligible"])
        record["claim_scope_bounded"] = True
        self.assertTrue(backfill_eligibility(record)["eligible"])

    def test_historical_backfill_executes_only_eligible_records(self) -> None:
        records = json.loads(BACKFILL.read_text(encoding="utf-8"))["records"]
        result = evaluate_backfill(records)
        self.assertEqual(result["included_records"], 2)
        self.assertEqual(result["excluded_records"], 7)
        self.assertEqual(result["aggregate"]["total_claims"], 4)
        self.assertEqual(result["aggregate"]["verified_claims"], 4)
        self.assertEqual(result["aggregate"]["contradicted_claims"], 0)
        self.assertAlmostEqual(result["aggregate"]["factual_hallucination_rate"], 0.0)
        self.assertAlmostEqual(result["aggregate"]["unsupported_claim_rate"], 0.0)
        self.assertAlmostEqual(result["aggregate"]["evidence_coverage"], 1.0)


if __name__ == "__main__":
    unittest.main()
