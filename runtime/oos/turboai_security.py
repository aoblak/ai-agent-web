from __future__ import annotations

import hmac
from pathlib import Path


class TurboAISecurityError(ValueError):
    """Raised when TurboAI input violates the OOS integration boundary."""


_FORBIDDEN_SECRETS = {
    "change-me",
    "changeme",
    "admin",
    "password",
    "secret",
}


def validate_production_secret(secret: str, *, min_length: int = 32) -> str:
    """Fail closed on missing, placeholder, or weak production signing secrets."""
    if not isinstance(secret, str):
        raise TurboAISecurityError("production secret must be a string")

    normalized = secret.strip()
    if not normalized:
        raise TurboAISecurityError("production secret must not be empty")
    if normalized.lower() in _FORBIDDEN_SECRETS:
        raise TurboAISecurityError("default or placeholder production secret is forbidden")
    if len(normalized) < min_length:
        raise TurboAISecurityError(
            f"production secret must be at least {min_length} characters"
        )
    return normalized


def require_session_owner(*, actor_id: str, owner_id: str) -> None:
    """Enforce object-level ownership before session reads or writes."""
    if (
        not isinstance(actor_id, str)
        or not actor_id.strip()
        or not isinstance(owner_id, str)
        or not owner_id.strip()
    ):
        raise PermissionError("session actor and owner identities must be non-empty strings")
    if not hmac.compare_digest(actor_id, owner_id):
        raise PermissionError("session access denied: actor is not the owner")


def resolve_upload_destination(upload_root: str | Path, filename: str) -> Path:
    """Return a contained upload path or reject traversal/nested path input.

    Phase 0/1 deliberately accepts only a single basename. Directory creation,
    archive extraction, and content/type validation belong to later ingest code.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise TurboAISecurityError("upload filename is required")
    if "\x00" in filename:
        raise TurboAISecurityError("NUL byte in upload filename")
    if filename in {".", ".."} or "/" in filename or "\\" in filename:
        raise TurboAISecurityError("nested or traversal upload paths are forbidden")

    root = Path(upload_root).expanduser().resolve()
    destination = (root / filename).resolve()

    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise TurboAISecurityError("upload destination escapes configured root") from exc

    if destination == root:
        raise TurboAISecurityError("upload filename must resolve to a file below root")
    return destination
