# Render-Path Unification — Design

**Status:** design, revised per the operator's ruling and its two refinements on
the render path. `Element.render()` is a fixed template skeleton (never
overridden) that calls a set of per-step hooks, each with a sensible default on
the ABC. A component overrides only the steps it needs; by default it overrides
nothing. Implementation is a single PR (see §Sequencing). No implementation
dispatched yet.
**Scope:** the four migrated Element-ABC kinds — `text`, `button`,
`checkbox`, `dialog`.
**Relationship to the migration:** this is **the fork's render engine**
([DES-041](../../../DESIGN.md)) — the prerequisite that makes `Element.render()`
the paint path for migrated kinds, so any kind can fork onto the new path. It
unifies the *paint* path for the kinds already on the ABC; every subsequent
migrated kind renders through this engine. (It does **not** build
legacy-container coexistence — under DES-041 composites are all-ABC; the
DI-truth rebind it depends on, for the ABC-in-ABC case, is merged in PR #237.)

## Abstract

Today an element being "on the ABC path" means its *type, codec routing, and
HubDisplay installation* changed — but the live pixels still flow through the
legacy renderer ([README.md:126](./README.md)). Only `text` actually paints
through `Element.render()`; `button`, `checkbox`, and `dialog` are ABC in type
but still paint via the legacy `ElementRenderer` because the ImGui renderer
factory has no adapter for them. This design gives each of the three a factory
renderer that reuses the existing per-kind paint logic verbatim, replaces the
ABC's *hardcoded* leaf-vs-composite branch in `Element.render()` with a fixed
skeleton that calls four overridable step hooks (`begin` / `paint_self` /
`render_children` / `end`), flips `_paint_element` to enter the ABC template for
every migrated kind, and prunes the ABC kinds out of the legacy dispatch. After
the change the invariant **"migrated to the ABC ≡ renders via
`Element.render()`"** holds for all four exemplars, and the load-bearing
subtlety the migration README warns about disappears for them. The whole
unification lands as one rollback-coherent PR.

## Motivation

### What is fragmented today

`DisplayServer._paint_element`
([server.py:1461-1466](../../../src/punt_lux/display/server.py)) has a per-kind
special case:

```python
def _paint_element(self, elem: Element) -> None:
    if isinstance(elem, TextElement):
        self._imgui_renderer_factory(elem).render()
    else:
        self._element_renderer.render_element(elem)
```

The `if` branch is the ABC render path. The `else` branch is the legacy path.
The same two-branch code is duplicated in `_render_scene_tab`
([server.py:1508-1511](../../../src/punt_lux/display/server.py)).
(`_render_framed_scene` already delegates to `_paint_element`
([server.py:1458](../../../src/punt_lux/display/server.py)), so flipping
`_paint_element` covers the framed path automatically.)

The `isinstance(TextElement)` special case exists only because the factory can
build exactly one adapter. `ImGuiRendererFactory.__call__`
([factory.py:77-86](../../../src/punt_lux/display/renderers/imgui/factory.py))
returns `ImGuiTextRenderer` for `TextElement` and raises `ValueError` for
everything else. So `text` is the *only* kind that can take the ABC branch;
routing any other ABC kind there would raise.

Meanwhile `button`, `checkbox`, and `dialog` — all ABC subclasses
([button.py:47](../../../src/punt_lux/protocol/elements/button.py),
[checkbox.py:41](../../../src/punt_lux/protocol/elements/checkbox.py),
[dialog.py:125](../../../src/punt_lux/protocol/elements/dialog.py)) — fall into
the `else` branch and paint via the legacy dispatch:

- `button`, `checkbox` → `ElementRenderer.render_element`
  ([element_renderer.py:209](../../../src/punt_lux/display/element_renderer.py))
  → `_dispatch_native`
  ([element_renderer.py:234](../../../src/punt_lux/display/element_renderer.py))
  matches `_NATIVE_DISPATCH`
  ([element_renderer.py:152-168](../../../src/punt_lux/display/element_renderer.py),
  entries at :159 and :161) → per-kind `ButtonRenderer` / `CheckboxRenderer`.
- `dialog` → `render_element` → not handled natively →
  `_RENDERERS["dialog"]`
  ([element_renderer.py:114](../../../src/punt_lux/display/element_renderer.py))
  → `_render_dialog`
  ([element_renderer.py:604-612](../../../src/punt_lux/display/element_renderer.py))
  → `ImGuiDialogRenderer`.

### Why unify

The introspection surface classifies elements as `render_path == "abc"` purely
by `isinstance(element, ElementABC)`
([scene_inspection.py:75](../../../src/punt_lux/scene_inspection.py)). It reads
`"abc"` for all four kinds already, even though three of them do not paint
through `Element.render()`. The README calls this the "subtlety most likely to
break a wrong mental model" ([README.md:128](./README.md)). Closing the gap for
these four makes the introspection signal mean what a reader expects it to mean,
and shrinks Batch 7 to deleting a now-legacy-only dispatch table.

## Specification

### 1. The render template: a fixed skeleton over per-step hooks

The core change. `Element.render()` today hardcodes a leaf-vs-composite branch
and a fixed child-iteration step into the base class
([element_abc.py:108-127](../../../src/punt_lux/domain/element_abc.py)):

**Before:**

```python
def render(self) -> None:
    """Template method per Composite pattern. NEVER overridden."""
    renderer = self._renderer_factory(self)
    children = self._children()
    if children:
        renderer.begin()
        try:
            for child in children:
                child.render()
        finally:
            renderer.end()
    else:
        renderer.render()
```

The branch bakes *one* rendering algorithm into the base class, and no component
can vary a single step of it without the base class deciding for it. The fix:
`render()` becomes a fixed skeleton — the step *sequence*, never overridden —
that calls four step hooks, **each with a sensible default on the ABC**. Every
step is independently overridable; by default a component overrides nothing.

**After:**

```python
def render(self) -> None:
    """Fixed template skeleton. NEVER overridden.

    Runs the render steps in order. ``begin`` opens this node's surface and
    reports whether the inner steps should run (a container that did not
    open — a hidden modal, a collapsed header — short-circuits them);
    ``paint_self`` paints the node's own body; ``render_children`` paints
    the children; ``end`` closes the surface. Each step is an overridable
    hook with a default; a component overrides only the steps it needs.
    """
    renderer = self._renderer_factory(self)
    opened = self._begin(renderer)
    if opened:
        self._paint_self(renderer)
        self._render_children(renderer)
    self._end(renderer, opened)
```

```python
def _begin(self, renderer: Renderer) -> bool:
    """Open this node's surface; return whether the inner steps run.
    Default: no container — proceed. Overridden by a component whose
    surface is a container that must be opened (and may fail to open)."""
    return True

def _paint_self(self, renderer: Renderer) -> None:
    """Paint this node's own body. Default: delegate to the renderer.
    A pure container whose body is only its children overrides this to
    nothing (its renderer's ``paint`` is then a no-op)."""
    renderer.paint()

def _render_children(self, renderer: Renderer) -> None:
    """Paint this node's children. Default: recurse ``_children()``,
    calling ``render()`` on each. A leaf has no children, so the default
    paints nothing. The children render between ``begin`` and ``end``, so
    a container's opened surface encloses them for free."""
    for child in self._children():
        child.render()

def _end(self, renderer: Renderer, opened: bool) -> None:
    """Close this node's surface. Default: nothing (a leaf has none).
    ``opened`` carries ``begin``'s verdict so a container closes only what
    actually opened (ImGui's ``end_popup`` runs only for an open modal)."""
    return
```

This is the Composite pattern with a Template Method whose steps are hooks:

- a **leaf** (text/button/checkbox) overrides nothing — `begin` proceeds,
  `paint_self` delegates to the renderer (the widget), `render_children`
  recurses zero children, `end` does nothing;
- a **plain box** (a future group with no gating) overrides nothing — the
  default recursion paints its children, bracketed by whatever its renderer's
  `paint` and open/close do;
- the **dialog** overrides only `begin`/`end` (see §3);
- a **future exotic** component reaches in and overrides any single step —
  reorder, filter, decorate — without touching the skeleton or any other kind
  (Open-Closed).

The skeleton is the stable template; the flexibility lives entirely in the
per-step hooks-with-defaults.

The prior D3 proposal — a list-returning `_render_children()` that the base
iterates and the dialog empties to `()` — is **withdrawn**. Rendering children
is a *step that paints*, not a list the base consumes. A component renders its
children its own way (or inherits the default recursion); it never lies about
having none.

### 2. Per-kind ImGui renderers

`ImGuiTextRenderer`
([text.py](../../../src/punt_lux/display/renderers/imgui/text.py)) is the
template, but its current delegation to
`self._factory.element_renderer.render_element(self._elem)`
([text.py:38-45](../../../src/punt_lux/display/renderers/imgui/text.py)) **must
change** — because §6 prunes `TextElement` from `_NATIVE_DISPATCH`, that call
would break. After the prune `render_element(text)` finds no native match and
no `_RENDERERS["text"]` entry, so it paints the literal
`"[unsupported element: text]"` fallback
([element_renderer.py:213-219](../../../src/punt_lux/display/element_renderer.py))
instead of the text. The text adapter therefore adopts the **same
narrow-accessor + `apply_tooltip` pattern** as the two new adapters: `paint`
obtains the surviving per-kind `TextRenderer` instance through the narrow
accessor — §6 keeps `_text_renderer` owned by `ElementRenderer`, so it survives
the prune — runs it, and applies the shared `apply_tooltip` pass. It does **not**
route back through `render_element`.

The `Renderer` Protocol is `begin`/`paint`/`end` (see §4). Three leaf adapters
reuse the existing per-kind renderers verbatim — **no paint logic is
rewritten** (`ImGuiTextRenderer` is retargeted as just described; the two below
are new):

- `ImGuiButtonRenderer` — `begin` returns `True`, `paint` runs the *existing*
  `ButtonRenderer`
  ([button_renderer.py:41-55](../../../src/punt_lux/display/renderers/button_renderer.py))
  and applies the generic tooltip pass, `end` is a no-op.
- `ImGuiCheckboxRenderer` — `begin` returns `True`, `paint` runs the *existing*
  `CheckboxRenderer`
  ([checkbox_renderer.py:45-59](../../../src/punt_lux/display/renderers/checkbox_renderer.py))
  and applies the tooltip pass, `end` is a no-op.

The **dialog needs no adapter**: `ImGuiDialogRenderer`
([dialog.py](../../../src/punt_lux/display/renderers/imgui/dialog.py)),
refactored into `begin`/`paint`/`end` (§3), satisfies the Protocol directly and
the factory returns it as-is.

`ImGuiTextRenderer` is retargeted to the same `begin`/`paint`/`end` shape: its
current `render()` becomes `paint()` **with the delegation body swapped for the
narrow-accessor + `apply_tooltip` calls above** (not `render_element`), and its
two no-op `begin`/`end` methods
([text.py:47-51](../../../src/punt_lux/display/renderers/imgui/text.py)) are
rewritten to the new signatures (`begin() -> bool` returning `True`, `end(opened)`
a no-op).

Reuse discipline: each renderer must obtain the per-kind renderer instance and
its per-scene `WidgetState` **from `ElementRenderer`**, not from the factory's
own state — see §5. The narrow accessor they call is added to `ElementRenderer`
(a public seam), and the current tooltip block
([element_renderer.py:221-232](../../../src/punt_lux/display/element_renderer.py))
is extracted into a public `apply_tooltip(elem)` method so both the legacy
`render_element` and the new leaf renderers share one implementation (PY-OO-5,
PY-OO-7 — the post-processing is behavior that belongs on the class that owns
the renderers, not duplicated per renderer).

`apply_tooltip` must extract the block **whole, including the
`is_text_with_inline_tooltip` guard**
([element_renderer.py:221-232](../../../src/punt_lux/display/element_renderer.py)).
That guard suppresses the generic tooltip for *unstyled* text with a tooltip,
because `TextRenderer` paints such text with `selectable()` and emits its own
tooltip inline. Dropping the guard would give unstyled-text-with-tooltip a
**double tooltip** once the text adapter runs `_text_renderer.render()` +
`apply_tooltip()`. Faithful whole-block extraction keeps the guard and the
single-tooltip behavior.

Factory dispatch after the change
([factory.py:77-86](../../../src/punt_lux/display/renderers/imgui/factory.py)):

```python
def __call__(self, elem: object) -> Renderer:
    if isinstance(elem, TextElement):
        return ImGuiTextRenderer(elem, self)
    if isinstance(elem, ButtonElement):
        return ImGuiButtonRenderer(elem, self)
    if isinstance(elem, CheckboxElement):
        return ImGuiCheckboxRenderer(elem, self)
    if isinstance(elem, DialogElement):
        return ImGuiDialogRenderer(elem, self)
    msg = f"no imgui renderer for {type(elem).__name__}"
    raise ValueError(msg)
```

The `isinstance` chain is recommended over a dispatch table because a chain of
four keeps the constructor selection explicit and typed. If it grows past ~6
kinds in a later batch, revisit a registry — not now.

### 3. The dialog is an ordinary component

The dialog is **not** a special case. With the hooks-with-defaults skeleton it
is a plain instance of the pattern: its surface is a modal popup, so it
overrides `begin`/`end` to open and close that popup, and the **default**
`render_children` recursion draws its child Buttons inside it — because `begin`
opened the popup context, the buttons drawn between `begin` and `end` land
inside it. It overrides nothing else.

```python
class DialogElement(Element):
    ...
    def _begin(self, renderer: Renderer) -> bool:
        """Open the modal popup; return whether it opened. The skeleton
        then draws the body and children only inside an open popup."""
        return renderer.begin()

    def _end(self, renderer: Renderer, opened: bool) -> None:
        """Close the modal popup (only if it opened) and handle
        Escape/outside dismissal."""
        renderer.end(opened)
```

`_paint_self` uses the default (`renderer.paint()`, a no-op for the dialog,
whose only body is its children) and `_render_children` uses the default
recursion — each child Button renders through its own `render()` →
`ImGuiButtonRenderer` → the existing `ButtonRenderer`, the *same* path a
standalone button takes. The `DialogElement` (domain) never touches ImGui; it
calls its renderer's `begin`/`end`, and the ImGui popup calls live in
`ImGuiDialogRenderer` (display tier).

The one real detail — `begin_popup_modal` is conditional (draw the body and
children only when the popup is open) — is handled by the *general* template
capability: `begin` returns a bool and the skeleton skips the inner steps when
it is `False`, and `end` receives `opened` so it closes only what opened. This
is a container short-circuit any component can use, not a dialog-specific hack.

**Reusing the existing modal logic.** `ImGuiDialogRenderer.render()` today is a
monolith that opens the popup, iterates the children, closes it, and handles
Escape ([dialog.py:62-91](../../../src/punt_lux/display/renderers/imgui/dialog.py)).
It maps onto `begin`/`paint`/`end` cleanly and its logic is reused, not
rewritten:

- `begin()` — the visibility gate + latch bookkeeping + `open_popup` +
  `begin_popup_modal`
  ([dialog.py:64-84](../../../src/punt_lux/display/renderers/imgui/dialog.py)),
  returning the `visible` flag `begin_popup_modal` yields. **It also stashes the
  prior-frame `was_open` latch snapshot on the renderer instance** (see the state
  hand-off note in §5) so `end()` can reconstruct the external-close condition.
- `paint()` — no-op (the dialog has no body distinct from its children).
- `end(opened)` — `end_popup` when `opened`, then the external-close /
  Escape-dismiss handling that today lives at
  [dialog.py:90-91, 93-107](../../../src/punt_lux/display/renderers/imgui/dialog.py),
  which flips the model and fires the `mark_removed` cascade. `end` reads the
  `was_open` snapshot `begin` stashed, not `opened` alone (see §5).

The dialog **intentionally drops** the generic tooltip pass that
`render_element(dialog)` runs today
([element_renderer.py:221-232](../../../src/punt_lux/display/element_renderer.py)).
The new `begin`/`paint`(no-op)/`end` path has no `apply_tooltip` call, and that
is deliberate: a modal popup's own tooltip is meaningless — the tooltip belongs
to the interactive children (buttons), which retain it through the unified
button path. This is a conscious removal, not an oversight.

The child iteration the monolith did internally
([dialog.py:85-88, 108-121](../../../src/punt_lux/display/renderers/imgui/dialog.py))
is **removed** from the renderer: children now render via the ABC's default
`render_children` recursion, between `begin` and `end`. So `ImGuiDialogRenderer`
no longer needs its injected `ButtonRenderer` or `_render_child` dispatch — the
buttons render through the unified button path. The dialog renderer shrinks to
popup chrome + dismiss handling.

### 4. The `Renderer` Protocol

The Protocol ([renderer.py:18-29](../../../src/punt_lux/protocol/renderer.py))
becomes the ImGui-surface contract the step hooks drive — open, paint own body,
close:

```python
@runtime_checkable
class Renderer(Protocol):
    """Per-kind ImGui surface. ``begin`` opens the surface and returns
    whether its inner steps run; ``paint`` fills the node's own body;
    ``end`` closes it (``opened`` says whether ``begin`` opened anything).
    A leaf is a degenerate container: ``begin`` returns True, ``end`` is a
    no-op."""

    def begin(self) -> bool: ...
    def paint(self) -> None: ...
    def end(self, opened: bool) -> None: ...
```

Two contract changes from today: `render()` is renamed `paint()` (naming what it
does — paint this node's own body — and freeing `render` for the Element
skeleton), and `begin()` returns `bool` / `end()` takes `opened: bool` so the
short-circuit is expressible. The Protocol docstring's current claim that "the
Element ABC's template method chooses which path to take based on whether
`_children()` is empty" ([renderer.py:22-25](../../../src/punt_lux/protocol/renderer.py))
becomes false and is rewritten as above. The `render()` and module docstrings on
the ABC ([element_abc.py:1-29, 108-116](../../../src/punt_lux/domain/element_abc.py))
are updated in the same PR so the source describes the fixed skeleton + four
step hooks, not a leaf-vs-composite branch.

Which element uses `begin`/`end` is decided by its step-hook overrides: a leaf's
default `_begin`/`_end` proceed and close nothing, so a leaf never drives the
renderer's `begin`/`end`; the dialog's overrides do. The renderer offers the
full `begin`/`paint`/`end` surface uniformly; each element invokes the steps it
needs.

**Consequences worth stating precisely:**

- **Composite renderers/elements obtain their children via the public accessor.**
  The default `_render_children` recurses `self._children()` (protected, on the
  element). A renderer that itself needs to read children reads the element's
  **public** `children` property — `DialogElement` exposes one
  ([dialog.py:204-207](../../../src/punt_lux/protocol/elements/dialog.py)) —
  never `child_elements()` (reserved for the validation walk) and never the
  protected `_children()`.
- **`wrap_handlers_for_remote` and the validation walk are UNCHANGED.** Only the
  render path changes. `wrap_handlers_for_remote` still recurses via
  `self._children()`
  ([event_handler_host.py:117](../../../src/punt_lux/domain/event_handler_host.py))
  — the dialog buttons' D21 wrapping is untouched — and the validation walk still
  recurses via the public `child_elements()` bridge
  ([element_abc.py:159-167](../../../src/punt_lux/domain/element_abc.py)). So
  `_children()` keeps two live consumers (wrapping + validation) plus the render
  default. This is exactly why the dialog does **not** empty `_children()`: doing
  so would strip the buttons' D21 wrapping and validation. The dialog reports its
  children truthfully and renders them via the default recursion.

### 5. Preserving interactivity exactly (HARD CONSTRAINT)

The load-bearing risk: a wrong renderer silently breaks clicks/toggles. Per
interactive kind, here is what the legacy `_dispatch_native` path provides today
and how the new path preserves it *identically*.

**`widget_state` (per-scene).** The factory binds `_widget_state` once at
construction
([factory.py:46](../../../src/punt_lux/display/renderers/imgui/factory.py), from
[server.py:260-261](../../../src/punt_lux/display/server.py)). It is **never
re-bound per scene** — `_render_framed_scene` and `_render_scene_tab` update
`self._element_renderer.widget_state`
([server.py:1449](../../../src/punt_lux/display/server.py),
[server.py:1502](../../../src/punt_lux/display/server.py)) but not the factory.
`ElementRenderer`'s `widget_state` setter
([element_renderer.py:193-197](../../../src/punt_lux/display/element_renderer.py))
forwards the new scene's state to every input renderer in
`_WIDGET_STATE_RENDERERS`
([element_renderer.py:173-182](../../../src/punt_lux/display/element_renderer.py)),
which includes `_checkbox_renderer`. **Therefore the checkbox renderer must paint
through `ElementRenderer`'s `_checkbox_renderer` — the instance that receives the
per-scene state — and must not read `factory.widget_state`, which is the stale
construction-time state.** Same rule for the dialog: its latch keys must read the
*current* per-scene state, so `ImGuiDialogRenderer` reads
`factory.element_renderer.widget_state` at `begin`/`end` time — as
`_render_dialog` does today when it constructs the renderer with
`self._widget_state`
([element_renderer.py:612](../../../src/punt_lux/display/element_renderer.py)).
Reading the factory's copy would toggle / latch against the wrong scene's state —
a silent cross-scene bug.

**Event emission + the D21 seam.** The interactive fire path lives on the
element, not the renderer:

- `ButtonRenderer.render` calls `elem.fire(ButtonClicked(...))`
  ([button_renderer.py:47-53](../../../src/punt_lux/display/renderers/button_renderer.py)).
- `CheckboxRenderer.render` calls `elem.fire(ValueChanged(...))`
  ([checkbox_renderer.py:52-59](../../../src/punt_lux/display/renderers/checkbox_renderer.py)).

`elem.fire` dispatches to the element's handler registry
([event_handler_host.py:81](../../../src/punt_lux/domain/event_handler_host.py)).
On the Display side those handlers were replaced by a `RemoteDispatchGroup` in
`wrap_handlers_for_remote`
([event_handler_host.py:117](../../../src/punt_lux/domain/event_handler_host.py)),
which
sends a `RemoteEventHandlerInvocation` to the Hub instead of running the real
handler. **Because the new renderers call the *same* `ButtonRenderer` /
`CheckboxRenderer` instances, `elem.fire` and the D21 wrapping are untouched.**
This holds for the dialog's buttons too: they render through the unified button
path (`child.render()` → `ImGuiButtonRenderer` → `ButtonRenderer`), so their
`fire` and wrapping are the same as any standalone button's.

**Dialog dismiss / model close (explicit state hand-off).** The Escape/outside-close
handling flips the model via `self._elem.model.close()` and fires the
`mark_removed` observer cascade
([dialog.py:93-107](../../../src/punt_lux/display/renderers/imgui/dialog.py),
[dialog.py:119-122](../../../src/punt_lux/protocol/elements/dialog.py),
[element_abc.py:320-345](../../../src/punt_lux/domain/element_abc.py)). Its
trigger condition is `was_open and not visible`
([dialog.py:90-91](../../../src/punt_lux/display/renderers/imgui/dialog.py)),
where `was_open` is the **prior-frame** latch read from `widget_state` at the top
of the frame ([dialog.py:70](../../../src/punt_lux/display/renderers/imgui/dialog.py))
and `visible` is the **this-frame** result of `begin_popup_modal`. Splitting the
monolith into `begin`/`end` breaks this, because `end(opened)` receives only the
this-frame `opened` (the `begin_popup_modal` visibility) — it **cannot**
reconstruct `was_open` from `opened` alone. The design step: `begin()` reads the
prior-frame `was_open` latch and **stashes it on the renderer instance**
(e.g. `self._was_open`); `end(opened)` reads that stash and runs the
external-close handler when `self._was_open and not opened`. This is safe to
stash on the instance because the renderer is constructed fresh **each frame** —
the skeleton calls `self._renderer_factory(self)` inside every `render()`
([§1](#1-the-render-template-a-fixed-skeleton-over-per-step-hooks)) — so the
stash never leaks across frames. With the hand-off in place the dismiss loop and
Hub re-push are preserved exactly.

### 6. The `_paint_element` flip and dispatch prune

**Flip both call sites** to enter the ABC template for every migrated kind:

```python
def _paint_element(self, elem: Element) -> None:
    if isinstance(elem, ElementABC):
        elem.render()
    else:
        self._element_renderer.render_element(elem)
```

Applied at [server.py:1461-1466](../../../src/punt_lux/display/server.py) and the
duplicated block at
[server.py:1508-1511](../../../src/punt_lux/display/server.py). (`ElementABC` is
`punt_lux.domain.element_abc.Element` — imported under the disambiguating alias
already used in
[scene_inspection.py:75](../../../src/punt_lux/scene_inspection.py).) The two
copies **collapse to one** call to `_paint_element`; `_render_scene_tab`
currently inlines the branch rather than calling `_paint_element` — that
duplication is fixed as part of this change.

Entering the template via `elem.render()` (rather than the current
`self._imgui_renderer_factory(elem).render()`, which called the renderer's paint
directly and bypassed the template) is what makes "migrated ≡ renders via
`Element.render()`" literally true. But that same bypass is load-bearing today,
and deleting it depends on a wiring step the `text`-only path never exercised:
the factory carried **on the element** must be the real Display factory, not the
Hub's raising sentinel. **That rebind is already merged in PR #237** — this
design adds nothing here; it *relies* on the merged rebind and the flip is what
finally reads it.

**The factory rebind is a merged prerequisite (PR #237), not a step this PR
adds.** Today `_paint_element`'s `text` branch paints through the *server's* live
factory — `self._imgui_renderer_factory(elem).render()`
([server.py:1463-1464](../../../src/punt_lux/display/server.py)) — and never
reads `elem._renderer_factory`. The flip deletes that bypass: `elem.render()`
calls `self._renderer_factory(self)`
([element_abc.py:117](../../../src/punt_lux/domain/element_abc.py)) — the factory
carried **on the element**. Off the Display that factory raises. The chain is:

- scene transport is pickle
  ([scene.py:83](../../../src/punt_lux/protocol/messages/scene.py) dumps,
  [scene.py:121-128](../../../src/punt_lux/protocol/messages/scene.py) loads);
- `Element.__reduce__` keeps `_renderer_factory` in the pickled state — it
  excludes only `_observers`
  ([element_abc.py:94](../../../src/punt_lux/domain/element_abc.py));
- the element was built Hub-side with `RaisingRendererFactory`
  ([server.py:233-234](../../../src/punt_lux/display/server.py)), whose `__call__`
  raises `RuntimeError` unconditionally
  ([raising.py:38-45](../../../src/punt_lux/protocol/renderers/raising.py)).

So every inbound ABC element arrives on the Display carrying a factory that
raises on `render()`. **PR #237 closes this**: `Element.bind_renderer_factory`
([element_abc.py:134-145](../../../src/punt_lux/domain/element_abc.py)) assigns
the passed factory to `self._renderer_factory` and **recurses into
`_children()`**, and the inbound `_wrap_abc_elements` pass calls it with the
Display's real factory on every top-level ABC element
([server.py:941-945](../../../src/punt_lux/display/server.py)) before the scene
is stored and painted. The rebound element instances are the *same* objects the
paint loop walks: `_wrap_abc_elements(msg)` runs before
`SceneManager.handle_scene`, which stores `self._scenes[msg.id] = msg` by
reference ([manager.py:195](../../../src/punt_lux/scene/manager.py)), and
`_render_scene_tab` iterates `scene.elements` from that same stored message. The
`RaisingRendererFactory` docstring now describes this correctly
([raising.py:11-13](../../../src/punt_lux/protocol/renderers/raising.py)).

What the rebind guarantees for this design's four exemplars, all covered by the
merged code:

- **text / button / checkbox** (top-level leaves): rebound directly by the
  `_wrap_abc_elements` loop.
- **dialog** (top-level composite): rebound, **and** its child Buttons rebound by
  `bind_renderer_factory`'s `_children()` recursion — the buttons now paint via
  the default `child.render()` recursion (§3), so each must carry the real
  factory. The merged recursion delivers exactly that.

The flip therefore does **not** add or alter the rebind. Nothing in this PR
touches `bind_renderer_factory` or `_wrap_abc_elements`. The one live risk the
flip introduces is that the rebound factory was **dormant** until now — nothing
in production reads `elem._renderer_factory`, because `render()` is not yet the
paint path. The flip makes it the paint path, so the live e2e check (§7) is the
first time the merged rebind is exercised end-to-end through `Element.render()`.
That is what §7's live check verifies; it is a confirmation that a merged
mechanism works when finally driven, not a guard against an unwired step in this
PR.

**Prune the ABC kinds from the legacy dispatch.** Remove `TextElement`,
`ButtonElement`, `CheckboxElement` from `_NATIVE_DISPATCH`
([element_renderer.py:152-168](../../../src/punt_lux/display/element_renderer.py))
and delete the `"dialog"` key from `_RENDERERS`
([element_renderer.py:114](../../../src/punt_lux/display/element_renderer.py)).
After this, `render_element` handles **only** not-yet-migrated legacy kinds
(image, separator, progress, spinner, markdown, slider, combo, input_text,
input_number, radio, color_picker, selectable, and the container/table/plot/
modal/tree/draw families). The per-kind `TextRenderer`/`ButtonRenderer`/
`CheckboxRenderer` instances stay owned by `ElementRenderer`
([element_renderer.py:132-146](../../../src/punt_lux/display/element_renderer.py))
so per-scene widget_state threading is unchanged; the new renderers reach them
through the narrow accessor from §2.

`element_kind_count`
([element_renderer.py:184-187](../../../src/punt_lux/display/element_renderer.py))
counts `len(_RENDERERS) + len(_NATIVE_DISPATCH)`. Removing four entries drops the
count; the migrated kinds must be counted at the factory instead so
introspection reports the same total. This is a real coupling to fix in the same
change, not a follow-up.

**Relationship to Batch 7.** The migration plan puts the paint flip in Batch 7
([README.md:121-128](./README.md)). This change performs the flip for the four
already-ABC kinds now; Batch 7 then shrinks to deleting whatever remains of the
legacy dispatch once the remaining kinds migrate.

### 7. Verification plan

Docs-first: this design ships no code. When implementation is dispatched, the
worker must verify all three of the following, and — per the operator's explicit
instruction — **all verification runs and is operator-confirmed BEFORE the PR
opens**, not after:

1. **Snapshot parity (byte-identical).** For a scene containing one of each of
   the four kinds, capture the rendered element tree / introspection snapshot
   before and after the change; they must be identical. Protocol roundtrip tests
   for the four kinds must be unchanged.
2. **`render_path` stays `"abc"`.** `inspect_scene` must report
   `render_path == "abc"` for all four kinds. This holds trivially — the signal
   is computed from `isinstance(element, ElementABC)`
   ([scene_inspection.py:75](../../../src/punt_lux/scene_inspection.py)) and the
   change does not alter element types — but it must be asserted so a regression
   in classification is caught.

   **Neither check #1 nor check #2 calls `Element.render()`.** The snapshot is
   read from introspection state and the `render_path` from `isinstance` — both
   sidestep the paint path entirely. Therefore **neither exercises the merged
   factory rebind from §6**: an element whose `_renderer_factory` was somehow not
   the real Display factory still snapshots correctly and still reports
   `render_path == "abc"`, yet would raise `RuntimeError` the instant it is
   painted. The rebind is merged (PR #237) and runs on every inbound scene, but
   until this flip nothing in production reads the rebound factory. The **live
   e2e check (#3) is therefore the first time the merged rebind is driven through
   `Element.render()`** — and any leak of a `RaisingRendererFactory` surfaces as
   a total render crash, not a subtle visual regression. The flip must be
   verified live, per kind, including the dialog's recursed child Buttons.
3. **LIVE interactivity re-confirmed (the part snapshot parity cannot cover).**
   Through the real entry points, with `list_recent_events` / `list_errors`
   capture and operator confirmation:
   - **Dialog ask-user loop:** render a dialog, dismiss it (button *and*
     Escape), confirm the model closed and the Hub saw exactly one dismissal,
     the window did not orphan.
   - **Checkbox toggle:** toggle across a scene switch, confirm the value reads
     back from the *correct* scene's widget_state (guards the staleness bug in
     §5).
   - **Button click fire-once-on-Hub:** click, confirm exactly one
     `RemoteEventHandlerInvocation` reached the Hub and the real handler ran
     once (guards D21).

Per [DoD item 3](../../../CLAUDE.md) and the migration verify-as-you-go process
([README.md:99-111](./README.md)), `make check` passing is necessary but not
sufficient — the interactive loops must be driven live and operator-confirmed,
and that confirmation gates the PR opening.

## Sequencing

**One PR for the whole unification** — settled by the operator. All four kinds
move together: the skeleton + four step hooks on the ABC, the `Renderer`
Protocol change, the two new leaf renderers, the `ImGuiDialogRenderer`
begin/paint/end refactor, the retargeted text renderer, the factory dispatch
entries, the `apply_tooltip` extraction, the `_paint_element` flip and call-site
collapse, the `_NATIVE_DISPATCH`/`_RENDERERS` prune, and the `element_kind_count`
fix. This is one rollback-coherent unit: the skeleton change, the renderers, and
the prune only make sense together — a partial state (skeleton changed but no
button renderer, or the flip without the prune) leaves some ABC kinds painting
through the factory and others through the legacy path, which is precisely the
fragmentation this change removes.

## Direction-check

The dialog/composite question (prior D3) and the sequencing question (prior D5)
are **resolved by the operator's ruling** — a fixed skeleton over per-step hooks
with defaults; the dialog is a plain instance overriding only `begin`/`end`; one
PR.

An independent design review found five wiring gaps between the ratified
template shape and the source. Four are **explicit design steps** in this PR; the
first is now a **merged prerequisite** the flip depends on, not work this PR does:

- **Factory rebind (§6) — MERGED in PR #237, not a step this PR adds.** The flip
  to `elem.render()` makes every inbound Display-side ABC element read the
  factory pickled on it, which off-Display is the Hub's `RaisingRendererFactory`.
  `Element.bind_renderer_factory` (recurses into children) plus the inbound
  `_wrap_abc_elements` call that invokes it with the real Display factory are
  both merged. The flip relies on them and touches neither.
- **Text adapter (§2).** After the `_NATIVE_DISPATCH` prune, the text adapter
  cannot delegate to `render_element` (it would paint the unsupported-element
  fallback). Fixed by switching text to the narrow-accessor + `apply_tooltip`
  pattern the button/checkbox adapters use.
- **Dialog latch hand-off (§5).** `end(opened)` cannot reconstruct the
  `was_open and not visible` external-close condition from `opened` alone. Fixed
  by having `begin()` stash the prior-frame `was_open` latch on the per-frame
  renderer instance.
- **Dialog tooltip drop (§3).** The `begin`/`paint`(no-op)/`end` path drops the
  generic tooltip pass; stated as an **intentional** removal (a modal's own
  tooltip is meaningless).
- **`apply_tooltip` guard (§2).** The extracted `apply_tooltip` must keep the
  `is_text_with_inline_tooltip` guard so unstyled-text-with-tooltip does not get
  a double tooltip.

The remaining open items are narrow confirmations:

- **D1 — Renderer delegation model.** The leaf renderers delegate to the per-kind
  renderer instances owned by `ElementRenderer` (which already receive per-scene
  widget_state), mirroring how text delegates today
  ([text.py:45](../../../src/punt_lux/display/renderers/imgui/text.py)) — rather
  than the factory owning the renderers and re-threading per-scene state.
  **Recommend confirm.** Lowest-risk: reuses the exact interactive path with zero
  re-plumbing of widget_state, emit, or D21.
- **D2 — Prune now vs defer to Batch 7.** Remove the four ABC kinds from the
  legacy dispatch in this PR (add the narrow accessor, extract `apply_tooltip`,
  fix `element_kind_count`) rather than leaving them in `_NATIVE_DISPATCH`.
  **Recommend confirm.** The stated goal is that `render_element` handle only
  legacy kinds after this change; deferring the prune would leave the very
  fragmentation this PR removes.
- **D4 — Renderer DI.** The renderers take only `(elem, factory)` and pull the
  per-kind renderer + current widget_state from the factory's `element_renderer`
  property
  ([factory.py:67-75](../../../src/punt_lux/display/renderers/imgui/factory.py)),
  so the factory stays the single mediator and no new constructor wiring crosses
  into `DisplayServer`. **Recommend confirm** rather than adding
  renderer/widget_state parameters to the factory `__call__` signature.

## Backwards compatibility

None at the wire/protocol level — element types, codecs, and the wire format are
untouched. The change is entirely display-side paint routing. `inspect_scene`
output is unchanged for the four kinds (§7 verification #2). The internal API
changes:

- **Additive:** a public accessor + `apply_tooltip` on `ElementRenderer`; two new
  leaf renderers; four overridable step hooks (`_begin`, `_paint_self`,
  `_render_children`, `_end`) on the Element ABC, all with defaults.
- **Merged prerequisite (PR #237), not introduced here:** `bind_renderer_factory`
  on the Element ABC (recurses into children) and the Display-side rebind call in
  the inbound wrap pass. This PR consumes them; it does not add them.
- **Changed (internal only):** the `Renderer` Protocol renames `render()` →
  `paint()` and gives `begin()` a `bool` return / `end()` an `opened` parameter;
  `ImGuiDialogRenderer` is refactored from a monolithic `render()` into
  `begin`/`paint`/`end` and loses its injected `ButtonRenderer`. No wire type,
  codec, or agent-facing surface is affected — `Renderer` is a Display-tier
  structural contract with no serialized form.

There is **no** list-returning `_render_children()` hook (the prior D3 proposal
is withdrawn); `_render_children` is a *step that paints*, with a default that
recurses.

## OO notes

- `Element.render()` stays the never-overridden fixed skeleton (PY-IC-7,
  open-closed): each variable step is an overridable hook with a default, so a
  new component overrides only what it needs and the base never changes. The
  prior template violated open-closed by baking one child-iteration algorithm
  into the base.
- The dialog's every-step-is-a-hook treatment means it is an ordinary component,
  not a special case — the strongest form of "the dialog is unremarkable once
  the template is right."
- The leaf renderers are `@final` classes satisfying the `Renderer` Protocol
  structurally, constructed via `__new__` returning `Self` (PY-CC-1, PY-TS-3),
  mirroring the text renderer.
- `apply_tooltip` moves post-processing behavior onto the class that owns the
  renderers rather than duplicating it per renderer (PY-OO-5, PY-OO-7).
- No new `str`-with-comment or `| None` fields are introduced.
