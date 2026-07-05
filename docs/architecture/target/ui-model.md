# Lux Target UI Model

**Status:** target UI object model for the rewrite.

Start with [target.md](./target.md). This document covers the UI class
hierarchy and its semantics, not process topology.

For the normative "what an Element must and must not support" contract, use
[element-contract.md](./element-contract.md).

## What This Document Covers

This document answers:

- what the Hub stores
- what the UI objects are
- where handlers run
- how observer-driven UI behavior works
- how application pub-sub differs from UI event mechanics

## Core Objects

### HubDisplay

`HubDisplay` is the Hub-side authoritative UI store.

It is responsible for at least:

- indexing authoritative UI objects
- tracking ownership
- resolving elements for interaction dispatch
- supporting removal and replacement of UI trees

Every authoritative interaction resolves against `HubDisplay`.

### Scene Or App UI

A Hub may host many independent UIs at once. Each one is a root tree installed
into `HubDisplay`.

In current terminology these are often called scenes. In practice they are the
authoritative UI for one app, one tool invocation, or one agent-produced
surface.

### Element

An `Element` is a typed UI object.

Examples include:

- text
- buttons
- dialogs
- tables
- other domain-specific widgets

Elements may carry state and behavior. They are not just wire structs.

### Composite

A `Composite` is an `Element` with children.

This is the load-bearing UI pattern in Lux. Composite elements manage child
relationships, and observer-driven behavior can propagate through this
hierarchy.

## Handler Model

Handlers are attached to authoritative Hub-side UI objects.

Examples:

- call model logic
- confirm or dismiss a dialog
- trigger lightweight built-in behavior
- publish an application-level topic

The Display copy never runs the real handler body locally. Display-side
handlers are wrappers that turn local interaction into a remote invocation back
to the Hub.

Hub and Display may therefore hold tier-local copies of the same conceptual UI
object tree. What differs is execution role:

- the Hub-side copy is authoritative and runs the real handler
- the Display-side copy is a rendering replica with wrapped handlers

## Observer Model

The UI hierarchy may use an observer pattern internally.

That observer mechanism is for UI-object behavior such as:

- responding to a child state change
- cascading removal
- coordinating updates inside a composite tree

This is part of the UI model itself.

## Application Pub-Sub

Application-level publish/subscribe is a separate mechanism owned by the Hub.

It is for app-specific or domain-specific events such as:

- `"dialog.confirmed"`
- `"item.selected"`
- other app topics

This pub-sub layer is not the same as the UI observer mechanism. They solve
different problems and should stay separate in the docs and in the code.

It is also the main business-logic channel for apps. For example, an app may
show a table, let the user select a row, and then expose an `Open` button. When
that Hub-side handler fires, it may both update local UI state and publish an
application event such as `openTicket`. Likewise, a timer or other non-UI app
logic may publish `closeTicket`, `markTicketInProgress`, or other app-defined
topics. Lux provides the Hub-managed pub-sub mechanism; the meaning of those
topics belongs to the app or agent.

Pub-sub is not the canonical state-replication channel. State changes still
flow through the Hub's authoritative UI model and the Display's replicated
copy; pub-sub exists so apps and agents can react to those state changes or to
other non-UI triggers.

## Where Behavior Lives

Lux allows a spectrum:

- a headless Python app can keep its authoritative UI and behavior in the Hub
- an agent can create ad hoc UI directly in the Hub
- some lightweight behavior can live in reusable UI classes
- some app-specific behavior can live in app code attached to those UI objects

The Hub hosts and executes these UIs. It does not imply a built-in catalog of
resident applications.

Apps and agents compose standard Lux element kinds. They may attach their own
topics, data, and business behavior, but they do not ship custom element
classes across the Hub/Display boundary. The Hub and Display each hold
tier-local copies of the same standard element vocabulary; what differs by tier
is authority and execution role, not the element catalog.

## Component Example

The button/dialog path is the clearest current example of the intended model.

- `DialogElement` owns a private dialog model.
- Child `ButtonElement`s act as the dialog's controllers.
- A Hub-side button handler may invoke dialog model behavior and publish an
  app-level topic.
- The Display-side copy of that same button only forwards the interaction back
  to the Hub.

This is the kind of object-level behavior Lux is aiming for: reusable standard
components with authoritative Hub-side behavior, not passive wire structs.

## View Logic Versus Business Logic

An interaction has two halves, and Lux must not conflate them.

- **View logic** is built into the widget and may be automatic. A dialog's
  dismiss-on-confirm, its confirmed/cancelled state, a checkbox flipping its
  own boolean — these the element owns. Lux can wire the view half itself, for
  example mapping a dialog's `OK` button to the `confirm` action.
- **Business logic** is what the interaction *means* to the app — delete a
  ticket, save a form, ship an order. Only the agent or app knows it, so it is
  wired out of band: a Hub-side handler, or the element publishes an app-level
  topic that the agent receives.

The two cannot merge because of the agent's position. In an immediate-mode UI
the application is in the render loop, so a click and its consequence sit in
the same line of code. Lux's agent is not in the loop — it sends a JSON tree
and is gone — so the consequence is necessarily wired separately from the view
behavior. Auto-mapping covers only the view half.

A consequence for the contract: an interactive element with no business wiring
(a dialog button with no `click` verb; a handler-less button) is inert. That
inertness must not be silent — it is surfaced the same way malformed data is,
as a validation error, rather than accepted with an `ack` the agent cannot
distinguish from correct wiring. See [DES-040](../../../DESIGN.md).

## Filtering And Lightweight Built-In Behavior

Some UI behaviors may be lightweight enough to belong in the UI model rather
than in a separate application service.

Examples may include:

- filtering
- selection handling
- local view-model transformations

The architectural rule is still the same: if the behavior is authoritative, it
belongs on the Hub side.

## Replication Semantics

The Display holds a full copy of the authoritative UI tree.

That copy exists for:

- rendering
- input capture
- remote handler dispatch

When the authoritative UI changes, the Hub may resend the whole tree and the
Display replaces its copy.

## Self-Validation

Before the Hub installs a decoded UI tree, every element in it self-validates.
Malformed UI is caught here — on the Hub, between decode and render, never on
the Display.

- Each element implements `validate()` returning its own
  component-appropriate errors (a table checks rows against columns; a tree
  checks its node structure). The default is "no errors".
- A walk recurses the whole tree and collects *every* error — it does not stop
  at the first. Every composite exposes its children to the walk, so an error
  nested any depth down is still collected.
- If the collected set is non-empty, the tree is **not** installed into
  `HubDisplay` and is never sent to the Display; the errors are returned to the
  producing agent, each naming the offending element.

This keeps malformed UI on the producer's side of the Hub/Display boundary: an
invalid tree never becomes authoritative and never reaches the renderer, where
it would draw garbage or fault far from its cause. The normative contract is in
[element-contract.md](./element-contract.md); the decision and its rejected
alternatives are [DES-039](../../../DESIGN.md).

## Invariants

- `HubDisplay` is authoritative.
- Display copies are never authoritative.
- Real handlers run on Hub-side objects.
- Display-side handlers are wrappers for remote dispatch.
- UI observer mechanics are distinct from application pub-sub.
- The same UI model should work for long-lived apps and ad hoc agent UIs.
- Every element self-validates before its tree becomes authoritative; an
  invalid tree is never installed into `HubDisplay` and never rendered.
- View logic (built-in, may be automatic) is distinct from business logic
  (agent-wired); a missing business handler surfaces as a validation error,
  not a silent no-op.
