import hashlib
import tempfile
import unittest
from pathlib import Path

from oos.retrieval import (
    LocalRetrievalIndex,
    RetrievalPolicy,
    RetrievalPolicyError,
    chunk_text,
)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.index = LocalRetrievalIndex(self.root / "index.sqlite")

    def tearDown(self):
        self.index.close()
        self.temp.cleanup()

    def test_ingest_search_and_provenance(self):
        docs = self.root / "docs"
        docs.mkdir()
        source = docs / "note.txt"
        source.write_text(
            "Local AI systems need explicit verification and provenance.",
            encoding="utf-8",
        )
        summary = self.index.ingest_path(docs, corpus_id="alpha")
        self.assertEqual(summary.ingested_files, 1)
        hits = self.index.search("verification provenance", corpus_id="alpha")
        self.assertTrue(hits)
        hit = hits[0]
        self.assertTrue(hit.source_id.endswith("/note.txt"))
        self.assertEqual(
            hit.source_sha256,
            hashlib.sha256(source.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            hit.chunk_sha256,
            hashlib.sha256(hit.text.encode("utf-8")).hexdigest(),
        )
        self.assertNotIn(str(self.root), hit.source_id)

    def test_corpus_isolation(self):
        a = self.root / "a.txt"
        b = self.root / "b.txt"
        a.write_text("alpha secret context", encoding="utf-8")
        b.write_text("beta secret context", encoding="utf-8")
        self.index.ingest_path(a, corpus_id="A")
        self.index.ingest_path(b, corpus_id="B")
        alpha_hits = self.index.search("alpha", corpus_id="A")
        self.assertEqual(len(alpha_hits), 1)
        self.assertTrue(alpha_hits[0].source_id.endswith("/a.txt"))
        self.assertEqual(self.index.search("alpha", corpus_id="B"), [])

    def test_directory_skips_disallowed_extensions(self):
        docs = self.root / "docs"
        docs.mkdir()
        (docs / "ok.md").write_text("allowed", encoding="utf-8")
        (docs / "no.bin").write_bytes(b"allowed-looking bytes")
        summary = self.index.ingest_path(docs, corpus_id="c")
        self.assertEqual(summary.ingested_files, 1)
        self.assertEqual(summary.skipped_files, 1)

    def test_explicit_disallowed_file_fails_closed(self):
        bad = self.root / "bad.bin"
        bad.write_bytes(b"x")
        with self.assertRaises(RetrievalPolicyError):
            self.index.ingest_path(bad, corpus_id="c")

    def test_invalid_utf8_file_fails_closed(self):
        bad = self.root / "bad.txt"
        bad.write_bytes(b"\xff\xfe")
        with self.assertRaises(RetrievalPolicyError):
            self.index.ingest_path(bad, corpus_id="c")

    def test_oversize_explicit_file_fails_closed(self):
        policy = RetrievalPolicy(max_file_bytes=4)
        other = LocalRetrievalIndex(self.root / "small.sqlite", policy=policy)
        try:
            p = self.root / "big.txt"
            p.write_text("12345", encoding="utf-8")
            with self.assertRaises(RetrievalPolicyError):
                other.ingest_path(p, corpus_id="c")
        finally:
            other.close()

    def test_symlink_file_is_not_ingested(self):
        docs = self.root / "docs"
        docs.mkdir()
        outside = self.root / "outside.txt"
        outside.write_text("do not ingest", encoding="utf-8")
        link = docs / "link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not supported")
        summary = self.index.ingest_path(docs, corpus_id="c")
        self.assertEqual(summary.ingested_files, 0)
        self.assertEqual(summary.skipped_files, 1)
        self.assertEqual(self.index.search("ingest", corpus_id="c"), [])

    def test_same_filename_from_different_roots_does_not_collide(self):
        left = self.root / "left"
        right = self.root / "right"
        left.mkdir()
        right.mkdir()
        (left / "doc.txt").write_text("left unique", encoding="utf-8")
        (right / "doc.txt").write_text("right unique", encoding="utf-8")
        self.index.ingest_path(left / "doc.txt", corpus_id="c")
        self.index.ingest_path(right / "doc.txt", corpus_id="c")
        left_hits = self.index.search("left", corpus_id="c")
        right_hits = self.index.search("right", corpus_id="c")
        self.assertTrue(left_hits and right_hits)
        self.assertNotEqual(left_hits[0].source_id, right_hits[0].source_id)
        self.assertTrue(left_hits[0].source_id.endswith("/doc.txt"))
        self.assertTrue(right_hits[0].source_id.endswith("/doc.txt"))

    def test_reingest_is_idempotent_and_changed_content_replaces(self):
        p = self.root / "doc.txt"
        p.write_text("first version", encoding="utf-8")
        first = self.index.ingest_path(p, corpus_id="c")
        second = self.index.ingest_path(p, corpus_id="c")
        self.assertEqual(first.ingested_files, 1)
        self.assertEqual(second.unchanged_files, 1)
        p.write_text("second replacement", encoding="utf-8")
        third = self.index.ingest_path(p, corpus_id="c")
        self.assertEqual(third.ingested_files, 1)
        self.assertEqual(self.index.search("first", corpus_id="c"), [])
        self.assertTrue(self.index.search("replacement", corpus_id="c"))

    def test_chunk_overlap_is_deterministic(self):
        chunks = chunk_text("abcdefghij", size=6, overlap=2)
        self.assertEqual(chunks, ["abcdef", "efghij", "ij"])

    def test_invalid_corpus_query_and_limit_fail(self):
        p = self.root / "doc.txt"
        p.write_text("hello", encoding="utf-8")
        with self.assertRaises(RetrievalPolicyError):
            self.index.ingest_path(p, corpus_id="../bad")
        self.index.ingest_path(p, corpus_id="good")
        with self.assertRaises(RetrievalPolicyError):
            self.index.search("", corpus_id="good")
        with self.assertRaises(RetrievalPolicyError):
            self.index.search("hello", corpus_id="good", limit=999)

    def test_corpus_chunk_limit_is_enforced_transactionally(self):
        policy = RetrievalPolicy(
            chunk_size=4,
            chunk_overlap=0,
            max_chunks_per_file=10,
            max_chunks_per_corpus=2,
        )
        other = LocalRetrievalIndex(self.root / "limited.sqlite", policy=policy)
        try:
            p = self.root / "many.txt"
            p.write_text("abcdefghijkl", encoding="utf-8")
            with self.assertRaises(RetrievalPolicyError):
                other.ingest_path(p, corpus_id="c")
            self.assertEqual(other.search("abcd", corpus_id="c"), [])
        finally:
            other.close()


if __name__ == "__main__":
    unittest.main()
