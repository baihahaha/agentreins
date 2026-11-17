# Learning Protocol (maintainer-facing)

agentreins is a real open-source project *and* the maintainer's path to mastering agent internals. This file says how both goals coexist. It is not user documentation.

## Method: Understand → Build → Break → Compare

1. **Understand.** Before coding a mechanism, write down (in an ADR or the devlog) what problem it solves, its inputs/outputs, and its trust boundary.
2. **Build.** The coding agent implements the approved plan; the maintainer reviews every line.
3. **Break.** Add tests that attack it: malformed arguments, duplicate calls, timeouts, crashes mid-step, permission denial.
4. **Compare.** After it works, read how one mature framework (LangGraph, OpenAI Agents SDK, Claude Agent SDK) solves the same problem. Note differences in the ADR.

## Who writes what

Decided 2026-11-17: **the coding agent (Claude Code) writes the code; the maintainer designs, reviews and approves.**

| Area | Maintainer | Coding agent |
|---|---|---|
| Requirements, architecture, ADR decisions | Decides | Proposes options with trade-offs and comparisons |
| Module plan | Reviews and approves before any code | Writes a short plan per module |
| All code, including the kernel | Reviews; asks questions until able to explain it | Writes, with tests and review notes explaining the why |
| Debugging | Asks for an explanation of the root cause | Diagnoses and fixes |

Learning comes from designing, reviewing and questioning, and from the Break step: the maintainer proposes ways to break each module.

## Definition of done for a kernel mechanism

- [ ] Can explain it without notes (lifecycle, failure modes, trust boundary)
- [ ] Implementation reviewed and merged, with tests that try to break it
- [ ] ADR updated with the decision and one comparison to an existing framework
- [ ] CHANGELOG entry

## Pitfalls to avoid

- Approving code you cannot explain. Ask until you can.
- Treating text that *describes* an action as an executed action.
- Trusting a model's self-reported completion or confidence.
- Treating prompt instructions as security or permissions.
- Real side effects (payments, bookings, production writes) in examples. Always use simulated backends.
