"""Tests for target-ingest module."""

import pytest

from target_search.db import open_db
from target_search.ingest import (
    chunk_text,
    estimate_tokens,
    index,
    infer_metadata,
)


@pytest.fixture
def db(tmp_path):
    """Create a fresh in-memory-like DB for each test."""
    conn = open_db(tmp_path / "test.db")
    yield conn
    conn.close()


class TestEstimateTokens:
    def test_basic(self):
        assert estimate_tokens("hello world") >= 1

    def test_empty(self):
        assert estimate_tokens("") == 1

    def test_long_text(self):
        text = "a" * 1000
        assert estimate_tokens(text) == 250


class TestChunkText:
    def test_empty(self):
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_single_paragraph(self):
        text = "This is a short paragraph."
        result = chunk_text(text)
        assert len(result) == 1
        assert result[0].chunk_index == 0
        assert result[0].text == text

    def test_multiple_paragraphs_within_limit(self):
        text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        result = chunk_text(text, max_chunk_tokens=500)
        assert len(result) == 1  # All fit in one chunk

    def test_paragraph_boundary_splitting(self):
        # Create paragraphs that will exceed chunk size
        para = "x" * 400  # ~100 tokens each
        text = f"{para}\n\n{para}\n\n{para}\n\n{para}"
        result = chunk_text(text, max_chunk_tokens=250)
        assert len(result) >= 2
        # Verify sequential chunk indices
        for i, chunk in enumerate(result):
            assert chunk.chunk_index == i

    def test_oversized_paragraph(self):
        # Single paragraph exceeding max
        text = "x" * 2000
        result = chunk_text(text, max_chunk_tokens=100)
        assert len(result) == 1  # Emitted as its own chunk
        assert result[0].token_count > 100


class TestInferMetadata:
    def test_memory_key(self):
        meta = infer_metadata("memory:2026-04-18")
        assert meta.source_type == "memory"
        assert meta.trust_level == 1.0
        assert meta.created_at == "2026-04-18"

    def test_email_key(self):
        meta = infer_metadata("email:thread:dream-system")
        assert meta.source_type == "email"
        assert meta.trust_level == 1.0

    def test_dream_key(self):
        meta = infer_metadata("dream:2026-04-17")
        assert meta.source_type == "dream"
        assert meta.trust_level == 0.5

    def test_unknown_key(self):
        meta = infer_metadata("random-doc")
        assert meta.source_type is None
        assert meta.trust_level == 1.0

    def test_date_extraction(self):
        meta = infer_metadata("notes:meeting-2026-01-15-standup")
        assert meta.created_at == "2026-01-15"


class TestIndex:
    def test_basic_index(self, db):
        result = index(db, "test:doc1", "Hello world. This is a test document.")
        assert result.doc_key == "test:doc1"
        assert result.chunks >= 1
        assert result.replaced is False

    def test_idempotent_reindex(self, db):
        index(db, "test:doc1", "First version.")
        result = index(db, "test:doc1", "Second version, completely different.")
        assert result.replaced is True
        # Verify only new chunks exist
        rows = db.execute(
            "SELECT chunk_text FROM record_chunks WHERE record_id = ?",
            (result.record_id,),
        ).fetchall()
        texts = [r["chunk_text"] for r in rows]
        assert all("Second" in t for t in texts)
        assert not any("First" in t for t in texts)

    def test_metadata_override(self, db):
        result = index(
            db, "test:doc1", "Content.",
            metadata={"source_type": "custom", "trust_level": 0.8},
        )
        row = db.execute(
            "SELECT source_type, trust_level FROM records WHERE id = ?",
            (result.record_id,),
        ).fetchone()
        assert row["source_type"] == "custom"
        assert row["trust_level"] == 0.8

    def test_empty_content(self, db):
        result = index(db, "test:empty", "")
        assert result.chunks == 0

    def test_multiple_documents(self, db):
        index(db, "doc:a", "Document A content.")
        index(db, "doc:b", "Document B content.")
        count = db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        assert count == 2
