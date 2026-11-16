# Learning Protocol (maintainer-facing)

agentreins is a real open-source project *and* the maintainer's path to mastering agent internals. This file says how both goals coexist. It is not user documentation.

## Method: Understand → Build → Break → Compare

1. **Understand.** Before coding a mechanism, write down (in an ADR or the devlog) what problem it solves, its inputs/outputs, and its trust boundary.
2. **Build.** The maintainer hand-writes the mechanism.
3. **Break.** Add tests that attack it: malformed arguments, duplicate calls, timeouts, crashes mid-step, permission denial.
4. **Compare.** After it works, read how one mature framework (LangGraph, OpenAI Agents SDK, Claude Agent SDK) solves the same problem. Note differences in the ADR.

## Who writes what

| Area | Maintainer | Coding agent (Claude Code) |
|---|---|---|
| Kernel: content/event model, agent loop, tool harness, event store, resume/reconciliation, interrupts | **Writes it.** | Reviews, challenges design, proposes edge-case tests. Gives hints, not solutions. |
| ADRs | Decides and owns | Drafts options and trade-offs for review |
| Tests | Writes kernel tests; approves all tests | Scaffolds repetitive tests, fixtures, failure injection harness |
| Provider adapters | Designs the interface; writes the first adapter | May write the second adapter following the first |
| CI, packaging, docs site, templates, examples, glue | Reviews | Writes |
| Debugging | Diagnoses first | Assists after a first hypothesis |

The rule of thumb: **if a mechanism appears in ARCHITECTURE.md's "Core decisions", the maintainer writes it.**

## Definition of done for a kernel mechanism

- [ ] Can explain it without notes (lifecycle, failure modes, trust boundary)
- [ ] Hand-written implementation merged, with tests that try to break it
- [ ] ADR updated with the decision and one comparison to an existing framework
- [ ] CHANGELOG entry

## Pitfalls to avoid

- Letting a coding agent generate the kernel "to save time". That defeats both goals.
- Treating text that *describes* an action as an executed action.
- Trusting a model's self-reported completion or confidence.
- Treating prompt instructions as security or permissions.
- Real side effects (payments, bookings, production writes) in examples. Always use simulated backends.
