# agentreins

**Drive your agents. Keep them on a leash.**

`agentreins` is a small, provider-neutral agent runtime for Python. It runs the model ↔ tool loop and makes it **durable**: every step is recorded in an append-only event log, so a run can be paused for human approval, survive a process crash, and resume without repeating side effects.

> **Status: pre-alpha.** The API is not stable yet. Target: v0.5 (core API frozen) in January 2027. See [ROADMAP.md](ROADMAP.md).

## Why another agent framework?

Most frameworks make the *happy path* easy. agentreins focuses on what happens when things go wrong:

- **Crash-safe by design.** The event log is the source of truth. Message history and checkpoints are derived from it.
- **Side effects are explicit.** Every tool declares whether it is `read_only`, `idempotent` or `side_effecting`. Side-effecting calls record their intent and an idempotency key *before* they execute, so recovery never blindly re-runs them.
- **Humans in the loop.** Approval is a first-class interrupt. A run suspends, persists, and resumes later, possibly in another process.
- **Trust boundaries are enforced in code.** The model *requests* tool calls; the runtime validates, authorizes and executes them. Prompts are not permissions.
- **Bounded.** Budgets on steps, tokens, cost and wall time; per-tool timeouts; structured cancellation.
- **Small and owned.** The only core dependency is `pydantic`. Provider adapters speak HTTP directly (via `httpx`); no vendor SDKs.

## Quickstart

```bash
pip install "agentreins[providers]"   # not yet published; [providers] adds httpx for OpenAI-compatible APIs
```

```python
from agentreins import Agent, tool


@tool(effect="read_only")
def get_inventory(sku: str) -> int:
    """Return units on hand for a SKU."""
    return {"A-12": 40}.get(sku, 0)


agent = Agent("openai:gpt-4.1-mini", tools=[get_inventory])  # reads OPENAI_API_KEY
result = agent.run_sync("How many units of A-12 do we have?")
print(result.output)
```

Every step of the run is saved in `agentreins.db`. Tools that change things (`effect` not given, or `"side_effecting"`) need approval by default. Offline version with a scripted model: [examples/01_hello_tool.py](examples/01_hello_tool.py).

## Non-goals (for 1.0)

- Graph / workflow DSLs, planners, multi-agent orchestration frameworks (an agent can be used as a tool)
- Building memory or vector database engines: agentreins defines the `MemoryStore` and `Retriever` interfaces; storage is a plug-in. A Chroma retriever ships as the optional extra `agentreins[knowledge]`
- Hosting, UI, or a cloud platform
- Wrapping every model provider: we support OpenAI-compatible APIs (OpenAI, Kimi, vLLM, Ollama and others) first, then Anthropic

## Project docs

| Document | Purpose |
|---|---|
| [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) | What agentreins must do, decisions, guarantees |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Module map and project structure |
| [docs/adr/](docs/adr/) | Architecture Decision Records, one per decision |
| [ROADMAP.md](ROADMAP.md) | Release plan |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup and workflow |
| [SECURITY.md](SECURITY.md) | Reporting vulnerabilities, threat model |

## Development

```bash
uv sync --all-extras       # creates a local .venv
uv run pytest
uv run ruff check . && uv run pyright
```

## License

[Apache-2.0](LICENSE)
