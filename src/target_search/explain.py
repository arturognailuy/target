"""target-explain: citation and evidence generation for ranked results."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from target_search.rank import RankedResult  # noqa: I001

# Reason code descriptions for human-readable output
REASON_DESCRIPTIONS: dict[str, str] = {
    "SEM_MATCH": "Semantically similar to query",
    "LEX_MATCH": "Contains matching keywords",
    "RECENT": "Recently created document",
    "CORRECTOR": "Corrects/supersedes another document",
    "CORRECTED": "Superseded by a newer document",
    "HIGH_TRUST": "High-trust source",
}


@dataclass
class EvidencePointer:
    """A traceable pointer to the source of a result."""

    chunk_id: int
    record_id: int
    doc_key: str
    chunk_index: int
    text_preview: str  # first N chars of chunk text


@dataclass
class CorrectionEvidence:
    """Evidence about correction relationships for a result."""

    correctors: list[str] = field(default_factory=list)
    corrected: list[str] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)


@dataclass
class Explanation:
    """Full explanation for a single ranked result."""

    doc_key: str
    chunk_index: int
    final_score: float
    features: dict[str, float]
    reason_codes: list[str]
    reason_descriptions: list[str]
    evidence: EvidencePointer
    correction_evidence: CorrectionEvidence | None
    citation: str  # human-readable citation string
    dominant_factors: list[str]  # top contributing factors

    def as_dict(self) -> dict:
        """Serialize to a dictionary."""
        result = {
            "doc_key": self.doc_key,
            "chunk_index": self.chunk_index,
            "final_score": round(self.final_score, 4),
            "features": {k: round(v, 4) for k, v in self.features.items()},
            "reason_codes": self.reason_codes,
            "reason_descriptions": self.reason_descriptions,
            "dominant_factors": self.dominant_factors,
            "citation": self.citation,
            "evidence": {
                "chunk_id": self.evidence.chunk_id,
                "record_id": self.evidence.record_id,
                "doc_key": self.evidence.doc_key,
                "chunk_index": self.evidence.chunk_index,
                "text_preview": self.evidence.text_preview,
            },
        }
        if self.correction_evidence:
            result["correction_evidence"] = {
                "correctors": self.correction_evidence.correctors,
                "corrected": self.correction_evidence.corrected,
                "edges": self.correction_evidence.edges,
            }
        return result


def _build_citation(result: RankedResult, preview_len: int = 80) -> str:
    """Build a human-readable citation string for a result.

    Format: [doc_key, chunk N] "preview..." (score: X.XXXX, reasons: A, B, C)
    """
    text = result.chunk_text[:preview_len]
    if len(result.chunk_text) > preview_len:
        text += "..."
    text = text.replace("\n", " ").strip()

    reasons = ", ".join(result.reason_codes) if result.reason_codes else "none"
    return (
        f'[{result.doc_key}, chunk {result.chunk_index}] '
        f'"{text}" '
        f'(score: {result.final_score:.4f}, reasons: {reasons})'
    )


def _dominant_factors(result: RankedResult, top_n: int = 3) -> list[str]:
    """Identify the top contributing factors to the final score.

    Returns factor names sorted by their weighted contribution (descending).
    """
    feature_names = {
        "S": "Semantic similarity",
        "L": "Lexical match (BM25)",
        "R": "Recency",
        "C": "Correction status",
        "T": "Source trust",
    }
    features = result.features.as_dict()

    # Sort by absolute value of feature score (contribution)
    sorted_features = sorted(
        features.items(),
        key=lambda x: abs(x[1]),
        reverse=True,
    )

    return [
        f"{feature_names[k]} ({v:.3f})"
        for k, v in sorted_features[:top_n]
        if abs(v) > 0.01  # skip negligible factors
    ]


def _get_correction_evidence(
    conn: sqlite3.Connection | None, doc_key: str
) -> CorrectionEvidence | None:
    """Get correction chain evidence for a doc_key.

    Returns None if no connection or no corrections found.
    """
    if conn is None:
        return None

    try:
        from target_search.correct import get_correction_chain

        chain = get_correction_chain(conn, doc_key)
        if not chain["correctors"] and not chain["corrected"]:
            return None
        return CorrectionEvidence(
            correctors=chain["correctors"],
            corrected=chain["corrected"],
            edges=chain["edges"],
        )
    except Exception:
        return None


def explain_result(
    result: RankedResult,
    conn: sqlite3.Connection | None = None,
    preview_len: int = 80,
) -> Explanation:
    """Generate a full explanation for a single ranked result.

    Args:
        result: The ranked result to explain.
        conn: Database connection for correction chain lookup.
        preview_len: Maximum characters for text preview in citation.

    Returns:
        An Explanation with citation, evidence, and factor analysis.
    """
    evidence = EvidencePointer(
        chunk_id=result.chunk_id,
        record_id=result.record_id,
        doc_key=result.doc_key,
        chunk_index=result.chunk_index,
        text_preview=result.chunk_text[:preview_len],
    )

    correction_evidence = _get_correction_evidence(conn, result.doc_key)

    reason_descriptions = [
        REASON_DESCRIPTIONS.get(code, code) for code in result.reason_codes
    ]

    return Explanation(
        doc_key=result.doc_key,
        chunk_index=result.chunk_index,
        final_score=result.final_score,
        features=result.features.as_dict(),
        reason_codes=result.reason_codes,
        reason_descriptions=reason_descriptions,
        evidence=evidence,
        correction_evidence=correction_evidence,
        citation=_build_citation(result, preview_len),
        dominant_factors=_dominant_factors(result),
    )


def explain_results(
    results: list[RankedResult],
    conn: sqlite3.Connection | None = None,
    preview_len: int = 80,
) -> list[Explanation]:
    """Generate explanations for a list of ranked results.

    Args:
        results: Ranked results to explain.
        conn: Database connection for correction chain lookup.
        preview_len: Maximum characters for text preview.

    Returns:
        List of Explanations, one per result.
    """
    return [explain_result(r, conn, preview_len) for r in results]


def format_explanation(expl: Explanation, verbose: bool = False) -> str:
    """Format an explanation as human-readable text.

    Args:
        expl: The explanation to format.
        verbose: If True, include full feature breakdown.

    Returns:
        Formatted string.
    """
    lines = []

    # Citation line
    lines.append(f"  Citation: {expl.citation}")

    # Dominant factors
    if expl.dominant_factors:
        lines.append(f"  Why: {'; '.join(expl.dominant_factors)}")

    # Reason descriptions
    if expl.reason_descriptions:
        lines.append(f"  Signals: {', '.join(expl.reason_descriptions)}")

    # Correction info
    if expl.correction_evidence:
        ce = expl.correction_evidence
        if ce.correctors:
            lines.append(f"  ⚠ Corrected by: {', '.join(ce.correctors)}")
        if ce.corrected:
            lines.append(f"  ✓ Corrects: {', '.join(ce.corrected)}")

    # Verbose: full feature breakdown
    if verbose:
        feat = expl.features
        lines.append(
            f"  Features: S={feat['S']:.4f} L={feat['L']:.4f} "
            f"R={feat['R']:.4f} C={feat['C']:.4f} T={feat['T']:.4f}"
        )

    return "\n".join(lines)
