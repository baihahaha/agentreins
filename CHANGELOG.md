# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/). Before 1.0, minor versions may contain breaking changes.

## [Unreleased]

### Added
- Runtime engine (M5a): the agent loop (`Runtime.run`) with parallel tool calls, retries with backoff, step/token/wall-time budgets, cancellation, and every step in the event log; `ContextManager` with the keep-all strategy; hook dispatch; `RunError`. Context-strategy contract tests.
- Models (M4): `FakeModel` (scripted, for tests and examples) and `OpenAIChatModel` (OpenAI Chat Completions and compatible servers, via `httpx` in the `providers` extra) with streaming and normalized errors; ModelAdapter contract tests; recorded tests replaying real OpenAI responses; live tests (`pytest -m live`).
- Internals guide (`docs/internals/`): overview of one agent run, plus pages for types, storage and tools. Docstrings required on public code (ruff `D101`–`D103`); a test keeps doc links valid.
- Tools (M3): `@tool` decorator and `PythonToolSource` (pydantic-validated arguments), `ToolRegistry`, `ToolHarness` (check -> prepare -> execute; policy timeout and fail-closed handling; credential scrubbing), built-in basic schema check, optional `ArgumentValidator` port, `DefaultPolicy`, `EnvCredentialProvider`; rejection reason `credentials_unavailable`.
- Storage (M2): `Ledger` (redact, check, store), `project_messages` (events -> conversation), `SQLiteEventStore` (default, stdlib only, WAL + `synchronous=FULL`), `InMemoryEventStore`, `PassThroughRedactor`, `RedactionError`; contract tests for EventStore and Redactor.
- `agentreins.types.events` (M1b): event envelope and the 11 event types (run, model, tool lifecycle), flat and discriminated on `type`; `RunRef`. ADR-0001 accepted.
- `agentreins.types` (M1a): content blocks and messages, model request/response and stream events, tool and policy types, Principal, leak-proof Credentials, Document/MemoryItem, Budget/Usage, error hierarchy, UUIDv7 IDs.
- Package layout (architecture step 4): the ten port interfaces in `agentreins.ports`, placeholder types, empty core engine and adapter modules.
- Architecture test enforcing the layer dependency rule and the core dependency policy.
- Project scaffold: packaging (hatchling, uv), CI (ruff, pyright strict, pytest on Python 3.11–3.14), PyPI release workflow, Apache-2.0 license, contributor and security docs.
