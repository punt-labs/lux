# Phase A — Protocol Package Split (Design)

**Status:** APPROVED by gvr 2026-05-20. PR 1 (elements) implementing as PR #169; PR 2 (messages) follows under lux-skc7.
**Mission:** `m-2026-05-16-001`. Worker: rmh. Evaluator: gvr.
**Beads:** lux-9i26 (elements), lux-skc7 (messages). Blocks lux-n5ep (ElementCodec)
and clears a partition obstacle for lux-ayeh / lux-5rk7 (three-layer model).

## Problem

Two protocol files are the only remaining blockers for module-size and
classes-per-module on the protocol layer:

| File | Lines | Dataclasses | module_size | classes_per_module | method_ratio |
|------|------:|------------:|------------:|-------------------:|-------------:|
| `protocol/elements.py` | 1,013 | 27 | FAIL (target ≤300) | FAIL (target ≤3, current 9x over) | 0.078 |
| `protocol/messages.py` | 570 | 22 | FAIL | FAIL (7x over) | 0.115 |

These two files hold 51 of the 65 dataclasses in the package. Until they
split, the protocol layer cannot make room for scene-graph nodes (DES-030,
lux-5rk7) or typed patches (lux-6jw9) without making `classes_per_module`
dramatically worse. The split is a prerequisite for Phase C, not an
aesthetic refactor.

Two structural facts shape the partition:

1. The wire types come in **families**. Twenty-three of the 27 element
   classes have the same shape: a flat dataclass with one or two
   serializer/deserializer helpers and no internal coupling. Four
   (`TableElement`, `TableFilter`, `TableDetail`, `Patch`) carry
   `__post_init__` validation and reference each other.
2. The protocol package has **exactly one external boundary that matters**:
   the public re-export surface in `protocol/__init__.py`. Every caller
   in the codebase (`src/` and `tests/`) imports through the package. The
   only direct submodule imports are from `protocol.messages` to access
   `MessageRegistry` and `_registry` (test isolation). The split is
   internal and the cost of changing it is bounded.

---

## Section 1 — Partition for `protocol/elements.py`

### Proposed files (5 modules + `__init__.py` aggregator)

| New file | Dataclasses | Est. lines | Family |
|----------|-------------|-----------:|--------|
| `protocol/elements/__init__.py` | (re-exports + `Element` union + dispatch) | ~180 | Aggregator |
| `protocol/elements/basics.py` | `TextElement`, `MarkdownElement`, `SeparatorElement`, `ImageElement`, `ProgressElement`, `SpinnerElement` | ~210 | Static display primitives |
| `protocol/elements/inputs.py` | `ButtonElement`, `CheckboxElement`, `SliderElement`, `ComboElement`, `RadioElement`, `InputTextElement`, `InputNumberElement`, `ColorPickerElement`, `SelectableElement` | ~290 | Interactive controls |
| `protocol/elements/layout.py` | `GroupElement`, `TabBarElement`, `CollapsingHeaderElement`, `WindowElement`, `ModalElement`, `TreeElement` | ~250 | Layout containers (own children) |
| `protocol/elements/graphics.py` | `DrawElement`, `PlotElement` | ~80 | 2D canvas / chart |
| `protocol/elements/table.py` | `TableFilter`, `TableDetail`, `TableElement` | ~210 | Tabular data + validation cluster |
| `protocol/elements/patch.py` | `Patch` | ~40 | Update message payload (lives here, not in messages, because patches reference element field shapes) |

Estimated lines include each class definition, its `_xxx_to_dict`,
`_xxx_from_dict`, and any `__post_init__`. Every target is ≤300 lines.

### Why this partition, not the bead's suggestion

The bead description proposes `interactive_elements`, `layout_elements`,
`display_elements`, `table_elements`. Two adjustments:

1. **Split `graphics` from `basics`**. `DrawElement` and `PlotElement` are
   the only two elements that carry list-of-dict commands or list-of-dict
   series. They are visually display-output but structurally heavyweight
   and likely to grow when Phase C adds typed `DrawCommand` /
   `PlotSeries` patches. Keeping them adjacent to small static blocks
   (Text, Separator, Spinner) blurs that growth boundary.
