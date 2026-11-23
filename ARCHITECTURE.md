# Architecture

- **Status:** step 2 (module map and project structure) agreed 2026-11-16. Step 3 (interface contracts) agreed 2026-11-17: one ADR per port, [ADR-0002](docs/adr/0002-model-adapter-port.md) to [ADR-0011](docs/adr/0011-memory-store-port.md). Step 4 (repo layout with stubs) done 2026-11-17. Step 5 (filling modules) follows the milestones in [ROADMAP.md](ROADMAP.md).
- **Requirements and decisions:** [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md). This file describes *how* the code is organized to meet them.
- **How the code works, end to end:** [docs/internals/](docs/internals/README.md), one page per area, updated with each milestone.
- **Detailed design of each module:** ADRs in [docs/adr/](docs/adr/), written when that module is built.

## Shape: ports and adapters

The core logic never talks to the outside world directly. It talks only to **ports** (interfaces). **Adapters** are the real implementations (Anthropic, SQLite, MCP, Chroma…). Swapping an adapter never touches the core. That is what makes runs testable offline and portable across providers and platforms.

```text
 Layer 4  PUBLIC API        Agent · tool · session · Allow/Deny/RequireApproval …
             |
 Layer 3  ORCHESTRATION     session   (run keys, session budget, principal)
             |
                            runtime   (the agent loop: steps, budgets, interrupts, hooks)
             |
 Layer 2  CORE ENGINES      tools     context     ledger
                            (registry (what the   (event log, redaction,
                             + harness) model sees) projections, resume)
             |
 Layer 1  PORTS             ToolSource · Policy · CredentialProvider · ModelAdapter ·
 (interfaces)               ContextStrategy · Retriever · MemoryStore · EventStore ·
                            Redactor · Hooks
             |
 Layer 0  TYPES             messages & content blocks · events · Principal · budgets · errors

 ───────────────── adapters (implement ports; plugged in at the public API) ─────────────────
 models: fake, anthropic, openai_compat     event stores: sqlite (default), in-memory
 tool sources: python functions, mcp        knowledge extra: chroma retriever, text-to-SQL tool
```

**Dependency rule:** a layer may only import from layers below it (enforced by `tests/unit/test_architecture.py`). Core engines and orchestration (layers 2–3) use only `types` and `ports`, never a specific adapter. Adapters use only `types` and `ports`. Only the public API wires adapters into the core as defaults.

## Modules

| Module | Owns | Does *not* own |
|---|---|---|
| **types** | Shared data shapes (messages, events, Principal, budgets, errors). Pure data, no logic | Behaviour |
| **ports** | The ten extension interfaces | Implementations |
| **tools** | The only path to run a tool: find → validate → policy → approval → credentials → execute → result | Deciding *when* to call a tool |
| **context** | Building what the model sees each turn: history, strategy, retrieved documents, memories | Storing history |
| **ledger** | Appending events (after redaction); rebuilding message history and run state from events; finding unfinished work on resume | Deciding what to do about unfinished work |
| **runtime** | One agent run: the loop, budgets, pausing for approval, calling hooks | Combining several runs |
| **session** | Grouping runs: run keys, session budget, shared principal | The loop itself |
| **public API** | The small, stable surface users import; wires default adapters | Logic |

## Project structure

