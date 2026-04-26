---
domain: Designs
status: Active
entry_points: []
dependencies:
  - .aidoc/architecture/system-overview.md
---

# Interface Contract

Target exposes exactly two operations to consumers. All internal complexity — chunking, embedding,
FTS indexing, correction detection, ranking — is hidden behind this minimal surface.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Internal modules behind this interface |

## Why Minimal

Any system that produces `(key, text)` pairs can feed into Target without understanding its
internals. The first consumer is a memory/dream system, but Target is general-purpose: chat logs,
bookmarks, code comments, RSS feeds — anything with a stable key and text content.

## Public API

```python
index(doc_key: str, doc_content: str, metadata: dict | None = None) -> None
query(text: str, top_n: int = 10) -> list[RankedResult]
```

**doc_key** is a stable, unique identifier (e.g., `memory:2026-04-18`, `email:thread:dream-system`).
Conventions in the key (prefix, date) allow metadata inference when explicit metadata is omitted.

**doc_content** is the raw text of the document.

**metadata** is optional hints: source type, date, trust level. When omitted, Target infers from
doc_key conventions.

## Query Output Contract

Each `RankedResult` includes:
- `final_score` — combined weighted score
- Feature breakdown: `{S, L, R, C, T}` (semantic, lexical, recency, correction, trust)
- Evidence pointers (record/chunk IDs)
- Reason codes: `SEM_MATCH`, `LEX_MATCH`, `RECENT`, `CORRECTED`, `HIGH_TRUST`

## Query Modes

The `--mode` flag on `target query` controls which search method is used:

- **`--mode hybrid`** (default): combines BM25 lexical + semantic vector results using the weighted
  ranking formula. If no embeddings exist, automatically falls back to lexical-only — no model
  loading, no errors.
- **`--mode lex`**: lexical search only (FTS5/BM25 keyword matching). Fast, no model loading.
  Good for exact keyword queries or when semantic extras are not installed.
- **`--mode sem`**: semantic search only (vector similarity). Requires embeddings to exist.
  Loads the embedding model to vectorize the query, then finds similar chunks by meaning.

**Indexing controls:**
- `target index doc_key file` — indexes for lexical search only (default, fast).
- `target index doc_key file --embed` — indexes for lexical + generates semantic embeddings.
- `target embed` — generates embeddings for any chunks that don't have them yet.

**Audit mode:** `target query "text" --audit` includes correction chain info in results —
showing which documents have been corrected and by what, with full transitive lineage.

## Correction Commands

- `target correct <corrector_key> <corrected_key>` — register that corrector supersedes corrected
- `target uncorrect <corrector_key> <corrected_key>` — remove a correction edge
- `target corrections` — list all correction edges
- `target corrections --doc-key <key>` — show full correction chain for a document

Corrections affect ranking: corrector documents are boosted, corrected documents are penalized.
Transitive chains propagate (A corrects B, B corrects C → A dominates C).

## Explain Command

- `target explain "query text"` — run a query and explain why each result ranks where it does
- `target explain "text" --verbose` — include full feature breakdown (S/L/R/C/T scores)
- `target explain "text" --json-output` — structured JSON with citations, evidence, dominant factors
- `target explain "text" --mode lex|sem|hybrid` — control search mode (same as query)
- `target explain "text" --top-n N` — number of results to explain (default 5)

Each result explanation includes: human-readable citation, dominant contributing factors,
reason code descriptions, evidence pointers (chunk/record IDs), and correction chain evidence.

### Evaluation and Tuning

- `target eval snapshot EVAL_SET` — run eval queries, save ranked results as golden snapshots
- `target eval diff EVAL_SET` — compare current results against saved snapshots
- `target eval report EVAL_SET` — compute quality metrics (precision@k, correction recall, noise rate)
- `target eval tune EVAL_SET` — grid search over weight combinations for optimal ranking
- `target eval benchmark EVAL_SET` — measure query latency across the eval set

## Design Principles

1. **Minimal interface.** Consumers see only `index()` and `query()`.
2. **General purpose.** Any `(key, text)` source can use Target.
3. **Correctness over speed.** Deterministic ranking for the same corpus and query.
4. **No private information.** Open-source project; code and docs must not contain private data.

## Invariants

- Re-indexing the same doc_key MUST replace previous chunks (idempotent upsert).
- Query output MUST be deterministic for the same corpus, query, and weight configuration.
- Correction edges MUST propagate transitively (A corrects B, B corrects C → A dominates C).
