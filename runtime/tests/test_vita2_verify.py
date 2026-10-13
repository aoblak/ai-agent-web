import unittest

from vita.vita2_verify import EvidenceItem, VerificationClaim, verify_claim


GOOD_HASH = "a" * 64


class VerifyClaimTest(unittest.TestCase):
    def setUp(self) -> None:
        self.claim = VerificationClaim(
            claimed_latitude=44.8211,
            claimed_longitude=13.9350,
            claimed_at="2026-09-09T07:00:00+02:00",
            max_distance_m=300,
            max_time_skew_s=300,
        )

    def test_supported_claim(self) -> None:
        report = verify_claim(
            self.claim,
            [
                EvidenceItem(
                    "img-1",
                    latitude=44.8212,
                    longitude=13.9351,
                    captured_at="2026-09-09T07:02:00+02:00",
                    sha256=GOOD_HASH,
                    source_ref="camera://device/1",
                )
            ],
        )
        self.assertEqual(report.status, "SUPPORTED")
        self.assertEqual(report.confidence, 1.0)
        self.assertFalse(report.contradictions)
        self.assertFalse(report.missing)

    def test_location_and_time_contradictions_are_explicit(self) -> None:
        report = verify_claim(
            self.claim,
            [
                EvidenceItem(
                    "img-2",
                    latitude=45.8150,
                    longitude=15.9819,
                    captured_at="2026-09-09T08:00:00+02:00",
                    sha256=GOOD_HASH,
                    source_ref="camera://device/1",
                )
            ],
        )
        self.assertEqual(report.status, "CONTRADICTED")
        self.assertIn("img-2:location", report.contradictions)
        self.assertIn("img-2:timestamp", report.contradictions)

    def test_missing_provenance_is_insufficient(self) -> None:
        report = verify_claim(
            self.claim,
            [
                EvidenceItem(
                    "img-3",
                    latitude=44.8211,
                    longitude=13.9350,
                    captured_at="2026-09-09T07:00:00+02:00",
                )
            ],
        )
        self.assertEqual(report.status, "INSUFFICIENT")
        self.assertIn("img-3:sha256", report.missing)
        self.assertIn("img-3:source_ref", report.missing)

    def test_no_evidence_is_insufficient(self) -> None:
        report = verify_claim(self.claim, [])
        self.assertEqual(report.status, "INSUFFICIENT")
        self.assertEqual(report.confidence, 0.0)
        self.assertIn("evidence", report.missing)


if __name__ == "__main__":
    unittest.main()