2. **Promote `Patch` to its own module.** `Patch` is one tiny dataclass
   plus its codec, and it is referenced by `UpdateMessage` over in
   `messages.py`. Burying it inside `table.py` (the bead's wording)
   couples it to a sibling it has nothing to do with. A dedicated
   `patch.py` mirrors how `UpdateMessage` lives separate from the scene
   messages and gives lux-6jw9 (typed patches) a natural home.

### Coupling justification

The element classes have almost no cross-references today. The exceptions:

- `TableElement` holds `TableFilter` and `TableDetail` — clustered in `table.py`.
- `GroupElement`, `TabBarElement`, `CollapsingHeaderElement`,
  `WindowElement`, `ModalElement`, `TreeElement` hold `list[Any]`
  children. These containers all defer to `_element_to_dict` /
  `element_from_dict` for child recursion. The recursion goes through
  the package boundary (`protocol/elements/__init__.py`), so containers
  in `layout.py` do not need a sibling-import.

The `inputs.py` cluster is the largest by class count (9). All nine share
the pattern `(id, label, kind, value, tooltip)` and the same trivial
codec shape. Even at ~290 lines it stays under 300; if it grows in
future phases, `inputs.py` is the next natural split (e.g. split
`inputs/buttons.py` vs `inputs/values.py`). The current single file
captures the cluster as one cohesive unit.

### Future-work fit

| Phase C addition | Where it lands |
|------------------|----------------|
| `TableNode` (scene graph, mutable) | `scene/nodes/table.py` — sibling to `protocol/elements/table.py` |
| `SliderPatch`, `CheckboxPatch`, … (typed patches) | `protocol/elements/inputs.py` adds `XxxPatch` next to `XxxElement` |
| `ElementCodec` registry (lux-n5ep) | replaces module-level `_ELEMENT_SERIALIZERS` in `protocol/elements/__init__.py` |

Without the split, each of these forces the choice between adding to an
already-failing god module or scattering a typed addition far from the
wire type it patches. With the split, every addition has an obvious
local home next to the type it depends on.

---

## Section 2 — Partition for `protocol/messages.py`

### Proposed files

| New file | Dataclasses | Est. lines | Family |
|----------|-------------|-----------:|--------|
| `protocol/messages/__init__.py` | (re-exports + `ClientMessage`/`DisplayMessage`/`Message` unions + `_registry` population) | ~190 | Aggregator |
| `protocol/messages/registry.py` | `MessageRegistry` class | ~80 | Codec dispatch |
| `protocol/messages/scene.py` | `SceneMessage`, `UpdateMessage`, `ClearMessage` | ~120 | Scene replacement / patching |
| `protocol/messages/lifecycle.py` | `ReadyMessage`, `ConnectMessage`, `AckMessage`, `PingMessage`, `PongMessage`, `UnknownMessage` | ~140 | Connection / heartbeat / handshake |
| `protocol/messages/interaction.py` | `InteractionMessage` | ~60 | User → agent events |
| `protocol/messages/menu.py` | `MenuMessage`, `RegisterMenuMessage`, `ThemeMessage` | ~80 | Display configuration commands |
| `protocol/messages/introspect.py` | `IntrospectRequest`, `IntrospectResponse`, `ListScenesRequest`, `ListScenesResponse`, `ScreenshotRequest`, `ScreenshotResponse`, `QueryRequest`, `QueryResponse` | ~240 | Request/response pairs |

Every target is ≤300 lines. The largest is `introspect.py` at ~240, which
clusters eight request/response classes that share the request/response
discipline (matched type strings, optional `error` field). If it grows in
a future phase, `introspect.py` splits cleanly into `query.py` and
`introspect.py` along the request/response/screenshot/list axis.

### Alignment with `elements` partition

| Element module | Message module | Relationship |
|----------------|----------------|--------------|
| `elements/__init__.py` (Element union) | `messages/scene.py` | `SceneMessage.elements: list[Element]` |
| `elements/patch.py` (Patch) | `messages/scene.py` | `UpdateMessage.patches: list[Patch]` |
| `elements/inputs.py` (Button, Slider, …) | `messages/interaction.py` | `InteractionMessage.element_id` references input element IDs |
| (none — pure display) | `messages/menu.py` | Menu commands are independent of elements |

Two intentional non-alignments:

1. **`messages/lifecycle.py` has no element counterpart**, because
   lifecycle messages carry no element data. Putting `ReadyMessage` and
   `PingMessage` in a "control" module alongside menu/theme would mix
   the connection lifecycle (one-time handshake) with the menu lifecycle
   (per-scene). Different cadences, different concerns.
2. **`messages/registry.py` is a class file, not a family file.**
   `MessageRegistry` is the only class in the protocol layer that owns
   shared mutable state (the codec dispatch tables). Isolating it makes
   the test isolation pattern (`from punt_lux.protocol.messages.registry
   import MessageRegistry`) explicit instead of fishing inside the
   message family aggregator.

---

## Section 3 — Re-export plan for `protocol/__init__.py`

The package's external `__init__.py` (the wire-framing module at
`protocol/__init__.py`) keeps its current `__all__` unchanged. After the
split, its imports change shape but not content:

```python
# Before
from punt_lux.protocol.elements import (
    ButtonElement, CheckboxElement, …, element_from_dict, element_to_dict,
)
from punt_lux.protocol.messages import (
    PROTOCOL_VERSION, AckMessage, …, message_from_dict, message_to_dict,
)

# After — same names, sourced from sub-packages
from punt_lux.protocol.elements import (
    ButtonElement, CheckboxElement, …, element_from_dict, element_to_dict,
)
from punt_lux.protocol.messages import (
    PROTOCOL_VERSION, AckMessage, …, message_from_dict, message_to_dict,
)
```

Identical lines. The sub-package `__init__.py` files do the heavy lifting:

