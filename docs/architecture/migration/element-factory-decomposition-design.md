# Element-Factory Decomposition: an ABC-kind registry

**Status:** design proposal (feeds a DESIGN.md ADR).
**Scope:** `src/punt_lux/protocol/element_factory.py` and the enumerations
that shadow it. Behavior-preserving refactor — no protocol change.

## Abstract

`element_factory.py` is over the 300-line PY-OO-2 target and grows on every
element migration. The growth is not one place but four, and the same "which
kinds are on the ABC path" fact is hand-copied into six locations across four
modules. This design replaces the hand-copied enumerations with one
`AbcElementRegistry` populated from a data-driven spec table. After the change,
migrating a kind adds one spec value to a registration module and one string to
an import-light name set; `element_factory.py` and the encoder never change.
The module lands well under 300 lines and stops ratcheting.

## 1. What the module does today, and why it ratchets

`JsonElementFactory` is the inbound wire decoder: `element_from_dict(d)` routes
`d["kind"]` to a per-kind ABC decoder, forks conditionally-ABC containers onto
the ABC path when their whole subtree is migrated, and sends everything else
through the legacy `ElementCodec`. That dispatch algorithm is the module's real
job and is worth keeping. The problem is that four *data* concerns are inlined
into it, and each grows per migration:

1. **Per-kind imports** — `element_factory.py:20-71`. A migrated leaf adds an
   element-class import, a decoder-class import, and (for handler-bearing kinds)
   a `build_standalone_<kind>_handler_decoder` import. ~3-6 lines per kind.
2. **`_ABC_KINDS`** — `element_factory.py:85-97`. One string per migrated leaf.
3. **`_ABC_LEAF_TYPES`** — `element_factory.py:99-111`. One class per migrated
   leaf, used by the leaf-decode assertion at `:301`.
4. **The `__new__` decoders dict** — `element_factory.py:149-206`. A 3-9 line
   constructor entry per leaf, each threading `renderer_factory`, `emit`,
   `element_cls`, and the kind's handler wiring. The three container decoders
   (`:210-230`) are three more inlined constructions.
5. **The `_decode_legacy` isinstance union** — `element_factory.py:334-347`. A
   14-arm `TextElement | ButtonElement | …` guard asserting a legacy result is
   not secretly a migrated kind. One arm per migrated kind (leaf *and*
   container).

A single migration therefore edits `element_factory.py` in four to five places.
The history in the mission brief (211 → 256 → 275 → 288 → 312 → 328, now 356
lines) is exactly this: each kind pushes the god-module further over target, and
`make check` never sees it because the ratchet only compares *touched* files
against the baseline.

### The deeper problem: the fact is copied six times

"Which kinds are on the ABC path" is one fact. It is currently written out by
hand in six places, which must be kept in sync manually:

| # | Location | Form |
|---|----------|------|
| 1 | `element_factory.py:85` `_ABC_KINDS` | leaf kind strings |
| 2 | `element_factory.py:101` `_ABC_LEAF_TYPES` | leaf classes |
| 3 | `element_factory.py:149` `__new__` decoders dict | kind → decoder ctor |
| 4 | `element_factory.py:334` `_decode_legacy` union | all ABC classes |
| 5 | `encoder_factory.py:47` `_DISPATCH` | class → encoder |
| 6 | `protocol/elements/__init__.py:179` `_element_to_dict` union | all ABC classes |

Two more enumerate the same fact as strings for the container gate
(`container_abc_gate.py:24` `_MIGRATED_ABC_KINDS`, `:42` `_CONTAINER_KINDS`).
Fixing only `element_factory.py`'s four copies leaves the encoder, the aggregator
union, and the gate to drift. The `checkbox` half-migration regression recorded
in `tests/CLAUDE.md` — encode path exercised while the JSON-encode asymmetry went
untested — is precisely a "these copies fell out of sync" failure. The general
solution is one source of truth, not four smaller ones.

## 2. Chosen decomposition

Introduce **one `AbcElementRegistry`**, the single source of truth for the ABC
kinds. It holds a per-kind `AbcKindSpec` — a small strategy object that knows
how to build that kind's decoder from the tier's dependency injection and how to
encode it. Every consumer that today hand-copies the enumeration reads it from
the registry instead. `element_factory.py` keeps only the dispatch algorithm and
drives it off the registry.

### 2.1 The spec: a kind's decode/encode knowledge, owned by one object

```python
@runtime_checkable
class AbcKindSpec(Protocol):
    """One migrated kind's decode/encode knowledge (PY-DP-11, structural)."""

    @property
    def kind(self) -> str: ...
    @property
    def element_type(self) -> type: ...
    @property
    def is_container(self) -> bool: ...
    def build_decoder(self, binding: TierBinding) -> KindDecoder: ...
    def encode(self, elem: object) -> dict[str, object]: ...
```

