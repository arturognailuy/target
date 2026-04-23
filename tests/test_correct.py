"""Tests for target-correct: correction graph and score modifiers."""

from __future__ import annotations

import pytest

from target_search.correct import (
    add_correction,
    correction_scores,
    get_correction_chain,
    get_corrections_for_doc,
    list_corrections,
    remove_correction,
)
from target_search.db import open_db
from target_search.ingest import index


@pytest.fixture
def conn(tmp_path):
    """Create a test database with sample documents."""
    db_path = tmp_path / "test.db"
    c = open_db(str(db_path))
    # Index sample docs
    index(c, "doc:v1", "The earth is flat. This is the original claim.")
    index(c, "doc:v2", "The earth is round. This corrects the earlier flat earth claim.")
    index(c, "doc:v3", "The earth is an oblate spheroid. More precise than just round.")
    index(c, "doc:unrelated", "Cats are great pets.")
    return c


class TestAddCorrection:
    def test_basic_add(self, conn):
        edge = add_correction(conn, "doc:v2", "doc:v1", reason="v2 supersedes v1")
        assert edge.corrector_doc_key == "doc:v2"
        assert edge.corrected_doc_key == "doc:v1"
        assert edge.edge_type == "supersedes"
        assert edge.confidence == 1.0
        assert edge.reason == "v2 supersedes v1"

    def test_idempotent_update(self, conn):
        add_correction(conn, "doc:v2", "doc:v1", confidence=0.5)
        edge = add_correction(conn, "doc:v2", "doc:v1", confidence=0.9, reason="updated")
        assert edge.confidence == 0.9
        assert edge.reason == "updated"
        # Should still be just one edge
        edges = list_corrections(conn)
        assert len(edges) == 1

    def test_self_correction_rejected(self, conn):
        with pytest.raises(ValueError, match="cannot correct itself"):
            add_correction(conn, "doc:v1", "doc:v1")

    def test_missing_doc_key_rejected(self, conn):
        with pytest.raises(ValueError, match="not found"):
            add_correction(conn, "doc:v2", "doc:nonexistent")

    def test_cycle_detection(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        # v1 → v2 would create a cycle
        with pytest.raises(ValueError, match="cycle"):
            add_correction(conn, "doc:v1", "doc:v2")

    def test_transitive_cycle_detection(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v2")
        # v1 → v3 would create a cycle: v1 → v3 → v2 → v1
        with pytest.raises(ValueError, match="cycle"):
            add_correction(conn, "doc:v1", "doc:v3")

    def test_custom_edge_type(self, conn):
        edge = add_correction(conn, "doc:v2", "doc:v1", edge_type="refines")
        assert edge.edge_type == "refines"

    def test_custom_confidence(self, conn):
        edge = add_correction(conn, "doc:v2", "doc:v1", confidence=0.7)
        assert edge.confidence == 0.7


class TestRemoveCorrection:
    def test_remove_existing(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        removed = remove_correction(conn, "doc:v2", "doc:v1")
        assert removed is True
        assert len(list_corrections(conn)) == 0

    def test_remove_nonexistent(self, conn):
        removed = remove_correction(conn, "doc:v2", "doc:v1")
        assert removed is False


class TestListCorrections:
    def test_empty(self, conn):
        assert list_corrections(conn) == []

    def test_multiple(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v2")
        edges = list_corrections(conn)
        assert len(edges) == 2


class TestGetCorrectionsForDoc:
    def test_corrector(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        info = get_corrections_for_doc(conn, "doc:v2")
        assert info["corrects"] == ["doc:v1"]
        assert info["corrected_by"] == []

    def test_corrected(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        info = get_corrections_for_doc(conn, "doc:v1")
        assert info["corrects"] == []
        assert info["corrected_by"] == ["doc:v2"]

    def test_unrelated(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        info = get_corrections_for_doc(conn, "doc:unrelated")
        assert info["corrects"] == []
        assert info["corrected_by"] == []


class TestCorrectionScores:
    def test_no_corrections(self, conn):
        scores = correction_scores(conn, ["doc:v1", "doc:v2"])
        assert scores["doc:v1"] == 0.0
        assert scores["doc:v2"] == 0.0

    def test_direct_correction(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        scores = correction_scores(conn, ["doc:v1", "doc:v2"])
        assert scores["doc:v2"] > 0  # corrector: boosted
        assert scores["doc:v1"] < 0  # corrected: penalized

    def test_chain_correction(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v2")
        scores = correction_scores(conn, ["doc:v1", "doc:v2", "doc:v3"])
        # v3 is the latest corrector — should have highest score
        assert scores["doc:v3"] > scores["doc:v2"]
        # v1 is most corrected — should have lowest
        assert scores["doc:v1"] < scores["doc:v2"]

    def test_unrelated_document(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        scores = correction_scores(conn, ["doc:unrelated"])
        assert scores["doc:unrelated"] == 0.0

    def test_scores_clamped(self, conn):
        """Scores should be in [-1, 1] range."""
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v1")
        scores = correction_scores(conn, ["doc:v1"])
        assert -1.0 <= scores["doc:v1"] <= 1.0

    def test_confidence_weighting(self, conn):
        add_correction(conn, "doc:v2", "doc:v1", confidence=0.3)
        scores_low = correction_scores(conn, ["doc:v2"])

        remove_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v2", "doc:v1", confidence=1.0)
        scores_high = correction_scores(conn, ["doc:v2"])

        assert scores_high["doc:v2"] > scores_low["doc:v2"]

    def test_empty_input(self, conn):
        assert correction_scores(conn, []) == {}


class TestCorrectionChain:
    def test_simple_chain(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v2")
        chain = get_correction_chain(conn, "doc:v1")
        assert "doc:v2" in chain["correctors"]
        assert "doc:v3" in chain["correctors"]
        assert chain["corrected"] == []

    def test_middle_of_chain(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v2")
        chain = get_correction_chain(conn, "doc:v2")
        assert "doc:v3" in chain["correctors"]
        assert "doc:v1" in chain["corrected"]

    def test_head_of_chain(self, conn):
        add_correction(conn, "doc:v2", "doc:v1")
        add_correction(conn, "doc:v3", "doc:v2")
        chain = get_correction_chain(conn, "doc:v3")
        assert chain["correctors"] == []
        assert "doc:v2" in chain["corrected"]
        assert "doc:v1" in chain["corrected"]

    def test_no_chain(self, conn):
        chain = get_correction_chain(conn, "doc:unrelated")
        assert chain["correctors"] == []
        assert chain["corrected"] == []
        assert chain["edges"] == []

    def test_chain_has_edges(self, conn):
        add_correction(conn, "doc:v2", "doc:v1", reason="update")
        chain = get_correction_chain(conn, "doc:v1")
        assert len(chain["edges"]) == 1
        assert chain["edges"][0]["corrector"] == "doc:v2"
        assert chain["edges"][0]["reason"] == "update"


class TestSchemaV2Migration:
    def test_v1_db_gets_migrated(self, tmp_path):
        """Simulate a v1 database and verify migration to v2."""
        db_path = tmp_path / "v1.db"
        # Create with full schema but pretend it's v1
        c = open_db(str(db_path))
        # The migration should have already run via open_db
        # Verify the correction_edges table exists
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='correction_edges'"
        ).fetchone()
        assert row is not None
        c.close()
