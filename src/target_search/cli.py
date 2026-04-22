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


@main.command("query")
@click.argument("text")
@click.option("--top-n", type=int, default=10, help="Number of results.")
@click.option("--mode", type=click.Choice(["hybrid", "lex", "sem"]), default="hybrid",
              help="Search mode: hybrid (default), lex-only, or sem-only.")
@click.option("--json-output", "json_out", is_flag=True, help="Output as JSON.")
@click.pass_context
def query_cmd(
    ctx: click.Context,
    text: str,
    top_n: int,
    mode: str,
    json_out: bool,
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

    if mode == "lex":
        # Lex-only: return BM25 results directly
        results = search_lex(conn, text, top_n)
        conn.close()

        if json_out:
            output = [
                {
                    "chunk_id": r.chunk_id,
                    "doc_key": r.doc_key,
                    "chunk_index": r.chunk_index,
                    "bm25_score": r.bm25_score,
                    "source_type": r.source_type,
                    "trust_level": r.trust_level,
                    "text": r.chunk_text,
                }
                for r in results
            ]
            click.echo(json.dumps(output, indent=2))
        else:
            if not results:
                click.echo("No results found.")
                return
            for i, r in enumerate(results, 1):
                click.echo(f"\n--- Result {i} (BM25: {r.bm25_score:.4f}) ---")
                click.echo(f"Key: {r.doc_key} | Chunk: {r.chunk_index}")
                click.echo(r.chunk_text[:200] + ("..." if len(r.chunk_text) > 200 else ""))
        return

    from target_search.rank import RankWeights, rank

    # Get candidates from both sources
    lex_results = search_lex(conn, text, top_n * 2) if mode != "sem" else None
    sem_results = sem_mod.search_sem(conn, text, top_n * 2) if mode != "lex" else None

    # Adjust weights for single-mode
    if mode == "sem":
        weights = RankWeights(semantic=0.7, lexical=0.0, recency=0.15, trust=0.15)
    else:
        weights = RankWeights()  # defaults

    ranked = rank(lex_results=lex_results, sem_results=sem_results, weights=weights)
    ranked = ranked[:top_n]
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
            click.echo(f"Features: S={feat.S:.3f} L={feat.L:.3f} R={feat.R:.3f} T={feat.T:.3f}")
            click.echo(r.chunk_text[:200] + ("..." if len(r.chunk_text) > 200 else ""))


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

    conn.close()
    click.echo(f"Records: {records}, Chunks: {chunks}, Embeddings: {embed_count}")


if __name__ == "__main__":
    main()
