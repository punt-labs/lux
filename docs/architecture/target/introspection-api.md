# Lux Target Introspection API

**Status:** target verification and control surface.

Start with [target.md](./target.md). This document explains how agents and
operators inspect the live system and verify outcomes.

## Purpose

Introspection exists so Lux can be observed through the real running system.

An agent should be able to:

1. drive the system through its real entry point
2. inspect the live result
3. compare the observed result with expected behavior

This is what makes "done" verifiable.

## Read-Only Introspection

The core read-only surface includes:

- `inspect_scene`
- `list_scenes`
- `list_recent_events`
- `list_errors`
- `list_clients`
- `list_menus`
- `get_display_info`
- `screenshot`

Together these let an agent confirm things like:

- a dialog rendered
- a click was registered
- a scene changed after a handler ran
- the display encountered or did not encounter an error

### `inspect_scene` render fidelity

Beyond scene structure, `inspect_scene` reports per element:

- `render_path` — `"abc"` for an element on the Element-ABC path, `"legacy"`
  for a not-yet-migrated wire dataclass. This lets a migration be verified
  programmatically ("this kind now renders via the ABC") without looking at
  pixels.
- `resolved_props` — the element's full resolved state including defaults, so
  an agent can read back both what it sent and what Lux filled in.
- `domain_mirror_present` — named for exactly what it reports: whether the
  *display-side* mirror of the element is present. It is not a claim about the Hub's authoritative
  `HubDisplay`; do not read Hub authority from a display-side query.

## Pre-Render Validation

Introspection verifies what the running system *did*. Self-validation lets an
agent verify what it is *about to* render, before anything is drawn.

When an agent submits a UI, every element self-validates (see
[element-contract.md](./element-contract.md) and [DES-039](../../../DESIGN.md)).
If any element's data does not fit its widget, the render call returns the
collected errors instead of an ack — each naming the offending element's `id`
and `kind` — and the invalid tree is not rendered. This is a verification
surface in its own right: the agent gets a precise, machine-readable account of
what was wrong with its own tree and can correct it in one round, rather than
rendering garbage and inspecting the damage afterward.

The two surfaces compose: validation catches malformed input before render;
read-only introspection (`inspect_scene`, `list_recent_events`, `list_errors`)
confirms what the valid tree became once rendered.

## Control

Some operations may change live display or Hub state. Those belong to the
control surface, not pure introspection.

The architectural split is:

- **introspection:** observe without modifying
- **control:** modify live state intentionally

Control operations should be documented and gated separately from read-only
inspection.

### Repo-scoped display config (breaking change in v0.19.0)

The display-mode control operations are scoped to a caller-supplied repository,
not to server-global state. `display_mode` and `set_display_mode` now **require
an absolute `repo` path** naming the caller's project; the config is read from
and written to `<repo>/.punt-labs/lux.md`. luxd holds no display-config state of
its own — it runs wherever launchd started it (typically `$HOME`), so every
caller must say which project it means. A missing, relative, or non-existent
`repo` argument is rejected with a `ValueError`.

## Scope

Introspection is about live Lux state, not about guessing from logs or asking a
human to describe what happened.

The API should expose enough information to inspect:

- current UI structure
- current clients and registrations
- recent interactions
- recent errors
- current display metadata

That inspection surface exists to verify what the real Hub/Display system did,
not to infer outcomes from implementation details. Business events, UI updates,
and rendered state should be verifiable without asking the user to narrate what
they saw.

## Relationship To The Architecture

Introspection does not change the authoritative model:

- the Hub remains the authority
- the Display remains the renderer/replica
- introspection simply makes that live system observable

## Implementation Note

The generic query mechanism is shipped, not aspirational. A `QueryDispatcher`
routes `QueryRequest` by method string and carries six built-in read-only
handlers — `inspect_scene`, `list_scenes`, `list_clients`, `list_menus`,
`list_recent_events`, `list_errors` — with control handlers such as
`get_display_info`, `get_theme`, `set_window_settings`, `set_frame_state`, and
`set_theme` registered by the display where they touch ImGui state. That
routing is implementation detail. The architectural point that outlives it: Lux
must expose a stable inspection surface for verification.
