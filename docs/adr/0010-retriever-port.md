# ADR-0010: Retriever port

- **Status:** accepted (architecture step 3). Provisional until the Chroma retriever exercises it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) C3, D6, governance principle (three control points)

## Context

A retriever finds relevant documents by vector or keyword search (REQUIREMENTS D6). Structured-data queries (text-to-SQL) are tools, not retrievers.

## Decisions

### D1. Returns documents, not text

```python
class Retriever(Protocol):
    async def search(
        self, query: str, credentials: Credentials | None, top_k: int, filters: dict | None
    ) -> list[Document]: ...
```

`Document` has `id`, `content`, `score`, `source`, `metadata`, so the agent can cite where information came from. Rejected: plain text (loses sources).

### D2. Automatic or as a tool, chosen per agent

- **Automatic (default when a retriever is configured):** before each model call, the context manager searches with the latest user message and adds results to the context.
- **As a tool:** a helper wraps the same retriever as a `search_docs` tool, so the agent decides when and what to search. The call then goes through the tool harness like any tool.

### D3. No permission logic in the retriever

Following the governance principle, agentreins adds no document-permission logic. The retriever receives the principal's credentials from the **CredentialProvider**, and the search system filters results under its own permissions. Retrieved documents are recorded in the event log, because everything that goes into the model is recorded; this keeps resume and audit correct.

## Comparison

To be completed when built: LangChain retrievers, LlamaIndex retrievers, Google ADK memory/search tools.
