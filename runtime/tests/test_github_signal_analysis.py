import json
import tempfile
import unittest
from pathlib import Path

from oos.github_signal_adapter import GitHubRestClient, HttpResponse
from oos.github_signal_analysis import (
    analyze,
    build_skill_candidates,
    detect_evidence_patterns,
    enrich_repositories,
    project_github_behavior_signals,
    project_pattern_inferences,
)
from oos.github_signal_ingester import GitHubSignalStore, RawGitHubEvent
from oos.signals import SignalType


def event(action, actor, object_type, object_id, when, payload=None):
    transport = "webhook" if action in {"STAR", "WATCH", "FORK"} else "poller"
    if action == "STAR":
        event_type, source_action = "star", "created"
    elif action == "WATCH":
        event_type, source_action = "watch", "started"
    elif action == "FORK":
        event_type, source_action = "fork", "created"
    elif action == "FOLLOW":
        event_type, source_action = "follow", "added"
    elif action in {"UNSTAR", "UNWATCH", "UNFOLLOW"}:
        event_type = {"UNSTAR": "star", "UNWATCH": "watch", "UNFOLLOW": "follow"}[action]
        source_action = "removed"
        transport = "poller"
    else:
        raise AssertionError(action)
    return RawGitHubEvent(
        transport=transport,
        event_type=event_type,
        action=source_action,
        actor=actor,
        object_type=object_type,
        object_id=object_id,
        occurred_at=when,
        payload=payload or {},
    )


class PatternTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = GitHubSignalStore(Path(self.temp.name) / "signals.sqlite")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, *args):
        return self.store.ingest(event(*args))

    def test_detects_evidence_chains_with_exact_signal_ids(self):
        follow = self.ingest(
            "FOLLOW", "me", "user", "owner", "2026-09-25T01:00:00Z"
        )
        star_a = self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        watch_a = self.ingest(
            "WATCH", "me", "repository", "owner/a", "2026-09-25T01:02:00Z"
        )
        fork_a = self.ingest(
            "FORK", "me", "repository", "owner/a", "2026-09-25T01:03:00Z"
        )
        star_b = self.ingest(
            "STAR", "me", "repository", "owner/b", "2026-09-25T01:04:00Z"
        )

        patterns = detect_evidence_patterns(self.store)
        by_key = {
            (pattern.pattern_type, pattern.object_id): pattern
            for pattern in patterns
        }

        self.assertEqual(
            {pattern.pattern_type for pattern in patterns},
            {
                "SUSTAINED_ATTENTION",
                "INTEREST_TO_EXPERIMENT",
                "PERSON_PROJECT_LINK",
                "OWNER_CLUSTER_INTEREST",
            },
        )
        self.assertEqual(
            set(
                by_key[
                    ("SUSTAINED_ATTENTION", "owner/a")
                ].evidence_signal_ids
            ),
            {star_a.signal_id, watch_a.signal_id},
        )
        self.assertEqual(
            set(
                by_key[
                    ("INTEREST_TO_EXPERIMENT", "owner/a")
                ].evidence_signal_ids
            ),
            {star_a.signal_id, fork_a.signal_id},
        )
        self.assertEqual(
            set(
                by_key[
                    ("PERSON_PROJECT_LINK", "owner/a")
                ].evidence_signal_ids
            ),
            {follow.signal_id, star_a.signal_id},
        )
        self.assertEqual(
            set(
                by_key[
                    ("PERSON_PROJECT_LINK", "owner/b")
                ].evidence_signal_ids
            ),
            {follow.signal_id, star_b.signal_id},
        )
        self.assertEqual(
            set(
                by_key[
                    ("OWNER_CLUSTER_INTEREST", "owner")
                ].evidence_signal_ids
            ),
            {star_a.signal_id, star_b.signal_id},
        )

    def test_analysis_is_idempotent(self):
        self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        self.ingest(
            "WATCH", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        first = analyze(self.store, detected_at="2026-09-25T02:00:00Z")
        second = analyze(self.store, detected_at="2026-09-25T03:00:00Z")
        self.assertEqual(first.persisted, 1)
        self.assertEqual(second.persisted, 0)
        self.assertEqual(len(self.store.patterns()), 1)

    def test_removal_signal_does_not_create_positive_pattern(self):
        self.ingest(
            "UNSTAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        self.ingest(
            "WATCH", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        self.assertEqual(detect_evidence_patterns(self.store), [])

    def test_removals_retract_active_patterns_in_event_time_order(self):
        for action, object_type, object_id in (
            ("STAR", "repository", "owner/a"),
            ("WATCH", "repository", "owner/a"),
            ("FOLLOW", "user", "owner"),
        ):
            with self.subTest(action=action):
                actor = "actor-" + action
                self.ingest("STAR", actor, "repository", "owner/a", "2026-09-25T01:00:00Z")
                self.ingest("WATCH", actor, "repository", "owner/a", "2026-09-25T01:00:01Z")
                self.ingest("FOLLOW", actor, "user", "owner", "2026-09-25T01:00:02Z")
                # A later-arriving old positive must not undo the newer removal.
                self.ingest("UN" + action, actor, object_type, object_id,
                            "2026-09-25T01:02:00Z")
                self.ingest(action, actor, object_type, object_id, "2026-09-25T01:01:00Z")
                types = {p.pattern_type for p in detect_evidence_patterns(self.store)
                         if p.actor == actor}
                if action in {"STAR", "WATCH"}:
                    self.assertNotIn("SUSTAINED_ATTENTION", types)
                if action in {"STAR", "FOLLOW"}:
                    self.assertNotIn("PERSON_PROJECT_LINK", types)

    def test_reactivated_star_uses_new_evidence_not_removed_star(self):
        old = self.ingest("STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z")
        self.ingest("UNSTAR", "me", "repository", "owner/a", "2026-09-25T01:01:00Z")
        watch = self.ingest("WATCH", "me", "repository", "owner/a", "2026-09-25T01:02:00Z")
        self.assertEqual(detect_evidence_patterns(self.store), [])
        new = self.ingest("STAR", "me", "repository", "owner/a", "2026-09-25T01:03:00Z")
        pattern = detect_evidence_patterns(self.store)[0]
        self.assertEqual(set(pattern.evidence_signal_ids), {new.signal_id, watch.signal_id})
        self.assertNotIn(old.signal_id, pattern.evidence_signal_ids)

    def test_unstar_removes_owner_cluster_interest(self):
        self.ingest("STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z")
        self.ingest("STAR", "me", "repository", "owner/b", "2026-09-25T01:01:00Z")
        self.assertIn("OWNER_CLUSTER_INTEREST", {p.pattern_type for p in detect_evidence_patterns(self.store)})
        self.ingest("UNSTAR", "me", "repository", "owner/b", "2026-09-25T01:02:00Z")
        self.assertEqual(detect_evidence_patterns(self.store), [])
        self.assertEqual(len(self.store.signal_rows()), 3)

    def test_patterns_have_no_numeric_score(self):
        self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        self.ingest(
            "WATCH", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        analyze(self.store, detected_at="2026-09-25T02:00:00Z")
        row = self.store.patterns()[0]
        self.assertNotIn("score", row)
        self.assertIn(row["claim_class"], {"SUPPORTED", "INFERRED"})


class SignalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = GitHubSignalStore(Path(self.temp.name) / "signals.sqlite")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def ingest(self, *args):
        return self.store.ingest(event(*args))

    def test_normalized_github_behavior_projects_as_human_behavior(self):
        star = self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        projected = project_github_behavior_signals(self.store)
        self.assertEqual(len(projected), 1)
        signal = projected[0]
        self.assertEqual(signal.signal_type, SignalType.HUMAN_BEHAVIOR_SIGNAL)
        self.assertEqual(signal.provenance_ref, f"github-signal:{star.signal_id}")
        self.assertEqual(signal.response["canonical_action"], "STAR")
        self.assertNotEqual(signal.signal_type, SignalType.EVIDENCE)

    def test_evidence_chain_projects_as_system_inference_not_evidence(self):
        star = self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        fork = self.ingest(
            "FORK", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        patterns = detect_evidence_patterns(self.store)
        inferred = project_pattern_inferences(
            patterns, detected_at="2026-09-25T02:00:00Z"
        )
        self.assertEqual(len(inferred), 1)
        signal = inferred[0]
        self.assertEqual(signal.signal_type, SignalType.SYSTEM_INFERENCE)
        self.assertNotEqual(signal.signal_type, SignalType.EVIDENCE)
        self.assertEqual(
            set(signal.response["evidence_signal_ids"]),
            {star.signal_id, fork.signal_id},
        )
        self.assertIn(str(star.signal_id), signal.provenance_ref)
        self.assertIn(str(fork.signal_id), signal.provenance_ref)

    def test_only_strong_pattern_yields_review_required_skill_candidate(self):
        star = self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        watch = self.ingest(
            "WATCH", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        weak_patterns = detect_evidence_patterns(self.store)
        self.assertEqual(build_skill_candidates(weak_patterns), [])

        fork = self.ingest(
            "FORK", "me", "repository", "owner/a", "2026-09-25T01:02:00Z"
        )
        patterns = detect_evidence_patterns(self.store)
        candidates = build_skill_candidates(patterns)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.review_state, "REVIEW_REQUIRED")
        self.assertEqual(candidate.source_pattern_type, "INTEREST_TO_EXPERIMENT")
        self.assertEqual(candidate.authority_home, "registry/company-os.json")
        self.assertEqual(
            set(candidate.evidence_signal_ids), {star.signal_id, fork.signal_id}
        )
        self.assertNotIn(watch.signal_id, candidate.evidence_signal_ids)
        self.assertNotIn(candidate.review_state, {"IMPLEMENTED", "PUBLISHED", "APPROVED"})

    def test_candidate_generation_does_not_mutate_company_or_skill_registry(self):
        company_path = Path(__file__).resolve().parents[1] / "registry" / "company-os.json"
        skills_path = Path(__file__).resolve().parents[1] / "registry" / "skills.json"
        company_before = company_path.read_bytes()
        skills_before = skills_path.read_bytes()

        self.ingest(
            "STAR", "me", "repository", "owner/a", "2026-09-25T01:00:00Z"
        )
        self.ingest(
            "FORK", "me", "repository", "owner/a", "2026-09-25T01:01:00Z"
        )
        candidates = build_skill_candidates(detect_evidence_patterns(self.store))
        self.assertEqual(len(candidates), 1)

        self.assertEqual(company_path.read_bytes(), company_before)
        self.assertEqual(skills_path.read_bytes(), skills_before)
        company = json.loads(company_before)
        self.assertTrue(company["architecture"]["human_final_authority"])
        self.assertTrue(company["architecture"]["fail_closed"])


class EnrichmentTests(unittest.TestCase):
    def test_repository_enrichment_is_get_only_and_license_is_metadata(self):
        calls = []

        def transport(method, url, headers):
            calls.append((method, url))
            payload = {
                "full_name": "owner/repo",
                "owner": {"login": "owner"},
                "private": False,
                "fork": False,
                "archived": False,
                "disabled": False,
                "visibility": "public",
                "language": "Python",
                "topics": ["agents", "memory"],
                "license": {"spdx_id": "MIT"},
                "stargazers_count": 10,
                "forks_count": 2,
                "open_issues_count": 1,
                "pushed_at": "2026-09-24T00:00:00Z",
                "updated_at": "2026-09-24T01:00:00Z",
            }
            return HttpResponse(200, {}, json.dumps(payload).encode())

        client = GitHubRestClient("token", transport=transport)
        with tempfile.TemporaryDirectory() as temp:
            store = GitHubSignalStore(Path(temp) / "signals.sqlite")
            try:
                count = enrich_repositories(
                    client,
                    store,
                    ["owner/repo"],
                    observed_at="2026-09-25T02:00:00Z",
                )
                self.assertEqual(count, 1)
                observation = store.latest_entity_observation(
                    "repository", "owner/repo"
                )
                self.assertEqual(observation["metadata"]["license_spdx"], "MIT")
                self.assertNotIn("license_compatible", observation["metadata"])
                self.assertTrue(all(method == "GET" for method, _ in calls))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