```python
# protocol/elements/__init__.py
from punt_lux.protocol.elements.basics import (
    ImageElement, MarkdownElement, ProgressElement, SeparatorElement,
    SpinnerElement, TextElement,
)
from punt_lux.protocol.elements.inputs import (
    ButtonElement, CheckboxElement, ColorPickerElement, ComboElement,
    InputNumberElement, InputTextElement, RadioElement, SelectableElement,
    SliderElement,
)
# … etc.

Element = (
    ImageElement | TextElement | ButtonElement | …  # union assembled here
)

# Dispatch tables built from per-module contributions
_ELEMENT_SERIALIZERS: dict[type, Callable[..., dict[str, Any]]] = {
    **basics._SERIALIZERS,
    **inputs._SERIALIZERS,
    **layout._SERIALIZERS,
    **graphics._SERIALIZERS,
    **table._SERIALIZERS,
}

def element_to_dict(elem: Element) -> dict[str, Any]: ...
def element_from_dict(d: dict[str, Any]) -> Element: ...
```

### Explicit `__all__` for `protocol/elements/__init__.py`

```python
__all__ = [
    "ButtonElement", "CheckboxElement", "CollapsingHeaderElement",
    "ColorPickerElement", "ComboElement", "DrawElement", "Element",
    "GroupElement", "ImageElement", "InputNumberElement",
    "InputTextElement", "MarkdownElement", "ModalElement", "Patch",
    "PlotElement", "ProgressElement", "RadioElement", "SelectableElement",
    "SeparatorElement", "SliderElement", "SpinnerElement", "TabBarElement",
    "TableDetail", "TableElement", "TableFilter", "TextElement",
    "TreeElement", "WindowElement", "element_from_dict", "element_to_dict",
]
```

Twenty-nine names — identical to today's `protocol/elements.py.__all__`
minus the five underscore-prefixed entries (see below).

### Explicit `__all__` for `protocol/messages/__init__.py`

```python
__all__ = [
    "AckMessage", "ClearMessage", "ClientMessage", "ConnectMessage",
    "DisplayMessage", "InteractionMessage", "IntrospectRequest",
    "IntrospectResponse", "ListScenesRequest", "ListScenesResponse",
    "MenuMessage", "Message", "MessageRegistry", "PROTOCOL_VERSION",
    "PingMessage", "PongMessage", "QueryRequest", "QueryResponse",
    "ReadyMessage", "RegisterMenuMessage", "SceneMessage",
    "ScreenshotRequest", "ScreenshotResponse", "ThemeMessage",
    "UnknownMessage", "UpdateMessage", "message_from_dict",
    "message_to_dict",
]
```

Twenty-eight names. `MessageRegistry` is promoted from
public-by-import-graph-accident to **explicit public** because the test
suite imports it. The module-level `_registry` instance stays private —
the one test that imports it (`test_registry_completeness`) reaches
into the implementation knowingly and is fine continuing to do so under
its underscore prefix.

### Names that are public-by-accident and become private

Today `protocol/elements.py.__all__` re-exports five underscore helpers:

```python
"_element_to_dict",
"_patch_from_dict",
"_patch_to_dict",
"_strip_none",
```

The only consumer outside `protocol/` is `protocol/messages.py` itself
(via `from punt_lux.protocol.elements import _element_to_dict, …`).
After the split, `_element_to_dict` and `_strip_none` live in
`protocol/elements/__init__.py` as **internal** helpers used by sibling
modules and `messages/scene.py`. `_patch_to_dict` and `_patch_from_dict`
live in `protocol/elements/patch.py`.

Recommendation: **drop these four names from `__all__` entirely.** They
are private; they are imported by sibling modules via explicit module
paths, not via `from protocol.elements import *`. No external caller
imports them. Keeping them in `__all__` is a documentation bug from the
prior refactor.

### Wire-package `__init__.py` (the existing `protocol/__init__.py`)

No change to its `__all__`. The 60 public names it exposes today
continue to import cleanly from the new sub-packages. `FrameReader`,
`HEADER_FORMAT`, `MAX_MESSAGE_SIZE`, and the framing functions stay
where they are — they belong to the wire-framing module, not to
elements or messages.

---

## Section 4 — Migration sequence

The hooks run `make check` on every Edit and Write. A single broken
intermediate state aborts the run and reverts the file. The migration
order must therefore leave the repo importable after every write.

### Strategy — two-pass per sub-package

**Pass 1 (additive):** Create the new sub-package alongside the old
file. The new sub-package re-exports through the old file. `make check`
passes because nothing has been removed and the old import paths still
resolve.

**Pass 2 (delete):** Once the new sub-package is wired and tested,
delete the old monolithic module.

This is the pattern that worked for the package splits in PRs #158–#162.
Two passes per file, no shim, no backwards-compat alias.

### Order of operations — elements

1a. **Rename `protocol/elements.py` → `protocol/elements/__init__.py`**
    as a single atomic git move plus commit. Python cannot resolve
    `protocol/elements.py` (file) and `protocol/elements/` (package)
    simultaneously, so the rename must precede any extraction; once
    the file is gone and the package is in place, resolution is
    unambiguous. Zero content change. `make check` passes — same
    names, same behavior, just a different file layout.

1b. **Extract `basics.py`.** Move six dataclasses + their codecs out
    of `__init__.py` into `protocol/elements/basics.py`. Add
    `from .basics import …` at the top of `__init__.py`. `make
    check` runs; tests still see the same names through the
    package.

1c. **Repeat for each module** in this order:
    `patch.py` → `graphics.py` → `inputs.py` → `layout.py` → `table.py`.
    Order matters slightly: `patch.py` first (no dependencies),
    then leaves that depend only on the public dispatcher, then
    `inputs.py` (largest cluster), then `layout.py` (containers
    that call back through the public `element_to_dict`), then
    `table.py` (depends on `TableFilter`/`TableDetail` co-located).

