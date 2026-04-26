"""target-eval: evaluation framework for retrieval quality measurement and tuning."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path

from target_search.rank import RankWeights, rank


@dataclass
class EvalQuery:
    """A single evaluation query with relevance judgments."""

    text: str
    relevant_keys: list[str] = field(default_factory=list)
    must_outrank: list[list[str]] = field(default_factory=list)
    topic: str | None = None


@dataclass
class QueryResult:
    """Result of evaluating a single query."""

    query_text: str
    top_keys: list[str]
    top_scores: list[float]
    precision_at_k: float
    outrank_pass: bool
    outrank_details: list[dict] = field(default_factory=list)


@dataclass
class EvalReport:
    """Aggregate evaluation report."""

    precision_at_k: float
    correction_recall: float
    noise_rate: float
    query_count: int
    per_query: list[QueryResult] = field(default_factory=list)


@dataclass
class SnapshotEntry:
    """Snapshot of a single query's results."""

    query_text: str
    results: list[dict]  # [{doc_key, chunk_index, score, reason_codes}]


@dataclass
class DiffEntry:
    """Difference between snapshot and current results for one query."""

    query_text: str
    status: str  # "unchanged", "changed", "new", "removed"
    snapshot_keys: list[str] = field(default_factory=list)
    current_keys: list[str] = field(default_factory=list)
    rank_changes: list[dict] = field(default_factory=list)


def load_eval_set(eval_path: str | Path) -> list[EvalQuery]:
    """Load evaluation query set from a JSON file.

    Expected format:
    {
        "queries": [
            {
                "text": "query text",
                "relevant_keys": ["key1", "key2"],
                "must_outrank": [["higher_key", "lower_key"]],
                "topic": "optional_topic"
            }
        ]
    }
    """
    data = json.loads(Path(eval_path).read_text(encoding="utf-8"))
    queries = data.get("queries", data) if isinstance(data, dict) else data
    return [
        EvalQuery(
            text=q["text"],
            relevant_keys=q.get("relevant_keys", q.get("expected_top_keys", [])),
            must_outrank=q.get("must_outrank", []),
            topic=q.get("topic"),
        )
        for q in queries
    ]


def _run_query(
    conn: sqlite3.Connection,
    query_text: str,
    top_n: int,
    weights: RankWeights,
    mode: str = "lex",
) -> list:
    """Run a query and return ranked results."""
    from target_search.lex import search_lex

    lex_results = search_lex(conn, query_text, top_n * 2) if mode != "sem" else None

    sem_results = None
    if mode in ("hybrid", "sem"):
        try:
            from target_search.sem import search_sem
            sem_results = search_sem(conn, query_text, top_n * 2)
        except ImportError:
            if mode == "sem":
                raise
            pass

    if mode == "lex":
        w = RankWeights(
            semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15
        )
    elif mode == "sem":
        w = RankWeights(
            semantic=0.6, lexical=0.0, recency=0.15, correction=0.10, trust=0.15
        )
    else:
        w = weights

    return rank(
        lex_results=lex_results,
        sem_results=sem_results,
        weights=w,
        conn=conn,
    )[:top_n]


