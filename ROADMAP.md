# Roadmap

**Capacity:** about 10 hours/week, one maintainer. **Targets:** v0.5 (core API frozen) around **2027-01-10**; v1.0-rc by **2027-02-05** (stretch).
Releases are tracked as GitHub milestones. Weekly status lives in [docs/dev/DEVLOG.md](docs/dev/DEVLOG.md).

Rule: **cut scope, not reliability.** If a week slips, drop the lowest item in that release, never the tests.

## v0.1: The loop (weeks 1–2, Nov 16 – Nov 29)

- [ ] Repo foundation: packaging, CI, lint/type/test, license, contributor docs
- [ ] ADR-0001: content and event model (accepted)
- [ ] `FakeModel`: scripted, deterministic model for tests
- [ ] Async `Agent.run()` with a max-step guard
- [ ] Tool registry: `@tool` decorator, pydantic schemas from type hints, effect class
- [ ] Tool harness: validation errors, unknown tool, exceptions, timeouts → structured `tool_result` errors
- [ ] Parallel tool calls with stable call IDs
- [ ] Tests: final answer, tool call, unknown tool, invalid args, tool failure, step limit
- [ ] **Publish 0.1.0 to PyPI**

## v0.2: Real models (week 3, Nov 30 – Dec 6)

- [ ] Streaming adapter interface
- [ ] Anthropic Messages adapter (httpx)
- [ ] OpenAI-compatible Chat Completions adapter (httpx; covers OpenAI, Kimi, vLLM, Ollama)
- [ ] Record/replay contract tests (offline in CI; live tests opt-in)
- [ ] Usage + cost accounting per run; token/cost budgets

## v0.3: Durability (weeks 4–5, Dec 7 – Dec 20)

- [ ] Event store interface; in-memory and SQLite implementations
- [ ] Projections: message history, run state
- [ ] `resume(run_id)` from the log
- [ ] Side-effecting tools: intent event + idempotency key; reconciliation on resume
- [ ] Failure-injection tests: kill mid-tool, mid-model-call, between events

## v0.4: Control (week 6, Dec 21 – Jan 3, holiday week, light)

- [ ] Interrupts: approval requests suspend the run; resume with a decision
- [ ] Policy hook before tool execution
- [ ] Cancellation and wall-time budget
- [ ] Hooks/middleware interface

## v0.5: Usable beta (weeks 7–8, Jan 4 – Jan 17)

- [ ] Context manager interface + truncation strategy (preserves tool_use/tool_result pairs)
- [ ] MCP client (stdio transport): MCP tools appear as registered tools
- [ ] Reference example: supply-chain disruption agent on a simulated ERP (approval + idempotent writes + crash recovery)
- [ ] Docs site (mkdocs-material): quickstart, concepts, API reference
- [ ] Threat model in SECURITY.md
- [ ] **API freeze**: everything public is documented and tested

## v1.0-rc (stretch, Jan 18 – Feb 5)

- [ ] OpenTelemetry tracing extra
- [ ] Summarization context strategy
- [ ] MCP streamable HTTP transport
- [ ] Small eval harness (completion rate, recovery success, cost per successful task)
- [ ] "How agentreins compares" doc (LangGraph, OpenAI Agents SDK, Claude Agent SDK)

## Later (post-1.0, unordered)

Agent-as-tool / delegation, workflow primitives, Postgres store, memory, A2A.