1d. **Tidy `__init__.py`.** After all six modules are extracted,
    `__init__.py` should be only: imports from sub-modules; the
    `Element` union; `_ELEMENT_SERIALIZERS` / `_ELEMENT_DESERIALIZERS`
    assembled from sub-module contributions; `element_to_dict` /
    `element_from_dict` dispatch functions; `_strip_none` (shared helper
    used by sibling sub-modules and by `messages/scene.py`); `__all__`.
    This is the natural shape of a package `__init__.py`. Estimated
    ~180 lines, all glue.

### Order of operations — messages

The messages split follows the same pattern. One twist: `messages.py`
imports private helpers from `elements.py`:

```python
from punt_lux.protocol.elements import (
    _element_to_dict, _patch_from_dict, _patch_to_dict, _strip_none,
)
```

These imports continue to resolve after the elements split because the
package `__init__.py` re-exports them (under their underscore names, even
if dropped from `__all__` — explicit imports still work). Once the
messages split lands, these imports are rewritten:

```python
# messages/scene.py
from punt_lux.protocol.elements import _element_to_dict, _strip_none
from punt_lux.protocol.elements.patch import _patch_from_dict, _patch_to_dict
```

Cleaner: `_patch_to_dict` is imported from where it lives, not from the
elements aggregator.

### Strategy for module-level codec helpers

The 105 module-level `_xxx_to_dict` / `_xxx_from_dict` functions are the
hardest part of the split. They are why `method_ratio` is 0.08. Two
options:

**Option A — Keep codecs co-located with their dataclass during the
split.** `_button_to_dict` and `_button_from_dict` move into
`inputs.py` next to `ButtonElement`. The serializer dispatch table
becomes a per-module contribution merged at the package `__init__.py`.

**Option B — Extract codecs into a parallel `codecs/` sub-package.**
Defer until lux-n5ep refactors them into `ElementCodec` methods anyway.

**Recommendation: Option A.** The codec functions are tightly coupled
to their dataclass — every change to a dataclass field needs a matching
change in its `_xxx_to_dict`. Co-location keeps the diff radius small
and makes the lux-n5ep refactor mechanical (`_button_to_dict` becomes
`ButtonElement.to_dict()` in the same file). Option B would create a
second migration where lux-n5ep then has to move things back.

The codecs do not improve `method_ratio` until lux-n5ep converts them
to methods. Phase A does not promise that improvement. See Section 7(e)
and 7(f) for the explicit accounting.

### `_strip_none` placement

`_strip_none` is a four-line helper imported by both elements codec
functions and `messages/scene.py`. It lives in
`protocol/elements/__init__.py` as `_strip_none` — accessible to all
elements sub-modules and to `messages/scene.py` via explicit import.
This is consistent with where it lives today.

### Per-step verification

Each of the seven element extractions and seven message extractions is
its own commit. `make check` runs between each. The two-pass discipline
means each commit either:

- adds a new module and routes through it (no removal yet), or
- after the new module is in place and used, no removal is needed
  because the old module *is* the new module — the rename in step 1a
  ensured we never had two parallel definitions of the same class.

There is no second pass to delete `protocol/elements.py` because step 1a
turned that file into a package. The file is gone; the package replaces it.

---

## Section 5 — PR plan

### Recommendation — two PRs

**PR 1 — Split `protocol/elements.py`.** One file → one package, six
sub-modules + aggregator. Touches:

- `src/punt_lux/protocol/elements.py` → `src/punt_lux/protocol/elements/` (package)
- `src/punt_lux/protocol/elements/__init__.py` (new aggregator)
- `src/punt_lux/protocol/elements/basics.py` (new)
- `src/punt_lux/protocol/elements/inputs.py` (new)
- `src/punt_lux/protocol/elements/layout.py` (new)
- `src/punt_lux/protocol/elements/graphics.py` (new)
- `src/punt_lux/protocol/elements/table.py` (new)
- `src/punt_lux/protocol/elements/patch.py` (new)
- `src/punt_lux/protocol/messages.py` (import path updates only)
- `src/punt_lux/protocol/__init__.py` (no `__all__` change; verify imports resolve)

**Acceptance criteria (PR 1):**

- `protocol/elements/__init__.py` ≤200 lines.
- Every new module ≤300 lines.
- OO ratchet: `classes_per_module` for the protocol package drops from
  27 to max-among-new-modules (target ≤9 in `inputs.py`).
- `module_size` aggregate for the protocol package drops by ≥800 lines
  via redistribution.
- Every existing public import path resolves. No name in
  `protocol/__init__.py.__all__` is removed.
- `make test` passes; `tests/test_protocol.py` runs unchanged.
- Wire format JSON output byte-identical before and after (verifiable
  by running a representative scene through `encode_message` and
  diffing the bytes).

**PR 2 — Split `protocol/messages.py`.** Same shape, six sub-modules +
registry + aggregator. Touches:

