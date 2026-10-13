from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


class RetrievalError(RuntimeError):
    """Base retrieval/index error."""


class RetrievalPolicyError(ValueError):
    """Raised when ingest or search violates retrieval policy."""


_CORPUS_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class RetrievalPolicy:
    allowed_extensions: tuple[str, ...] = (".txt", ".md", ".py", ".json", ".csv")
    max_file_bytes: int = 2 * 1024 * 1024
    max_files_per_ingest: int = 500
    chunk_size: int = 800
    chunk_overlap: int = 100
    max_chunks_per_file: int = 2048
    max_chunks_per_corpus: int = 10000
    max_search_limit: int = 50

    def __post_init__(self) -> None:
        normalized = tuple(
            sorted(
                {
                    ext.lower() if ext.startswith(".") else f".{ext.lower()}"
                    for ext in self.allowed_extensions
                }
            )
        )
        if not normalized:
            raise RetrievalPolicyError("allowed_extensions must not be empty")
        object.__setattr__(self, "allowed_extensions", normalized)
        if self.max_file_bytes <= 0 or self.max_files_per_ingest <= 0:
            raise RetrievalPolicyError("file limits must be positive")
        if (
            self.chunk_size <= 0
            or self.chunk_overlap < 0
            or self.chunk_overlap >= self.chunk_size
        ):
            raise RetrievalPolicyError(
                "chunk_overlap must satisfy 0 <= overlap < chunk_size"
            )
        if self.max_chunks_per_file <= 0 or self.max_chunks_per_corpus <= 0:
            raise RetrievalPolicyError("chunk limits must be positive")
        if self.max_search_limit <= 0:
            raise RetrievalPolicyError("max_search_limit must be positive")


@dataclass(frozen=True)
class IngestSummary:
    corpus_id: str
    ingested_files: int
    unchanged_files: int
    skipped_files: int
    chunks_written: int


@dataclass(frozen=True)
class SearchResult:
    corpus_id: str
    source_id: str
    source_sha256: str
    chunk_index: int
    chunk_sha256: str
    text: str
    score: float


def _validate_corpus_id(corpus_id: str) -> str:
    if not isinstance(corpus_id, str) or not _CORPUS_ID.fullmatch(corpus_id):
        raise RetrievalPolicyError("corpus_id must match [A-Za-z0-9._-]{1,64}")
    return corpus_id


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN.findall(text)]


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    if size <= 0 or overlap < 0 or overlap >= size:
        raise RetrievalPolicyError("invalid chunk parameters")
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    step = size - overlap
    while start < len(text):
        chunks.append(text[start : start + size])
        start += step
    return chunks


