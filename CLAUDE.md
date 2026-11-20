# agentreins: instructions for coding agents

Read ARCHITECTURE.md, docs/internals/README.md and docs/dev/LEARNING_PROTOCOL.md first.

- **Working model (decided 2026-11-17): Claude writes, the maintainer reviews and approves.** For every module: first present a short plan (what it does, key choices, tests) and wait for approval. Then implement with tests. The maintainer reviews before it is merged. One module at a time.
- Design decisions belong to the maintainer: if implementation reveals a choice not covered by an ADR, stop and ask rather than deciding silently.
- Explain the code in review notes so the maintainer learns from it (why, trade-offs, what other frameworks do).
- Core dependency policy: stdlib + pydantic only. Anything else goes in an optional extra.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- Tests must run offline; real-provider tests are marked `live`.
- Every milestone PR adds or updates its page in `docs/internals/` (walkthrough, guarantees with their tests, design choices, limits). Line links must still point at the right code.
- Public classes, methods and functions need docstrings (ruff `D101`–`D103`; adapter methods inherit the port's). They become the API reference.
- Commits and PRs are in the maintainer's name only: no `Co-Authored-By: Claude` trailer and no "Generated with Claude Code" footer.
