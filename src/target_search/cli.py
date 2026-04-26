"""target-cli: command-line interface for Target search system."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from target_search.db import open_db
from target_search.ingest import index
from target_search.lex import search_lex

DEFAULT_DB = "target.db"


def _try_import_sem():
    """Try to import semantic search module. Returns None if deps missing."""
    try:
        from target_search import sem
        return sem
    except ImportError:
        return None


@click.group()
@click.option("--db", default=DEFAULT_DB, envvar="TARGET_DB", help="Database file path.")
@click.pass_context
def main(ctx: click.Context, db: str) -> None:
    """Target — general-purpose document search and ranking."""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db


@main.command("index")
@click.argument("doc_key")
@click.argument("file", type=click.Path(exists=True))
@click.option("--source-type", default=None, help="Override source type.")
@click.option("--trust-level", type=float, default=None, help="Override trust level (0.0-1.0).")
@click.option("--max-chunk-tokens", type=int, default=256, help="Max tokens per chunk.")
@click.option("--embed/--no-embed", default=False, help="Generate embeddings after indexing.")
@click.pass_context
def index_cmd(
    ctx: click.Context,
    doc_key: str,
    file: str,
    source_type: str | None,
    trust_level: float | None,
    max_chunk_tokens: int,
    embed: bool,
) -> None:
    """Index a document from a file."""
    conn = open_db(ctx.obj["db_path"])
    content = Path(file).read_text(encoding="utf-8")

    metadata = {}
    if source_type:
        metadata["source_type"] = source_type
    if trust_level is not None:
        metadata["trust_level"] = trust_level

    result = index(conn, doc_key, content, metadata or None, max_chunk_tokens=max_chunk_tokens)

    action = "replaced" if result.replaced else "indexed"
    click.echo(f"{action} {result.doc_key}: {result.chunks} chunks (record_id={result.record_id})")

    if embed:
        sem = _try_import_sem()
        if sem is None:
            click.echo("Warning: semantic extras not installed. Skipping embeddings.")
        else:
            count = sem.index_embeddings(conn)
            click.echo(f"embedded {count} chunks")

    conn.close()


@main.command("index-stdin")
@click.argument("doc_key")
@click.option("--source-type", default=None)
@click.option("--trust-level", type=float, default=None)
@click.option("--max-chunk-tokens", type=int, default=256)
@click.option("--embed/--no-embed", default=False, help="Generate embeddings after indexing.")
@click.pass_context
def index_stdin_cmd(
    ctx: click.Context,
    doc_key: str,
    source_type: str | None,
    trust_level: float | None,
    max_chunk_tokens: int,
    embed: bool,
) -> None:
    """Index a document from stdin."""
    conn = open_db(ctx.obj["db_path"])
    content = sys.stdin.read()

    metadata = {}
    if source_type:
        metadata["source_type"] = source_type
    if trust_level is not None:
        metadata["trust_level"] = trust_level

    result = index(conn, doc_key, content, metadata or None, max_chunk_tokens=max_chunk_tokens)

    action = "replaced" if result.replaced else "indexed"
    click.echo(f"{action} {result.doc_key}: {result.chunks} chunks (record_id={result.record_id})")

    if embed:
        sem = _try_import_sem()
        if sem is None:
            click.echo("Warning: semantic extras not installed. Skipping embeddings.")
        else:
            count = sem.index_embeddings(conn)
            click.echo(f"embedded {count} chunks")

    conn.close()


@main.command("embed")
@click.option("--model", default="all-MiniLM-L6-v2", help="Embedding model name.")
@click.pass_context
def embed_cmd(ctx: click.Context, model: str) -> None:
    """Generate embeddings for all un-embedded chunks."""
    sem = _try_import_sem()
    if sem is None:
        click.echo(
            "Error: semantic extras not installed. "
            "Install with: pip install target-search[semantic]"
        )
        raise SystemExit(1)

    conn = open_db(ctx.obj["db_path"])
    count = sem.index_embeddings(conn, model_name=model)
    conn.close()
    click.echo(f"embedded {count} chunks")


@main.command("correct")
@click.argument("corrector_key")
@click.argument("corrected_key")
@click.option("--confidence", type=float, default=1.0, help="Confidence level (0.0-1.0).")
@click.option("--reason", default=None, help="Reason for the correction.")
@click.option("--edge-type", default="supersedes", help="Type of correction edge.")
@click.pass_context
def correct_cmd(
    ctx: click.Context,
    corrector_key: str,
    corrected_key: str,
    confidence: float,
    reason: str | None,
    edge_type: str,
) -> None:
    """Add a correction: CORRECTOR_KEY corrects/supersedes CORRECTED_KEY."""
    from target_search.correct import add_correction

    conn = open_db(ctx.obj["db_path"])
    try:
        edge = add_correction(conn, corrector_key, corrected_key, edge_type, confidence, reason)
        click.echo(
            f"correction added: {edge.corrector_doc_key} → {edge.corrected_doc_key} "
            f"(type={edge.edge_type}, confidence={edge.confidence})"
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
    finally:
        conn.close()


@main.command("uncorrect")
@click.argument("corrector_key")
@click.argument("corrected_key")
@click.pass_context
def uncorrect_cmd(
    ctx: click.Context,
    corrector_key: str,
    corrected_key: str,
) -> None:
    """Remove a correction edge."""
    from target_search.correct import remove_correction

    conn = open_db(ctx.obj["db_path"])
    removed = remove_correction(conn, corrector_key, corrected_key)
    conn.close()
    if removed:
        click.echo(f"correction removed: {corrector_key} → {corrected_key}")
    else:
        click.echo(f"No correction found: {corrector_key} → {corrected_key}")


@main.command("corrections")
@click.option("--doc-key", default=None, help="Show corrections for a specific document.")
@click.option("--json-output", "json_out", is_flag=True, help="Output as JSON.")
@click.pass_context
def corrections_cmd(
    ctx: click.Context,
    doc_key: str | None,
    json_out: bool,
) -> None:
    """List correction edges, optionally filtered by document."""
    from target_search.correct import get_correction_chain, list_corrections

    conn = open_db(ctx.obj["db_path"])

    if doc_key:
        chain = get_correction_chain(conn, doc_key)
        conn.close()
        if json_out:
            click.echo(json.dumps(chain, indent=2))
        else:
            click.echo(f"Correction chain for: {chain['doc_key']}")
            if chain["correctors"]:
                click.echo(f"  Corrected by: {', '.join(chain['correctors'])}")
            if chain["corrected"]:
                click.echo(f"  Corrects: {', '.join(chain['corrected'])}")
            if chain["edges"]:
                click.echo("  Edges:")
                for e in chain["edges"]:
                    reason_str = f" ({e['reason']})" if e["reason"] else ""
                    click.echo(
                        f"    {e['corrector']} → {e['corrected']} "
                        f"[{e['type']}, conf={e['confidence']}]{reason_str}"
                    )
            if not chain["correctors"] and not chain["corrected"]:
                click.echo("  No corrections found.")
    else:
        edges = list_corrections(conn)
        conn.close()
        if json_out:
            output = [
                {
                    "corrector": e.corrector_doc_key,
                    "corrected": e.corrected_doc_key,
                    "type": e.edge_type,
                    "confidence": e.confidence,
                    "reason": e.reason,
                }
                for e in edges
            ]
            click.echo(json.dumps(output, indent=2))
        else:
            if not edges:
                click.echo("No corrections registered.")
            else:
                for e in edges:
                    reason_str = f" ({e.reason})" if e.reason else ""
                    click.echo(
                        f"{e.corrector_doc_key} → {e.corrected_doc_key} "
                        f"[{e.edge_type}, conf={e.confidence}]{reason_str}"
                    )


@main.command("query")
@click.argument("text")
@click.option("--top-n", type=int, default=10, help="Number of results.")
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="hybrid",
              help="Search mode: hybrid (default), lex-only, or sem-only.")
@click.option("--json-output", "json_out", is_flag=True, help="Output as JSON.")
@click.option("--audit", is_flag=True, help="Include correction chain info in results.")
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str,
    top_n: int,
    mode: str,
    json_out: bool,
    audit: bool,
) -> None:
    """Query indexed documents with hybrid BM25 + semantic ranking."""
    conn = open_db(ctx.obj["db_path"])

    sem_mod = _try_import_sem()
    has_semantic = sem_mod is not None

    # If hybrid or sem mode requested but no semantic deps, fall back
    if mode in ("hybrid", "sem") and not has_semantic:
        if mode == "sem":
            click.echo("Error: semantic extras not installed.")
            raise SystemExit(1)
        click.echo("Warning: semantic extras not installed. Falling back to lex-only.")
        mode = "lex"

    # Check if embeddings exist for hybrid/sem modes
    if mode in ("hybrid", "sem") and has_semantic:
        try:
            embed_count = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        except Exception:
            embed_count = 0
        if embed_count == 0:
            if mode == "sem":
                click.echo("No embeddings found. Run 'target embed' first.")
                raise SystemExit(1)
            mode = "lex"

    from target_search.rank import RankWeights, rank

    # Get candidates from both sources
    lex_results = search_lex(conn, text, top_n * 2) if mode != "sem" else None
    sem_results = sem_mod.search_sem(conn, text, top_n * 2) if mode != "lex" else None

    # Adjust weights based on mode
    if mode == "lex":
        weights = RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15)
    elif mode == "sem":
        weights = RankWeights(semantic=0.6, lexical=0.0, recency=0.15, correction=0.10, trust=0.15)
    else:
        weights = RankWeights()  # defaults

    ranked = rank(
        lex_results=lex_results,
        sem_results=sem_results,
        weights=weights,
        conn=conn,
    )
    ranked = ranked[:top_n]

    # Get correction chain info if audit mode
    audit_info = {}
    if audit:
        from target_search.correct import get_correction_chain
        for r in ranked:
            if r.doc_key not in audit_info:
                audit_info[r.doc_key] = get_correction_chain(conn, r.doc_key)

    conn.close()

    if json_out:
        output = [
            {
                "chunk_id": r.chunk_id,
                "doc_key": r.doc_key,
                "chunk_index": r.chunk_index,
                "final_score": round(r.final_score, 4),
                "features": {k: round(v, 4) for k, v in r.features.as_dict().items()},
                "reason_codes": r.reason_codes,
                "source_type": r.source_type,
                "trust_level": r.trust_level,
                "text": r.chunk_text,
                **({"correction_chain": audit_info.get(r.doc_key)} if audit else {}),
            }
            for r in ranked
        ]
        click.echo(json.dumps(output, indent=2))
    else:
        if not ranked:
            click.echo("No results found.")
            return
        for i, r in enumerate(ranked, 1):
            codes = ", ".join(r.reason_codes) if r.reason_codes else "none"
            click.echo(f"\n--- Result {i} (score: {r.final_score:.4f} | {codes}) ---")
            click.echo(f"Key: {r.doc_key} | Chunk: {r.chunk_index}")
            feat = r.features
            click.echo(
                f"Features: S={feat.S:.3f} L={feat.L:.3f} R={feat.R:.3f} "
                f"C={feat.C:.3f} T={feat.T:.3f}"
            )
            click.echo(r.chunk_text[:200] + ("..." if len(r.chunk_text) > 200 else ""))
            if audit and r.doc_key in audit_info:
                chain = audit_info[r.doc_key]
                if chain["correctors"]:
                    click.echo(f"  ⚠ Corrected by: {', '.join(chain['correctors'])}")
                if chain["corrected"]:
                    click.echo(f"  ✓ Corrects: {', '.join(chain['corrected'])}")


@main.command("explain")
@click.argument("text")
@click.option("--top-n", type=int, default=5, help="Number of results to explain.")
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="hybrid",
              help="Search mode.")
@click.option("--json-output", "json_out", is_flag=True, help="Output as JSON.")
@click.option("--verbose", "-v", is_flag=True, help="Include full feature breakdown.")
@click.pass_context
def explain_cmd(
    ctx: click.Context,
    text: str,
    top_n: int,
    mode: str,
    json_out: bool,
    verbose: bool,
) -> None:
    """Explain why results rank the way they do for a query."""
    from target_search.explain import explain_results, format_explanation
    from target_search.rank import RankWeights, rank

    conn = open_db(ctx.obj["db_path"])

    sem_mod = _try_import_sem()
    has_semantic = sem_mod is not None

    if mode in ("hybrid", "sem") and not has_semantic:
        if mode == "sem":
            click.echo("Error: semantic extras not installed.")
            raise SystemExit(1)
        mode = "lex"

    if mode in ("hybrid", "sem") and has_semantic:
        try:
            embed_count = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
        except Exception:
            embed_count = 0
        if embed_count == 0:
            if mode == "sem":
                click.echo("No embeddings found. Run 'target embed' first.")
                raise SystemExit(1)
            mode = "lex"

    lex_results = search_lex(conn, text, top_n * 2) if mode != "sem" else None
    sem_results = sem_mod.search_sem(conn, text, top_n * 2) if mode != "lex" else None

    if mode == "lex":
        weights = RankWeights(semantic=0.0, lexical=0.20, recency=0.15, correction=0.50, trust=0.15)
    elif mode == "sem":
        weights = RankWeights(semantic=0.6, lexical=0.0, recency=0.15, correction=0.10, trust=0.15)
    else:
        weights = RankWeights()

    ranked = rank(
        lex_results=lex_results,
        sem_results=sem_results,
        weights=weights,
        conn=conn,
    )
    ranked = ranked[:top_n]

    explanations = explain_results(ranked, conn=conn)
    conn.close()

    if json_out:
        click.echo(json.dumps([e.as_dict() for e in explanations], indent=2))
    else:
        if not explanations:
            click.echo("No results found.")
            return
        for i, expl in enumerate(explanations, 1):
            codes = ", ".join(expl.reason_codes) if expl.reason_codes else "none"
            click.echo(f"\n=== Result {i} (score: {expl.final_score:.4f} | {codes}) ===")
            click.echo(format_explanation(expl, verbose=verbose))


# --- Eval subcommands ---

@main.group("eval")
@click.pass_context
def eval_group(ctx: click.Context) -> None:
    """Evaluation, regression testing, and weight tuning."""
    pass


@eval_group.command("snapshot")
@click.argument("eval_set", type=click.Path(exists=True))
@click.option("--output", "-o", default="tests/eval/snapshot.json", help="Snapshot output path.")
@click.option("--top-k", type=int, default=5, help="Results per query.")
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="lex")
@click.pass_context
def eval_snapshot_cmd(
    ctx: click.Context, eval_set: str, output: str, top_k: int, mode: str
) -> None:
    """Run eval queries and save results as golden snapshots."""
    from target_search.eval import load_eval_set, save_snapshot, snapshot

    conn = open_db(ctx.obj["db_path"])
    queries = load_eval_set(eval_set)
    entries = snapshot(conn, queries, top_k=top_k, mode=mode)
    save_snapshot(entries, output)
    conn.close()
    click.echo(f"Snapshot saved: {output} ({len(entries)} queries)")


@eval_group.command("diff")
@click.argument("eval_set", type=click.Path(exists=True))
@click.option("--snapshot-path", "-s", default="tests/eval/snapshot.json",
              help="Saved snapshot to compare against.")
@click.option("--top-k", type=int, default=5)
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="lex")
@click.option("--json-output", "json_out", is_flag=True)
@click.pass_context
def eval_diff_cmd(
    ctx: click.Context, eval_set: str, snapshot_path: str, top_k: int,
    mode: str, json_out: bool,
) -> None:
    """Compare current results against saved snapshots."""
    from target_search.eval import (
        diff_snapshot,
        load_eval_set,
        load_snapshot,
        snapshot,
    )

    conn = open_db(ctx.obj["db_path"])
    queries = load_eval_set(eval_set)
    current = snapshot(conn, queries, top_k=top_k, mode=mode)
    saved = load_snapshot(snapshot_path)
    conn.close()

    diffs = diff_snapshot(saved, current)

    if json_out:
        click.echo(json.dumps(
            [{"query": d.query_text, "status": d.status,
              "rank_changes": d.rank_changes} for d in diffs],
            indent=2,
        ))
    else:
        changed = [d for d in diffs if d.status != "unchanged"]
        click.echo(f"Compared {len(diffs)} queries: "
                   f"{len(diffs) - len(changed)} unchanged, {len(changed)} changed")
        for d in changed:
            click.echo(f"\n  [{d.status.upper()}] {d.query_text}")
            for rc in d.rank_changes:
                old = rc['old_rank'] or 'absent'
                new = rc['new_rank'] or 'absent'
                click.echo(f"    {rc['doc_key']}: rank {old} → {new}")


@eval_group.command("report")
@click.argument("eval_set", type=click.Path(exists=True))
@click.option("--top-k", type=int, default=5)
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="lex")
@click.option("--json-output", "json_out", is_flag=True)
@click.pass_context
def eval_report_cmd(
    ctx: click.Context, eval_set: str, top_k: int, mode: str, json_out: bool,
) -> None:
    """Compute and display quality metrics."""
    from target_search.eval import evaluate, load_eval_set

    conn = open_db(ctx.obj["db_path"])
    queries = load_eval_set(eval_set)
    report = evaluate(conn, queries, top_k=top_k, mode=mode)
    conn.close()

    if json_out:
        click.echo(json.dumps({
            "precision_at_k": round(report.precision_at_k, 4),
            "correction_recall": round(report.correction_recall, 4),
            "noise_rate": round(report.noise_rate, 4),
            "query_count": report.query_count,
            "per_query": [
                {
                    "query": qr.query_text,
                    "precision": round(qr.precision_at_k, 4),
                    "outrank_pass": qr.outrank_pass,
                    "top_keys": qr.top_keys,
                }
                for qr in report.per_query
            ],
        }, indent=2))
    else:
        click.echo(f"\n=== Evaluation Report (top-{top_k}, {mode} mode) ===")
        click.echo(f"  Queries: {report.query_count}")
        click.echo(f"  Precision@{top_k}: {report.precision_at_k:.2%}")
        click.echo(f"  Correction recall: {report.correction_recall:.2%}")
        click.echo(f"  Noise rate: {report.noise_rate:.2%}")
        click.echo("")
        for qr in report.per_query:
            status = "✓" if qr.outrank_pass else "✗"
            click.echo(f"  {status} \"{qr.query_text}\" — P@{top_k}={qr.precision_at_k:.2%}")
            for od in qr.outrank_details:
                mark = "✓" if od["passed"] else "✗"
                click.echo(f"      {mark} {od['higher']} > {od['lower']}")


@eval_group.command("tune")
@click.argument("eval_set", type=click.Path(exists=True))
@click.option("--top-k", type=int, default=5)
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="lex")
@click.option("--steps", type=int, default=5, help="Grid search granularity per weight.")
@click.option("--json-output", "json_out", is_flag=True)
@click.pass_context
def eval_tune_cmd(
    ctx: click.Context, eval_set: str, top_k: int, mode: str, steps: int,
    json_out: bool,
) -> None:
    """Run weight grid search and report optimal weights."""
    from target_search.eval import load_eval_set, tune_weights

    conn = open_db(ctx.obj["db_path"])
    queries = load_eval_set(eval_set)
    click.echo(f"Tuning weights (steps={steps}, {steps**5} combinations)...")
    result = tune_weights(conn, queries, top_k=top_k, mode=mode, steps=steps)
    conn.close()

    if json_out:
        click.echo(json.dumps(result, indent=2))
    else:
        bw = result["best_weights"]
        click.echo("\n=== Weight Tuning Results ===")
        click.echo(f"  Combinations tested: {result['total_combinations']}")
        click.echo(f"  Best combined score: {result['best_score']}")
        click.echo("  Best weights:")
        click.echo(f"    semantic={bw['semantic']}, lexical={bw['lexical']}, "
                   f"recency={bw['recency']}, correction={bw['correction']}, "
                   f"trust={bw['trust']}")
        click.echo("\n  Top 5 combinations:")
        for i, r in enumerate(result["top_10"][:5], 1):
            w = r["weights"]
            click.echo(
                f"    {i}. P@k={r['precision_at_k']:.2%} CR={r['correction_recall']:.2%} "
                f"score={r['combined_score']} "
                f"[s={w['semantic']}, l={w['lexical']}, r={w['recency']}, "
                f"c={w['correction']}, t={w['trust']}]"
            )


@eval_group.command("benchmark")
@click.argument("eval_set", type=click.Path(exists=True))
@click.option("--iterations", type=int, default=10, help="Iterations per query.")
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="lex")
@click.option("--json-output", "json_out", is_flag=True)
@click.pass_context
def eval_benchmark_cmd(
    ctx: click.Context, eval_set: str, iterations: int, mode: str, json_out: bool,
) -> None:
    """Run performance benchmarks (query latency)."""
    from target_search.eval import benchmark, load_eval_set

    conn = open_db(ctx.obj["db_path"])
    queries = load_eval_set(eval_set)
    result = benchmark(conn, queries, mode=mode, iterations=iterations)
    conn.close()

    if json_out:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"\n=== Performance Benchmark ({iterations} iterations/query) ===")
        click.echo(f"  Queries: {result['query_count']}")
        click.echo(f"  Median latency: {result['median_ms']} ms")
        click.echo(f"  P95 latency: {result['p95_ms']} ms")
        click.echo(f"  Mean latency: {result['mean_ms']} ms")
        click.echo("")
        for t in result["per_query"]:
            click.echo(
                f"  \"{t['query']}\" — {t['mean_ms']} ms "
                f"(min={t['min_ms']}, max={t['max_ms']})"
            )


@main.command("stats")
@click.pass_context
def stats_cmd(ctx: click.Context) -> None:
    """Show database statistics."""
    conn = open_db(ctx.obj["db_path"])
    records = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM record_chunks").fetchone()[0]

    # Check for embeddings
    embed_count = 0
    try:
        embed_count = conn.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0]
    except Exception:
        pass

    # Check for corrections
    correction_count = conn.execute("SELECT COUNT(*) FROM correction_edges").fetchone()[0]

    conn.close()
    click.echo(
        f"Records: {records}, Chunks: {chunks}, Embeddings: {embed_count}, "
        f"Corrections: {correction_count}"
    )


if __name__ == "__main__":
    main()
