"""Tests for target-explain: citation and evidence generation."""

from __future__ import annotations

import pytest

from target_search.db import open_db
from target_search.explain import (
    CorrectionEvidence,
    Explanation,
    _build_citation,
    _dominant_factors,
    explain_result,
    explain_results,
    format_explanation,
)
from target_search.rank import FeatureBreakdown, RankedResult


def _make_result(
    chunk_id=1,
    record_id=1,
    doc_key="doc:test",
    chunk_index=0,
    chunk_text="The quick brown fox jumps over the lazy dog.",
    final_score=0.75,
    features=None,
    reason_codes=None,
    source_type=None,
    trust_level=1.0,
    created_at=None,
) -> RankedResult:
    """Helper to create a RankedResult for testing."""
    if features is None:
        features = FeatureBreakdown(S=0.8, L=0.6, R=0.5, C=0.0, T=1.0)
    if reason_codes is None:
        reason_codes = ["SEM_MATCH", "LEX_MATCH", "HIGH_TRUST"]
    return RankedResult(
        chunk_id=chunk_id,
        record_id=record_id,
        doc_key=doc_key,
        chunk_index=chunk_index,
        chunk_text=chunk_text,
        final_score=final_score,
        features=features,
        reason_codes=reason_codes,
        source_type=source_type,
        trust_level=trust_level,
        created_at=created_at,
    )


class TestBuildCitation:
    def test_basic_citation(self):
        r = _make_result()
        cit = _build_citation(r)
        assert "[doc:test, chunk 0]" in cit
        assert "quick brown fox" in cit
        assert "score: 0.7500" in cit
        assert "SEM_MATCH" in cit

    def test_long_text_truncated(self):
        r = _make_result(chunk_text="x" * 200)
        cit = _build_citation(r, preview_len=50)
        assert "..." in cit

    def test_short_text_not_truncated(self):
        r = _make_result(chunk_text="short")
        cit = _build_citation(r)
        assert "..." not in cit

    def test_no_reason_codes(self):
        r = _make_result(reason_codes=[])
        cit = _build_citation(r)
        assert "reasons: none" in cit

    def test_newlines_stripped(self):
        r = _make_result(chunk_text="line one\nline two\nline three")
        cit = _build_citation(r)
        assert "\n" not in cit.split('"')[1]  # text between quotes


class TestDominantFactors:
    def test_identifies_top_factors(self):
        r = _make_result(features=FeatureBreakdown(S=0.9, L=0.1, R=0.5, C=0.0, T=0.8))
        factors = _dominant_factors(r, top_n=3)
        assert len(factors) <= 3
        assert "Semantic similarity" in factors[0]

    def test_skips_negligible_factors(self):
        r = _make_result(features=FeatureBreakdown(S=0.0, L=0.0, R=0.0, C=0.005, T=0.0))
        factors = _dominant_factors(r)
        assert len(factors) == 0

    def test_all_zero(self):
        r = _make_result(features=FeatureBreakdown(S=0.0, L=0.0, R=0.0, C=0.0, T=0.0))
        factors = _dominant_factors(r)
        assert factors == []

    def test_respects_top_n(self):
        r = _make_result(features=FeatureBreakdown(S=0.9, L=0.8, R=0.7, C=0.6, T=0.5))
        factors = _dominant_factors(r, top_n=2)
        assert len(factors) == 2


class TestExplainResult:
    def test_basic_explanation(self):
        r = _make_result()
        expl = explain_result(r)
        assert isinstance(expl, Explanation)
        assert expl.doc_key == "doc:test"
        assert expl.final_score == 0.75
        assert expl.citation
        assert len(expl.reason_descriptions) == 3
        assert "Semantically similar to query" in expl.reason_descriptions

    def test_evidence_pointer(self):
        r = _make_result(chunk_id=42, record_id=7)
        expl = explain_result(r)
        assert expl.evidence.chunk_id == 42
        assert expl.evidence.record_id == 7
        assert expl.evidence.doc_key == "doc:test"

    def test_no_conn_no_correction_evidence(self):
        r = _make_result()
        expl = explain_result(r, conn=None)
        assert expl.correction_evidence is None

    def test_as_dict(self):
        r = _make_result()
        expl = explain_result(r)
        d = expl.as_dict()
        assert "doc_key" in d
        assert "citation" in d
        assert "evidence" in d
        assert "features" in d
        assert "dominant_factors" in d
        assert "reason_descriptions" in d

    def test_unknown_reason_code(self):
        r = _make_result(reason_codes=["CUSTOM_CODE"])
        expl = explain_result(r)
        assert "CUSTOM_CODE" in expl.reason_descriptions


