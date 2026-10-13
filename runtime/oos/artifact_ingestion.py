from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import PurePath
from typing import Any, Callable, Mapping, Protocol
import json
import mimetypes
import re
import zipfile

from vita.vita2_verify import EvidenceItem, VerificationClaim, verify_claim


_GENERIC_MEDIA_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
_EXECUTABLE_MEDIA_TYPES = {
    "application/vnd.microsoft.portable-executable",
    "application/x-elf",
    "application/x-mach-binary",
}
_EXECUTABLE_EXTENSIONS = {
    ".exe", ".dll", ".com", ".scr", ".msi", ".elf", ".so", ".dylib", ".app", ".apk",
}
_ACTIVE_ARCHIVE_EXTENSIONS = {
    ".exe", ".dll", ".com", ".scr", ".msi", ".elf", ".so", ".dylib", ".apk", ".jar",
}
_OFFICE_MACRO_EXTENSIONS = {".docm", ".xlsm", ".pptm"}
_ACTIVE_TEXT_MEDIA_TYPES = {"text/html", "application/xhtml+xml", "image/svg+xml"}


@dataclass(frozen=True)
class ArtifactInput:
    payload: bytes
    original_name: str
    source_ref: str | None
    declared_media_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    captured_at: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    direction: str = "IN"
    parent_artifact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpecializedVerification:
    status: str
    checks: tuple[dict[str, Any], ...] = ()
    contradictions: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchiveReceipt:
    uri: str
    sha256: str
    stored_at: str


@dataclass(frozen=True)
class IndexReceipt:
    uri: str
    record_sha256: str
    stored_at: str


class ArchiveSink(Protocol):
    """Immutable, idempotent content-addressed remote archive boundary."""

    def store(
        self,
        *,
        artifact_id: str,
        payload: bytes,
        sha256_hex: str,
        media_type: str,
        original_name: str,
        quarantine: bool,
    ) -> ArchiveReceipt: ...


class IndexSink(Protocol):
    """Compact remote L2 pointer/index boundary; never receives raw payload bytes."""

    def append(
        self,
        *,
        artifact_id: str,
        record: Mapping[str, Any],
        record_sha256: str,
    ) -> IndexReceipt: ...


ArtifactVerifier = Callable[[bytes, Mapping[str, Any]], SpecializedVerification]


def _normalize_specialized_result(result: Any) -> SpecializedVerification | None:
    """Validate one detached snapshot before adapter data can influence trust."""
    if not isinstance(result, SpecializedVerification):
        return None
    status, checks, contradictions, missing = (
        result.status, result.checks, result.contradictions, result.missing,
    )
    if not (
        isinstance(status, str)
        and status in {"VERIFIED", "PARTIAL", "UNVERIFIED", "CONTRADICTED"}
        and isinstance(checks, tuple)
        and all(isinstance(check, Mapping) for check in checks)
        and isinstance(contradictions, tuple)
        and all(isinstance(item, str) for item in contradictions)
        and isinstance(missing, tuple)
        and all(isinstance(item, str) for item in missing)
    ):
        return None
    # Read adapter mappings once; custom get() behavior and later adapter
    # mutations must not disagree with the checks used for the trust decision.
    snapshot = tuple(dict(check) for check in checks)
    if any("ok" in check and not isinstance(check["ok"], bool) for check in snapshot):
        return None
    return SpecializedVerification(status, snapshot, contradictions, missing)


