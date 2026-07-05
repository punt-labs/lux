# Lux Target Architecture

**Status:** canonical target for the rewrite.

This document describes the architecture Lux is moving toward. It is not a
claim that the current code already cleanly implements this model. For the
current architecture — what the shipped code does today, honestly framed as a
system mid-migration toward this target — see [system.tex](../system.tex).

If you read only one target-architecture document, read this one.

## Problem

Lux exists so many agents and apps can share one visual surface.

- Minimum scope: one user with many agent/app UIs aggregated by one Hub.
- Maximum scope: many users with many agent/app UIs aggregated by one Hub.

Lux also exists so agents can verify what actually happened by inspecting the
live system rather than asking the user to report what they saw.

## Core Model

Lux is a Hub/Display system with one authority.

1. Clients submit UI to the Hub.
2. The Hub decodes or constructs typed UI objects. Every element self-validates
   first; a tree with any invalid element is rejected back to the client and is
   never installed or rendered (see
   [element-contract.md](./element-contract.md)). Valid UI objects are
   installed in `HubDisplay`.
3. `HubDisplay` is the authoritative store for UI state, ownership, and
   handler dispatch.
4. The Display receives a full replica of the UI and uses it only for
   rendering and input capture.
5. When the user interacts with the Display, the interaction is routed back to
   the owning Hub and the real handler runs there.
6. After a change, the Hub re-sends the whole affected UI to the Display.
   Lux does not need a diff protocol until a real performance problem appears.

The Hub wins every disagreement. The Display is a replica, not a second
authority.

## Front Doors

MCP is one entry point into the Hub, not the architecture itself.

Lux should support multiple front doors:

- MCP agents calling tools such as `show()` and `show_table()`
- direct applications using a client API
- future transports that speak the same Hub-facing model

A headless Python app can keep its authoritative UI in the Hub. An agent can
also create ad hoc UI directly through the Hub. Both fit the same model.

The MCP surface stays small on purpose. `show()` is the one universal render
API — it takes an arbitrary element tree — and widget conveniences
(`show_table`, dashboards, ask-user flows) are composed from it as skills
rather than added as standing tools, so the tool contract every agent carries
does not grow per widget. The elements are limited; the ways they combine are
unlimited. See [DES-040](../../../DESIGN.md).

## Communication Model

Lux has two primary communication legs:

- **Agent/App ↔ Hub:** clients submit UI, call client-API or MCP operations,
  use app-level pub-sub, and use introspection/control surfaces.
- **Hub ↔ Display:** the Hub sends replicated UI state to the Display, and the
  Display sends user interactions back to the Hub.

The important boundary rule is:

- **UI state crosses IPC.**
- **Render calls do not.**

That means scene trees, updates, serialized Lux element objects, and remote
interaction messages may cross the boundary. ImGui calls, renderer invocations,
and pixel operations do not. The Display receives replicated UI state and then
renders locally.

## Roles

```text
Agent or app
  - MCP client
  - client API user
  - future front door
          |
          v
Hub
  - owns HubDisplay
  - aggregates many app/agent UIs
  - executes real handlers
  - runs lightweight built-in UI behavior
  - publishes app-level events
  - exposes introspection APIs
          |
          | full UI replica
          v
Display
  - stores a full copy of the UI
  - renders that copy
  - wraps handlers for remote dispatch
  - forwards interactions to the owning Hub
```

## The Hub

The Hub is authoritative.

It hosts UIs, but it does not automatically imply built-in apps or built-in
screens. Apps and agents supply UI. The Hub stores, executes, and coordinates
that UI in a lightweight way.

That lightweight behavior includes things like:

- handler execution
- ownership checks
- observer-driven UI updates inside the composite hierarchy
- simple built-in UI behavior where it belongs in the UI model

## The Display

The Display keeps a full copy of the UI tree for whatever it is rendering.

Handlers on the Display copy are wrapped so they do not execute real behavior
locally. When invoked, they call back to the Hub that sent the UI. The Display
only needs to know which Hub owns that UI and how to communicate with it over
an already-established connection.

## Event Models

Lux has two different event mechanisms and they must not be conflated.

- **UI event/observer mechanics:** local to the UI object hierarchy. These are
  things like handler invocation and observer cascades inside the composite
  tree.
- **Application pub-sub:** Hub-managed publish/subscribe for application-level
  events and topics. This is separate from the UI observer mechanism.

Application pub-sub is what enables business logic at the app level. A Hub-side
event handler may both perform local UI behavior and publish an application
event such as `openTicket`, `closeTicket`, or `markTicketInProgress`. That same
pub-sub channel may also be used by non-UI sources such as timers or other app
logic. The published topics are defined by the app or agent, not by Lux.
Pub-sub is not the canonical UI-state replication path; it is the business
event channel that reacts to state changes or other app activity.

## Replication Policy

The default replication rule is simple:

- if one relevant piece of UI state changes for a rendered UI, the Hub may
  resend the whole UI for that app/scene/display
- the Display replaces its previous copy with the new one
- ImGui re-renders the current copy every frame

This is simpler, easier to inspect, and easier to reason about than a
distributed incremental diff protocol.

## Current Demonstrated Slice

Only a small slice of this target is demonstrated cleanly in the code today.

The real sliver is:

- Hub-side `HubDisplay` authority
- connection-scoped Hub pub-sub
- ABC-backed Lux elements on the button/dialog path
- Display-side handler wrapping for remote dispatch
- Hub-side re-dispatch of the real handler after a display click

That sliver is enough to validate the architectural direction. It is not yet
evidence that the entire current codebase cleanly implements the full target.

## Verification

The architecture includes introspection so agents can verify real outcomes.

An agent should be able to:

- verify its own UI *before* render — self-validation returns any malformed
  element to the agent instead of rendering it (see
  [introspection-api.md](./introspection-api.md))
- render UI through its real entry point
- trigger real interactions
- inspect live Hub/Display state
- compare the observed result with expected behavior

## Related Target Docs

- [README.md](./README.md)
- [topology.md](./topology.md)
- [ui-model.md](./ui-model.md)
- [element-contract.md](./element-contract.md)
- [introspection-api.md](./introspection-api.md)
