"""BNT-0001: authorization evidence must be bound to the acting principal."""
import unittest

from oos.execution import (
    AuthorizationEvidence,
    CapabilityEvidence,
    ExecutionRecord,
    ExecutionState,
    Operation,
)


class BNT0001PrincipalBindingTests(unittest.TestCase):
    def operation(self):
        return Operation(
            "req-bnt-0001",
            "op-bnt-0001",
            "expected-principal",
            "repo:controlled-test",
            "write",
            {"marker": "safe-test-only"},
            "session-bnt-0001",
            expected_state="written",
        )

    def test_foreign_principal_capability_cannot_authorize_operation(self):
        operation = self.operation()
        record = ExecutionRecord(operation)
        record.verify_capability(
            CapabilityEvidence(
                operation.operation_id,
                "foreign-principal",
                operation.target,
                operation.action,
                "t0",
                True,
            )
        )
        self.assertEqual(record.state, ExecutionState.BLOCKED)

    def test_foreign_principal_authorization_cannot_authorize_operation(self):
        operation = self.operation()
        record = ExecutionRecord(operation)
        record.verify_capability(
            CapabilityEvidence(
                operation.operation_id,
                operation.principal,
                operation.target,
                operation.action,
                "t0",
                True,
            )
        )
        self.assertEqual(record.state, ExecutionState.CAPABILITY_VERIFIED)

        record.authorize(
            AuthorizationEvidence(
                operation.operation_id,
                "foreign-principal",
                "ALLOW",
                "policy:bnt-0001-controlled",
                operation.session_id,
                operation.input_digest,
            )
        )
        self.assertEqual(record.state, ExecutionState.BLOCKED)


if __name__ == "__main__":
    unittest.main()