@dataclass(frozen=True)
class IngestionPolicy:
    require_source_ref: bool = True
    require_archive: bool = True
    require_index_record: bool = True
    quarantine_executables: bool = True
    require_verified_for_trust: bool = True
    max_artifact_bytes: int = 100 * 1024 * 1024

    def __post_init__(self) -> None:
        for field_name in (
            "require_source_ref",
            "require_archive",
            "require_index_record",
            "quarantine_executables",
            "require_verified_for_trust",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be boolean")
        if (
            not isinstance(self.max_artifact_bytes, int)
            or isinstance(self.max_artifact_bytes, bool)
            or self.max_artifact_bytes <= 0
        ):
            raise ValueError("max_artifact_bytes must be a positive integer")


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    direction: str
    parent_artifact_ids: tuple[str, ...]
    sha256: str
    byte_size: int
    original_name: str
    declared_media_type: str | None
    detected_media_type: str
    kind: str
    verification_status: str
    archive_status: str
    archive_uri: str | None
    archive_sha256: str | None
    index_status: str
    index_uri: str | None
    index_record_sha256: str | None
    quarantined: bool
    trust_ready: bool
    contradictions: tuple[str, ...]
    missing: tuple[str, ...]
    checks: tuple[dict[str, Any], ...]
    audit: tuple[dict[str, Any], ...]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_name(name: str) -> str:
    base = PurePath(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]+", "_", base).strip()
    return base[:255] or "unnamed"


def _normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.split(";", 1)[0].strip().lower()
    aliases = {
        "image/jpg": "image/jpeg",
        "audio/x-wav": "audio/wav",
        "application/x-zip-compressed": "application/zip",
    }
    return aliases.get(normalized, normalized)


def _zip_profile(payload: bytes) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...]]:
    risks: list[str] = []
    checks: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            infos = zf.infolist()
            checks.append({"check": "archive.member_count", "value": len(infos)})
            if len(infos) > 10000:
                risks.append("archive:excessive_member_count")
                infos = infos[:10000]

            names = {info.filename for info in infos}
            lowered = {name.lower() for name in names}

            for info in infos:
                parts = PurePath(info.filename.replace("\\", "/")).parts
                if info.filename.startswith(("/", "\\")) or ".." in parts:
                    risks.append("archive:path_traversal")
                if info.flag_bits & 0x1:
                    risks.append("archive:encrypted_member")
                suffix = PurePath(info.filename).suffix.lower()
                if suffix in _ACTIVE_ARCHIVE_EXTENSIONS:
                    risks.append("archive:active_member")
                if info.file_size > 1_073_741_824:
                    risks.append("archive:member_over_1gb")
                if info.compress_size and info.file_size / info.compress_size > 1000:
                    risks.append("archive:extreme_compression_ratio")

            if any(name.endswith("vbaproject.bin") for name in lowered):
                risks.append("archive:office_macro")

            if "[content_types].xml" in lowered:
                if any(name.startswith("word/") for name in lowered):
                    return (
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        tuple(sorted(set(risks))),
                        tuple(checks),
                    )
                if any(name.startswith("xl/") for name in lowered):
                    return (
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        tuple(sorted(set(risks))),
                        tuple(checks),
                    )
                if any(name.startswith("ppt/") for name in lowered):
                    return (
                        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        tuple(sorted(set(risks))),
                        tuple(checks),
                    )
    except (zipfile.BadZipFile, OSError, ValueError):
        return "application/zip", ("archive:parse_failed",), tuple(checks)

    return "application/zip", tuple(sorted(set(risks))), tuple(checks)


def _sniff(payload: bytes) -> tuple[str, tuple[str, ...], tuple[dict[str, Any], ...]]:
    head = payload[:32]
    if head.startswith(b"%PDF-"):
        return "application/pdf", (), ()
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", (), ()
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", (), ()
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", (), ()
    if head.startswith(b"PK\x03\x04"):
        return _zip_profile(payload)
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip", (), ()
    if head.startswith(b"Rar!\x1a\x07"):
        return "application/vnd.rar", (), ()
    if head.startswith(b"7z\xbc\xaf'\x1c"):
        return "application/x-7z-compressed", (), ()
    if head.startswith(b"RIFF") and payload[8:12] == b"WAVE":
        return "audio/wav", (), ()
    if len(payload) >= 12 and payload[4:8] == b"ftyp":
        return "video/mp4", (), ()
    if head.startswith(b"OggS"):
        return "application/ogg", (), ()
    if head.startswith(b"ID3") or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg", (), ()
    if head.startswith(b"MZ"):
        return "application/vnd.microsoft.portable-executable", (), ()
    if head.startswith(b"\x7fELF"):
        return "application/x-elf", (), ()
    if head[:4] in {
        b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
    }:
        return "application/x-mach-binary", (), ()

    try:
        text = payload.decode("utf-8")
        if not text:
            return "text/plain", (), ()
        stripped = text.lstrip().lower()
        if (
            stripped.startswith("<!doctype html")
            or stripped.startswith("<html")
            or stripped.startswith("<script")
        ):
            return "text/html", (), ()
        if stripped.startswith("<svg"):
            return "image/svg+xml", (), ()
        printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
        if printable / max(len(text), 1) >= 0.95:
            return "text/plain", (), ()
    except UnicodeDecodeError:
        pass

    return "application/octet-stream", (), ()


