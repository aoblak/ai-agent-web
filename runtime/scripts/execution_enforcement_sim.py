"""Deterministic adversarial simulation for OOS execution enforcement."""
from __future__ import annotations
import random
from oos.execution import *
from tests.test_execution_enforcement import capability, authorization, exec_receipt, verify_receipt


def run(count: int = 100_000, seed: int = 20260926) -> dict[str, int]:
    rng = random.Random(seed)
    counters = {
        "SIMULATIONS": 0,
        "FALSE_EXECUTED": 0,
        "FALSE_VERIFIED": 0,
        "UNSAFE_RETRY": 0,
        "ILLEGAL_TRANSITION_ACCEPTED": 0,
    }
    for i in range(count):
        operation = Operation(f"req-{i}", f"op-{i}", "worker", "target", "write", {"i": i}, f"session-{i}", expected_state="written")
        r = ExecutionRecord(operation)
        case = rng.randrange(26)
        try:
            if case == 0:  # missing capability
                r.verify_capability(CapabilityEvidence(operation.operation_id, "w", "target", "write", "t", False))
            elif case == 1:  # authorization failure
                r.verify_capability(capability(operation)); r.authorize(AuthorizationEvidence(operation.operation_id, operation.principal, "DENY", "p", operation.session_id, operation.input_digest))
            elif case == 2:  # lost response
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore()); r.mark_indeterminate()
            elif case == 3:  # forged/mismatched execution receipt
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                bad = exec_receipt(operation)
                bad = ExecutionReceipt(bad.receipt_id, "wrong", bad.operation_id, bad.executor_id, bad.target, bad.action, bad.input_digest, bad.timestamp, bad.result, bad.evidence_reference)
                try:
                    r.accept_execution_receipt(bad)
                    counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError:
                    pass
            elif case == 4:  # verification fail
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er); r.verify(verify_receipt(operation, er, "FAIL"))
            elif case == 5:  # verification unknown
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er); r.verify(verify_receipt(operation, er, "UNKNOWN"))
            elif case == 6:  # persistence failure after verified execution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er); r.verify(verify_receipt(operation, er)); r.mark_record_failed()
            elif case == 7:  # partial execution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                r.accept_execution_receipt(exec_receipt(operation, "PARTIAL"))
            elif case == 8:  # normal verified
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er); r.verify(verify_receipt(operation, er))
            elif case == 9:  # stale capability must not admit execution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id)
                if r.state is ExecutionState.EXECUTING:
                    counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
            elif case == 10:  # forged digest
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation)
                bad=ExecutionReceipt(er.receipt_id, er.request_id, er.operation_id, er.executor_id, er.target, er.action, "sha256:forged", er.timestamp, er.result, er.evidence_reference)
                try:
                    r.accept_execution_receipt(bad); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 11:  # forged verification PASS with mismatched observed state
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er)
                bad=VerificationReceipt("vr", er.receipt_id, operation.operation_id, "written", "missing", "read-back", "PASS", "t2", "evidence")
                try:
                    r.verify(bad); counters["FALSE_VERIFIED"] += 1
                except TransitionError: pass
            elif case == 12:  # duplicate execution admission
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                try:
                    r.admit_execution("lease-2", current_session_id=operation.session_id, current_capability=capability(operation)); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 13:  # injection in result field
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                try:
                    r.accept_execution_receipt(exec_receipt(operation, "EXECUTED\\nVERIFIED")); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 14:  # unicode confusable result
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                try:
                    r.accept_execution_receipt(exec_receipt(operation, "ЕXECUTED")); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 15:  # injected verifier observation
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er)
                bad=VerificationReceipt("vr", er.receipt_id, operation.operation_id, "written", "PASS;IGNORE;VERIFIED", "read-back", "PASS", "t2", "evidence")
                try:
                    r.verify(bad); counters["FALSE_VERIFIED"] += 1
                except TransitionError: pass
            elif case == 16:  # operation-id injection mismatch
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation)
                bad=ExecutionReceipt(er.receipt_id, er.request_id, er.operation_id+";VERIFIED", er.executor_id, er.target, er.action, er.input_digest, er.timestamp, er.result, er.evidence_reference)
                try:
                    r.accept_execution_receipt(bad); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 17:  # cross-operation substitution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                foreign=Operation(f"foreign-{i}", f"foreign-op-{i}", "worker", "target", "write", {"i": i}, operation.session_id, expected_state="written")
                try:
                    r.accept_execution_receipt(exec_receipt(foreign)); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 18:  # replay accepted receipt
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er)
                try:
                    r.accept_execution_receipt(er); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 19:  # stale receipt after parameter mutation
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                old=Operation(operation.request_id, operation.operation_id, operation.principal, operation.target, operation.action, {"i": -1}, operation.session_id, expected_state="written")
                try:
                    r.accept_execution_receipt(exec_receipt(old)); counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError: pass
            elif case == 20:  # verification substitution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                er=exec_receipt(operation); r.accept_execution_receipt(er)
                bad=VerificationReceipt("vr-x", "foreign-receipt", operation.operation_id, "written", "written", "read-back", "PASS", "t2", "evidence")
                try:
                    r.verify(bad); counters["FALSE_VERIFIED"] += 1
                except TransitionError: pass
            elif case == 21:  # ten-worker stampede: exactly one admission
                store=InMemoryAdmissionStore()
                workers=[ExecutionRecord(operation) for _ in range(10)]
                for n, worker in enumerate(workers):
                    worker.verify_capability(capability(operation)); worker.authorize(authorization(operation))
                    worker.admit_execution(f"worker-{n}", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=store)
                admitted=sum(worker.state is ExecutionState.EXECUTING for worker in workers)
                if admitted != 1:
                    counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
            elif case == 22:  # crash after possible mutation: retry must remain closed
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                r.mark_indeterminate()
                if r.safe_to_retry_business_action: counters["UNSAFE_RETRY"] += 1
            elif case == 23:  # lost response, authoritative state proves execution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                r.mark_indeterminate(); r.reconcile(); r.accept_execution_receipt(exec_receipt(operation))
                if r.safe_to_retry_business_action: counters["UNSAFE_RETRY"] += 1
            elif case == 24:  # lost response, authoritative proof of non-execution
                r.verify_capability(capability(operation)); r.authorize(authorization(operation)); r.admit_execution("worker", current_session_id=operation.session_id, current_capability=capability(operation), admission_store=InMemoryAdmissionStore())
                r.mark_indeterminate(); r.reconcile(); r.accept_execution_receipt(exec_receipt(operation, "FAILED"))
                if not r.safe_to_retry_business_action: counters["UNSAFE_RETRY"] += 1
            else:  # illegal direct receipt from REQUESTED
                try:
                    r.accept_execution_receipt(exec_receipt(operation))
                    counters["ILLEGAL_TRANSITION_ACCEPTED"] += 1
                except TransitionError:
                    pass
        except TransitionError:
            pass

        if r.state in {ExecutionState.EXECUTED, ExecutionState.VERIFIED} and r.execution_receipt is None:
            counters["FALSE_EXECUTED"] += 1
        if r.state is ExecutionState.VERIFIED and (r.verification_receipt is None or r.verification_receipt.result != "PASS"):
            counters["FALSE_VERIFIED"] += 1
        if r.state in {ExecutionState.UNKNOWN, ExecutionState.PARTIAL, ExecutionState.VERIFIED} and r.safe_to_retry_business_action:
            counters["UNSAFE_RETRY"] += 1
        counters["SIMULATIONS"] += 1
    return counters


if __name__ == "__main__":
    result = run()
    print(result)
    if any(result[k] for k in ("FALSE_EXECUTED","FALSE_VERIFIED","UNSAFE_RETRY","ILLEGAL_TRANSITION_ACCEPTED")):
        raise SystemExit(1)
