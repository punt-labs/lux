# Lux Architectural Review

**Date:** March 2026 | **Version:** v0.7.0 | **Reviewer:** code-architect agent

## Summary

The architecture spec (`docs/architecture.tex`) is accurate in its broad strokes. The system is genuinely well-designed: single-threaded display loop, clean framing protocol, solid test coverage at the state machine layer, and documented acknowledgement of its own known limitations. Findings below are organized by severity.

---

## 1. Spec-Code Divergences

### 1.1 `insert_after` Patch Operation: Serialized but Never Applied (Important)

The `Patch` dataclass in `src/punt_lux/protocol.py:429` carries an `insert_after` field. The MCP server at `src/punt_lux/server.py:842` passes it through. It is serialized to the wire. However, `_apply_update()` in `display.py:1277` only handles `patch.remove` and `patch.set`. There is no branch for `insert_after`. The field is silently dropped. The architecture spec (SS2.3) does not mention `insert_after` at all.

An agent calling `update(scene_id, [{"id": "x", "insert_after": {...}}])` gets an ack but the display does nothing. No error is returned.

### 1.2 `WindowMessage` Emitted from Display to Client: Defined but Never Sent (Minor)

`WindowMessage` is defined in protocol.py, serialized, exported, and included in the `DisplayMessage` union. The architecture spec (SS3.2) lists it as "Window lifecycle (resized, closed, focused)." However, nowhere in `display.py` does the display server actually emit a `WindowMessage`. This is a half-implemented feature: the protocol plumbing exists but the trigger is absent.

### 1.3 `grid_columns` on `SceneMessage`: Wire-Round-Trippable but Never Rendered (Minor)

`SceneMessage` has `grid_columns: int | None`. The client sends it. The display stores it. But `_render_scene_tab()` never reads it -- there is no grid layout logic. The architecture spec does not mention it.

### 1.4 Text Styles "success" and "error": Documented in MCP, Not Rendered (Minor)

The architecture spec SS3.3 lists text styles: "heading, caption, success, error, code." `_render_text()` handles heading, caption, and code, but falls through to plain `text_wrapped()` for success and error. An agent following the spec will not get colored text.

### 1.5 Spec Claims `ReceiveScene` Clears the Event Queue; Code Does Selective Drain (Spec Stale)

The Z spec `ReceiveScene` schema sets `eventQueue' = {}` unconditionally. The concrete code performs a selective drain: only events for elements removed between old and new scene are dropped. This is correct for multi-scene coexistence and documented in architecture.tex SS4.1.2, but it means the Z spec refinement relationship breaks for replace-in-place. The architecture spec acknowledges the formal model predates multi-scene tabs (SS9, last paragraph).

---

## 2. Architectural Concerns

### 2.1 `_with_reconnect` Module-Level Client Singleton Not Thread-Safe (Important)

`_with_reconnect()` in `server.py:70-87` catches `OSError`, resets `_client = None`, and retries. The module-level `_client` singleton is not protected against concurrent access. FastMCP may run tools concurrently. If two concurrent tool calls both see `OSError`, both reset `_client = None`, and both call `_get_client()` which creates two `LuxClient` instances. The first connection leaks.

### 2.2 Widget State Swap Leaves Stale Reference on Rendering Exception (Minor)

`_render_scene_tab()` swaps `self._widget_state` before rendering. If a renderer raises, the swap is not restored. The exposure is limited since `_apply_update()` accesses per-scene state directly via `self._scene_widget_state[scene_id]`, but the invariant "`self._widget_state` always equals `self._scene_widget_state[self._active_tab]`" can break.

### 2.3 `_dismiss_scene` Does Not Drain Events for the Dismissed Scene (Important)

When a tab is closed, `_dismiss_scene()` removes the scene but does not remove events in `_event_queue` that reference elements from the dismissed scene. Those stale events will be broadcast to all clients on the next `_flush_events()`. This violates the Z spec invariant: "Queued interaction events reference elements that exist in the current scene."

### 2.4 Clear All Menu Uses `.clear()` on Shared Dicts (Minor)

The menu path uses `.clear()` on existing containers. The `ClearMessage` path allocates fresh instances (`WidgetState()`, `{}`). The spec says "Fresh instances allocated (not .clear() on aliased objects)." Inconsistent, though low risk in practice since no external code holds references to individual scene widget states at clear time.

---

## 3. Invariant Violations

### 3.1 Z Spec Invariant `eventQueue subseteq elemIds` Violable via Tab Dismiss (Critical)

