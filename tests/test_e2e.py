from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from target_search.correct import add_correction, get_correction_chain
from target_search.db import open_db
from target_search.explain import explain_results
from target_search.ingest import index
from target_search.lex import search_lex
from target_search.rank import RankWeights, rank

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "e2e"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"


def _load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _index_manifest(conn, manifest: dict) -> None:
    for item in manifest["fixtures"]:
        text = (FIXTURE_DIR / item["file"]).read_text(encoding="utf-8")
        metadata = {
            "source_type": item.get("source_type"),
            "trust_level": item.get("trust_level", 1.0),
            "created_at": item.get("created_at"),
        }
        index(conn, item["doc_key"], text, metadata=metadata)

    for edge in manifest.get("corrections", []):
        add_correction(
            conn,
            edge["corrector"],
            edge["corrected"],
            reason=edge.get("reason"),
        )


@pytest.fixture()
def e2e_db(tmp_path):
    db_path = tmp_path / "target-e2e.db"
    conn = open_db(db_path)
    manifest = _load_manifest()
    _index_manifest(conn, manifest)
    yield conn, manifest
    conn.close()


def _doc_keys(results):
    return [r.doc_key for r in results]


def _find_rank(doc_keys: list[str], target: str) -> int:
    return doc_keys.index(target)


def test_pipeline_topical_retrieval_lex(e2e_db):
    conn, _ = e2e_db

    queries = [
        ("Three Laws positronic", "robotics"),
        ("psychohistory galactic empire", "space"),
        ("improbability drive", "comedy"),
        ("Keplerian", "contact"),
    ]

    topic_prefix = {
        "robotics": ("encyclopedia:robotics", "bulletin:robotics", "manual:robotics"),
        "space": ("encyclopedia:space", "manifest:space", "bulletin:space", "rumor:space"),
        "comedy": ("guide:comedy",),
        "contact": ("report:contact", "transmission:contact", "distress:contact"),
    }

    for query, topic in queries:
        ranked = rank(
            lex_results=search_lex(conn, query, top_n=20),
            sem_results=None,
            weights=RankWeights(
                semantic=0.0,
                lexical=0.20,
                recency=0.15,
                correction=0.50,
                trust=0.15,
            ),
            conn=conn,
        )[:3]
        assert ranked, f"No results for {query}"
        # Chunk-level retrieval can include occasional cross-topic tails.
        # Require top-2 topical purity.
        top_two = ranked[:2]
        assert all(r.doc_key.startswith(topic_prefix[topic]) for r in top_two)


def test_cross_topic_isolation_lex(e2e_db):
    conn, _ = e2e_db

    ranked = rank(
        lex_results=search_lex(conn, "towel requisition hitchhiker", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15),
        conn=conn,
    )[:5]

    keys = _doc_keys(ranked)
    assert any(k.startswith("guide:comedy") for k in keys)
    assert not any(k.startswith("encyclopedia:robotics") for k in keys)


@pytest.mark.parametrize(
    "query,must_outrank",
    [
        (
            "terasynaptic cycles production",
            ("bulletin:robotics:positronic-errata", "encyclopedia:robotics:positronic-brain"),
        ),
        (
            "prometheus passenger capacity",
            ("manifest:space:prometheus-corrected", "manifest:space:prometheus"),
        ),
        (
            "Alpha shortest route",
            ("bulletin:space:route-beta9", "encyclopedia:space:route-alpha7"),
        ),
    ],
)
def test_correction_pairs_must_outrank_in_lex_mode(e2e_db, query, must_outrank):
    conn, _ = e2e_db

    ranked = rank(
        lex_results=search_lex(conn, query, top_n=20),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15),
        conn=conn,
    )
    keys = _doc_keys(ranked)
    higher, lower = must_outrank
    assert _find_rank(keys, higher) < _find_rank(keys, lower)


def test_trust_weighting_with_identical_content(tmp_path):
    conn = open_db(tmp_path / "trust.db")
    text = "The reactor emits blue Cherenkov light during startup sequence."

    index(
        conn,
        "report:trust:high",
        text,
        metadata={"source_type": "memory", "trust_level": 1.0, "created_at": "2026-04-01"},
    )
    index(
        conn,
        "rumor:trust:low",
        text,
        metadata={"source_type": "dream", "trust_level": 0.2, "created_at": "2026-04-01"},
    )

    ranked = rank(
        lex_results=search_lex(conn, "reactor emits blue light", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.25, recency=0.15, correction=0.0, trust=0.60),
        conn=conn,
    )

    keys = _doc_keys(ranked)
    assert _find_rank(keys, "report:trust:high") < _find_rank(keys, "rumor:trust:low")
    conn.close()


