"""Tests for target-lex module."""

import pytest

from target_search.db import open_db
from target_search.ingest import index
from target_search.lex import search_lex


@pytest.fixture
def db(tmp_path):
    conn = open_db(tmp_path / "test.db")
    yield conn
    conn.close()


@pytest.fixture
def populated_db(db):
    """DB with several documents indexed."""
    index(
        db, "doc:python",
        "Python is a programming language. It is used for web development, "
        "data science, and machine learning.",
    )
    index(
        db, "doc:rust",
        "Rust is a systems programming language. "
        "It focuses on safety, speed, and concurrency.",
    )
    index(
        db, "doc:cooking",
        "Cooking is the art of preparing food. "
        "Recipes include ingredients and step-by-step instructions.",
    )
    index(
        db, "doc:sqlite",
        "SQLite is an embedded database engine. "
        "It uses SQL for querying and supports full-text search via FTS5.",
    )
    return db


class TestSearchLex:
    def test_empty_query(self, populated_db):
        results = search_lex(populated_db, "")
        assert results == []

    def test_basic_search(self, populated_db):
        results = search_lex(populated_db, "programming language")
        assert len(results) >= 1
        doc_keys = [r.doc_key for r in results]
        assert "doc:python" in doc_keys or "doc:rust" in doc_keys

    def test_specific_term(self, populated_db):
        results = search_lex(populated_db, "cooking recipes food")
        assert len(results) >= 1
        assert results[0].doc_key == "doc:cooking"

    def test_top_n_limit(self, populated_db):
        results = search_lex(populated_db, "programming", top_n=1)
        assert len(results) <= 1

    def test_no_results(self, populated_db):
        results = search_lex(populated_db, "quantum entanglement physics")
        assert len(results) == 0

    def test_result_fields(self, populated_db):
        results = search_lex(populated_db, "SQLite database")
        assert len(results) >= 1
        r = results[0]
        assert r.chunk_id is not None
        assert r.record_id is not None
        assert r.doc_key == "doc:sqlite"
        assert r.bm25_score > 0
        assert r.chunk_text is not None

    def test_bm25_ordering(self, populated_db):
        results = search_lex(populated_db, "programming language safety")
        if len(results) >= 2:
            # Scores should be in descending order
            assert results[0].bm25_score >= results[1].bm25_score
