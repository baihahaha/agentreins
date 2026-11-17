# ADR-0011: MemoryStore port

- **Status:** accepted (architecture step 3). Provisional until the in-memory reference store and a plug-in exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) C4, D2, governance principle (three control points)

## Context

Long-term memory keeps facts across runs. Storage and search are plug-ins (REQUIREMENTS D2); the core ships only an in-memory reference store.

## Decisions

### D1. Methods

```python
class MemoryStore(Protocol):
    async def save(self, namespace: str, item: MemoryItem, credentials: Credentials | None) -> str: ...
    async def search(self, namespace: str, query: str, top_k: int, credentials: Credentials | None) -> list[MemoryItem]: ...
    async def delete(self, namespace: str, item_id: str, credentials: Credentials | None) -> None: ...
    async def delete_all(self, namespace: str, credentials: Credentials | None) -> None: ...
```

`MemoryItem` has `id`, `content`, `metadata`, `created_at`. `delete_all` supports "forget this user" requests (e.g. GDPR).

### D2. Who decides when to save and recall

| Mode | Provided by |
|---|---|
| Agent saves and recalls via `remember` / `recall` tools | **Built in.** Tool calls go through the harness like any tool |
| Automatic recall before each model call | **Built in**, via the context manager (same as the retriever) |
| Automatic saving after a run (model-extracted facts) | **Plug-ins** (e.g. a mem0 plug-in) |

Memories that enter the model are recorded in the event log (everything that goes into the model is recorded), after redaction.

### D3. Namespaces, not permissions

Following the governance principle, agentreins adds no permission logic. The core passes a namespace derived from the principal (e.g. tenant + user) and the principal's credentials; the store keeps namespaces separate. This is partitioning, not a permission decision.

## Comparison

To be completed when built: LangGraph Store namespaces, Letta memory tiers, Anthropic memory tool, mem0, Google ADK MemoryService.
