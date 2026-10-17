from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class GitHubSignalError(ValueError):
    """Raised when a GitHub event cannot be normalized safely."""


_CANONICAL_MAP: dict[tuple[str, str, str], tuple[str, str]] = {
    ("events_api", "WatchEvent", "started"): ("STAR", "OBJECT_MARKED"),
    ("webhook", "star", "created"): ("STAR", "OBJECT_MARKED"),
    ("webhook", "star", "deleted"): ("UNSTAR", "OBJECT_UNMARKED"),
    ("webhook", "watch", "started"): ("WATCH", "STREAM_SUBSCRIBED"),
    ("webhook", "fork", "created"): ("FORK", "WORK_INTENT_MARKER"),
    ("poller", "follow", "added"): ("FOLLOW", "PERSON_MARKED"),
    ("poller", "follow", "removed"): ("UNFOLLOW", "PERSON_UNMARKED"),
    ("poller", "watch", "added"): ("WATCH", "STREAM_SUBSCRIBED"),
    ("poller", "watch", "removed"): ("UNWATCH", "STREAM_UNSUBSCRIBED"),
    ("poller", "star", "added"): ("STAR", "OBJECT_MARKED"),
    ("poller", "star", "removed"): ("UNSTAR", "OBJECT_UNMARKED"),
}

_REVIEW_STATES = {
    "approved": "APPROVED",
    "changes_requested": "CHANGES_REQUESTED",
    "commented": "COMMENTED",
}


