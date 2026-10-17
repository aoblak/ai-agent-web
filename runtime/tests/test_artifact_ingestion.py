import unittest
from collections.abc import Mapping
from io import BytesIO
import zipfile

from oos.artifact_ingestion import (
    ArchiveReceipt,
    IndexReceipt,
    ArtifactIngestionGate,
    ArtifactInput,
    IngestionPolicy,
    SpecializedVerification,
)
from vita.vita2_verify import VerificationClaim


class FakeArchive:
    def __init__(self, *, bad_checksum=False):
        self.bad_checksum = bad_checksum
        self.seen = []

    def store(
        self,
        *,
        artifact_id,
        payload,
        sha256_hex,
        media_type,
        original_name,
        quarantine,
    ):
        self.seen.append(
            {
                "artifact_id": artifact_id,
                "size": len(payload),
                "media_type": media_type,
                "name": original_name,
                "quarantine": quarantine,
            }
        )
        return ArchiveReceipt(
            uri=f"s3://cold-archive/{sha256_hex}",
            sha256=("0" * 64 if self.bad_checksum else sha256_hex),
            stored_at="2026-09-25T22:00:00Z",
        )


class FakeIndex:
    def __init__(self, *, bad_checksum=False):
        self.bad_checksum = bad_checksum
        self.seen = []

    def append(self, *, artifact_id, record, record_sha256):
        self.seen.append(
            {
                "artifact_id": artifact_id,
                "record": dict(record),
                "record_sha256": record_sha256,
            }
        )
        return IndexReceipt(
            uri=f"index://artifacts/{artifact_id}",
            record_sha256=("0" * 64 if self.bad_checksum else record_sha256),
            stored_at="2026-09-25T22:00:00Z",
        )


def make_docx():
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
    return out.getvalue()


def make_suspicious_zip():
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../escape.txt", "x")
        zf.writestr("payload.exe", b"MZ")
    return out.getvalue()


