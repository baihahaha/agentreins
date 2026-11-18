# Changelog

All notable changes are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/). Before 1.0, minor versions may contain breaking changes.

## [Unreleased]

### Added
- Storage (M2): `Ledger` (redact, check, store), `project_messages` (events -> conversation), `SQLiteEventStore` (default, stdlib only, WAL + `synchronous=FULL`), `InMemoryEventStore`, `PassThroughRedactor`, `RedactionError`; contract tests for EventStore and Redactor.
- `agentreins.types.events` (M1b): event envelope and the 11 event types (run, model, tool lifecycle), flat and discriminated on `type`; `RunRef`. ADR-0001 accepted.
- `agentreins.types` (M1a): content blocks and messages, model request/response and stream events, tool and policy types, Principal, leak-proof Credentials, Document/MemoryItem, Budget/Usage, error hierarchy, UUIDv7 IDs.
- Package layout (architecture step 4): the ten port interfaces in `agentreins.ports`, placeholder types, empty core engine and adapter modules.
- Architecture test enforcing the layer dependency rule and the core dependency policy.
- Project scaffold: packaging (hatchling, uv), CI (ruff, pyright strict, pytest on Python 3.11–3.14), PyPI release workflow, Apache-2.0 license, contributor and security docs.