`TierBinding` is the DI bundle — it replaces the four keyword arguments the
`__new__` dict threads by hand (PY-OO-3):

```python
@dataclass(frozen=True, slots=True)
class TierBinding:
    renderer_factory: RendererFactory
    emit: Emit
    publish_sink: PublishSink
    recurse: RecurseFromDict   # the factory's bound element_from_dict
```

Concrete implementers capture the five construction shapes the current `__new__`
uses, without a class per kind:

- **`LeafKindSpec`** — `Decoder(renderer_factory, emit, element_cls)`, plus an
  optional `handler_builder: Callable[[PublishSink], HandlerDecoder]` that, when
  present, adds `handler_decoder=handler_builder(binding.publish_sink)`. Covers
  text, progress (no handler) and button, checkbox, input_text, input_number,
  slider, color_picker (handler).
- **`DialogKindSpec`** — the one leaf whose decoder takes `publish_sink=` rather
  than a `handler_decoder`. A distinct class because its wiring genuinely
  differs; folding it into `LeafKindSpec` with a mode flag would be a `str`-with-
  comment in spirit.
- **`ContainerKindSpec`** — `Decoder(decode_element=binding.recurse,
  element_cls, [handler_decoder=…])`. Covers group (no handler),
  collapsing_header, tab_bar (handler). `is_container` is `True`.

Each spec also carries its stateless encoder instance and returns it via
`encode`, so the registry owns both directions.

### 2.2 The registry: the single source of truth

```python
class AbcElementRegistry:
    _specs: dict[str, AbcKindSpec]     # keyed by wire kind

    def register(self, spec: AbcKindSpec) -> None: ...

    @property
    def all_kinds(self) -> frozenset[str]: ...
    @property
    def leaf_kinds(self) -> frozenset[str]: ...
    @property
    def container_kinds(self) -> frozenset[str]: ...
    @property
    def abc_types(self) -> tuple[type, ...]: ...      # replaces #2, #4, #6

    def build_decoders(self, binding: TierBinding) -> dict[str, KindDecoder]:
        # replaces #3 — leaf + container decoders in one pass
        ...
    def encoder_dispatch(self) -> tuple[tuple[type, KindEncoder], ...]:
        # replaces #5
        ...
    def encode(self, elem: object) -> dict[str, object]: ...
```

Enumerations #2, #3, #4, #5, #6 collapse into registry properties. The registry
holds classes and is therefore a "heavy" module (it participates in the element
import graph). That is fine for its consumers — `element_factory`, `encoder_
factory`, and the aggregator `__init__` — all of which already import element
classes.

### 2.3 The gate stays import-light; the two survivors are cross-checked

`container_abc_gate.py` must **not** import element classes: the aggregator
imports the container codecs to build the union, the container codecs import the
gate, and the gate importing the registry (which imports element classes) would
close a cycle. The gate's decision is a pure function of the wire dict plus two
*string* sets, so those strings stay in an import-light module:

```python
# abc_kind_names.py — strings only, zero element imports
class AbcKindNames:
    MIGRATED_ABC_KINDS: ClassVar[frozenset[str]] = frozenset({...})
    ABC_CONTAINER_KINDS: ClassVar[frozenset[str]] = frozenset({...})

    @classmethod
    def is_migrated(cls, kind: object) -> bool: ...
    @classmethod
    def is_container(cls, kind: object) -> bool: ...
```

This leaves two data homes for the fact — the heavy spec table and the light
name set — because the layering forbids the gate from seeing classes. The two
are reconciled with a **fail-loud import-time cross-check** in the registration
module:

```python
built = DefaultAbcKinds.build()
if built.all_kinds != AbcKindNames.MIGRATED_ABC_KINDS:
    raise RuntimeError(
        "ABC kind registry and AbcKindNames disagree: "
        f"{built.all_kinds ^ AbcKindNames.MIGRATED_ABC_KINDS}"
    )
```

Drift becomes an `ImportError` at process start, not a silent wire bug months
later. Six hand-copied code enumerations become two data sets with a mechanical
consistency guard — a strict, honest improvement given the layering constraint.

### 2.4 De-specialize the button sugar

`canonicalize_button_sugar` (`element_factory.py:245-281`, 37 lines) is button
wire logic living in the central dispatcher, forced there by the `if kind ==
"button"` special case in `decode` (`:241-242`). It is also called from
`dialog_codec.py:125`. Move it onto the button codec so the button decoder
self-canonicalizes, and re-point the dialog codec. The central `decode` loses
its only per-kind branch. This removes ~37 lines and one special case from the
god-module and puts button quirks where a reader looks for them.

### 2.5 What `element_factory.py` keeps

Only the dispatch algorithm, now generic:

```python
class JsonElementFactory:
    def __new__(cls, *, renderer_factory, emit, publish_sink, codec,
                registry=DEFAULT_ABC_REGISTRY) -> Self:
        self = super().__new__(cls)
        self._codec = codec
        self._registry = registry
        binding = TierBinding(renderer_factory, emit, publish_sink,
                              self.element_from_dict)
        self._decoders = registry.build_decoders(binding)   # leaf + container
        return self

    def element_from_dict(self, d):
        kind = d.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError("Element missing or invalid 'kind' field")
        if kind in self._registry.leaf_kinds:
            return self._decode_leaf(kind, d)
        if kind in self._registry.container_kinds and ContainerAbcGate.is_all_abc(d):
            return self._decoders[kind](d)
        return self._decode_legacy(d)
```

The container fork stops naming `group`/`collapsing_header`/`tab_bar`; a new
container kind is picked up by `registry.container_kinds` with no edit here. The
`_decode_legacy` guard becomes `if isinstance(elem, self._registry.abc_types):
raise AssertionError(...)` — one line replacing the 14-arm union.

The `@trace`d `decode(raw)` entry and `element_from_dict` both remain (their
external and internal callers are unchanged); both are backed by the registry.
`JsonElementFactory.__new__`'s public signature is unchanged (the `registry`
parameter defaults to the shared instance), so the four construction sites need
no edit.

## 3. Concrete write-set

### Create (5 modules, import-graph order)

| Module | Classes | Responsibility |
|--------|---------|----------------|
| `protocol/elements/abc_kind_names.py` | `AbcKindNames` | Import-light kind-string sets + membership methods. The gate's only dependency. |
| `protocol/elements/abc_kind_spec.py` | `TierBinding`, `AbcKindSpec` | DI value object + the runtime-checkable spec Protocol (PY-IC-9 types module). |
| `protocol/elements/abc_kind_specs.py` | `LeafKindSpec`, `DialogKindSpec`, `ContainerKindSpec` | The three construction-shape implementers (≤3 per PY-OO-2). |
| `protocol/elements/abc_registry.py` | `AbcElementRegistry` | Single source of truth; decoder-build and encoder-dispatch views. |
| `protocol/elements/abc_kind_table.py` | `DefaultAbcKinds` | Imports every migrated kind's element/decoder/encoder/handler-builder; builds the populated registry; runs the `AbcKindNames` cross-check. **This is the one file a future migration edits.** |

### Modify

| File | Change |
|------|--------|
| `protocol/element_factory.py` | Delete per-kind imports, `_ABC_KINDS`, `_ABC_LEAF_TYPES`, the `__new__` decoders dict, `canonicalize_button_sugar`, and the `_decode_legacy` union. Drive dispatch off the injected `registry`. Target ~130 lines. |
| `protocol/encoder_factory.py` | `JsonEncoderFactory.encode` delegates to `registry.encoder_dispatch()`; drop the per-kind imports and the `_DISPATCH` literal. Public name/class preserved (tests and `__init__` import it). |
| `protocol/elements/container_abc_gate.py` | Replace `_MIGRATED_ABC_KINDS` / `_CONTAINER_KINDS` with `AbcKindNames` references. Stays import-light; `is_all_abc` classmethod surface unchanged (many tests + container codecs depend on it). |
| `protocol/elements/button_codec.py` | Absorb the button-sugar canonicalizer; `JsonButtonDecoder.decode` self-canonicalizes. |
| `protocol/elements/dialog_codec.py` | Re-point `_canonicalize_button_sugar` (`:125`) to the button codec's new home. |
| `protocol/elements/__init__.py` | `_element_to_dict` isinstance union (`:179`) → `registry.abc_types`. Construct the module-level default registry (beside `_to_dict_codec`). |

### Unchanged (verify, do not edit)

The four `JsonElementFactory(...)` construction sites — `display_client.py:108`,
`tools/hub_factory.py:77`, `display/server.py:233`, `tests/conftest.py:52` (and
`tests/regression/test_dialog_interaction_trace.py:406`) — keep their call shape
because the new `registry` parameter defaults. Confirm no edit is needed.

## 4. Representative kind: `text`, before and after

### Before — adding `text` touched six code sites across three modules

```python
# element_factory.py — imports
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder
# element_factory.py:87   _ABC_KINDS
    "text",
# element_factory.py:104  _ABC_LEAF_TYPES
    TextElement,
# element_factory.py:150  __new__ decoders dict
    "text": JsonTextDecoder(
        renderer_factory=renderer_factory, emit=emit, element_cls=TextElement
    ).decode,
# element_factory.py:336  _decode_legacy union
    TextElement
# encoder_factory.py:48   _DISPATCH
    (TextElement, JsonTextEncoder().encode),
# __init__.py:181         _element_to_dict union
    TextElement
```

### After — one spec value plus one name-set entry