```text
agentreins/
│
├── src/agentreins/
│   ├── __init__.py              # Layer 4 PUBLIC API: the only thing users import from.
│   │                            #   Re-exports Agent, tool, session, Allow/Deny/RequireApproval…
│   ├── py.typed
│   │
│   ├── types/                   # Layer 0 VOCABULARY: pure data shapes, no logic
│   │   ├── content.py           #   Message, TextBlock, ToolUseBlock, ToolResultBlock, ReasoningBlock, ImageBlock
│   │   ├── model.py             #   ModelRequest, ModelResponse, ModelStreamEvent, ModelCapabilities
│   │   ├── events.py            #   Event envelope + every event type (run.started, tool.call.requested…)
│   │   ├── tools.py             #   ToolSpec, ToolCall, ToolResult, Effect (read_only / idempotent / side_effecting)
│   │   ├── policy.py            #   Allow, Deny, RequireApproval
│   │   ├── identity.py          #   Principal, Credentials
│   │   ├── knowledge.py         #   Document, MemoryItem
│   │   ├── budget.py            #   Budget, Usage
│   │   └── errors.py            #   agentreins exception hierarchy
│   │
│   ├── ports/                   # Layer 1 PORTS: the 10 extension interfaces, no implementations
│   │   ├── model.py             #   ModelAdapter
│   │   ├── tool_source.py       #   ToolSource
│   │   ├── policy.py            #   Policy
│   │   ├── credentials.py       #   CredentialProvider
│   │   ├── context.py           #   ContextStrategy, Retriever
│   │   ├── memory.py            #   MemoryStore
│   │   ├── event_store.py       #   EventStore
│   │   ├── redactor.py          #   Redactor
│   │   └── hooks.py             #   Hooks
│   │
│   ├── tools/                   # Layer 2 CORE ENGINES (the logic; uses only layers 0 and 1)
│   │   ├── registry.py          #   which tools exist for this agent
│   │   ├── harness.py           #   validate → policy → approval → credentials → execute → result
│   │   └── schema_check.py      #   basic argument check for sources that cannot validate
│   ├── context/
│   │   └── manager.py           #   builds what the model sees each turn
│   ├── ledger/
│   │   ├── ledger.py            #   append events (redacted first), read events
│   │   ├── projections.py       #   events → message history, run state
│   │   └── recovery.py          #   on resume: find unfinished work
│   ├── runtime/                 # Layer 3 ORCHESTRATION (with session/)
│   │   ├── agent.py             #   Agent definition (prompt, tools, model, output type) + fingerprint
│   │   ├── loop.py              #   one run: model → tools → model … with budgets
│   │   ├── interrupts.py        #   pause for approval, resume
│   │   └── hooks.py             #   calls registered hooks at each step
│   ├── session/
│   │   └── session.py           #   run keys, session budget, shared principal
│   │
│   ├── testing/                 #   no_governance() and other test helpers (REQUIREMENTS D7)
│   │
│   └── adapters/                # ADAPTERS: implementations of the ports
│       ├── models/              #   fake.py · anthropic.py · openai_compat.py
│       ├── event_stores/        #   sqlite.py (default) · in_memory.py
│       ├── memory_stores/       #   in_memory.py (reference only)
│       ├── tool_sources/        #   python.py (@tool decorator + source) · mcp.py
│       ├── policies/            #   default.py (reads allowed, side effects need approval) · rules.py
│       ├── credentials/         #   env.py
│       ├── redactors/           #   passthrough.py · secrets.py
│       ├── context_strategies/  #   keep_all.py · truncate.py
│       └── knowledge/           #   optional extra agentreins[knowledge]:
│                                #     chroma_retriever.py · text_to_sql_tool.py
│
├── tests/
│   ├── unit/                    # mirrors src/: one folder per module
│   ├── contract/                # one test suite per port, run against every adapter of it
│   │                            #   (third-party plug-in authors reuse these too)
│   ├── recorded/                # saved real provider responses, replayed offline
│   ├── failure/                 # crash injection: kill mid-tool / mid-model-call, then resume
│   └── live/                    # real API calls: opt-in, never in normal CI
│
├── examples/
│   ├── 01_hello_tool.py         # small, numbered, each runs offline with the fake model
│   ├── 02_approval.py
│   ├── …
│   └── supply_chain/            # reference app: simulated ERP, approval, crash recovery
│
├── docs/
│   ├── REQUIREMENTS.md          # step 1
│   ├── adr/                     # one file per design decision
│   └── dev/                     # learning protocol, devlog
│
├── .github/                     # CI, release, issue/PR templates
├── pyproject.toml · README.md · ARCHITECTURE.md · ROADMAP.md
└── CHANGELOG.md · CONTRIBUTING.md · SECURITY.md · LICENSE · CLAUDE.md
```

## Open items

- ADR-0001 (content and event model): three open questions to settle at the start of M1, before the `types` module is built.
- Port merging was considered in step 3: none merged (redactor stays separate from hooks, ADR-0006).