- `src/punt_lux/protocol/messages.py` → `src/punt_lux/protocol/messages/`
- `src/punt_lux/protocol/messages/__init__.py` (new aggregator)
- `src/punt_lux/protocol/messages/registry.py` (new — `MessageRegistry`)
- `src/punt_lux/protocol/messages/scene.py` (new)
- `src/punt_lux/protocol/messages/lifecycle.py` (new)
- `src/punt_lux/protocol/messages/interaction.py` (new)
- `src/punt_lux/protocol/messages/menu.py` (new)
- `src/punt_lux/protocol/messages/introspect.py` (new)
- `src/punt_lux/socket_server.py` (no change — already imports
  `from punt_lux.protocol.messages import Message`; resolves via package)
- `tests/test_socket_server.py` (no change)
- `tests/test_protocol.py` (no change — already imports
  `MessageRegistry` via the package path)

**Acceptance criteria (PR 2):**

- `protocol/messages/__init__.py` ≤200 lines.
- Every new module ≤300 lines.
- OO ratchet: `classes_per_module` for the messages package drops from
  22 to max-among-new-modules (target ≤8 in `introspect.py`).
- `module_size` aggregate drops by ≥400 lines via redistribution.
- All seven existing `from punt_lux.protocol.messages import …` import
  sites continue to resolve (one in src, six in tests).
- Wire format JSON output byte-identical before and after.

### Why two PRs, not one

- **Rollback granularity.** If the elements split exposes a subtle
  serialization regression (e.g. dispatch table assembly order),
  reverting one PR reverts one concern. A combined PR couples the two
  splits unnecessarily.
- **Review scope.** Each PR touches ~1,200 lines of moved code. One
  combined PR doubles that. Reviewer fatigue increases the chance of
  missing a regression in either half.
- **Independent value.** Elements split unblocks lux-n5ep alone.
  Messages split is independently useful for lux-skc7. Ship them
  separately so each lands with full reviewer attention.

The two PRs can ship back-to-back the same day. No coordination is
required between them — they touch disjoint files except for one
import line in `messages.py` that gets rewritten in PR 2 anyway.

### Why not three or more PRs

A single sub-module extraction (e.g. "split off `inputs.py` only") is
incoherent — the package layout is a single design decision. Shipping
half a partition produces a worse score than the existing layout
(more `__init__.py` glue, same class count in the residual file). One
PR per file is the minimum cohesive unit.

---

## Section 6 — Risks and open questions

### Downstream caller survey

Every direct import of `protocol.elements` or `protocol.messages`
submodules in the repository (results from `grep -rn` across `src/`
and `tests/`):

**`from punt_lux.protocol.elements import …`** — zero hits outside the
protocol package itself. Every consumer goes through
`from punt_lux.protocol import …`.

**`from punt_lux.protocol.messages import …`** — eight hits:

| File | Imports | After split |
|------|---------|-------------|
| `src/punt_lux/socket_server.py:21` | `Message` | Resolves via package `__init__.py` — no change |
| `tests/test_socket_server.py:20` | `Message` | Resolves via package `__init__.py` — no change |
| `tests/test_protocol.py:1841` | `MessageRegistry` | Resolves via package `__init__.py` — no change |
| `tests/test_protocol.py:1858` | `MessageRegistry` | Same |
| `tests/test_protocol.py:1873` | `MessageRegistry` | Same |
| `tests/test_protocol.py:1882` | `MessageRegistry` | Same |
| `tests/test_protocol.py:1890` | `MessageRegistry` | Same |
| `tests/test_protocol.py:1900` | `_registry` | Resolves to module-level instance in the new `messages/__init__.py` |

Critically, **no caller imports anything that is moved to a non-aggregator
sub-module.** Every public name remains importable via the package
path. No call-site changes are required outside the protocol package
itself.

Inside the protocol package, `messages.py` imports four underscore
helpers from `elements.py`. These imports are rewritten in PR 2 (see
Section 4).

### Test fixtures and mocks

`tests/conftest.py` and the protocol test files do not introspect the
file layout. They import names through standard Python paths and
construct dataclasses by name. The grep above confirms zero structural
dependency.

One specific verification target: `test_protocol.py:1900` does
`from punt_lux.protocol.messages import _registry`. This works because
`_registry` is a module-level instance. In the new layout, `_registry`
lives in `messages/__init__.py`. The import path resolves the same way
— `from punt_lux.protocol.messages import _registry` loads
`messages/__init__.py` and looks up `_registry`. No change needed.

### Wire-format invariants

The split must not change the JSON output of `message_to_dict` or
`element_to_dict` for any input. The codec dispatch tables
(`_ELEMENT_SERIALIZERS`, `_ELEMENT_DESERIALIZERS`, the `_registry`
dispatch) are reassembled in the aggregator `__init__.py` files, but
the per-class codec functions are byte-moved with no logic change.

Verification plan for each PR:

1. Capture a representative scene (one of each element kind, one of
   each message kind) before the split. Serialize via `encode_message`
   and write the bytes to `.tmp/before-PR.bin`.
2. Apply the split.
3. Serialize the same fixture. Write to `.tmp/after-PR.bin`.
4. `diff .tmp/before-PR.bin .tmp/after-PR.bin` must be empty.

This is part of the implementer's local-review checklist, not a test
file added to the repo. The roundtrip tests in `tests/test_protocol.py`
already cover wire-format stability for every individual element and
message kind.

