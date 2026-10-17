import json
import unittest
from unittest.mock import patch

from oos.model_router import (
    Capability,
    EvidencePacket,
    ModelCatalog,
    ModelResponse,
    ModelRouter,
    OpenAIResponsesExecutor,
    RoutingError,
    TaskProfile,
)


class FakeExecutor:
    def __init__(self, evidence=None):
        self.calls = []
        self.evidence = evidence or {
            "problem": "conflicting state",
            "branch": "feature/router",
            "head": "abc123",
            "relevant_files": ["registry/state.yaml"],
            "relevant_commits": ["abc123"],
            "tests_and_results": ["unit tests PASS"],
            "observed_behavior": ["state and code differ"],
            "conflicting_evidence": ["state says planned; code exists"],
            "attempted_solutions": [],
            "unresolved_question": "Which source is current?",
            "confidence": 0.6,
        }

    def run(self, *, model, instructions, input_text):
        self.calls.append((model, instructions, input_text))
        output = json.dumps(self.evidence) if len(self.calls) == 1 else "completed"
        return ModelResponse(model=model, output_text=output, response_id=str(len(self.calls)))


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.catalog = ModelCatalog("cheap", "standard", "strong")

    def test_routine_task_uses_fast_model_without_evidence_call(self):
        executor = FakeExecutor()
        result = ModelRouter(self.catalog, executor).run(
            TaskProfile("Format docs", "documentation"), branch="feature/docs", head="abc"
        )
        self.assertEqual(result.capability, Capability.FAST)
        self.assertEqual(result.model, "cheap")
        self.assertIsNone(result.evidence)
        self.assertEqual([call[0] for call in executor.calls], ["cheap"])

    def test_normal_implementation_uses_general_model(self):
        executor = FakeExecutor()
        result = ModelRouter(self.catalog, executor).run(
            TaskProfile("Implement endpoint", "implementation"), branch="feature/api", head="abc"
        )
        self.assertEqual(result.capability, Capability.GENERAL)
        self.assertEqual([call[0] for call in executor.calls], ["standard"])

    def test_contradiction_gets_cheap_evidence_before_strong_escalation(self):
        executor = FakeExecutor()
        result = ModelRouter(self.catalog, executor).run(
            TaskProfile(
                "Reconcile state", "implementation", conflicting_evidence=("code vs state",)
            ),
            branch="feature/router",
            head="abc123",
        )
        self.assertEqual(result.capability, Capability.HIGH)
        self.assertEqual(result.evidence_model, "cheap")
        self.assertEqual([call[0] for call in executor.calls], ["cheap", "strong"])
        self.assertIn("unresolved_question", executor.calls[1][2])

    def test_resolved_architecture_packet_downgrades_to_general(self):
        evidence = {
            "problem": "architecture question",
            "branch": "feature/router",
            "head": "abc123",
            "relevant_files": ["oos/model_router.py"],
            "relevant_commits": ["abc123"],
            "tests_and_results": ["tests PASS"],
            "observed_behavior": ["single clear extension point"],
            "conflicting_evidence": [],
            "attempted_solutions": [],
            "unresolved_question": "",
            "confidence": 0.95,
        }
        executor = FakeExecutor(evidence)
        result = ModelRouter(self.catalog, executor).run(
            TaskProfile("Choose extension", "architecture"), branch="feature/router", head="abc123"
        )
        self.assertEqual(result.capability, Capability.GENERAL)
        self.assertEqual([call[0] for call in executor.calls], ["cheap", "standard"])

    def test_security_and_consequential_work_stays_high_and_flags_authority(self):
        evidence = dict(FakeExecutor().evidence)
        evidence.update(
            branch="security/auth", head="abc", conflicting_evidence=[],
            unresolved_question="", confidence=1.0,
        )
        executor = FakeExecutor(evidence)
        result = ModelRouter(self.catalog, executor).run(
            TaskProfile("Change auth", "security", consequential=True), branch="security/auth", head="abc"
        )
        self.assertEqual(result.capability, Capability.HIGH)
        self.assertTrue(result.requires_human_authority)
        self.assertEqual([call[0] for call in executor.calls], ["cheap", "strong"])

    def test_consequential_fast_type_is_never_executed_by_fast_model(self):
        for task_type in ("discovery", "documentation", "routine_test", "mechanical_refactor"):
            with self.subTest(task_type=task_type):
                evidence = dict(FakeExecutor().evidence)
                evidence.update(branch="feature/safe", head="abc", conflicting_evidence=[],
                                unresolved_question="", confidence=1.0)
                executor = FakeExecutor(evidence)
                result = ModelRouter(self.catalog, executor).run(
                    TaskProfile("Consequence-bearing change", task_type, consequential=True),
                    branch="feature/safe", head="abc",
                )
                self.assertEqual(result.capability, Capability.HIGH)
                self.assertTrue(result.requires_human_authority)
                self.assertEqual([call[0] for call in executor.calls], ["cheap", "strong"])

    def test_consequential_fast_type_invalid_evidence_fails_closed(self):
        executor = FakeExecutor({"problem": "incomplete"})
        with self.assertRaises(RoutingError):
            ModelRouter(self.catalog, executor).run(
                TaskProfile("Consequence-bearing audit", "documentation", consequential=True),
                branch="feature/safe", head="abc",
            )
        self.assertEqual([call[0] for call in executor.calls], ["cheap"])

    def test_repeated_failure_escalates_after_evidence(self):
        evidence = dict(FakeExecutor().evidence)
        evidence.update(
            branch="fix/bug", head="abc", conflicting_evidence=[],
            unresolved_question="", confidence=1.0,
        )
        executor = FakeExecutor(evidence)
        result = ModelRouter(self.catalog, executor).run(
            TaskProfile("Fix bug", "debugging", failed_attempts=2), branch="fix/bug", head="abc"
        )
        self.assertEqual(result.capability, Capability.HIGH)
        self.assertEqual([call[0] for call in executor.calls], ["cheap", "strong"])

    def test_invalid_evidence_fails_closed(self):
        executor = FakeExecutor()
        executor.evidence = {"problem": "incomplete"}
        with self.assertRaises(RoutingError):
            ModelRouter(self.catalog, executor).run(
                TaskProfile("Reconcile", "debugging", risks=("production",)),
                branch="fix/bug",
                head="abc",
            )
        self.assertEqual(len(executor.calls), 1)

    def test_evidence_must_match_routed_branch_and_head(self):
        executor = FakeExecutor()
        with self.assertRaises(RoutingError):
            ModelRouter(self.catalog, executor).run(
                TaskProfile("Reconcile", "debugging", risks=("uncertainty",)),
                branch="different-branch",
                head="abc123",
            )
        self.assertEqual(len(executor.calls), 1)

    def test_suspected_credentials_fail_before_any_model_call(self):
        executor = FakeExecutor()
        with self.assertRaises(RoutingError):
            ModelRouter(self.catalog, executor).run(
                TaskProfile("Inspect api_key=sk-1234567890abcdef", "documentation"),
                branch="feature/docs",
                head="abc",
            )
        self.assertEqual(executor.calls, [])

    def test_evidence_schema_and_task_validation(self):
        with self.assertRaises(RoutingError):
            EvidencePacket.from_json("not json")
        with self.assertRaises(ValueError):
            TaskProfile("", "documentation")
        with self.assertRaises(ValueError):
            TaskProfile("x", "unknown")
        with self.assertRaises(ValueError):
            ModelCatalog("", "general", "high")
        profile = TaskProfile.from_dict(
            {"objective": "Inspect", "task_type": "discovery", "relevant_files": ["README.md"]}
        )
        self.assertEqual(profile.relevant_files, ("README.md",))
        with self.assertRaises(ValueError):
            TaskProfile.from_dict({"objective": "Inspect", "task_type": "discovery", "risks": "x"})

    def test_openai_adapter_sends_selected_model_and_does_not_store(self):
        response = {
            "id": "resp_1",
            "model": "chosen-model",
            "output": [{"content": [{"type": "output_text", "text": "result"}]}],
        }

        class FakeHTTPResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def read(self):
                return json.dumps(response).encode()

        with patch("oos.model_router.request.urlopen", return_value=FakeHTTPResponse()) as urlopen:
            executor = OpenAIResponsesExecutor(api_key="test-key")
            result = executor.run(model="chosen-model", instructions="rules", input_text="task")
        sent = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(sent["model"], "chosen-model")
        self.assertFalse(sent["store"])
        self.assertEqual(result.model, "chosen-model")
        self.assertEqual(result.output_text, "result")

    def test_openai_adapter_requires_key_and_https(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                OpenAIResponsesExecutor()
        with self.assertRaises(ValueError):
            OpenAIResponsesExecutor(api_key="test", base_url="http://example.invalid")


if __name__ == "__main__":
    unittest.main()
