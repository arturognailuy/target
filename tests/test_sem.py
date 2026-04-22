"""Tests for target-sem: semantic search with sqlite-vec."""

from __future__ import annotations

import struct

import pytest

from target_search.db import open_db
from target_search.ingest import index

# Skip all tests if semantic deps are not installed
sem = pytest.importorskip("target_search.sem")


@pytest.fixture
def db(tmp_path):
    """Create a fresh database with test data."""
    conn = open_db(tmp_path / "test.db")
    index(
        conn, "doc:animals",
        "Dogs are loyal pets that love their owners.\n\n"
        "Cats are independent creatures that value their freedom.",
    )
    index(
        conn, "doc:weather",
        "Rain falls from clouds in the sky.\n\n"
        "Snow covers the ground in winter months.",
    )
    index(
        conn, "doc:coding",
        "Python is a popular programming language.\n\n"
        "JavaScript runs in web browsers.",
    )
    return conn


class TestSerialize:
    def test_serialize_list(self):
        data = sem._serialize_f32([1.0, 2.0, 3.0])
        assert len(data) == 12  # 3 * 4 bytes
        values = struct.unpack("3f", data)
        assert values == pytest.approx((1.0, 2.0, 3.0))

    def test_serialize_numpy(self):
        np = pytest.importorskip("numpy")
        arr = np.array([1.0, 2.0], dtype=np.float32)
        data = sem._serialize_f32(arr)
        assert len(data) == 8


class TestEmbedding:
    def test_embed_text_returns_vector(self):
        vec = sem.embed_text("hello world")
        assert isinstance(vec, list)
        assert len(vec) == sem.EMBEDDING_DIM
        assert all(isinstance(v, float) for v in vec)

    def test_embed_texts_batch(self):
        vecs = sem.embed_texts(["hello", "world"])
        assert len(vecs) == 2
        assert len(vecs[0]) == sem.EMBEDDING_DIM

    def test_embed_texts_empty(self):
        assert sem.embed_texts([]) == []

    def test_similar_texts_closer(self):
        v1 = sem.embed_text("dogs are loyal pets")
        v2 = sem.embed_text("cats are friendly animals")
        v3 = sem.embed_text("quantum physics equations")

        # Compute cosine similarity (vectors are normalized)
        def cosine_sim(a, b):
            return sum(x * y for x, y in zip(a, b))

        sim_related = cosine_sim(v1, v2)
        sim_unrelated = cosine_sim(v1, v3)
        assert sim_related > sim_unrelated


class TestEnsureVecTable:
    def test_creates_tables(self, db):
        sem.ensure_vec_table(db)
        # Should not raise
        db.execute("SELECT count(*) FROM chunk_embeddings")

    def test_idempotent(self, db):
        sem.ensure_vec_table(db)
        sem.ensure_vec_table(db)  # Should not raise


class TestIndexEmbeddings:
    def test_embeds_all_chunks(self, db):
        count = sem.index_embeddings(db)
        total_chunks = db.execute("SELECT COUNT(*) FROM record_chunks").fetchone()[0]
        assert count == total_chunks
        embed_count = db.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        assert embed_count == total_chunks

    def test_idempotent(self, db):
        count1 = sem.index_embeddings(db)
        count2 = sem.index_embeddings(db)
        assert count1 > 0
        assert count2 == 0  # Already embedded

    def test_incremental(self, db):
        sem.index_embeddings(db)
        # Add a new doc
        index(db, "doc:new", "This is brand new content.")
        count = sem.index_embeddings(db)
        assert count >= 1  # Only new chunks


class TestSearchSem:
    def test_basic_search(self, db):
        sem.index_embeddings(db)
        results = sem.search_sem(db, "pet animals")
        assert len(results) > 0
        assert results[0].chunk_id > 0

    def test_semantic_relevance(self, db):
        sem.index_embeddings(db)
        results = sem.search_sem(db, "loyal companion animals")
        # The dogs/cats doc should rank higher than weather/coding
        top_keys = [r.doc_key for r in results[:2]]
        assert "doc:animals" in top_keys

    def test_result_fields(self, db):
        sem.index_embeddings(db)
        results = sem.search_sem(db, "programming")
        assert len(results) > 0
        r = results[0]
        assert isinstance(r.cosine_score, float)
        assert 0.0 <= r.cosine_score <= 1.0
        assert r.doc_key is not None
        assert r.chunk_text is not None

    def test_empty_query(self, db):
        sem.index_embeddings(db)
        assert sem.search_sem(db, "") == []
        assert sem.search_sem(db, "   ") == []

    def test_top_n_limit(self, db):
        sem.index_embeddings(db)
        results = sem.search_sem(db, "animals", top_n=2)
        assert len(results) <= 2


class TestRemoveEmbeddings:
    def test_removes(self, db):
        sem.index_embeddings(db)
        chunk_ids = [r[0] for r in db.execute("SELECT id FROM record_chunks LIMIT 1").fetchall()]
        sem.remove_embeddings(db, chunk_ids)
        vec_count = db.execute(
            "SELECT COUNT(*) FROM chunk_embeddings WHERE chunk_id = ?", (chunk_ids[0],)
        ).fetchone()[0]
        assert vec_count == 0

    def test_remove_empty(self, db):
        sem.remove_embeddings(db, [])  # Should not raise
