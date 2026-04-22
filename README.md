# Target

General-purpose document search and ranking. Indexes documents by key, retrieves them via hybrid BM25 + semantic search with correction-aware ranking and explainable results.

## Quick Start

```bash
pip install -e ".[dev]"
target index "doc:readme" README.md
target query "search ranking"
```

For semantic search: `pip install -e ".[dev,semantic]"` and use `target index key file --embed`.

## Documentation

This project uses [AI-Native documentation](https://github.com/gnailuy/target/tree/main/.aidoc) in `.aidoc/` for detailed architecture, design, and workflow docs.

Full documentation index: [.aidoc/INDEX.md](.aidoc/INDEX.md)
- [System Overview](.aidoc/architecture/system-overview.md) — architecture and modules
- [Interface Contract](.aidoc/designs/interface-contract.md) — public API
- [Setup Guide](.aidoc/workflows/setup-guide.md) — environment setup and development

## License

MIT