@dataclass(frozen=True)
class RawGitHubEvent:
    transport: str
    event_type: str
    action: str
    actor: str
    object_type: str
    object_id: str
    occurred_at: str
    payload: Mapping[str, Any]
    source_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "transport",
            "event_type",
            "action",
            "actor",
            "object_type",
            "object_id",
            "occurred_at",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise GitHubSignalError(f"{field_name} must be a non-empty string")
        try:
            parsed_occurred_at = datetime.fromisoformat(
                self.occurred_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise GitHubSignalError("occurred_at must be ISO-8601 date-time") from exc
        if parsed_occurred_at.tzinfo is None:
            raise GitHubSignalError("occurred_at must include timezone")
        if not isinstance(self.payload, Mapping):
            raise GitHubSignalError("payload must be a mapping")
        if self.source_event_id is not None and (
            not isinstance(self.source_event_id, str) or not self.source_event_id.strip()
        ):
            raise GitHubSignalError("source_event_id must be null or a non-empty string")

    def canonical_payload_json(self) -> str:
        try:
            return json.dumps(
                self.payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise GitHubSignalError("payload must be JSON-serializable") from exc

    def fingerprint(self) -> str:
        envelope = {
            "transport": self.transport,
            "event_type": self.event_type,
            "action": self.action,
            "actor": self.actor,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "occurred_at": self.occurred_at,
            "payload": json.loads(self.canonical_payload_json()),
            "source_event_id": self.source_event_id,
        }
        raw = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class NormalizedGitHubSignal:
    canonical_action: str
    semantic_class: str
    actor: str
    object_type: str
    object_id: str
    actor_relation: str
    evaluation: str | None = None

    @property
    def observed_fact(self) -> str:
        return f"{self.actor} {self.canonical_action} {self.object_id}"


@dataclass(frozen=True)
class StoredRawEvent:
    raw_event_id: int
    fingerprint: str
    duplicate: bool


@dataclass(frozen=True)
class StoredSignal:
    raw_event_id: int
    signal_id: int
    fingerprint: str
    normalized: NormalizedGitHubSignal
    duplicate: bool


def _actor_relation(event: RawGitHubEvent) -> str:
    if event.object_type != "repository":
        return "UNKNOWN"
    owner, sep, _ = event.object_id.partition("/")
    if not sep:
        return "UNKNOWN"
    return "SELF" if owner.casefold() == event.actor.casefold() else "EXTERNAL"


def normalize_github_event(event: RawGitHubEvent) -> NormalizedGitHubSignal:
    """Normalize a bounded GitHub event into an evidence-preserving OOS signal.

    This function normalizes observed provider behavior only. It does not infer
    quality, endorsement, adoption, production use, or motive.
    """

    if event.transport == "webhook" and event.event_type == "pull_request_review":
        if event.action != "submitted":
            raise GitHubSignalError("only submitted pull request reviews are supported")
        review = event.payload.get("review")
        if not isinstance(review, Mapping):
            raise GitHubSignalError("pull_request_review payload must include review")
        state = review.get("state")
        if not isinstance(state, str):
            raise GitHubSignalError("review.state must be a string")
        evaluation = _REVIEW_STATES.get(state.strip().lower())
        if evaluation is None:
            raise GitHubSignalError(f"unsupported review state: {state}")
        return NormalizedGitHubSignal(
            canonical_action="REVIEW",
            semantic_class="CONCRETE_EVALUATION",
            actor=event.actor,
            object_type=event.object_type,
            object_id=event.object_id,
            actor_relation=_actor_relation(event),
            evaluation=evaluation,
        )

    key = (event.transport, event.event_type, event.action)
    mapped = _CANONICAL_MAP.get(key)
    if mapped is None:
        raise GitHubSignalError(
            "unsupported or ambiguous GitHub event; raw event may be recorded "
            "but no canonical signal may be asserted"
        )
    canonical_action, semantic_class = mapped
    return NormalizedGitHubSignal(
        canonical_action=canonical_action,
        semantic_class=semantic_class,
        actor=event.actor,
        object_type=event.object_type,
        object_id=event.object_id,
        actor_relation=_actor_relation(event),
    )


class GitHubSignalStore:
    """Small local SQLite store that keeps raw evidence separate from signals."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS github_raw_events (
                id INTEGER PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                source_event_id TEXT,
                transport TEXT NOT NULL,
                event_type TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS github_signals (
                id INTEGER PRIMARY KEY,
                raw_event_id INTEGER NOT NULL UNIQUE,
                canonical_action TEXT NOT NULL,
                semantic_class TEXT NOT NULL,
                actor_relation TEXT NOT NULL,
                evaluation TEXT,
                FOREIGN KEY (raw_event_id)
                    REFERENCES github_raw_events(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS github_poll_meta (
                kind TEXT PRIMARY KEY,
                initialized_at TEXT NOT NULL,
                observed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS github_poll_snapshot (
                kind TEXT NOT NULL,
                object_id TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                PRIMARY KEY (kind, object_id),
                FOREIGN KEY (kind)
                    REFERENCES github_poll_meta(kind)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS github_entity_observations (
                id INTEGER PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                metadata_sha256 TEXT NOT NULL,
                UNIQUE(entity_type, entity_id, metadata_sha256)
            );

            CREATE TABLE IF NOT EXISTS github_signal_patterns (
                id INTEGER PRIMARY KEY,
                fingerprint TEXT NOT NULL UNIQUE,
                pattern_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                object_id TEXT NOT NULL,
                claim_class TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                proposed_action TEXT NOT NULL,
                detected_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "GitHubSignalStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def record_raw(self, event: RawGitHubEvent) -> StoredRawEvent:
        """Persist provider evidence before attempting semantic normalization."""

        payload_json = event.canonical_payload_json()
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        fingerprint = event.fingerprint()
        with self.conn:
            # Serialize the lookup and insert across connections. Delivery IDs
            # survive redelivery even when the fallback receipt time changes.
            self.conn.execute("BEGIN IMMEDIATE")
            if event.transport == "webhook" and event.source_event_id is not None:
                existing = self.conn.execute(
                    "SELECT * FROM github_raw_events WHERE transport = 'webhook' "
                    "AND source_event_id = ? ORDER BY id LIMIT 1",
                    (event.source_event_id,),
                ).fetchone()
                if existing is not None and (
                    existing["payload_sha256"] != payload_sha256
                    or any(existing[field] != getattr(event, field) for field in
                           ("event_type", "action", "actor", "object_type", "object_id"))
                ):
                    raise GitHubSignalError("Webhook delivery ID reused with different evidence")
            else:
                existing = self.conn.execute(
                    "SELECT * FROM github_raw_events WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
            duplicate = existing is not None
            if existing is None:
                cursor = self.conn.execute(
                    """
                    INSERT INTO github_raw_events(
                        fingerprint, source_event_id, transport, event_type,
                        action, actor, object_type, object_id, occurred_at,
                        payload_json, payload_sha256
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        fingerprint,
                        event.source_event_id,
                        event.transport,
                        event.event_type,
                        event.action,
                        event.actor,
                        event.object_type,
                        event.object_id,
                        event.occurred_at,
                        payload_json,
                        payload_sha256,
                    ),
                )
                raw_event_id = int(cursor.lastrowid)
            else:
                raw_event_id = int(existing["id"])
                fingerprint = str(existing["fingerprint"])

        return StoredRawEvent(
            raw_event_id=raw_event_id,
            fingerprint=fingerprint,
            duplicate=duplicate,
        )

    def ingest(self, event: RawGitHubEvent) -> StoredSignal:
        raw = self.record_raw(event)
        normalized = normalize_github_event(event)

        with self.conn:
            signal_row = self.conn.execute(
                "SELECT id FROM github_signals WHERE raw_event_id = ?",
                (raw.raw_event_id,),
            ).fetchone()
            if signal_row is None:
                cursor = self.conn.execute(
                    """
                    INSERT INTO github_signals(
                        raw_event_id, canonical_action, semantic_class,
                        actor_relation, evaluation
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        raw.raw_event_id,
                        normalized.canonical_action,
                        normalized.semantic_class,
                        normalized.actor_relation,
                        normalized.evaluation,
                    ),
                )
                signal_id = int(cursor.lastrowid)
            else:
                signal_id = int(signal_row["id"])

        return StoredSignal(
            raw_event_id=raw.raw_event_id,
            signal_id=signal_id,
            fingerprint=raw.fingerprint,
            normalized=normalized,
            duplicate=raw.duplicate,
        )

    def poll_snapshot(self, kind: str) -> tuple[bool, dict[str, dict[str, Any]]]:
        if not isinstance(kind, str) or not kind.strip():
            raise GitHubSignalError("poll snapshot kind must be non-empty")
        meta = self.conn.execute(
            "SELECT kind FROM github_poll_meta WHERE kind = ?",
            (kind,),
        ).fetchone()
        rows = self.conn.execute(
            "SELECT object_id, metadata_json FROM github_poll_snapshot "
            "WHERE kind = ? ORDER BY object_id",
            (kind,),
        ).fetchall()
        snapshot = {
            str(row["object_id"]): json.loads(row["metadata_json"])
            for row in rows
        }
        return meta is not None, snapshot

    def replace_poll_snapshot(
        self,
        kind: str,
        items: Mapping[str, Mapping[str, Any]],
        *,
        observed_at: str,
    ) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise GitHubSignalError("poll snapshot kind must be non-empty")
        if not isinstance(observed_at, str) or not observed_at.strip():
            raise GitHubSignalError("observed_at must be non-empty")
        if not isinstance(items, Mapping):
            raise GitHubSignalError("poll snapshot items must be a mapping")

        encoded: list[tuple[str, str]] = []
        for object_id, metadata in items.items():
            if not isinstance(object_id, str) or not object_id.strip():
                raise GitHubSignalError("snapshot object_id must be non-empty")
            if not isinstance(metadata, Mapping):
                raise GitHubSignalError("snapshot metadata must be a mapping")
            try:
                metadata_json = json.dumps(
                    metadata,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            except (TypeError, ValueError) as exc:
                raise GitHubSignalError(
                    "snapshot metadata must be JSON-serializable"
                ) from exc
            encoded.append((object_id, metadata_json))

        existing = self.conn.execute(
            "SELECT initialized_at FROM github_poll_meta WHERE kind = ?",
            (kind,),
        ).fetchone()
        initialized_at = (
            str(existing["initialized_at"]) if existing is not None else observed_at
        )

        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO github_poll_meta"
                "(kind, initialized_at, observed_at) VALUES(?,?,?)",
                (kind, initialized_at, observed_at),
            )
            self.conn.execute(
                "DELETE FROM github_poll_snapshot WHERE kind = ?",
                (kind,),
            )
            self.conn.executemany(
                "INSERT INTO github_poll_snapshot"
                "(kind, object_id, metadata_json) VALUES(?,?,?)",
                [(kind, object_id, metadata_json) for object_id, metadata_json in encoded],
            )

    def record_entity_observation(
        self,
        entity_type: str,
        entity_id: str,
        metadata: Mapping[str, Any],
        *,
        observed_at: str,
    ) -> int:
        for name, value in (
            ("entity_type", entity_type),
            ("entity_id", entity_id),
            ("observed_at", observed_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise GitHubSignalError(f"{name} must be non-empty")
        if not isinstance(metadata, Mapping):
            raise GitHubSignalError("entity metadata must be a mapping")
        try:
            metadata_json = json.dumps(
                metadata,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except (TypeError, ValueError) as exc:
            raise GitHubSignalError(
                "entity metadata must be JSON-serializable"
            ) from exc
        digest = hashlib.sha256(metadata_json.encode("utf-8")).hexdigest()
        existing = self.conn.execute(
            "SELECT id FROM github_entity_observations "
            "WHERE entity_type = ? AND entity_id = ? AND metadata_sha256 = ?",
            (entity_type, entity_id, digest),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])
        with self.conn:
            cursor = self.conn.execute(
                "INSERT INTO github_entity_observations"
                "(entity_type, entity_id, observed_at, metadata_json, metadata_sha256) "
                "VALUES(?,?,?,?,?)",
                (entity_type, entity_id, observed_at, metadata_json, digest),
            )
        return int(cursor.lastrowid)

    def latest_entity_observation(
        self,
        entity_type: str,
        entity_id: str,
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, observed_at, metadata_json, metadata_sha256 "
            "FROM github_entity_observations "
            "WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (entity_type, entity_id),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json"))
        return result

    def signal_rows(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT
                s.id AS signal_id,
                s.canonical_action,
                s.semantic_class,
                s.actor_relation,
                s.evaluation,
                r.actor,
                r.object_type,
                r.object_id,
                r.occurred_at
            FROM github_signals s
            JOIN github_raw_events r ON r.id = s.raw_event_id
            ORDER BY r.occurred_at, s.id
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def repository_ids(self) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT r.object_id
            FROM github_signals s
            JOIN github_raw_events r ON r.id = s.raw_event_id
            WHERE r.object_type = 'repository'
              AND instr(r.object_id, '/') > 0
            ORDER BY r.object_id
            """
        ).fetchall()
        return [str(row["object_id"]) for row in rows]

    def record_pattern(
        self,
        *,
        fingerprint: str,
        pattern_type: str,
        actor: str,
        object_id: str,
        claim_class: str,
        evidence_signal_ids: list[int],
        proposed_action: str,
        detected_at: str,
    ) -> int:
        if not evidence_signal_ids:
            raise GitHubSignalError("pattern must have evidence signal IDs")
        evidence_json = json.dumps(
            sorted({int(signal_id) for signal_id in evidence_signal_ids}),
            separators=(",", ":"),
        )
        existing = self.conn.execute(
            "SELECT id FROM github_signal_patterns WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if existing is not None:
            return int(existing["id"])
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO github_signal_patterns(
                    fingerprint, pattern_type, actor, object_id, claim_class,
                    evidence_json, proposed_action, detected_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    fingerprint,
                    pattern_type,
                    actor,
                    object_id,
                    claim_class,
                    evidence_json,
                    proposed_action,
                    detected_at,
                ),
            )
        return int(cursor.lastrowid)

    def patterns(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM github_signal_patterns ORDER BY id"
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["evidence_signal_ids"] = json.loads(item.pop("evidence_json"))
            result.append(item)
        return result

    def raw_event(self, raw_event_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM github_raw_events WHERE id = ?",
            (raw_event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(raw_event_id)
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def signal(self, signal_id: int) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT
                s.id,
                s.raw_event_id,
                s.canonical_action,
                s.semantic_class,
                s.actor_relation,
                s.evaluation,
                r.actor,
                r.object_type,
                r.object_id
            FROM github_signals s
            JOIN github_raw_events r ON r.id = s.raw_event_id
            WHERE s.id = ?
            """,
            (signal_id,),
        ).fetchone()
        if row is None:
            raise KeyError(signal_id)
        return dict(row)
