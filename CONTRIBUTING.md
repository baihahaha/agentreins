# Contributing

Thanks for your interest! agentreins is early (pre-alpha), so please **open an issue before a large PR** so we can agree on the design first.

## Setup

```bash
git clone https://github.com/baihahaha/agentreins && cd agentreins
uv sync --all-extras        # creates .venv with dev tools
```

## Before you push

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```

CI runs the same checks on Python 3.11–3.14.

## Guidelines

- **Tests are required** for behavior changes. Tests must run offline. Use `FakeModel` or recorded provider responses. Tests that call real APIs are marked `@pytest.mark.live` and are skipped in CI.
- **Public API** is what `agentreins/__init__.py` exports. Changing it needs a CHANGELOG entry; breaking it needs a discussion.
- **Architectural changes** need an ADR in `docs/adr/` (copy `0000-template.md`).
- **Dependencies:** the core may depend only on `pydantic`. New dependencies go behind an optional extra and need justification in the PR.
- Commits: small and focused; imperative subject line ("Add tool timeout").
- Update `CHANGELOG.md` under "Unreleased" for user-visible changes.

## Code of conduct

See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