### External structural tools

- **`tools/oo_score.py`** parses Python ASTs and reports per-file
  metrics. It treats every `.py` file independently, so the split
  changes the per-file numbers but not the aggregate-of-protocol
  computation. Ratchet movement is documented in Section 7(e).
- **`tools/oo_coupling.py`** computes import-graph metrics at the
  package level. After the split, the protocol package has more
  internal modules and more intra-package edges — this is the
  expected shape of a healthy package. `pkg_efferent_coupling` to
  external packages is unchanged.
- **`fuzz` / `probcli`** — Lux does not have Z specifications.
  Z-spec tooling does not parse the protocol.
- **`mcp-proxy`** — operates on JSON wire bytes, not Python source.
  Unaffected.
- **No JSON schema file** is generated from the dataclass module
  layout. The protocol contract is defined by the dataclass field
  declarations themselves and by `docs/architecture/` documents.

### Open questions for the evaluator

1. **`Patch` placement — decided.** `protocol/elements/patch.py` is
   the binding home, per evaluator (gvr) round-1 reflection. `Patch`'s
   data model is element-shaped (id plus per-field set dict), and
   Phase C typed patches (`SliderPatch`, `CheckboxPatch`, …) live
   next to their element kinds. Co-locating wire `Patch` with its
   future typed siblings bounds the Phase C diff radius to
   `elements/`. Cost: one extra import in `messages/scene.py`;
   accepted.

2. **`inputs.py` size headroom.** At 9 classes and ~290 estimated
   lines, `inputs.py` is the most crowded sub-module. Acceptable for
   Phase A, but Phase C additions (per-element typed patches) push it
   over 300. Sub-split candidates: split by `SelectableElement` /
   discrete pickers vs continuous-value inputs. Defer the decision
   until lux-6jw9 actually adds the patches.

3. **`_strip_none` location.** Currently proposed to live in
   `protocol/elements/__init__.py`. Alternative: promote it to
   `protocol/_helpers.py` as a package-internal utility. Defer —
   it's a four-line function and moving it later is one search/replace.

---

## Section 7 — Why this makes the code better

### (a) Cognition load

Three contributor tasks become measurably easier:

**Adding a new element kind today** requires editing one file (1,013
lines, 27 dataclasses, 50 codec functions). Touch points in
`elements.py`:

1. New `@dataclass(frozen=True, slots=True)` definition.
2. New `_xxx_to_dict` serializer.
3. New `_xxx_from_dict` deserializer.
4. New entry in `_ELEMENT_SERIALIZERS` dispatch table.
5. New entry in `_ELEMENT_DESERIALIZERS` dispatch table.
6. New entry in `__all__`.
7. New entry in the `Element` type union.

Seven touch points across a 1,013-line file.

**After the split**, the touch points compress to one sub-module file:

1. New dataclass in `inputs.py` (or wherever it fits, typically ≤290
   lines).
2. New serializer/deserializer in the same file.
3. New entry in the sub-module's local `_SERIALIZERS` /
   `_DESERIALIZERS` dict.
4. New entry in `protocol/elements/__init__.py`'s `__all__` (one
   line) and `Element` union (one line).

Two files touched — one ≤300 lines, the other ~180. The contributor
loads ≤480 lines of context instead of 1,013.

