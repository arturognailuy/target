"""target-rank: weighted merge of lexical + semantic search results."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class RankWeights:
    """Configurable weights for the ranking formula."""

    semantic: float = 0.4
    lexical: float = 0.3
    recency: float = 0.15
    correction: float = 0.0  # Phase 3
    trust: float = 0.15


@dataclass
class FeatureBreakdown:
    """Score breakdown for a single result."""

    S: float = 0.0  # semantic
    L: float = 0.0  # lexical
    R: float = 0.0  # recency
    C: float = 0.0  # correction (Phase 3)
    T: float = 0.0  # trust

    def as_dict(self) -> dict[str, float]:
        return {"S": self.S, "L": self.L, "R": self.R, "C": self.C, "T": self.T}


@dataclass
class RankedResult:
    """A single ranked search result with feature breakdown."""

    chunk_id: int
    record_id: int
    doc_key: str
    chunk_index: int
    chunk_text: str
    final_score: float
    features: FeatureBreakdown
    reason_codes: list[str] = field(default_factory=list)
    source_type: str | None = None
    trust_level: float = 1.0
    created_at: str | None = None


def _normalize_scores(scores: list[float]) -> list[float]:
    """Min-max normalize scores to [0, 1]."""
    if not scores:
        return []
    mn = min(scores)
    mx = max(scores)
    if mx == mn:
        return [1.0] * len(scores)
    return [(s - mn) / (mx - mn) for s in scores]


def _recency_score(created_at: str | None, reference_date: date | None = None) -> float:
    """Compute recency score using exponential decay. More recent = higher score.

    Decay: exp(-days_old / 365). Documents without dates get 0.5.
    """
    if not created_at:
        return 0.5

    try:
        doc_date = datetime.fromisoformat(created_at).date()
    except (ValueError, TypeError):
        return 0.5

    if reference_date is None:
        reference_date = date.today()

    days_old = (reference_date - doc_date).days
    if days_old < 0:
        days_old = 0

    return math.exp(-days_old / 365.0)


def _trust_score(trust_level: float) -> float:
    """Normalize trust level to [0, 1]. Already in that range by convention."""
    return max(0.0, min(1.0, trust_level))


def rank(
    lex_results: list | None = None,
    sem_results: list | None = None,
    weights: RankWeights | None = None,
    reference_date: date | None = None,
) -> list[RankedResult]:
    """Merge lexical and semantic results into a single ranked list.

    Combines scores using:
      score = w_s·S + w_l·L + w_r·R + w_c·C + w_t·T

    Args:
        lex_results: Results from search_lex (LexResult objects).
        sem_results: Results from search_sem (SemResult objects).
        weights: Scoring weights. Defaults to RankWeights().
        reference_date: Reference date for recency calculation.

    Returns:
        Sorted list of RankedResult (highest score first).
    """
    if weights is None:
        weights = RankWeights()

    lex_results = lex_results or []
    sem_results = sem_results or []

    # Collect all chunk info by chunk_id
    candidates: dict[int, dict] = {}

    for r in lex_results:
        candidates[r.chunk_id] = {
            "chunk_id": r.chunk_id,
            "record_id": r.record_id,
            "doc_key": r.doc_key,
            "chunk_index": r.chunk_index,
            "chunk_text": r.chunk_text,
            "bm25_raw": r.bm25_score,
            "cosine_raw": 0.0,
            "source_type": r.source_type,
            "trust_level": r.trust_level,
            "created_at": r.created_at,
        }

    for r in sem_results:
        if r.chunk_id in candidates:
            candidates[r.chunk_id]["cosine_raw"] = r.cosine_score
        else:
            candidates[r.chunk_id] = {
                "chunk_id": r.chunk_id,
                "record_id": r.record_id,
                "doc_key": r.doc_key,
                "chunk_index": r.chunk_index,
                "chunk_text": r.chunk_text,
                "bm25_raw": 0.0,
                "cosine_raw": r.cosine_score,
                "source_type": r.source_type,
                "trust_level": r.trust_level,
                "created_at": r.created_at,
            }

    if not candidates:
        return []

    # Normalize raw scores across all candidates
    chunk_ids = list(candidates.keys())
    bm25_raw = [candidates[cid]["bm25_raw"] for cid in chunk_ids]
    cosine_raw = [candidates[cid]["cosine_raw"] for cid in chunk_ids]

    bm25_norm = _normalize_scores(bm25_raw)
    cosine_norm = _normalize_scores(cosine_raw)

    results: list[RankedResult] = []
    for i, cid in enumerate(chunk_ids):
        c = candidates[cid]

        S = cosine_norm[i]
        L = bm25_norm[i]
        R = _recency_score(c["created_at"], reference_date)
        C = 0.0  # Phase 3
        T = _trust_score(c["trust_level"])

        final_score = (
            weights.semantic * S
            + weights.lexical * L
            + weights.recency * R
            + weights.correction * C
            + weights.trust * T
        )

        # Determine reason codes
        reason_codes = []
        if S > 0.3:
            reason_codes.append("SEM_MATCH")
        if L > 0.3:
            reason_codes.append("LEX_MATCH")
        if R > 0.7:
            reason_codes.append("RECENT")
        if T >= 0.8:
            reason_codes.append("HIGH_TRUST")

        results.append(
            RankedResult(
                chunk_id=cid,
                record_id=c["record_id"],
                doc_key=c["doc_key"],
                chunk_index=c["chunk_index"],
                chunk_text=c["chunk_text"],
                final_score=final_score,
                features=FeatureBreakdown(S=S, L=L, R=R, C=C, T=T),
                reason_codes=reason_codes,
                source_type=c["source_type"],
                trust_level=c["trust_level"],
                created_at=c["created_at"],
            )
        )

    # Sort by final_score descending, then chunk_id for determinism
    results.sort(key=lambda r: (-r.final_score, r.chunk_id))
    return results
