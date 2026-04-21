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

- **Default mode:** returns current-best truth (corrections outrank originals)
- **Audit mode** (`--audit`): includes superseded claims with full correction chain lineage

## Design Principles

1. **Minimal interface.** Consumers see only `index()` and `query()`.
2. **General purpose.** Any `(key, text)` source can use Target.
3. **Correctness over speed.** Deterministic ranking for the same corpus and query.
4. **No private information.** Open-source project; code and docs must not contain private data.

## Invariants

- Re-indexing the same doc_key MUST replace previous chunks (idempotent upsert).
- Query output MUST be deterministic for the same corpus, query, and weight configuration.
- Correction edges MUST propagate transitively (A corrects B, B corrects C → A dominates C).
