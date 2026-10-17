import copy
import json
from pathlib import Path
import tempfile
import unittest

from oos.company import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_NEEDS_APPROVAL,
    CompanyRegistryError,
    decide_company_request,
    load_company_registry,
    validate_company_registry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "registry" / "company-os.json"


class CompanyOSTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    def test_reference_registry_is_valid(self) -> None:
        self.assertEqual(validate_company_registry(self.registry), [])
        loaded = load_company_registry(REGISTRY_PATH)
        self.assertEqual(loaded["company_id"], "workspace-owner")
        self.assertTrue(loaded["architecture"]["human_final_authority"])
        self.assertTrue(loaded["architecture"]["fail_closed"])

    def test_unknown_skill_fails_closed(self) -> None:
        decision = decide_company_request(
            self.registry,
            skill_id="does_not_exist",
            capability="anything",
            action="read",
        )
        self.assertEqual(decision.state, DECISION_DENY)
        self.assertEqual(decision.reason, "unknown_skill")

    def test_planned_skill_is_not_executable(self) -> None:
        decision = decide_company_request(
            self.registry,
            skill_id="finance_admin",
            capability="analyze_cash_flow",
            action="analyze",
        )
        self.assertEqual(decision.state, DECISION_DENY)
        self.assertEqual(decision.reason, "skill_not_implemented:planned")

    def test_implemented_skill_allows_only_declared_capability_and_action(self) -> None:
        allowed = decide_company_request(
            self.registry,
            skill_id="repository_continuity",
            capability="retrieve_evidence",
            action="read",
        )
        self.assertEqual(allowed.state, DECISION_ALLOW)
        self.assertTrue(allowed.allowed)

        bad_capability = decide_company_request(
            self.registry,
            skill_id="repository_continuity",
            capability="send_email",
            action="read",
        )
        self.assertEqual(bad_capability.state, DECISION_DENY)
        self.assertEqual(bad_capability.reason, "capability_not_allowlisted")

        bad_action = decide_company_request(
            self.registry,
            skill_id="repository_continuity",
            capability="retrieve_evidence",
            action="external_communication",
        )
        self.assertEqual(bad_action.state, DECISION_DENY)
        self.assertEqual(bad_action.reason, "action_not_allowlisted")

    def test_consequential_action_requires_explicit_human_approval(self) -> None:
        registry = copy.deepcopy(self.registry)
        skill = registry["departments"][0]["skills"][0]
        skill["status"] = "implemented"
        skill["capabilities"] = ["publish_statement"]
        skill["allowed_actions"] = ["publication"]

        pending = decide_company_request(
            registry,
            skill_id=skill["id"],
            capability="publish_statement",
            action="publication",
            human_approved=False,
        )
        self.assertEqual(pending.state, DECISION_NEEDS_APPROVAL)
        self.assertEqual(pending.reason, "human_approval_required")

        approved = decide_company_request(
            registry,
            skill_id=skill["id"],
            capability="publish_statement",
            action="publication",
            human_approved=True,
        )
        self.assertEqual(approved.state, DECISION_ALLOW)

    def test_invalid_registry_is_denied_and_loader_rejects_it(self) -> None:
        invalid = copy.deepcopy(self.registry)
        invalid["departments"][0]["skills"][0]["status"] = "magic"
        self.assertTrue(validate_company_registry(invalid))

        decision = decide_company_request(
            invalid,
            skill_id="portfolio_prioritization",
            capability="prioritize_portfolio",
            action="read",
        )
        self.assertEqual(decision.state, DECISION_DENY)
        self.assertEqual(decision.reason, "invalid_registry")

        with tempfile.TemporaryDirectory() as temp_dir:
            broken_path = Path(temp_dir) / "invalid-company-os.json"
            broken_path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(CompanyRegistryError):
                load_company_registry(broken_path)

    def test_duplicate_skill_ids_are_rejected(self) -> None:
        duplicate = copy.deepcopy(self.registry)
        duplicate["departments"][1]["skills"][0]["id"] = (
            duplicate["departments"][0]["skills"][0]["id"]
        )
        errors = validate_company_registry(duplicate)
        self.assertIn("duplicate:skill:portfolio_prioritization", errors)


if __name__ == "__main__":
    unittest.main()
