# agentreins: instructions for coding agents

Read ARCHITECTURE.md and docs/dev/LEARNING_PROTOCOL.md first.

- **Working model (decided 2026-11-17): Claude writes, the maintainer reviews and approves.** For every module: first present a short plan (what it does, key choices, tests) and wait for approval. Then implement with tests. The maintainer reviews before it is merged. One module at a time.
- Design decisions belong to the maintainer: if implementation reveals a choice not covered by an ADR, stop and ask rather than deciding silently.
- Explain the code in review notes so the maintainer learns from it (why, trade-offs, what other frameworks do).
- Core dependency policy: stdlib + pydantic only. Anything else goes in an optional extra.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- Tests must run offline; real-provider tests are marked `live`.