class TestExplainResults:
    def test_multiple_results(self):
        results = [
            _make_result(chunk_id=1, doc_key="doc:a"),
            _make_result(chunk_id=2, doc_key="doc:b"),
            _make_result(chunk_id=3, doc_key="doc:c"),
        ]
        explanations = explain_results(results)
        assert len(explanations) == 3
        assert explanations[0].doc_key == "doc:a"
        assert explanations[2].doc_key == "doc:c"

    def test_empty_results(self):
        explanations = explain_results([])
        assert explanations == []


class TestFormatExplanation:
    def test_basic_format(self):
        r = _make_result()
        expl = explain_result(r)
        text = format_explanation(expl)
        assert "Citation:" in text
        assert "Why:" in text
        assert "Signals:" in text

    def test_verbose_includes_features(self):
        r = _make_result()
        expl = explain_result(r)
        text = format_explanation(expl, verbose=True)
        assert "Features:" in text
        assert "S=" in text
        assert "L=" in text

    def test_not_verbose_excludes_features(self):
        r = _make_result()
        expl = explain_result(r)
        text = format_explanation(expl, verbose=False)
        assert "Features:" not in text

    def test_with_correction_evidence(self):
        r = _make_result(reason_codes=["CORRECTED"])
        expl = explain_result(r)
        # Manually add correction evidence
        expl.correction_evidence = CorrectionEvidence(
            correctors=["doc:v2"],
            corrected=[],
            edges=[{
                "corrector": "doc:v2", "corrected": "doc:test",
                "type": "supersedes", "confidence": 1.0,
            }],
        )
        text = format_explanation(expl)
        assert "Corrected by:" in text
        assert "doc:v2" in text


class TestWithDatabase:
    """Integration tests using a real database."""

    @pytest.fixture
    def db(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        conn = open_db(db_path)
        yield conn
        conn.close()

    def test_correction_evidence_from_db(self, db):
        from target_search.correct import add_correction
        from target_search.ingest import index

        index(db, "doc:old", "The server runs on port 8080.")
        index(db, "doc:new", "The server now runs on port 3000.")
        add_correction(db, "doc:new", "doc:old", "supersedes", 1.0, "Port changed")

        r = _make_result(doc_key="doc:old")
        expl = explain_result(r, conn=db)
        assert expl.correction_evidence is not None
        assert "doc:new" in expl.correction_evidence.correctors

    def test_no_correction_returns_none(self, db):
        from target_search.ingest import index

        index(db, "doc:standalone", "No corrections here.")
        r = _make_result(doc_key="doc:standalone")
        expl = explain_result(r, conn=db)
        assert expl.correction_evidence is None

    def test_end_to_end_explain_with_query(self, db):
        """Full integration: index, correct, query, explain."""
        from target_search.correct import add_correction
        from target_search.ingest import index
        from target_search.lex import search_lex
        from target_search.rank import RankWeights, rank

        index(db, "doc:v1", "The game was lost by the home team.")
        index(db, "doc:v2", "Actually the home team won the game decisively.")
        add_correction(db, "doc:v2", "doc:v1", "supersedes", 1.0, "Outcome corrected")

        lex_results = search_lex(db, "game", 10)
        weights = RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15)
        ranked = rank(lex_results=lex_results, weights=weights, conn=db)

        explanations = explain_results(ranked, conn=db)
        assert len(explanations) == 2

        # doc:v2 (corrector) should be first
        assert explanations[0].doc_key == "doc:v2"
        assert "CORRECTOR" in explanations[0].reason_codes
        assert explanations[0].correction_evidence is not None
        assert "doc:v1" in explanations[0].correction_evidence.corrected

        # doc:v1 (corrected) should be second
        assert explanations[1].doc_key == "doc:v1"
        assert "CORRECTED" in explanations[1].reason_codes
        assert explanations[1].correction_evidence is not None
        assert "doc:v2" in explanations[1].correction_evidence.correctors

        # Both should have valid citations
        for expl in explanations:
            assert expl.citation
            assert "score:" in expl.citation
            assert expl.evidence.chunk_id > 0
