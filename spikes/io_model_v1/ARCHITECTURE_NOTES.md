# Architecture notes — clarifications from spike review

Captures conclusions reached during the spike build (operator + claude) that resolve specific architectural questions io-model.md leaves implicit. Each conclusion has a "**Q**" framing the question and a "**Resolved**" framing the answer.

## A1 — MCP vs Lux IPC

**Q.** Are MCP and Lux IPC parallel wire protocols an agent might use?

**Resolved.** No. **Lux IPC is the Hub's canonical wire API.** MCP is an agent-facing protocol veneer in front of it — there can be many MCP gateways, each translating an agent's MCP tool calls into Hub Lux IPC calls.

Two flavors:

- **Inline gateway** (the existing `src/punt_lux/tools/server.py`): one process exposing Hub primitives 1:1 as MCP tools (`show`, `show_table`, `show_dashboard`, `recv`, etc.) with mild ergonomic wrappers.
- **Standalone-app gateway** (e.g. a future Beads MCP server): a separate process with its own domain MCP tools (`beads_search`, `beads_show_dashboard`) that internally construct a `DisplayClient` and call `client.show(...)` against the Hub.

The Hub itself is agnostic to which path was taken; it sees the same Lux IPC requests over its socket regardless of origin.

## A2 — Typed Updates / Events vs Observer notifications

**Q.** Should everything that crosses a process boundary go through pub/sub (subscribe/publish/notify), or is there a meaningful distinction?

**Resolved.** There is a meaningful distinction. Two channels coexist:

- **Typed Updates and Events** form the canonical contract on the Hub↔Display and Hub↔client boundaries. They are well-defined wire kinds: `AddElement`, `RemoveElement`, `SetProperty`, `ButtonClicked`, `InteractionMessage`. Each is schema-tracked, boundary-validated, and part of the architectural contract. **All state changes live here.**
- **Observer notifications** (the `subscribe` / `publish` / `notify` path producing `observed` envelopes) are a lighter mechanism — closer to *callbacks the agent or app explicitly opted into when it generated the scene/code*. They are not the canonical state-change channel; they are a way to react to things the canonical channel did.

**Rules of thumb:**

- A dialog dismissing itself uses a typed `RemoveElement` Update (state change → canonical channel).
- An agent learning that a click happened uses an `observed` envelope on a topic it subscribed to (callback → observer channel).
- An app updating an issue should update the issue's visible state through a `show()` (typed channel); the Hub's reactive machinery fans out an `observed` notification to any topic subscribers as a side effect.

**Do not conflate.** Don't push state changes through pub/sub, and don't reach for typed wire kinds to deliver every notification.

## A3 — PublishMessage wire kind

**Q.** Does an in-fabric publisher (e.g. an app process that wants to publish a topic) need a dedicated `PublishMessage` wire kind?

**Resolved.** Not at current scope. Generalized peer-to-peer pub/sub from external publishers to the Hub is a future capability that has not been thought through yet. For now the principle is: external apps express intent by sending **typed Updates** (e.g. `show()`), and the Hub's reactive machinery generates `observed` notifications for subscribers as a consequence of accepting those Updates. The `publish()` call inside the Hub produces `observed` envelopes on subscriber sockets — that wire output is the notification channel.

If generalized pub/sub is later needed, it would be additive — a new wire kind that triggers the Hub's `publish()` from outside — but it should not replace or compete with the typed Update channel.

## A4 — Hub-side `publish()` produces wire output

**Q.** Does the Hub's internal `publish()` call cross a process boundary?

**Resolved.** The Python call itself is in-process (one Python function calling another), but **its purpose is to produce wire output** — `{"kind": "observed", "topic": ..., "payload": ...}` envelopes written to every subscriber socket. So while the API invocation is in-process, the wire format of `observed` envelopes is part of the contract and lives on subscriber-facing sockets.
