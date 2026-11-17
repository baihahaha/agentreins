# ADR-0004: Policy port

- **Status:** accepted (architecture step 3). Provisional until the default and rules policies exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) G1–G3, D4, guarantee #2

## Context

Policy decides whether a principal may call a tool with given arguments. agentreins is the enforcement point; the decision may come from simple rules in code or from an external engine (AWS Verified Permissions, OPA…).

## Decisions

### D1. Methods

```python
class Policy(Protocol):
    async def decide(self, request: PolicyRequest) -> Allow | Deny | RequireApproval: ...
    async def visible_tools(self, principal: Principal, tools: list[ToolSpec]) -> list[ToolSpec]: ...  # optional
```

- `decide()` is called for **every** tool call. `PolicyRequest` holds the principal, the tool spec (including effect class), the **validated** arguments, the run and session IDs, and the budget used so far.
- `visible_tools()` is optional. It hides tools the principal can never use, so the model doesn't waste steps on them. It is a convenience, not a security boundary: `decide()` is still always called.
- Policy never modifies arguments (REQUIREMENTS D4).

Alternatives rejected: yes/no only (no approval path); name-only rules (can't express "over $10k"). A post-execution result check is a known gap, deferred; the redactor covers what is stored.

### D2. Order in the harness

Validate arguments → `decide()` → (approval if required) → execute. Policy always sees clean, typed values. No tool skips policy, read-only included, because reading can expose data too.

### D3. Policy failure is configurable; default Deny

If `decide()` raises or times out, the default answer is `Deny("policy unavailable")`: the model is told, the event is logged, the run continues (bounded by budgets). Configurable alternative: fail the whole run. Never fail open.

### D4. Default policy

When nothing is configured:

| Effect class | Default |
|---|---|
| `read_only`, `idempotent` | Allow |
| `side_effecting` | RequireApproval |

Users can allow specific side-effecting tools without approval (e.g. `allow=["create_po"]`). Errors explain this. Similar to Claude Code, where reads are allowed and edits ask.

## Comparison

To be completed when built: Claude Agent SDK (allowed/disallowed tools + permission callback), OpenAI Agents SDK guardrails, Cedar/OPA (allow/deny only).