class LocalRetrievalIndex:
    """Small corpus-isolated local retrieval index with explicit provenance.

    This module deliberately handles only trusted local indexing/search mechanics.
    It does not grant filesystem access to agents and is not an OOS authorization
    boundary.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        policy: RetrievalPolicy | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy = policy or RetrievalPolicy()
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS retrieval_sources (
                corpus_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                PRIMARY KEY (corpus_id, source_id)
            );
            CREATE TABLE IF NOT EXISTS retrieval_chunks (
                corpus_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                source_sha256 TEXT NOT NULL,
                chunk_sha256 TEXT NOT NULL,
                text TEXT NOT NULL,
                PRIMARY KEY (corpus_id, source_id, chunk_index),
                FOREIGN KEY (corpus_id, source_id)
                    REFERENCES retrieval_sources(corpus_id, source_id)
                    ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS retrieval_chunks_corpus
                ON retrieval_chunks(corpus_id);
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "LocalRetrievalIndex":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _candidate_paths(self, path: Path) -> tuple[Path, list[Path], bool]:
        if not path.exists():
            raise FileNotFoundError(path)
        if path.is_symlink():
            raise RetrievalPolicyError("symlink ingest roots are forbidden")
        if path.is_file():
            return path.parent.resolve(), [path], True
        if not path.is_dir():
            raise RetrievalPolicyError(
                "ingest path must be a regular file or directory"
            )
        root = path.resolve()
        files: list[Path] = []
        for candidate in path.rglob("*"):
            if not candidate.is_file():
                continue
            files.append(candidate)
            if len(files) > self.policy.max_files_per_ingest:
                raise RetrievalPolicyError(
                    "ingest path exceeds max_files_per_ingest"
                )
        files.sort(key=lambda candidate: str(candidate))
        return root, files, False

    def _prepare_file(
        self,
        file_path: Path,
        *,
        root: Path,
        explicit: bool,
    ) -> tuple[str, bytes, str, list[str]] | None:
        if file_path.is_symlink():
            if explicit:
                raise RetrievalPolicyError("symlink files are forbidden")
            return None
        if file_path.suffix.lower() not in self.policy.allowed_extensions:
            if explicit:
                raise RetrievalPolicyError("file extension is not allowlisted")
            return None
        resolved = file_path.resolve()
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            if explicit:
                raise RetrievalPolicyError("file escapes ingest root") from exc
            return None
        stat = resolved.stat()
        if stat.st_size > self.policy.max_file_bytes:
            if explicit:
                raise RetrievalPolicyError("file exceeds max_file_bytes")
            return None
        raw = resolved.read_bytes()
        if len(raw) > self.policy.max_file_bytes:
            if explicit:
                raise RetrievalPolicyError("file exceeds max_file_bytes")
            return None
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            if explicit:
                raise RetrievalPolicyError("file must be valid UTF-8 text") from exc
            return None
        chunks = chunk_text(
            text,
            size=self.policy.chunk_size,
            overlap=self.policy.chunk_overlap,
        )
        if len(chunks) > self.policy.max_chunks_per_file:
            if explicit:
                raise RetrievalPolicyError("file exceeds max_chunks_per_file")
            return None
        root_fingerprint = hashlib.sha256(
            str(root).encode("utf-8")
        ).hexdigest()[:12]
        source_id = f"{root_fingerprint}/{relative.as_posix()}"
        digest = hashlib.sha256(raw).hexdigest()
        return source_id, raw, digest, chunks

    def ingest_path(self, path: str | Path, *, corpus_id: str) -> IngestSummary:
        corpus_id = _validate_corpus_id(corpus_id)
        source_path = Path(path)
        root, candidates, explicit = self._candidate_paths(source_path)
        prepared: list[tuple[str, bytes, str, list[str]]] = []
        skipped = 0
        for candidate in candidates:
            item = self._prepare_file(
                candidate,
                root=root,
                explicit=explicit,
            )
            if item is None:
                skipped += 1
            else:
                prepared.append(item)

        ingested = 0
        unchanged = 0
        chunks_written = 0
        with self.conn:
            current_total = self.conn.execute(
                "SELECT COUNT(*) FROM retrieval_chunks WHERE corpus_id = ?",
                (corpus_id,),
            ).fetchone()[0]
            for source_id, raw, digest, chunks in prepared:
                row = self.conn.execute(
                    "SELECT sha256, chunk_count FROM retrieval_sources "
                    "WHERE corpus_id = ? AND source_id = ?",
                    (corpus_id, source_id),
                ).fetchone()
                if row is not None and row["sha256"] == digest:
                    unchanged += 1
                    continue
                previous_chunks = int(row["chunk_count"]) if row is not None else 0
                projected_total = current_total - previous_chunks + len(chunks)
                if projected_total > self.policy.max_chunks_per_corpus:
                    raise RetrievalPolicyError(
                        "corpus would exceed max_chunks_per_corpus"
                    )

                self.conn.execute(
                    "DELETE FROM retrieval_sources "
                    "WHERE corpus_id = ? AND source_id = ?",
                    (corpus_id, source_id),
                )
                self.conn.execute(
                    "INSERT INTO retrieval_sources"
                    "(corpus_id, source_id, sha256, size_bytes, chunk_count) "
                    "VALUES(?,?,?,?,?)",
                    (corpus_id, source_id, digest, len(raw), len(chunks)),
                )
                for index, chunk in enumerate(chunks):
                    chunk_digest = hashlib.sha256(
                        chunk.encode("utf-8")
                    ).hexdigest()
                    self.conn.execute(
                        "INSERT INTO retrieval_chunks"
                        "(corpus_id, source_id, chunk_index, source_sha256, "
                        "chunk_sha256, text) VALUES(?,?,?,?,?,?)",
                        (
                            corpus_id,
                            source_id,
                            index,
                            digest,
                            chunk_digest,
                            chunk,
                        ),
                    )
                current_total = projected_total
                ingested += 1
                chunks_written += len(chunks)

        return IngestSummary(
            corpus_id,
            ingested,
            unchanged,
            skipped,
            chunks_written,
        )

    def search(
        self,
        query: str,
        *,
        corpus_id: str,
        limit: int = 5,
    ) -> list[SearchResult]:
        corpus_id = _validate_corpus_id(corpus_id)
        if not isinstance(query, str) or not query.strip():
            raise RetrievalPolicyError("query must be a non-empty string")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
            or limit > self.policy.max_search_limit
        ):
            raise RetrievalPolicyError("limit is outside retrieval policy")
        rows = self.conn.execute(
            "SELECT source_id, source_sha256, chunk_index, chunk_sha256, text "
            "FROM retrieval_chunks WHERE corpus_id = ? "
            "ORDER BY source_id, chunk_index",
            (corpus_id,),
        ).fetchall()
        if len(rows) > self.policy.max_chunks_per_corpus:
            raise RetrievalPolicyError("stored corpus exceeds retrieval policy")
        if not rows:
            return []

        query_tokens = _tokens(query)
        if not query_tokens:
            return []
        document_tokens = [_tokens(row["text"]) for row in rows]
        document_frequency: Counter[str] = Counter()
        for tokens in document_tokens:
            document_frequency.update(set(tokens))
        doc_count = len(rows)

        def idf(term: str) -> float:
            return (
                math.log(
                    (doc_count + 1)
                    / (document_frequency.get(term, 0) + 1)
                )
                + 1.0
            )

        query_counts = Counter(query_tokens)
        query_weights = {
            term: count * idf(term)
            for term, count in query_counts.items()
        }
        query_norm = math.sqrt(
            sum(weight * weight for weight in query_weights.values())
        )
        if query_norm == 0:
            return []

        scored: list[SearchResult] = []
        for row, tokens in zip(rows, document_tokens):
            counts = Counter(tokens)
            if not counts:
                continue
            doc_weights = {
                term: count * idf(term)
                for term, count in counts.items()
            }
            doc_norm = math.sqrt(
                sum(weight * weight for weight in doc_weights.values())
            )
            if doc_norm == 0:
                continue
            dot = sum(
                query_weights.get(term, 0.0) * weight
                for term, weight in doc_weights.items()
            )
            score = dot / (query_norm * doc_norm)
            if score <= 0:
                continue
            scored.append(
                SearchResult(
                    corpus_id=corpus_id,
                    source_id=row["source_id"],
                    source_sha256=row["source_sha256"],
                    chunk_index=int(row["chunk_index"]),
                    chunk_sha256=row["chunk_sha256"],
                    text=row["text"],
                    score=float(score),
                )
            )
        scored.sort(
            key=lambda result: (
                -result.score,
                result.source_id,
                result.chunk_index,
            )
        )
        return scored[:limit]
