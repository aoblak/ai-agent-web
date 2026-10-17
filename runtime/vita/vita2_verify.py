from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Iterable


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    latitude: float | None = None
    longitude: float | None = None
    captured_at: str | None = None
    sha256: str | None = None
    source_ref: str | None = None


@dataclass(frozen=True)
class VerificationClaim:
    claimed_latitude: float
    claimed_longitude: float
    claimed_at: str
    max_distance_m: float = 250.0
    max_time_skew_s: int = 300

    def __post_init__(self) -> None:
        if not _valid_coordinates(self.claimed_latitude, self.claimed_longitude):
            raise ValueError("claimed coordinates must be finite WGS84 latitude/longitude")
        if (
            isinstance(self.max_distance_m, bool)
            or not isinstance(self.max_distance_m, (int, float))
            or not isfinite(float(self.max_distance_m))
            or self.max_distance_m <= 0
        ):
            raise ValueError("max_distance_m must be a positive finite number")
        if (
            not isinstance(self.max_time_skew_s, int)
            or isinstance(self.max_time_skew_s, bool)
            or self.max_time_skew_s < 0
        ):
            raise ValueError("max_time_skew_s must be a non-negative integer")
        if not isinstance(self.claimed_at, str) or not self.claimed_at.strip():
            raise ValueError("claimed_at must be a non-empty timestamp")
        _parse_time(self.claimed_at)


@dataclass(frozen=True)
class VerificationReport:
    status: str
    confidence: float
    contradictions: tuple[str, ...]
    missing: tuple[str, ...]
    checks: tuple[dict[str, object], ...] = field(default_factory=tuple)


def _parse_time(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("timestamps must include timezone")
    return dt.astimezone(timezone.utc)


def _valid_coordinates(latitude: object, longitude: object) -> bool:
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
    ):
        return False
    lat = float(latitude)
    lon = float(longitude)
    return isfinite(lat) and isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000.0
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlambda / 2) ** 2
    return 2 * radius_m * asin(sqrt(a))


def _valid_sha256(value: str | None) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in value)


def verify_claim(claim: VerificationClaim, evidence: Iterable[EvidenceItem]) -> VerificationReport:
    items = list(evidence)
    if not items:
        return VerificationReport("INSUFFICIENT", 0.0, (), ("evidence",), ())

    claim_time = _parse_time(claim.claimed_at)
    contradictions: list[str] = []
    missing: list[str] = []
    checks: list[dict[str, object]] = []

    location_passes = 0
    time_passes = 0
    provenance_passes = 0

    invalid_ids = sorted(
        {
            repr(item.evidence_id)
            for item in items
            if not isinstance(item.evidence_id, str) or not item.evidence_id.strip()
        }
    )
    if invalid_ids:
        labels = tuple(f"invalid_evidence_id:{value}" for value in invalid_ids)
        return VerificationReport("INSUFFICIENT", 0.0, (), labels, ())

    evidence_ids = [item.evidence_id for item in items]
    duplicate_ids = sorted(
        {evidence_id for evidence_id in evidence_ids if evidence_ids.count(evidence_id) > 1}
    )
    if duplicate_ids:
        labels = tuple(f"duplicate_evidence_id:{value}" for value in duplicate_ids)
        return VerificationReport("INSUFFICIENT", 0.0, (), labels, ())

    for item in items:
        if item.latitude is None or item.longitude is None:
            missing.append(f"{item.evidence_id}:location")
        elif not _valid_coordinates(item.latitude, item.longitude):
            missing.append(f"{item.evidence_id}:location_invalid")
        else:
            distance = _haversine_m(
                claim.claimed_latitude,
                claim.claimed_longitude,
                item.latitude,
                item.longitude,
            )
            location_ok = distance <= claim.max_distance_m
            location_passes += int(location_ok)
            checks.append(
                {
                    "evidence_id": item.evidence_id,
                    "check": "location",
                    "ok": location_ok,
                    "distance_m": round(distance, 2),
                }
            )
            if not location_ok:
                contradictions.append(f"{item.evidence_id}:location")

        if item.captured_at is None:
            missing.append(f"{item.evidence_id}:timestamp")
        else:
            try:
                observed_time = _parse_time(item.captured_at)
            except (TypeError, ValueError):
                missing.append(f"{item.evidence_id}:timestamp_invalid")
            else:
                skew_s = abs((observed_time - claim_time).total_seconds())
                time_ok = skew_s <= claim.max_time_skew_s
                time_passes += int(time_ok)
                checks.append(
                    {
                        "evidence_id": item.evidence_id,
                        "check": "time",
                        "ok": time_ok,
                        "skew_s": round(skew_s, 3),
                    }
                )
                if not time_ok:
                    contradictions.append(f"{item.evidence_id}:timestamp")

        source_ref_ok = isinstance(item.source_ref, str) and bool(item.source_ref.strip())
        provenance_ok = _valid_sha256(item.sha256) and source_ref_ok
        provenance_passes += int(provenance_ok)
        checks.append(
            {
                "evidence_id": item.evidence_id,
                "check": "provenance",
                "ok": provenance_ok,
            }
        )
        if not _valid_sha256(item.sha256):
            missing.append(f"{item.evidence_id}:sha256")
        if not source_ref_ok:
            missing.append(f"{item.evidence_id}:source_ref")

    total_possible = len(items) * 3
    passed = location_passes + time_passes + provenance_passes
    confidence = round(passed / total_possible, 3)

    if contradictions:
        status = "CONTRADICTED"
    elif missing:
        status = "INSUFFICIENT"
    else:
        status = "SUPPORTED"

    return VerificationReport(
        status,
        confidence,
        tuple(sorted(set(contradictions))),
        tuple(sorted(set(missing))),
        tuple(checks),
    )
