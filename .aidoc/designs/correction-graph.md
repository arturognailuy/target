---
domain: Designs
status: Active
entry_points:
  - src/target_search/correct.py
dependencies:
  - .aidoc/architecture/system-overview.md
  - .aidoc/designs/interface-contract.md
---

# Correction Graph Design

A directed acyclic graph (DAG) where edges represent "document A corrects/supersedes document B." Scores propagate transitively to boost correctors and penalize corrected documents in ranking. Cycle detection enforces DAG invariants.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [System Overview](../architecture/system-overview.md) | Architecture context for the correction module |
| [Interface Contract](interface-contract.md) | Public API surface including correction commands |

## Why a Graph

Documents evolve: later information corrects, supersedes, or refines earlier claims. A flat index treats all versions equally. The correction graph encodes temporal truth — when two documents conflict on the same topic, the corrector should rank higher than the corrected.

This is distinct from simple "freshness" (recency decay). Recency approximates truth by time; correction edges express explicit causal relationships: "this document exists *because* that one was wrong."

## Graph Model

- **Nodes:** documents identified by `doc_key` (must exist in the `records` table).
- **Edges:** directed — `corrector_doc_key → corrected_doc_key` means "corrector supersedes corrected."
- **Edge attributes:** `edge_type` (default: `supersedes`), `confidence` (0.0–1.0, default 1.0), `reason` (optional human-readable note).
- **Storage:** `correction_edges` table (schema v2) with unique constraint on `(corrector_doc_key, corrected_doc_key)`. Upserts update confidence/reason.

## DAG Invariants

The graph must remain a DAG. Two invariants are enforced at edge-insertion time:

1. **No self-correction:** `corrector == corrected` is rejected immediately.
2. **No cycles:** Before inserting `A → B`, BFS traversal checks whether `B` can already reach `A` via existing edges. If reachable, the edge would create a cycle and is rejected.

Both checks run before the INSERT, so the database never contains invalid state.

## Scoring Formula

Each document receives a correction score in `[-1.0, 1.0]`:

```
score = Σ(direct_corrections × 0.5 × confidence)
      + Σ(transitive_corrections × 0.25)
      - Σ(direct_corrected_by × 0.5 × confidence)
      - Σ(transitive_corrected_by × 0.25)
```

Clamped to `[-1.0, 1.0]`.

**Rationale for the weights:**
- Direct edges carry stronger signal (±0.5) because they represent explicit, intended corrections.
- Transitive edges carry weaker signal (±0.25) because the relationship is inferred through a chain — the corrector may not have been aware of all ancestors/descendants.
- Confidence weighting on direct edges allows partial corrections (e.g., "mostly right but one detail changed" at confidence 0.6).
- Transitive edges use count-based scoring (not confidence-weighted) because aggregating confidence across chains is unreliable.

**How it feeds into ranking:** The correction score is feature `C` in the ranking formula: `score = w_s·S + w_l·L + w_r·R + w_c·C + w_t·T`. Default weight `w_c = 0.10`.

## Traversal

Two BFS functions support transitive queries:

- **`_get_transitive_correctors(doc_key)`** — walks *up* the graph (following `corrected_doc_key → corrector_doc_key` edges) to find all ancestors. Used for penalty propagation.
- **`_get_transitive_corrected(doc_key)`** — walks *down* the graph (following `corrector_doc_key → corrected_doc_key` edges) to find all descendants. Used for boost propagation.

Both are also used by `get_correction_chain()` for audit mode output.

## Edge Cases

| Case | Behavior |
|------|----------|
| Self-correction (`A → A`) | Rejected with ValueError |
| Duplicate edge (`A → B` twice) | Upsert — updates confidence and reason |
| Diamond (`A→B`, `A→C`, `B→D`, `C→D`) | Valid DAG. D gets penalty from both paths; scores clamp at -1.0 |
| Multiple correctors (`A→C`, `B→C`) | Valid. C's penalty = sum of both edges (clamped) |
| Removing an edge | Deletes from DB. Does not cascade — other edges remain |
| Referenced doc_key missing from records | Rejected with ValueError at edge creation |

## Schema Migration

The `correction_edges` table was added in schema v2. Existing v1 databases are migrated automatically on open: the table is created if absent, and `schema_version` is updated. No data migration needed — v1 databases simply have zero correction edges.

## Code Pointers

- Edge management + cycle detection + scoring: `src/target_search/correct.py`
- Schema DDL (v2 migration): `src/target_search/db.py`
- Ranking integration: `src/target_search/rank.py` (calls `correction_scores()`)
- CLI commands: `target correct`, `target uncorrect`, `target corrections`
- Tests: `tests/test_correct.py` (28 tests)