**Reading a single element kind today** (e.g. "how does
`SliderElement` serialize?") requires jumping among lines 112, 572,
876, 953 of one file. Five locations, four jumps. **After**: read
`inputs.py` end to end (≤290 lines, six locations for nine elements
clustered together — they fit in one editor pane).

**Reviewing a protocol change today** requires loading 1,013 lines of
context to see whether a new field is consistent with siblings.
**After**: review the relevant ~290-line family file. Sibling
inconsistency is visible at a glance; cross-family inconsistency is
not the reviewer's problem because cross-family additions are by
definition rare.

### (b) Coupling

Today's `elements.py` has a single cross-class coupling:
`TableElement.detail: TableDetail | None` and
`TableElement.filters: list[TableFilter] | None`. Both targets live
in the same proposed `table.py` cluster. The split groups the
tightly-coupled classes; no edge crosses a sub-module boundary
within `elements/`.

Container elements (`GroupElement`, `TabBarElement`,
`WindowElement`, `ModalElement`, `CollapsingHeaderElement`,
`TreeElement`) hold `list[Any]` children that are deserialized
through the package-level `element_from_dict`. The recursion crosses
the package boundary by design — every container reaches the
dispatcher, not a sibling sub-module. This is the loose coupling we
want.

`messages.py` couples to `elements.py` via four imports:
`_element_to_dict`, `_strip_none`, `_patch_to_dict`,
`_patch_from_dict`. After the split, three of these still come from
`elements/__init__.py` (one package import, not four file imports).
`_patch_to_dict` and `_patch_from_dict` come from
`elements/patch.py` directly — the patch codec sits next to the
patch type, and `messages/scene.py` imports them explicitly. This is
slightly more import lines for slightly more local provenance.

### (c) Testability

Today `tests/test_protocol.py` is 1,900+ lines testing one
1,013-line file plus one 570-line file. It runs against the
aggregate import surface, which is fine for behavioral testing.

What becomes natural after the split:

- **Per-family regression tests.** A change to `inputs.py` can be
  scoped: `pytest tests/test_protocol.py -k input` runs in
  milliseconds, isolates the affected surface, and is the natural
  test target for the implementer of lux-6jw9 typed patches.
- **Per-family fuzz harnesses with scoped `hypothesis` strategies.**
  Each sub-module's `__all__` defines the natural scope for a
  `hypothesis` strategy module. A `tests/strategies/inputs.py`
  generating `st.one_of(button_strategy, slider_strategy, …)` mirrors
  the closed type union of `protocol/elements/inputs.py` exactly — 9
  strategies for 9 element classes, one screen of code. The top-level
  "any element" strategy assembles the per-family strategies the same
  way `protocol/elements/__init__.py` assembles the `Element` union.
  Today, a strategy for "any element" has to import everything from
  `elements.py`; after the split, each family's strategies are
  independently writable and the all-elements strategy is composition,
  not enumeration. This is the standard idiom for property-based
  testing against a closed type union — Phase A makes it usable here.
- **`MessageRegistry` in isolation.** Currently testable but
  awkward — the test reaches into a 570-line module to get
  `MessageRegistry` and `_registry`. After the split, `MessageRegistry`
  is the only class in `messages/registry.py` (~80 lines). Tests
  against the registry class are obviously scoped to one file.

What does **not** improve: rendering tests, scene tests, and any
test that relies on a full element scene. These tests already use
the package-level imports and continue to do so unchanged.

### (d) Future-work fit

Concrete example for Phase C (DES-030, lux-5rk7 scene graph nodes):

- A `TableNode` mutable scene-graph class for `TableElement` lives at
  `scene/nodes/table.py`. It imports `TableElement`, `TableFilter`,
  and `TableDetail` from `protocol/elements/table.py`. The four
  classes are file-adjacent and import-adjacent — `scene/nodes/table.py`
  and `protocol/elements/table.py` are mirror files in the package
  tree.
- Without the split, `TableNode` would import from a 1,013-line
  `protocol/elements.py` and rely on a reader to mentally locate the
  three classes it actually depends on.

**Cross-package mirroring as a navigational property.** After Phase C,
`scene/nodes/<family>.py` will mirror `protocol/elements/<family>.py`
across the whole tree — `scene/nodes/inputs.py` opposite
`protocol/elements/inputs.py`, `scene/nodes/layout.py` opposite
`protocol/elements/layout.py`, and so on. A contributor working on the
table family always opens the two mirror files together; the location
of `TableNode` is derivable from the location of `TableElement` without
search. This is a structural property the contributor can rely on, not
a per-class convenience. Without the protocol split, no such mirror
exists — scene nodes would land in a flat `scene/nodes.py` regardless
of how `protocol/elements.py` is organized, and the navigational
property is absent.

Concrete example for lux-n5ep (`ElementCodec` registry):

- The 50 codec functions become `to_dict()` and `from_dict()`
  classmethods on their dataclass. The transformation is per-file
  mechanical: `_button_to_dict(elem)` becomes `elem.to_dict()` in
  `inputs.py`. The module-level dispatch dict goes away, replaced by
  `element.to_dict()` on the union.
- In one file: 50 functions to convert, 1,013 lines of context.
  Split into five files: 6-10 functions per file, ≤290 lines of
  context. Mechanical refactor with bounded blast radius.

Concrete example for lux-6jw9 (typed patches):

- `SliderPatch`, `CheckboxPatch`, `InputTextPatch`, …, live in
  `inputs.py` next to `SliderElement`, `CheckboxElement`, …. Each
  patch dataclass is 4–8 lines. The pair lives in one editor pane.
- Without the split, adding nine typed patches would add 60–80 lines
  to a file already at 1,013 lines, increasing the
  `classes_per_module` violation from 9x to 12x.

### (e) OO ratchet movement

Per-file projection. Current values from `make report` on
`src/punt_lux/protocol/`:

| File | Metric | Before | After (projected) |
|------|--------|-------:|------------------:|
| `elements.py` (deleted) | module_size | 1,013 | — |
| `elements.py` (deleted) | classes_per_module | 27 | — |
| `elements.py` (deleted) | method_ratio | 0.078 | — |
| `elements/__init__.py` | module_size | — | ~180 PASS |
| `elements/__init__.py` | classes_per_module | — | 0 PASS |
| `elements/__init__.py` | method_ratio | — | ~0.0 FAIL (glue only; lux-n5ep) |
| `elements/basics.py` | module_size | — | ~210 PASS |
| `elements/basics.py` | classes_per_module | — | 6 FAIL (target ≤3) |
| `elements/inputs.py` | module_size | — | ~290 PASS |
| `elements/inputs.py` | classes_per_module | — | 9 FAIL |
| `elements/layout.py` | module_size | — | ~250 PASS |
| `elements/layout.py` | classes_per_module | — | 6 FAIL |
| `elements/graphics.py` | module_size | — | ~80 PASS |
| `elements/graphics.py` | classes_per_module | — | 2 PASS |
| `elements/table.py` | module_size | — | ~210 PASS |
| `elements/table.py` | classes_per_module | — | 3 PASS |
| `elements/patch.py` | module_size | — | ~40 PASS |
| `elements/patch.py` | classes_per_module | — | 1 PASS |
| `messages.py` (deleted) | module_size | 570 | — |
| `messages.py` (deleted) | classes_per_module | 22 | — |
| `messages.py` (deleted) | method_ratio | 0.115 | — |
| `messages/__init__.py` | module_size | — | ~190 PASS |
| `messages/__init__.py` | classes_per_module | — | 0 PASS |
| `messages/registry.py` | module_size | — | ~80 PASS |
| `messages/registry.py` | classes_per_module | — | 1 PASS |
| `messages/scene.py` | module_size | — | ~120 PASS |
| `messages/scene.py` | classes_per_module | — | 3 PASS |
| `messages/lifecycle.py` | module_size | — | ~140 PASS |
| `messages/lifecycle.py` | classes_per_module | — | 6 FAIL |
| `messages/interaction.py` | module_size | — | ~60 PASS |
| `messages/interaction.py` | classes_per_module | — | 1 PASS |
| `messages/menu.py` | module_size | — | ~80 PASS |
| `messages/menu.py` | classes_per_module | — | 3 PASS |
| `messages/introspect.py` | module_size | — | ~240 PASS |
| `messages/introspect.py` | classes_per_module | — | 8 FAIL |

**Aggregate movement (protocol package):**

| Metric | Before | After (projected) | Delta |
|--------|-------:|------------------:|------:|
| `module_size` (max) | 1,013 (`elements.py`) | ~290 (`elements/inputs.py`) | −723 |
| `module_size` (sum) | 1,839 across 3 files | ~1,900 across 14 files | +~60 (overhead of `__init__.py` glue and `__all__` declarations) |
| `classes_per_module` (max) | 27 (`elements.py`) | 9 (`inputs.py`) | −18 |
| `classes_per_module` (failing files) | 2 of 3 | 5 of 14 | −36% rate |
| `method_ratio` (per-file ≥0.5 threshold) | 0 of 3 | 3 of 14 (`registry.py`, etc.) | +3 |
| Files at FAIL on **any** ratchet metric | 2 (`elements.py`, `messages.py`) | 5 (the new files with >3 classes) | More files flagged, but each is closer to threshold |

**Files whose score gets worse:** None. The deleted files are gone;
every new file has at least one metric ≤ a current file's value.

**Files that newly appear at FAIL:** `basics.py` (6 classes),
`inputs.py` (9), `layout.py` (6), `lifecycle.py` (6), `introspect.py`
(8). All five fail `classes_per_module` only. **This is acceptable**
because the alternative — one file at 27 classes_per_module — is 3x
to 5x worse. Phase C and lux-n5ep further decompose these classes
(typed patches, methods replace module functions), reducing the
class count per file as they land.

**The metric that does not move in Phase A:** `method_ratio` on the
protocol package. It stays at ~0.08 in `inputs.py`, ~0.0 in the
aggregator, ~0.0 in `basics.py`, etc., because the codec helpers
remain module-level functions. This is the explicit handoff to
lux-n5ep (Section 7(f)).

**Net ratchet judgment:** The split *passes* the ratchet rule. No
file regresses; every old file's worst metric improves. The new
files' worst metric (`classes_per_module`) is materially better than
the file they replaced.

### (f) What this does NOT fix

Limits of Phase A. Stating these up front prevents the implementation
PR from being oversold.

1. **`method_ratio` does not reach the target.** The protocol package
   has 105 module-level codec functions. After the split, those
   functions are distributed across 14 files but they remain
   module-level. `method_ratio` stays low until lux-n5ep
   (`ElementCodec` registry) converts them to methods. Phase A is the
   prerequisite, not the fix.

2. **`classes_per_module` still fails on 5 of 14 files.**
   `inputs.py` has 9 dataclasses; `basics.py` and `layout.py` have 6;
   `lifecycle.py` has 6; `introspect.py` has 8. The threshold is 3.
   Further sub-splits are possible but not justified at this scope —
   the families are cohesive units. Phase C decomposes individual
   element classes (separating wire types from scene nodes from
   typed patches) and naturally lowers these counts. Phase A is not
   the right time to over-split.

3. **The wire format is unchanged.** No new fields, no renames, no
   new element kinds, no new message kinds. Byte-identical JSON
   before and after. lux-6jw9 (typed patches) is the wire-format
   change; this is not it.

4. **Renderers (`display/`) are not improved.** `display/server.py`
   still imports `from punt_lux.protocol import …`. Its module-size
   and complexity violations are unchanged. Phase B (lux-wzpq,
   lux-jyj2) handles the renderer side.

5. **Tests are reorganized only to the minimum extent.**
   `tests/test_protocol.py` continues to import via the package and
   continues to test all elements and messages in one file. Splitting
   the test file to mirror the new sub-module structure is a follow-up
   task, not a Phase A goal.

6. **No new abstractions.** No new base class, no new protocol, no
   new ABC, no new registry pattern. Phase A moves code; it does not
   reshape it. The reshaping (`ElementCodec`, typed patches, scene
   graph nodes) is the work this split unblocks, not the work it does.

---

## Sign-off

Designed by **rmh** (Raymond H, Python specialist).
Date: **2026-05-16**.

Awaiting review by gvr (evaluator) before any implementation begins.
