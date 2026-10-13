import unittest
from io import BytesIO
import zipfile

from oos.company import DECISION_NEEDS_APPROVAL, decide_company_request
from oos.github_signal_adapter import GitHubAdapterError, GitHubRestClient
from oos.github_signal_ingester import GitHubSignalError, RawGitHubEvent
from oos.prompt_reliability import (
    backfill_eligibility,
    summarize_claims,
    validate_run_metadata,
)
from oos.turboai_security import require_session_owner
from oos.artifact_ingestion import (
    ArtifactIngestionGate,
    ArtifactInput,
    IngestionPolicy,
    SpecializedVerification,
)
from oos.model_router import ModelCatalog, ModelRouter, OpenAIResponsesExecutor, TaskProfile
from vita.vita1_os import ActionRequest, TrustedActionEngine
from vita.vita2_verify import EvidenceItem, VerificationClaim, verify_claim

from oos.torture import (
    evaluate_action_transition,
    evaluate_agent_conflict,
    evaluate_claim_scope,
    evaluate_entity_resolution,
    evaluate_negative_claim,
    evaluate_provenance_graph,
    evaluate_success_claim,
    evaluate_temporal_validity,
    recover_interrupted_write,
    trace_contamination,
    validate_search_receipt,
)


class EpistemicECCFaultInjectionTest(unittest.TestCase):
    def test_success_without_postcondition_contract_is_blocked(self) -> None:
        result = evaluate_success_claim({"claimed_success": True, "postconditions": {}})
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)

    def test_malformed_interrupted_write_ledger_is_blocked(self) -> None:
        result = recover_interrupted_write(
            {"completed_effect_ids": "effect-1", "requested_effect_id": "effect-2"}
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)

    def test_malformed_agent_proposal_is_blocked(self) -> None:
        result = evaluate_agent_conflict(
            {"proposals": [{"agent": "A", "verified": True}]}
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)

    def test_search_receipt_rejects_empty_provider(self) -> None:
        result = validate_search_receipt(
            {
                "query": "parks",
                "provider": " ",
                "scope": "all-pages",

                "claim_scope": "all-pages",
                "searched_scopes": ["all-pages"],
                "started_at": "2026-09-29T00:00:00Z",
                "completed_at": "2026-09-29T00:00:01Z",
                "result_count": 0,
                "completeness": "complete",
                "raw_response_digest": "sha256:" + ("0" * 64),
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertIn("provider", result.evidence["empty_fields"])

    def test_negative_search_claim_cannot_exceed_searched_scope(self) -> None:
        result = validate_search_receipt(
            {
                "query": "gateway",
                "provider": "github",
                "scope": "main",

                "claim_scope": "all-repository-refs",
                "searched_scopes": ["main"],
                "started_at": "2026-09-30T00:00:00Z",
                "completed_at": "2026-09-30T00:00:01Z",
                "result_count": 0,
                "completeness": "complete",
                "raw_response_digest": "sha256:" + ("a" * 64),
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)
        self.assertEqual(result.evidence["reason"], "negative_claim_exceeds_searched_scope")

    def test_search_receipt_rejects_fake_completeness(self) -> None:
        result = validate_search_receipt(
            {
                "query": "parks",
                "provider": "provider",
                "scope": "all-pages",

                "claim_scope": "all-pages",

                "searched_scopes": ["all-pages"],
                "started_at": "2026-09-29T00:00:00Z",
                "completed_at": "2026-09-29T00:00:01Z",
                "result_count": 0,
                "completeness": "complete-enough",
                "raw_response_digest": "sha256:" + ("0" * 64),
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["reason"], "invalid_completeness")

    def test_correlated_downstream_evidence_counts_as_one_origin(self) -> None:
        result = evaluate_provenance_graph(
            {
                "min_independent_roots": 2,
                "trusted_origins": ["wp-db-row-18"],
                "evidence": [
                    {"id": "db", "parent_ids": [], "origin": "wp-db-row-18"},
                    {"id": "rest", "parent_ids": ["db"]},
                    {"id": "map", "parent_ids": ["db"]},
                    {"id": "worker", "parent_ids": ["rest"]},
                ],
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)
        self.assertEqual(result.evidence["independent_origins"], ["wp-db-row-18"])

    def test_two_root_ids_with_same_origin_are_not_independent(self) -> None:
        result = evaluate_provenance_graph(
            {
                "min_independent_roots": 2,
                "trusted_origins": ["google-place-123"],
                "evidence": [
                    {"id": "source-a", "parent_ids": [], "origin": "google-place-123"},
                    {"id": "source-b", "parent_ids": [], "origin": "google-place-123"},
                ],
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["reason"], "insufficient_independent_evidence")

    def test_provenance_cycle_is_blocked(self) -> None:
        result = evaluate_provenance_graph(
            {
                "trusted_origins": ["unused"],
                "evidence": [
                    {"id": "a", "parent_ids": ["c"]},
                    {"id": "b", "parent_ids": ["a"]},
                    {"id": "c", "parent_ids": ["b"]},
                ]
            }
        )
        self.assertEqual(result.status, "CONFLICT")
        self.assertFalse(result.action_allowed)

    def test_missing_provenance_parent_is_blocked(self) -> None:
        result = evaluate_provenance_graph(
            {
                "trusted_origins": ["unused"],
                "evidence": [
                    {"id": "derived", "parent_ids": ["missing"]}
                ]
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["reason"], "missing_provenance_parent")

    def test_root_without_origin_is_blocked(self) -> None:
        result = evaluate_provenance_graph(
            {"trusted_origins": ["expected"], "evidence": [{"id": "root", "parent_ids": []}]}
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["reason"], "missing_root_origin")

    def test_temporal_truth_expires(self) -> None:
        result = evaluate_temporal_validity(
            {
                "verified_at": "2026-09-01T00:00:00Z",
                "valid_until": "2026-09-20T00:00:00Z",
                "as_of": "2026-09-29T00:00:00Z",
            }
        )
        self.assertEqual(result.status, "STALE_STATE")
        self.assertFalse(result.action_allowed)

    def test_future_verification_is_conflict(self) -> None:
        result = evaluate_temporal_validity(
            {
                "verified_at": "2026-10-01T00:00:00Z",
                "valid_until": "2026-10-10T00:00:00Z",
                "as_of": "2026-09-29T00:00:00Z",
            }
        )
        self.assertEqual(result.status, "CONFLICT")
        self.assertFalse(result.action_allowed)

    def test_claim_scope_cannot_escalate(self) -> None:
        result = evaluate_claim_scope(
            {
                "claim_scope": "physical_location_verified",
                "evidence_scopes": ["db_value_present", "rest_matches_db"],
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)

    def test_plan_cannot_jump_to_executed(self) -> None:
        result = evaluate_action_transition(
            {
                "from_state": "PROPOSED",
                "to_state": "EXECUTED",
                "evidence": {"execution_receipt": "cmd:123"},
            }
        )
        self.assertEqual(result.status, "NEEDS_CHANGES")
        self.assertFalse(result.action_allowed)

    def test_executed_requires_postcondition_before_verified(self) -> None:
        result = evaluate_action_transition(
            {
                "from_state": "EXECUTED",
                "to_state": "VERIFIED",
                "evidence": {"postcondition_verified": False},
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)

    def test_name_only_entity_match_never_auto_merges(self) -> None:
        result = evaluate_entity_resolution(
            {
                "left": {"name": "Example restaurant"},
                "right": {"name": "Example restaurant"},
            }
        )
        self.assertEqual(result.status, "NEEDS_REVIEW")
        self.assertFalse(result.action_allowed)

    def test_strong_entity_identifier_conflict_blocks_merge(self) -> None:
        result = evaluate_entity_resolution(
            {
                "left": {"name": "X", "place_id": "A"},
                "right": {"name": "X", "place_id": "B"},
            }
        )
        self.assertEqual(result.status, "CONFLICT")
        self.assertFalse(result.action_allowed)

    def test_no_data_during_outage_is_not_negative_fact(self) -> None:
        result = evaluate_negative_claim(
            {"source_available": False, "query_complete": False, "result_count": 0}
        )
        self.assertEqual(result.status, "UNAVAILABLE")
        self.assertFalse(result.action_allowed)

    def test_zero_results_are_negative_only_after_complete_query(self) -> None:
        result = evaluate_negative_claim(
            {"source_available": True, "query_complete": True, "result_count": 0}
        )
        self.assertEqual(result.status, "PASS")
        self.assertTrue(result.evidence["negative_evidence"])

    def test_contamination_reaches_all_declared_dependents(self) -> None:
        result = trace_contamination(
            {
                "invalidated": ["claim:C17"],
                "dependencies": {
                    "claim:C17": ["rule:R4", "decision:D11"],
                    "rule:R4": ["artifact:A29"],
                    "decision:D11": ["agent-state:AG7"],
                    "artifact:A29": ["published:P3"],
                },
            }
        )
        self.assertEqual(result.status, "CONTAMINATED")
        self.assertFalse(result.action_allowed)
        self.assertEqual(
            result.evidence["impacted"],
            [
                "agent-state:AG7",
                "artifact:A29",
                "claim:C17",
                "decision:D11",
                "published:P3",
                "rule:R4",
            ],
        )

    def test_string_false_cannot_claim_success(self) -> None:
        result = evaluate_success_claim(
            {"claimed_success": "false", "postconditions": {"write": True}}
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["reason"], "invalid_claimed_success")

    def test_search_receipt_rejects_reversed_timestamps(self) -> None:
        result = validate_search_receipt(
            {
                "query": "parks",
                "provider": "provider",
                "scope": "all-pages",

                "claim_scope": "all-pages",

                "searched_scopes": ["all-pages"],
                "started_at": "2026-09-29T00:00:02Z",
                "completed_at": "2026-09-29T00:00:01Z",
                "result_count": 0,
                "completeness": "complete",
                "raw_response_digest": "sha256:" + ("0" * 64),
            }
        )
        self.assertEqual(result.status, "CONFLICT")
        self.assertEqual(result.evidence["reason"], "search_completed_before_started")

    def test_naive_timestamp_is_not_assumed_utc(self) -> None:
        result = evaluate_temporal_validity(
            {
                "verified_at": "2026-09-01T00:00:00",
                "valid_until": "2026-09-20T00:00:00Z",
                "as_of": "2026-09-10T00:00:00Z",
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")

    def test_invalid_validity_interval_is_conflict(self) -> None:
        result = evaluate_temporal_validity(
            {
                "verified_at": "2026-09-20T00:00:00Z",
                "valid_until": "2026-09-01T00:00:00Z",
                "as_of": "2026-09-21T00:00:00Z",
            }
        )
        self.assertEqual(result.status, "CONFLICT")
        self.assertEqual(result.evidence["reason"], "invalid_validity_interval")

    def test_self_declared_origin_is_not_trusted(self) -> None:
        result = evaluate_provenance_graph(
            {
                "trusted_origins": ["real-source"],
                "evidence": [
                    {"id": "fake-root", "parent_ids": [], "origin": "invented-source"}
                ],
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["reason"], "untrusted_provenance_origin")

    def test_execution_receipt_must_be_verified_structure(self) -> None:
        result = evaluate_action_transition(
            {
                "from_state": "EXECUTING",
                "to_state": "EXECUTED",
                "evidence": {"execution_receipt": "200 OK"},
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertFalse(result.action_allowed)

    def test_approved_state_still_requires_approval_receipt(self) -> None:
        result = evaluate_action_transition(
            {
                "from_state": "APPROVED",
                "to_state": "EXECUTING",
                "evidence": {},
            }
        )
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertEqual(result.evidence["required"], "approval_receipt")

    def test_single_noncanonical_identifier_does_not_auto_merge(self) -> None:
        result = evaluate_entity_resolution(
            {
                "left": {"name": "X", "phone": "+385123"},
                "right": {"name": "X", "phone": "+385123"},
            }
        )
        self.assertEqual(result.status, "NEEDS_REVIEW")
        self.assertEqual(
            result.evidence["reason"], "insufficient_matching_strong_identifiers"
        )

    def test_vita_without_expected_postcondition_cannot_verify(self) -> None:
        engine = TrustedActionEngine()
        result = engine.execute(
            ActionRequest(
                action="compute.sum",
                actor="red-team",
                payload={"values": [1, 2]},
            )
        )
        self.assertEqual(result.status, "VERIFICATION_FAILED")
        self.assertFalse(result.verified)

    def test_vita_truthy_string_does_not_count_as_approval(self) -> None:
        engine = TrustedActionEngine()
        result = engine.execute(
            ActionRequest(action="production.write", actor="red-team"),
            approval="yes",
        )
        self.assertEqual(result.status, "WAITING_APPROVAL")
        self.assertFalse(result.verified)

    def test_vita_blank_actor_is_denied_and_audit_has_identity_fields(self) -> None:
        engine = TrustedActionEngine()
        result = engine.execute(
            ActionRequest(
                action="compute.sum",
                actor=" ",
                payload={"values": [1, 2]},
            ),
            expected={"sum": 3},
        )
        self.assertEqual(result.status, "DENIED")
        self.assertEqual(result.audit[0]["action"], "compute.sum")
        self.assertEqual(result.audit[0]["actor"], " ")

    def test_artifact_whitespace_source_ref_is_missing(self) -> None:
        record = ArtifactIngestionGate(
            policy=IngestionPolicy(require_archive=False, require_index_record=False)
        ).ingest(ArtifactInput(b"hello", "note.txt", "   "))
        self.assertEqual(record.verification_status, "UNVERIFIED")
        self.assertIn("source_ref", record.missing)
        self.assertFalse(record.trust_ready)

    def test_empty_artifact_cannot_be_promoted_by_semantic_verifier(self) -> None:
        def verifier(payload, metadata):
            return SpecializedVerification("VERIFIED")

        record = ArtifactIngestionGate(
            verifiers={"text": verifier},
            policy=IngestionPolicy(require_archive=False, require_index_record=False),
        ).ingest(ArtifactInput(b"", "empty.txt", "chat://empty"))
        self.assertEqual(record.verification_status, "UNVERIFIED")
        self.assertIn("payload", record.missing)
        self.assertFalse(record.trust_ready)

    def test_active_html_is_quarantined_even_if_semantically_verified(self) -> None:
        def verifier(payload, metadata):
            return SpecializedVerification("VERIFIED")

        record = ArtifactIngestionGate(
            verifiers={"text": verifier},
            policy=IngestionPolicy(require_archive=False, require_index_record=False),
        ).ingest(
            ArtifactInput(
                b"<script>alert(1)</script>",
                "note.html",
                "chat://html",
                "text/html",
            )
        )
        self.assertEqual(record.detected_media_type, "text/html")
        self.assertTrue(record.quarantined)
        self.assertFalse(record.trust_ready)

    def test_structural_archive_risk_ignores_executable_quarantine_toggle(self) -> None:
        out = BytesIO()
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("../escape.txt", "x")

        record = ArtifactIngestionGate(
            policy=IngestionPolicy(
                require_archive=False,
                require_index_record=False,
                quarantine_executables=False,
            )
        ).ingest(ArtifactInput(out.getvalue(), "bundle.zip", "chat://zip"))
        self.assertTrue(record.quarantined)
        self.assertEqual(record.verification_status, "UNVERIFIED")

    def test_false_scalar_cannot_impersonate_preserved_output(self) -> None:
        run = {
            "run_id": "r1",
            "prompt_id": "p1",
            "prompt_version": "1",
            "prompt_source": "test",
            "model": "test-model",
            "context_version": "c1",
            "test_suite": "suite",
            "claims": [],
            "raw_output_ref": False,
            "output_digest": 0,
        }
        self.assertIn("missing:output_artifact", validate_run_metadata(run))

    def test_false_scalar_cannot_enter_historical_backfill(self) -> None:
        result = backfill_eligibility(
            {
                "source_fidelity": "RAW",
                "source_verified": True,
                "raw_output_ref": False,
                "raw_excerpt": 0,
                "claims": [
                    {
                        "status": "VERIFIED",
                        "verifiable": True,
                        "evidence_refs": ["oracle:1"],
                    }
                ],
            }
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["reason"], "raw_output_not_preserved")

    def test_boolean_evidence_reference_is_not_coverage(self) -> None:
        summary = summarize_claims(
            [
                {
                    "status": "VERIFIED",
                    "verifiable": True,
                    "evidence_refs": [False, 1],
                }
            ]
        )
        self.assertEqual(summary.evidence_coverage, 0.0)

    def test_string_false_cannot_poison_reliability_flags(self) -> None:
        with self.assertRaisesRegex(ValueError, "verifiable must be boolean"):
            summarize_claims(
                [
                    {
                        "status": "VERIFIED",
                        "verifiable": "false",
                        "evidence_refs": ["oracle:1"],
                    }
                ]
            )
        with self.assertRaisesRegex(ValueError, "expected_unknown must be boolean"):
            summarize_claims(
                [
                    {
                        "status": "UNKNOWN",
                        "verifiable": False,
                        "expected_unknown": "false",
                    }
                ]
            )

    def test_session_owner_rejects_whitespace_and_type_coercion(self) -> None:
        for actor, owner in ((" ", " "), (1, "1"), ("1", 1)):
            with self.subTest(actor=actor, owner=owner):
                with self.assertRaises(PermissionError):
                    require_session_owner(actor_id=actor, owner_id=owner)

    def test_company_truthy_string_cannot_bypass_human_approval(self) -> None:
        registry = {
            "schema_version": "1",
            "company_id": "test",
            "name": "Test",
            "departments": [
                {
                    "id": "ops",
                    "name": "Operations",
                    "skills": [
                        {
                            "id": "publisher",
                            "status": "implemented",
                            "capabilities": ["publish_statement"],
                            "allowed_actions": ["publication"],
                            "tools": [],
                            "component_refs": [],
                        }
                    ],
                }
            ],
        }
        decision = decide_company_request(
            registry,
            skill_id="publisher",
            capability="publish_statement",
            action="publication",
            human_approved="yes",
        )
        self.assertEqual(decision.state, DECISION_NEEDS_APPROVAL)

    def test_vita2_rejects_impossible_claim_coordinates(self) -> None:
        with self.assertRaisesRegex(ValueError, "WGS84"):
            VerificationClaim(
                claimed_latitude=100.0,
                claimed_longitude=13.9,
                claimed_at="2026-09-29T00:00:00Z",
            )

    def test_vita2_whitespace_source_ref_is_not_provenance(self) -> None:
        claim = VerificationClaim(
            claimed_latitude=44.8,
            claimed_longitude=13.9,
            claimed_at="2026-09-29T00:00:00Z",
        )
        report = verify_claim(
            claim,
            [
                EvidenceItem(
                    "e1",
                    latitude=44.8,
                    longitude=13.9,
                    captured_at="2026-09-29T00:00:00Z",
                    sha256="a" * 64,
                    source_ref="   ",
                )
            ],
        )
        self.assertEqual(report.status, "INSUFFICIENT")
        self.assertIn("e1:source_ref", report.missing)

    def test_vita2_invalid_evidence_coordinate_is_not_supported(self) -> None:
        claim = VerificationClaim(
            claimed_latitude=44.8,
            claimed_longitude=13.9,
            claimed_at="2026-09-29T00:00:00Z",
        )
        report = verify_claim(
            claim,
            [
                EvidenceItem(
                    "e1",
                    latitude=float("nan"),
                    longitude=13.9,
                    captured_at="2026-09-29T00:00:00Z",
                    sha256="a" * 64,
                    source_ref="camera://1",
                )
            ],
        )
        self.assertEqual(report.status, "INSUFFICIENT")
        self.assertIn("e1:location_invalid", report.missing)

    def test_vita2_malformed_timestamp_and_duplicate_ids_fail_closed(self) -> None:
        claim = VerificationClaim(
            claimed_latitude=44.8,
            claimed_longitude=13.9,
            claimed_at="2026-09-29T00:00:00Z",
        )
        malformed = verify_claim(
            claim,
            [
                EvidenceItem(
                    "e1",
                    latitude=44.8,
                    longitude=13.9,
                    captured_at="not-a-time",
                    sha256="a" * 64,
                    source_ref="camera://1",
                )
            ],
        )
        self.assertEqual(malformed.status, "INSUFFICIENT")
        self.assertIn("e1:timestamp_invalid", malformed.missing)

        duplicate = verify_claim(
            claim,
            [
                EvidenceItem(
                    "same",
                    latitude=44.8,
                    longitude=13.9,
                    captured_at="2026-09-29T00:00:00Z",
                    sha256="a" * 64,
                    source_ref="camera://1",
                ),
                EvidenceItem(
                    "same",
                    latitude=44.8,
                    longitude=13.9,
                    captured_at="2026-09-29T00:00:00Z",
                    sha256="b" * 64,
                    source_ref="camera://2",
                ),
            ],
        )
        self.assertEqual(duplicate.status, "INSUFFICIENT")
        self.assertIn("duplicate_evidence_id:same", duplicate.missing)

    def test_github_signal_rejects_non_datetime_occurred_at(self) -> None:
        with self.assertRaisesRegex(GitHubSignalError, "ISO-8601"):
            RawGitHubEvent(
                transport="webhook",
                event_type="star",
                action="created",
                actor="user",
                object_type="repository",
                object_id="owner/repo",
                occurred_at="yesterday",
                payload={},
            )

        with self.assertRaisesRegex(GitHubSignalError, "timezone"):
            RawGitHubEvent(
                transport="webhook",
                event_type="star",
                action="created",
                actor="user",
                object_type="repository",
                object_id="owner/repo",
                occurred_at="2026-09-29T10:00:00",
                payload={},
            )

    def test_github_token_cannot_be_sent_to_custom_host_without_opt_in(self) -> None:
        with self.assertRaisesRegex(GitHubAdapterError, "explicit opt-in"):
            GitHubRestClient("secret-token", base_url="https://attacker.example")
        with self.assertRaises(GitHubAdapterError):
            GitHubRestClient("   ")

        client = GitHubRestClient(
            "secret-token",
            base_url="https://github.example/api/v3",
            allow_custom_base_url=True,
            transport=lambda method, url, headers: None,
        )
        self.assertEqual(client.base_url, "https://github.example/api/v3")

    def test_openai_key_cannot_be_sent_to_custom_host_without_opt_in(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit opt-in"):
            OpenAIResponsesExecutor(
                api_key="secret-key",
                base_url="https://attacker.example/v1",
            )
        with self.assertRaises(ValueError):
            OpenAIResponsesExecutor(api_key="   ")

        executor = OpenAIResponsesExecutor(
            api_key="secret-key",
            base_url="https://gateway.example/v1",
            allow_custom_base_url=True,
        )
        self.assertEqual(executor.base_url, "https://gateway.example/v1")

    def test_router_rejects_nonboolean_consequential_authority_flag(self) -> None:
        for value in ("", "false", 0, 1):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "consequential must be boolean"):
                    TaskProfile.from_dict(
                        {
                            "objective": "Production change",
                            "task_type": "implementation",
                            "consequential": value,
                        }
                    )

    def test_router_rejects_boolean_confidence_threshold(self) -> None:
        class NoopExecutor:
            def run(self, **kwargs):
                raise AssertionError("must not execute")

        with self.assertRaisesRegex(ValueError, "numeric"):
            ModelRouter(
                ModelCatalog("fast", "general", "high"),
                NoopExecutor(),
                evidence_confidence_threshold=True,
            )

    def test_vita2_nonstring_evidence_ids_fail_closed_without_crash(self) -> None:
        claim = VerificationClaim(
            claimed_latitude=44.8,
            claimed_longitude=13.9,
            claimed_at="2026-09-29T00:00:00Z",
        )
        report = verify_claim(
            claim,
            [
                EvidenceItem(
                    1,
                    latitude=44.8,
                    longitude=13.9,
                    captured_at="2026-09-29T00:00:00Z",
                    sha256="a" * 64,
                    source_ref="camera://1",
                ),
                EvidenceItem(
                    "valid",
                    latitude=44.8,
                    longitude=13.9,
                    captured_at="2026-09-29T00:00:00Z",
                    sha256="b" * 64,
                    source_ref="camera://2",
                ),
            ],
        )
        self.assertEqual(report.status, "INSUFFICIENT")
        self.assertTrue(any(item.startswith("invalid_evidence_id:") for item in report.missing))

    def test_artifact_gate_rejects_oversize_before_parsing(self) -> None:
        gate = ArtifactIngestionGate(
            policy=IngestionPolicy(
                require_archive=False,
                require_index_record=False,
                max_artifact_bytes=4,
            )
        )
        with self.assertRaisesRegex(ValueError, "max_artifact_bytes"):
            gate.ingest(ArtifactInput(b"12345", "oversize.txt", "chat://oversize"))

    def test_artifact_gate_rejects_nonbytes_payload(self) -> None:
        gate = ArtifactIngestionGate(
            policy=IngestionPolicy(require_archive=False, require_index_record=False)
        )
        with self.assertRaisesRegex(ValueError, "payload must be bytes"):
            gate.ingest(ArtifactInput("text-not-bytes", "bad.txt", "chat://bad"))

    def test_artifact_policy_rejects_truthy_and_falsey_nonbooleans(self) -> None:
        for field_name in (
            "require_source_ref",
            "require_archive",
            "require_index_record",
            "quarantine_executables",
            "require_verified_for_trust",
        ):
            for bad_value in ("", "false", 0, 1):
                with self.subTest(field_name=field_name, bad_value=bad_value):
                    kwargs = {field_name: bad_value}
                    with self.assertRaisesRegex(ValueError, "must be boolean"):
                        IngestionPolicy(**kwargs)

    def test_malformed_fault_inputs_fail_closed(self) -> None:
        bad_cases = [
            evaluate_provenance_graph({"evidence": []}),
            evaluate_temporal_validity({"as_of": "not-a-date"}),
            evaluate_claim_scope({"claim_scope": "", "evidence_scopes": []}),
            evaluate_entity_resolution({"left": None, "right": {}}),
            evaluate_negative_claim(
                {"source_available": True, "query_complete": True, "result_count": True}
            ),
            trace_contamination({"dependencies": [], "invalidated": []}),
        ]
        for result in bad_cases:
            with self.subTest(result=result):
                self.assertFalse(result.action_allowed)
                self.assertNotEqual(result.status, "PASS")


if __name__ == "__main__":
    unittest.main()
