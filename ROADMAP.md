# Roadmap

Work proceeds in milestones; each ends with something runnable. Dates are a reference only, not deadlines.

**Process per module** (see [docs/dev/LEARNING_PROTOCOL.md](docs/dev/LEARNING_PROTOCOL.md)): plan → maintainer approves → implementation with tests on a branch (one reviewable change, about 300–400 lines) → review notes → maintainer approves → merge. Design choices not covered by an ADR are raised, never decided silently.

Rule: **cut scope, not reliability.**

## Done

- [x] Requirements ([docs/REQUIREMENTS.md](docs/REQUIREMENTS.md))
- [x] Module map and project structure ([ARCHITECTURE.md](ARCHITECTURE.md))
- [x] Port interfaces (ADR-0002 to ADR-0011)
- [x] Package layout with stubs and architecture test

## Milestones

| # | Milestone | Modules | Result |
|---|---|---|---|
| **M1** | Vocabulary | Settle ADR-0001 (event model); all of `types/` | Every data shape the framework uses |
| **M2** | Storage | `ledger/`; in-memory and SQLite event stores; pass-through redactor; contract tests for EventStore and Redactor | Save and read a run's log; storage survives crashes |
| **M3** | Tools | `tools/` (decorator, registry, harness); Python tool source; default policy; environment credentials | A Python function becomes a governed tool |
| **M4** | Models | Fake model; OpenAI Chat Completions adapter; recorded-response tests; ModelAdapter contract tests | Call OpenAI-compatible providers (OpenAI, Kimi, Ollama…) through the port |
| **M5** | First agent | `context/`; keep-all strategy; `runtime/` (loop, hooks); `examples/01_hello_tool.py` | **A complete agent runs**, offline (Fake) and live (OpenAI) |
| **M6** | Durability | `ledger/recovery`; `session/`; run keys; crash-injection tests | Kill an agent mid-run and resume it |
| **M7** | Control | Interrupts and approvals; rules policy; secrets redactor; `testing.no_governance()` | Human approval for actions |
| **M8+** | Breadth | MCP; truncation; memory tools; knowledge extra (Chroma, text-to-SQL); Anthropic adapter; supply-chain example; docs site | Real-world features |

Releases: publish **0.1.0** to PyPI after M5; **v0.5 (API freeze)** after M7 plus MCP and the docs site.

## Documentation

| When | What |
|---|---|
| Every milestone | Its page in [docs/internals/](docs/internals/README.md) (how the code works), in the same PR |
| After M5 (0.1.0) | Docs site (mkdocs): API reference generated from docstrings, plus a quickstart |
| M8 | User guide on the docs site: defining tools, policies, stores, deployment |

## CI hardening

Done: dependencies installed with `uv sync --locked`, job timeouts, merged branches auto-deleted.

**At the start of M4** (CI starts holding an API key):
- [ ] Pin every third-party action to a commit SHA (with the version in a comment)
- [ ] Add `.github/dependabot.yml` for `github-actions` and `uv`
- [ ] Nightly scheduled workflow running `live` tests, with provider keys stored as repository secrets

**Before publishing 0.1.0** (CI starts publishing to PyPI):
- [ ] Release only tested code: run the checks in `release.yml`, or restrict `v*` tags to commits on `main`
- [ ] Create the `pypi` environment with protection rules (only `v*` tags, required approval)
- [ ] Register the PyPI trusted publisher for `release.yml`

Optional: dependency caching (`setup-uv` with `enable-cache: true`).

## Later (post-1.0, unordered)

Graph package on top of sessions; knowledge manager (metadata management); OpenTelemetry exporter; Postgres event store; platform plug-ins (e.g. `agentreins-aws`); handoffs.
