"""target-ingest: document ingestion, normalization, and chunking."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field


@dataclass
class ChunkResult:
    """Result of chunking a document."""

    chunk_index: int
    text: str
    token_count: int


@dataclass
class IngestResult:
    """Result of ingesting a document."""

    doc_key: str
    record_id: int
    chunks: int
    replaced: bool


@dataclass
class Metadata:
    """Optional document metadata."""

    source_type: str | None = None
    created_at: str | None = None
    trust_level: float = 1.0
    extra: dict = field(default_factory=dict)


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return max(1, len(text) // 4)


def chunk_text(
    text: str,
    max_chunk_tokens: int = 256,
    overlap_tokens: int = 32,
) -> list[ChunkResult]:
    """Split text into chunks respecting paragraph boundaries.

    Strategy:
    1. Split on double newlines (paragraph boundaries).
    2. Accumulate paragraphs until max_chunk_tokens is reached.
    3. Emit chunk, carry last paragraph as overlap for next chunk.
    """
    if not text.strip():
        return []

    paragraphs = re.split(r"\n\s*\n", text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[ChunkResult] = []
    current_parts: list[str] = []
    current_tokens = 0
    chunk_index = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)

        # If a single paragraph exceeds max, emit it as its own chunk
        if para_tokens > max_chunk_tokens and not current_parts:
            chunks.append(ChunkResult(
                chunk_index=chunk_index,
                text=para,
                token_count=para_tokens,
            ))
            chunk_index += 1
            continue

        # If adding this paragraph exceeds max, emit current chunk
        if current_tokens + para_tokens > max_chunk_tokens and current_parts:
            chunk_text_str = "\n\n".join(current_parts)
            chunks.append(ChunkResult(
                chunk_index=chunk_index,
                text=chunk_text_str,
                token_count=estimate_tokens(chunk_text_str),
            ))
            chunk_index += 1

            # Overlap: keep last paragraph if it fits within overlap budget
            last = current_parts[-1]
            if estimate_tokens(last) <= overlap_tokens:
                current_parts = [last]
                current_tokens = estimate_tokens(last)
            else:
                current_parts = []
                current_tokens = 0

        current_parts.append(para)
        current_tokens += para_tokens

    # Emit remaining
    if current_parts:
        chunk_text_str = "\n\n".join(current_parts)
        chunks.append(ChunkResult(
            chunk_index=chunk_index,
            text=chunk_text_str,
            token_count=estimate_tokens(chunk_text_str),
        ))

    return chunks


def infer_metadata(doc_key: str) -> Metadata:
    """Infer metadata from doc_key conventions.

    Conventions:
    - Keys starting with 'memory:' → source_type='memory', trust=1.0
    - Keys starting with 'email:' → source_type='email', trust=1.0
    - Keys starting with 'dream:' → source_type='dream', trust=0.5 (reflective)
    - Date patterns (YYYY-MM-DD) in key → created_at
    """
    meta = Metadata()

    # Source type from prefix
    if ":" in doc_key:
        prefix = doc_key.split(":")[0].lower()
        type_map = {"memory": "memory", "email": "email", "dream": "dream"}
        meta.source_type = type_map.get(prefix)
        if prefix == "dream":
            meta.trust_level = 0.5

    # Date extraction
    date_match = re.search(r"\d{4}-\d{2}-\d{2}", doc_key)
    if date_match:
        meta.created_at = date_match.group()

    return meta


def index(
    conn: sqlite3.Connection,
    doc_key: str,
    doc_content: str,
    metadata: dict | None = None,
    max_chunk_tokens: int = 256,
    overlap_tokens: int = 32,
) -> IngestResult:
    """Index a document: normalize, chunk, and store.

    Idempotent: re-indexing the same doc_key replaces previous chunks.
    """
    # Merge explicit metadata with inferred
    inferred = infer_metadata(doc_key)
    if metadata:
        if "source_type" in metadata:
            inferred.source_type = metadata["source_type"]
        if "created_at" in metadata:
            inferred.created_at = metadata["created_at"]
        if "trust_level" in metadata:
            inferred.trust_level = metadata["trust_level"]
        inferred.extra = {k: v for k, v in metadata.items()
                          if k not in ("source_type", "created_at", "trust_level")}

    # Check if record exists (for replaced flag)
    existing = conn.execute(
        "SELECT id FROM records WHERE doc_key = ?", (doc_key,)
    ).fetchone()
    replaced = existing is not None

    if replaced:
        record_id = existing["id"]
        # Delete old chunks (cascade triggers FTS cleanup)
        conn.execute("DELETE FROM record_chunks WHERE record_id = ?", (record_id,))
        conn.execute(
            """UPDATE records SET source_type=?, created_at=?, updated_at=datetime('now'),
               trust_level=?, metadata_json=? WHERE id=?""",
            (
                inferred.source_type,
                inferred.created_at,
                inferred.trust_level,
                json.dumps(inferred.extra) if inferred.extra else None,
                record_id,
            ),
        )
    else:
        cursor = conn.execute(
            """INSERT INTO records (doc_key, source_type, created_at, trust_level, metadata_json)
               VALUES (?, ?, ?, ?, ?)""",
            (
                doc_key,
                inferred.source_type,
                inferred.created_at,
                inferred.trust_level,
                json.dumps(inferred.extra) if inferred.extra else None,
            ),
        )
        record_id = cursor.lastrowid

    # Chunk and insert
    chunks = chunk_text(doc_content, max_chunk_tokens, overlap_tokens)
    for chunk in chunks:
        conn.execute(
            """INSERT INTO record_chunks (record_id, chunk_index, chunk_text, token_count)
               VALUES (?, ?, ?, ?)""",
            (record_id, chunk.chunk_index, chunk.text, chunk.token_count),
        )

    conn.commit()

    return IngestResult(
        doc_key=doc_key,
        record_id=record_id,
        chunks=len(chunks),
        replaced=replaced,
    )
