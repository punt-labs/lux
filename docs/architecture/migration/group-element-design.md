# Migrating `group` onto the Element-ABC / HubDisplay Path — the First Container ("a frame")

**Status:** design + verification plan for operator direction-check. No code.
**Type:** migration design (composite/container; the first container migrated).
**Element:** `group` — a display-only layout container (`rows` / `columns` / `paged`).
**Exemplar copied:** `DialogElement` — the composite already on the ABC path
(`protocol/elements/dialog.py:114`, `display/renderers/imgui/dialog.py:30`).
**Ground truth:** `docs/architecture/target/{target,ui-model,element-contract,introspection-api}.md`,
[DES-039](../../../DESIGN.md) (self-validating elements), [DES-041](../../../DESIGN.md)
(fork, don't mix; order by testability), the render engine merged in PR #239
(`docs/architecture/migration/render-path-unification-design.md`), and the code
cited inline.

`group` is the first **container** in the testability order
([DES-041](../../../DESIGN.md), `README.md:68`). A container comes first because
it is the frame that lets us compose and test all-ABC scenes: until one exists,
every migrated primitive has to be nested inside a legacy container to be seen,
which is precisely the mix DES-041 forbids. Migrating `group` gives the fork an
all-ABC root to hang primitives on.

This goes to the operator for a direction-check **before** any implementation.
The decisions in §8 are the direction-check items; the mixed-group codec
decision (§4) is the top one.

---

## 1. Understanding restated (in the designer's words)

### 1.1 The target model, applied to a container

Clients submit UI to the Hub; the Hub decodes it into typed UI objects and
installs them in `HubDisplay`, the authoritative store for state, ownership, and
dispatch; the Display holds a full replica used only for rendering and input
capture; after a change the Hub re-sends the whole affected UI and the Display
replaces its copy (`target.md:24`–`:39`). The load-bearing boundary rule: **UI
state crosses IPC; render calls do not** (`target.md:63`–`:71`).

A `group` is a **composite/layout element** — the "composite/layout elements"
family whose role is "structure and composition" and whose handler expectation is
"may own child behavior and observer cascades" (`element-contract.md:80`,
`:246`). But `group` itself is **display-only**: it owns children and arranges
them, and that is all. It fires no events, has no dismiss verb, no `was_open`
latch, and no private model. It is **`Dialog` minus the interactive machinery,
plus a layout**.

### 1.2 What crosses the boundary, what is authoritative, what is local

For a migrated ABC `group` specifically:

- **Crosses the Hub→Display boundary:** the serialized group object *and its ABC
  children*. A top-level ABC element crosses as a single base64-encoded pickle
  blob (`scene.py:78`–`:84`); `pickle` recurses the object graph, so the group's
  ABC children (and their handler registrations) travel inside the one blob.
  `Element.__reduce__` (`element_abc.py:73`) keeps `_renderer_factory` and
  `_handlers` in the pickled state and drops only `_observers`. This is UI state.
- **Hub-authoritative:** the group's structure and layout — `id`, `layout`, the
  ordered `children`, and (for paged) `pages` / `page_source`. The Hub owns it;
  the Display never mutates it.
- **Display-local:** the ImGui layout calls (`begin_horizontal` / `columns` /
  child regions), and — for `paged` only — the **current page index**. The page
  index is ephemeral *view* state, held in the Display's `WidgetState`, never
  re-pushed to the Hub. This mirrors [DES-041](../../../DESIGN.md) decision 3
  (ephemeral view state stays Display-local; authoritative state routes to the
  Hub) — a group has no authoritative interaction, so *nothing* routes back.

Render calls do not cross the wire: `Element.render()` runs on the Display
against its replica, resolving the group's ImGui adapter through the factory
(`element_abc.py:100`, `imgui/factory.py:92`).

### 1.3 Why `group` needs the composite surface but NOT the interactive surface

The Element ABC (`element_abc.py:43`) carries render, children, validation,
handler, wrap, and observer surfaces. `group` uses the composite subset and
inherits — but never exercises — the interactive subset:

| ABC member | Group needs it? | Why |
|---|---|---|
| `id` (abstract, `element_abc.py:95`) | **Yes** | Every element has a stable scene identity (`element-contract.md:44`); `HubDisplay` indexes by it. |
| `render()` template (`element_abc.py:100`) | **Yes, inherited** | Never overridden. Drives `_begin` → `_paint_self` → `_render_children` → `_end`. |
| `_children()` (`element_abc.py:142`) | **Yes, overridden** | Returns the group's children so the default recursion paints them (Dialog does the same, `dialog.py:198`). |
| `_begin` / `_end` (`element_abc.py:117`, `:136`) | **Yes** | Open/close the ImGui layout surface (see §3). Dialog overrides these to open/close its modal. |
| `_paint_self` (`element_abc.py:124`) | **No-op** | A pure container's body *is* its children; its renderer's `paint` is a no-op (`dialog.py:84`). |
| `child_elements()` (`element_abc.py:169`) | **Yes, overridden** | The validation-walk bridge. Overridden so hidden `pages` elements are still validated (§2.3). |
| `validate()` (`element_abc.py:160`) | **Yes, overridden** | Component-appropriate structural check for a group (§2.2). |
| `bind_renderer_factory` (`element_abc.py:147`) | **Yes, inherited** | Recurses `_children()` to rebind the Display factory onto the group and its subtree. |
| handler registry / `fire` (via `EventHandlerHost`) | **Present, unused** | A group registers no handlers and fires no events. The empty registry costs nothing. |
| `wrap_handlers_for_remote` (D21) | **Present, transparent** | Recurses `_children()`; a group declares **no** `RemoteDispatchSpec`, so it wraps nothing of its own — but it correctly forwards the recursion so an interactive *child* (a button in the group) is wrapped. |
| `mark_removed` / observers (`element_abc.py:198`, `:211`) | **Present, unused** | Used by composites that cascade child removal; a group has no dismiss, so it never drives it. |

The rule in one line: **a display-only container needs the ABC's identity,
render template, children hook, layout begin/end, validation, and factory
rebind; it inherits — but does not exercise — the model, dismiss, latch, and
observer-cascade machinery that makes `Dialog` interactive.**

### 1.4 The analogy to `Dialog`, made explicit

`DialogElement` (`dialog.py:114`) is the proof the composite shape works on the
ABC path:

- It subclasses `Element` with keyword-only `__new__` and sentinel
  `renderer_factory` / `emit` defaults (`dialog.py:130`).
- It implements the one abstract member `id` (`dialog.py:153`).
- It overrides `_children()` to expose its child controllers (`dialog.py:198`)
  and renders them via the **default** `_render_children` recursion.
- It keeps `to_dict` / `from_dict` delegators so the structural
  `domain.element.Element` Protocol still holds (`dialog.py:231`).
- It implements `resolved_props()` for introspection (`dialog.py:259`).

`GroupElement` is the same composite shape, minus four things Dialog has and a
group must not: the private `DialogModel`, the `on_dismiss` → `mark_removed`
binding (`dialog.py:148`), the `visible`/`confirmed` state, and the renderer's
`was_open` latch + Escape-dismiss cascade (`imgui/dialog.py:95`). In their place
`group` adds one thing Dialog does not have: a `layout` discriminator that
selects how `_begin`/`_end` arrange the children. That is the entire delta:
**Dialog minus interaction, plus layout.**

---

## 2. The ABC `GroupElement` design

### 2.1 Fields, and the OO rules the field set observes

`GroupElement` carries: `id`, `children` (a tuple of ABC `Element`), `layout`
(`Literal["rows", "columns", "paged"]`), the paged params `pages`
(a tuple of tuples of ABC `Element`) and `page_source` (`str`, `""` = none),
`tooltip`, and the `kind` discriminator.

**PY-OO rules cited, with the layout field's BEFORE/AFTER:**

The legacy field is already a `Literal`, so the layout field is not itself a
`str`-with-comment violation — but the legacy dataclass exposes it (and every
other field) as a **public mutable attribute** (`layout.py:35`–`:41`), which
`PY-EN-1` forbids. The migration moves data behind read-only properties and
puts behavior on the class (`PY-OO-5`):

**BEFORE** (`layout.py:23`–`:41`, procedural dataclass, public fields):

```python
@dataclass(frozen=True, slots=True)
class GroupElement:
    id: str
    kind: Literal["group"] = "group"
    layout: Literal["rows", "columns", "paged"] = "rows"
    children: list[Any] = field(default_factory=lambda: list[Any]())
    pages: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    page_source: str | None = None  # id of ComboElement driving page index
    tooltip: str | None = None
```

**AFTER** (ABC subclass, private state + read-only property, behavior on the class):

```python
class GroupElement(Element):
    _id: str
    _layout: Literal["rows", "columns", "paged"]
    _children_tuple: tuple[Element, ...]
    _pages: tuple[tuple[Element, ...], ...]
    _page_source: str
    _tooltip: str | None
    _kind: Literal["group"]

    @property
    def layout(self) -> Literal["rows", "columns", "paged"]:
        """Return how the group arranges its children."""
        return self._layout
```

Two `PY-TS-14` / `PY-OO-5` improvements ride along, as the ratchet expects when
touching a file:

- `page_source: str | None` → `page_source: str` with `""` as the discriminated
  "no page-source" state (the same move `TextElement.color` made,
  `text.py:104`–`:107`). The encoder omits it when `""`, so the wire shape is
  unchanged.
- `children: list[Any]` → `children: tuple[Element, ...]` — a group holds ABC
  `Element` objects, not `Any`. The `Any` was the type system giving up on the
  heterogeneous legacy union; on the ABC fork every child is an `Element`.

`tooltip: str | None` **stays** — absence is the documented contract for an
optional tooltip (`PY-TS-14` OK, as `text.py:100`).

### 2.2 The render hooks it overrides

The render engine (PR #239) makes `Element.render()` the paint path
(`element_abc.py:100`). `GroupElement` overrides the hooks a container needs and
inherits the rest:

- **`_children()`** → returns the group's children tuple (the render-visible set;
  for a `rows`/`columns` group this is every child). Drives the default child
  recursion, the D21 wrap recursion, `bind_renderer_factory` recursion, and the
  validation walk.
- **`_begin(renderer)`** → **inherited default** (`element_abc.py:117`), which
  delegates to `renderer.begin()`. The layout choice lives in the *renderer*
  (§3): `ImGuiGroupRenderer.begin()` reads `elem.layout` and opens the matching
  ImGui surface — `begin_vertical` for `rows`, `begin_horizontal` for `columns`
  (imgui-bundle stack layout). It returns `True` (the surface always "opens").
- **`_paint_self(renderer)`** → **inherited default**, which calls
  `renderer.paint()` — a **no-op** for a group, exactly as
  `ImGuiDialogRenderer.paint` is a no-op (`imgui/dialog.py:84`), because a
  group's only body is its children.
- **`_render_children(renderer)`** → **inherited default recursion**
  (`element_abc.py:129`): `for child in self._children(): child.render()`. Each
  child paints through its own factory adapter, bracketed by the layout surface
  `begin`/`end` opened around it.
- **`_end(renderer, opened)`** → **inherited default**, which calls
  `renderer.end(opened=...)`; `ImGuiGroupRenderer.end` closes whatever `begin`
  opened (`end_vertical` / `end_horizontal`).

For `rows` and `columns`, the ABC group is therefore a **plain box**: it
overrides only `_children()`, and the layout is entirely a property of its
renderer's `begin`/`end`. This is exactly the "future group with no gating"
the render-engine design named as the plain-box case
(`render-path-unification-design.md` §1). The `paged` layout is more than a
plain box; it is treated separately in §3.3 and §8-Q3.

Note on `columns`: the legacy renderer arranges columns by injecting
`imgui.same_line()` *between* children (`container_renderer.py:88`–`:90`), which
cannot be expressed in a `begin`/`end` bracket around the default recursion. The
ABC renderer instead uses imgui-bundle's stack-layout API
(`begin_horizontal` / `end_horizontal`), which lays contained widgets out
horizontally with no inter-child call — a clean fit for the default recursion.
This is a **rendering refinement** (new render code the fork writes anyway), not
a wire change; §8-Q2 asks the operator to ratify it versus replicating the
`same_line` interleave through a widened renderer protocol.

### 2.3 `validate()` — component-appropriate, and the pages coverage rule

Per [DES-039](../../../DESIGN.md), validation rides with the migration. A group
is a **container**, so what it validates about *itself* is structural: its
`page_source`, when set, must name one of its own children (a dangling
`page_source` yields a paged group whose combo drives nothing — a silent
no-op the agent should see). The bulk of a group's validity is its children's
validity, and that is covered not by the group's `validate()` but by the walk
recursing into the group's children.

The `validate()` contract for `GroupElement`:

```python
def validate(self) -> tuple[ValidationError, ...]:
    """Return this group's own structural errors.

    A group with layout='paged' and a non-empty page_source must name a
    child id that exists; a dangling page_source is a silent no-op. Child
    validity is collected by the hierarchy walk, not here.
    """
```

The **hierarchy coverage** is the load-bearing part. The walk recurses every
container's `child_elements()` and accumulates *all* errors, never fail-fast
(`element-contract.md:290`–`:303`, DES-039 part 3). `GroupElement` must expose
**every** installed descendant — including elements on non-active `pages`, which
are installed but not currently drawn — so an invalid element hidden on page 2
is still caught. The legacy group already does this (`layout.py:43`–`:51`). The
ABC group therefore **overrides `child_elements()`** (rather than letting it
bridge to `_children()`):

```python
def child_elements(self) -> tuple[Element, ...]:
    """Return children AND every paged element for the validation walk.

    Distinct from _children() (the render-visible set): an invalid element
    on a non-active page is installed and must be validated, even though it
    is not currently painted.
    """
    paged = tuple(e for page in self._pages for e in page)
    return (*self._children_tuple, *paged)
```

The DES-039 **structural guard test** (derives the container set from the
`Element` union and fails if a new container omits `child_elements()`,
DES-039 supporting types) already protects this: the migrated ABC `GroupElement`
joins the union and must satisfy the guard. A group that returned only
`_children()` and dropped its pages would fail the guard's nested-coverage
assertion.

### 2.4 The ImGui adapter — `ImGuiGroupRenderer`

Mirrors `ImGuiDialogRenderer` (`imgui/dialog.py:30`): a `@final` class satisfying
the `begin` / `paint` / `end` `Renderer` Protocol, constructed via `__new__`
returning `Self`, holding `(elem, factory)`. It reuses the container-layout logic
that today lives in `ContainerRenderer.render_group` (`container_renderer.py:78`)
— but ported onto begin/end, not copied verbatim:

- `begin()` — read `elem.layout`; `rows` → `imgui.begin_vertical(elem.id)`,
  `columns` → `imgui.begin_horizontal(elem.id)`. Return `True`.
- `paint()` — no-op (the body is the children).
- `end(opened)` — close the matching stack-layout surface.

The per-scene `WidgetState` (needed only by `paged`) is read from
`factory.element_renderer.widget_state` at `begin`/`end` time, exactly as the
dialog reads its latches from the *current* scene's state
(`render-path-unification-design.md` §5) — never from the factory's
construction-time copy, which would be a silent cross-scene bug.

---

## 3. Rendering `rows` / `columns` / `paged`

### 3.1 `rows`

Vertical stack. `ImGuiGroupRenderer.begin` opens `begin_vertical`, the default
recursion paints children top-to-bottom, `end` closes it. `GroupElement`
overrides only `_children()`. This is the minimal plain-box case and the one that
proves the container frame works.

### 3.2 `columns`

Horizontal row. `begin` opens `begin_horizontal`, the default recursion paints
children left-to-right (stack layout flows them automatically), `end` closes it.
Same group override surface as `rows`; the only difference is the ImGui primitive
the renderer selects from `elem.layout`.

### 3.3 `paged` — the one layout that is not a plain box

A paged group draws a nav row (`<< Prev`, an inline page-source combo, `Next >>`)
plus the always-visible children, then the active page's content
(`container_renderer.py:102`–`:131`). Two properties make it genuinely more than
`begin`/`end`:

1. The **page index** is Display-local `WidgetState` read and mutated by the nav
   buttons — not a fixed bracket around the children.
2. The children rendered depend on that index — the default "render every child"
   recursion is wrong; only the active page's elements draw.

So `paged` needs `_children()` to include the pages (for wrap / rebind /
validation coverage) but a **`_render_children` override** that draws nav +
always-visible children + active page, delegating the ImGui nav widgets and the
page-index `WidgetState` access to the renderer (the domain `GroupElement` must
not call ImGui — `PY-IC-8`, core never imports presentation). That override needs
renderer methods beyond `begin`/`paint`/`end`, which either widens the shared
`Renderer` Protocol or gives the group a container-renderer sub-protocol.

Because `paged` carries this distinct concern (Display-local state, nav widgets,
a protocol widening) and because interactive children on non-active pages raise a
wrap/rebind coverage question (`_children()` must include them, but a page-2
button's factory rebind and D21 wrap happen at receive time whether or not the
page is drawn), **the recommendation is to migrate `rows`/`columns` in the first
container PR and split `paged` into an immediate follow-up PR within the same
group-migration epic** (§8-Q3). One container at a time, testability-first
([DES-041](../../../DESIGN.md)); `rows`/`columns` is the composable frame the rest
of the fork needs, and `paged` is a self-contained increment on top of it.

---

## 4. THE KEY DESIGN QUESTION — the codec decides ABC-vs-legacy by all-ABC-ness

The ABC group's `_render_children` calls `child.render()`, and only ABC children
have `render()`. So **an ABC `GroupElement` can hold only ABC children.** Most
child kinds (`image`, `slider`, `table`, …) are still legacy dataclasses today.
Two ways to reconcile this:

- **(a) Fork by all-ABC-ness.** The codec decodes a `group` to the ABC
  `GroupElement` **only when every element in its subtree is a migrated ABC
  kind**; otherwise it decodes the legacy (renamed) group. All-ABC composites are
  the fork.
- **(b) Bridge.** The ABC group holds legacy children and routes them back
  through the legacy renderer. This is exactly the legacy+ABC coexistence
  machinery [DES-041](../../../DESIGN.md) **forbids** ("fork, don't mix; don't
  build coexistence machinery"). **Rejected.**

**Recommendation: (a), per fork-don't-mix.** Specification follows.

### 4.1 How the decode decides

`JsonElementFactory.element_from_dict` (`element_factory.py:169`) is the
agent-facing top-level decoder. Today it routes a kind in `_ABC_KINDS`
(`element_factory.py:49`) to the ABC decoders and everything else to the legacy
`ElementCodec`. `group` becomes **conditionally ABC**: for `kind == "group"`, run
an all-ABC gate over the wire subtree.

```python
_MIGRATED_ABC_KINDS = frozenset({"text", "button", "checkbox", "dialog", "group"})

def _group_is_all_abc(self, raw: Mapping[str, object]) -> bool:
    """True iff every element in the group's subtree is a migrated ABC kind."""
    # Walk raw["children"] and raw["pages"] recursively; every element's
    # "kind" must be in _MIGRATED_ABC_KINDS. Any legacy kind anywhere -> False.
```

- **All-ABC** → decode to `GroupElement` via `JsonGroupDecoder`, which recurses
  each child through the factory's ABC decode (`element_factory.py:116`),
  producing ABC children. A nested `group` in an all-ABC subtree is itself
  all-ABC, so the recursion stays consistent (the nested group also passes the
  gate and decodes ABC).
- **Any legacy descendant** → decode to the renamed `LegacyGroupElement` via the
  `ElementCodec` path (`element_factory.py:190`), which builds legacy children.

### 4.2 What happens to a mixed group

A group is "mixed" when its subtree contains at least one not-yet-migrated
(legacy) kind. It decodes to `LegacyGroupElement`. Two sub-cases matter:

1. **ABC *leaves* inside a legacy group** (e.g. a `text` child alongside an
   `image`). This already happens today and already works: the legacy group's
   `from_dict` recurses children through `container_dispatch.dispatch.from_dict`
   (= `element_from_dict`, `layout.py:71`), which decodes `text` to an ABC
   `TextElement` (`text`/`button`/`checkbox`/`dialog` have no legacy form). That
   ABC leaf paints through the **nested-in-legacy** path — `render_element` →
   `_dispatch_native` — which the render engine **intentionally left in place**
   during the mixed period (`render-path-unification-design.md` §6, prune
   deferred to fork completion). This coexistence is not new machinery; it is the
   legacy path staying alive while still in use. **Preserved unchanged.**
2. **An ABC *container* inside a legacy group** — an ABC `GroupElement` nested in
   a `LegacyGroupElement`. This is the **new hazard** the migration must not
   create. The legacy `ContainerRenderer.render_group` recurses children via
   `render_element` (`container_renderer.py:87`–`:90`); an ABC `GroupElement` is
   in neither `_NATIVE_DISPATCH` (leaves) nor `_RENDERERS`, so it would hit the
   `[unsupported element]` fallback — a visible regression. **This must be
   structurally impossible.** The all-ABC *subtree* gate guarantees it at the top
   decision (a legacy descendant forces the whole subtree legacy), but a legacy
   group must also decode its **nested groups as legacy**, even when a sibling
   subtree happens to be all-ABC. The specification: `LegacyGroupElement`'s child
   recursion routes a nested `kind == "group"` to `LegacyGroupElement`
   unconditionally (a legacy-forcing recursion), instead of re-running the ABC
   gate per nested group. This keeps every group in a legacy subtree legacy and
   is **not a bridge** — it does not make an ABC container hold legacy children;
   it keeps the legacy container fully legacy. §8-Q1 asks the operator to ratify
   this rule; it is the subtle half of decision (a).

### 4.3 How it composes with the render engine's nested-in-legacy path

The render engine already services "a legacy group holding ABC leaves"
(§4.2 case 1) via `ContainerRenderer` + the restored `_dispatch_native`
(`render-path-unification-design.md` §6). This migration adds the **top-level
all-ABC group** path: a top-level ABC `GroupElement` paints through
`Element.render()` → `ImGuiGroupRenderer`, and its ABC children paint through
their own adapters via the default recursion. The two paths do not interleave —
that is the fork. The mixed case (case 2) is made impossible by construction, not
serviced.

### 4.4 What crosses the Hub/Display boundary (stated plainly)

- A **top-level all-ABC `GroupElement`** crosses as one `_pickled` blob
  (`scene.py:78`–`:84`); its ABC children replicate inside that blob (pickle
  recurses), handlers preserved. On the Display, `_wrap_abc_elements` calls
  `bind_renderer_factory`, which recurses `_children()` to rebind the real
  factory onto the group and every descendant
  (`element_abc.py:147`, `render-path-unification-design.md` §6). **Render calls
  stay Display-local.**
- A **`LegacyGroupElement`** crosses as a plain dict via `_element_to_dict`
  (`scene.py:86`, `__init__.py:183`). (Its ABC *leaves* cross as JSON inside that
  dict and lose handler registrations — a known coexistence limitation the fork
  dissolves by migrating each kind, out of scope here.)

---

## 5. Fork, don't mix — the rename and the codec routing

Per [DES-041](../../../DESIGN.md) decision 2, **the new ABC class takes the
canonical name `GroupElement`; the legacy dataclass is renamed out of the way**
to `LegacyGroupElement`.

- **`protocol/elements/layout.py`** — rename `GroupElement` →
  `LegacyGroupElement` (class, `__all__` at `layout.py:12`, and `register_codecs`
  at `layout.py:379`). The legacy class keeps its dataclass shape and its
  `child_elements()` (`layout.py:43`) for the validation walk. Its child
  recursion is amended to force nested groups legacy (§4.2 case 2).
- **`protocol/elements/group.py`** (new) — the canonical ABC `GroupElement`.
- **`protocol/elements/__init__.py`** — the `Element` union (`__init__.py:130`)
  keeps a `GroupElement` member (now the ABC class) and adds `LegacyGroupElement`
  for the mixed path; `_element_to_dict` (`__init__.py:183`) adds ABC
  `GroupElement` to the per-kind-encoder isinstance tuple.
- **`protocol/element_factory.py`** — the all-ABC gate + a `_group_decoder`
  field constructed in `__new__`; `decode()` and `element_from_dict()` route
  `group` per §4.1.
- **`protocol/encoder_factory.py`** — add
  `isinstance(elem, GroupElement) → JsonGroupEncoder().encode(elem)`
  (`encoder_factory.py` dispatch chain).
- **`display/renderers/imgui/factory.py`** — add
  `(GroupElement, ImGuiGroupRenderer)` to `_DISPATCH` (`imgui/factory.py:45`).
- **`display/renderers/container_renderer.py`** — the `render_group` cast
  (`container_renderer.py:80`) now names `LegacyGroupElement`.

The legacy and ABC `group` codecs are two live decode/encode paths **selected by
the all-ABC gate**, not two paths for one representation — the gate makes the
choice deterministic, so no wire dict is ambiguous.

---

## 6. Introspection — `render_path` flips to `"abc"`, ships in the same PR

The introspection primitive is already shipped: `scene_inspection.py` classifies
each element `render_path = "abc" if isinstance(element, ElementABC) else
"legacy"` (`scene_inspection.py:75`) and reads `resolved_props()` for `Inspectable`
elements (`scene_inspection.py:76`). A migrated ABC `GroupElement`:

- **flips `render_path` to `"abc"`** automatically (it is an `ElementABC`
  subclass); a `LegacyGroupElement` reads `"legacy"`.
- **reads back its resolved props** — `GroupElement` implements
  `Inspectable.resolved_props()` (as `DialogElement` does, `dialog.py:259`):

```python
def resolved_props(self) -> Mapping[str, object]:
    return {
        "layout": self._layout,
        "children": [c.id for c in self._children_tuple],
        "pages": [[e.id for e in page] for page in self._pages],
        "page_source": self._page_source,
        "tooltip": self._tooltip,
    }
```

**The introspection extension that ships in this PR** is recursion into container
children. `SceneInspection.from_scene` currently emits one `element_paths` record
per *top-level* element (`scene_inspection.py:140`–`:151`). For a container
migration, a test must verify that the group's **children** also flipped — a
top-level `"abc"` group tells you nothing about a nested child's path. The
extension: `SceneInspection` walks `child_elements()` recursively so every
descendant gets an `element_paths` record. This is the introspection "scaling
with functionality" the process requires (`README.md:111`–`:119`) and is the
first migration where a container makes it necessary.

---

## 7. Test plan (Levels 1–6 per `tests/CLAUDE.md`)

Write expected values first; drive the real entry point; assert against live
state. Levels 1–2 are unit roundtrips; Levels 3–5 exercise the real boundary and
must never stub it (`tests/CLAUDE.md:48`–`:127`).

1. **Level 1 — serialization roundtrip.** Build an all-ABC `group` (rows and
   columns) → `to_dict` → `from_dict` → assert equal. Include a group holding a
   `text` + `button` child (proves ABC child recursion) and an empty group.
2. **Level 2 — wire roundtrip (ABC pickled path).** Put the group in a
   `SceneMessage` → serialize → deserialize → assert equal. Assert the group
   crossed as a `_pickled` entry (`scene.py:78`), and that its children survived
   inside the blob with handlers intact — the asymmetry that let `checkbox` slip
   through (`tests/CLAUDE.md:87`–`:95`).
3. **Level 3 — Hub/Display crossing.** Install the all-ABC group into `HubDisplay`
   → push to the Display → assert the Display holds an equal replica, and that
   `bind_renderer_factory` rebound the real factory onto the group *and its
   children* (a child `render()` does not raise the sentinel `RuntimeError`).
4. **Self-validation (DES-039).**
   - **valid** → `validate()` returns `()` for the group; the tree renders.
   - **malformed** → a paged group with a `page_source` naming no child returns
     the component-appropriate error; driven through `show()`, assert the client
     is never called (`client.show.assert_not_called()`).
   - **nested-malformed** → an invalid element (e.g. a ragged `table`, or an
     invalid element on a **non-active page**) inside the group is collected by
     the walk; assert via `show()` that the group's `child_elements()` exposed it
     and the tree is not rendered.
   - **structural guard** → the DES-039 container-guard test still passes with
     ABC `GroupElement` in the union (it exposes `child_elements()`).
5. **Level 5 — introspection (`render_path == "abc"`).** Query `inspect_scene`;
   assert the group's record reads `render_path == "abc"` and `resolved_props`
   reads back `layout` + child ids; assert the **child** records also read
   `"abc"` (the recursion extension, §6). Capture the same assertion returning
   `"legacy"` for a mixed group on the same input shape, so the fork is explicit.
   (Do not assert Hub authority from the display side — `tests/CLAUDE.md:125`.)
6. **Level 6 — live visual confirmation.** `make restart`; render an all-ABC
   group in `rows` and in `columns` through the real `show` tool; confirm by eye
   (and `screenshot`) the children arrange vertically / horizontally; capture
   `inspect_scene` + `list_recent_events`; operator confirms observed layout
   matches expected before the group is called done.

`make check` (OO score, mypy, pyright, ruff, radon, pylint) must pass; stage
`.oo-baseline.json` + `.oo-audit.jsonl` in the same commit.

---

## 8. The write set

The design produces this write set — created/renamed/split by structure, not
predetermined to existing files. `PY-OO-2` (≤ 300 lines, ≤ 3 classes/module) is
noted where a split is planned.

**New:**

- `src/punt_lux/protocol/elements/group.py` — ABC `GroupElement` (one class).
- `src/punt_lux/protocol/elements/group_codec.py` — `JsonGroupEncoder` +
  `JsonGroupDecoder` incl. the all-ABC gate + recursion (two classes; if the gate
  walk grows, extract a small `GroupSubtree` value class — still ≤ 3 classes).
- `src/punt_lux/display/renderers/imgui/group.py` — `ImGuiGroupRenderer`
  (begin/paint/end). **PY-OO-2 split-plan:** if `paged` (its follow-up PR) pushes
  this module over 300 lines or a third class, extract the paged nav/page-index
  logic into `imgui/group_paged.py`.
- `tests/test_group_element.py` — Levels 1–5 + validation; scene-inspection
  recursion test.

**Renamed / amended:**

- `src/punt_lux/protocol/elements/layout.py` — `GroupElement` →
  `LegacyGroupElement` (class, `__all__`, `register_codecs`); legacy child
  recursion forces nested groups legacy (§4.2).
- `src/punt_lux/protocol/elements/__init__.py` — `Element` union +
  `_element_to_dict` routing.
- `src/punt_lux/protocol/element_factory.py` — the all-ABC gate, `_group_decoder`,
  `decode()` / `element_from_dict()` routing.
- `src/punt_lux/protocol/encoder_factory.py` — `GroupElement` encode entry.
- `src/punt_lux/display/renderers/imgui/factory.py` — `_DISPATCH` entry.
- `src/punt_lux/display/renderers/container_renderer.py` — cast to
  `LegacyGroupElement`.
- `src/punt_lux/scene_inspection.py` — `element_paths` recursion into container
  children.
- `.oo-baseline.json`, `.oo-audit.jsonl` — staged with the commit.

The `GroupElement` module follows the `Dialog` split precedent — element and
codec in separate modules (`dialog.py` + `dialog_codec.py`) — so no module
carries both the class and its codec, keeping each within `PY-OO-2`.

---

## 9. Direction-check questions for the operator

Concrete decisions, each with a recommendation. No implementation dispatches
until they are ruled on.

**Q1 — The mixed-group codec rule (THE top decision, §4).** Recommend **(a) fork
by all-ABC-ness**: a `group` decodes to the ABC `GroupElement` only when its
entire subtree is migrated-ABC, else to the renamed `LegacyGroupElement`; and a
legacy group forces its **nested groups** legacy (so an ABC container can never be
nested in a legacy container — the `[unsupported element]` regression is
structurally impossible). Reject **(b) bridge** per DES-041. **Decision needed:**
ratify (a) including the legacy-forcing-nested-group rule, or direct otherwise.

**Q2 — Columns via stack layout vs. `same_line` interleave (§2.2).** Recommend the
ABC renderer use imgui-bundle's `begin_horizontal`/`begin_vertical`, so
`_render_children` stays the pure default recursion and no inter-child call is
needed. The alternative — replicate the legacy `same_line` interleave
(`container_renderer.py:88`) — forces a `_render_children` override and a widened
renderer protocol for the plain-box case. **Decision needed:** ratify stack layout
(a small rendering refinement the fork writes anyway), or require exact
`same_line` parity.

**Q3 — Scope: `rows`/`columns` first, `paged` as an immediate follow-up (§3.3).**
Recommend the first container PR migrates `rows`/`columns` (pure plain-box:
override only `_children()`, layout in the renderer's begin/end) and a second PR
in the same epic adds `paged` (Display-local page index, nav widgets, a
`_render_children` override, pages in `_children()` for wrap/rebind/validation
coverage). One container concern at a time, testability-first
([DES-041](../../../DESIGN.md)). **Decision needed:** confirm the split, or require
`paged` in the first PR.

**Q4 — `page_source: str | None` → `str` with `""` sentinel (§2.1).** Recommend the
`PY-TS-14`/`PY-OO-5` tightening (discriminated "no page-source" state, encoder
omits it when `""`; identical wire bytes), matching `TextElement.color`
(`text.py:104`). **Decision needed:** none if accepted; flag if the operator wants
the field to stay `str | None`.

---

## 10. Report status

Design + verification plan only. No production code, tests, or introspection
implementation written. Saved to
`docs/architecture/migration/group-element-design.md`.
