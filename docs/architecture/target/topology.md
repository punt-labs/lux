# Lux Target Topology

**Status:** target process and deployment model for the rewrite.

Start with [target.md](./target.md). This document goes deeper on process
roles, connectivity, and replication.

## What This Document Covers

This document answers:

- what the major runtime roles are
- how clients, Hub, and Display talk to each other
- what gets replicated
- what may run on one machine versus different machines

It does not define the UI class hierarchy. That lives in
[ui-model.md](./ui-model.md).

## Topology

```text
clients
  - MCP agents
  - direct apps via client API
  - future front doors
          |
          v
Hub
  - authoritative UI store
  - aggregation point
  - handler execution
  - app-level pub-sub
          |
          | full UI replicas
          v
Display
  - rendering replica
  - input capture
  - remote dispatch back to the Hub
```

## Clients

The architecture allows multiple front doors into the Hub.

- MCP is one front door.
- A direct application API is another.
- The important thing is the Hub-facing model, not the transport a client used
  to reach it.

Clients do not talk to the Display directly in the canonical model. They talk
to the Hub.

## Agent Or App To Hub

The client-facing leg carries application intent, not rendering commands.

Typical operations on this leg include:

- submit or replace UI
- publish or subscribe to app-level topics
- inspect the live system
- invoke control operations

MCP is one gateway on this leg. A direct client API is another. The Hub-facing
model matters more than which gateway was used.

## Hub

The Hub is the authoritative runtime.

At minimum it aggregates many app/agent UIs for one user. At maximum it can
aggregate many app/agent UIs for many users.

The Hub owns:

- authoritative UI state
- UI ownership
- handler execution
- application-level publish/subscribe
- scene/app aggregation
- the connection to one or more Displays

The Hub may host UIs from:

- long-lived headless applications
- ad hoc agent output
- mixed environments where many independent clients contribute UI

## Display

The Display is a rendering replica.

It holds a full copy of the UI it is rendering. It does not own the real
behavior of that UI. Its job is to:

- render the current copy
- wrap handlers for remote dispatch
- forward interactions to the owning Hub

The Display only needs enough routing information to send interaction messages
back to the Hub that owns the replicated UI.

## Hub To Display

The Hub-to-Display leg carries replicated UI state and inbound user
interactions.

Hub to Display:

- full scene trees
- full-tree replacements
- other replicated UI payloads that preserve Lux element semantics

Display to Hub:

- remote interaction invocations
- user-originated events that the Hub must interpret against authoritative UI

Render calls do **not** cross this boundary. The Hub does not stream ImGui
operations or pixel commands to the Display. Instead, it sends UI state or
serialized Lux element objects; the Display turns that replicated state into
local render calls.

## Replication Model

The Hub sends full UI state to the Display.

The default rule is intentionally simple:

- when a rendered UI changes, the Hub may resend the whole UI for that
  app/scene/display
- the Display replaces its old copy
- the Display renders the new copy on the next frame

There is no requirement for a retained diff protocol between Hub and Display.
That can be added later only if needed.

## Interaction Flow

### Outbound

1. A client submits UI to the Hub.
2. The Hub installs that UI into `HubDisplay`.
3. The Hub sends a full replica to the Display.
4. The Display stores that replica and wraps handlers for remote dispatch.

### Inbound

1. The user interacts with the Display copy.
2. The wrapped handler emits a remote invocation back to the owning Hub.
3. The Hub resolves the authoritative element.
4. The Hub runs the real handler.
5. If the UI changed, the Hub re-sends the full updated UI.

## Current Demonstrated Slice

The current code demonstrates only a narrow slice of this topology cleanly:

- client-side UI submission into Hub-side indexing
- Hub-side `HubDisplay` authority for the indexed slice
- Display-side handler wrapping on the ABC button/dialog path
- remote invocation back to the Hub
- Hub-side handler execution and full-scene re-push

That slice is enough to demonstrate the intended communication shape, but not
enough to treat the entire codebase as already migrated.

## Deployment

The Hub and Display may run on the same machine or on different machines.

Typical cases:

- local Hub + local Display
- remote agents or apps connecting to a local Hub
- remote Hub with a local Display

The architecture should not depend on co-location.

## Design Constraints

- The Hub is authoritative.
- Clients target the Hub, not the Display.
- The Display is a full replica, not an incremental state owner.
- Full-tree resend is acceptable until proven otherwise.
- A single Hub may aggregate many independent clients.