def evaluate(
    conn: sqlite3.Connection,
    eval_queries: list[EvalQuery],
    top_k: int = 5,
    weights: RankWeights | None = None,
    mode: str = "lex",
) -> EvalReport:
    """Run evaluation and compute metrics.

    Returns:
        EvalReport with precision@k, correction recall, noise rate.
    """
    if weights is None:
        weights = RankWeights()

    per_query: list[QueryResult] = []
    total_precision = 0.0
    total_outrank_pairs = 0
    total_outrank_pass = 0

    for eq in eval_queries:
        results = _run_query(conn, eq.text, top_k, weights, mode)
        top_keys = [r.doc_key for r in results]
        top_scores = [r.final_score for r in results]

        # Precision@k: fraction of top-k results that are relevant
        if eq.relevant_keys:
            relevant_in_top = sum(1 for k in top_keys if k in eq.relevant_keys)
            denom = min(top_k, len(eq.relevant_keys))
            p_at_k = relevant_in_top / denom if denom > 0 else 0.0
        else:
            p_at_k = 1.0  # No relevance judgments = skip

        # Must-outrank checks
        outrank_details = []
        query_outrank_pass = True
        for pair in eq.must_outrank:
            if len(pair) != 2:
                continue
            higher, lower = pair
            total_outrank_pairs += 1
            h_rank = top_keys.index(higher) if higher in top_keys else len(top_keys)
            l_rank = top_keys.index(lower) if lower in top_keys else len(top_keys)
            passed = h_rank < l_rank
            if passed:
                total_outrank_pass += 1
            else:
                query_outrank_pass = False
            outrank_details.append({
                "higher": higher,
                "lower": lower,
                "higher_rank": h_rank + 1 if higher in top_keys else None,
                "lower_rank": l_rank + 1 if lower in top_keys else None,
                "passed": passed,
            })

        total_precision += p_at_k
        per_query.append(QueryResult(
            query_text=eq.text,
            top_keys=top_keys,
            top_scores=top_scores,
            precision_at_k=p_at_k,
            outrank_pass=query_outrank_pass,
            outrank_details=outrank_details,
        ))

    n = len(eval_queries) or 1
    avg_precision = total_precision / n
    correction_recall = total_outrank_pass / total_outrank_pairs if total_outrank_pairs > 0 else 1.0
    noise_rate = 1.0 - avg_precision

    return EvalReport(
        precision_at_k=avg_precision,
        correction_recall=correction_recall,
        noise_rate=noise_rate,
        query_count=n,
        per_query=per_query,
    )


def snapshot(
    conn: sqlite3.Connection,
    eval_queries: list[EvalQuery],
    top_k: int = 5,
    weights: RankWeights | None = None,
    mode: str = "lex",
) -> list[SnapshotEntry]:
    """Run all eval queries and return snapshot entries."""
    if weights is None:
        weights = RankWeights()

    entries = []
    for eq in eval_queries:
        results = _run_query(conn, eq.text, top_k, weights, mode)
        entries.append(SnapshotEntry(
            query_text=eq.text,
            results=[
                {
                    "doc_key": r.doc_key,
                    "chunk_index": r.chunk_index,
                    "score": round(r.final_score, 6),
                    "reason_codes": r.reason_codes,
                }
                for r in results
            ],
        ))
    return entries


def save_snapshot(entries: list[SnapshotEntry], path: str | Path) -> None:
    """Save snapshot entries to a JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = [{"query_text": e.query_text, "results": e.results} for e in entries]
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_snapshot(path: str | Path) -> list[SnapshotEntry]:
    """Load snapshot entries from a JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [SnapshotEntry(query_text=d["query_text"], results=d["results"]) for d in data]


def diff_snapshot(
    saved: list[SnapshotEntry],
    current: list[SnapshotEntry],
) -> list[DiffEntry]:
    """Compare saved snapshot against current results."""
    saved_map = {e.query_text: e for e in saved}
    current_map = {e.query_text: e for e in current}

    diffs = []
    all_queries = list(dict.fromkeys(
        [e.query_text for e in saved] + [e.query_text for e in current]
    ))

    for q in all_queries:
        s = saved_map.get(q)
        c = current_map.get(q)

        if s and not c:
            diffs.append(DiffEntry(
                query_text=q,
                status="removed",
                snapshot_keys=[r["doc_key"] for r in s.results],
            ))
        elif c and not s:
            diffs.append(DiffEntry(
                query_text=q,
                status="new",
                current_keys=[r["doc_key"] for r in c.results],
            ))
        else:
            s_keys = [r["doc_key"] for r in s.results]
            c_keys = [r["doc_key"] for r in c.results]
            if s_keys == c_keys:
                # Check if scores changed significantly
                s_scores = [r["score"] for r in s.results]
                c_scores = [r["score"] for r in c.results]
                score_drift = any(
                    abs(a - b) > 0.001 for a, b in zip(s_scores, c_scores)
                )
                status = "score_drift" if score_drift else "unchanged"
            else:
                status = "changed"

            rank_changes = []
            if status in ("changed", "score_drift"):
                for key in set(s_keys + c_keys):
                    old_rank = s_keys.index(key) + 1 if key in s_keys else None
                    new_rank = c_keys.index(key) + 1 if key in c_keys else None
                    if old_rank != new_rank:
                        rank_changes.append({
                            "doc_key": key,
                            "old_rank": old_rank,
                            "new_rank": new_rank,
                        })

            diffs.append(DiffEntry(
                query_text=q,
                status=status,
                snapshot_keys=s_keys,
                current_keys=c_keys,
                rank_changes=rank_changes,
            ))

    return diffs


