# ADR-0006: Redactor port

- **Status:** accepted (architecture step 3). Provisional until the pass-through and secret-pattern redactors exercise it; frozen at v0.5.
- **Date:** 2026-11-17
- **Related:** [REQUIREMENTS.md](../REQUIREMENTS.md) G6, guarantees #1, #2, #4

## Context

Secrets and personal data must not be stored in the event log. The model's context is built from the log, so redaction also decides what the model sees.

```text
tool result ──> REDACTOR ──> event log ──> context ──> model
```

## Decisions

### D1. A separate port, not a hook

```python
class Redactor(Protocol):
    async def redact(self, event: Event) -> Event: ...
```

Applied by the ledger before every append. It may change event content only; IDs, sequence number and type must stay unchanged (checked by contract tests, and also by the ledger at runtime: a violation raises `RedactionError` and nothing is stored). `Ledger.append` returns the events as stored, and the runtime must use those from then on. Not merged into hooks: hooks observe and may fail without stopping the run, whereas the redactor changes data and must never be skipped.

### D2. The model sees what was stored

Redaction happens once, when the event enters the log; the context is built from the log. The model therefore sees identical data live and after a resume (guarantees #1, #4).

Consequence: whatever is redacted, the model cannot use. Right for secrets. For personal data it is a per-deployment choice; data the agent needs should flow through tool data rather than the conversation.

Not affected by redaction: tool arguments and credentials given to tools, what tools send to real systems, and what policy sees (policy gets arguments before redaction).

Rejected: model sees originals while only storage is redacted (behaviour differs after resume); storing an encrypted original alongside (complex, new secret to protect).

### D3. Redactor failure fails the run

If `redact` raises, the event is not stored and the run fails; it can be resumed once the redactor is fixed. Rejected: storing unredacted (leak), skipping the event (gap in the log).

## Comparison

To be completed when built: Microsoft Presidio, OpenTelemetry attribute redaction, LangSmith data masking.
