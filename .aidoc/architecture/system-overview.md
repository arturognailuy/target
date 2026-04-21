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
all-MiniLM-L6-v2 via sentence-transformers). Stores vectors in sqlite-vec. Accepts a query,
embeds it, and returns chunks ranked by cosine similarity.

### target-correct
Maintains a directed correction graph ("doc A corrects doc B"). Provides correction score
modifiers for ranked results — boosting correctors, demoting corrected documents. Propagates
correction chains (A corrects B, B corrects C → A dominates C).

### target-rank
Weighted merge layer. Combines scored candidate sets from lex, sem, and correct into a final
ranked list. Scoring formula: `score = w_s·S + w_l·L + w_r·R + w_c·C + w_t·T` where S=semantic,
L=lexical, R=recency, C=correction, T=trust. Weights are configurable; zeroing a weight disables
that provider. Produces deterministic output for the same corpus, query, and weights.

### target-explain
Generates citations and evidence for ranked results. Each result gets traceable evidence pointers,
reason codes (e.g., `SEM_MATCH`, `LEX_MATCH`, `CORRECTED`), and human-readable citation strings.

### target-cli
Thin CLI wrapper (argparse or click). Commands: `target index`, `target query [--top-n N]`,
`target explain`. Output in JSON (machine) or formatted text (human).

## Data Flow

Indexing path: Sources → target-ingest → (target-lex + target-sem + target-correct) in parallel.

Query path: CLI → target-lex (BM25 candidates) + target-sem (vector candidates) in parallel →
union + dedupe → target-correct (correction features) → target-rank (weighted merge) →
target-explain (citations) → CLI output.

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python | Ecosystem fit: embedding models, sqlite-vec, numpy; existing scripts are Python |
| Database | SQLite (WAL mode) | Single-file, zero-config, backupable as one file |
| FTS | FTS5 (built-in) | Mature, fast, BM25 out of the box |
| Vector search | sqlite-vec | First-class Python bindings, same SQLite file |
| Embeddings | all-MiniLM-L6-v2 (default) | Small, fast, good general text quality |
| Testing | pytest | Standard; fixtures for known-answer evaluation |
| CLI | argparse or click | Thin wrapper, not the focus |
