# Security Policy

## Reporting a vulnerability

Please **do not open a public issue.** Report privately via [GitHub security advisories](https://github.com/baihahaha/agentreins/security/advisories/new). You will get an acknowledgement within 7 days.

## Supported versions

Pre-1.0: only the latest release receives fixes.

## Security model (summary)

agentreins treats **all model output as untrusted input**.

- A model's tool call is a *request*. The runtime only executes registered tools, after schema validation and policy checks.
- Prompts are not permissions. Authorization must be enforced in policy hooks or in the tools themselves.
- Tool results (including from MCP servers and web content) may contain prompt injection. agentreins does not claim to prevent injection; it limits blast radius through effect classes, policy hooks and human approval for side effects.
- Secrets: adapters read API keys from the environment; they are never written to the event log.

A full threat model will be published with v0.5.
