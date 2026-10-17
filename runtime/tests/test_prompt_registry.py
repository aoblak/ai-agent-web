import copy
import json
from pathlib import Path
import unittest

from oos.prompt_registry import (
    FAILURE_TAXONOMY,
    compare_execution_summaries,
    execution_manifest_digest,
    prompt_content_digest,
    reproducibility_level,
    summarize_executions,
    validate_execution_manifest,
    validate_execution_record,
    validate_prompt_definition,
    validate_version_transition,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "registry" / "prompts.json"
GOLDEN = ROOT / "evals" / "datasets" / "prompt-registry-golden.json"


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def sample_manifest(prompt: dict, *, revision: str | None = None) -> dict:
    model = {
        "provider": "example-provider",
        "name": "example-model",
        "config": {"temperature": 0},
    }
    if revision:
        model["revision"] = revision
    return {
        "manifest_version": "1.0.0",
        "prompt": {
            "prompt_id": prompt["prompt_id"],
            "version": prompt["version"],
            "content_digest": prompt["content_digest"],
        },
        "model": model,
        "context": {
            "profile": "test-context",
            "ref": "git:deadbeef",
            "digest": "sha256:" + "1" * 64,
        },
        "policy": {"id": "oos-read-only", "version": "1.0.0"},
        "toolset": {"id": "none", "version": "1.0.0"},
        "output_schema": {"id": "prompt-eval", "version": "1.0.0"},
    }


def sample_record(manifest: dict, *, success: bool, cost: float, latency: float, tokens: int) -> dict:
    return {
        "execution_id": f"exec-{tokens}-{int(success)}",
        "manifest_digest": execution_manifest_digest(manifest),
        "started_at": "2026-09-11T16:00:00Z",
        "completed_at": "2026-09-11T16:00:01Z",
        "status": "SUCCESS" if success else "FAILED",
        "task_success": success,
        "policy_compliant": True,
        "verifiable": True,
        "failure_codes": [] if success else ["BAD_PROMPT"],
        "metrics": {
            "input_tokens": tokens,
            "output_tokens": tokens // 2,
            "latency_ms": latency,
            "cost": cost,
        },
    }


class PromptRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = load_registry()
        self.prompt = next(item for item in registry["prompts"] if item.get("prompt_id") == "oos.prompt-registry-evaluator")
        self.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]

    def test_registry_definition_digest_is_valid(self) -> None:
        result = validate_prompt_definition(self.prompt)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(prompt_content_digest(self.prompt), self.prompt["content_digest"])

    def test_silent_mutation_is_detected(self) -> None:
        candidate = copy.deepcopy(self.prompt)
        candidate["template"] += " changed"
        result = validate_prompt_definition(candidate)
        self.assertFalse(result.valid)
        self.assertIn("content_digest_mismatch", result.errors)

    def test_same_version_cannot_change_identity_even_with_recomputed_digest(self) -> None:
        candidate = copy.deepcopy(self.prompt)
        candidate["template"] += " changed"
        candidate["content_digest"] = prompt_content_digest(candidate)
        result = validate_version_transition(self.prompt, candidate)
        self.assertFalse(result.valid)
        self.assertIn("VERSION_IMMUTABILITY_VIOLATION", result.errors)

    def test_changed_identity_requires_incremented_version_and_supersedes(self) -> None:
        candidate = copy.deepcopy(self.prompt)
        candidate["version"] = "1.1.0"
        candidate["template"] += " changed"
        candidate["supersedes"] = f"{self.prompt['prompt_id']}@{self.prompt['version']}"
        candidate["content_digest"] = prompt_content_digest(candidate)
        result = validate_version_transition(self.prompt, candidate)
        self.assertTrue(result.valid, result.errors)

    def test_semver_release_has_higher_precedence_than_prerelease(self) -> None:
        previous = copy.deepcopy(self.prompt)
        previous["version"] = "2.0.0-rc.1"
        previous["content_digest"] = prompt_content_digest(previous)

        candidate = copy.deepcopy(previous)
        candidate["version"] = "2.0.0"
        candidate["supersedes"] = f"{previous['prompt_id']}@{previous['version']}"
        candidate["content_digest"] = prompt_content_digest(candidate)

        result = validate_version_transition(previous, candidate)
        self.assertTrue(result.valid, result.errors)

    def test_semver_prerelease_identifiers_follow_numeric_precedence(self) -> None:
        previous = copy.deepcopy(self.prompt)
        previous["version"] = "2.0.0-rc.1"
        previous["content_digest"] = prompt_content_digest(previous)

        candidate = copy.deepcopy(previous)
        candidate["version"] = "2.0.0-rc.2"
        candidate["supersedes"] = f"{previous['prompt_id']}@{previous['version']}"
        candidate["content_digest"] = prompt_content_digest(candidate)

        result = validate_version_transition(previous, candidate)
        self.assertTrue(result.valid, result.errors)

    def test_semver_rejects_numeric_prerelease_leading_zero(self) -> None:
        candidate = copy.deepcopy(self.prompt)
        candidate["version"] = "2.0.0-01"
        candidate["content_digest"] = prompt_content_digest(candidate)
        result = validate_prompt_definition(candidate)
        self.assertFalse(result.valid)
        self.assertIn("invalid_semver", result.errors)

    def test_manifest_captures_bounded_vs_strong_reproducibility(self) -> None:
        bounded = sample_manifest(self.prompt)
        strong = sample_manifest(self.prompt, revision="provider-revision-123")
        self.assertTrue(validate_execution_manifest(bounded).valid)
        self.assertEqual(reproducibility_level(bounded), "BOUNDED")
        self.assertEqual(reproducibility_level(strong), "STRONG")

    def test_failure_taxonomy_and_unknown_code_rejection(self) -> None:
        self.assertIn("POLICY_VIOLATION", FAILURE_TAXONOMY)
        manifest = sample_manifest(self.prompt)
        record = sample_record(manifest, success=False, cost=0.1, latency=100, tokens=100)
        record["failure_codes"] = ["NOT_A_REAL_CODE"]
        result = validate_execution_record(record)
        self.assertFalse(result.valid)
        self.assertTrue(any(error.startswith("unknown_failure_codes:") for error in result.errors))

    def test_regression_summary_exposes_quality_cost_token_and_latency_deltas(self) -> None:
        manifest = sample_manifest(self.prompt)
        baseline = summarize_executions(
            [
                sample_record(manifest, success=False, cost=0.20, latency=200, tokens=200),
                sample_record(manifest, success=True, cost=0.20, latency=200, tokens=200),
            ]
        )
        candidate = summarize_executions(
            [
                sample_record(manifest, success=True, cost=0.15, latency=150, tokens=150),
                sample_record(manifest, success=True, cost=0.15, latency=150, tokens=150),
            ]
        )
        delta = compare_execution_summaries(baseline, candidate)
        self.assertGreater(delta["task_success_rate_delta"], 0)
        self.assertEqual(delta["policy_compliance_rate_delta"], 0)
        self.assertEqual(delta["verifiability_rate_delta"], 0)
        self.assertLess(delta["avg_total_tokens_delta"], 0)
        self.assertLess(delta["avg_latency_ms_delta"], 0)
        self.assertLess(delta["avg_cost_delta"], 0)

    def test_total_tokens_average_uses_each_execution_population(self) -> None:
        manifest = sample_manifest(self.prompt)
        rows = [sample_record(manifest, success=True, cost=0, latency=0, tokens=100)
                for _ in range(3)]
        rows[0]["metrics"] = {"input_tokens": 100}
        rows[1]["metrics"] = {"output_tokens": 100}
        rows[2]["metrics"] = {}
        summary = summarize_executions(rows)
        self.assertEqual(summary["avg_input_tokens"], 100)
        self.assertEqual(summary["avg_output_tokens"], 100)
        self.assertEqual(summary["avg_total_tokens"], 100)
        self.assertIsNone(summarize_executions([rows[2]])["avg_total_tokens"])
        self.assertEqual(summarize_executions([rows[0]])["avg_total_tokens"], 100)

    def test_golden_dataset_declares_core_acceptance_cases(self) -> None:
        by_id = {case["case_id"]: case for case in self.golden}
        self.assertTrue(by_id["valid-definition"]["expected_valid"])
        self.assertEqual(
            by_id["same-version-mutated-identity"]["expected_error"],
            "VERSION_IMMUTABILITY_VIOLATION",
        )
        self.assertEqual(by_id["bounded-reproducibility"]["expected_level"], "BOUNDED")
        self.assertEqual(by_id["strong-reproducibility"]["expected_level"], "STRONG")


if __name__ == "__main__":
    unittest.main()