def tune_weights(
    conn: sqlite3.Connection,
    eval_queries: list[EvalQuery],
    top_k: int = 5,
    mode: str = "lex",
    steps: int = 5,
) -> dict:
    """Grid search over weight combinations to find optimal weights.

    Args:
        conn: Database connection.
        eval_queries: Evaluation query set.
        top_k: Number of results to evaluate.
        mode: Search mode.
        steps: Number of steps per weight dimension (total combos = steps^5).

    Returns:
        Dict with best_weights, best_score, all_results (sorted).
    """
    # Generate weight values to try
    values = [round(i / (steps - 1), 2) if steps > 1 else 0.5 for i in range(steps)]

    best_score = -1.0
    best_weights = RankWeights()
    all_results = []

    for s, lx, r, c, t in product(values, repeat=5):
        total = s + lx + r + c + t
        if total == 0:
            continue

        weights = RankWeights(
            semantic=s, lexical=lx, recency=r, correction=c, trust=t
        )

        report = evaluate(conn, eval_queries, top_k, weights, mode)
        # Combined score: 60% precision + 40% correction recall
        combined = 0.6 * report.precision_at_k + 0.4 * report.correction_recall

        all_results.append({
            "weights": asdict(weights),
            "precision_at_k": round(report.precision_at_k, 4),
            "correction_recall": round(report.correction_recall, 4),
            "noise_rate": round(report.noise_rate, 4),
            "combined_score": round(combined, 4),
        })

        if combined > best_score:
            best_score = combined
            best_weights = weights

    all_results.sort(key=lambda x: -x["combined_score"])

    return {
        "best_weights": asdict(best_weights),
        "best_score": round(best_score, 4),
        "total_combinations": len(all_results),
        "top_10": all_results[:10],
    }


def benchmark(
    conn: sqlite3.Connection,
    eval_queries: list[EvalQuery],
    weights: RankWeights | None = None,
    mode: str = "lex",
    iterations: int = 10,
) -> dict:
    """Run performance benchmarks.

    Returns:
        Dict with query_latency_ms (median, p95, mean) and per-query timings.
    """
    if weights is None:
        weights = RankWeights()

    timings = []
    for eq in eval_queries:
        query_times = []
        for _ in range(iterations):
            start = time.perf_counter()
            _run_query(conn, eq.text, 10, weights, mode)
            elapsed = (time.perf_counter() - start) * 1000
            query_times.append(elapsed)
        timings.append({
            "query": eq.text,
            "mean_ms": round(sum(query_times) / len(query_times), 2),
            "min_ms": round(min(query_times), 2),
            "max_ms": round(max(query_times), 2),
        })

    all_times = [t["mean_ms"] for t in timings]
    all_times.sort()
    n = len(all_times)

    return {
        "iterations_per_query": iterations,
        "query_count": n,
        "median_ms": round(all_times[n // 2], 2) if n else 0,
        "p95_ms": round(all_times[int(n * 0.95)], 2) if n else 0,
        "mean_ms": round(sum(all_times) / n, 2) if n else 0,
        "per_query": timings,
    }