The Z spec states: `hasScene = ztrue implies eventQueue subseteq elemIds`. The concrete multi-scene extension requires all element IDs in `_event_queue` reference elements in some active scene.

`_dismiss_scene()` does not drain events. Scenario:
1. Scene "s1" has button "b1". User clicks it. Event queued.
2. User dismisses "s1" via tab close button.
3. `_dismiss_scene("s1")` removes the scene but leaves the event.
4. `_flush_events()` broadcasts the orphaned event.

**No test covers this path.**

### 3.2 `RemoveElement` Z Spec Precondition `targetId notin eventQueue` Not Enforced (Minor)

The Z spec's `RemoveElement` has precondition `targetId? notin eventQueue`. The concrete code removes elements unconditionally without checking pending events. Same class of stale-event problem as 3.1.

---

## 4. Security Gaps

### 4.1 Socket Directory Created Without Explicit Mode 0700 (Important)

The architecture spec states: "Directory permissions (0700) on `/tmp/lux-$USER/`" as the mitigation for socket hijacking. The code at `paths.py` creates the directory with `mkdir(parents=True, exist_ok=True)` using no `mode` argument. Default on macOS with umask 022 produces `0o755` -- world-readable, world-executable. Other local users can traverse into the directory and connect to the socket.

**The spec claims 0700 protection but the code does not implement it.**

### 4.2 AST Scanner Bypass Confirmed (Documented)

The spec explicitly states the AST check "can be trivially bypassed" and calls it a "UX signal, not a security boundary." This is confirmed accurate. `__builtins__["eval"](...)` and `(lambda: None).__globals__['os']` are not caught. The spec's honesty about this is correct.

### 4.3 No Rate Limit on Event Queue Growth from render_function ctx.send() (Minor)

A user-approved `render_function` calling `ctx.send()` every frame at 60 FPS generates 60 events/second. No rate limit exists. This is a post-consent threat (user clicked Allow) so the spec's threat model does not require it, but it is a gap the spec does not acknowledge.

---

## 5. Performance Cliffs

### 5.1 Column Weight Computation on Table Update (Minor, Documented)

`_render_table()` caches column weights keyed by `id(rows)`. When `update()` replaces rows, `id()` changes and triggers an O(R*C) scan. For a 10,000-row table updated frequently, this runs O(10k) on each update frame. Pagination limits visible rows but column width computation scans all rows.

### 5.2 `_flush_events()` List Copy Overhead (Minor)

`_flush_events()` iterates `list(self._clients)` inside the event loop, creating a list copy per event to handle mid-iteration modification. At K<100 events and N<64 clients this is negligible. At high event rates from `ctx.send()`, K grows unbounded.

---

## 6. Test Coverage Gaps

### 6.1 Tab Dismiss + Event Flush Not Tested (Critical)

No test for: inject scene, queue event, dismiss scene, flush events. This is the path that violates invariant 3.1.

### 6.2 `insert_after` Patch Field Not Tested (Important)

No tests verify that `insert_after` does or does not work.

### 6.3 `WindowMessage` Emission Not Tested (Minor)

Never emitted, never tested.

### 6.4 Image `data` Field (base64) Not Rendered (Important)

`ImageElement` has a `data: str | None` field for base64 images. `_render_image()` only handles `img.path`. Sending `{"kind": "image", "data": "..."}` silently shows fallback alt text.

### 6.5 `_with_reconnect` Concurrency Race Not Tested (Important)

Module-level `_client` singleton mutation not tested for concurrent access.

### 6.6 Socket Directory Permissions Not Tested (Important)

No test asserts the socket directory has mode 0700.

---

## Architectural Soundness Assessment

The core architecture is sound. The single-threaded polling loop, framed JSON protocol, per-scene widget state swap, and consent-based render function security are well-reasoned decisions. The test suite is unusually thorough for an ImGui application -- the refinement tests provide formal verification coverage that most projects do not attempt.

The findings cluster into two themes:

1. **Multi-scene tabs outgrew the formal model.** The Z spec models single-scene. The multi-scene extension is correct in the happy path but introduces edge cases (dismiss + event drain) that the formal model cannot see and the test suite does not cover.

2. **Partially implemented features create silent no-ops.** `insert_after`, `WindowMessage`, `grid_columns`, `image.data`, and text styles "success"/"error" are all in the protocol but produce no behavior. Each is a latent spec divergence waiting to confuse an agent.

The security gap in finding 4.1 (directory permissions) is the most operationally significant: it contradicts the spec's stated mitigation and is straightforward to fix with `mkdir(mode=0o700)`.
