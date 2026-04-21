---
domain: Conventions
status: Active
entry_points: []
dependencies: []
---

# Target — Documentation Index

Target is a general-purpose document search and ranking system that combines BM25 lexical search
with semantic vector similarity, plus correction-aware ranking, behind a minimal `index()`/`query()` interface.

## Document Inventory

| Document | Domain | Status | Summary |
|----------|--------|--------|---------|
| [System Overview](architecture/system-overview.md) | Architecture | Active | Six-module pipeline, data flow, technology stack |
| [Interface Contract](designs/interface-contract.md) | Designs | Active | Public API surface, design principles, invariants |
| [Testing Strategy](conventions/testing-strategy.md) | Conventions | Active | Unit, integration, and evaluation testing approach |
| [Development Plan](workflows/development-plan.md) | Workflows | Active | Five-phase build plan with deliverables |

## Reading Chains

**New contributor:** Interface Contract → System Overview → Testing Strategy → Development Plan

**Architecture deep-dive:** System Overview → Interface Contract

**Starting development:** Development Plan → Testing Strategy → System Overview