def _kind_for(media_type: str) -> str:
    if media_type.startswith("image/"):
        return "image"
    if media_type == "application/pdf":
        return "document"
    if "wordprocessingml" in media_type:
        return "document"
    if "spreadsheetml" in media_type:
        return "spreadsheet"
    if "presentationml" in media_type:
        return "presentation"
    if media_type.startswith("audio/"):
        return "audio"
    if media_type.startswith("video/"):
        return "video"
    if media_type.startswith("text/"):
        return "text"
    if media_type in {
        "application/zip", "application/gzip", "application/vnd.rar", "application/x-7z-compressed"
    }:
        return "archive"
    if media_type in _EXECUTABLE_MEDIA_TYPES:
        return "executable"
    return "binary"


def _compatible(expected: str | None, detected: str) -> bool:
    expected = _normalize_media_type(expected)
    detected = _normalize_media_type(detected) or detected
    if expected is None or expected in _GENERIC_MEDIA_TYPES:
        return True
    if expected == detected:
        return True
    if expected == "application/zip" and detected.startswith("application/vnd.openxmlformats-officedocument."):
        return True
    if expected.startswith("text/") and detected == "text/plain":
        return True
    return False


class ArtifactIngestionGate:
    """Fail-closed intake for untrusted artifacts.

    The gate never executes payloads and never writes raw bytes to Git. Callers may
    provide a remote ArchiveSink; only its immutable receipt is retained here.
    """

    def __init__(
        self,
        *,
        archive_sink: ArchiveSink | None = None,
        index_sink: IndexSink | None = None,
        verifiers: Mapping[str, ArtifactVerifier] | None = None,
        policy: IngestionPolicy | None = None,
    ) -> None:
        self.archive_sink = archive_sink
        self.index_sink = index_sink
        self.verifiers = dict(verifiers or {})
        self.policy = policy or IngestionPolicy()

    def ingest(
        self,
        artifact: ArtifactInput,
        *,
        claim: VerificationClaim | None = None,
    ) -> ArtifactRecord:
        payload = artifact.payload
        if not isinstance(payload, bytes):
            raise ValueError("artifact payload must be bytes")
        if len(payload) > self.policy.max_artifact_bytes:
            raise ValueError("artifact exceeds max_artifact_bytes")
        direction = artifact.direction.strip().upper()
        if direction not in {"IN", "OUT"}:
            raise ValueError("artifact.direction must be IN or OUT")
        parent_artifact_ids = tuple(dict.fromkeys(artifact.parent_artifact_ids))
        if direction == "OUT" and not artifact.source_ref:
            raise ValueError("OUT artifacts require source_ref provenance")
        digest = sha256(payload).hexdigest()
        artifact_id = f"sha256:{digest}"
        name = _safe_name(artifact.original_name)
        declared = _normalize_media_type(artifact.declared_media_type)
        detected, risks, sniff_checks = _sniff(payload)
        kind = _kind_for(detected)

        audit: list[dict[str, Any]] = [
            {"event": "artifact.received", "at": _utc_now(), "direction": direction, "parents": list(parent_artifact_ids)},
            {"event": "artifact.fingerprinted", "sha256": digest, "byte_size": len(payload)},
            {"event": "artifact.classified", "media_type": detected, "kind": kind},
        ]
        source_ref_ok = (
            isinstance(artifact.source_ref, str)
            and bool(artifact.source_ref.strip())
        )
        payload_ok = len(payload) > 0

        checks: list[dict[str, Any]] = [
            {"check": "sha256", "ok": True},
            {"check": "payload_nonempty", "ok": payload_ok},
            {"check": "source_ref", "ok": source_ref_ok},
            {"check": "signature_classification", "ok": True, "media_type": detected},
            *sniff_checks,
        ]
        contradictions: list[str] = []
        missing: list[str] = []

        if not payload_ok:
            missing.append("payload")
        if self.policy.require_source_ref and not source_ref_ok:
            missing.append("source_ref")

        if not _compatible(declared, detected):
            contradictions.append("media_type:declared_vs_detected")
            checks.append(
                {
                    "check": "declared_media_type",
                    "ok": False,
                    "declared": declared,
                    "detected": detected,
                }
            )
        elif declared:
            checks.append({"check": "declared_media_type", "ok": True})

        guessed, _ = mimetypes.guess_type(name)
        guessed = _normalize_media_type(guessed)
        if guessed and guessed not in _GENERIC_MEDIA_TYPES and not _compatible(guessed, detected):
            contradictions.append("filename:extension_vs_signature")
            checks.append(
                {
                    "check": "filename_media_type",
                    "ok": False,
                    "filename_type": guessed,
                    "detected": detected,
                }
            )

        suffix = PurePath(name).suffix.lower()
        active_content = (
            detected in _EXECUTABLE_MEDIA_TYPES
            or detected in _ACTIVE_TEXT_MEDIA_TYPES
            or declared in _ACTIVE_TEXT_MEDIA_TYPES
            or suffix in _EXECUTABLE_EXTENSIONS
            or suffix in _OFFICE_MACRO_EXTENSIONS
            or any(risk in {"archive:active_member", "archive:office_macro"} for risk in risks)
        )
        severe_archive_risk = any(
            risk in {
                "archive:path_traversal",
                "archive:extreme_compression_ratio",
                "archive:excessive_member_count",
                "archive:encrypted_member",
                "archive:member_over_1gb",
                "archive:parse_failed",
            }
            for risk in risks
        )
        quarantined = severe_archive_risk or (
            self.policy.quarantine_executables and active_content
        )
        for risk in risks:
            checks.append({"check": risk, "ok": False})

        specialized_results: list[str] = []

        if claim is not None:
            report = verify_claim(
                claim,
                [
                    EvidenceItem(
                        artifact_id,
                        latitude=artifact.latitude,
                        longitude=artifact.longitude,
                        captured_at=artifact.captured_at,
                        sha256=digest,
                        source_ref=artifact.source_ref,
                    )
                ],
            )
            checks.extend(report.checks)
            contradictions.extend(report.contradictions)
            missing.extend(report.missing)
            specialized_results.append(
                "VERIFIED" if report.status == "SUPPORTED" else report.status
            )
            audit.append({"event": "artifact.vita2_verified", "status": report.status})

        verifier = self.verifiers.get(kind)
        if verifier is not None:
            try:
                result = _normalize_specialized_result(verifier(payload, artifact.metadata))
            except Exception as exc:  # verifier adapters are an external trust boundary
                missing.append(f"{kind}:specialized_verifier_unavailable")
                specialized_results.append("UNVERIFIED")
                audit.append({
                    "event": "artifact.specialized_verified", "kind": kind,
                    "status": "UNVERIFIED", "reason": type(exc).__name__,
                })
            else:
                if result is None:
                    missing.append(f"{kind}:specialized_verifier_invalid_result")
                    specialized_results.append("UNVERIFIED")
                    audit.append({
                        "event": "artifact.specialized_verified", "kind": kind,
                        "status": "UNVERIFIED", "reason": "invalid_result",
                    })
                else:
                    checks.extend(result.checks)
                    contradictions.extend(result.contradictions)
                    missing.extend(result.missing)
                    specialized_results.append(result.status)
                    if any(check.get("ok") is False for check in result.checks):
                        contradictions.append(f"{kind}:specialized_verifier_failed_check")
                    if result.status == "CONTRADICTED":
                        contradictions.append(f"{kind}:specialized_verifier")
                    audit.append({
                        "event": "artifact.specialized_verified", "kind": kind,
                        "status": result.status,
                    })

        contradictions = sorted(set(contradictions))
        missing = sorted(set(missing))

        if contradictions:
            verification_status = "CONTRADICTED"
        elif quarantined:
            verification_status = "UNVERIFIED"
        elif missing:
            verification_status = "UNVERIFIED"
        elif "UNVERIFIED" in specialized_results:
            verification_status = "UNVERIFIED"
        elif specialized_results and all(status == "VERIFIED" for status in specialized_results):
            verification_status = "VERIFIED"
        else:
            verification_status = "PARTIAL"

        archive_status = "SKIPPED"
        archive_uri: str | None = None
        archive_sha: str | None = None

        if self.archive_sink is None:
            archive_status = "PENDING" if self.policy.require_archive else "SKIPPED"
            audit.append({"event": "artifact.archive", "status": archive_status})
        else:
            try:
                receipt = self.archive_sink.store(
                    artifact_id=artifact_id,
                    payload=payload,
                    sha256_hex=digest,
                    media_type=detected,
                    original_name=name,
                    quarantine=quarantined,
                )
                archive_uri = receipt.uri
                archive_sha = receipt.sha256.lower()
                if not archive_uri or archive_sha != digest:
                    archive_status = "FAILED"
                    audit.append({"event": "artifact.archive", "status": "FAILED", "reason": "receipt_mismatch"})
                else:
                    archive_status = "STORED"
                    audit.append({"event": "artifact.archive", "status": "STORED", "uri": archive_uri})
            except Exception as exc:  # archive adapters are external trust boundaries
                archive_status = "FAILED"
                audit.append(
                    {
                        "event": "artifact.archive",
                        "status": "FAILED",
                        "reason": type(exc).__name__,
                    }
                )

        index_manifest = {
            "schema": "oos.artifact-index.v1",
            "artifact_id": artifact_id,
            "direction": direction,
            "parent_artifact_ids": list(parent_artifact_ids),
            "sha256": digest,
            "byte_size": len(payload),
            "original_name": name,
            "declared_media_type": declared,
            "detected_media_type": detected,
            "kind": kind,
            "source_ref": artifact.source_ref,
            "verification_status": verification_status,
            "archive_status": archive_status,
            "archive_uri": archive_uri,
            "archive_sha256": archive_sha,
            "quarantined": quarantined,
            "contradictions": contradictions,
            "missing": missing,
        }
        encoded_manifest = json.dumps(
            index_manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        manifest_sha = sha256(encoded_manifest).hexdigest()

        index_status = "SKIPPED"
        index_uri: str | None = None
        index_record_sha: str | None = None
        if self.index_sink is None:
            index_status = "PENDING" if self.policy.require_index_record else "SKIPPED"
            audit.append({"event": "artifact.index", "status": index_status})
        else:
            try:
                receipt = self.index_sink.append(
                    artifact_id=artifact_id,
                    record=index_manifest,
                    record_sha256=manifest_sha,
                )
                index_uri = receipt.uri
                index_record_sha = receipt.record_sha256.lower()
                if not index_uri or index_record_sha != manifest_sha:
                    index_status = "FAILED"
                    audit.append(
                        {"event": "artifact.index", "status": "FAILED", "reason": "receipt_mismatch"}
                    )
                else:
                    index_status = "STORED"
                    audit.append({"event": "artifact.index", "status": "STORED", "uri": index_uri})
            except Exception as exc:  # remote index is an external trust boundary
                index_status = "FAILED"
                audit.append(
                    {
                        "event": "artifact.index",
                        "status": "FAILED",
                        "reason": type(exc).__name__,
                    }
                )

        archive_ok = archive_status == "STORED" or not self.policy.require_archive
        index_ok = index_status == "STORED" or not self.policy.require_index_record
        verification_ok = (
            verification_status == "VERIFIED"
            if self.policy.require_verified_for_trust
            else verification_status in {"VERIFIED", "PARTIAL"}
        )
        trust_ready = verification_ok and archive_ok and index_ok and not quarantined

        audit.append(
            {
                "event": "artifact.finalized",
                "verification_status": verification_status,
                "archive_status": archive_status,
                "index_status": index_status,
                "trust_ready": trust_ready,
            }
        )

        return ArtifactRecord(
            artifact_id=artifact_id,
            direction=direction,
            parent_artifact_ids=parent_artifact_ids,
            sha256=digest,
            byte_size=len(payload),
            original_name=name,
            declared_media_type=declared,
            detected_media_type=detected,
            kind=kind,
            verification_status=verification_status,
            archive_status=archive_status,
            archive_uri=archive_uri,
            archive_sha256=archive_sha,
            index_status=index_status,
            index_uri=index_uri,
            index_record_sha256=index_record_sha,
            quarantined=quarantined,
            trust_ready=trust_ready,
            contradictions=tuple(contradictions),
            missing=tuple(missing),
            checks=tuple(checks),
            audit=tuple(audit),
        )