def test_recency_weighting_with_identical_content(tmp_path):
    conn = open_db(tmp_path / "recency.db")
    text = "Hyperspace beacon maintenance uses phased plasma relays."

    index(
        conn,
        "report:recency:old",
        text,
        metadata={"source_type": "memory", "trust_level": 1.0, "created_at": "2020-01-01"},
    )
    index(
        conn,
        "report:recency:new",
        text,
        metadata={"source_type": "memory", "trust_level": 1.0, "created_at": "2026-04-01"},
    )

    ranked = rank(
        lex_results=search_lex(conn, "hyperspace beacon maintenance", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.20, recency=0.80, correction=0.0, trust=0.0),
        reference_date=date(2026, 4, 25),
        conn=conn,
    )

    keys = _doc_keys(ranked)
    assert _find_rank(keys, "report:recency:new") < _find_rank(keys, "report:recency:old")
    conn.close()


def test_explain_output_contains_evidence_and_features(e2e_db):
    conn, _ = e2e_db

    ranked = rank(
        lex_results=search_lex(conn, "prometheus passenger capacity", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15),
        conn=conn,
    )[:3]

    explanations = explain_results(ranked, conn=conn)
    assert explanations

    for expl in explanations:
        assert expl.citation
        assert expl.evidence.doc_key == expl.doc_key
        assert set(expl.features.keys()) == {"S", "L", "R", "C", "T"}

    corr = [e for e in explanations if e.doc_key == "manifest:space:prometheus-corrected"][0]
    assert corr.correction_evidence is not None
    assert "manifest:space:prometheus" in corr.correction_evidence.corrected


def test_empty_corpus_returns_no_results(tmp_path):
    conn = open_db(tmp_path / "empty.db")
    results = search_lex(conn, "anything", top_n=10)
    assert results == []
    conn.close()


def test_single_document_corpus(tmp_path):
    conn = open_db(tmp_path / "single.db")
    index(conn, "doc:single", "A single distress beacon pulse was received.")
    ranked = rank(
        lex_results=search_lex(conn, "distress beacon", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.25, recency=0.15, correction=0.0, trust=0.60),
        conn=conn,
    )
    assert len(ranked) == 1
    assert ranked[0].doc_key == "doc:single"
    conn.close()


def test_reindex_idempotency(e2e_db):
    conn, manifest = e2e_db

    first = [r.doc_key for r in rank(
        lex_results=search_lex(conn, "Three Laws positronic", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15),
        conn=conn,
    )[:5]]

    _index_manifest(conn, manifest)

    second = [r.doc_key for r in rank(
        lex_results=search_lex(conn, "Three Laws positronic", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15),
        conn=conn,
    )[:5]]

    assert first == second


def test_cjk_content_query(e2e_db):
    conn, _ = e2e_db
    ranked = rank(
        lex_results=search_lex(conn, "farstar_colony_signal_14903", top_n=10),
        sem_results=None,
        weights=RankWeights(semantic=0.0, lexical=0.25, recency=0.15, correction=0.0, trust=0.60),
        conn=conn,
    )
    keys = _doc_keys(ranked)
    assert "transmission:contact:farstar-colony" in keys


def test_correction_chain_presence(e2e_db):
    conn, _ = e2e_db
    chain = get_correction_chain(conn, "manifest:space:prometheus")
    assert "manifest:space:prometheus-corrected" in chain["correctors"]
    assert chain["edges"]


@pytest.mark.slow
def test_semantic_and_hybrid_modes_e2e(e2e_db):
    sem = pytest.importorskip("target_search.sem")
    conn, manifest = e2e_db

    # build embeddings
    sem.index_embeddings(conn)

    # verify two representative queries in sem/hybrid modes
    checks = [
        ("robot ethics and positronic brain", "encyclopedia:robotics:ethics"),
        ("alien silicon communication pulses", "report:contact:xenolinguistics"),
    ]

    for query, expected in checks:
        sem_ranked = rank(
            lex_results=None,
            sem_results=sem.search_sem(conn, query, top_n=10),
            weights=RankWeights(
                semantic=0.6,
                lexical=0.0,
                recency=0.15,
                correction=0.10,
                trust=0.15,
            ),
            conn=conn,
        )[:5]
        hybrid_ranked = rank(
            lex_results=search_lex(conn, query, top_n=10),
            sem_results=sem.search_sem(conn, query, top_n=10),
            weights=RankWeights(),
            conn=conn,
        )[:5]

        sem_keys = _doc_keys(sem_ranked)
        hybrid_keys = _doc_keys(hybrid_ranked)
        assert expected in sem_keys
        assert expected in hybrid_keys

    # reindex should not break semantic pipeline
    _index_manifest(conn, manifest)
    after = rank(
        lex_results=search_lex(conn, "improbability drive", top_n=10),
        sem_results=sem.search_sem(conn, "improbability drive", top_n=10),
        weights=RankWeights(),
        conn=conn,
    )[:5]
    assert after
