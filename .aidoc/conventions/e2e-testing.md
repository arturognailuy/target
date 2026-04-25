---
domain: Conventions
status: Active
entry_points: []
dependencies:
  - .aidoc/conventions/testing-strategy.md
  - .aidoc/architecture/system-overview.md
  - .aidoc/designs/correction-graph.md
---

# End-to-End Testing

End-to-end tests exercise the full Target pipeline — ingest → lex + sem → correct → rank →
explain — as a single flow with realistic data. They complement unit tests (which verify modules
in isolation) by catching integration bugs that cross module boundaries.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [Testing Strategy](testing-strategy.md) | Parent testing approach; E2E extends integration level |
| [System Overview](../architecture/system-overview.md) | Pipeline being tested end-to-end |
| [Correction Graph](../designs/correction-graph.md) | Correction logic validated by E2E tests |

## Why E2E Testing

E2E tests provide three things that unit and module tests cannot:

1. **Regression safety net.** A "nothing broke" gate when changing ranking weights, chunk sizes,
   or candidate pool sizes.
2. **Eval harness foundation.** The fixture → index → query → assert pipeline is the scaffold
   for precision@k, correction recall, and noise rate metrics.
3. **Cross-module coverage.** Unit tests verify modules in isolation, but integration bugs
   (e.g., a query mode bypassing the ranking module) only surface when the full pipeline runs
   with realistic multi-document data.

## Fixture Corpus

A curated set of original sci-fi themed documents in `tests/fixtures/e2e/`, each a short
markdown file with controlled content. The corpus world-builds a shared universe inspired by
Asimov and Adams (no copyrighted text — all original writing).

Four topic clusters provide predictable retrieval targets: robotics & AI ethics, space travel &
galactic civilizations, comedy sci-fi & improbability, and first contact & alien biology.
Documents within a cluster share terms and semantics so retrieval results are predictable.

The corpus includes correction pairs with natural in-universe reasons, varying trust levels
(official encyclopedia entries vs. unverified transmissions), and edge cases (single-sentence
documents, multi-chunk documents, CJK content, code-like content).

A manifest file (`tests/fixtures/e2e/manifest.json`) maps each fixture to its doc_key,
source_type, trust_level, correction relationships, and known-answer query expectations.
See the manifest and test code for implementation details.

## Test Suites

All E2E tests live in `tests/test_e2e.py` and use a shared database built from the fixture
corpus in a session-scoped pytest fixture.

### 1. Pipeline Tests

Full ingest → query → assert flow. For each topic cluster, query with a representative term
and assert the top-k results are from the correct cluster. Cross-topic isolation verifies that
unrelated clusters don't leak into top-k. Each test runs in lex, sem, and hybrid modes.

### 2. Correction Regression Tests

For each correction pair, query the corrected topic and assert the corrector ranks strictly
higher. Transitive correction chains are validated (A > B > C). Audit mode validates
correction annotations are present.

### 3. Trust and Recency Tests

Controlled equal-content comparisons: higher trust ranks first; more recent ranks first
(when other factors are equal).

### 4. Explain Output Validation

Citation presence, correction evidence, and feature breakdown (S, L, R, C, T) are validated
for top-k results in verbose/JSON mode.

### 5. Edge Case Tests

Empty corpus (no crash), single-document corpus, re-index idempotency (results identical
after re-indexing), and CJK content retrieval.

## Embedding Strategy

E2E tests use the real embedding model (all-MiniLM-L6-v2) for semantic and hybrid modes.
Tests requiring the model are marked `@pytest.mark.slow` — skippable in fast CI runs
(`pytest -m "not slow"`). The CI matrix runs the full suite on Python 3.12 and fast-only
on the others.

## Success Criteria

- All fixture-based pipeline tests pass in all three modes (lex, sem, hybrid).
- All correction regression tests pass (corrector always outranks corrected).
- Explain output validation passes for all top-k results.
- No test depends on exact floating-point scores (use ranking order and presence assertions).
- Tests run in under 60 seconds on CI (excluding model download on first run).
