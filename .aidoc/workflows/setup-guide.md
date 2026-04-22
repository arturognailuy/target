---
domain: Workflows
status: Active
entry_points:
  - pyproject.toml
dependencies:
  - .aidoc/workflows/development-plan.md
  - .aidoc/conventions/testing-strategy.md
---

# Setup Guide

How to set up a development environment for Target, run the project, and execute tests.
Target uses `pyproject.toml` (PEP 621) for dependency management — no `requirements.txt` needed.

## Related Docs

| Document | Relationship |
|----------|-------------|
| [Development Plan](development-plan.md) | Build phases and current status |
| [Testing Strategy](../conventions/testing-strategy.md) | Test levels and how to run them |
| [Interface Contract](../designs/interface-contract.md) | CLI commands and public API |

## Why This Approach

Target follows modern Python packaging standards. `pyproject.toml` declares both runtime and
development dependencies in one place, replacing the older `setup.py` + `requirements.txt` pattern.
A virtual environment isolates project packages from the system Python installation, keeping the
global environment clean.

For reproducible pinned installs, options like `pip-compile` (pip-tools), `uv`, or `poetry` can
generate lock files from `pyproject.toml` — but for a small project, `pip install -e ".[dev]"` in
a venv is clean and sufficient.

## Environment Setup

Create and activate a virtual environment, then install Target in editable mode with dev extras:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `.venv` directory is already in `.gitignore`.

## Running Tests

With the venv active:

```
pytest -v
```

See `testing-strategy.md` for details on unit, module-level, and integration test design.

## Quick Start

Index a document and query it:

```
target index "doc:readme" README.md
target query "search ranking"
```

Pipe content via stdin:

```
echo "some text" | target index-stdin "doc:example"
```

View index statistics:

```
target stats
```

## Deactivating

When done working on the project:

```
deactivate
```

## Data Files

Target creates a `target.db` SQLite database in the working directory by default.
This file is in `.gitignore` (`*.db`) to prevent accidentally committing test data.
