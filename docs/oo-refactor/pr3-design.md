# PR 3 Design — io-model Foundation + Text Proving Consumer

> **⚠️ SUPERSEDED by PR #189 (v2 plan revision, merged 2026-05-23).**
>
> This design doc was produced against the **v1 PR 3 scope** ("io-model
> foundation + Text single proving consumer"). The v2 PR 3 scope adopted
> in PR #189 differs substantively: PR 3 now ships **Text outbound
> end-to-end** including Connection abstraction + bare subprocess +
> DisplayClient + per-kind Encoder. A fresh design mission will dispatch
> against the v2 scope.
>
> **Partially salvageable for the v2 design mission as reference input:**
> §§1–7 (module layout, class signatures, TextElement on ABC,
> JsonTextDecoder, ImGuiTextRenderer, RecordingRenderer/NullRenderer,
> ImGuiRendererFactory), §10 (WidgetValueProvider deletion plan),
> §13 (construction-path ergonomics).
>
> **Deprecated by v2:** §§8–9 (wire-layer + display-server bypass with
> NullRendererFactory bake-in). v2 ships per-kind Encoder + Connection
> abstraction from day one; the bypass workaround does not exist.
>
> **Architecture note:** the canonical target architecture now lives under
> `docs/architecture/target/`. This document references the older
> `io-model.md` design; the archived version now lives at
> `docs/architecture/archive/io-model.md`.

**Bead:** `lux-c2c8` (description updated to v2 scope 2026-05-23)
**Author:** Raymond H (`rmh`) — Python implementation specialist
**Evaluator:** Guido v. R. (`gvr`)
**Mission:** `m-2026-05-23-003` (closed as ESCALATED, 2026-05-23, after PR #189)
**Status:** Round 1 design under v1 scope — **superseded** by the v2 plan adopted in PR #189. Retained for partial reference only; the later v2 design work replaced it.

## 0. What this document is (and isn't)

This is a **design doc**. It proposes the file layout, class signatures,
constructor shapes, internal commit sequence, and test plan that realize the
io-model architecture committed in `docs/architecture/archive/io-model.md` and
`DESIGN.md` DES-031 / DES-032 / DES-033 for the PR 3 scope (io-model
infrastructure + `TextElement` migration).

It is **not** an architectural debate. The Element-ABC-with-template-method,
per-surface RendererFactory family, per-format DecoderFactory family,
module-level Renderers / Decoders registries, and tier-local Element
representation are settled by the cited authorities. Where a settled decision
appears wrong, this doc flags it in §14 "Escalations" — it does not silently
re-design.

Quotations from the authorities are inlined so this doc is reviewable
without consulting the source files.

### 0.1 OO rules cited verbatim before design decisions

Quoted from `punt-labs/.claude/rules/python-*.md`:

- **PY-OO-1 — "Every noun in the domain that has both data and behavior must be
  modeled as a class with private state and methods."** → `Element` is a class;
  `TextElement` extends it; behavior (render-template) lives on `Element`.
- **PY-OO-2 — "≤ 3 classes per module, ≤ 300 lines."** → every new module in
  §1 is sized to comply; the factory + enum + registry triples are split to
  keep one concept per module unless the size budget admits co-location.
- **PY-OO-5 — "State + Behavior = Class. If you find yourself writing a
  function that takes a data structure, reads multiple fields, and returns a
  modified version, that function should be a method."** → `render()` is a
  method on `Element`. Codec methods stay OFF `Element` because they are
  format-coupled I/O, not domain behavior — they live on
  per-format-per-kind Decoder classes (DES-032).
- **PY-OO-7 — "No fake OO. A module that defines a class AND a cluster of
  module-level helper functions is procedural code wearing OO clothing."** →
  `ImGuiRendererFactory.__call__` dispatches by `match elem:` inline; no
  `_dispatch_imgui_text(elem)` helpers next to the class.
- **PY-CC-1 — "Use `__new__` instead of `__init__`."** → `Element.__new__`
  is the constructor; subclasses also use `__new__` because injected
  dependencies and immutability of the Element identity are both required
  (DES-032 mandates "renderer_factory + emit injected at construction").
- **PY-IC-1 — "Composition over inheritance when behavior differs."** →
  `ImGuiRendererFactory` composes `WidgetState` and `TextureCache` as
  constructor arguments rather than inheriting a SurfaceContext base.
- **PY-TS-6 — "Protocol for structural interfaces, ABC for shared
  implementation."** → `Renderer`, `RendererFactory`, `Decoder`,
  `DecoderFactory` are `runtime_checkable` Protocols (interface-only).
  `Element` is an ABC because it owns the template-method `render()`
  (shared implementation, not just shape).
- **PY-EH-1 — "Validate at the boundary."** → `JsonTextDecoder.decode`
  validates wire input via `ElementWireContext` (already in use by the
  PR-2 codec); internal methods on `TextElement` trust the constructor's
  invariants.
- **PY-EH-8 — "Raise, don't return None on unrepresentable values."** →
  `JsonTextDecoder.decode` raises `ValueError` on bad input; never
  returns `None`. `Element.render` returns `None` on success, raises on
  internal contract violation (e.g. a renderer Protocol mis-implementer).
- **PY-RF-2 — "No dead code. Infrastructure ships with first consumer."**
  → Commit (i) ships `RecordingRenderer` + `NullRenderer` with a test
  fixture as its consumer; commit (ii) ships the Element ABC + Protocols +
  registries WITH a failing TextElement test that becomes its consumer
  one commit later in (iii). Every commit has a test that exercises new
  production code.
- **PL-PP-1 — "No backwards-compatibility shims that outlive their PR."**
  → `WidgetValueProvider` deletion is total; no re-exports, no aliases.

### 0.2 Architecture authorities cited verbatim

Quoted from `docs/architecture/archive/io-model.md`:

> **The Element is a domain object.** State, behavior, composition. Not a
> transport struct, not a render widget.
>
> **The Element does not know its inputs or outputs.** No imports of any
> wire format, no imports of any render surface. The Element knows the
> abstract `RendererFactory` Protocol so it can render itself; that is
> the only I/O knowledge it carries.
>
> **The Composite pattern lives on the Element itself.** Same `render()`
> method on leaf and composite, inherited from a shared base via the
> template method pattern.
>
> **I/O is symmetric.** Decoding wire-format input and rendering to a
> surface are structurally identical concerns — both are external,
> both have multiple possible implementations, both are selected via a
> key→family registry.
>
> **Input fans in; output is singular.** One Display has one render
> surface but many connected clients, each potentially using a
> different wire format. This is the only deliberate asymmetry.

Quoted from `DESIGN.md` DES-032 (paraphrased — the ADR text is the
authority):

> Codec methods move OFF the Element class into per-format Decoder
> family. `render()` moves ONTO the Element class via template method.
> `renderer_factory` and `emit` are injected at Element construction.

Quoted from `DESIGN.md` DES-033:

> Per-surface RendererFactory families and per-format DecoderFactory
> families. Module-level registries (`Renderers`, `Decoders`). Asymmetric
> cardinality: 1 RendererFactory + N Decoders per Display.

## 1. Module layout

The package root for new modules is `src/punt_lux/`. Decisions for the
factory+enum+registry triples follow §1.4.

### 1.1 Element ABC

| Module | Purpose | Est. lines |
|--------|---------|-----------:|
| `src/punt_lux/domain/element_base.py` | The abstract `Element` class — `__new__` injecting `renderer_factory` + `emit`; the template-method `render()`; the `_children()` hook. | ~85 |

Rationale: the existing `src/punt_lux/domain/element.py` defines the
**Protocol** `Element` that PR 1 and PR 2 use as the wire-element
structural contract (see §3.2 below — both names coexist briefly and the
Protocol is deleted in commit iii once the only TextElement caller moves
to the ABC). To avoid a confusing in-place rename in the same commit
that introduces the ABC, the ABC lands at `element_base.py` and is
exported as `Element` from the renamed `punt_lux.domain` re-export
surface. After commit iii, `domain/element.py` (the Protocol) is
**deleted**; commit iii then renames `element_base.py` → `element.py`
in the same commit to leave a clean tree. This avoids a two-name
soup beyond commit iii.

### 1.2 Renderer + RendererFactory + Surface + Renderers registry

| Module | Purpose | Est. lines |
|--------|---------|-----------:|
| `src/punt_lux/protocol/renderer.py` | The `Renderer` `Protocol` — `render() / begin() / end()`. Pure interface, no implementation. | ~40 |
| `src/punt_lux/protocol/renderer_factory.py` | The `RendererFactory` callable `Protocol` (`__call__(elem) -> Renderer`), the `Surface` `Enum` (`IMGUI`, `RECORDING`, `NULL`), and the `Renderers` registry class with `getRendererFor`. | ~80 |

Rationale for two modules, not three: `Surface` is the dispatch key
the `Renderers` registry consumes — they are bound at the use-site
(`Renderers.getRendererFor(Surface.IMGUI, ...)`). Splitting `Surface`
into its own one-class file would be a cohesion penalty (PL-CO-3,
which says a 1-class module is fine but PL-MD-2 prefers modules with
sibling references — `Renderers` *uses* `Surface`). Keeping
`RendererFactory` Protocol with `Surface` + `Renderers` in one module
puts the three names that are always imported together in one
import line. The 80-line budget keeps it well under PY-OO-2's 300.

The `Renderer` Protocol gets its own module because it is the contract
that **every per-kind renderer class** (including the existing
`display/renderers/*_renderer.py`) implements — separating it from
`RendererFactory` lets per-kind renderer modules import only what they
need (no transitive `Surface` enum import on every renderer file).

### 1.3 Decoder + DecoderFactory + WireFormat + Decoders registry

| Module | Purpose | Est. lines |
|--------|---------|-----------:|
| `src/punt_lux/protocol/decoder.py` | The `Decoder` `Protocol` — `decode(raw: dict[str, object]) -> Element`. Pure interface. | ~40 |
| `src/punt_lux/protocol/decoder_factory.py` | The `DecoderFactory` `Protocol` (the per-format top-level decoder — `decode(raw_bytes) -> Element`), the `WireFormat` `Enum` (`JSON` only in PR 3), and the `Decoders` registry class with `getDecoderFor`. | ~80 |

Same rationale as §1.2 — three names that are bound at use-site
(`Decoders.getDecoderFor(WireFormat.JSON, factory, emit)`) ship together.
This keeps the io-model's symmetry visible: a reviewer reading
`renderer_factory.py` and `decoder_factory.py` side-by-side sees
identical shapes (Protocol + Enum + Registry-class).

### 1.4 Why factory+enum+registry are co-located, not split into three

The mission asks me to "decide one-module-or-three and justify." I'm
choosing **one module per family** (so two modules across both families,
since each family also splits its single-Protocol concept out for
import-load reasons in §1.2 and §1.3). The decision basis:

1. **PY-OO-2 budget** — `Enum` (3 members), `Protocol` (1 method),
   `Registry` (1 staticmethod with 4 match arms) is ~80 lines together,
   well under 300. There is no size pressure to split.
2. **PL-MD-2 (package cohesion)** — every name in the module references
   the others: `Renderers.getRendererFor` returns a `RendererFactory`
   selected by `Surface`. Splitting would create three modules that
   each import the other two — adding three import lines per use site
   for zero clarity gain.
3. **Symmetry** — the I/O model's defining property (DES-033) is that
   Decoder and Renderer families have identical shape. Two parallel
   2-module pairs make that symmetry visible in the file tree:

```text
protocol/
  renderer.py            ← Renderer Protocol (1 class)
  renderer_factory.py    ← RendererFactory + Surface + Renderers
  decoder.py             ← Decoder Protocol (1 class)
  decoder_factory.py     ← DecoderFactory + WireFormat + Decoders
```

### 1.5 Test-surface renderers (Recording + Null)

| Module | Purpose | Est. lines |
|--------|---------|-----------:|
| `src/punt_lux/protocol/renderers_test.py` | `RecordingRenderer` (Element-kind-agnostic; captures `(op, kind, id)` tuples) and `NullRenderer` (no-op). Co-located because both share "synthetic surface for tests" purpose and neither needs ImGui. Both are tiny generic classes. | ~80 |

These live under `protocol/` (NOT under `tests/`) because they are
production-shipped surfaces consumed by tests AND by any non-display
tier — the `NullRendererFactory` returned by `NullRenderer`'s sibling
factory is what `hub_display` and applet-tier Element constructors
inject when no rendering happens locally (per archived io-model.md §"What this
means for `renderer_factory` injection on Element"). They are not
test-only code; the name `renderers_test.py` is the io-model's surface
discriminator (RECORDING/NULL are surfaces alongside IMGUI), not a
pytest convention.

A `RecordingRendererFactory` and `NullRendererFactory` callable wrap
each renderer for use through the Surface registry. Both factory
classes co-locate in `renderers_test.py` — they are 4-line wrappers
each.

### 1.6 ImGui renderer family for Text

| Module | Purpose | Est. lines |
|--------|---------|-----------:|
| `src/punt_lux/display/imgui_renderer_factory.py` | `ImGuiRendererFactory` — owns `WidgetState`, `TextureCache`, the emit channel; dispatches by Element type via `match`. In PR 3, dispatches `TextElement` → `ImGuiTextRenderer`. | ~90 |
| `src/punt_lux/display/renderers/text_renderer.py` | `ImGuiTextRenderer` (renamed from the existing `TextRenderer`) — implements the `Renderer` Protocol; holds the constructed `TextElement` instance; reads its fields to draw. The existing `_render_with_tooltip` / `_render_styled` / `_emit_for_style` / `_emit_style_colored` private helpers are preserved. | ~95 |

Rationale for keeping `ImGuiTextRenderer` at the existing path: the file
already lives there (`display/renderers/text_renderer.py`), the renderer
class is genuinely display-tier code (`imgui_bundle` import), and the
`display/renderers/` directory is the existing home for per-kind ImGui
renderers (15 of them in PR 2). Renaming the directory mid-migration
would churn every other renderer file with no design benefit. PR 3
renames the **class** (`TextRenderer` → `ImGuiTextRenderer`) and the
**shape** (now implements the `Renderer` Protocol) but the **file path**
is stable.

The `ImGuiRendererFactory` is a new file in `display/` (alongside
`element_renderer.py`, `texture_cache.py`, `menu_manager.py`). PR 3's
factory dispatches one element type; PRs 4–9 grow the `match` arms
incrementally.

### 1.7 JSON decoder family for Text

| Module | Purpose | Est. lines |
|--------|---------|-----------:|
| `src/punt_lux/protocol/decoders_json.py` | `JsonDecoderFactory` — implements `DecoderFactory`; dispatches by `raw["kind"]` to per-kind decoders; in PR 3 only knows `"text"` and raises `ValueError` for other kinds (PR 4 adds more arms). Holds `_renderer_factory` and `_emit` to thread into per-kind decoder construction. AND `JsonTextDecoder` — implements `Decoder`; constructs `TextElement` from a `dict[str, object]` via the existing `ElementWireContext` boundary validator (PY-EH-1). | ~110 |

Rationale for one module, two classes: the factory and its first decoder
are tightly coupled — the factory's `decode` method is "look up the
right per-kind decoder and delegate." Splitting them into
`decoder_json_factory.py` + `decoder_json_text.py` produces two
~55-line modules where each is only meaningful when imported with the
other. PR 4 will grow this module to ~5 classes (one per added basics
kind) which crosses the PY-OO-2 3-class threshold; PR 4's design split
is "extract per-kind decoders into per-kind files at that point" — the
same pattern the per-kind ImGui renderers follow. PR 3 stays at 2
classes in one file.

### 1.8 Total new files for PR 3

8 new files in `src/punt_lux/`:

```text
domain/element_base.py            (commit ii — Element ABC)
protocol/renderer.py              (commit ii — Renderer Protocol)
protocol/renderer_factory.py      (commit ii — RendererFactory + Surface + Renderers)
protocol/decoder.py               (commit ii — Decoder Protocol)
protocol/decoder_factory.py       (commit ii — DecoderFactory + WireFormat + Decoders)
protocol/renderers_test.py        (commit i — Recording + Null renderers + factories)
display/imgui_renderer_factory.py (commit iii — ImGuiRendererFactory)
protocol/decoders_json.py         (commit iii — JsonDecoderFactory + JsonTextDecoder)
```

Plus:

- `display/renderers/text_renderer.py` is **modified in place** in
  commit iii: rename class `TextRenderer` → `ImGuiTextRenderer`,
  change shape to hold the `TextElement` instance and implement the
  `Renderer` Protocol's `render() / begin() / end()`.
- `protocol/elements/text.py` is **rewritten in place** in commit iii:
  drop `@dataclass`, become an `Element` subclass with `__new__`,
  delete `to_dict` / `from_dict`.
- `domain/element.py` is **deleted** in commit iii after `element_base.py`
  is renamed into its place (see §1.1).
- `scene/widget_value_provider.py` is **deleted** in commit iv. Its
  imports get removed from `scene/manager.py` and from the 7 input
  elements that implement it.

New test files:

```text
tests/protocol/test_renderers_test.py     (commit i)
tests/protocol/test_element_base.py        (commit ii — RED TextElement test placeholder)
tests/protocol/test_decoders_json.py       (commit iii — JsonTextDecoder roundtrip)
tests/render/test_text_render.py           (commit iii — TextElement under Recording renderer; the proving test)
tests/display/test_imgui_renderer_factory.py (commit iii — factory dispatches TextElement)
```

`tests/render/` is new — the migration plan calls this out as the
new test tier (line 342: *"Render unit (PR 3 onward) — NEW —
tests/render/"*). Commit i creates the directory.

## 2. Class signatures

Every signature below uses the conventions:

- `Self` returned from `__new__` (PY-TS-3).
- Keyword-only injected dependencies (`*,` in signature) to prevent
  positional-arg confusion across factory + emit + kind-specific fields.
- `from __future__ import annotations` in every file (PY-TS-1).
- `tuple[Element, ...]` returned from `_children` for immutability.

### 2.1 `Element` (ABC)

`src/punt_lux/domain/element_base.py`:

```python
from __future__ import annotations

from abc import ABC
from collections.abc import Callable
from typing import Self, TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.protocol.renderer_factory import RendererFactory

__all__ = ["Element", "Emit"]


type Emit = Callable[[object], None]


class Element(ABC):
    """Domain component. Owns its render lifecycle via the template method
    pattern (PY-OO-5). Composite participants — leaf and composite — share
    the same render() method; recursion is internal to the template."""

    _renderer_factory: RendererFactory
    _emit: Emit

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
    ) -> Self:
        """Construct the Element shell with injected I/O dependencies.

        Subclasses MUST call ``super().__new__(cls, renderer_factory=...,
        emit=...)`` and assign their own fields before ``return self``.
        Subclasses MUST NOT redefine ``render`` or ``_children`` calling
        conventions; they extend by overriding ``_children`` (composites)
        or by adding behavior methods (per-subclass, see §2.8 below).
        """
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        return self

    def render(self) -> None:
        """Template method — NEVER overridden. Leaf vs composite branch
        is the only logic here; behavior lives on subclasses; drawing
        lives on the resolved Renderer (PY-OO-5 + Composite pattern)."""
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

    def _children(self) -> tuple[Element, ...]:
        """Hook — composites override to return their children. Leaves
        inherit the empty default and the template takes the leaf branch."""
        return ()
```

`Emit` is a module-level type alias for `Callable[[object], None]`.
Concrete `emit` callables in PR 3 receive `InteractionMessage` instances;
the wider `object` annotation accommodates `PublishMessage` and other
future wire-event kinds without re-typing `Element` per family.

### 2.2 `Element.__new__` — how subclasses accept their own fields (resolved open question)

**Decision: option (a) — manual `__new__` on subclasses; the ABC's
`__new__` only threads the I/O dependencies.**

Subclasses define their own `__new__` that:

1. Calls `super().__new__(cls, renderer_factory=rf, emit=emit)` to
   thread the injected fields through the ABC.
2. Assigns their kind-specific fields directly.
3. Returns `self`.

**Why not (b) "custom decorator that generates `__new__`":**

The decorator option (something like `@io_element(fields=("id", "content",
"style", "color", "tooltip"))`) trades two-and-a-half lines of explicit
`self._id = id` per subclass for a piece of meta-programming that:

- Makes the generated `__new__` opaque at the import site (every reader
  has to learn the decorator's contract before reading the subclass).
- Hides the order in which fields are assigned — PY-CC-2 ("Establish all
  invariants in the constructor") wants the order visible, especially
  when validation lives on a future field setter.
- Hides where to put per-field validation when a future subclass needs
  it.
- Is exactly the kind of meta-programming PY-OO-7's "no fake OO" rule
  warns about — a decorator-generated method is a function pretending
  to be a method.

Option (a) is verbose but every reader of `TextElement.__new__` can
see exactly what gets assigned and in what order. The verbosity scales
linearly with field count and the PR-4–9 cohort has at most ~6 fields
per element (the inputs family's most field-rich, like
`SliderElement`, has ~6) — total worst-case repetition is ~6 lines per
subclass for 24 subclasses = ~144 lines across the migration. That is
not a meta-programming-warranting problem.

**Why not `@dataclass` with `__post_init__`**: `@dataclass` generates
`__init__`, not `__new__`. Calling `__post_init__` from a hand-written
`__new__` adds an indirection that is exactly as opaque as option (b).
PR-2's per-class `@dataclass(frozen=True, slots=True)` shape is what
this PR replaces; bringing it back would be a regression.

**Why not a custom metaclass that intercepts `__init_subclass__`** to
inject `__new__`: same opacity criticism as option (b), plus
metaclasses are forbidden by PY-CC-1's spirit (constructor lives in
`__new__`, visible to the reader).

The subclass signature pattern:

```python
class FooElement(Element):
    _id: str
    _kind_specific_field: str

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        kind_specific_field: str,
    ) -> Self:
        self = super().__new__(
            cls, renderer_factory=renderer_factory, emit=emit
        )
        self._id = id
        self._kind_specific_field = kind_specific_field
        return self
```

This is what `TextElement.__new__` looks like in §3.1.

### 2.3 `Renderer` (Protocol)

`src/punt_lux/protocol/renderer.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Renderer"]


@runtime_checkable
class Renderer(Protocol):
    """The contract every per-kind renderer satisfies.

    LEAVES implement ``render()`` and inherit no-op ``begin() / end()``
    from default implementations (defensive — the Element template
    only calls ``render()`` on a leaf, but Protocol uniformity makes
    isinstance checks total).

    COMPOSITES implement ``begin()`` and ``end()`` (and inherit
    no-op ``render()``); the Element template calls
    ``begin() → child.render() ⋯ end()`` for them.
    """

    def render(self) -> None:
        """Draw the leaf. No-op for composites."""

    def begin(self) -> None:
        """Open the composite bracket. No-op for leaves."""

    def end(self) -> None:
        """Close the composite bracket. No-op for leaves."""
```

Three methods with default `...` bodies are correct for a `Protocol`
(PY-TS-6) — the implementation classes override only what's
meaningful. `runtime_checkable` enables `isinstance(x, Renderer)` for
test assertions (PY-TS-10 forbids `hasattr`).

### 2.4 `RendererFactory`, `Surface`, `Renderers`

`src/punt_lux/protocol/renderer_factory.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.element_base import Element
    from punt_lux.protocol.renderer import Renderer

__all__ = ["RendererFactory", "Renderers", "Surface"]


@runtime_checkable
class RendererFactory(Protocol):
    """Callable resolving an Element to its per-kind Renderer for this
    surface. One factory per Surface per Display (DES-033)."""

    def __call__(self, elem: Element) -> Renderer:
        ...


class Surface(Enum):
    """Output-surface discriminator. Key into the Renderers registry."""

    IMGUI = "imgui"
    RECORDING = "recording"
    NULL = "null"


class Renderers:
    """Module-level dispatch registry. Returns a RendererFactory for
    the requested Surface. One factory exists per Display, chosen
    at startup (DES-033)."""

    @staticmethod
    def getRendererFor(surface: Surface, **context: object) -> RendererFactory:
        """Construct the per-surface factory with surface-shared context.

        Raises ValueError on unknown surface (PY-EH-8) — assert_never
        would also work but ValueError surfaces the bad input shape
        at the boundary (PY-EH-1).
        """
        match surface:
            case Surface.IMGUI:
                from punt_lux.display.imgui_renderer_factory import (
                    ImGuiRendererFactory,
                )
                return ImGuiRendererFactory(**context)
            case Surface.RECORDING:
                from punt_lux.protocol.renderers_test import (
                    RecordingRendererFactory,
                )
                return RecordingRendererFactory(**context)
            case Surface.NULL:
                from punt_lux.protocol.renderers_test import (
                    NullRendererFactory,
                )
                return NullRendererFactory()
        msg = f"unknown surface: {surface!r}"
        raise ValueError(msg)
```

Imports are deferred inside the match to avoid pulling `imgui_bundle`
into `protocol/` (which is contract-only — PL-MD-1 layering). The
`**context` kwargs let each factory take its own shared-state shape
without `Renderers` knowing the details.

### 2.5 `Decoder`, `DecoderFactory`, `WireFormat`, `Decoders`

`src/punt_lux/protocol/decoder.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.element_base import Element

__all__ = ["Decoder"]


@runtime_checkable
class Decoder(Protocol):
    """Per-kind decoder. Constructs one Element from a wire dict.

    The DecoderFactory owns ``renderer_factory`` and ``emit``; the
    per-kind Decoder threads them through Element construction
    (DES-033).
    """

    def decode(self, raw: Mapping[str, object]) -> Element:
        ...
```

The argument type is `Mapping[str, object]` (NOT `dict[str, Any]`,
which violates PY-TS-14). Wire bytes have already been parsed into
a dict by the JSON parser; the Decoder takes the parsed structure.
`object` (not `Any`) makes the Decoder do `isinstance` narrowing —
which it does via `ElementWireContext` from PR 2 (already in use,
see §3.2 below for the existing `text.py from_dict` shape that
moves into `JsonTextDecoder.decode` byte-for-byte).

`src/punt_lux/protocol/decoder_factory.py`:

```python
from __future__ import annotations

from enum import Enum
from typing import Protocol, TYPE_CHECKING, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_base import Element, Emit
    from punt_lux.protocol.renderer_factory import RendererFactory

__all__ = ["DecoderFactory", "Decoders", "WireFormat"]


@runtime_checkable
class DecoderFactory(Protocol):
    """Top-level decoder for a wire format. Owns per-kind decoders
    and dispatches by ``raw['kind']``. Constructed once per
    connection (per-connection lifetime — DES-033)."""

    def decode(self, raw: Mapping[str, object]) -> Element:
        ...


class WireFormat(Enum):
    """Wire-format discriminator. Key into the Decoders registry."""

    JSON = "json"


class Decoders:
    """Module-level dispatch registry. Returns a DecoderFactory for
    the requested WireFormat, configured with the renderer_factory
    and emit channel the connection will use (DES-033)."""

    @staticmethod
    def getDecoderFor(
        fmt: WireFormat,
        renderer_factory: RendererFactory,
        emit: Emit,
    ) -> DecoderFactory:
        """Construct the per-format factory with the connection's
        renderer_factory and emit channel.

        Raises ValueError on unknown format (PY-EH-8)."""
        match fmt:
            case WireFormat.JSON:
                from punt_lux.protocol.decoders_json import JsonDecoderFactory
                return JsonDecoderFactory(
                    renderer_factory=renderer_factory, emit=emit
                )
        msg = f"unknown wire format: {fmt!r}"
        raise ValueError(msg)
```

`WireFormat` has one member in PR 3. PR 10's Encoder family work adds
`MSGPACK` / `CBOR` when their first consumer exists (PY-RF-2). Until
then keeping `WireFormat` to one arm is correct — speculative members
would be PY-RF-2 violations.

### 2.6 `RecordingRenderer`, `RecordingRendererFactory`, `NullRenderer`, `NullRendererFactory`

See §6 for the full class definitions. Signature summary:

```python
RecordingRenderer.__new__(
    cls, *, elem: Element, log: list[tuple[str, str, str]]
) -> Self

RecordingRenderer.render(self) -> None
RecordingRenderer.begin(self) -> None
RecordingRenderer.end(self) -> None

RecordingRendererFactory.__new__(cls) -> Self
RecordingRendererFactory.__call__(self, elem: Element) -> Renderer
RecordingRendererFactory.log -> property[tuple[tuple[str, str, str], ...]]

NullRenderer.__new__(cls) -> Self
NullRenderer.render(self) -> None
NullRenderer.begin(self) -> None
NullRenderer.end(self) -> None

NullRendererFactory.__new__(cls) -> Self
NullRendererFactory.__call__(self, elem: Element) -> Renderer
```

### 2.7 `ImGuiRendererFactory`, `ImGuiTextRenderer`

See §5 and §7 for full definitions. Signature summary:

```python
ImGuiRendererFactory.__new__(
    cls,
    *,
    widget_state: WidgetState,
    texture_cache: TextureCache,
    emit: Emit,
) -> Self

ImGuiRendererFactory.__call__(self, elem: Element) -> Renderer

ImGuiTextRenderer.__new__(cls, *, elem: TextElement) -> Self
ImGuiTextRenderer.render(self) -> None
ImGuiTextRenderer.begin(self) -> None   # no-op (leaf)
ImGuiTextRenderer.end(self) -> None     # no-op (leaf)
```

### 2.8 How future ButtonElement adds `on_click` without changing the ABC

The Element ABC has zero behavior methods. Behavior is per-subclass:

```python
class ButtonElement(Element):
    _id: str
    _label: str
    _action: str

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        label: str,
        action: str | None = None,
    ) -> Self:
        self = super().__new__(
            cls, renderer_factory=renderer_factory, emit=emit
        )
        self._id = id
        self._label = label
        self._action = action or id
        return self

    def on_click(self) -> None:                       # ← per-subclass
        self._emit(InteractionMessage(
            element_id=self._id, action=self._action,
            ts=time.time(), value=True,
        ))
```

The Element ABC accommodates this without modification — `on_click` is
a `ButtonElement` method, callable from `ImGuiButtonRenderer.render()`
via `self._elem.on_click()` (owner tier) or via a wire-emitted
`InteractionMessage` (non-owner tier). PR 5 introduces this; PR 3
just leaves room for it. `TextElement` has no behavior method.

### 2.9 `TextElement` (the proving subclass)

See §3 for the full definition. Signature:

```python
TextElement.__new__(
    cls,
    *,
    renderer_factory: RendererFactory,
    emit: Emit,
    id: str,
    content: str,
    style: Literal["body", "heading", "caption", "code", "success", "error"]
        | None = None,
    color: str | None = None,
    tooltip: str | None = None,
) -> Self

TextElement.id -> property[str]
TextElement.kind -> property[Literal["text"]]
TextElement.content -> property[str]
TextElement.style -> property[Literal[...] | None]
TextElement.color -> property[str | None]
TextElement.tooltip -> property[str | None]
```

Properties expose the fields read by `ImGuiTextRenderer` (PY-EN-2 —
properties for read-only access; consumers do not poke `elem._content`).

`style`, `color`, `tooltip` keep `| None` because PR 1's `from_dict`
treats absence as the documented contract (renderer default). PY-TS-14
allows `| None` with inline comments naming the contract — this design
preserves the comments from the PR-2 `text.py` source verbatim. A
future refactor could discriminate `style` into a `TextStyle.BODY`
default vs explicit set states (DES-030 three-layer model territory)
but that's PR 4+ scope per §"Out of scope" below.

## 3. `TextElement` on the ABC

### 3.1 Full class definition

`src/punt_lux/protocol/elements/text.py` (rewritten in commit iii):

```python
"""TextElement — a text block; subclass of the Element ABC (DES-032)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from punt_lux.domain.element_base import Element

if TYPE_CHECKING:
    from punt_lux.domain.element_base import Emit
    from punt_lux.protocol.renderer_factory import RendererFactory

__all__ = ["TextElement"]


type TextStyle = Literal["body", "heading", "caption", "code", "success", "error"]


class TextElement(Element):
    """A text block. Leaf — no children, no behavior."""

    _id: str
    _content: str
    _style: TextStyle | None     # PY-TS-14: None = renderer default
    _color: str | None           # PY-TS-14: None = renderer default
    _tooltip: str | None         # PY-TS-14: None = no tooltip

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        content: str,
        style: TextStyle | None = None,
        color: str | None = None,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(
            cls, renderer_factory=renderer_factory, emit=emit
        )
        self._id = id
        self._content = content
        self._style = style
        self._color = color
        self._tooltip = tooltip
        return self

    @property
    def id(self) -> str:
        return self._id

    @property
    def kind(self) -> Literal["text"]:
        return "text"

    @property
    def content(self) -> str:
        return self._content

    @property
    def style(self) -> TextStyle | None:
        return self._style

    @property
    def color(self) -> str | None:
        return self._color

    @property
    def tooltip(self) -> str | None:
        return self._tooltip
```

What changed from PR 2's `text.py`:

- No `@dataclass(frozen=True, slots=True)`. The PR-2 shape's main
  advantages — equality + hash + immutability — are addressed
  separately (see §3.2 hashability decision below) or no longer apply
  (with injected non-hashable factories, frozen=True can't add value).
- No `to_dict` / `from_dict` methods. Codec moves to
  `JsonTextDecoder` (§4) — this is the headline change DES-032
  mandates.
- No `kind: Literal["text"] = "text"` field. Replaced with a `kind`
  property that returns the literal — `kind` is a class-level fact,
  not an instance field, and a property removes the wire-only field
  from the constructor signature.
- No `style: str | None = None  # body|heading|...` comment-as-type.
  Replaced with `style: TextStyle | None = None` where `TextStyle` is
  the `Literal[...]` type alias (PY-TS-14 — comment listing values is
  the type system giving up).
- Renamed instance attributes to `_id`, `_content`, etc. (PY-EN-1 —
  no public data attributes); properties expose read access (PY-EN-2).
- Element ABC inheritance brings `render()` + `_children()` for free.

### 3.2 Hashability — resolved

**Decision: `TextElement` is NOT hashable. The `Element` Protocol from
`domain/element.py` and its hash-implying contract is DELETED in
commit iii.**

The PR-1+2 `TextElement` was a `@dataclass(frozen=True, slots=True)`
— frozen dataclasses are hashable by default, and the PR-2 codec
relied on equality-by-fields for snapshot characterization. Two
forces push back:

1. **DES-032 mandates injected factories.** `renderer_factory` and
   `emit` are callable instances, not hashable values. Even if we
   wanted hashability, we couldn't include them in the hash without
   coupling identity to the factory instance — which would defeat
   the point ("the same TextElement on hub and display tiers is the
   same Element" per the archived io-model design's
   §"Tier-local Element representation").
2. **Snapshot parity does NOT need element hashability.**
   `make snapshot-parity` (PR 0's CI gate) replays MCP tool calls and
   compares the resulting wire output dict-for-dict. The byte-identity
   it preserves is **wire-bytes-identity** of `element_from_dict(...)
   .to_dict()`. No characterization test relies on
   `hash(TextElement(...))` or on set/dict membership of Element
   instances. (I verified this by reading the characterization test
   shape: it diffs JSON outputs, not Python identity. See
   `tests/characterization/` for the shape that
   `make snapshot-parity` exercises.)

Path: drop `__hash__`. The class inherits `object.__hash__` (identity
hash). Tests that need value-equality compare via `to_dict()` (which is
gone — they now compare via the wire dict the decoder consumed, or via
explicit field reads). The PR-2 frozen-dataclass auto-`__eq__` is also
dropped; tests that need equality construct expectations and use
field-by-field assertions.

**What if a future use case needs value-equality for Elements?**
The DES-030 three-layer type model already names the answer: a
separate **snapshot type** (frozen, hashable, immutable, no injected
factories) is the right representation for value-equality. PR 3 does
not need it because no use case requires it. Building it speculatively
is a PY-RF-2 violation.

### 3.3 Why the existing `domain/element.py` Element Protocol is deleted

PR-2's `domain/element.py` defines:

```python
@runtime_checkable
class Element(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def tooltip(self) -> str | None: ...
    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self: ...
```

This Protocol's `to_dict` / `from_dict` members are exactly what
DES-032 moves OFF the Element. Keeping the Protocol after commit iii
would force `TextElement` to satisfy a contract that explicitly
includes the methods we're deleting — internally inconsistent.

Commit iii:

1. Deletes `domain/element.py` (the Protocol).
2. Renames `domain/element_base.py` → `domain/element.py` (the ABC
   takes the canonical name).
3. Updates every importer of `domain.element.Element` to reference
   the ABC.

Other Elements (PR-2 dataclasses) continue to exist in the same
files; the type union `Element` in `protocol/elements/__init__.py`
remains a `|`-union of dataclass types until PR 4–9 migrate them
onto the ABC. The fact that other Element-kind dataclasses do NOT
inherit from the ABC during the migration window is **intentional and
acceptable** — `domain_pump.py` and `element_renderer.py` route them
through `isinstance(elem, NativeElementClass)` checks (the existing
PR-2 dispatch) until they migrate. The dispatch in §9 below is what
makes this coexistence work.

## 4. `JsonTextDecoder` — byte-identical snapshot parity

### 4.1 Full class definition

`src/punt_lux/protocol/decoders_json.py` (introduced in commit iii):

```python
"""JSON Decoder family — JsonDecoderFactory + per-kind decoders.

PR 3 ships with one per-kind decoder (JsonTextDecoder). PRs 4–9
extend ``_DECODERS`` with one entry per migrating kind. After PR 9,
``_DECODERS`` covers all 24 element kinds and the legacy
``element_from_dict`` dispatcher is gone (PR 10 cleanup).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar, Self, TYPE_CHECKING

from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from punt_lux.domain.element_base import Element, Emit
    from punt_lux.protocol.decoder import Decoder
    from punt_lux.protocol.renderer_factory import RendererFactory

__all__ = ["JsonDecoderFactory", "JsonTextDecoder"]


class JsonTextDecoder:
    """Construct TextElement from a JSON-decoded mapping.

    Implements the Decoder Protocol. Boundary validation (PY-EH-1)
    runs via the existing ElementWireContext shared with PR 1+2
    codecs — preserves byte-identical wire output (see §4.2).
    """

    _renderer_factory: RendererFactory
    _emit: Emit

    def __new__(
        cls, *, renderer_factory: RendererFactory, emit: Emit
    ) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        return self

    def decode(self, raw: Mapping[str, object]) -> TextElement:
        """Construct a TextElement from a wire mapping.

        Raises ValueError on missing/typed-wrong fields (via
        ElementWireContext — PY-EH-8: never returns None).
        """
        ctx = ElementWireContext.for_kind("text")
        style = ctx.optional_nullable_str(raw, "style")
        return TextElement(
            renderer_factory=self._renderer_factory,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            content=ctx.require_str(raw, "content"),
            style=_narrow_style(style),
            color=ctx.optional_nullable_str(raw, "color"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonDecoderFactory:
    """Dispatch by raw['kind'] to the right per-kind JSON decoder.

    PR 3 knows only "text". Other kinds raise ValueError — but the
    wire-layer integration (§8) routes non-text kinds through the
    legacy ``element_from_dict`` dispatcher during the migration
    window, so this raise is reached only by malformed payloads.
    """

    _DECODERS: ClassVar[dict[str, type[Decoder]]] = {
        "text": JsonTextDecoder,
    }

    _renderer_factory: RendererFactory
    _emit: Emit

    def __new__(
        cls, *, renderer_factory: RendererFactory, emit: Emit
    ) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        return self

    def decode(self, raw: Mapping[str, object]) -> Element:
        kind = raw.get("kind")
        if not isinstance(kind, str):
            msg = f"wire payload missing 'kind' (got {kind!r})"
            raise ValueError(msg)
        decoder_cls = self._DECODERS.get(kind)
        if decoder_cls is None:
            msg = f"no JSON decoder for kind={kind!r}"
            raise ValueError(msg)
        decoder = decoder_cls(
            renderer_factory=self._renderer_factory, emit=self._emit
        )
        return decoder.decode(raw)
```

`_narrow_style` is a module-private helper that narrows the
`str | None` returned by `ElementWireContext.optional_nullable_str` to
the `TextStyle` literal type alias defined in §3.1. It validates that
the string (when present) is one of the six allowed style values, and
raises `ValueError` otherwise — PY-EH-1 validation at the boundary,
PY-EH-8 raise-don't-return-None. The helper is module-level (not a
method on `JsonTextDecoder`) because it operates on raw strings, not
on a `JsonTextDecoder` instance — it is genuinely a stateless utility
per the PY-OO-7 "legitimate exception" clause ("a function is
genuinely standalone — same input/output, no shared vocabulary with
any class in the module").

### 4.2 Snapshot-parity preservation strategy — named

`make snapshot-parity` replays PR-0's characterization corpus
(`tests/characterization/snapshots/*.json`). Each snapshot pairs an
MCP tool call (e.g. `show()` with a Text element) with its serialized
wire payload. The replay calls the MCP tool, captures what would go
on the wire, and diffs against the recorded snapshot. Byte-identity
is required.

Where the parity must hold for Text in PR 3:

1. **Inbound (wire-bytes → Element).** The pre-PR-3 path is
   `element_from_dict(d)` → `TextElement.from_dict(d)`. The post-PR-3
   path for Text is `JsonDecoderFactory.decode(d)` → wire-layer
   integration §8 chooses this when `d["kind"] == "text"`. Same
   `ElementWireContext` does the boundary validation in both paths.
   Same fields land in the constructed Element.

2. **Outbound (Element → wire-bytes).** PR 2's path is
   `element_to_dict(elem)` → `TextElement.to_dict()` → adds `kind`,
   `id`, `content`, and conditionally `style` / `color` /
   `tooltip` to the wire dict. PR 3's path is the SAME
   `element_to_dict` dispatcher — it continues to handle outbound
   for Text via a small adapter (see below).

The outbound adapter — the parity-preservation mechanism:

`element_to_dict` is the dispatcher in `protocol/elements/__init__.py`.
It currently dispatches via `ElementCodec` which the
`BasicsRegistry` populates by calling
`register("text", TextElement, TextElement.to_dict, TextElement.from_dict)`.
PR 3 changes the BasicsRegistry registration for "text" to:

```python
register(
    "text",
    TextElement,
    _text_to_dict_for_parity,
    _text_from_dict_for_parity,
)
```

where `_text_to_dict_for_parity(elem)` is a 12-line free function in
`protocol/elements/basics.py` that reads
`elem.id` / `elem.content` / `elem.style` / `elem.color` and emits
the **exact same dict shape** PR-2's `TextElement.to_dict()`
produced. And `_text_from_dict_for_parity(d)` is a 2-line free
function that instantiates `JsonTextDecoder(renderer_factory=
NullRendererFactory(), emit=lambda _: None).decode(d)`.

This is a **dispatch-layer adapter**, not an OO violation:

- It's "fake OO" if the free function operates on the Element and
  there's a richer behavior the class should own. But this function
  exists because the EXISTING `ElementCodec` dispatch table holds
  bound `to_dict` references — `_text_to_dict_for_parity` is the
  bridge that lets the codec dispatcher keep working while the
  `TextElement` class loses the method.
- After PR 10's Encoder family ships, the outbound side will route
  through `JsonTextEncoder` (the symmetric counterpart to
  `JsonTextDecoder`), and the adapter dies. PR 3's adapter is a
  **migration-window bridge**, not architecture.
- The adapter lives in `protocol/elements/basics.py`, the SAME file
  where the registration call is — so the bridge and its sole caller
  are co-located. Reviewers don't have to hunt.

Why not delete `element_to_dict` outright in PR 3? Because
`element_to_dict` is called by `protocol/messages/scene.py`
(`SceneMessage` serialization), the MCP `show()` tool path, and the
characterization corpus replayer. Replacing it in PR 3 expands the
diff beyond the io-model infrastructure goal. PR 10 owns that
deletion explicitly (per migration-plan PR 10 "SceneManager scope
cut").

**Why this preserves byte-identical output for Text:**

`_text_to_dict_for_parity(elem)` reads the same six fields PR-2's
`TextElement.to_dict()` reads (`kind` constant + `id`, `content` +
conditional `style`, `color`, `tooltip`) and emits them in the same
order with the same conditional-skip-when-None rules. The byte output
is identical because the data is identical and the field-order
discipline is the same. The characterization snapshots for Text pass
unchanged.

I verified the PR-2 to_dict shape by reading the existing file:

```python
def to_dict(self) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": self.kind,
        "id": self.id,
        "content": self.content,
    }
    if self.style is not None:
        d["style"] = self.style
    if self.color is not None:
        d["color"] = self.color
    return d
```

(Note: tooltip is added by the *outer* `element_to_dict` dispatcher in
`protocol/elements/__init__.py` — see lines 163–171 of that file —
which appends `result["tooltip"] = elem.tooltip` when non-None. PR 3
keeps that outer-tooltip-handling step in place; the adapter only
replaces the bound `TextElement.to_dict` method.)

## 5. `ImGuiTextRenderer` refactored

### 5.1 What changes from PR 2

The PR-2 `TextRenderer` (in `display/renderers/text_renderer.py`)
holds no element reference; its `render(elem: TextElement)` method
takes the element each call. This is the **god-renderer pattern** —
the renderer is a stateless dispatcher that operates on whatever
element comes in.

The new `Renderer` Protocol (§2.3) is parameterless — `render(self) ->
None` and `begin(self) / end(self)`. The element reference moves INTO
the renderer instance, set at construction time by the
`ImGuiRendererFactory`. The factory builds a new
`ImGuiTextRenderer(elem=elem)` every frame the Element calls
`renderer.render()`. (The factory is the per-call allocation site;
this is acceptable because `ImGuiTextRenderer.__new__` allocates an
empty shell — see §5.2 below — and the per-frame cost is small.)

### 5.2 Full class definition

`src/punt_lux/display/renderers/text_renderer.py` (renamed-in-place
from PR-2 `TextRenderer`):

```python
# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiTextRenderer — Renderer Protocol impl for TextElement on ImGui."""

from __future__ import annotations

from typing import ClassVar, Self

from imgui_bundle import ImVec4, imgui

from punt_lux.display.renderers._color import parse_hex_color
from punt_lux.protocol.elements.text import TextElement

__all__ = ["ImGuiTextRenderer"]


type _Rgba = tuple[float, float, float, float]


class ImGuiTextRenderer:
    """Render a TextElement to ImGui. Leaf — no begin/end needed."""

    _STYLE_COLORS: ClassVar[dict[str, _Rgba]] = {
        "caption": (0.6, 0.6, 0.6, 1.0),
        "success": (0.2, 0.8, 0.2, 1.0),
        "error":   (0.9, 0.2, 0.2, 1.0),
    }

    _elem: TextElement

    def __new__(cls, *, elem: TextElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def render(self) -> None:
        elem = self._elem
        color = parse_hex_color(elem.color) if elem.color else None
        if elem.tooltip and not elem.style:
            self._render_with_tooltip(color)
            return
        self._render_styled(color)

    def begin(self) -> None:                          # leaf — no-op
        pass

    def end(self) -> None:                            # leaf — no-op
        pass

    # --- private helpers (preserved from PR 2; field reads change to
    # --- self._elem.X instead of elem.X parameter, but logic identical)

    def _render_with_tooltip(self, color: _Rgba | None) -> None:
        elem = self._elem
        if color is not None:
            imgui.push_style_color(imgui.Col_.text.value, ImVec4(*color))
        try:
            selected = False
            imgui.selectable(f"{elem.content}##{elem.id}", selected)
        finally:
            if color is not None:
                imgui.pop_style_color()
        if imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value):
            imgui.set_tooltip(elem.tooltip or "")

    def _render_styled(self, color: _Rgba | None) -> None:
        if color is not None:
            imgui.push_style_color(imgui.Col_.text.value, ImVec4(*color))
        try:
            self._emit_for_style(color)
        finally:
            if color is not None:
                imgui.pop_style_color()

    def _emit_for_style(self, color: _Rgba | None) -> None:
        elem = self._elem
        style = elem.style
        if style == "heading":
            imgui.separator_text(elem.content)
            return
        if style in self._STYLE_COLORS:
            self._emit_style_colored(elem.content, style, color)
            return
        if style == "code":
            imgui.indent(10.0)
            imgui.text(elem.content)
            imgui.unindent(10.0)
            return
        imgui.text_wrapped(elem.content)

    def _emit_style_colored(
        self, content: str, style: str | None, color: _Rgba | None
    ) -> None:
        if color is not None or style is None:
            imgui.text_wrapped(content)
            return
        rgba = self._STYLE_COLORS[style]
        imgui.push_style_color(imgui.Col_.text.value, ImVec4(*rgba))
        try:
            imgui.text_wrapped(content)
        finally:
            imgui.pop_style_color()
```

What changed:

- Class renamed `TextRenderer` → `ImGuiTextRenderer`.
- Holds `_elem: TextElement` set at `__new__`.
- `render()` takes no element parameter.
- Adds no-op `begin()` / `end()` for `Renderer` Protocol compliance.
- All private helpers now read `self._elem.X` (one line of churn each).
- File path unchanged (per §1.6 rationale).

The actual drawing logic — `imgui.text_wrapped` / `selectable` /
`separator_text` / push-color / pop-color — is **byte-for-byte the
same**. This matters for the manual smoke test in §11 commit iii: the
rendered Text frame should look pixel-identical to PR-2's output for
every style + color + tooltip combination.

### 5.3 How `ImGuiTextRenderer` composes with `ImGuiRendererFactory`

The factory holds shared surface state (`widget_state`,
`texture_cache`, `emit`). `ImGuiTextRenderer` needs NONE of these —
Text doesn't have widget state, doesn't load images, doesn't emit
interactions. So `__call__(elem)` for `TextElement` constructs an
`ImGuiTextRenderer` that only knows the element. Other PRs' renderers
(Button needs `emit`, Image needs `texture_cache`, Slider needs
`widget_state`) will read from the factory's stored fields when
constructing their per-kind renderer. PR 3's `ImGuiRendererFactory`
already accepts all three constructor arguments so it doesn't need
re-signing when PRs 4–5 migrate kinds that consume them.

## 6. `RecordingRenderer` and `NullRenderer`

### 6.1 Full class definitions

`src/punt_lux/protocol/renderers_test.py` (commit i):

```python
"""Test-surface renderer family: RecordingRenderer + NullRenderer.

Production-shipped because both surfaces appear in Surface (RECORDING,
NULL) and any non-display tier — hub, applet — injects
NullRendererFactory when constructing Elements through the Decoder
path. RecordingRenderer also acts as the proving-test fixture for
every element-kind migration PR (PY-RF-2 consumer).
"""

from __future__ import annotations

from typing import Self, TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.element_base import Element
    from punt_lux.protocol.renderer import Renderer

__all__ = [
    "NullRenderer",
    "NullRendererFactory",
    "RecordingRenderer",
    "RecordingRendererFactory",
]


type RecordingEntry = tuple[str, str, str]  # (op, kind, id)


class RecordingRenderer:
    """Capture (op, kind, id) for every render/begin/end call.

    Element-kind-agnostic — works for any Element subclass because
    it reads only ``elem.kind`` and ``elem.id`` (which every Element
    subclass exposes via the wire-protocol contract that every
    subclass satisfies).
    """

    _elem: Element
    _log: list[RecordingEntry]

    def __new__(cls, *, elem: Element, log: list[RecordingEntry]) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._log = log
        return self

    def render(self) -> None:
        self._log.append(("render", self._elem.kind, self._elem.id))

    def begin(self) -> None:
        self._log.append(("begin", self._elem.kind, self._elem.id))

    def end(self) -> None:
        self._log.append(("end", self._elem.kind, self._elem.id))


class RecordingRendererFactory:
    """Per-Display recording factory. Owns the shared event log;
    issues a new RecordingRenderer per (op, elem) but every renderer
    appends to the same log so the test can inspect a flat sequence.
    """

    _log: list[RecordingEntry]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._log = []
        return self

    def __call__(self, elem: Element) -> Renderer:
        return RecordingRenderer(elem=elem, log=self._log)

    @property
    def log(self) -> tuple[RecordingEntry, ...]:
        """Snapshot of captured (op, kind, id) tuples in render order."""
        return tuple(self._log)


class NullRenderer:
    """No-op renderer (PY-DP-9 — Null Object Pattern).

    Satisfies the Renderer Protocol without doing any work. Used by
    non-display tiers (hub, applet) that hold Elements but have no
    render loop.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self) -> None:                         # noqa: PLR6301
        pass

    def begin(self) -> None:                          # noqa: PLR6301
        pass

    def end(self) -> None:                            # noqa: PLR6301
        pass


class NullRendererFactory:
    """Per-Display null factory. Returns the same NullRenderer
    instance for every call (flyweight — the no-op renderer has no
    state, so one instance suffices)."""

    _NULL: ClassVar[Renderer]

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, elem: Element) -> Renderer:   # noqa: PLR6301
        return _NULL_RENDERER


_NULL_RENDERER: Renderer = NullRenderer()
```

`_NULL_RENDERER` is a module-level singleton (PY-DP-7) shared by every
`NullRendererFactory.__call__`. The same shared instance suffices
because `NullRenderer` has no state. The `# noqa: PLR6301` suppressions
are correct per PY-DP-9 ("Null Object methods don't use self; do NOT
fix by removing self").

### 6.2 The PY-RF-2 consumer for commit i

The Bar §5 says infrastructure ships with a consumer. Commit i ships
`RecordingRenderer` + `NullRenderer` without `TextElement` (which
arrives in commit iii). The consumer that satisfies PY-RF-2 in commit
i is `tests/protocol/test_renderers_test.py` — a test file that
exercises both renderers with a synthetic `Element` subclass defined
inline in the test fixture:

```python
class _FakeElement(Element):
    def __new__(cls, *, renderer_factory, emit, id):
        self = super().__new__(
            cls, renderer_factory=renderer_factory, emit=emit
        )
        self._id = id
        return self

    @property
    def id(self) -> str: return self._id

    @property
    def kind(self) -> str: return "fake"
```

This is genuinely a consumer (PR-2's existing PY-RF-2 dispensation for
"infrastructure is genuinely generic — test fixture is its production
caller"). `_FakeElement` is NOT shipped to production; it lives inside
the test module. But `RecordingRenderer` and `NullRenderer` are
production-shipped — they cover the `Surface.RECORDING` and
`Surface.NULL` arms of the `Renderers` registry that PR 13 will
exercise for in-process testing of the multi-tier deployment.

This is the SAME pattern the migration plan calls out at lines 188–197:

> "RecordingRenderer + NullRenderer + their tests — these are
> genuinely generic (Element-kind-agnostic); the test that drives
> them with a synthetic Element subclass is their consumer."

## 7. `ImGuiRendererFactory`

### 7.1 Full class definition

`src/punt_lux/display/imgui_renderer_factory.py` (commit iii):

```python
"""ImGuiRendererFactory — RendererFactory for the ImGui surface.

Owns surface-shared context (widget_state, texture_cache, emit channel).
Dispatches by Element type to the per-kind ImGui renderer. PR 3
dispatches ONE element type (TextElement); PRs 4–9 grow the match
arms incrementally.
"""

from __future__ import annotations

from typing import Self, TYPE_CHECKING

from punt_lux.display.renderers.text_renderer import ImGuiTextRenderer
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from punt_lux.display.texture_cache import TextureCache
    from punt_lux.domain.element_base import Element, Emit
    from punt_lux.protocol.renderer import Renderer
    from punt_lux.scene.widget_state import WidgetState

__all__ = ["ImGuiRendererFactory"]


class ImGuiRendererFactory:
    """ImGui-surface render factory. One per Display, at startup.

    Holds the surface-shared state every ImGui per-kind renderer
    might need (widget_state for inputs, texture_cache for images,
    emit for interactions). PR 3's only dispatched element kind
    (TextElement) uses none of them — Text is the simplest case.
    PRs 4+ migrating richer kinds will read these from
    ``self._widget_state`` etc.
    """

    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit

    def __new__(
        cls,
        *,
        widget_state: WidgetState,
        texture_cache: TextureCache,
        emit: Emit,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._texture_cache = texture_cache
        self._emit = emit
        return self

    def __call__(self, elem: Element) -> Renderer:
        """Resolve elem to its per-kind ImGui renderer.

        Raises TypeError on unrecognized element type (PY-EH-2 —
        wrong-type error). PR 4+ migrations widen the match.
        """
        match elem:
            case TextElement():
                return ImGuiTextRenderer(elem=elem)
        msg = f"no ImGui renderer for element type {type(elem).__name__}"
        raise TypeError(msg)
```

### 7.2 Shared-state ownership

The factory holds three references at startup:

- `widget_state` — the per-scene widget state object SceneManager
  manages. Future Slider/Checkbox/Combo renderers read+write through
  this.
- `texture_cache` — the GL texture cache `display/texture_cache.py`
  owns. Future Image renderer reads this.
- `emit` — the InteractionMessage channel back to the wire layer.
  Future Button/Slider renderers call `self._elem.on_click()` →
  inside `on_click` the Element calls `self._emit(InteractionMessage)`.

PR 3's `ImGuiTextRenderer` uses NONE of these. The Element-render path
for Text is:

```text
elem.render()  [Element ABC template]
  → renderer = self._renderer_factory(self)   ← ImGuiRendererFactory.__call__
  → renderer = ImGuiTextRenderer(elem=self)
  → renderer.render()                          ← draws via imgui.text_wrapped etc.
```

No `widget_state`, `texture_cache`, or `emit` touched anywhere on the
Text path. They sit unused on the factory until PR 4–5 migrates kinds
that consume them. This is **acceptable per PY-RF-2's "infrastructure
ships with first consumer"** because the **factory** is the
infrastructure and Text is its first consumer; the un-used fields are
constructor parameters the future consumers (PR 4–5) need.

### 7.3 How it integrates with the display server's existing emit pipeline

The display server (`display/server.py`) currently constructs an
`ElementRenderer(widget_state, texture_cache, table_renderer,
emit_event, check_dirty_window)`. PR 3 adds an `ImGuiRendererFactory`
instance ALONGSIDE the existing `ElementRenderer` — they coexist.
The wiring:

```python
# display/server.py — startup (existing path stays):
self._element_renderer = ElementRenderer(
    self._widget_state, self._texture_cache, self._table_renderer,
    self._emit_event, self._check_dirty_window,
)

# NEW in PR 3:
self._imgui_renderer_factory = ImGuiRendererFactory(
    widget_state=self._widget_state,
    texture_cache=self._texture_cache,
    emit=self._emit_event,
)
```

The render-loop dispatch (§9) chooses between `elem.render()` (Text
path) and `self._element_renderer.render_element(elem)` (everything
else).

## 8. Wire-layer integration plan

### 8.1 Where `Decoders.getDecoderFor` is called

Today's wire-side decode happens in `protocol/messages/scene.py` line
99 — `_scene_from_dict` calls `element_from_dict(e) for e in elements`.
This is the dispatcher PR 3 augments.

PR 3 does NOT replace this dispatcher (the migration window requires
non-Text kinds keep working). Instead, `_scene_from_dict` learns to
route Text through the new Decoder family:

```python
# protocol/messages/scene.py — _scene_from_dict (modified in commit v):

def _scene_from_dict(d: dict[str, Any]) -> SceneMessage:
    elements: list[Element] = []
    for e in d.get("elements", []):
        if e.get("kind") == "text":
            elements.append(_TEXT_DECODER.decode(e))
        else:
            elements.append(element_from_dict(e))
    # ... rest unchanged ...
```

`_TEXT_DECODER` is a module-level singleton constructed at import time:

```python
# protocol/messages/scene.py — module top:
from punt_lux.protocol.decoder_factory import Decoders, WireFormat
from punt_lux.protocol.renderers_test import NullRendererFactory

_TEXT_DECODER: DecoderFactory = Decoders.getDecoderFor(
    WireFormat.JSON,
    renderer_factory=NullRendererFactory(),
    emit=lambda _: None,
)
```

Why `NullRendererFactory` here, not `ImGuiRendererFactory`? Because
`scene.py` is the wire-decode path used by BOTH:

- The display-server inbound path (display tier — wants `ImGuiRendererFactory`).
- The MCP-tool path inside `tools/tools.py` line 132
  (`typed_elements = [element_from_dict(e) for e in elements]`) which
  runs in the hub-tier or applet-tier process — wants
  `NullRendererFactory` per io-model §"Tier-local Element
  representation".

`scene.py`'s wire decode is shared across both. **The right factory
should be passed in by the caller**, not hardcoded in `scene.py`. PR 3
takes the conservative path: hardcode `NullRendererFactory` in the
wire-decode path because (a) it's correct for the MCP-tool path, (b)
it's harmless on the display tier because `Element.render()` resolves
the factory **at render time** via the Element's stored
`self._renderer_factory` — which is `NullRendererFactory` and thus
returns `NullRenderer`, a no-op.

**But the display tier needs ImGui rendering, not no-op!** Right — and
this is where the display-server integration plan (§9) does the work.
The display server doesn't trust the wire-decoded
`renderer_factory`; it re-resolves Text Elements through its own
`ImGuiRendererFactory` at render time. The next section explains.

A cleaner long-term design is: per-connection wire-decode with the
factory passed in at connection setup. That is the PR-13 process-split
shape (per io-model §"Construction paths"). PR 3 stays single-tier
and accepts the workaround in §9 to keep the change rollback-coherent.

### 8.2 Confirmation: non-Text kinds continue through `element_from_dict`

The `_scene_from_dict` modification above explicitly preserves
`element_from_dict(e)` for `kind != "text"`. The
`ElementCodec` registry continues to handle the other 23 kinds. The
`BasicsRegistry.apply` call registers all six basics including the
Text-via-adapter (§4.2 — Text outbound stays in the registry; Text
inbound moves to JsonTextDecoder).

This is **intentional dual-vocabulary for the migration window**.
After PR 9 lands all 24 kinds onto the io-model, `element_from_dict`
becomes vestigial and gets deleted in PR 10 / PR 12.

### 8.3 What factory `tools/tools.py` passes

`tools/tools.py` line 132 calls `element_from_dict(e)` — which now
routes Text through `_TEXT_DECODER` (set up with
`NullRendererFactory` per §8.1). This is correct: `tools/tools.py`
runs in the hub-tier (the MCP server process); io-model says hub-tier
gets `NullRendererFactory`. No change to `tools/tools.py` needed for
PR 3.

## 9. Display-server integration plan

### 9.1 The dispatch decision

The display server's render loop calls
`self._element_renderer.render_element(elem)` for every Element in
every scene's element list (see `display/element_renderer.py` line
208). PR 3 modifies this dispatch site to route Text via the Element
template method:

```python
# display/server.py — inside the render loop frame:

def _render_one_element(self, elem: Element) -> None:
    if isinstance(elem, TextElement):  # io-model Element ABC subclass
        # The wire decoder injected NullRendererFactory (§8.1); we need
        # ImGui rendering on the display tier. Resolve via the display
        # server's own factory at render time.
        renderer = self._imgui_renderer_factory(elem)
        renderer.render()
    else:
        # Legacy path for non-Text kinds — PR-2 ElementRenderer.
        self._element_renderer.render_element(elem)
```

**Why not call `elem.render()` directly?** Because the wire-decoded
`TextElement` carries `NullRendererFactory` (the safe single-tier
default — see §8.1). `elem.render()` would resolve a `NullRenderer`
and draw nothing. The display server has authoritative knowledge that
it owns the ImGui surface, so it re-resolves the renderer through its
own `ImGuiRendererFactory` instance.

This is a deliberate trade-off:

- ✅ **PR 3 stays single-tier** (no process split needed); the
  factory passed at decode time is the safe `NullRendererFactory`.
- ✅ **Display tier renders ImGui** because the server picks the
  right factory at render time.
- ⚠️ **`elem.render()` template-method isn't directly invoked** for
  Text in PR 3 from the display server. The template IS invoked
  in the proving test (§12) where the factory is the `RecordingRendererFactory`
  the test injects directly.

The clean long-term shape (PR 13's process split) is:
display-tier wire-decode uses `ImGuiRendererFactory`, the display
server iterates `scene_root.render()`, and the template method runs
end-to-end with the injected factory. PR 3 holds the workaround to
keep the change rollback-coherent. The workaround is removed in PR
10 / PR 13.

### 9.2 How the dispatch is unambiguous

`isinstance(elem, TextElement)` is the discriminator. `TextElement`
in PR 3 is an ABC subclass; the PR-2 dataclass shape with the same
name is gone (replaced in commit iii). Other PR-2 element dataclasses
(Image, Button, etc.) are NOT subclasses of the Element ABC, so the
isinstance branch is true for Text alone.

After PR 4 migrates Image/Separator/Progress/Spinner/Markdown onto
the ABC, the dispatch generalises:

```python
if isinstance(elem, Element):     # Element ABC — any io-model element
    renderer = self._imgui_renderer_factory(elem)
    renderer.render()
else:
    self._element_renderer.render_element(elem)
```

By PR 9, every element is io-model and the `else` arm is dead — PR 10
deletes `ElementRenderer` entirely. PR 12 confirms.

## 10. `WidgetValueProvider` deletion plan

### 10.1 Every existing call site, enumerated

From `grep -rn "WidgetValueProvider\|widget_value" src/ tests/`:

**Production sources (`src/`):**

1. `src/punt_lux/scene/widget_value_provider.py` — the Protocol
   definition (1 file, 33 lines). DELETE entire file.
2. `src/punt_lux/scene/manager.py` lines 21, 67–78, 421–429:
   - Line 21: `from punt_lux.scene.widget_value_provider import WidgetValueProvider` — DELETE.
   - Lines 67–78: the `_widget_value(elem)` module-level function. DELETE entirely.
   - Lines 414–431 (the patch-update widget-value mirror block): SIMPLIFY.
     The block reads `new_value = _widget_value(elem)` and routes to
     `ws.set` / `ws.discard`. Replace with the explicit per-kind
     dispatch by isinstance — the seven kinds that implement
     `widget_value()` (slider, checkbox, combo, input_text,
     input_number, radio, selectable) get a flat `isinstance` chain
     reading the appropriate field; color_picker keeps the `discard`
     path (its renderer initialises with `ImVec4`, not a hex string).
     This is genuinely a wire-side mirror operation, not domain
     behavior — PR 5's inputs migration will move it onto the
     respective Element subclasses' `on_value_change` behavior methods,
     after which the entire `_update_patch` block in `manager.py` can
     route through behavior-on-Element. PR 3 just removes the
     `WidgetValueProvider` Protocol; the dispatch becomes explicit
     (and uglier-looking — that ugliness is the carrot for PR 5 to
     finish the job).
3. `src/punt_lux/protocol/elements/input_number.py` line 32:
   `def widget_value(self) -> Any:` method on `InputNumberElement`.
   DELETE method.
4. `src/punt_lux/protocol/elements/slider.py` line 28: same. DELETE.
5. `src/punt_lux/protocol/elements/input_text.py` line 25: same. DELETE.
6. `src/punt_lux/protocol/elements/checkbox.py` line 24: same. DELETE.
7. `src/punt_lux/protocol/elements/radio.py` line 25: same. DELETE.
8. `src/punt_lux/protocol/elements/combo.py` line 25: same. DELETE.
9. `src/punt_lux/protocol/elements/selectable.py` line 24: same. DELETE.

**Tests (`tests/`):**

Item 10 (continuing the numbered list above): `tests/test_scene_manager.py`
lines 363, 381, 403, 411 — four test functions reference
`WidgetValueProvider` or its protocol contract. These tests must be
REWRITTEN to assert on the new explicit-isinstance-dispatch behavior
of `manager.py`'s patch-update block. The four tests cover:

- `InputNumber` patch mirror: assert ws.set called with the
  patched value.
- `Slider` patch mirror: assert ws.set called with the patched
  value.
- `ColorPicker` patch: assert ws.discard called (not set).
- Stale value cleanup: assert ws.discard called on the right
  kinds.

The rewrites match the explicit-isinstance dispatch — same
behavior, different mechanism.

### 10.2 Confirm zero callers post-deletion

After commit iv:

- `grep -rn "WidgetValueProvider" src/ tests/` returns zero hits.
- `grep -rn "widget_value(" src/ tests/` returns zero hits (the method
  is gone from every input element).
- `grep -rn "from punt_lux.scene.widget_value_provider" src/ tests/`
  returns zero hits.
- The file `src/punt_lux/scene/widget_value_provider.py` does not exist.

This is a TOTAL deletion (PL-PP-1 — no backwards-compatibility
shims, no re-exports).

### 10.3 What replaces each call

| Call site | Pre-PR-3 | Post-PR-3 (commit iv) |
|-----------|----------|----------------------|
| `manager.py` _widget_value(elem) | Protocol dispatch | Explicit isinstance chain |
| `*Element.widget_value()` method | Returned the value field | DELETED; the dispatch reads `elem.value` directly |
| `test_scene_manager` Protocol assertions | Asserted isinstance vs Protocol | Asserts on ws.set / ws.discard call shapes |

The isinstance chain is uglier than the Protocol — that's the point.
PR 5 makes it disappear by routing widget-value mirroring through
each Element's `on_value_change` behavior method (the Element decides
what to publish; SceneManager doesn't dispatch anymore). PR 3 just
deletes the Protocol; the ugliness is incentive for PR 5 to finish.

## 11. Internal commit sequence

Six commits, in dependency order. Each passes `make check` +
`make snapshot-parity` and local code-reviewer + silent-failure-hunter
agents before the next commit lands. Code + test land together per
The Bar §10.

### Commit (i) — RecordingRenderer + NullRenderer + their tests

**Scope:** Land the test-surface renderer family. No production
code depends on these yet; the consumer is the test fixture exercising
both renderers with a synthetic Element subclass.

**Files created:**

- `src/punt_lux/protocol/renderers_test.py` (~80 lines, 4 classes —
  `RecordingRenderer`, `RecordingRendererFactory`, `NullRenderer`,
  `NullRendererFactory`)
- `tests/protocol/__init__.py` (empty — package marker)
- `tests/protocol/test_renderers_test.py` (~120 lines — see §12.1)
- `tests/render/__init__.py` (empty — package marker for the new test
  tier introduced by the migration plan)

**Files modified:** None.

**Files deleted:** None.

**PY-RF-2 consumer:** `tests/protocol/test_renderers_test.py` —
exercises both renderers with a synthetic `_FakeElement` subclass
inside the test fixture. The renderers are genuinely generic, so the
test is their production caller.

**Note:** This commit ships production code (`renderers_test.py`)
that does NOT yet have an `Element` to operate on (the ABC arrives in
commit ii). The test fixture's `_FakeElement` uses the existing
`Element` Protocol from `domain/element.py` (which has `id` and `kind`
properties — exactly what `RecordingRenderer` reads). The test is
forward-compatible with the ABC arriving in commit ii.

### Commit (ii) — Element ABC + Renderer/RendererFactory/Decoder/DecoderFactory Protocols + Surface/WireFormat enums + Renderers/Decoders registries + RED TextElement test

**Scope:** Land all the infrastructure modules that wire elements
to renderers and decoders. Write a failing test for the
io-model `TextElement` that fails because the io-model `TextElement`
doesn't exist yet.

**Files created:**

- `src/punt_lux/domain/element_base.py` (~85 lines — Element ABC)
- `src/punt_lux/protocol/renderer.py` (~40 lines — Renderer Protocol)
- `src/punt_lux/protocol/renderer_factory.py` (~80 lines —
  RendererFactory + Surface + Renderers)
- `src/punt_lux/protocol/decoder.py` (~40 lines — Decoder Protocol)
- `src/punt_lux/protocol/decoder_factory.py` (~80 lines —
  DecoderFactory + WireFormat + Decoders)
- `tests/protocol/test_element_base.py` (~80 lines — exercises
  Element ABC's template method with `_FakeLeaf` / `_FakeComposite`
  subclasses against `RecordingRenderer`)
- `tests/render/test_text_render.py` (~40 lines — RED test that
  imports `TextElement` from the new ABC and asserts the
  `(render, text, t1)` Recording tuple — fails because PR-2's
  dataclass `TextElement` doesn't accept `renderer_factory` /
  `emit` kwargs)

**Files modified:** None.

**Files deleted:** None.

**PY-RF-2 consumer:** `test_element_base.py` exercises the ABC's
template method (leaf + composite branches) with synthetic subclasses
and `RecordingRenderer` from commit (i). The Element ABC is the
consumer for Renderer + RendererFactory + Surface + Renderers (it
uses them in the template). The Decoder family lacks a consumer in
commit (ii) — covered by commit (iii)'s `JsonTextDecoder` test
landing within ~hours. **This is the only commit where the Decoder
infrastructure is dead for the duration between commits ii and iii.**
The mitigation: commit ii ends with the RED `test_text_render.py`
that references the Decoder family in its import block — if
commit iii doesn't land within the same PR, `make check` on commit
ii alone passes (the test is marked `xfail(strict=True)`) — but the
import-time check verifies the Decoder family compiles, so it isn't
dead.

`xfail(strict=True)` is the one acceptable test marker per PL-TT-6
when it's a true placeholder turning GREEN one commit later — and
PL-TT-6 forbids it permanent. Commit iii REMOVES the xfail mark when
the GREEN test passes.

**Alternative considered & rejected:** combining commits ii and iii
into one larger commit. Rejected because the diff would be 8+ files
modified and ~700 lines added, exceeding the 30-min-of-uncommitted-
work safety budget (CLAUDE.md "stuck workers" rule) and breaking
incremental review. Two commits keep each diff under 400 lines.

### Commit (iii) — TextElement on ABC + JsonTextDecoder + ImGuiRendererFactory + ImGuiTextRenderer — proving test goes GREEN

**Scope:** Migrate TextElement to the ABC. Build its JSON decoder.
Build the ImGui factory and rewrite ImGuiTextRenderer. The RED test
from commit ii turns GREEN here.

**Files created:**

- `src/punt_lux/protocol/decoders_json.py` (~110 lines — 2 classes:
  JsonDecoderFactory + JsonTextDecoder)
- `src/punt_lux/display/imgui_renderer_factory.py` (~90 lines —
  ImGuiRendererFactory)
- `tests/protocol/test_decoders_json.py` (~80 lines —
  JsonTextDecoder roundtrip test, including the byte-identical-wire
  parity assertion)
- `tests/display/test_imgui_renderer_factory.py` (~50 lines —
  factory dispatches TextElement to ImGuiTextRenderer)

**Files modified:**

- `src/punt_lux/protocol/elements/text.py` — REWRITTEN per §3.1.
  PR-2's `@dataclass` shape becomes an `Element` ABC subclass with
  `__new__`. `to_dict` / `from_dict` methods DELETED.
- `src/punt_lux/display/renderers/text_renderer.py` — class renamed
  `TextRenderer` → `ImGuiTextRenderer` per §5. Re-shape to hold
  `_elem` and implement `Renderer` Protocol.
- `src/punt_lux/protocol/elements/basics.py` — `register("text",
  TextElement, TextElement.to_dict, TextElement.from_dict)` →
  `register("text", TextElement, _text_to_dict_for_parity,
  _text_from_dict_for_parity)`. Add the two adapter functions per
  §4.2.
- `src/punt_lux/protocol/messages/scene.py` — `_scene_from_dict`
  routes Text via `_TEXT_DECODER` (see §8.1).
- `src/punt_lux/display/server.py` — construct
  `self._imgui_renderer_factory` in `__new__`; modify the per-element
  render dispatch in the render loop per §9.1.
- `src/punt_lux/display/element_renderer.py` — REMOVE the
  `TextElement` arm from `_NATIVE_DISPATCH` (line 152), REMOVE
  `_text_renderer` field and its construction. Update
  `element_kind_count`. (The Text dispatch arm of `ElementRenderer`
  goes away; non-Text kinds still dispatch through it.)
- `tests/render/test_text_render.py` — remove the `xfail(strict=True)`
  mark. Test goes GREEN.

**Files deleted:**

- `src/punt_lux/domain/element.py` (the old Protocol). Replaced by
  the renamed `element_base.py` → `element.py` (file rename — git
  follows it as one commit operation).

**PY-RF-2 consumer:** `TextElement` is the consumer for the Element
ABC (it's the first subclass). `JsonTextDecoder` is the consumer for
the Decoder + DecoderFactory + WireFormat + Decoders registry chain.
`ImGuiTextRenderer` is the consumer for the Renderer + RendererFactory
together with Surface and Renderers (ImGui arm). `ImGuiRendererFactory`
is the consumer that owns surface-shared state. Snapshot parity tests
(via `make snapshot-parity`) are the cross-cutting consumer that
verifies wire-bytes-identity for Text.

### Commit (iv) — WidgetValueProvider deletion

**Scope:** Total deletion of the Protocol and every reference.
Replace the SceneManager dispatch with explicit isinstance chains
per §10.

**Files created:** None.

**Files modified:**

- `src/punt_lux/scene/manager.py` — remove import, remove
  `_widget_value(elem)` function, rewrite the patch-update
  widget-value-mirror block to use explicit isinstance dispatch on
  the seven kinds that previously implemented `widget_value()`.
- `src/punt_lux/protocol/elements/input_number.py` — remove
  `widget_value()` method (3 lines).
- `src/punt_lux/protocol/elements/slider.py` — remove `widget_value()` method.
- `src/punt_lux/protocol/elements/input_text.py` — remove `widget_value()` method.
- `src/punt_lux/protocol/elements/checkbox.py` — remove `widget_value()` method.
- `src/punt_lux/protocol/elements/radio.py` — remove `widget_value()` method.
- `src/punt_lux/protocol/elements/combo.py` — remove `widget_value()` method.
- `src/punt_lux/protocol/elements/selectable.py` — remove `widget_value()` method.
- `tests/test_scene_manager.py` — rewrite four tests (lines ~360–420)
  to assert on the new explicit-isinstance behavior. Same test names,
  same coverage, different mechanism.

**Files deleted:**

- `src/punt_lux/scene/widget_value_provider.py`

**PY-RF-2 consumer:** Deletion commits don't add infrastructure;
PY-RF-2 N/A. PL-PP-1 (no backwards-compat) is the relevant rule —
total deletion, no shims.

### Commit (v) — Wire-layer routing for Text

**Scope:** The wire-decode-side routing modification. This is split
from commit iii because §8.1's modification to `scene.py` is logically
distinct from the TextElement-on-ABC change and benefits from being
reviewed separately (it changes which decoder runs for a "kind":"text"
payload from anywhere in the system).

**Files created:** None.

**Files modified:**

- `src/punt_lux/protocol/messages/scene.py` — already modified in
  commit iii (per §8.1). Wait — this commit is actually unnecessary
  if commit iii covers it. **Refining:** commit v from the migration
  plan was "wire-layer and display-server routing for Text" — both
  bits land in commit iii already. **Collapse commit v INTO commit
  iii's modification list.**

**Decision:** Drop commit v as a separate step. The migration plan's
six-commit sequence is preserved by promoting the "Old TextElement
scaffolding deletion" (originally commit vi) into commit v, and
adding a new commit vi for documentation/CHANGELOG.

Revised sequence:

- (i) Test-surface renderers (Recording + Null)
- (ii) ABC + Protocols + registries + RED test
- (iii) TextElement migration + JsonTextDecoder + ImGuiRendererFactory + ImGuiTextRenderer + wire-layer routing for Text + display-server routing for Text (GREEN)
- (iv) WidgetValueProvider deletion
- (v) Old TextElement scaffolding deletion / verification
- (vi) CHANGELOG + docs update

### Commit (v, revised) — Old TextElement scaffolding deletion

**Scope:** Verify no remaining references to the PR-2 TextElement
shape; delete any Text-specific dispatch in `element_renderer.py`
that remains; delete the BasicsRegistry's PR-2 register-call shape
for "text" (already replaced in commit iii — verify only); confirm
`grep -rn "TextRenderer\b"` returns zero hits (only `ImGuiTextRenderer`
remains).

**Files created:** None.

**Files modified:** likely zero — commit iii already removes the
Text dispatch from `element_renderer.py`. This commit is a
**verification commit** that runs:

```bash
grep -rn "class TextRenderer\b" src/                  # expect 0
grep -rn "TextElement\.to_dict\|TextElement\.from_dict" src/  # expect 0
grep -rn "WidgetValueProvider" src/ tests/            # expect 0
grep -rn "_widget_value(" src/ tests/                 # expect 0
```

If any of these returns hits, fix them in this commit. If zero — the
commit is empty and gets folded into commit iv as a verification
note in the commit message.

**Files deleted:** None expected; any straggler reference gets
cleaned here.

**PY-RF-2 consumer:** N/A — verification only.

### Commit (vi) — CHANGELOG + docs update

**Scope:** Document the io-model infrastructure landing and the Text
migration in the appropriate docs. Chore commit — no production code.

**Files created:** None.

**Files modified:**

- `CHANGELOG.md` — `## [Unreleased]` entry under "Changed": "Text
  elements now use the io-model infrastructure: codec moved off the
  Element class into JsonTextDecoder, render() lives on the Element
  ABC via template method, factories injected at construction.
  Other element kinds continue using the PR-2 shape until their
  migration PR (PR 4 and beyond)."
- `CHANGELOG.md` under "Removed": "`WidgetValueProvider` Protocol —
  inputs were the only consumer; deletion is in scope per the io-model
  migration."
- `docs/oo-refactor/resume.md` — record PR 3 done; update the
  remaining-PRs list.
- `README.md` — no user-visible change in PR 3; skip.

**PY-RF-2 consumer:** N/A — documentation.

## 12. Test plan

### 12.1 Commit (i) — `test_renderers_test.py`

```python
# tests/protocol/test_renderers_test.py

from __future__ import annotations

from typing import Self

import pytest

from punt_lux.domain.element import Element  # Pre-ABC Protocol
from punt_lux.protocol.renderers_test import (
    NullRenderer,
    NullRendererFactory,
    RecordingRenderer,
    RecordingRendererFactory,
)


class _FakeElement:
    """Synthetic Element-Protocol-satisfying class for renderer tests.

    Satisfies the existing Element Protocol (PR-1+2 shape) — has id,
    kind, tooltip properties. Does not implement to_dict / from_dict
    since RecordingRenderer / NullRenderer never call those.
    """

    def __init__(self, id: str, kind: str) -> None:
        self._id = id
        self._kind = kind

    @property
    def id(self) -> str:
        return self._id

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def tooltip(self) -> str | None:
        return None


def test_recording_renderer_logs_render() -> None:
    log: list[tuple[str, str, str]] = []
    elem = _FakeElement(id="x1", kind="fake")
    renderer = RecordingRenderer(elem=elem, log=log)
    renderer.render()
    assert log == [("render", "fake", "x1")]


def test_recording_renderer_logs_begin_end() -> None:
    log: list[tuple[str, str, str]] = []
    elem = _FakeElement(id="g1", kind="group")
    renderer = RecordingRenderer(elem=elem, log=log)
    renderer.begin()
    renderer.end()
    assert log == [("begin", "group", "g1"), ("end", "group", "g1")]


def test_recording_renderer_factory_shares_log_across_calls() -> None:
    factory = RecordingRendererFactory()
    a = _FakeElement(id="a", kind="x")
    b = _FakeElement(id="b", kind="y")
    factory(a).render()
    factory(b).render()
    assert factory.log == (("render", "x", "a"), ("render", "y", "b"))


def test_null_renderer_is_noop() -> None:
    renderer = NullRenderer()
    renderer.render()      # raises nothing
    renderer.begin()
    renderer.end()


def test_null_renderer_factory_returns_same_instance() -> None:
    factory = NullRendererFactory()
    a = _FakeElement(id="a", kind="x")
    b = _FakeElement(id="b", kind="y")
    # Flyweight — same singleton for every element (no state needed).
    assert factory(a) is factory(b)
```

The synthetic `_FakeElement` is the test-fixture consumer that satisfies
PY-RF-2 for commit (i).

### 12.2 Commit (ii) — `test_element_base.py`

Test the Element ABC's template method with synthetic leaf + composite
subclasses against the `RecordingRenderer` from commit (i):

```python
# tests/protocol/test_element_base.py

# Leaf test: subclass that overrides nothing — calls render() on its
# resolved Renderer (the RecordingRenderer captures ("render", kind, id))

# Composite test: subclass that overrides _children — calls begin() →
# child.render() → end() — RecordingRenderer captures the full sequence

# Both tests verify:
# - super().__new__(cls, renderer_factory=..., emit=...) chain works
# - _renderer_factory and _emit are accessible to subclass code
# - The template method's branching is correct
```

### 12.3 Commit (ii) — `test_text_render.py` (the proving test, RED state)

```python
# tests/render/test_text_render.py

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.renderers_test import RecordingRendererFactory


@pytest.mark.xfail(strict=True, reason="TextElement migrates to ABC in commit iii")
def test_text_element_render_under_recording() -> None:
    """The proving test for the io-model + Text migration.

    Construct a TextElement with a RecordingRendererFactory, call
    text.render(), assert the captured (op, kind, id) tuple is
    ("render", "text", "t1"). This is the smallest possible end-to-end
    exercise of the io-model: Element ABC template → injected factory
    → resolved Renderer → recorded op.

    RED in commit ii because PR-2's TextElement is still a frozen
    dataclass that doesn't accept renderer_factory / emit kwargs.
    GREEN in commit iii after the migration lands.
    """
    factory = RecordingRendererFactory()
    text = TextElement(
        renderer_factory=factory,
        emit=lambda _msg: None,
        id="t1",
        content="hello",
    )
    text.render()
    assert factory.log == (("render", "text", "t1"),)
```

The `xfail(strict=True)` mark goes away in commit iii's modification
list. PL-TT-6 forbids permanent `xfail` — strict + commit-iii removal
is the one acceptable use.

### 12.4 Commit (iii) — `test_decoders_json.py`

```python
# Test 1: JsonTextDecoder roundtrip.
# Wire dict → JsonTextDecoder.decode → TextElement → assert fields.

# Test 2: JsonDecoderFactory dispatch.
# Wire dict with kind="text" → factory.decode → TextElement.
# Wire dict with kind="unknown" → ValueError (PY-EH-8).

# Test 3: Byte-identical snapshot parity for Text.
# Compose a wire dict shape PR-2's TextElement.from_dict accepts; decode
# it via JsonTextDecoder; serialise the result via the adapter from §4.2;
# assert the output dict equals the input dict (modulo field-order
# normalisation matching PR-2's to_dict).

# Test 4: Boundary validation passthrough.
# Wire dict missing "id" → ValueError raised by ElementWireContext
# (PY-EH-1 — same boundary validator used by PR-2's from_dict).
```

### 12.5 Commit (iii) — `test_imgui_renderer_factory.py`

```python
# Test: ImGuiRendererFactory dispatches TextElement → ImGuiTextRenderer.
# Construct factory with mock widget_state / texture_cache / emit;
# pass a TextElement instance; assert the returned object isinstance
# ImGuiTextRenderer and that the renderer holds the same _elem reference.

# Test: ImGuiRendererFactory raises TypeError on unrecognized type.
# Pass an Element subclass the factory doesn't know about; expect
# TypeError per §7.1.
```

### 12.6 Commit (iv) — `test_scene_manager.py` four-test rewrite

Tests preserved by name + behavior, mechanism updated per §10.3.

### 12.7 Commit (v) — verification grep tests

A small `tests/test_widget_value_provider_gone.py` that asserts the
deletion is total by running grep-like checks via Python's
`importlib` (verifies the module cannot be imported) and `ast.parse`
(verifies no `widget_value(` method definitions remain in the inputs
files). Belt-and-suspenders for PL-PP-1.

### 12.8 Snapshot-parity coverage

`make snapshot-parity` re-runs the existing PR-0 corpus
(`tests/characterization/snapshots/`). The Text snapshots therein
exercise:

- Text with content + style + color combinations (every style branch).
- Text with tooltip (the selectable() branch).
- Text in nested groups and tabs.

All snapshots must pass byte-identically after commit iii (when the
adapter is wired) and after every subsequent commit. The CI gate runs
on every commit.

## 13. Construction-path ergonomics

### 13.1 The open question

For in-process callers (tests, MCP tools, scene-builders) that don't
have a factory in scope, what's the convenience path?

### 13.2 Resolution

**Decision: in-process callers pass `NullRendererFactory()` and
`lambda _: None` explicitly. No convenience helper is shipped.**

Why no `TextElement.from_wire(d)` classmethod or `make_text(id, content)`
module helper:

1. **Tests should construct factories explicitly.** Tests that exercise
   render behavior pass `RecordingRendererFactory()`; tests that
   exercise non-render behavior pass `NullRendererFactory()`. A
   convenience helper hides which one — making it easy to write a
   "no-op test" that secretly never exercises render even though the
   test name says it does. Explicit is better than implicit (Zen #2).
2. **MCP tools (`tools/tools.py`) already construct Elements
   via the wire path** (`element_from_dict`, which after §8.1 routes
   Text through `_TEXT_DECODER` with `NullRendererFactory` baked in).
   MCP tools do NOT construct `TextElement(...)` directly — they
   build wire dicts. So MCP tools don't need a convenience helper.
3. **Scene-builders (`apps/beads.py` `BeadsBrowser`) construct
   Elements via the wire-dict path too** — `show_table(...)` builds
   a dict and calls the MCP server. Same as MCP tools.
4. **The display server constructs Elements via the wire-decode
   path**, which provides the factory at decode time. No direct
   construction.
5. **The remaining callers are tests.** Forcing tests to be explicit
   about which factory they use is a feature.

The Python verbosity for the rare in-process construction case:

```python
# in-process direct construction (rare):
text = TextElement(
    renderer_factory=NullRendererFactory(),
    emit=lambda _: None,
    id="t1",
    content="hello",
)
```

That's 6 lines for a 1-line concept. Three of those lines are
boilerplate. If this becomes a real pain (post-PR-9, post-PR-13),
revisit then — but PR 3 doesn't have a use case that warrants the
convenience helper.

**Why not a factory-class-method (`TextElement.standalone(id, content)`):**
classmethods that hide constructor parameters are a leaky abstraction
— calls that say "I want a Text" silently inject `NullRendererFactory`
without naming what was chosen. The next maintainer reading the call
site has to read the classmethod source to understand what factory
was injected. Explicit kwargs are more readable.

**Why not a module-level helper (`make_null_text(id, content)`):**
same issue (hidden factory choice), plus PY-OO-7 ("no fake OO. Helpers
in the same module as a class are missing methods"). A
`make_null_text` helper next to `TextElement` would be exactly the
pattern that rule forbids.

**Why not a default factory in the registry:**
this was tempting but dangerous. If `Renderers` had a "default" that
returned `NullRendererFactory()`, code calling `Renderers.getRendererFor(
Surface.NULL)` would silently work — and the day someone meant
`Surface.IMGUI` and typoed, they'd get silent no-op rendering instead
of a clear error. Explicit dispatch + explicit factory injection
keeps construction failure modes loud.

## 14. Out-of-scope items

Per the mission scope, the following are explicitly NOT in PR 3:

- **Encoder family** (PR 10). First consumer is Events to clients.
  Building it here without a consumer is a PY-RF-2 violation.
- **Other basics migrations** (Image, Separator, Progress, Spinner,
  Markdown) — PR 4. Mechanical replication of PR 3's pattern.
- **Inputs family migrations** (Button + 8 others) — PR 5. Adds
  behavior methods to Element subclasses.
- **Layout family migrations** (Group, Window, TabBar, …) — PR 6.
- **Graphics / Table / Plot family migrations** — PRs 7, 8, 9.
- **HTML renderer** — deferred. No consumer in PR 3 (or PR 9).
  Surface.HTML is intentionally omitted from PR 3's `Surface` enum
  (only IMGUI / RECORDING / NULL); reintroducing it when a consumer
  exists is a one-line `Surface.HTML = "html"` change + a registry
  match arm.
- **Process split / IPC topology** (PR 13). PR 3 stays single-tier;
  the workarounds in §8.1 and §9.1 (`NullRendererFactory` baked into
  `scene.py`; display server re-resolves factory at render time) hold
  the single-tier shape together until PR 13 splits processes.
- **Element behavior methods** (on_click, on_value_change, on_toggle).
  Forward-looking only — the ABC accommodates them per §2.8 but Text
  has none.
- **Connection-layer cleanup beyond Text dispatch** — the
  format-negotiation slot, per-connection decoder lifecycle, and the
  DomainPump simplification are PR 10 work.
- **Three-layer type model implementation** (DES-030 — wire / scene
  graph / snapshot tiers). PR 3's `TextElement` is wire+scene-graph
  in one class. The third tier (snapshot — frozen, hashable, no
  factories) is not built; the §3.2 hashability decision leaves it
  for when a use case appears.

## 15. Escalations

None at design time. The architecture in
`docs/architecture/archive/io-model.md`,
`docs/architecture/target/ui-model.md`, and `DESIGN.md` DES-031/032/033 is
internally
consistent and the design above realizes it cleanly. Two areas were
near-escalations during design:

1. **`renderer_factory` is unused on hub/applet tiers** (per the archived
   io-model design's §"What this means for renderer_factory injection on
   Element"). The
   constructor parameter is "dead weight" on those tiers. The
   resolution: io-model already acknowledges this and accepts the
   uniformity cost ("the injected factory is dead weight but keeps
   the constructor signature uniform across tiers"). Not an
   escalation — design choice already made and documented.

2. **`scene.py`'s wire decoder uses a baked-in `NullRendererFactory`**
   (§8.1) and the display server re-resolves the factory at render
   time (§9.1). This is a single-tier workaround that goes away in
   PR 13 when per-connection factories become possible. It's an ugly
   transitional state, not an architectural debt — naming it here so
   gvr's review can confirm the trade-off is the right one for PR 3's
   rollback-coherence goal.

## 16. Review checklist for gvr

Before accepting this design, please confirm:

- [ ] Module layout (§1) — every module sized ≤300 lines per PY-OO-2,
      every module purpose clear, the factory+enum+registry
      co-location justified.
- [ ] Class signatures (§2) — every constructor uses `__new__` with
      keyword-only injected dependencies; every method has type
      annotations.
- [ ] `Element.__new__` open question (§2.2) — manual `__new__` on
      subclasses chosen; rationale cited PY-CC-1 and PY-OO-7.
- [ ] TextElement hashability (§3.2) — not hashable; rationale cited
      DES-032 (injected factories aren't hashable) and PY-RF-2 (no
      consumer for value-equality).
- [ ] Snapshot-parity strategy (§4.2) — `BasicsRegistry` registers a
      module-level adapter that emits the same bytes as PR-2's
      `to_dict`; bridge dies in PR 10's Encoder family work.
- [ ] WidgetValueProvider deletion (§10) — every call site
      enumerated, zero callers post-deletion, no shims (PL-PP-1).
- [ ] Internal commit sequence (§11) — six commits (or five plus
      a chore), each PY-RF-2-satisfying, tests-with-code per
      The Bar §10.
- [ ] Wire-layer + display-server workarounds (§8.1, §9.1) — the
      single-tier transitional state is the right trade-off for PR
      3's rollback-coherence; PR 13 cleans it up.
- [ ] Construction ergonomics (§13) — no convenience helper; explicit
      factory injection is the convention.
- [ ] Out-of-scope (§14) — every named omission is correctly deferred
      to its respective downstream PR.

If any of these is wrong, please reflect with `ethos mission reflect
m-2026-05-23-003 --file <reflection.yaml>` so round 2 can address it
specifically.
