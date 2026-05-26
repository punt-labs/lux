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

## Control

Some operations may change live display or Hub state. Those belong to the
control surface, not pure introspection.

The architectural split is:

- **introspection:** observe without modifying
- **control:** modify live state intentionally

Control operations should be documented and gated separately from read-only
inspection.

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

The current code already has a generic query mechanism in progress. That
mechanism is implementation detail. The important architectural point is that
Lux must expose a stable inspection surface for verification.
