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
pip install agentreins            # not yet published
```

```python
# Illustrative. The API is being designed (see docs/adr/).
from agentreins import Agent, tool


@tool(effect="read_only")
def get_inventory(sku: str) -> int:
    """Return units on hand for a SKU."""
    ...


agent = Agent(model="anthropic:claude-sonnet-5-5", tools=[get_inventory])
result = await agent.run("How many units of A-12 do we have?")
```

## Non-goals (for 1.0)

- Graph / workflow DSLs, planners, multi-agent orchestration frameworks (an agent can be used as a tool)
- Long-term memory / vector stores
- Hosting, UI, or a cloud platform
- Wrapping every model provider: we support Anthropic and OpenAI-compatible APIs, which covers OpenAI, Kimi, vLLM, Ollama and others

## Project docs

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Components, trust boundaries, core decisions |
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
