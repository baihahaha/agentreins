# ADR-0008: CredentialProvider port

- **Status:** accepted (architecture step 3). Provisional until the environment-variable provider and a platform plug-in exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) G1 (outbound identity), G6, guarantee #2

## Context

Tools need credentials to call enterprise systems, and they should act with the permissions of the run's principal, never with more.

## Decisions

### D1. Tools declare needs; the provider supplies per principal

```python
class CredentialProvider(Protocol):
    async def get(self, principal: Principal, name: str) -> Credentials: ...
```

A tool declares what it needs (e.g. `requires="erp"`). The harness calls `get(principal, "erp")` and hands the result to the tool via `ToolContext`. Rejected: one shared credential for all tools (agent more powerful than any user); tools fetching their own (no central control or visibility).

### D2. Credentials cannot leak by accident

`Credentials` is a dedicated type that refuses to be printed, serialized or stored. The core rule "no credentials in events" is enforced by the type, not by convention.

### D3. Fetched per call; the provider handles caching and expiry

The provider is called on every tool call and owns caching and refresh. The core never holds credentials beyond a single call, since platform credentials (AWS STS, OAuth tokens) expire within minutes to hours.

### Default provider

Reads environment variables: need `erp` → `AGENTREINS_CRED_ERP` (prefix configurable; non-alphanumerics become `_`). Every principal gets the **same** key: suitable for development only. If a credential cannot be fetched, the call is rejected with reason `credentials_unavailable` and the tool never runs (decided 2026-11-20); the provider's error message is not shown to the model, in case it contains a secret. Documentation states that production needs a per-principal provider (e.g. AWS STS role assumption, OAuth token exchange).

## Comparison

To be completed when built: AWS Bedrock AgentCore Identity (outbound auth), OAuth 2.0 token exchange (RFC 8693).
