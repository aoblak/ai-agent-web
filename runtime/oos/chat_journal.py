from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

GENESIS = "0" * 64

@dataclass(frozen=True)
class AppendResult:
    seq: int
    event_hash: str

class ChatJournalWriter:
    """Append-only NDJSON journal with a hash chain.

    The class intentionally exposes no update/delete API.
    Existing events may be corrected only by appending a new correction event.
    """

    def __init__(self, path: str | Path, chat_id: str):
        self.path = Path(path)
        self.chat_id = chat_id
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _canonical_payload(event: dict[str, Any]) -> bytes:
        body = {k: v for k, v in event.items() if k != "event_hash"}
        return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    @classmethod
    def _hash(cls, event: dict[str, Any]) -> str:
        return sha256(cls._canonical_payload(event)).hexdigest()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                out.append(json.loads(raw))
        return out

    def append_event(self, role: str, event_type: str, content: Any, *, metadata: dict[str, Any] | None = None) -> AppendResult:
        events = self._read()
        seq = len(events) + 1
        prev_hash = events[-1]["event_hash"] if events else GENESIS
        event = {
            "seq": seq,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": self.chat_id,
            "role": role,
            "event_type": event_type,
            "content": content,
            "metadata": metadata or {},
            "previous_hash": prev_hash,
        }

        # Semantic promotion is part of the write boundary, not an optional
        # caller-side check. Canonical changes fail closed before persistence.
        PromotionGate.assert_valid(events, event)
        event["event_hash"] = self._hash(event)

        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
            fh.flush()
        return AppendResult(seq=seq, event_hash=event["event_hash"])

    def correction(self, supersedes_seq: int, corrected_content: Any, *, reason: str) -> AppendResult:
        return self.append_event(
            role="system-event",
            event_type="correction",
            content=corrected_content,
            metadata={"supersedes_seq": supersedes_seq, "reason": reason},
        )

    def checkpoint(self) -> AppendResult:
        events = self._read()
        root = events[-1]["event_hash"] if events else GENESIS
        return self.append_event(
            role="system-event",
            event_type="checkpoint",
            content={"root_hash_before_checkpoint": root, "event_count_before_checkpoint": len(events)},
        )

    def verify_chain(self) -> tuple[bool, str | None]:
        events = self._read()
        expected_prev = GENESIS
        expected_seq = 1
        for event in events:
            if event.get("seq") != expected_seq:
                return False, f"sequence mismatch at event {expected_seq}"
            if event.get("chat_id") != self.chat_id:
                return False, f"chat_id mismatch at event {expected_seq}"
            if event.get("previous_hash") != expected_prev:
                return False, f"previous_hash mismatch at event {expected_seq}"
            actual = event.get("event_hash")
            computed = self._hash(event)
            if actual != computed:
                return False, f"event hash mismatch at event {expected_seq}"
            expected_prev = actual
            expected_seq += 1
        return True, None


class PromotionGate:
    """Fail-closed semantic gate for canonicalization/promotion events."""

    CANONICAL_EVENT_TYPES = {"promotion", "canonicalization", "state-change"}

    @staticmethod
    def validate(events: list[dict[str, Any]], candidate: dict[str, Any]) -> tuple[bool, str | None]:
        if candidate.get("event_type") not in PromotionGate.CANONICAL_EVENT_TYPES:
            return True, None

        metadata = candidate.get("metadata") or {}
        source_seqs = metadata.get("source_seqs")
        if not isinstance(source_seqs, list) or not source_seqs:
            return False, "promotion requires non-empty source_seqs"

        by_seq = {e.get("seq"): e for e in events if isinstance(e.get("seq"), int)}
        missing = [seq for seq in source_seqs if seq not in by_seq]
        if missing:
            return False, f"promotion references missing source events: {missing}"

        direct_user_sources = [by_seq[seq] for seq in source_seqs if by_seq[seq].get("role") == "user"]
        if not direct_user_sources:
            return False, "promotion must reference at least one direct user event"

        if metadata.get("changes_canon") is True:
            prior_user_seqs = {
                seq for seq, event in by_seq.items()
                if event.get("role") == "user"
            }
            cited_user_seqs = {
                seq for seq in source_seqs
                if by_seq[seq].get("role") == "user"
            }
            omitted_user_seqs = sorted(prior_user_seqs - cited_user_seqs)
            if omitted_user_seqs:
                return False, (
                    "canon-changing promotion omits prior user events: "
                    f"{omitted_user_seqs}"
                )

        if metadata.get("contradiction_check") != "pass":
            return False, "promotion contradiction_check must be pass"

        if metadata.get("changes_canon") is True and metadata.get("authorized_by_user") is not True:
            return False, "canon-changing promotion requires explicit user authorization"

        if metadata.get("external_state_claim") is True and metadata.get("independent_verification") is not True:
            return False, "external/live state promotion requires independent verification"

        return True, None

    @staticmethod
    def assert_valid(events: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
        ok, err = PromotionGate.validate(events, candidate)
        if not ok:
            raise ValueError(err or "promotion rejected")


class ChatJournalIngress:
    """Ingress adapter: first event for an unseen chat_id creates its journal automatically."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_chat_id(chat_id: str) -> str:
        if not chat_id or not isinstance(chat_id, str):
            raise ValueError("chat_id is required")
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in chat_id)
        if safe in {"", ".", ".."}:
            raise ValueError("invalid chat_id")
        return safe

    def journal_path(self, chat_id: str) -> Path:
        safe = self._safe_chat_id(chat_id)
        return self.root / f"{safe}.ndjson"

    def ingest(self, chat_id: str, role: str, event_type: str, content: Any, *, metadata: dict[str, Any] | None = None) -> AppendResult:
        path = self.journal_path(chat_id)
        writer = ChatJournalWriter(path, chat_id)

        # First observed event creates an explicit session_open record.
        if not path.exists() or path.stat().st_size == 0:
            writer.append_event(
                "system-event",
                "session_open",
                {"chat_id": chat_id},
                metadata={"created_by": "ChatJournalIngress"},
            )

        # Fail closed if an existing journal is corrupted before appending.
        ok, err = writer.verify_chain()
        if not ok:
            raise ValueError(f"refusing append to corrupted journal: {err}")

        return writer.append_event(role, event_type, content, metadata=metadata)

    def verify_chat(self, chat_id: str) -> tuple[bool, str | None]:
        return ChatJournalWriter(self.journal_path(chat_id), chat_id).verify_chain()
