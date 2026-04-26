"""Tests for target-eval: evaluation framework."""

from __future__ import annotations

import json

import pytest

from target_search.db import open_db
from target_search.eval import (
    EvalQuery,
    benchmark,
    diff_snapshot,
    evaluate,
    load_eval_set,
    load_snapshot,
    save_snapshot,
    snapshot,
    tune_weights,
)
from target_search.ingest import index


@pytest.fixture
def eval_db(tmp_path):
    """Create a test database with some indexed documents."""
    db_path = str(tmp_path / "test.db")
    conn = open_db(db_path)

    # Index a few documents with different topics
    index(conn, "doc:alpha", "The positronic brain operates at high speed with quantum circuits.")
    index(conn, "doc:beta", "Colony ship Prometheus carries 12000 passengers to the outer rim.")
    index(conn, "doc:gamma", "The improbability drive uses quantum fluctuations for travel.")
    index(conn, "doc:delta", "Hyperspace routes connect the core worlds to the periphery.")

    # Add a correction
    from target_search.correct import add_correction
    add_correction(conn, "doc:beta", "doc:alpha", reason="Updated info")

    return conn


@pytest.fixture
def eval_queries():
    return [
        EvalQuery(
            text="positronic brain speed",
            relevant_keys=["doc:alpha"],
            must_outrank=[["doc:beta", "doc:alpha"]],
        ),
        EvalQuery(
            text="colony ship passengers",
            relevant_keys=["doc:beta"],
        ),
        EvalQuery(
            text="improbability drive quantum",
            relevant_keys=["doc:gamma"],
        ),
    ]


class TestEvaluate:
    def test_basic_evaluate(self, eval_db, eval_queries):
        report = evaluate(eval_db, eval_queries, top_k=5, mode="lex")
        assert report.query_count == 3
        assert 0.0 <= report.precision_at_k <= 1.0
        assert 0.0 <= report.correction_recall <= 1.0
        assert 0.0 <= report.noise_rate <= 1.0
        assert len(report.per_query) == 3

    def test_empty_queries(self, eval_db):
        report = evaluate(eval_db, [], top_k=5, mode="lex")
        assert report.query_count == 0 or report.query_count == 1  # edge case

    def test_per_query_results(self, eval_db, eval_queries):
        report = evaluate(eval_db, eval_queries, top_k=5, mode="lex")
        for qr in report.per_query:
            assert qr.query_text
            assert isinstance(qr.top_keys, list)
            assert isinstance(qr.precision_at_k, float)

    def test_outrank_details(self, eval_db, eval_queries):
        report = evaluate(eval_db, eval_queries, top_k=5, mode="lex")
        # First query has a must_outrank pair
        qr = report.per_query[0]
        assert len(qr.outrank_details) == 1
        assert qr.outrank_details[0]["higher"] == "doc:beta"
        assert qr.outrank_details[0]["lower"] == "doc:alpha"


class TestSnapshot:
    def test_snapshot_and_save(self, eval_db, eval_queries, tmp_path):
        entries = snapshot(eval_db, eval_queries, top_k=5, mode="lex")
        assert len(entries) == 3

        path = tmp_path / "snap.json"
        save_snapshot(entries, path)
        assert path.exists()

        loaded = load_snapshot(path)
        assert len(loaded) == 3
        assert loaded[0].query_text == entries[0].query_text

    def test_diff_unchanged(self, eval_db, eval_queries, tmp_path):
        entries = snapshot(eval_db, eval_queries, top_k=5, mode="lex")
        path = tmp_path / "snap.json"
        save_snapshot(entries, path)

        current = snapshot(eval_db, eval_queries, top_k=5, mode="lex")
        saved = load_snapshot(path)
        diffs = diff_snapshot(saved, current)
        assert all(d.status == "unchanged" for d in diffs)

    def test_diff_changed(self, eval_db, eval_queries, tmp_path):
        entries = snapshot(eval_db, eval_queries, top_k=5, mode="lex")
        path = tmp_path / "snap.json"
        save_snapshot(entries, path)

        # Index new doc that will change results
        index(eval_db, "doc:new", "positronic brain speed test benchmark ultra fast")
        current = snapshot(eval_db, eval_queries, top_k=5, mode="lex")
        saved = load_snapshot(path)
        diffs = diff_snapshot(saved, current)

        changed_count = sum(1 for d in diffs if d.status != "unchanged")
        # At least one query should have different results
        assert changed_count >= 1


class TestLoadEvalSet:
    def test_load_eval_set(self, tmp_path):
        data = {
            "queries": [
                {
                    "text": "test query",
                    "relevant_keys": ["key1"],
                    "must_outrank": [["key1", "key2"]],
                    "topic": "test",
                }
            ]
        }
        path = tmp_path / "eval.json"
        path.write_text(json.dumps(data))
        queries = load_eval_set(path)
        assert len(queries) == 1
        assert queries[0].text == "test query"
        assert queries[0].relevant_keys == ["key1"]
        assert queries[0].must_outrank == [["key1", "key2"]]

    def test_load_with_expected_top_keys_fallback(self, tmp_path):
        """Test backward compatibility with expected_top_keys field."""
        data = {
            "queries": [
                {"text": "q1", "expected_top_keys": ["k1", "k2"]}
            ]
        }
        path = tmp_path / "eval.json"
        path.write_text(json.dumps(data))
        queries = load_eval_set(path)
        assert queries[0].relevant_keys == ["k1", "k2"]


class TestTuneWeights:
    def test_tune_basic(self, eval_db, eval_queries):
        result = tune_weights(eval_db, eval_queries, top_k=5, mode="lex", steps=3)
        assert "best_weights" in result
        assert "best_score" in result
        assert "total_combinations" in result
        assert result["total_combinations"] > 0
        assert result["best_score"] >= 0.0

    def test_tune_returns_top_10(self, eval_db, eval_queries):
        result = tune_weights(eval_db, eval_queries, top_k=5, mode="lex", steps=3)
        assert "top_10" in result
        assert len(result["top_10"]) <= 10
        # Should be sorted by combined_score descending
        scores = [r["combined_score"] for r in result["top_10"]]
        assert scores == sorted(scores, reverse=True)


class TestBenchmark:
    def test_benchmark_basic(self, eval_db, eval_queries):
        result = benchmark(eval_db, eval_queries, mode="lex", iterations=3)
        assert result["query_count"] == 3
        assert result["iterations_per_query"] == 3
        assert result["median_ms"] > 0
        assert len(result["per_query"]) == 3
        for t in result["per_query"]:
            assert t["mean_ms"] > 0
            assert t["min_ms"] <= t["max_ms"]
