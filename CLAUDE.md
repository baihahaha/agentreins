# agentreins: instructions for coding agents

Read ARCHITECTURE.md and docs/dev/LEARNING_PROTOCOL.md first.

- **Kernel code is hand-written by the maintainer.** Do not write implementations of: the content/event model, agent loop, tool harness, event store, resume/reconciliation, interrupts. For these: review, challenge, propose tests, give hints. Only write them if the maintainer explicitly asks for that specific piece.
- You may write: CI, packaging, docs, templates, examples, test fixtures and scaffolding, glue code.
- Core dependency policy: stdlib + pydantic only. Anything else goes in an optional extra.
- Checks: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`
- Tests must run offline; real-provider tests are marked `live`.
