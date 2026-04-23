"""target-correct: correction graph and score modifiers.

Maintains a directed graph of correction relationships between documents.
A correction edge (A → B) means "document A corrects/supersedes document B."
Correctors are boosted; corrected documents are penalized in ranking.
Correction chains propagate transitively: if A corrects B and B corrects C,
then A dominates C.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class CorrectionEdge:
    """A single correction relationship."""

    id: int
    corrector_doc_key: str
    corrected_doc_key: str
    edge_type: str
    confidence: float
    reason: str | None
    created_at: str


def add_correction(
    conn: sqlite3.Connection,
    corrector_doc_key: str,
    corrected_doc_key: str,
    edge_type: str = "supersedes",
    confidence: float = 1.0,
    reason: str | None = None,
) -> CorrectionEdge:
    """Add a correction edge: corrector_doc_key corrects corrected_doc_key.

    Idempotent: re-adding the same edge updates confidence and reason.
    Validates that both doc_keys exist in the records table.
    """
    # Validate doc_keys exist
    for key in (corrector_doc_key, corrected_doc_key):
        row = conn.execute("SELECT id FROM records WHERE doc_key = ?", (key,)).fetchone()
        if row is None:
            raise ValueError(f"doc_key not found in records: {key}")

    # Prevent self-correction
    if corrector_doc_key == corrected_doc_key:
        raise ValueError("A document cannot correct itself")

    # Detect cycles: would this edge create a cycle?
    if _would_create_cycle(conn, corrector_doc_key, corrected_doc_key):
        raise ValueError(
            f"Adding edge {corrector_doc_key} → {corrected_doc_key} would create a cycle"
        )

    cursor = conn.execute(
        """INSERT INTO correction_edges (corrector_doc_key, corrected_doc_key, edge_type,
               confidence, reason)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(corrector_doc_key, corrected_doc_key)
           DO UPDATE SET confidence=excluded.confidence, reason=excluded.reason,
                         edge_type=excluded.edge_type
           RETURNING id, corrector_doc_key, corrected_doc_key, edge_type, confidence,
                     reason, created_at""",
        (corrector_doc_key, corrected_doc_key, edge_type, confidence, reason),
    )
    row = cursor.fetchone()
    conn.commit()
    return CorrectionEdge(
        id=row["id"],
        corrector_doc_key=row["corrector_doc_key"],
        corrected_doc_key=row["corrected_doc_key"],
        edge_type=row["edge_type"],
        confidence=row["confidence"],
        reason=row["reason"],
        created_at=row["created_at"],
    )


def remove_correction(
    conn: sqlite3.Connection,
    corrector_doc_key: str,
    corrected_doc_key: str,
) -> bool:
    """Remove a correction edge. Returns True if an edge was removed."""
    cursor = conn.execute(
        "DELETE FROM correction_edges WHERE corrector_doc_key = ? AND corrected_doc_key = ?",
        (corrector_doc_key, corrected_doc_key),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_corrections(conn: sqlite3.Connection) -> list[CorrectionEdge]:
    """List all correction edges."""
    rows = conn.execute(
        """SELECT id, corrector_doc_key, corrected_doc_key, edge_type, confidence,
                  reason, created_at
           FROM correction_edges ORDER BY id"""
    ).fetchall()
    return [
        CorrectionEdge(
            id=r["id"],
            corrector_doc_key=r["corrector_doc_key"],
            corrected_doc_key=r["corrected_doc_key"],
            edge_type=r["edge_type"],
            confidence=r["confidence"],
            reason=r["reason"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


def get_corrections_for_doc(
    conn: sqlite3.Connection,
    doc_key: str,
) -> dict:
    """Get correction info for a document.

    Returns dict with:
      - corrects: list of doc_keys this document corrects (direct)
      - corrected_by: list of doc_keys that correct this document (direct)
    """
    corrects = [
        r["corrected_doc_key"]
        for r in conn.execute(
            "SELECT corrected_doc_key FROM correction_edges WHERE corrector_doc_key = ?",
            (doc_key,),
        ).fetchall()
    ]
    corrected_by = [
        r["corrector_doc_key"]
        for r in conn.execute(
            "SELECT corrector_doc_key FROM correction_edges WHERE corrected_doc_key = ?",
            (doc_key,),
        ).fetchall()
    ]
    return {"corrects": corrects, "corrected_by": corrected_by}


def _would_create_cycle(
    conn: sqlite3.Connection,
    corrector: str,
    corrected: str,
) -> bool:
    """Check if adding corrector → corrected would create a cycle.

    A cycle exists if corrected can already reach corrector via existing edges.
    """
    # BFS from corrected following corrector edges
    visited: set[str] = set()
    queue = [corrected]
    while queue:
        current = queue.pop(0)
        if current == corrector:
            return True
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute(
            "SELECT corrected_doc_key FROM correction_edges WHERE corrector_doc_key = ?",
            (current,),
        ).fetchall()
        for r in rows:
            queue.append(r["corrected_doc_key"])
    return False


def _get_transitive_correctors(conn: sqlite3.Connection, doc_key: str) -> set[str]:
    """Get all doc_keys that transitively correct this document (ancestors in the graph)."""
    visited: set[str] = set()
    queue = [doc_key]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute(
            "SELECT corrector_doc_key FROM correction_edges WHERE corrected_doc_key = ?",
            (current,),
        ).fetchall()
        for r in rows:
            queue.append(r["corrector_doc_key"])
    visited.discard(doc_key)
    return visited


def _get_transitive_corrected(conn: sqlite3.Connection, doc_key: str) -> set[str]:
    """Get all doc_keys that this document transitively corrects (descendants in the graph)."""
    visited: set[str] = set()
    queue = [doc_key]
    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)
        rows = conn.execute(
            "SELECT corrected_doc_key FROM correction_edges WHERE corrector_doc_key = ?",
            (current,),
        ).fetchall()
        for r in rows:
            queue.append(r["corrected_doc_key"])
    visited.discard(doc_key)
    return visited


def correction_scores(
    conn: sqlite3.Connection,
    doc_keys: list[str],
) -> dict[str, float]:
    """Compute correction score modifiers for a set of doc_keys.

    Returns a dict mapping doc_key → correction score in [-1.0, 1.0]:
      - Positive: this document is a corrector (boosted)
      - Negative: this document has been corrected/superseded (penalized)
      - Zero: no correction relationship

    Score formula:
      - Correctors get +0.5 per direct correction, +0.25 per transitive
      - Corrected docs get -0.5 per direct corrector, -0.25 per transitive
      - Clamped to [-1.0, 1.0]
      - Weighted by edge confidence
    """
    if not doc_keys:
        return {}

    scores: dict[str, float] = {}

    for dk in doc_keys:
        score = 0.0

        # Direct corrections this doc makes (boost)
        direct_corrects = conn.execute(
            "SELECT confidence FROM correction_edges WHERE corrector_doc_key = ?",
            (dk,),
        ).fetchall()
        for r in direct_corrects:
            score += 0.5 * r["confidence"]

        # Transitive corrections (smaller boost)
        trans_corrected = _get_transitive_corrected(conn, dk)
        # Subtract direct count since we already counted those
        trans_only = len(trans_corrected) - len(direct_corrects)
        if trans_only > 0:
            score += 0.25 * trans_only

        # Direct correctors of this doc (penalty)
        direct_corrected_by = conn.execute(
            "SELECT confidence FROM correction_edges WHERE corrected_doc_key = ?",
            (dk,),
        ).fetchall()
        for r in direct_corrected_by:
            score -= 0.5 * r["confidence"]

        # Transitive correctors (smaller penalty)
        trans_correctors = _get_transitive_correctors(conn, dk)
        trans_only_correctors = len(trans_correctors) - len(direct_corrected_by)
        if trans_only_correctors > 0:
            score -= 0.25 * trans_only_correctors

        scores[dk] = max(-1.0, min(1.0, score))

    return scores


def get_correction_chain(
    conn: sqlite3.Connection,
    doc_key: str,
) -> dict:
    """Get the full correction chain for a document (for audit mode).

    Returns:
      - correctors: doc_keys that correct this one (transitive)
      - corrected: doc_keys this one corrects (transitive)
      - edges: all relevant edges in the chain
    """
    correctors = _get_transitive_correctors(conn, doc_key)
    corrected = _get_transitive_corrected(conn, doc_key)

    all_keys = correctors | corrected | {doc_key}
    placeholders = ",".join("?" * len(all_keys))
    edges = conn.execute(
        f"""SELECT id, corrector_doc_key, corrected_doc_key, edge_type, confidence,
                   reason, created_at
            FROM correction_edges
            WHERE corrector_doc_key IN ({placeholders})
               OR corrected_doc_key IN ({placeholders})""",
        list(all_keys) + list(all_keys),
    ).fetchall()

    return {
        "doc_key": doc_key,
        "correctors": sorted(correctors),
        "corrected": sorted(corrected),
        "edges": [
            {
                "corrector": e["corrector_doc_key"],
                "corrected": e["corrected_doc_key"],
                "type": e["edge_type"],
                "confidence": e["confidence"],
                "reason": e["reason"],
            }
            for e in edges
        ],
    }
