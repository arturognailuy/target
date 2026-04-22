"""target-sem: semantic search with sqlite-vec and sentence-transformers."""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

# Lazy-loaded globals
_model = None
_model_name: str | None = None

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 default
DEFAULT_MODEL = "all-MiniLM-L6-v2"


def _serialize_f32(vector: list[float] | np.ndarray) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec."""
    if hasattr(vector, "tolist"):
        vector = vector.tolist()
    return struct.pack(f"{len(vector)}f", *vector)


def _load_model(model_name: str = DEFAULT_MODEL):
    """Lazy-load sentence-transformers model."""
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError(
            "sentence-transformers is required for semantic search. "
            "Install with: pip install target-search[semantic]"
        ) from e
    _model = SentenceTransformer(model_name)
    _model_name = model_name
    return _model


def embed_text(text: str, model_name: str = DEFAULT_MODEL) -> list[float]:
    """Embed a single text string, returning a float vector."""
    model = _load_model(model_name)
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()


def embed_texts(texts: list[str], model_name: str = DEFAULT_MODEL) -> list[list[float]]:
    """Embed multiple texts in batch, returning list of float vectors."""
    if not texts:
        return []
    model = _load_model(model_name)
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return [v.tolist() for v in vecs]


def ensure_vec_table(conn: sqlite3.Connection, dim: int = EMBEDDING_DIM) -> None:
    """Create the sqlite-vec virtual table if it doesn't exist."""
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except ImportError as e:
        raise ImportError(
            "sqlite-vec is required for semantic search. "
            "Install with: pip install target-search[semantic]"
        ) from e

    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec "
        f"USING vec0(embedding float[{dim}] distance_metric=cosine)"
    )

    # Metadata table linking chunk_vec rowids to chunk ids + model info
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunk_embeddings (
            chunk_id INTEGER NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, model)
        )
    """)


def index_embeddings(
    conn: sqlite3.Connection,
    model_name: str = DEFAULT_MODEL,
    dim: int = EMBEDDING_DIM,
    batch_size: int = 64,
) -> int:
    """Embed all chunks that don't have embeddings yet. Returns count of newly embedded chunks."""
    ensure_vec_table(conn, dim)

    # Find chunks without embeddings for this model
    rows = conn.execute(
        """
        SELECT rc.id, rc.chunk_text
        FROM record_chunks rc
        LEFT JOIN chunk_embeddings ce ON ce.chunk_id = rc.id AND ce.model = ?
        WHERE ce.chunk_id IS NULL
        """,
        (model_name,),
    ).fetchall()

    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        texts = [r["chunk_text"] for r in batch]
        vectors = embed_texts(texts, model_name)

        for row, vec in zip(batch, vectors):
            chunk_id = row["id"]
            conn.execute(
                "INSERT OR REPLACE INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                (chunk_id, _serialize_f32(vec)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO chunk_embeddings(chunk_id, model, dim) VALUES (?, ?, ?)",
                (chunk_id, model_name, dim),
            )
        total += len(batch)

    conn.commit()
    return total


def remove_embeddings(conn: sqlite3.Connection, chunk_ids: list[int]) -> None:
    """Remove embeddings for deleted chunks."""
    if not chunk_ids:
        return
    placeholders = ",".join("?" * len(chunk_ids))
    conn.execute(f"DELETE FROM chunk_vec WHERE rowid IN ({placeholders})", chunk_ids)
    conn.execute(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})", chunk_ids)
    conn.commit()


@dataclass
class SemResult:
    """A single semantic search result."""

    chunk_id: int
    record_id: int
    doc_key: str
    chunk_index: int
    chunk_text: str
    cosine_score: float  # 1.0 - cosine_distance (higher = more similar)
    source_type: str | None
    trust_level: float
    created_at: str | None


def search_sem(
    conn: sqlite3.Connection,
    query: str,
    top_n: int = 20,
    model_name: str = DEFAULT_MODEL,
    dim: int = EMBEDDING_DIM,
) -> list[SemResult]:
    """Search indexed documents using semantic similarity.

    Returns up to top_n results ordered by cosine similarity (higher = better).
    """
    if not query.strip():
        return []

    ensure_vec_table(conn, dim)

    query_vec = embed_text(query, model_name)

    rows = conn.execute(
        """
        SELECT
            cv.rowid AS chunk_id,
            cv.distance AS cosine_distance,
            rc.record_id,
            r.doc_key,
            rc.chunk_index,
            rc.chunk_text,
            r.source_type,
            r.trust_level,
            r.created_at
        FROM chunk_vec cv
        JOIN record_chunks rc ON rc.id = cv.rowid
        JOIN records r ON r.id = rc.record_id
        WHERE cv.embedding MATCH ?
            AND k = ?
        ORDER BY cv.distance
        """,
        (_serialize_f32(query_vec), top_n),
    ).fetchall()

    return [
        SemResult(
            chunk_id=row["chunk_id"],
            record_id=row["record_id"],
            doc_key=row["doc_key"],
            chunk_index=row["chunk_index"],
            chunk_text=row["chunk_text"],
            cosine_score=1.0 - row["cosine_distance"],
            source_type=row["source_type"],
            trust_level=row["trust_level"],
            created_at=row["created_at"],
        )
        for row in rows
    ]
