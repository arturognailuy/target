"""target-lex: FTS5 / BM25 lexical search."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class LexResult:
    """A single lexical search result."""

    chunk_id: int
    record_id: int
    doc_key: str
    chunk_index: int
    chunk_text: str
    bm25_score: float
    source_type: str | None
    trust_level: float
    created_at: str | None


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize a free-text query for FTS5 MATCH.

    FTS5 treats bare words that collide with column names or operators
    (e.g. "in", "or", "not") as syntax — causing 'no such column' errors.
    We quote every token so they're all treated as literal search terms,
    then join with implicit AND.
    """
    import re

    # Strip anything that isn't alphanumeric, whitespace, or basic punctuation
    tokens = re.findall(r"[\w]+", query)
    if not tokens:
        return ""
    # Double-quote each token; FTS5 treats quoted strings as literals
    return " ".join(f'"{t}"' for t in tokens)


def search_lex(
    conn: sqlite3.Connection,
    query: str,
    top_n: int = 20,
) -> list[LexResult]:
    """Search indexed documents using FTS5 BM25 ranking.

    Returns up to top_n results ordered by BM25 relevance (lower = more relevant
    in SQLite FTS5; we negate so higher = better).
    """
    if not query.strip():
        return []

    # Sanitize query for FTS5: quote each token so words like "in" or
    # "improvement" aren't mistaken for column names or FTS5 operators.
    sanitized = _sanitize_fts5_query(query)
    if not sanitized:
        return []

    # FTS5 bm25() returns negative scores (more negative = more relevant)
    # We negate to make higher = better
    rows = conn.execute(
        """
        SELECT
            rc.id AS chunk_id,
            rc.record_id,
            r.doc_key,
            rc.chunk_index,
            rc.chunk_text,
            -bm25(chunk_fts) AS bm25_score,
            r.source_type,
            r.trust_level,
            r.created_at
        FROM chunk_fts
        JOIN record_chunks rc ON rc.id = chunk_fts.rowid
        JOIN records r ON r.id = rc.record_id
        WHERE chunk_fts MATCH ?
        ORDER BY bm25(chunk_fts)
        LIMIT ?
        """,
        (sanitized, top_n),
    ).fetchall()

    return [
        LexResult(
            chunk_id=row["chunk_id"],
            record_id=row["record_id"],
            doc_key=row["doc_key"],
            chunk_index=row["chunk_index"],
            chunk_text=row["chunk_text"],
            bm25_score=row["bm25_score"],
            source_type=row["source_type"],
            trust_level=row["trust_level"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
