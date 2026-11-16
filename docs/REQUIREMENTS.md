# agentreins: Requirements

- **Status:** step 1 of the architecture process, agreed 2026-11-16
- **Phases** (v0.1, v0.5…) in this document are a reference for ordering, not deadlines.
- **Process:** (1) requirements → (2) module map → (3) interface contracts → (4) repo layout with stubs → (5) fill modules one by one. Each step is agreed before the next starts.

## 1. Target user

Python developers building agents that **take real actions in business systems** (operations, back-office automation, internal tools), where a wrong or duplicated action costs money. A typical run calls tools with side effects, may wait minutes to days for human approval, and must survive process crashes.

**Not targeted:** chatbots, quick research prototypes, no-code users.

agentreins competes on *safest to run in production*, not *easiest to start*.

## 2. Requirement structure

| Part | Question |
|---|---|
| **Capabilities** (§3) | What can I build with it? |
| **Governance** (§4) | Who may do what, and how is it controlled and proven? |
| **Guarantees** (§6) | How reliably does it behave, especially under failure? |

Design principle: **general through a few primitives that compose, plus extension points, not through built-in features.** The architecture covers every requirement below from the start; the implementation is delivered in phases.

Bins: **Core** = built in and always present. **Extension point** = interface defined by agentreins, with a simple default; users or plug-ins provide alternatives. **Out of scope** = owned by the host application or platform; agentreins connects to it.

## 3. Capabilities

| # | Capability | Bin | What agentreins provides | Phase |
|---|---|---|---|---|
| C1 | Agent loop | Core | Multi-step model ↔ tool loop, parallel tool calls, streaming | v0.1–0.2 |
| C2 | Tools | Core + extension | Core: tool registry, tool harness, Python-function tools. Extension: **tool source** (MCP is the first) | v0.1; MCP v0.5 |
| C3 | Context | Core + extension | Core: context manager. Extensions: **context strategy** (default: keep all, then truncation), **retriever** (vector or keyword search; first-party Chroma retriever in `agentreins[knowledge]`, see D6) | v0.1; truncation v0.5 |
| C4 | State & memory | Core + extension | Core: run state from the event log. Extensions: **event store**, **memory store** | v0.1–0.3; memory later |
| C5 | Composition | Core (minimal) | Plain Python orchestration, **sessions**, **run keys**, agent-as-tool | after v0.5 |
| C6 | Human interaction | Core | Interrupts (pause/resume), event stream for UIs. UI itself out of scope | v0.4 |
| C7 | Structured output | Core | Final result validated as a pydantic model | v0.2 |
| C8 | Models | Extension | **Model adapter**; ships Fake, Anthropic, OpenAI-compatible | v0.1–0.2 |

## 4. Governance

| # | Governance | Bin | What agentreins provides | Phase |
|---|---|---|---|---|
| G1 | Identity | Core carries; authentication out of scope | `Principal` attached to every run and session, passed to tools and policy | v0.4 |
| G2 | Authorization | Extension, enforced by core | **Policy** consulted by the harness before every tool call | v0.4 |
| G3 | Approval rules | Core mechanism | A policy answer of `RequireApproval` pauses the run (see D4) | v0.4 |
| G4 | Audit | Core | The event log is the audit trail; hooks export it | v0.3 |
| G5 | Cost & resources | Core per run/session; extension across sessions | Budgets per run and per session; cross-session quotas via an interface | v0.2; quotas later |
| G6 | Data protection | Core rule + extension | Core rule: credentials never appear in events. Extension: **redactor** applied before anything is stored | v0.3 |
| G7 | Observability | Core hooks + optional extra | **Hooks**; OpenTelemetry exporter as an optional extra | 1.0-rc |
| G8 | Change control | Core | Every run records a fingerprint of the agent definition (prompt, tool schemas, model) | v0.3 |

### Identity and enterprise platforms

agentreins is the **enforcement point**, never the source of truth. It owns no identity, permission or business data.

- **Inbound (who is the agent acting for?):** the host application authenticates the user with its own platform (AWS, IBM, Okta, Entra ID…) and passes a verified `Principal` into the run. agentreins never verifies passwords or tokens itself.
- **Outbound (how do tools act as that user?):** tools get credentials from a **credential provider** (default: environment variables; later plug-ins such as AWS STS or OAuth token exchange), so the agent only ever has that user's permissions.
- **Stored:** only the agent's own execution record (event log), holding identity *IDs* and decisions, never tokens or business data. Business data stays in enterprise systems and is reached only through tools.

