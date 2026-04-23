"""Tests for target-rank: weighted merge of search results."""

from __future__ import annotations

from datetime import date

import pytest

from target_search.rank import (
    FeatureBreakdown,
    RankedResult,
    RankWeights,
    _normalize_scores,
    _recency_score,
    _trust_score,
    rank,
)


# Mock result classes for testing (matching the interface of LexResult/SemResult)
class MockLexResult:
    def __init__(self, chunk_id, record_id=1, doc_key="doc:test", chunk_index=0,
                 chunk_text="test", bm25_score=0.0, source_type=None,
                 trust_level=1.0, created_at=None):
        self.chunk_id = chunk_id
        self.record_id = record_id
        self.doc_key = doc_key
        self.chunk_index = chunk_index
        self.chunk_text = chunk_text
        self.bm25_score = bm25_score
        self.source_type = source_type
        self.trust_level = trust_level
        self.created_at = created_at


class MockSemResult:
    def __init__(self, chunk_id, record_id=1, doc_key="doc:test", chunk_index=0,
                 chunk_text="test", cosine_score=0.0, source_type=None,
                 trust_level=1.0, created_at=None):
        self.chunk_id = chunk_id
        self.record_id = record_id
        self.doc_key = doc_key
        self.chunk_index = chunk_index
        self.chunk_text = chunk_text
        self.cosine_score = cosine_score
        self.source_type = source_type
        self.trust_level = trust_level
        self.created_at = created_at


class TestNormalizeScores:
    def test_basic(self):
        assert _normalize_scores([1, 2, 3]) == [0.0, 0.5, 1.0]

    def test_single_value(self):
        assert _normalize_scores([5.0]) == [1.0]

    def test_equal_values(self):
        assert _normalize_scores([3.0, 3.0, 3.0]) == [1.0, 1.0, 1.0]

    def test_empty(self):
        assert _normalize_scores([]) == []


class TestRecencyScore:
    def test_today(self):
        ref = date(2026, 4, 22)
        score = _recency_score("2026-04-22", ref)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_one_year_ago(self):
        ref = date(2026, 4, 22)
        score = _recency_score("2025-04-22", ref)
        assert score == pytest.approx(0.368, abs=0.01)  # e^(-1)

    def test_none(self):
        assert _recency_score(None) == 0.5

    def test_invalid(self):
        assert _recency_score("not-a-date") == 0.5


class TestTrustScore:
    def test_normal(self):
        assert _trust_score(0.5) == 0.5
        assert _trust_score(1.0) == 1.0

    def test_clamp(self):
        assert _trust_score(-0.5) == 0.0
        assert _trust_score(1.5) == 1.0


class TestRank:
    def test_empty(self):
        assert rank() == []

    def test_lex_only(self):
        lex = [
            MockLexResult(chunk_id=1, bm25_score=2.0, doc_key="doc:a"),
            MockLexResult(chunk_id=2, bm25_score=1.0, doc_key="doc:b"),
        ]
        results = rank(lex_results=lex)
        assert len(results) == 2
        assert isinstance(results[0], RankedResult)
        # Higher BM25 should rank higher
        assert results[0].chunk_id == 1

    def test_sem_only(self):
        sem = [
            MockSemResult(chunk_id=1, cosine_score=0.9, doc_key="doc:a"),
            MockSemResult(chunk_id=2, cosine_score=0.5, doc_key="doc:b"),
        ]
        results = rank(sem_results=sem)
        assert len(results) == 2
        assert results[0].chunk_id == 1

    def test_hybrid_merge(self):
        lex = [
            MockLexResult(chunk_id=1, bm25_score=2.0, doc_key="doc:a"),
            MockLexResult(chunk_id=2, bm25_score=1.0, doc_key="doc:b"),
        ]
        sem = [
            MockSemResult(chunk_id=2, cosine_score=0.9, doc_key="doc:b"),
            MockSemResult(chunk_id=3, cosine_score=0.8, doc_key="doc:c"),
        ]
        results = rank(lex_results=lex, sem_results=sem)
        # Should have 3 unique chunks
        assert len(results) == 3
        chunk_ids = {r.chunk_id for r in results}
        assert chunk_ids == {1, 2, 3}

    def test_feature_breakdown(self):
        lex = [MockLexResult(chunk_id=1, bm25_score=1.0, trust_level=0.8)]
        results = rank(lex_results=lex)
        r = results[0]
        assert isinstance(r.features, FeatureBreakdown)
        assert r.features.L == 1.0  # Only one, normalized to 1.0
        assert r.features.T == 0.8

    def test_reason_codes(self):
        lex = [MockLexResult(chunk_id=1, bm25_score=1.0, trust_level=0.9,
                             created_at="2026-04-22")]
        sem = [MockSemResult(chunk_id=1, cosine_score=0.9)]
        results = rank(lex_results=lex, sem_results=sem,
                       reference_date=date(2026, 4, 22))
        r = results[0]
        assert "LEX_MATCH" in r.reason_codes
        assert "SEM_MATCH" in r.reason_codes
        assert "HIGH_TRUST" in r.reason_codes
        assert "RECENT" in r.reason_codes

    def test_custom_weights(self):
        # With lexical weight = 0, semantic should dominate
        lex = [MockLexResult(chunk_id=1, bm25_score=10.0, doc_key="doc:a")]
        sem = [MockSemResult(chunk_id=2, cosine_score=0.9, doc_key="doc:b")]
        weights = RankWeights(semantic=1.0, lexical=0.0, recency=0.0, trust=0.0)
        results = rank(lex_results=lex, sem_results=sem, weights=weights)
        assert results[0].chunk_id == 2

    def test_zero_weight_disables(self):
        # With semantic weight=0, the S feature still gets computed
        # but doesn't affect the final score
        lex = [MockLexResult(chunk_id=1, bm25_score=5.0)]
        weights = RankWeights(semantic=0.0, lexical=1.0, recency=0.0, correction=0.0, trust=0.0)
        results = rank(lex_results=lex, weights=weights)
        # Final score should only reflect lexical
        assert results[0].final_score == pytest.approx(results[0].features.L * 1.0)

    def test_deterministic(self):
        lex = [
            MockLexResult(chunk_id=1, bm25_score=2.0, doc_key="doc:a"),
            MockLexResult(chunk_id=2, bm25_score=1.0, doc_key="doc:b"),
        ]
        r1 = rank(lex_results=lex)
        r2 = rank(lex_results=lex)
        assert [r.chunk_id for r in r1] == [r.chunk_id for r in r2]
        assert [r.final_score for r in r1] == [r.final_score for r in r2]

    def test_recency_affects_ranking(self):
        ref = date(2026, 4, 22)
        lex = [
            MockLexResult(chunk_id=1, bm25_score=1.0, doc_key="doc:old",
                          created_at="2024-01-01"),
            MockLexResult(chunk_id=2, bm25_score=1.0, doc_key="doc:new",
                          created_at="2026-04-20"),
        ]
        weights = RankWeights(semantic=0.0, lexical=0.3, recency=0.7, trust=0.0)
        results = rank(lex_results=lex, weights=weights, reference_date=ref)
        # Newer doc should rank higher
        assert results[0].doc_key == "doc:new"
