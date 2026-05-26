# Lux Target Element Contract

**Status:** draft normative target for Lux elements. Review expected.

Start with [target.md](./target.md) and [ui-model.md](./ui-model.md). Those
documents explain the overall Hub/Display architecture and UI object model.
This document narrows the scope to one question:

- what an Element must support
- what an Element may support
- what an Element must not support

This is a target-architecture document. It does not claim every current
implementation already satisfies the contract cleanly.

## Scope

This document is a semantic contract, not a field-by-field wire schema.

- Per-kind field shapes live with the protocol element definitions and codecs.
- This document defines the intended behavior and boundaries of Lux element
  kinds.

## Core Definition

An Element is a typed Lux UI object from the standard Lux element vocabulary.

An Element may be:

- passive display content
- an interactive control
- a composite that owns child elements
- a reusable component with lightweight built-in behavior

An Element is not just a raw wire struct, but it is also not an arbitrary app
class. Elements are the shared UI vocabulary that both the Hub and Display
understand.

## Common Contract

Every Element must:

- have a stable `kind` from the standard Lux element catalog
- have a stable `id` within its enclosing scene or app UI
- support serialization across the Hub/Display boundary without changing its
  semantic identity
- render deterministically from its current state
- fit the two-tier model: authoritative on the Hub, replicated on the Display

Every Element may:

- carry state
- expose built-in UI behavior
- participate in observer relationships
- own children if it is a composite
- expose typed interactions if it is interactive

Every Element must not:

- make the Display authoritative for its state or behavior
- require a custom app-defined element class to cross the Hub/Display boundary
- bypass the Hub and execute business behavior directly on the Display
- treat app-level pub-sub as its state replication mechanism

## Standard Element Vocabulary

Apps and agents compose the standard Lux element catalog. They do not send
custom element classes across the Hub/Display boundary.

The main families today are:

- basic display elements: `text`, `image`, `markdown`, `separator`,
  `progress`, `spinner`
- interactive controls: `button`, `checkbox`, `slider`, `combo`,
  `input_text`, `input_number`, `radio`, `color_picker`, `selectable`
- composite/layout elements: `group`, `window`, `tab_bar`,
  `collapsing_header`, `tree`, `modal`, `dialog`
- structured and richer display elements: `table`, `plot`, `draw`

The exact field schema of each kind may evolve, but the catalog itself is part
of the contract. New kinds should be added deliberately; apps should not work
around missing concepts by inventing their own cross-boundary classes.

## Framing Contract

User-facing app or agent UI is framed.

- A scene or app UI should render inside a frame or framed root surface.
- If a client omits explicit frame metadata, Lux should still treat the UI as
  framed through an implicit frame rooted at that scene or app surface.
- Display background, world background, idle screens, and other display chrome
  are separate from app content.

App content should not appear as free-floating elements directly against the
display background unless Lux explicitly defines that surface as display chrome
rather than hosted app UI.

## Tier Contract

The Hub-side copy of an Element is authoritative.

The Display-side copy of the same Element:

- exists for rendering
- exists for input capture
- preserves the element's structure and handler registrations semantically
- must not run the real business behavior locally

The Display wraps the original handlers for remote dispatch. It does not invent
an alternative behavior model.

## Interaction Contract

Interactive elements expose typed Lux interactions.

The transport shape should separate:

- **which element** was interacted with
- **what kind of interaction** happened
- **what payload** came with it

For command-like interactions:

- `event_kind` names the typed interaction, such as `button_clicked`
- `action` names the UI action, such as `confirm`, `cancel`, or the element's
  fallback action
- no value payload is required unless the interaction semantics need one

For value-changing interactions:

- `event_kind` should be `value_changed`
- `action` should be `changed`
- `value` carries the new value

Business meaning should not be encoded primarily in low-level transport action
names. It belongs in the handler chain and in app-defined pub-sub topics.

## Handler Contract

Handlers are part of the authoritative Element model.

An interactive Element may have:

- built-in handlers supplied by Lux
- app-defined handlers supplied by a client or agent
- decorators such as publish behavior attached to those handlers

The required behavior is:

1. The Display receives an element copy.
2. The Display wraps the original handler bucket for each element/event pair.
3. One user interaction produces one remote invocation for that element/event
   bucket.
4. The Hub resolves the authoritative Element.
5. The Hub fires the real event once.
6. The original authoritative handler chain runs once.

That means many interactive elements in one UI produce many wrapped handler
buckets, but one button or checkbox event with multiple handlers is still one
remote dispatch group, not one network message per inner handler.

If Display-side execution ever leaks through to a business side effect, that
should fail loudly rather than silently swallowing the behavior.

## Built-In Versus App-Defined Behavior

Lux may provide lightweight built-in behavior on standard elements when that
behavior is part of the element's own semantics.

Examples:

- a checkbox may update its own authoritative boolean value
- a dialog may own a private dialog model and dismiss itself through that model
- a table may support built-in filtering or other generic view behavior

That built-in behavior does not prevent app-defined behavior from also running.

For example, a checkbox may:

1. update its own authoritative `value`
2. run additional handlers
3. publish an app-defined topic such as `markTicketInProgress`

Lux owns the generic element behavior. The app or agent owns the business
meaning of the topics and downstream reactions.

## Composite Contract

Composite elements own child elements.

A composite may be responsible for:

- child ordering
- child lifetime
- observer-driven updates
- removal cascades
- delegating child interactions into a larger component behavior

The composite contract should stay explicit. Child ownership and observer
behavior should not be hidden in renderer code or Display-local state.

## Observer Versus Pub-Sub

Lux has two distinct mechanisms:

- **UI observer mechanics:** internal to element and composite behavior
- **application pub-sub:** app-level business events managed by the Hub

Elements may use observer relationships as part of their own UI semantics.
Elements may also publish app-level topics through handlers. These are not the
same mechanism and should not be documented or implemented as though they were.

## Family Expectations

This is the intended family-level behavior split.

| Family | Typical role | Handler expectation |
| --- | --- | --- |
| basic display elements | passive content | no app-facing handlers |
| interactive controls | user input | typed interactions; built-in behavior allowed |
| composite/layout elements | structure and composition | may own child behavior and observer cascades |
| structured/rich display elements | richer reusable widgets | generic built-in UI behavior allowed; business logic still Hub-side |

This table is intentionally high level. If Lux needs a strict per-kind support
matrix later, it should be added explicitly rather than inferred from code.

## What Elements Must Not Become

Elements must not become:

- arbitrary app-specific classes shipped across the boundary
- Display-local business services
- hidden transport adapters that talk around the Hub
- a dumping ground for app semantics that should instead live in handlers,
  app code, or Hub pub-sub

The target model is a standard Lux UI vocabulary with authoritative Hub-side
behavior and replicated Display-side rendering.

## Related Target Docs

- [target.md](./target.md)
- [topology.md](./topology.md)
- [ui-model.md](./ui-model.md)
- [introspection-api.md](./introspection-api.md)
