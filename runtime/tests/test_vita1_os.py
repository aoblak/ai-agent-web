import unittest

from vita.vita1_os import ActionRequest, TrustedActionEngine


class TrustedActionEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = TrustedActionEngine()

    def test_safe_action_executes_and_verifies(self) -> None:
        request = ActionRequest(action="compute.sum", actor="test", payload={"values": [2, 3, 5]})
        result = self.engine.execute(request, expected={"sum": 10})

        self.assertEqual(result.status, "COMPLETED")
        self.assertTrue(result.verified)
        self.assertEqual(result.output, {"sum": 10})
        self.assertEqual(
            [event["event"] for event in result.audit],
            [
                "request.received",
                "policy.evaluated",
                "execution.started",
                "execution.completed",
                "result.verified",
            ],
        )

    def test_consequential_action_waits_for_approval(self) -> None:
        request = ActionRequest(action="production.write", actor="test")
        result = self.engine.execute(request)

        self.assertEqual(result.status, "WAITING_APPROVAL")
        self.assertFalse(result.verified)
        self.assertEqual(result.audit[-1]["event"], "approval.required")

    def test_even_approved_consequential_action_has_no_production_executor(self) -> None:
        request = ActionRequest(action="production.write", actor="test")
        result = self.engine.execute(request, approval=True)

        self.assertEqual(result.status, "BLOCKED")
        self.assertFalse(result.verified)
        self.assertEqual(result.audit[-1]["detail"]["reason"], "no_executor_registered")

    def test_unknown_action_is_denied(self) -> None:
        request = ActionRequest(action="shell.exec", actor="test")
        result = self.engine.execute(request)

        self.assertEqual(result.status, "DENIED")
        self.assertFalse(result.verified)
        self.assertEqual(result.audit[-1]["event"], "execution.denied")

    def test_verification_failure_is_explicit(self) -> None:
        request = ActionRequest(action="compute.sum", actor="test", payload={"values": [1, 2]})
        result = self.engine.execute(request, expected={"sum": 99})

        self.assertEqual(result.status, "VERIFICATION_FAILED")
        self.assertFalse(result.verified)


if __name__ == "__main__":
    unittest.main()
