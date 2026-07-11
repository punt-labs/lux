# Migrating `tab_bar` and `collapsing_header` onto the Element-ABC / HubDisplay Path — the Two Remaining Simple Composites

**Status:** design + verification plan, amended to the operator's Hub-authoritative
ruling on view-state locality. No code.
**Type:** migration design (interactive container; the two remaining B3 simple
composites).
**Elements:** `tab_bar` (tabbed container) and `collapsing_header` (collapsible
section).
**Exemplars copied:** `GroupElement` — the first container on the ABC path
(`protocol/elements/group.py:42`, `protocol/elements/group_codec.py`,
`display/renderers/imgui/group.py:29`) — for the composite/child-bearing surface;
and `ButtonElement` / `CheckboxElement` — the shipped interactive exemplars
(`protocol/elements/button.py:43`, `protocol/elements/checkbox.py:40`) — for the
full D21 path: a `_remote_dispatch_specs`, a built-in state-sync handler, the
Display-side wrap, and Hub-side re-dispatch. New class takes the canonical name
(DES-041, fork-don't-mix).
**Ground truth:** `docs/architecture/target/{target,ui-model,element-contract,introspection-api}.md`,
[DES-039](../../../DESIGN.md) (self-validating elements), [DES-041](../../../DESIGN.md)
(fork, don't mix; order by testability), the render engine (PR #239), the `group`
migration (PR #240, [`group-element-design.md`](group-element-design.md)), the
checkbox/button D21 path, and the code cited inline.

`tab_bar` and `collapsing_header` are the two remaining **simple composites** in
the testability order (audit §5 Batch 3, [DES-041](../../../DESIGN.md)). `group`
crossed in PR #240 and is the container frame they copy; `button`/`checkbox`
crossed earlier and are the interaction frame they copy. They are the
highest-leverage kinds left because they organize every other element — a tab bar
groups multi-view surfaces, a collapsing header hides secondary content.

The operator has ruled the one genuine open decision — view-state locality (§4) —
in favour of **Hub-authoritative**. This document is the design under that ruling:
both containers are now **interactive** kinds on the full D21 path, and the design
below specifies the fire/dispatch/re-push loop, the agent-drive write path, and
the Hub's reconciliation of the active tab when the tab set changes. §9 lists the
remaining sign-off items — including the new decisions the interactive design
creates.

---

## 1. Understanding restated (in the designer's words)

### 1.1 The target model, applied to two interactive containers

Clients submit UI to the Hub; the Hub decodes it into typed UI objects and
installs them in `HubDisplay`, the authoritative store for state, ownership, and
dispatch; the Display holds a full replica used only for rendering and input
capture; after a change the Hub re-sends the whole affected UI and the Display
replaces its copy (`target.md:24`–`:39`). The load-bearing boundary rule: **UI
state crosses IPC; render calls do not** (`target.md:63`–`:71`).

Both kinds belong to the **composite/layout elements** family — role "structure
and composition," handler expectation "may own child behavior and observer
cascades" (`element-contract.md:80`, `:246`). Like `group` they own children and
arrange them. Unlike `group`, they also carry one **agent-drivable view
selection** each:

- `tab_bar` — which tab is active;
- `collapsing_header` — whether the section is open.

Under the operator's ruling those selections are **Hub-authoritative** (§4). That
makes both kinds interactive: each fires a typed interaction (`tab_changed`,
`header_toggled`), routes it to the Hub, and lets the Hub update the authoritative
selection and re-push. They are therefore **`Group` (a container) composed with a
`Checkbox`-shaped interaction (one Hub-authoritative value the user can change and
the agent can drive)** — not the display-only shape `group` was.

### 1.2 What crosses the boundary, what is authoritative, what is local

For a migrated ABC `tab_bar` / `collapsing_header`:

- **Crosses the Hub→Display boundary:** the serialized container object *and its
  ABC children*, *and the built-in state-sync handler each registers*. A top-level
  ABC element crosses as one base64-encoded pickle blob
  (`protocol/messages/scene.py`); `pickle` recurses the object graph, so the
  container's ABC children, their handler registrations, and the container's own
  handler registration all travel inside the one blob. `Element.__reduce__`
  (`element_abc.py:75`) keeps `_renderer_factory` and `_handlers` in the pickled
  state and drops only `_observers`. This is UI state.
- **Hub-authoritative:** the container's *structure* — `id`, the ordered tabs and
  their children (`tab_bar`); `id`, `label`, and the ordered children
  (`collapsing_header`) — **and the runtime view-selection**: the active tab
  (`tab_bar`) and the open flag (`collapsing_header`). The Hub owns all of it;
  the Display never mutates it locally. This is the delta from the earlier draft,
  where the runtime selection was Display-local (§4).
- **Display-local:** only the ImGui layout/paint calls, and *continuous in-flight
  input* that has no place on the Hub — scroll offset, a window drag, mid-type
  filter text. A tab click and a header toggle are *discrete* selections, so they
  route to the Hub; they are not in this list. (See the discrete-vs-continuous
  principle, §4.)

Render calls do not cross the wire: `Element.render()` runs on the Display
against its replica, resolving each container's ImGui adapter through the factory
(`element_abc.py:110`, `display/renderers/imgui/factory.py`).

### 1.3 Why they need BOTH the composite surface AND the interactive surface

The Element ABC (`element_abc.py:43`) carries render, children, validation,
handler, wrap, and observer surfaces. `group` used the composite subset and only
*inherited* the interactive subset. These two kinds use **both** — the composite
subset like `group`, and the interactive subset like `checkbox`:

| ABC member | Needed? | Why |
|---|---|---|
| `id` (abstract, `element_abc.py:97`) | **Yes** | Every element has a stable scene identity; `HubDisplay` indexes by it. |
| `render()` template (`element_abc.py:102`) | **Yes, inherited** | Never overridden. Drives `_begin` → `_paint_self` → `_render_children` → `_end`. |
| `_children()` (`element_abc.py:144`) | **Yes, overridden** | Returns the container's children so the walk paints, wraps, rebinds, and validates them. |
| `_begin` / `_end` | **Yes (renderer-side)** | Open/close the tab-bar / collapsing-header surface (§3). |
| `_paint_self` | **No-op** | A pure container's body *is* its children; its renderer's `paint` is a no-op. |
| `_render_children` | **`tab_bar`: overridden; `collapsing_header`: inherited** | The tab bar interleaves per-tab item brackets and gates on the active tab (§3.1); the header is a plain box (§3.2). |
| `child_elements()` (`element_abc.py:176`) | **Inherited (bridges to `_children()`)** | Every installed child is render-visible-set-membership (all tabs' children cross the wire), so the walk set equals `_children()` — no override needed. |
| `validate()` (`element_abc.py:167`) | **Yes, overridden** | Component-appropriate structural check, now including active-tab validity (§3.3). |
| `bind_renderer_factory` (`element_abc.py:154`) | **Yes, inherited** | Recurses `_children()` to rebind the Display factory onto the container and its subtree. |
| handler registry / `fire` (via `EventHandlerHost`) | **Used** | Each container registers a built-in state-sync handler for its interaction (the checkbox pattern, §4.6), so `fire` has a bucket to dispatch and the Hub has authoritative behavior to run. |
| `_remote_dispatch_specs` (`event_handler_host.py:140`) | **Yes, overridden** | Each declares its own spec (`tab_changed` / `header_toggled`) so the Display wrap collapses its bucket into one remote invocation (§4.5). |
| `wrap_handlers_for_remote` (D21) | **Used** | Recurses `_children()` **and** wraps the container's own bucket — an interactive container wraps *itself* now, not just an interactive child. |
| `apply_patch` / `_set_<field>` (`element_abc.py:198`) | **Yes** | The Hub updates the authoritative selection through `apply_patch` — both the built-in handler and the agent-drive write path use it (§4.6, §4.7). |
| `mark_removed` / observers | **Present, unused** | Neither container dismisses itself. |

The rule in one line: **an interactive container needs the ABC's identity, render
template, children hook, layout begin/end, validation, and factory rebind (the
`group` composite subset) AND its handler registry, remote-dispatch spec, wrap,
and field-patch surface (the `checkbox` interactive subset).** It inherits — but
does not exercise — only the self-dismiss/observer-cascade machinery.

### 1.4 The delta from `group`, `checkbox`, and the honest cost

`GroupElement` (`group.py:42`) proves the display-only composite works on the ABC
path; `CheckboxElement` (`checkbox.py:40`) proves the Hub-authoritative
single-value interaction works. These two kinds are the **composition** of those
two proofs: a container that also owns one Hub-authoritative value.

- `collapsing_header` is the *closest* copy — a plain box (override `_children()`
  only) carrying a single Hub-authoritative `open: bool`, toggled exactly the way
  `checkbox` toggles its `value: bool`.
- `tab_bar` is the harder copy — it needs a `_render_children` override and a
  per-tab renderer sub-protocol (§3.1), and its Hub-authoritative value is a tab
  *id* rather than a bool (§4.5).

**One real cost, stated honestly.** Hub-authoritative view-navigation
round-trips to the Hub: a tab click or a header toggle travels to the Hub and the
new selection comes back on the re-push. For a local Hub (v1) that is a sub-
millisecond, one-frame echo. On a **remote** Hub/Display it adds a network hop
before the tab visually settles, mitigable later with optimistic local rendering
(render the click immediately, reconcile when the echo arrives). We note it as a
**deferred v2-remote optimization, not a v1 blocker** — the same replication model
already governs `checkbox`, and no v1 surface has found the local echo
perceptible.

---

## 2. Promote the raw child containers to typed Elements, and add the view field

Both legacy dataclasses store children in a shape the composite render template
cannot recurse (audit §4 "Composite"):

- `TabBarElement.tabs: list[dict[str, Any]]` (`layout.py:108`) — each tab is an
  untyped mapping `{"label", "children"}`. `PY-OO-4` (no raw dict for a domain
  concept) and `PY-OO-1` (domain nouns are classes). A tab is a domain noun with
  data (`tab_id`, `label`) and children.
- `CollapsingHeaderElement.children: list[Any]` (`layout.py:152`) — `Any` is the
  type system giving up on the heterogeneous legacy union.

The migration introduces one small typed value class, tightens the fields, and
adds the Hub-authoritative view field to each container:

- **`Tab`** — a `@dataclass(frozen=True, slots=True)` value object: `tab_id: str`,
  `label: str`, `children: tuple[Element, ...]`. Composed into `TabBarElement`
  (`_tabs: tuple[Tab, ...]`), not inherited (`PY-IC-1`). The `tab_id` is the
  *stable identity* the active-tab selection names (§4.5) — stable under reorder
  and relabel, which is what makes the Hub's reconciliation a membership check
  rather than an index clamp (§4.8).
- **`TabBarElement._active_tab: str`** — the `tab_id` of the currently-active tab.
  `""` is the discriminated "no tabs" state (an empty strip); with tabs present it
  always names a live tab (the decoder seeds it to `tabs[0].tab_id`, and the Hub
  keeps it valid, §4.8). This is a total field, not an Optional — the same move
  `group.page_source: str = ""` made.
- **`CollapsingHeaderElement._open: bool`** — the Hub-authoritative open flag. It
  *replaces* the legacy `default_open`: under Hub authority there is no separate
  "declared initial" vs "runtime" split — the single `open` field is the initial
  value the agent declares, the runtime value the user toggles, and the value the
  agent re-drives. One field, three roles, one authority. (Wire-key note in §9-Q9.)
- **`collapsing_header`**: `children: list[Any]` → `_children_tuple: tuple[Element, ...]`.
- **Both**: `tooltip: str | None` **stays** — absence is the documented contract
  for an optional tooltip (`PY-TS-14` OK, as `group.py`/`checkbox.py`).

The typed `Tab` is what lets `TabBarElement._children()` return real Elements so
the render template, the D21 wrap recursion, `bind_renderer_factory`, and the
validation walk all traverse the subtree uniformly; and its `tab_id` is what the
interaction carries.

---

## 3. The two ABC designs

### 3.1 `TabBarElement` — the interactive composite that is not a plain box

`_children()` flattens every tab's children into one tuple:

```python
def _children(self) -> tuple[Element, ...]:
    return tuple(child for tab in self._tabs for child in tab.children)
```

Every tab's children are *installed and cross the wire* — only the active tab is
*drawn*. So the render-visible-set membership (any child may be drawn once its tab
is active) equals the installed set, and `child_elements()` (the validation walk)
bridges to `_children()` unchanged — **no `child_elements()` override**.

The ABC template's default `_render_children` recursion paints *every* child
flat, with no tab headers — wrong for a tab bar. `tab_bar` therefore **overrides
`_render_children`** to bracket each tab and gate on selection, delegating the
ImGui work to the renderer (the domain class must not call ImGui — `PY-IC-8`, core
never imports presentation):

```python
def _render_children(self, renderer: Renderer) -> None:
    tab_renderer = cast("TabContainerRenderer", renderer)
    for tab in self._tabs:
        selected = tab_renderer.begin_tab(tab, active=self._active_tab)
        try:
            if selected:
                for child in tab.children:
                    child.render()
        finally:
            tab_renderer.end_tab(opened=selected)
```

Note `_active_tab` is passed *in*: the renderer honours the Hub-authoritative
selection, it does not invent one (§4.7). The renderer surface it needs
(`begin_tab` / `end_tab`) is broader than the shared leaf `Renderer` Protocol
(`begin`/`paint`/`end`, `protocol/renderer.py`). The recommendation (§9-Q2) is a
**small `TabContainerRenderer` sub-protocol** rather than widening the shared
`Renderer` Protocol.

The ImGui adapter `ImGuiTabBarRenderer` (`display/renderers/imgui/tab_bar.py`,
`@final`, `(elem, factory)` constructor like `imgui/group.py`) is the interactive
seam (§4.7). Its `begin_tab`/`end_tab` both **honour the Hub's active tab** and
**detect a user change to fire `tab_changed`** — the exact two-way pattern the
button renderer uses for a click, generalized to a persistent selection.

### 3.2 `CollapsingHeaderElement` — the interactive plain-box copy of `group`+`checkbox`

Overrides only `_children()` (returns `_children_tuple`) and `validate()`. It does
**not** override `_render_children`: a collapsing header is a single disclosure
region, so the ABC template's existing gate does the work — `_begin` returns
whether the header is expanded, and the template runs `_paint_self` +
`_render_children` only `if opened`.

The ImGui adapter `ImGuiCollapsingHeaderRenderer`
(`display/renderers/imgui/collapsing_header.py`, `@final`) is the interactive seam:

- `begin()` → **honour the Hub `open` state each frame** with
  `imgui.set_next_item_open(elem.open)` (not `ImGuiCond.first_use_ever` — the Hub
  owns the value, so it is authoritative every frame, not just the first, §4.7);
  then call `imgui.collapsing_header(elem.label)` and read the bool ImGui returns.
  A `False` return means the ABC template skips the children — collapsed sections
  draw no body, for free.
- **Detect a user toggle and fire `header_toggled`**: when the bool ImGui reports
  differs from `elem.open` (a user just clicked the disclosure triangle), the
  adapter constructs a `HeaderToggled` event carrying the new bool and calls
  `elem.fire(event)` — routing it to the Hub (§4.6). It must fire only on the
  *transition*, not every frame, and it must **not** mutate `elem.open` locally
  (that would make the Display authoritative).
- `paint()` → no-op. `end(opened)` → no-op (`collapsing_header` returns a bool with
  no matching close call).

### 3.3 `validate()` — component-appropriate, now including the active tab

Per [DES-039](../../../DESIGN.md), validation rides with the migration. Each kind
checks what is *component-appropriate* for its widget; child validity is collected
by the walk recursing `child_elements()`, not here.

- **`tab_bar`**: (a) every tab must carry a non-empty string `label` — an
  empty/blank label yields an unclickable, indistinguishable tab; (b) `tab_id`
  values must be unique — the active-tab selection names a tab by id, and
  duplicate ids make the selection ambiguous; (c) if `_active_tab` is non-empty it
  must name a live tab. A tab bar with zero tabs is valid (an empty strip, with
  `_active_tab == ""`). Checks (b) and (c) are new and exist precisely because the
  selection is now Hub-authoritative and id-addressed.
- **`collapsing_header`**: the `label` must be non-empty — a headerless disclosure
  toggle is a mistake. `open` is a `bool` coerced at the decode boundary, so no
  runtime invariant fails here.

These are the recommended invariants; the exact component-appropriate set is the
implementer's DES-039 call, confirmed during migration (§9-Q5). A malformed tab
mapping or non-list children is caught at the decode boundary (`PY-EH-1`); a
*nested* invalid element is collected by the walk via `child_elements()`.

---

## 4. View-state locality — RESOLVED: Hub-authoritative, and the discrete-vs-continuous principle

`tab_bar` carries an **active-tab selection**; `collapsing_header` carries an
**open/collapsed flag**. The question was whether each lives Display-local (the
replica owns it, the Hub never re-pushes it) or Hub-authoritative (it crosses the
boundary and is re-pushed on change).

**The operator has ruled: Hub-authoritative for both.** This section documents the
ruling, its rationale, and the go-forward principle it establishes. It is not
re-argued here; the earlier Display-local recommendation and its supporting
"snap-back" argument are removed as incorrect (below).

### 4.1 The ruling and its rationale

Both the `tab_bar` active tab and the `collapsing_header` open flag are
Hub-authoritative. Three reasons, as ruled:

1. **The agent can drive navigation.** Only a Hub-authoritative selection lets the
   *agent* switch tabs or expand a section for the user — a v2 GUI-interaction
   capability (the agent reshapes the live UI, `target.md` "Verification"). A
   Display-local selection is invisible and unreachable to the Hub, so the agent
   could never drive it.
2. **Single source of truth.** One authority means no Hub/Display divergence about
   which tab is showing or whether a section is open. The Display renders whatever
   the Hub says; there is no second, private answer on the Display.
3. **Structural-change coherence.** When a tab is added, removed, or relabeled, the
   Hub reconciles the active tab *deliberately* (§4.8), rather than leaving it to
   ImGui's implicit id-keyed fallback — which is what a Display-local selection
   would rely on, and what made the "new tab added → inconsistency" case
   worrying.

**The removed argument.** The earlier draft argued that Hub-authority "fights
replication: every unrelated Hub re-push snaps the user back to tab 1." That is
wrong, and it is struck. A *faithful* Hub re-pushes the **correct** active tab —
because the active tab is part of the element structure the Hub owns and sends.
An unrelated re-push carries the current `_active_tab` unchanged, so the Display
re-renders the same active tab. There is no snap-back. The snap-back only happens
if the selection is Display-local *and* the Hub resends a replica that doesn't
know the selection — the opposite arrangement. Hub-authority is what *prevents*
the snap-back, not what causes it.

### 4.2 The go-forward principle: discrete drivable selection vs continuous in-flight input

The ruling generalizes into a boundary that keeps the model coherent as more kinds
migrate:

- **DISCRETE, agent-drivable view-selections are Hub-authoritative.** A value drawn
  from a small, enumerable set that (a) the user changes by a distinct act and (b)
  the agent might reasonably want to drive: the `tab_bar` active tab, the
  `collapsing_header` open/collapsed flag, and the `group` **paged page-index**.
  These cross the boundary and are re-pushed on change.
- **CONTINUOUS, in-flight input stays Display-local.** A value that is a *transient
  editing gesture* with no discrete "the user chose X" moment and no agent-drive
  use case: scroll offset, mid-type filter text, a search string being typed, a
  window-drag position, a column-resize in progress. These stay on the Display and
  are **not** re-pushed — a whole-tree resend must never clobber a user's
  in-progress filter or scroll. This is the `table` B6 carve-out, unchanged
  ([DES-041](../../../DESIGN.md) decision 3): "ephemeral *view* state — active
  filter text, search string, scroll, window drag position — stays Display-local."

The distinguishing test: **is this a discrete choice the agent might set, or a
continuous gesture only the user makes?** A tab is a discrete choice (and an agent
might open a specific tab for the user) → Hub. A scroll offset is a continuous
gesture (no agent drives a pixel scroll) → Display. The `table` filter text and
scroll remain Display-local under this exact test; nothing about the ruling
touches them.

### 4.3 Consequence: the paged-group page-index should move to Hub-authoritative

`group`'s **paged page-index** was earlier ruled Display-local
([`group-element-design.md`](group-element-design.md) §1.2, §3.3). Under the
discrete-vs-continuous principle it is on the **discrete, agent-drivable** side —
"which sub-view is showing" is exactly the same kind of selection as the active
tab, and an agent might page a group for the user. For consistency the paged
page-index **should move to Hub-authoritative** to match.

This document **flags** that as a small follow-up revision to
`group-element-design.md`; it does **not** implement it here (paged is a separate,
already-scoped increment in the group epic). The flag exists so the boundary stays
coherent: three container "which sub-view" selections (tab, header, page) should
land on the same side of the line, and that side is Hub-authoritative.

### 4.4 `resolved_props()` REPORTS the authoritative view-state

Because the Hub now **owns** the active tab and the open flag, introspection
**reports** them — the opposite of the earlier draft, which said the Hub "literally
cannot" report an `active_tab` it did not own.

- `tab_bar.resolved_props()` returns its `tabs` (each `tab_id` + `label` + child
  ids) **and `active_tab`** (the id of the currently-active tab).
- `collapsing_header.resolved_props()` returns `label`, child ids, **and `open`**
  (the current runtime open flag).

```python
# TabBarElement
def resolved_props(self) -> Mapping[str, object]:
    return {
        "tabs": [
            {"tab_id": t.tab_id, "label": t.label,
             "children": [c.id for c in t.children]}
            for t in self._tabs
        ],
        "active_tab": self._active_tab,
        "tooltip": self._tooltip,
    }

# CollapsingHeaderElement
def resolved_props(self) -> Mapping[str, object]:
    return {
        "label": self._label,
        "open": self._open,
        "children": [c.id for c in self._children_tuple],
        "tooltip": self._tooltip,
    }
```

An agent can therefore verify, without pixels, *which tab is active* and *whether
a section is open* — the introspection payoff of Hub authority (§7 Level 5).

### 4.5 The interaction each kind fires

Both kinds join the D21 event set. Two new typed interactions
(`domain/interaction.py`), each a frozen-slots dataclass carrying the three
identifying fields plus its payload, exactly like `ButtonClicked` / `ValueChanged`:

- **`TabChanged`** — payload `tab_id: str` (the newly-selected tab's id). `EventKind`
  discriminator `"tab_changed"`.
- **`HeaderToggled`** — payload `open: bool` (the new open state). `EventKind`
  discriminator `"header_toggled"`.

The `EventKind` Literal (`interaction.py:24`) extends from
`Literal["button_clicked", "value_changed"]` to add `"tab_changed"` and
`"header_toggled"`. Each container declares its spec (`event_handler_host.py:140`),
mirroring `button.py:153` / `checkbox.py:117`:

```python
# TabBarElement
def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
    return (RemoteDispatchSpec(TabChanged, self.id, "tab_changed"),)

# CollapsingHeaderElement
def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
    return (RemoteDispatchSpec(HeaderToggled, self.id, "header_toggled"),)
```

The action is the element `id` (there is one interaction per container, so the id
is the natural bucket key — the same default `button` uses via its `None` action).

The wire message `RemoteEventHandlerInvocation.value` is already `Any`
(`remote_invocation.py:24` — "wire payload; shape varies by element kind"), so a
`str` tab id or a `bool` open flag crosses with **no message-schema change** — only
the dispatch branches that read `value` grow (§4.6).

### 4.6 The full D21 loop — user acts → Display fires → Hub re-dispatches → re-push

The loop is byte-identical in shape to the button/checkbox loop; only the event
type and payload differ. Take `tab_bar` (header is the same with
`HeaderToggled`/`open`):

1. **Built-in state-sync handler registered at decode.** Just as
   `JsonCheckboxDecoder` registers `_UpdateValueHandler` before any wire handlers
   (`checkbox_codec.py:108`), `JsonTabBarDecoder` registers a serializable
   `_UpdateActiveTabHandler(elem)` for `TabChanged`:

   ```python
   class _UpdateActiveTabHandler:
       """Built-in state-sync: mirror the new active tab onto the element."""
       def __call__(self, event: TabChanged) -> None:
           self._elem.apply_patch({"active_tab": event.tab_id})
   ```

   This handler is what gives the wrap a bucket to collapse and the Hub the
   authoritative behavior to run — the same role `_UpdateValueHandler` plays for
   `checkbox`. It is `__reduce__`/`__setstate__`-serializable so it survives the
   pickle to the Display (`checkbox_codec.py:48`).

2. **Display wraps the bucket.** After receiving the replica, the Display calls
   `wrap_handlers_for_remote(send_fn)` (`event_handler_host.py:117`). It reads the
   container's `_remote_dispatch_specs()`, finds the `TabChanged` bucket
   (populated by the built-in handler), and collapses it into one
   `RemoteDispatchGroup` — **the Display copy never runs the real state update
   locally**; it will forward.

3. **User clicks a tab.** `ImGuiTabBarRenderer` detects that ImGui reports a
   different selected tab than `elem.active_tab` and constructs
   `TabChanged(scene_id, element_id, owner_id, tab_id=<clicked id>)`, then calls
   `elem.fire(event)` — the exact move `ButtonRenderer.render` makes on a click.

4. **`fire` runs the wrapped handler → one remote invocation.** The
   `RemoteDispatchGroup.__call__` (`remote_dispatch.py:94`) reads the event's
   payload and sends one `RemoteEventHandlerInvocation(element_id, action=id,
   event_kind="tab_changed", value=<tab_id>)` over the real socket. Its `__call__`
   currently branches on `ValueChanged` / `ButtonClicked` to extract `value`; it
   **grows two branches** — `TabChanged → value = event.tab_id`,
   `HeaderToggled → value = event.open` (§6, the wrap seam).

5. **Hub re-dispatches on its authoritative copy.**
   `ClientRegistry._hub_interaction_dispatch` (`clients.py:100`) resolves the
   element and owner from `HubDisplay`, and **grows two branches** to construct the
   typed event from `event_kind`: `"tab_changed" → TabChanged(..., tab_id=value)`,
   `"header_toggled" → HeaderToggled(..., open=value)`. It then calls
   `element.fire(event)` on the Hub's copy — where the built-in
   `_UpdateActiveTabHandler` runs and `apply_patch({"active_tab": tab_id})` updates
   the **authoritative** selection.

6. **Hub re-pushes the whole scene.** The existing re-push in
   `_hub_interaction_dispatch` (`clients.py:199`) resends
   `hub_display.scene_roots(scene_id)`. The re-pushed `tab_bar` now carries the new
   `active_tab`; the Display replaces its replica and renders the newly-active tab.
   The loop closes: the user's click is reflected because the Hub — the one
   authority — recorded it and echoed it.

The in-process dispatch contract `Display.interact` (`display.py:250`,
`_build_event` at `:330`) grows the same two branches so the single-runtime test
path constructs `TabChanged` / `HeaderToggled` for these kinds, exactly as it does
`ButtonClicked` / `ValueChanged` today.

### 4.7 The agent-drive (write) path — the Hub sets the value, the adapter honours it

Because the active tab / open flag is a **field of the element structure the Hub
owns**, the agent drives it the same way it drives any field: a re-push with a new
value. There are two equivalent write entry points:

- **A field patch** through the scene-update path — `SetProperty` /
  `apply_patch({"active_tab": "details"})` (or `{"open": True}`) on the Hub copy —
  followed by the Hub's re-push. `_set_active_tab` / `_set_open` are the patch
  setters (`element_abc.py:198` dispatches `_set_<field>`), mirroring
  `button._set_label` / `checkbox._set_value`.
- **A fresh `show()`** carrying the container with the desired `active_tab` / `open`
  — the whole-UI resend replaces the replica.

Either way the new value is part of the structure that crosses to the Display. The
**critical adapter requirement**: the ImGui adapter must *honour* the Hub-set value,
not merely read ImGui's local state. ImGui, in immediate mode, tracks its own
id-keyed selection; if the adapter only *reads* that, an agent-driven change would
be ignored (ImGui would keep showing the user's last local pick). So:

- **`tab_bar`**: when `elem.active_tab` differs from the value the adapter last
  honoured (a fresh Hub value arrived), the adapter forces ImGui to that tab via
  `imgui.set_tab_item_flags(..., ImGuiTabItemFlags_SetSelected)` on the matching
  tab for that frame, and records the honoured value in the per-scene
  `WidgetState`. When `elem.active_tab` is unchanged, it does *not* force-select
  (that would fight a user mid-click); instead it compares ImGui's reported
  selection to `elem.active_tab` and fires `tab_changed` on a user divergence
  (§4.6 step 3).
- **`collapsing_header`**: `imgui.set_next_item_open(elem.open)` each frame honours
  the Hub value; the same change-detection via `WidgetState` distinguishes a
  fresh Hub write (honour it) from a user toggle (fire `header_toggled`).

The `WidgetState` "last honoured value" is read from the *current* scene's state at
render time, never from the factory's construction-time copy — the same discipline
`group`'s paged renderer follows to avoid a cross-scene bug
([`group-element-design.md`](group-element-design.md) §2.4). This is Display-local
*bookkeeping* (last-seen), not Display-local *authority* — the authority is
`elem.active_tab` / `elem.open`, which the Hub owns.

### 4.8 Hub reconciliation on structural change — resolving "new tab added → inconsistency"

When a re-push changes the tab *set* — a tab added, removed, or relabeled — the Hub
must keep `_active_tab` valid. This is the operator's explicit concern, and
id-addressing is what makes it clean:

- **A tab is added.** `_active_tab` still names a live tab, so it is unchanged — the
  new tab does not steal focus. (Index-addressing would have been fragile here: an
  insert shifts every later index, so an index-based selection would silently point
  at a different tab. Id-addressing has no such failure — this is why `Tab` carries
  a `tab_id` and the selection names it, §2.)
- **A tab is removed.** If the removed tab was *not* the active one, `_active_tab` is
  still valid — unchanged. If the removed tab *was* the active one, the Hub
  **resets `_active_tab` to `tabs[0].tab_id`** (the first remaining tab), or to `""`
  if no tabs remain. A dangling selection never survives.
- **A tab is relabeled.** The `tab_id` is stable across a label change, so
  `_active_tab` is untouched — relabeling never disturbs the selection. (Another
  reason the selection names an id, not a label.)

Where this runs: reconciliation belongs on the **element**, invoked by the Hub
whenever the tab set is replaced — i.e. inside the `_set_tabs` patch setter (and at
decode, seeding `_active_tab` to `tabs[0].tab_id` when the wire omits it). A single
method keeps the invariant in one place:

```python
def _reconcile_active_tab(self) -> None:
    """Keep _active_tab naming a live tab after the tab set changes.

    A selection that still names a present tab is kept; a selection whose
    tab was removed resets to the first tab; an empty tab set clears it.
    """
    live = {tab.tab_id for tab in self._tabs}
    if self._active_tab in live:
        return
    self._active_tab = self._tabs[0].tab_id if self._tabs else ""
```

The invariant — **`_active_tab` is `""` or names a live tab, always** — is what
`validate()` check (c) asserts (§3.3) and what the reconciliation maintains. The
"new tab added → inconsistency" case is resolved explicitly: an add leaves a valid
selection valid, and the only mutation is the deliberate reset-on-remove.

`collapsing_header` has no structural analog — `open` is a bool with no set to
reconcile against — so its only "reconciliation" is the trivial one: a re-push
carries whatever `open` the Hub holds.

---

## 5. Fork, don't mix — renames, the all-ABC gate, and the legacy-forcing rule

Per [DES-041](../../../DESIGN.md) decision 2, **the new ABC classes take the
canonical names; the legacy dataclasses are renamed out of the way**, exactly as
`GroupElement` → `LegacyGroupElement` (PR #240). This is unchanged by the
Hub-authoritative ruling — the fork mechanics are about ABC-vs-legacy routing, not
about view-state.

- `protocol/elements/layout.py` — `TabBarElement` → `LegacyTabBarElement`;
  `CollapsingHeaderElement` → `LegacyCollapsingHeaderElement` (class, `__all__`,
  `register_codecs`). Each legacy class keeps its dataclass shape and its
  `child_elements()` for the validation walk.

**The all-ABC gate.** Like `group`, both kinds are **conditionally ABC** — they
hold children, so they cross onto the ABC class only when their *entire subtree* is
migrated-ABC; any legacy descendant forks the whole subtree legacy. This is the
`JsonGroupDecoder.is_all_abc` / `first_non_abc_kind` mechanism
(`group_codec.py:67`–`:102`). Two structural facts follow:

1. **Extend the migrated-ABC-kinds set.** `_MIGRATED_ABC_KINDS`
   (`group_codec.py:31`) must grow to include `tab_bar` and `collapsing_header` so
   an all-ABC `group` (or tab_bar, or header) may hold them.
2. **The gate must recurse each container's child shape.** `first_non_abc_kind`
   currently special-cases `kind == "group"` to recurse. It must also recurse
   `tab_bar` (children under `tabs[].children`) and `collapsing_header` (children
   under `children`). Three container kinds now share one recursive "is my whole
   subtree all-ABC?" walk. The recommendation (§9-Q3) is to **extract that walk and
   the `_MIGRATED_ABC_KINDS` set out of `group_codec.py` into a shared
   `container_abc_gate` module** the three codecs reuse (`PY-OO-7`, DRY across the
   codec family).

**The legacy-forcing rule, generalized.** `LegacyGroupElement.decode_child` is
shared by every legacy container codec and today forces a nested `kind == "group"`
to `LegacyGroupElement` so an ABC container is never nested in a legacy one (which
would hit the `[unsupported element]` fallback). Now that `tab_bar` and
`collapsing_header` are *also* conditionally-ABC container kinds, that rule must
**force nested `group`, `tab_bar`, AND `collapsing_header` to their legacy forms**
inside a legacy subtree, keeping the "an ABC container never nests in a legacy
container" invariant structural (§9-Q4).

---

## 6. The write set

Created / renamed / amended by structure, not predetermined to existing files.
`PY-OO-2` (≤ 300 lines, ≤ 3 classes/module) is noted where a split is planned.
Every module follows the `Dialog`/`Group`/`Checkbox` split precedent — element and
codec in separate modules — so no module carries both a class and its codec.

The Hub-authoritative ruling adds an **interaction surface** to the write set that
the earlier display-only draft did not have: two new event types, an `EventKind`
extension, a built-in state-sync handler per kind, and dispatch branches in three
existing D21 modules.

### 6.1 Shared interaction surface (both kinds)

**New:**

- `src/punt_lux/domain/interaction.py` — **amend**: add `TabChanged`
  (payload `tab_id: str`) and `HeaderToggled` (payload `open: bool`) frozen-slots
  event dataclasses; extend `EventKind` to
  `Literal["button_clicked", "value_changed", "tab_changed", "header_toggled"]`
  (§4.5). (This file already holds two event classes; adding two more may push it
  toward the `PY-OO-2` class-count — split into an `interactions/` package if the
  count exceeds 3 per module.)

**Amended (the D21 dispatch seam grows two branches each):**

- `src/punt_lux/domain/handlers/remote_dispatch.py` — `RemoteDispatchGroup.__call__`
  (`:94`) adds `TabChanged → value = event.tab_id` and
  `HeaderToggled → value = event.open` alongside the existing
  `ValueChanged`/`ButtonClicked` branches. **The wrap seam.**
- `src/punt_lux/domain/hub/clients.py` — `_hub_interaction_dispatch` (`:157`) adds
  `event_kind == "tab_changed"` / `"header_toggled"` branches that construct the
  typed event and fire it on the Hub copy. **The Hub re-dispatch seam.**
- `src/punt_lux/domain/display.py` — `Display._build_event` (`:330`) adds the same
  two kinds for the in-process test dispatch contract.
- `RemoteEventHandlerInvocation` (`protocol/messages/remote_invocation.py`) —
  **no change**: `value: Any` already carries a `str` or `bool` payload.

### 6.2 `tab_bar`

**New:**

- `src/punt_lux/protocol/elements/tab_bar.py` — the ABC `TabBarElement` (canonical
  name) + the `Tab` value class (two classes, ≤ 300 lines). Overrides `id`, `kind`,
  `_children()`, `_render_children()`, `validate()`, `_remote_dispatch_specs()`,
  `resolved_props()`; setters `_set_tabs` (calls `_reconcile_active_tab`, §4.8) and
  `_set_active_tab`; keeps `to_dict`/`from_dict` delegators; `tooltip` stays
  `str | None`.
- `src/punt_lux/protocol/elements/tab_bar_codec.py` — `JsonTabBarEncoder` +
  `JsonTabBarDecoder` (all-ABC gate via the shared `container_abc_gate`, §5;
  registers the built-in `_UpdateActiveTabHandler` before wire handlers; seeds
  `_active_tab` to `tabs[0].tab_id` when the wire omits it).
- `src/punt_lux/protocol/standalone_tab_bar_handler.py` — the built-in
  `_UpdateActiveTabHandler` (serializable state-sync, §4.6) + a `noop` factory
  registry, parallel to `standalone_checkbox_handler.py`.
- `src/punt_lux/display/renderers/imgui/tab_bar.py` — `ImGuiTabBarRenderer`
  (`@final`; `begin`/`paint`/`end` **plus** `begin_tab`/`end_tab`), the interactive
  seam that honours `elem.active_tab` (SetSelected on Hub change) and fires
  `tab_changed` on a user change (§4.7). Satisfies `TabContainerRenderer`.
- `src/punt_lux/protocol/renderer.py` (or a sibling) — the `TabContainerRenderer`
  sub-protocol (`begin_tab(tab, *, active) -> bool`, `end_tab(*, opened: bool)`)
  extending the shared `Renderer` (§9-Q2).
- `tests/test_tab_bar_element.py` — Levels 1–5 + validation (§7).
- `tests/e2e/scenario.py` — two new `Scenario` classmethods (child-forwarding +
  interactive) + `SCENARIOS` entries (§7 Level 4).

**Amended:**

- `src/punt_lux/protocol/elements/layout.py` — `TabBarElement` →
  `LegacyTabBarElement`; `decode_child` legacy-forces nested `tab_bar` /
  `collapsing_header` (§5).
- `src/punt_lux/protocol/elements/container_abc_gate.py` (new, shared) — extracted
  `_MIGRATED_ABC_KINDS` + recursive `first_non_abc_kind`; add `tab_bar`.
- `src/punt_lux/protocol/element_factory.py` — a `_tab_bar_decoder` field;
  `element_from_dict` gains the conditional-ABC fork branch.
- `src/punt_lux/protocol/elements/__init__.py` — the `Element` union gains ABC
  `TabBarElement` and `LegacyTabBarElement`; `_element_to_dict` adds ABC
  `TabBarElement` to the per-kind-encoder isinstance tuple.
- `src/punt_lux/protocol/encoder_factory.py` — `TabBarElement` encode entry.
- `src/punt_lux/display/renderers/imgui/factory.py` — `(TabBarElement,
  ImGuiTabBarRenderer)` in `_DISPATCH`.
- `.oo-baseline.json`, `.oo-audit.jsonl` — staged with the commit.

### 6.3 `collapsing_header`

**New:**

- `src/punt_lux/protocol/elements/collapsing_header.py` — the ABC
  `CollapsingHeaderElement` (canonical name; one class). Overrides `id`, `kind`,
  `_children()`, `validate()`, `_remote_dispatch_specs()`, `resolved_props()`;
  setter `_set_open`; keeps `to_dict`/`from_dict` delegators; `open: bool`,
  `label: str`, `tooltip: str | None`. **Inherits** `_render_children` (plain box).
- `src/punt_lux/protocol/elements/collapsing_header_codec.py` —
  `JsonCollapsingHeaderEncoder` + `JsonCollapsingHeaderDecoder` (all-ABC gate;
  registers the built-in `_UpdateOpenHandler`).
- `src/punt_lux/protocol/standalone_collapsing_header_handler.py` — the built-in
  `_UpdateOpenHandler` (serializable state-sync for `HeaderToggled`) + a `noop`
  factory, parallel to the checkbox handler.
- `src/punt_lux/display/renderers/imgui/collapsing_header.py` —
  `ImGuiCollapsingHeaderRenderer` (`@final`; honours `elem.open` via
  `set_next_item_open` each frame, fires `header_toggled` on a user toggle, §4.7).
- `tests/test_collapsing_header_element.py` — Levels 1–5 + validation.
- `tests/e2e/scenario.py` — two new `Scenario` classmethods + `SCENARIOS` entries.

**Amended:**

- `src/punt_lux/protocol/elements/layout.py` — `CollapsingHeaderElement` →
  `LegacyCollapsingHeaderElement` (the `decode_child` amendment is shared with
  §6.2).
- `src/punt_lux/protocol/elements/container_abc_gate.py` — add `collapsing_header`.
- `src/punt_lux/protocol/element_factory.py` — a `_collapsing_header_decoder` field
  plus the `element_from_dict` fork branch.
- `src/punt_lux/protocol/elements/__init__.py` — union + `_element_to_dict`.
- `src/punt_lux/protocol/encoder_factory.py` — encode entry.
- `src/punt_lux/display/renderers/imgui/factory.py` — `_DISPATCH` entry.

### 6.4 Introspection — no new primitive

`SceneInspection.from_scene` already recurses `child_elements()` so every
descendant emits an `element_paths` record (landed with PR #240). A migrated ABC
`tab_bar`/`collapsing_header` flips `render_path` to `"abc"` automatically and its
children's records flip too. Each element implements
`Inspectable.resolved_props()` — now **reporting the authoritative view-state**
(§4.4). **Nothing new to write here** beyond the `resolved_props` bodies — verify
the recursion and the reported `active_tab`/`open` in the Level-5 test.

---

## 7. Verify plan — Levels 1–6 per [`tests/CLAUDE.md`](../../../tests/CLAUDE.md)

Write expected values first; drive the real entry point; assert against live
state. Levels 1–2 are unit roundtrips; Levels 3–5 exercise the real boundary and
must never stub it. Both kinds run every level; `make check` must pass and
`.oo-baseline.json` + `.oo-audit.jsonl` are staged in the same commit.

Because both kinds are now **interactive**, each needs a **Level-4 interactive
Scenario** — the real `tab_changed` / `header_toggled` → Hub → re-push loop, like
the button Scenario — *in addition* to a child-forwarding Scenario.

1. **Level 1 — serialization roundtrip.** Build an all-ABC `tab_bar` (two tabs,
   each holding a `text` + `button`, with an explicit `active_tab`) → `to_dict` →
   `from_dict` → assert equal. Same for a `collapsing_header` (`open=True` and
   `open=False`). Include an empty tab_bar (`active_tab == ""`) and a container
   nested in a `group`.
2. **Self-validation (DES-039).**
   - **valid** → `validate()` returns `()`; the tree renders.
   - **malformed** → a `tab_bar` with an empty-label tab, **duplicate `tab_id`s**,
     or an `active_tab` naming no tab; a `collapsing_header` with an empty label —
     each returns the component-appropriate error; driven through `show()`, assert
     `client.show.assert_not_called()`.
   - **nested-malformed** → an invalid element inside a tab / inside the header is
     collected by the walk via `child_elements()`. Nest in **both** new containers.
   - **structural guard** → the DES-039 container-guard test passes with the ABC
     classes in the union (each exposes `child_elements()`).
3. **Level 2 — wire roundtrip (ABC pickled path).** Put the container in a
   `SceneMessage` → serialize → deserialize → assert equal; assert it crossed as a
   `_pickled` entry and its children **and its built-in state-sync handler**
   survived inside the blob (the wrap on the Display depends on that handler being
   present).
4. **Level 3 — Hub/Display crossing.** Install the all-ABC container into
   `HubDisplay` → push → assert an equal replica, and that `bind_renderer_factory`
   rebound the real factory onto the container *and its children*.
5. **Level 4 — the harness Scenarios (interactive AND child-forwarding).** Each
   kind gets **two** `Scenario` values in `SCENARIOS`, read by the I1–I6 invariants
   (`scenario.py:299`) — no new assertion code:
   - **Interactive Scenario** (the real D21 loop for the container itself):
     - `tab_bar_change_progress`: a `tab_bar` with two tabs beside a display-only
       `progress`. The injected interaction is a `tab_changed` carrying the second
       tab's `tab_id` (`InteractionExpectation(event_kind="tab_changed",
       value="<tab-2 id>")`); the built-in state-sync flips the Hub `active_tab`, so
       the dispatch re-push carries the mutated `active_tab`
       (`PropAfterDispatch(element_id=<tab_bar id>, field="active_tab",
       value="<tab-2 id>")`). A wire `handlers` entry publishes `tab_selected`; the
       agent reacts by advancing the progress. This proves the tab click crosses the
       faithful boundary, the Hub updates the authoritative selection once, and the
       re-push reflects it — the exact shape of `group_checkbox_progress`
       (`scenario.py:124`) with `value_changed`→`tab_changed`.
     - `collapsing_header_toggle_progress`: a `collapsing_header` beside a
       display-only `progress`. The injected interaction is a `header_toggled`
       carrying `True` (`event_kind="header_toggled", value=True`); the built-in
       state-sync flips the Hub `open` `False`→`True`, so the re-push carries the
       mutated `open` (`PropAfterDispatch(element_id=<header id>, field="open",
       value=True)`). A `handlers` entry publishes `header_expanded`; the agent
       advances the progress.
   - **Child-forwarding Scenario** (a composed interactive *child*, proving the wrap
     recursion reaches inside):
     - `tab_bar_button_progress`: a `tab_bar` whose active tab holds a publishing
       `button` and a display-only `progress`; the button publishes `ticket_opened`;
       proves the container **forwards its child's D21 wrap** through the flattened
       tab children.
     - `collapsing_header_button_progress`: the same, with the button + progress
       inside the header.
   The interactive Scenario asserts the container's *own* wrap+re-dispatch; the
   child-forwarding Scenario asserts the *recursive* wrap. Both are needed — a
   container could wrap itself correctly yet fail to recurse, or vice versa.
6. **Level 5 — introspection (`render_path == "abc"` + reported view-state).** Query
   `inspect_scene`; assert the container's record reads `render_path == "abc"` and
   `resolved_props` reads back the structure **and the authoritative view-state** —
   `tabs` + `active_tab` (tab_bar), `label` + `open` + child ids
   (collapsing_header). After driving the interactive Scenario, assert the reported
   `active_tab` / `open` reflects the interaction (this is the Hub-authority payoff:
   the introspection surface reports the selection the Hub now owns). Assert the
   **child** records also read `"abc"`. Capture the same shape decoding `"legacy"`
   when a legacy descendant forces the subtree legacy.
7. **Level 6 — live visual confirmation.** `make restart`; render a `tab_bar` and a
   `collapsing_header` through the real `show` tool; confirm by eye + `screenshot`
   that tabs switch on click and the header expands/collapses, **and** that an
   agent-driven `active_tab` / `open` re-push moves the selection without a user
   click (the agent-drive path, §4.7); capture `inspect_scene` +
   `list_recent_events`; **operator confirms** before either kind is called done.

---

## 8. What crosses the boundary, stated plainly

- A **top-level all-ABC `tab_bar` / `collapsing_header`** crosses as one `_pickled`
  blob; its ABC children and its built-in state-sync handler replicate inside that
  blob (pickle recurses), all handlers preserved. On the Display, the post-receive
  rebind calls `bind_renderer_factory` (recurses `_children()`) and
  `wrap_handlers_for_remote` (wraps the container's own bucket and recurses into
  children). Render calls stay Display-local.
- A **`LegacyTabBarElement` / `LegacyCollapsingHeaderElement`** (any legacy
  descendant) crosses as a plain dict via the legacy encode path — the known
  coexistence limitation the fork dissolves as each child kind migrates, out of
  scope here.
- The **active tab** (`active_tab: str`) and the **open flag** (`open: bool`) **do
  cross** — they are Hub-authoritative structure, re-pushed on every change. This is
  the delta from the earlier draft, where they stayed Display-local. A user
  interaction crosses back as a `RemoteEventHandlerInvocation` whose `value` carries
  the new `tab_id` / `open` bool.

---

## 9. Items needing operator sign-off

Concrete decisions, each with a recommendation. No implementation dispatches until
they are ruled on.

**Q1 — View-state locality (§4). RESOLVED.** The operator ruled
**Hub-authoritative** for both the `tab_bar` active-tab and the
`collapsing_header` open-state: the Hub owns them, they cross the boundary, and
they are re-pushed on change. The discrete-vs-continuous principle (§4.2) is the
go-forward rule; the paged-group page-index consequence (§4.3) is flagged as a
follow-up. No further decision — recorded here for completeness.

**Q2 — `tab_bar` render surface: a `TabContainerRenderer` sub-protocol (§3.1).**
Recommend a small `TabContainerRenderer` extending the shared `Renderer` with
`begin_tab(tab, *, active) -> bool` / `end_tab(*, opened: bool)`, keeping every
leaf adapter's surface minimal (`PY-IC-7`). **Decision needed:** ratify the
sub-protocol.

**Q3 — Shared all-ABC gate (§5).** Recommend extracting `_MIGRATED_ABC_KINDS` and
`first_non_abc_kind` into a shared `container_abc_gate` module reused by the three
container codecs (`PY-OO-7`). **Decision needed:** ratify (this refactors
`group_codec`).

**Q4 — Legacy nested-container forcing, generalized (§5).**
`LegacyGroupElement.decode_child` must force nested `group`, `tab_bar`, AND
`collapsing_header` to their legacy forms. Recommend. **Decision needed:** ratify.

**Q5 — `validate()` component-appropriate invariants (§3.3).** Recommend `tab_bar`
reports empty/missing labels, duplicate `tab_id`s, and an `active_tab` naming no
tab; `collapsing_header` reports an empty label. **Decision needed:** confirm or
adjust (implementer's DES-039 call).

**Q6 — Typed `Tab` value class + field tightenings (§2).** Recommend promoting
`tabs: list[dict]` → `tuple[Tab, ...]` (a frozen slotted `Tab(tab_id, label,
children)`), `collapsing_header.children` → `tuple[Element, ...]`, `tab_bar` gains
`active_tab: str`, `collapsing_header` gains `open: bool`; `tooltip: str | None`
stays. **Decision needed:** none if accepted.

**Q7 — Sequencing within the batch (§1.4).** Recommend landing `collapsing_header`
**first** (the plain-box copy — one Hub-authoritative bool, the checkbox pattern
verbatim) and `tab_bar` **second** (the `_render_children` override, the
`TabContainerRenderer` sub-protocol, id-addressed selection + reconciliation). One
container concern at a time, testability-first ([DES-041](../../../DESIGN.md)).
**Decision needed:** confirm the split.

**Q8 — Interaction payload shape — tab *id*, not tab *index* (§4.5, §4.8).
RESOLVED by [DES-045](../../../DESIGN.md).** The selection and the `tab_changed`
payload are a **stable `tab_id` string**, never a positional index. This is not a
per-element choice: DES-045 makes it the cross-cutting contract for every
composite's addressable sub-parts (see
[element-contract.md](../target/element-contract.md), "Sub-Element Addressing"),
so `tab_bar` inherits it rather than re-deciding it. Id-addressing is what makes
structural reconciliation a membership check — an add/remove/relabel of *other*
tabs never disturbs the active selection (§4.8), which directly resolves the "new
tab added → inconsistency" concern; an index would silently point at a different
tab after any insert or reorder. Each `Tab` carries a `tab_id`, synthesized from
the wire `id` when present and from the tab index when absent (the encoder emits
it so the round-trip is stable). No further decision — settled by the contract.

**Q9 — NEW: does `header_toggled` fire, and does `collapsing_header` keep a separate
`default_open`? (§2, §3.2, §4.6).** Two coupled sub-decisions:

- *Firing.* Recommend `header_toggled` **does fire** on a user toggle. Under
  single-source-of-truth (the ruling's reason 2), a user collapse that did *not*
  reach the Hub would let the Hub's `open` diverge from what the user sees — the
  exact divergence Hub-authority exists to prevent. So the toggle must route to the
  Hub even when no app-level business handler is attached; the built-in state-sync
  handler is the minimum, and an app may add its own (`header_expanded`, etc.).
- *`default_open`.* Recommend **collapsing the legacy `default_open` into the single
  Hub-authoritative `open` field** (§2): under Hub authority there is no meaningful
  "declared initial vs runtime" split — `open` is declared, toggled, and
  agent-driven through one field. The wire key becomes `open` on the ABC path (the
  legacy path keeps `default_open`). **Decision needed:** ratify firing + the
  `default_open` → `open` collapse, or keep `default_open` as a distinct wire key.

---

## 10. Report status

Design + verification plan only, amended to the operator's Hub-authoritative
ruling. No production code, tests, or introspection implementation written. Saved
to `docs/architecture/migration/simple-composites-design.md`.
