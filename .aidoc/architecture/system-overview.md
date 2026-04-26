---
domain: Architecture
status: Active
entry_points: []
dependencies:
  - .aidoc/designs/interface-contract.md
---

# System Overview

Target is built as a six-module pipeline plus a CLI facade. Each module does one thing,
communicates through explicit interfaces, and can be tested or replaced independently.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [Interface Contract](../designs/interface-contract.md) | Public API that this architecture serves |
| [Testing Strategy](../conventions/testing-strategy.md) | How each module is tested |
| [Development Plan](../workflows/development-plan.md) | Build order for these modules |

## Why This Architecture

Hybrid retrieval (lexical + semantic) outperforms either approach alone. Lexical search catches
exact matches and rare terms; semantic search captures meaning across paraphrases. A separate
correction layer is needed because document corpora evolve — newer documents may supersede older ones,
and rankings must reflect that. Keeping these concerns in separate modules follows the Unix doctrine:
each module is small, composable, and independently testable.

## Modules

### target-ingest
Accepts `(doc_key, doc_content, metadata)` tuples. Normalizes text, splits into chunks respecting
paragraph/section boundaries, attaches metadata (source type, date, trust level — inferred from
doc_key conventions when not provided), and upserts into storage. Re-ingesting the same doc_key
replaces previous chunks (idempotent).

### target-lex (FTS5 / BM25)
Maintains a SQLite FTS5 index over ingested chunks. Accepts a query string and returns chunks
ranked by BM25 score. Handles tokenization including CJK text and code blocks.

### target-sem (sqlite-vec)
Generates embeddings for ingested chunks using a configurable embedding model (default:
all-MiniLM-L6-v2 via sentence-transformers). Stores vectors in sqlite-vec with cosine distance.
Embedding is incremental — only un-embedded chunks are processed on each run. Accepts a query,
embeds it, and returns chunks ranked by cosine similarity. Semantic extras are optional (`pip
install target-search[semantic]`); the system gracefully degrades to lexical-only when absent.

### target-correct
Maintains a directed correction graph where edges represent "document A corrects/supersedes
document B." Provides:
- **Edge management:** `add_correction()`, `remove_correction()`, `list_corrections()` with
  cycle detection and self-correction prevention.
- **Score modifiers:** `correction_scores()` computes per-doc-key scores in [-1, 1] — positive
  for correctors (boosted), negative for corrected docs (penalized). Weighted by edge confidence.
- **Transitive propagation:** if A corrects B and B corrects C, A dominates C. Scores accumulate
  across chains with diminishing weight (+0.5 direct, +0.25 transitive).
- **Audit support:** `get_correction_chain()` returns full transitive correctors, corrected docs,
  and all edges for a document — used by CLI `--audit` mode.

### target-rank
Weighted merge layer. Combines scored candidate sets from lex, sem, and correct into a final
ranked list. Scoring formula: `score = w_s·S + w_l·L + w_r·R + w_c·C + w_t·T` where S=semantic,
L=lexical, R=recency (exponential decay), C=correction, T=trust. Default weights:
semantic=0.35, lexical=0.25, recency=0.15, correction=0.10, trust=0.15. Correction scores are
normalized from [-1, 1] to [0, 1] before applying weight. Weights are configurable via
`RankWeights` dataclass; zeroing a weight disables that provider. Produces deterministic output
for the same corpus, query, and weights. Accepts optional `conn` parameter for correction score
lookup.

### target-explain
Generates citations and evidence for ranked results. Each result gets an `Explanation` containing:
traceable evidence pointers (chunk/record IDs), human-readable citation strings, reason code
descriptions, dominant contributing factors, and correction chain evidence when applicable.
Explanations are serializable to JSON via `as_dict()` and formattable as human-readable text
via `format_explanation()`. Operates on `RankedResult` objects from target-rank — no direct
database queries except optional correction chain lookup.

### target-cli
Thin CLI wrapper using click. Commands: `target index [--embed]`, `target index-stdin`, `target
query [--top-n N] [--mode hybrid|lex|sem] [--json-output] [--audit]`, `target explain [--top-n N]
[--mode hybrid|lex|sem] [--json-output] [--verbose]`, `target embed`,
`target stats`, `target correct`, `target uncorrect`, `target corrections [--doc-key KEY]`,
`target eval snapshot`, `target eval diff`, `target eval report`, `target eval tune`,
`target eval benchmark`.
Query mode controls search method: `hybrid` (default, combines BM25 + semantic + corrections),
`lex` (keyword only, no model loading), `sem` (vector only). When no embeddings exist,
hybrid silently falls back to lexical-only. `--audit` includes correction chain info in results.
JSON output includes per-result feature breakdown and reason codes including `CORRECTOR` and
`CORRECTED`.

## Data Flow

Indexing path: Sources → target-ingest → (target-lex + target-sem) in parallel.
Correction path: `target correct` → target-correct (stores edges in correction_edges table).

Query path: CLI → target-lex (BM25 candidates) + target-sem (vector candidates) in parallel →
union + dedupe → target-correct (correction scores per doc_key) → target-rank (weighted merge) →
target-explain (citations + evidence + dominant factors) → CLI output.

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python | Ecosystem fit: embedding models, sqlite-vec, numpy; existing scripts are Python |
| Database | SQLite (WAL mode) | Single-file, zero-config, backupable as one file |
| FTS | FTS5 (built-in) | Mature, fast, BM25 out of the box |
| Vector search | sqlite-vec | First-class Python bindings, same SQLite file |
| Embeddings | all-MiniLM-L6-v2 (default) | Small, fast, good general text quality |
| Testing | pytest | Standard; fixtures for known-answer evaluation |
| CLI | click | Thin wrapper, not the focus |