```python
# abc_kind_table.py — the only functional edit for a new kind
LeafKindSpec(
    kind="text",
    element_cls=TextElement,
    decoder_cls=JsonTextDecoder,
    encoder=JsonTextEncoder(),
)                       # handler-bearing kinds add handler_builder=build_standalone_…

# abc_kind_names.py — the string the import-light gate needs
MIGRATED_ABC_KINDS = frozenset({..., "text"})
```

`element_factory.py`, `encoder_factory.py`, and `__init__.py` are not touched.
A container kind is a `ContainerKindSpec(...)` value and additionally lists its
string in `ABC_CONTAINER_KINDS`; `dialog` is a `DialogKindSpec(...)`.

## 5. Rejected alternatives

- **Split `element_factory.py` into two files** (e.g. leaf dispatch here,
  container dispatch there). Gets under 300 lines but does nothing for goal #2:
  every migration still edits the split files, and the six-way duplication
  survives. Rejected — treats the symptom, not the disease.

- **Move the `__new__` dict into a data module, keep everything else.** Fixes
  copy #3 only. The encoder `_DISPATCH`, the two isinstance unions, and the
  membership sets still drift independently. Rejected — a partial single-source
  is not a single source.

- **A bespoke `TextKindSpec`, `ButtonKindSpec`, … class per kind.** Maximum
  locality but ~12 near-identical classes, and each new kind adds a class rather
  than a value. The three construction shapes do not justify twelve classes;
  the data varies, the behavior does not. Rejected in favor of three
  parametrized spec classes carrying the per-kind classes as data (PY-OO-5).

- **Fold `AbcKindNames` into the registry (one data home).** Would be ideal but
  closes an import cycle: the gate needs the strings, the registry needs the
  classes, and the gate cannot import the registry. Rejected as infeasible under
  the current layering; the fail-loud cross-check (§2.3) is the honest
  second-best.

- **Self-registering codecs via import side effects** (each `<kind>_codec.py`
  calls `DEFAULT_REGISTRY.register(...)` at import). Eliminates the table module,
  but registration then depends on import order and on every codec module
  actually being imported — a fragile, implicit contract. The explicit
  `DefaultAbcKinds.build()` table is inspectable, ordered, and cross-checkable.
  Rejected — explicit is better than implicit.

## 6. Behavior-preservation and verification

This is a refactor; the wire format does not change. Proof obligations:

1. **Same decoder per kind.** The spec `build_decoder` for each kind must
   construct the identical decoder the `__new__` dict builds today, with the
   same DI. Assert per-kind by decoding a fixture and comparing to a decode
   through a hand-built decoder — or simpler, rely on the existing per-kind
   migration suites below, which already decode every kind through the factory.

2. **All 25 kinds still roundtrip.** Run, unchanged and green:
   - `make test` — Level-1 serialization roundtrips for every kind; the per-kind
     migration suites `test_text_*`, `test_inputs_migration`, `test_slider_
     migration`, `test_input_text_migration`, `test_input_number_migration`,
     `test_color_picker_migration`, `test_progress_element`, `test_group_element`,
     `test_collapsing_header_element`, `test_tab_bar_element`, and the dialog
     path. These exercise both `JsonElementFactory.element_from_dict` and
     `JsonEncoderFactory().encode`.
   - `make snapshot-parity` — replays the characterization corpus; byte-identical
     output across every MCP tool that renders elements. This is the strongest
     end-to-end guard that encode/decode is unchanged.
   - `make test-integration` — the `tests/e2e/` business-event-loop harness
     drives the full Hub/Display leg for the interactive kinds (Level 4).

3. **Gate decisions unchanged.** The `is_all_abc` classmethod surface and its
   test suite (`test_group_element`, `test_tab_bar_element`,
   `test_collapsing_header_element`, and the `*_migration` gate tests) stay green
   — the gate keeps the same public shape and only sources its strings from
   `AbcKindNames`.

4. **Cross-check fires.** Add a unit test that the import-time
   `registry.all_kinds == AbcKindNames.MIGRATED_ABC_KINDS` guard raises when a
   spec is registered without its name (fidelity: the guard must catch the drift
   it exists to prevent).

5. **`make check`** — the full gate, including `make check-oo`. `element_factory.py`
   drops below 300; the new modules are each ≤300 lines and ≤3 classes.
   `make update-oo`; stage `.oo-baseline.json` + `.oo-audit.jsonl` with the
   change (the factory file's `module_size` improves, which the ratchet requires
   — do not `--rebaseline` to absorb it).

The migration gate in `tests/CLAUDE.md` (Levels 1-6) is the acceptance
procedure; because the wire form is untouched, Levels 1-5 passing over the real
boundary — not a stub — is sufficient, and no new Level-6 visual confirmation is
required beyond a smoke `make restart` that the window still renders a mixed
scene.
