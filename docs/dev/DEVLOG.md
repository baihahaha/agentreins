# Devlog

Short weekly notes: what shipped, what was learned, what's blocked. Newest first.

## Week 1 (2026-11-16 → 11-22)

- Re-scoped from a learning lab to the open-source project **agentreins**. Target v0.5 ~2027-01-10.
- Decisions: event-sourced runtime; pydantic is the only core dependency; httpx adapters, no vendor SDKs; Apache-2.0.
- Cut from the critical path: cloud platform tours, multi-framework re-implementations, the B2C capstone (B2B supply-chain becomes the reference example).
- Repo scaffold: uv, ruff, pyright strict, pytest, CI matrix 3.11–3.14, release via PyPI trusted publishing.
- Architecture steps 1–4 done: requirements, module map, ten port ADRs (0002–0011), package layout with an architecture test.
- Working model changed (11-17): Claude Code writes the code; the maintainer plans, reviews and approves. One PR per module; `main` is protected.
- Next: settle ADR-0001's three questions, then start M1 (`types/`).