class ArtifactIngestionGateTest(unittest.TestCase):
    def test_failed_mapping_check_cannot_hide_behind_custom_get(self):
        class MisleadingCheck(dict):
            def get(self, key, default=None):
                return True if key == "ok" else super().get(key, default)

        for direction in ("IN", "OUT"):
            for strict in (True, False):
                with self.subTest(direction=direction, strict=strict):
                    record = ArtifactIngestionGate(
                        archive_sink=FakeArchive(), index_sink=FakeIndex(),
                        policy=IngestionPolicy(require_verified_for_trust=strict),
                        verifiers={"text": lambda payload, metadata: SpecializedVerification(
                            "VERIFIED", checks=(MisleadingCheck(check="signature", ok=False),),
                        )},
                    ).ingest(ArtifactInput(
                        b"hello", "note.txt", "fixture://mapping", direction=direction,
                    ))
                    self.assertFalse(record.trust_ready)
                    self.assertEqual(record.verification_status, "CONTRADICTED")
                    self.assertIs(record.checks[-1]["ok"], False)
                    self.assertEqual(record.archive_status, "STORED")
                    self.assertEqual(record.index_status, "STORED")

    def test_unverified_specialized_status_never_degrades_to_partial(self):
        for direction in ("IN", "OUT"):
            for strict in (True, False):
                with self.subTest(direction=direction, strict=strict):
                    record = ArtifactIngestionGate(
                        archive_sink=FakeArchive(), index_sink=FakeIndex(),
                        policy=IngestionPolicy(require_verified_for_trust=strict),
                        verifiers={"text": lambda payload, metadata: SpecializedVerification(
                            "UNVERIFIED", checks=({"check": "format", "ok": True},),
                        )},
                    ).ingest(ArtifactInput(
                        b"hello", "note.txt", "fixture://unverified", direction=direction,
                    ))
                    self.assertEqual(record.verification_status, "UNVERIFIED")
                    self.assertFalse(record.trust_ready)
                    self.assertEqual(record.archive_status, "STORED")
                    self.assertEqual(record.index_status, "STORED")

    def test_specialized_check_snapshot_survives_adapter_mutation(self):
        check = {"check": "signature", "ok": True}

        class MutatingArchive(FakeArchive):
            def store(self, **kwargs):
                check["ok"] = False
                return super().store(**kwargs)

        record = ArtifactIngestionGate(
            archive_sink=MutatingArchive(), index_sink=FakeIndex(),
            verifiers={"text": lambda payload, metadata: SpecializedVerification(
                "VERIFIED", checks=(check,),
            )},
        ).ingest(ArtifactInput(b"hello", "note.txt", "fixture://snapshot"))
        self.assertIs(check["ok"], False)
        self.assertIs(record.checks[-1]["ok"], True)
        self.assertIsNot(record.checks[-1], check)
        self.assertEqual(record.verification_status, "VERIFIED")
        self.assertTrue(record.trust_ready)

    def test_unreadable_check_preserves_receipts_and_redacts_exception(self):
        class UnreadableCheck(Mapping):
            def __len__(self):
                return 1

            def __iter__(self):
                raise RuntimeError("fixture-secret-must-not-enter-audit")

            def __getitem__(self, key):
                raise KeyError(key)

        record = ArtifactIngestionGate(
            archive_sink=FakeArchive(), index_sink=FakeIndex(),
            policy=IngestionPolicy(require_verified_for_trust=False),
            verifiers={"text": lambda payload, metadata: SpecializedVerification(
                "VERIFIED", checks=(UnreadableCheck(),),
            )},
        ).ingest(ArtifactInput(b"hello", "note.txt", "fixture://unreadable"))
        self.assertEqual(record.verification_status, "UNVERIFIED")
        self.assertFalse(record.trust_ready)
        self.assertEqual(record.archive_status, "STORED")
        self.assertEqual(record.index_status, "STORED")
        self.assertNotIn("fixture-secret-must-not-enter-audit", repr(record))

    def test_failed_specialized_check_blocks_both_directions(self):
        for direction in ("IN", "OUT"):
            with self.subTest(direction=direction):
                gate = ArtifactIngestionGate(
                    archive_sink=FakeArchive(),
                    index_sink=FakeIndex(),
                    verifiers={"text": lambda payload, metadata: SpecializedVerification(
                        "VERIFIED", checks=({"check": "semantic.canary", "ok": False},),
                    )},
                )
                record = gate.ingest(ArtifactInput(
                    b"hello", "note.txt", "fixture://canary", direction=direction,
                ))
                self.assertFalse(record.trust_ready)
                self.assertEqual(record.verification_status, "CONTRADICTED")
                self.assertIn("text:specialized_verifier_failed_check", record.contradictions)

    def test_relaxed_verification_policy_cannot_override_failed_check(self):
        gate = ArtifactIngestionGate(
            policy=IngestionPolicy(
                require_archive=False, require_index_record=False,
                require_verified_for_trust=False,
            ),
            verifiers={"text": lambda payload, metadata: SpecializedVerification(
                "VERIFIED", checks=({"check": "semantic.canary", "ok": False},),
            )},
        )
        self.assertFalse(gate.ingest(ArtifactInput(
            b"hello", "note.txt", "fixture://canary",
        )).trust_ready)

    def test_verifier_exception_is_redacted_and_preserves_archive_record(self):
        def unavailable(payload, metadata):
            raise RuntimeError("fixture-secret-must-not-enter-audit")

        archive, index = FakeArchive(), FakeIndex()
        record = ArtifactIngestionGate(
            archive_sink=archive, index_sink=index, verifiers={"text": unavailable},
        ).ingest(ArtifactInput(b"hello", "note.txt", "fixture://canary"))
        self.assertEqual(record.verification_status, "UNVERIFIED")
        self.assertFalse(record.trust_ready)
        self.assertEqual(record.archive_status, "STORED")
        self.assertEqual(record.index_status, "STORED")
        self.assertIn("text:specialized_verifier_unavailable", record.missing)
        self.assertNotIn("fixture-secret-must-not-enter-audit", repr(record))
        self.assertTrue(any(event.get("reason") == "RuntimeError" for event in record.audit))

    def test_invalid_specialized_results_fail_closed(self):
        for result in (
            None,
            SpecializedVerification("PASS"),
            SpecializedVerification("VERIFIED", checks=({"check": "bad", "ok": "false"},)),
            SpecializedVerification("VERIFIED", checks=({"check": "bad", "ok": 0},)),
            SpecializedVerification("VERIFIED", checks=("not-a-check",)),
            SpecializedVerification("VERIFIED", contradictions=([],)),
            SpecializedVerification("VERIFIED", missing=([],)),
        ):
            with self.subTest(result=result):
                gate = ArtifactIngestionGate(
                    archive_sink=FakeArchive(), index_sink=FakeIndex(),
                    verifiers={"text": lambda payload, metadata: result},
                )
                record = gate.ingest(ArtifactInput(b"hello", "note.txt", "fixture://canary"))
                self.assertFalse(record.trust_ready)
                self.assertEqual(record.verification_status, "UNVERIFIED")
                self.assertIn("text:specialized_verifier_invalid_result", record.missing)

    def test_positive_specialized_checks_preserve_trust_and_receipts(self):
        record = ArtifactIngestionGate(
            archive_sink=FakeArchive(), index_sink=FakeIndex(),
            verifiers={"text": lambda payload, metadata: SpecializedVerification(
                "VERIFIED", checks=({"check": "semantic.canary", "ok": True},),
            )},
        ).ingest(ArtifactInput(b"hello", "note.txt", "fixture://canary"))
        self.assertTrue(record.trust_ready)
        self.assertEqual(record.verification_status, "VERIFIED")
        self.assertEqual(record.archive_status, "STORED")
        self.assertEqual(record.index_status, "STORED")

    def test_text_is_partial_without_semantic_verifier_but_archived(self):
        archive = FakeArchive()
        record = ArtifactIngestionGate(archive_sink=archive, index_sink=FakeIndex()).ingest(
            ArtifactInput(b"hello", "note.txt", "chat://upload/1", "text/plain")
        )
        self.assertEqual(record.detected_media_type, "text/plain")
        self.assertEqual(record.verification_status, "PARTIAL")
        self.assertEqual(record.archive_status, "STORED")
        self.assertFalse(record.trust_ready)
        self.assertEqual(len(archive.seen), 1)

    def test_active_markup_is_quarantined_beyond_leading_nodes(self):
        for text in ("<!--header--><script>alert(1)</script>",
                     "\ufeff<script>alert(1)</script>",
                     '<?xml version="1.0"?><svg onload="alert(1)"/>',
                     '<meta charset="utf-8"><script>alert(1)</script>',
                     'ordinary note\n<img src="x" onerror="alert(1)">',
                     '<!--header--><script/src="x"></script>'):
            with self.subTest(text=text):
                archive = FakeArchive()
                def approve(payload, metadata):
                    return SpecializedVerification("VERIFIED", checks=({"check": "text", "ok": True},))
                gate = ArtifactIngestionGate(archive_sink=archive, index_sink=FakeIndex(),
                                             verifiers={"text": approve, "image": approve})
                record = gate.ingest(ArtifactInput(text.encode("utf-8"), "note.txt", "fixture://active"))
                self.assertIn(record.detected_media_type, {"text/html", "image/svg+xml"})
                self.assertTrue(record.quarantined)
                self.assertFalse(record.trust_ready)
                self.assertTrue(archive.seen[0]["quarantine"])

    def test_registered_semantic_verifier_can_make_artifact_trust_ready(self):
        archive = FakeArchive()

        def verifier(payload, metadata):
            return SpecializedVerification(
                "VERIFIED",
                checks=({"check": "semantic.fixture", "ok": payload == b"hello"},),
            )

        gate = ArtifactIngestionGate(
            archive_sink=archive,
            index_sink=FakeIndex(),
            verifiers={"text": verifier},
        )
        record = gate.ingest(ArtifactInput(b"hello", "note.txt", "chat://upload/2"))
        self.assertEqual(record.verification_status, "VERIFIED")
        self.assertTrue(record.trust_ready)

    def test_all_invoked_verifiers_must_pass_for_verified_status(self):
        archive = FakeArchive()

        def verifier(payload, metadata):
            return SpecializedVerification("PARTIAL")

        claim = VerificationClaim(
            claimed_latitude=44.8211,
            claimed_longitude=13.9350,
            claimed_at="2026-09-09T07:00:00+02:00",
            max_distance_m=300,
            max_time_skew_s=300,
        )
        record = ArtifactIngestionGate(
            archive_sink=archive,
            index_sink=FakeIndex(),
            verifiers={"image": verifier},
        ).ingest(
            ArtifactInput(
                b"\xff\xd8\xff" + b"x" * 20,
                "capture.jpg",
                "camera://device/2",
                "image/jpeg",
                latitude=44.8212,
                longitude=13.9351,
                captured_at="2026-09-09T07:02:00+02:00",
            ),
            claim=claim,
        )
        self.assertEqual(record.verification_status, "PARTIAL")
        self.assertFalse(record.trust_ready)

    def test_archive_required_is_pending_without_sink(self):
        record = ArtifactIngestionGate().ingest(
            ArtifactInput(b"hello", "note.txt", "chat://upload/3")
        )
        self.assertEqual(record.archive_status, "PENDING")
        self.assertEqual(record.index_status, "PENDING")
        self.assertFalse(record.trust_ready)

    def test_image_and_pdf_signatures_are_detected(self):
        gate = ArtifactIngestionGate(policy=IngestionPolicy(require_archive=False))
        image = gate.ingest(
            ArtifactInput(b"\xff\xd8\xff" + b"x" * 20, "photo.jpg", "chat://upload/4")
        )
        pdf = gate.ingest(
            ArtifactInput(b"%PDF-1.7\nbody", "document.pdf", "chat://upload/5")
        )
        self.assertEqual(image.detected_media_type, "image/jpeg")
        self.assertEqual(image.kind, "image")
        self.assertEqual(pdf.detected_media_type, "application/pdf")
        self.assertEqual(pdf.kind, "document")

    def test_office_zip_is_classified_without_extracting_to_disk(self):
        record = ArtifactIngestionGate(
            policy=IngestionPolicy(require_archive=False)
        ).ingest(
            ArtifactInput(
                make_docx(),
                "report.docx",
                "chat://upload/6",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        )
        self.assertIn("wordprocessingml.document", record.detected_media_type)
        self.assertEqual(record.kind, "document")
        self.assertFalse(record.quarantined)

    def test_disguised_executable_is_quarantined_and_contradicted(self):
        record = ArtifactIngestionGate(
            policy=IngestionPolicy(require_archive=False)
        ).ingest(
            ArtifactInput(
                b"MZ" + b"\x00" * 32,
                "holiday.jpg",
                "chat://upload/7",
                "image/jpeg",
            )
        )
        self.assertTrue(record.quarantined)
        self.assertEqual(record.verification_status, "CONTRADICTED")
        self.assertIn("media_type:declared_vs_detected", record.contradictions)
        self.assertIn("filename:extension_vs_signature", record.contradictions)

    def test_suspicious_archive_is_quarantined(self):
        archive = FakeArchive()
        record = ArtifactIngestionGate(archive_sink=archive, index_sink=FakeIndex()).ingest(
            ArtifactInput(make_suspicious_zip(), "bundle.zip", "chat://upload/8")
        )
        self.assertTrue(record.quarantined)
        self.assertEqual(record.verification_status, "UNVERIFIED")
        self.assertEqual(record.archive_status, "STORED")
        self.assertTrue(archive.seen[0]["quarantine"])

    def test_archive_receipt_checksum_must_match(self):
        record = ArtifactIngestionGate(
            archive_sink=FakeArchive(bad_checksum=True),
            index_sink=FakeIndex(),
        ).ingest(
            ArtifactInput(b"hello", "note.txt", "chat://upload/9")
        )
        self.assertEqual(record.archive_status, "FAILED")
        self.assertFalse(record.trust_ready)

    def test_vita2_claim_dispatch_can_verify_location_time_and_provenance(self):
        archive = FakeArchive()
        claim = VerificationClaim(
            claimed_latitude=44.8211,
            claimed_longitude=13.9350,
            claimed_at="2026-09-09T07:00:00+02:00",
            max_distance_m=300,
            max_time_skew_s=300,
        )
        record = ArtifactIngestionGate(archive_sink=archive, index_sink=FakeIndex()).ingest(
            ArtifactInput(
                b"\xff\xd8\xff" + b"x" * 20,
                "capture.jpg",
                "camera://device/1",
                "image/jpeg",
                latitude=44.8212,
                longitude=13.9351,
                captured_at="2026-09-09T07:02:00+02:00",
            ),
            claim=claim,
        )
        self.assertEqual(record.verification_status, "VERIFIED")
        self.assertEqual(record.archive_status, "STORED")
        self.assertTrue(record.trust_ready)

    def test_remote_index_receipt_checksum_must_match(self):
        record = ArtifactIngestionGate(
            archive_sink=FakeArchive(),
            index_sink=FakeIndex(bad_checksum=True),
            policy=IngestionPolicy(require_verified_for_trust=False),
        ).ingest(
            ArtifactInput(b"hello", "note.txt", "chat://upload/index-bad")
        )
        self.assertEqual(record.archive_status, "STORED")
        self.assertEqual(record.index_status, "FAILED")
        self.assertFalse(record.trust_ready)

    def test_index_manifest_points_to_archive_without_raw_payload(self):
        archive = FakeArchive()
        index = FakeIndex()
        record = ArtifactIngestionGate(
            archive_sink=archive,
            index_sink=index,
            policy=IngestionPolicy(require_verified_for_trust=False),
        ).ingest(
            ArtifactInput(b"hello", "note.txt", "chat://upload/index-ok")
        )
        self.assertEqual(record.index_status, "STORED")
        self.assertTrue(record.trust_ready)
        manifest = index.seen[0]["record"]
        self.assertEqual(manifest["archive_uri"], record.archive_uri)
        self.assertEqual(manifest["sha256"], record.sha256)
        self.assertNotIn("payload", manifest)

    def test_unknown_binary_is_not_silently_verified(self):
        record = ArtifactIngestionGate(
            policy=IngestionPolicy(require_archive=False)
        ).ingest(
            ArtifactInput(b"\x00\x01\x02\x03", "blob.bin", "chat://upload/10")
        )
        self.assertEqual(record.detected_media_type, "application/octet-stream")
        self.assertEqual(record.verification_status, "PARTIAL")
        self.assertFalse(record.trust_ready)

    def test_missing_provenance_is_unverified(self):
        record = ArtifactIngestionGate(
            policy=IngestionPolicy(require_archive=False)
        ).ingest(ArtifactInput(b"hello", "note.txt", None))
        self.assertEqual(record.verification_status, "UNVERIFIED")
        self.assertIn("source_ref", record.missing)


    def test_inbound_direction_is_explicit_in_record_and_index(self):
        index = FakeIndex()
        record = ArtifactIngestionGate(
            archive_sink=FakeArchive(),
            index_sink=index,
            policy=IngestionPolicy(require_verified_for_trust=False),
        ).ingest(ArtifactInput(b"source", "scan.jpg", "chat://upload/source", direction="IN"))
        self.assertEqual(record.direction, "IN")
        self.assertEqual(record.parent_artifact_ids, ())
        self.assertEqual(index.seen[0]["record"]["direction"], "IN")

    def test_outbound_generated_artifact_records_lineage(self):
        index = FakeIndex()
        parent = "sha256:" + ("a" * 64)
        record = ArtifactIngestionGate(
            archive_sink=FakeArchive(),
            index_sink=index,
            policy=IngestionPolicy(require_verified_for_trust=False),
        ).ingest(
            ArtifactInput(
                b"generated document",
                "contract.txt",
                "chat://generated/contract",
                direction="OUT",
                parent_artifact_ids=(parent,),
            )
        )
        self.assertEqual(record.direction, "OUT")
        self.assertEqual(record.parent_artifact_ids, (parent,))
        manifest = index.seen[0]["record"]
        self.assertEqual(manifest["direction"], "OUT")
        self.assertEqual(manifest["parent_artifact_ids"], [parent])
        self.assertNotIn("payload", manifest)

    def test_direction_is_fail_closed(self):
        with self.assertRaises(ValueError):
            ArtifactIngestionGate().ingest(
                ArtifactInput(b"x", "x.txt", "chat://x", direction="SIDEWAYS")
            )

    def test_outbound_requires_provenance(self):
        with self.assertRaises(ValueError):
            ArtifactIngestionGate().ingest(
                ArtifactInput(b"x", "x.txt", None, direction="OUT")
            )


if __name__ == "__main__":
    unittest.main()