## 5. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **MCP is a tool source**, not built into the loop. The tool-source interface is modelled on MCP's concepts. MCP tools are treated as side-effecting unless configured otherwise. | Every tool, whatever its source, passes the same harness (validation, policy, approval, audit). MCP elicitation maps to interrupts; sampling maps to the model adapter. MCP prompts/resources arrive later via context/retriever. |
| D2 | **Long-term memory is a plug-in.** The core defines a `MemoryStore` (save, search, delete), always scoped to the principal, and ships only an in-memory reference implementation. Storage and search (vector DBs, mem0, cloud services) are plug-ins. Every memory access is recorded in the event log, after redaction. | No consensus across frameworks on storage, extraction or retrieval, and heavy dependencies. The three usage patterns map onto existing primitives: agent-driven = tools, after-run = hooks, auto-inject = context manager. Logging recalled memories keeps audit and resume correct. |
| D3 | **Composition is plain Python.** No graph or workflow language in the core for 1.0. A **session** groups runs under one key, principal and budget; **run keys** make re-executed orchestration code skip completed runs and resume half-finished ones. | Same control as a graph (`if` = path, `for` = bounded loop, business retry = loop; technical retries handled inside runs) without a new language. A graph package can be built on top later without core changes. |
| D4 | **Policy answers `Allow`, `Deny(reason)` or `RequireApproval(reason)`.** Policy never modifies arguments. Deny returns an error result to the model; RequireApproval pauses and persists the run. | One decision point for authorization and approval. Not modifying arguments keeps the model's view and the audit trail truthful. |
| D5 | **SQLite is the default event store**; in-memory is opt-in (tests, experiments). | Guarantee #1 must hold out of the box. SQLite is in the Python standard library; the cost (a local file, about 1 ms per step) is negligible next to model calls. |
| D6 | **Knowledge sources ship as a first-party optional extra, `agentreins[knowledge]`:** a Chroma vector retriever, and a text-to-SQL **tool** over SQLite. Both live in this repo, are tested in CI and used in examples, but are not part of the core install. A **retriever** means vector or keyword search only. Text-to-SQL is a governed **tool**: read-only connection, allow-listed tables, row limits, every query logged. | Users can try retrieval and structured-data queries out of the box, while the core install stays light (dependency policy, guarantee #7). Model-written SQL is an action the agent decides to take, so it goes through the tool harness (policy, approval, audit; guarantee #2) rather than being injected automatically. |

## 6. Guarantees (ranked: higher wins on conflict)

| # | Guarantee | Meaning |
|---|---|---|
| 1 | **Correct under failure** | A crash at any point can be resumed; a side-effecting tool never runs twice by accident. |
| 2 | **Safe by default** | Every tool call passes harness and policy, with no bypass. If policy cannot answer, the call is refused (**fail closed**). |
| 3 | **Bounded** | Every run and session terminates; budgets are always enforced. |
| 4 | **Auditable & reproducible** | Every decision is recorded (model requests, policy answers, approvals, memory used); runs can be replayed from the log. |
| 5 | **Testable offline** | Runs and sessions are fully testable without network or API keys. |
| 6 | **Portable** | No lock-in to a model provider or cloud; provider features live in adapters, never in the core. |
| 7 | **Small & readable** | Core under about 3,000 lines. |
| 8 | **Low overhead** | Single-digit milliseconds per step of framework overhead. |

Agreed conflict rules:

- **Correct > bounded:** when a budget runs out mid-tool, the tool **finishes and is recorded, then** the run stops.
- **Safe > available:** policy unavailable → refuse or pause, never run.
- **Correct > small/fast:** every step is persisted (hence D5).
- **Portable > features:** provider-specific features only inside adapters.

## 7. Extension points

All interfaces are defined in step 3, before any module is built, so the runtime is wired correctly from v0.1. Each has a working default or an explicit "none". Interfaces are **provisional** until a real implementation has exercised them, and are frozen at v0.5.

| Extension point | Default (phase) | Later |
|---|---|---|
| Model adapter | Fake (v0.1) | Anthropic, OpenAI-compatible (v0.2) |
| Tool source | Python functions (v0.1) | MCP (v0.5) |
| Context strategy | Keep all (v0.1) | Truncation (v0.5) |
| Retriever | Chroma vector retriever, via `agentreins[knowledge]` | more plug-ins (pgvector, Elasticsearch, keyword search…) |
| Memory store | in-memory reference | plug-ins |
| Event store | SQLite default, in-memory opt-in (v0.1) | plug-ins (Postgres…) |
| Policy | registered tools only (v0.1) | rules with three answers (v0.4) |
| Credential provider | environment variables (v0.2) | platform plug-ins |
| Redactor | pass-through (v0.1) | secret patterns (v0.3) |
| Hooks | built in (v0.1) | OpenTelemetry exporter (1.0-rc) |

## 8. Out of scope for 1.0

Authentication, identity providers and policy engines (connected to, not built); long-term memory and vector database implementations; graph/workflow language; UI; hosting; platform integration packages (e.g. `agentreins-aws`, post-1.0).

## 9. Open items for later steps

- Step 2: can any extension points be merged (e.g. redactor as a hook)?
- Policy module: exact default policy for side-effecting tools before v0.4.
- Composition module: first-class handoffs, or built from agent-as-tool?
- Memory module: runtime-driven vs agent-driven saving.
- Durability module: reconciliation contract for a side-effecting tool whose outcome is unknown after a crash.
- **Knowledge manager (parked):** metadata management for knowledge sources. Scope to be discussed later; the retriever and tool interfaces should not block it.
