---
domain: Conventions
status: Draft
entry_points: []
dependencies:
  - .aidoc/conventions/testing-strategy.md
  - .aidoc/architecture/system-overview.md
  - .aidoc/designs/correction-graph.md
---

# End-to-End Test Plan

End-to-end tests exercise the full Target pipeline — ingest → lex + sem → correct → rank →
explain — as a single flow with realistic data. They complement unit tests (which verify modules
in isolation) by catching integration bugs like the Phase 3 lex-only ranking bypass.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [Testing Strategy](testing-strategy.md) | Parent testing approach; E2E extends integration level |
| [System Overview](../architecture/system-overview.md) | Pipeline being tested end-to-end |
| [Correction Graph](../designs/correction-graph.md) | Correction logic validated by E2E tests |
| [Development Plan](../workflows/development-plan.md) | E2E tests precede Phase 5 (evaluation) |

## Why E2E Before Phase 5

Phase 5 involves tuning ranking weights, chunk sizes, and candidate pool sizes. Each change risks
breaking existing behavior. E2E tests provide three things:

1. **Regression safety net.** A "nothing broke" gate before and after each tuning iteration.
2. **Eval harness foundation.** The fixture → index → query → assert pipeline is the scaffold
   that Phase 5 extends with precision@k, correction recall, and noise rate metrics.
3. **Coverage gap closure.** 126 unit/module tests exist, but no test exercises the full pipeline
   with realistic multi-document data. The Phase 3 lex-only ranking bug is the kind of issue E2E
   tests are designed to catch.

## Fixture Corpus

A curated set of 15–20 documents in `tests/fixtures/e2e/`, each a short markdown file with
controlled content. The corpus covers:

- **Topical clusters.** 3–4 topic groups (e.g., "server config", "deployment", "database",
  "authentication") with 4–5 documents each.
- **Known relationships.** Documents within a cluster share terms and semantics so retrieval
  results are predictable.
- **Corrections.** At least 3 correction pairs: one document supersedes another on a specific
  claim (e.g., port number changed, password policy updated, deployment target moved).
- **Varying trust levels.** Documents tagged with different source types (memory, email, dream)
  to exercise trust weighting.
- **Edge cases.** One very short document (single sentence), one longer document (multiple
  paragraphs / multiple chunks), one with CJK content, one with code blocks.

Each fixture file uses a naming convention: `<topic>-<sequence>.md` (e.g., `server-01.md`,
`server-02-correction.md`).

A manifest file `tests/fixtures/e2e/manifest.json` maps each fixture to its doc_key, source_type,
trust_level, and any correction relationships. This is the single source of truth for test
expectations.

## Test Suites

All E2E tests live in `tests/test_e2e.py` and use a shared database built from the fixture
corpus in a session-scoped pytest fixture.

### 1. Pipeline Tests

Full ingest → query → assert flow:

- **Topical retrieval.** For each topic cluster, query with a representative term. Assert the
  top-k results are all from the correct cluster.
- **Cross-topic isolation.** Query for topic A; assert topic B documents don't appear in top-k.
- **All query modes.** Each pipeline test runs in lex, sem, and hybrid modes. Results may differ
  in ordering but the correct cluster should dominate top-k in all modes.

### 2. Correction Regression Tests

- **Corrector outranks corrected.** For each correction pair, query the corrected topic. Assert
  the corrector ranks strictly higher than the corrected document.
- **Transitive correction.** If A corrects B and B corrects C, query the topic. Assert
  A > B > C in ranking.
- **Audit mode.** Run the same queries with `--audit`. Assert correction annotations are present
  (corrector shows "✓ Corrects", corrected shows "⚠ Corrected by").

### 3. Trust and Recency Tests

- **Trust weighting.** Index two documents with identical content but different trust levels.
  Assert the higher-trust document ranks first.
- **Recency decay.** Index two documents with identical content but different dates. Assert the
  more recent document ranks first (when other factors are equal).

### 4. Explain Output Validation

- **Citation presence.** For each top-k result, assert a citation string is generated.
- **Correction evidence.** For correction pairs, assert explain output includes correction chain
  evidence (corrector/corrected labels, edge metadata).
- **Feature breakdown.** In verbose/JSON mode, assert all five features (S, L, R, C, T) are
  present and within expected ranges.

### 5. Edge Case Tests

- **Empty corpus.** Query against an empty database. Assert empty results, no crash.
- **Single-document corpus.** Index one document, query. Assert it appears as the sole result.
- **Re-index idempotency.** Index the full corpus, query, record results. Re-index the same
  corpus. Query again. Assert results are identical.
- **CJK content.** Query with CJK terms against the CJK fixture. Assert it appears in results.

## Known-Answer Pairs

The manifest includes a `queries` section with expected results:

```json
{
  "queries": [
    {
      "text": "server port number",
      "expected_top_3": ["server-02-correction", "server-01", "server-03"],
      "must_outrank": [["server-02-correction", "server-01"]]
    }
  ]
}
```

Each query specifies:
- `expected_top_3`: the doc_keys that should appear in the top 3 (order-sensitive for
  correction pairs, order-flexible otherwise).
- `must_outrank`: pairs where the first must rank strictly above the second (correction
  assertions).

## Embedding Strategy

E2E tests use the real embedding model (all-MiniLM-L6-v2) for semantic and hybrid modes.
This is intentional — E2E tests validate the full pipeline including real embeddings.

Tests that run the embedding model are marked with `@pytest.mark.slow` so they can be skipped
in fast CI runs (`pytest -m "not slow"`). The CI matrix runs the full suite including slow
tests on one Python version (3.12) and fast-only on the others.

## Success Criteria

Before Phase 5 begins:
- All fixture-based pipeline tests pass in all three modes (lex, sem, hybrid).
- All correction regression tests pass (corrector always outranks corrected).
- Explain output validation passes for all top-k results.
- No test depends on exact floating-point scores (use ranking order and presence assertions).
- Tests run in under 60 seconds on CI (excluding model download on first run).
