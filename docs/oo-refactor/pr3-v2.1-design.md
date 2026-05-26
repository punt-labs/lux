# PR 3 v2.1 — production-integration map for the io-model spike

> **Status note:** point-in-time migration design. The canonical target
> architecture now lives under `docs/architecture/target/`.

**Status:** design
**Bead:** `lux-c2c8`
**Plan reference:** `docs/oo-refactor/migration-plan.md` PR 3 (v2.1)
**Reference implementation:** `spikes/io_model_v1/` (validated end-to-end against ARCHITECTURE_NOTES.md A1–A5)
**Worker / Evaluator:** `rmh` / `gvr`

## How to read this doc

The spike at `spikes/io_model_v1/` is the design. This document maps each spike
module to its production destination, names the few production-only adaptations
PR 3 must add (real ImGui, lux socket conventions, the 29 MCP tools), and
sequences the commits. Where a spike module already answers a design question,
this doc cites the spike instead of restating it. The two new surfaces
production needs — `ImGuiTextRenderer` and integration with `paths.py` /
`display_client.py` — are specified explicitly. Everything else is "lift".

Hard constraints (from the mission contract): (1) the 29 MCP tools in
`src/punt_lux/tools/tools.py` keep their signatures; (2) no new wire kinds, no
`DrawProgram`, no `HubRenderer`-as-encoder, no applet-routed custom subclass
behavior (see ARCHITECTURE_NOTES.md A2, A3, A5); (3) every production
destination respects PY-OO-2 (≤ 300 lines, ≤ 3 classes per module).

---

## Section 1 — Module layout map

Every spike module gets a production destination. Split rule: PY-OO-2
(spike files holding > 3 classes split along their class groupings).
PR 3 migrates only Text (1 of 4 spike kinds); per-kind split footprint
is smaller for PR 3 and grows in PRs 4-11.

| # | Spike module | Production destination | Adaptation |
|---|---|---|---|
| 1 | `src/lux_spike/element.py` | `src/punt_lux/domain/element_abc.py` (NEW) | Port verbatim. The existing `src/punt_lux/domain/element.py` is the PR-1 Element **Protocol** (structural typing for wire dataclasses); the spike's `Element` is an **ABC** with the template-method `render()` + `_children()` hook. Both live alongside in PR 3 — the Protocol still types the 23 unmigrated kinds; the ABC types Text. The ABC's filename keeps the two distinct. |
| 2 | `src/lux_spike/protocols.py` (4 Protocols) | `src/punt_lux/protocol/renderer.py` (Renderer + RendererFactory + Emit alias) + `src/punt_lux/protocol/codec_protocols.py` (Decoder + Encoder) (NEW) | Split per PY-OO-2 (one concept per module: render-side protocols / wire-side protocols). |
| 3 | `src/lux_spike/elements.py` (4 element classes) | `src/punt_lux/protocol/elements/text.py` (rewritten as ABC subclass — see §4) | Only Text migrates in PR 3. Button/Panel/Dialog land in PR 4. The existing dataclass + `to_dict`/`from_dict` is **deleted** from `text.py` in the same commit that lands the ABC-shaped TextElement; the codec moves into a new sibling decoder/encoder module (#4). |
| 4 | `src/lux_spike/codec.py` (4 decoders + 4 encoders + UpdateCodec + 2 free functions) | `src/punt_lux/protocol/elements/text_codec.py` (NEW — JsonTextDecoder + JsonTextEncoder) + `src/punt_lux/protocol/element_factory.py` (NEW — JsonElementFactory dispatching by `kind`) + `src/punt_lux/protocol/encoder_factory.py` (NEW — JsonEncoderFactory dispatching by type) + `src/punt_lux/protocol/update_codec.py` (NEW — UpdateCodec; AddElement-only in PR 3) | Per-kind file naming follows existing `protocol/elements/<kind>.py` convention. The four free codec functions in the spike (`encode_interaction`, `decode_interaction`, `encode_button_clicked`, `_get_id`) DO NOT MIGRATE in PR 3 (Button/Interaction land in PR 4). |
| 5 | `src/lux_spike/connection.py` (LineSocket + listen_unix + connect_unix + spawn_reader) | `src/punt_lux/protocol/connection.py` (NEW) | Lift verbatim. Adapt only the socket-path source: the spike reads env vars (`LUX_SPIKE_*`); production reads `DisplayPaths().socket_path` (see §5). The hub-side service-lifecycle integration lives in `paths.py` (already exists) — `connection.py` is pure transport. |
| 6 | `src/lux_spike/renderers/null.py` | `src/punt_lux/protocol/renderers/null.py` (NEW) | Lift verbatim. **Lives under `protocol/renderers/` not `display/renderers/`** because it has zero ImGui dependency and is used on the Hub (which has no `[display]` extra). PL-PA-4 layering. |
| 7 | `src/lux_spike/renderers/text.py` (TextOutput + 4 per-kind renderers + factory) | `src/punt_lux/display/renderers/imgui/factory.py` (NEW — `ImGuiRendererFactory`) + `src/punt_lux/display/renderers/imgui/text.py` (NEW — `ImGuiTextRenderer`) | The spike's TextRendererFactory dispatches by element type to per-kind text renderers. In production the **same shape** holds but the surface is ImGui: `ImGuiRendererFactory` owns the surface-shared state (widget_state, texture_cache, emit channel); `ImGuiTextRenderer` is the per-kind ImGui adapter (see §2). |
| 8 | `src/lux_spike/renderers/recording.py` | `src/punt_lux/protocol/renderers/recording.py` (NEW) | Lift verbatim. Lives under `protocol/renderers/` (no ImGui dep) so test files in `tests/render/` can use it without the `[display]` extra. Used by PR 3+ tests for headless render assertions. |
| 9 | `src/lux_spike/hub.py` (HubDisplay + SubscriptionRegistry + main) | `src/punt_lux/hub/hub_display.py` (NEW — HubDisplay only) + `src/punt_lux/hub/main.py` (NEW — Hub process entry, accept-only path; AddElement only in PR 3) | The spike's `hub.py` mixes state owner + subscription registry + process entry in one file (acceptable for spike; not for production). **SubscriptionRegistry is deferred to PR 4** (Observer subsystem). PR 3 ships HubDisplay + a minimal accept-only Hub process. PR 3 does NOT touch the existing `src/punt_lux/hub.py` (luxd WebSocket hub) — that's the MCP gateway shell, not the io-model Hub process. The new `src/punt_lux/hub/` package is the io-model Hub. |
| 10 | `src/lux_spike/display.py` (DisplayDisplay + build_surface + main) | `src/punt_lux/display/display_display.py` (NEW — DisplayDisplay, the apply-side mirror) + grafted into existing `src/punt_lux/display/server.py` (the existing render loop becomes the new apply-loop's frame walker for Text; other kinds untouched in PR 3) | The spike's main loop wires its own ImGui-equivalent (text/recording surfaces). Production already has a render loop in `display/server.py` (1,459 LoC). PR 3 does NOT rewrite that — it adds the io-model decode → apply → element.render() path **alongside** the existing PR-2 path, gated per-element-kind. Only Text routes through the new path; the other 23 kinds continue through PR-2 element_renderer dispatch. The gating delete is PR 12. |
| 11 | `src/lux_spike/agent.py` (basic + dialog modes) | NOT MIGRATED in PR 3 | The agent is the MCP tool surface. The 29 production MCP tools in `tools/tools.py` ARE the agent — they call into `DisplayClient`. No spike-agent file moves; instead §3 maps tool-call paths onto the new Hub API. |
| 12 | `src/lux_spike/updates.py` (AddElement, SetProperty, RemoveElement, ButtonClicked, PropertyChanged, InteractionMessage) | `src/punt_lux/protocol/updates.py` (NEW — AddElement only in PR 3) | SetProperty lands in PR 5 with the in-fabric applet; RemoveElement + ButtonClicked + InteractionMessage land in PR 4 with Button + Dialog. PropertyChanged is deferred until a consumer exists (PR 5 candidate). |

**Module-size check:** every new file is < 300 LoC, ≤ 3 classes (usually
1). Spike's `hub.py` (358 LoC, 3 classes) and `codec.py` (314 LoC, 9
classes — over ceiling) each split into their per-row destinations.

**WidgetValueProvider deletion** (PR 3 acceptance): delete
`src/punt_lux/scene/widget_value_provider.py` + remove its sole call
site in `scene/manager.py` (lines 21, 76). The Protocol bridged
PR-2's behaviorless wire elements; under the io-model, elements own
state via `_set_content` and the SceneManager dispatch becomes direct
method calls. Sole consumer goes away with this PR's Text migration;
grep verifies no others (§8).

---

## Section 2 — Real ImGui adaptation

### The shape the spike validated

The spike's `TextRendererFactory` (spike `renderers/text.py`) holds one piece
of surface-shared state (`TextOutput`), constructs per-kind renderers on each
factory call, and each per-kind renderer holds `(_elem, _out)`. The factory
is `__call__`-able: `factory(elem) -> Renderer`. The factory is constructed
once at Display startup (`build_surface()` in spike `display.py`) and stays
alive for the process lifetime.

### Production destination

```text
src/punt_lux/display/renderers/imgui/
├── __init__.py                  (NEW — exports ImGuiRendererFactory)
├── factory.py                   (NEW — ~80 LoC)
└── text.py                      (NEW — ~60 LoC; wraps existing TextRenderer)
```

### ImGuiRendererFactory (PR 3 v2.1 plan, extraction rule)

The plan's extraction rule (migration-plan.md PR 3 row 200, last bullet):

> "The factory holds only surface-shared context (widget_state, texture_cache,
> emit channel). Per-kind state lives on the per-kind renderer."

Mirrors the spike: `TextOutput` is the spike's surface-shared state. In
production three pieces of shared state matter:

- `WidgetState` (from `src/punt_lux/scene/widget_state.py`) — per-scene widget
  state already maintained by `display/server.py`.
- `TextureCache` (from `src/punt_lux/display/texture_cache.py`) — image
  textures live here (no relevance to Text but the factory is the right
  owner for later kinds).
- `Emit` (the spike's `_emit` channel) — Display-tier emit. Per spike
  `display.py` line 167, Display-tier emit is a no-op `def display_emit(e):
  pass` since DISP is not the behavior owner. PR 3 lifts that no-op verbatim.

Shape:

```python
# src/punt_lux/display/renderers/imgui/factory.py
class ImGuiRendererFactory:
    _widget_state: WidgetState
    _texture_cache: TextureCache
    _emit: Emit  # Display-tier emit; in PR 3 a no-op (see spike display.py:167)

    def __new__(cls, *, widget_state, texture_cache, emit) -> Self: ...
    def __call__(self, elem: object) -> Renderer:
        match elem:
            case TextElement(): return ImGuiTextRenderer(elem, self)
            # PR 4+ add Button, Dialog, Panel, etc. matches here
            case _: raise ValueError(f"no imgui renderer for {type(elem).__name__}")
```

Per-kind renderers receive the factory, not the shared pieces — the
factory remains the single mediator (spike `renderers/text.py:49`).

### ImGuiTextRenderer

The existing `display/renderers/text_renderer.py` (86 LoC) already
does the right ImGui calls for `TextElement` (style branches, color,
tooltip via `imgui.text_wrapped` / `selectable` / `separator_text`).
PR 3 doesn't rewrite that logic. The new `ImGuiTextRenderer` is a
thin Renderer-Protocol-conforming adapter:

```python
# src/punt_lux/display/renderers/imgui/text.py
class ImGuiTextRenderer:
    _elem: TextElement
    _factory: ImGuiRendererFactory  # for future shared-state access; unused for Text

    def __new__(cls, elem: TextElement, factory: ImGuiRendererFactory) -> Self: ...
    def render(self) -> None:
        # Delegates the actual ImGui calls to the proven PR-2 TextRenderer.
        _TEXT_RENDERER.render(self._elem)
    def begin(self) -> None: pass  # leaf
    def end(self) -> None: pass    # leaf

_TEXT_RENDERER = TextRenderer()  # PR-2 ImGui calls (module-level reuse)
```

The existing `display/renderers/text_renderer.py` survives PR 3 verbatim —
deletion is part of PR 12's sweep, when no PR-2 dispatch path calls it
directly.

### RecordingRenderer as a test surface

Spike `RecordingRendererFactory` lifts verbatim to
`src/punt_lux/protocol/renderers/recording.py` — zero ImGui dep,
importable from `tests/render/` without `[display]`. PR 3 lands
`test_text_recording.py` (asserts per-frame `{"op": "render",
"kind": "text", ...}` entries — spike `R1` shape) and
`test_text_outbound_e2e.py` (full pipeline through `Connection`).

### What does NOT change in PR 3

`display/server.py` (1,459 LoC) keeps its render loop; only the
per-element Text dispatch gets a conditional routing through
`ImGuiTextRenderer` (§3). `display/element_renderer.py` (1,113 LoC)
continues handling the 23 non-Text kinds. Decomposition of both is
deferred per family across PRs 4-11 + PR 12.

---

## Section 3 — MCP-tool preservation map

### The invariant contract

The 29 MCP tools live in `src/punt_lux/tools/tools.py`. Their signatures are
the agent-facing wire contract. PR 3 must preserve every signature. The 29
break into:

| Group | Count | Reads element dicts? | PR 3 impact |
|---|---:|---|---|
| Scene-emitting (`show`, `show_table`, `show_dashboard`, `show_diagram`, `update`, `clear`, etc.) | ~12 | Yes — via `element_from_dict` | Text element dicts route to new path; all other element dicts continue through existing `ElementCodec` |
| Query-style (`@_query_tool`-decorated) | ~10 | No — pure server-side state queries | Untouched |
| Menu / theme / misc (`set_menu`, `set_theme`, `recv`, `ping`, …) | ~7 | No | Untouched |

`tools/tools.py:33-156` (`show()`) is the largest blast radius. Its
argument schema (`elements: list[dict[str, Any]]`) doesn't change; only
`element_from_dict()`'s internals do.

### Dispatch shape (Text → new path; 23 kinds → existing path)

Current code (`src/punt_lux/protocol/elements/__init__.py:179`):

```python
def element_from_dict(d: dict[str, Any]) -> Element:
    elem = _codec.from_dict(d)              # dispatches all 24 kinds
    ...                                      # tooltip post-process
    return elem
```

PR 3 introduces an io-model element factory for Text and keeps `_codec`
for everything else. The shape:

```python
# src/punt_lux/protocol/elements/__init__.py — modified in PR 3 commit (iii)
from punt_lux.protocol.element_factory import JsonElementFactory  # io-model path

_ELEMENT_FACTORY = _build_default_element_factory()   # rf=Null, emit=no-op

def element_from_dict(d: dict[str, Any]) -> Element:
    # Preserve _codec.from_dict's contract: missing/empty/non-string kind
    # is a ValueError (no forward-compatible unknown fallback). See
    # protocol/elements/codec.py:75-94.
    kind = d.get("kind")
    if not isinstance(kind, str) or not kind:
        err = "Element missing or invalid 'kind' field"
        raise ValueError(err)
    if kind == "text":
        return _ELEMENT_FACTORY.decode(d)            # → io-model TextElement (ABC subclass)
    elem = _codec.from_dict(d)                       # → PR-2 path for 23 other kinds
    # tooltip post-process unchanged
    ...
    return elem
```

Why this shape: 29 MCP tools stay invariant; `show()` peers pass dicts
through `element_from_dict()` unchanged; the new TextElement satisfies
the PR-1 `Element` Protocol structurally so downstream `SceneMessage`
plumbing accepts it. The `Element` union (`__init__.py:124`) becomes
ABC TextElement ∪ the 23 PR-2 dataclasses for PR 3 — runtime no-op,
mypy narrowing via union.

### What gates the io-model path

No env flag for Text dispatch — pure code swap. The two backends
(in-memory vs Unix socket — §5) are gated by `LUX_DISPLAY_IN_PROCESS=1`;
that's the only env var PR 3 adds (spike's `LUX_SPIKE_*` don't migrate).

### Tools.py call-site count

`grep -n "element_from_dict" src/punt_lux/tools/tools.py` returns the
import (line 16) and one call inside `show()` (line 132):
`typed_elements = [element_from_dict(e) for e in elements]`. Peer
tools (`update()`, `show_table()`, `show_dashboard()`) take pre-typed
`Element` objects or build dicts and round-trip the same way. PR 3
changes only the *internals* of `element_from_dict`; the input shape
(`dict[str, Any]`) and return type (`Element` Protocol satisfier) are
unchanged, so every tool call site keeps compiling. `SceneMessage`
serialization uses `element_to_dict` (not `element_from_dict`); the
return trip happens on the receiver. Blast radius for the change is
bounded by `tests/protocol/test_element_codec.py` plus tool smokes.

---

## Section 4 — TextElement migration

### Pattern source

Spike `elements.py` `LabelElement` (28-58) is the template. Production
`TextElement` mirrors its `__new__`-keyword-only-injected pattern with
Text's extra fields (style, color, tooltip).

### Production TextElement (PR 3)

`src/punt_lux/protocol/elements/text.py` — REWRITTEN. Dataclass deleted;
codec body moves to `text_codec.py` (§1 row #4); `to_dict`/`from_dict`
remain as thin delegators per D5 (see below).

```python
# Module-level sentinels — same null objects the spike's Hub tier uses.
_NULL_FACTORY: RendererFactory = NullRendererFactory()
def _no_emit(_msg: object) -> None: pass

class TextElement(Element):
    _id: str
    _content: str
    _style: str | None       # PY-TS-14 OK: see D3 (snapshot parity requires permissive)
    _tooltip: str | None     # PY-TS-14 OK: absence is the contract
    _color: str              # PY-TS-14 fix: "" = renderer default
    _kind: Literal["text"]

    def __new__(cls, *,
                renderer_factory: RendererFactory = _NULL_FACTORY,
                emit: Emit = _no_emit,
                id, content,
                style=None, tooltip=None, color="") -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id, self._content, self._style = id, content, style
        self._tooltip, self._color, self._kind = tooltip, color, "text"
        return self

    # @property accessors for id, kind, content, style, tooltip, color.
    # _set_content / _set_style / _set_tooltip / _set_color — minimal
    # setters for the scene patch path (D6) + PR 5's SetProperty.
    # to_dict / from_dict — ≤ 3-line delegators to JsonTextEncoder /
    # JsonTextDecoder for D5 (Element Protocol contract). _patch
    # inherited from Element ABC for D6.
```

**D1 transitional resolution — sentinel defaults on `renderer_factory`
and `emit`.** Spike `LabelElement` requires both as kwargs (no defaults,
`elements.py:28-58`). Production has 100+ existing call sites that pass
neither, so the verbatim spike signature would break the test suite. The
defaults preserve the keyword-only-injected shape — factory and emit are
still injected through `__new__`, not constructed inside the class — and
the decode path through `JsonElementFactory` always passes real values
(runtime semantics on the wire path unchanged). Required-kwarg
discipline tightens back in PR 12's sweep after PRs 4-11 migrate each
family and update call sites.

### What's deleted from `src/punt_lux/protocol/elements/text.py`

- `@dataclass(frozen=True, slots=True)` — replaced by `__new__`.
- All dataclass fields (`kind`, `id`, `content`, `style`, `tooltip`,
  `color`) — become `_`-prefixed slots with `@property` accessors.
- The codec **body** of `to_dict` / `from_dict` moves to
  `JsonTextEncoder.encode` / `JsonTextDecoder.decode` in
  `text_codec.py`. The methods themselves stay on the class as
  ≤ 3-line delegators (D5).

### What's added (other than the class itself)

- `src/punt_lux/protocol/elements/text_codec.py`: `JsonTextDecoder` +
  `JsonTextEncoder` lifted from spike `codec.py:25-41` and `:183-185`,
  adapted to Text's fields. `__new__` injects `renderer_factory` +
  `emit` (decoder) or nothing (encoder).

### One OO-rule resolution + one deferred

- **PY-TS-14 — `color: str | None` → `color: str = ""`** (D4 — land
  as-is). The spike's elements have no `color`. Production Text does.
  The PR-2 file used `color: str | None = None  # PY-TS-14: None =
  renderer default` — the comment said the type system gave up. PR 3
  flips to `color: str = ""` (empty string is the discriminated "no
  override" state). The renderer
  `parse_hex_color(elem.color) if elem.color else None` already treats
  empty/None equivalently; the change is a refinement of the model,
  not a behavior change. Snapshot parity (acceptance) verifies bytes.
- **PY-TS-14 — `style: str | None`** (D3 — DEFERRED). Earlier drafts
  flipped `style` to `Literal["body","heading","caption","code","success","error"]`.
  Implementation surfaced that
  `tests/domain/test_basics_migration.py::test_text_element_from_dict_accepts_arbitrary_style_string`
  asserts arbitrary style strings are accepted for snapshot parity:
  captured scenes with `{"style": "fancy"}` must replay byte-equivalent.
  Tightening at the wire would either reject the value (breaking
  replay) or coerce it (breaking byte parity). The Literal flip is a
  schema tightening that needs a coordinated rollout PR with an
  agent-traffic audit; in PR 3 the field stays `str | None = None`
  and `text_renderer.py:34`'s existing
  `if elem.tooltip and not elem.style:` works unchanged.

### Paired adaptations for the existing production layer (D5, D6)

- **D5 — Element Protocol satisfaction.** `domain/element.py` declares
  a `@runtime_checkable` Element Protocol that structurally requires
  `to_dict` and `from_dict` on every element kind. Deleting both from
  TextElement would break `isinstance(elem, Element)` for every
  TextElement instance (and ≥ 3 tests assert exactly that). Resolution:
  TextElement keeps both methods as ≤ 3-line delegators (see code
  block above). Codec body lives in `JsonTextEncoder/Decoder`; the
  delegators are removed in a follow-up PR that relaxes the Protocol
  to drop the codec methods (the architecturally correct end-state,
  out of PR 3 scope).
- **D6 — Scene patch path adaptation.** `scene/manager.py:402-415`
  uses `dataclasses.fields(elem)` and `dataclasses.replace(elem,
  **valid)` for the SetProperty patch path. Both raise `TypeError`
  on non-dataclass TextElement. Resolution: commit (iii) adds a
  generic `_patch(patch: dict) -> Self` method to the Element ABC
  (see code block above) and inserts an `isinstance(elem, Element)`
  branch in `scene/manager._apply_patch_set`: ABC elements route
  through `elem._patch(valid)`, dataclass elements continue through
  `dataclasses.replace`. The 5 scene-manager patch tests exercise
  the new branch automatically.

### What remains `str | None`

`tooltip: str | None = None` — keeps the optional shape. Per PY-TS-14:
absence is the documented contract. A Text element with no hover hint
is a real state, not "the type system gave up".

---

## Section 5 — Connection abstraction in production

### Spike pattern

Spike `connection.py` provides `LineSocket` (line-delimited JSON over
Unix sockets, thread-safe send), `listen_unix` (server-side bind+listen
context manager), `connect_unix` (client-side with retry), and
`spawn_reader` (daemon-thread reader pump). All five lift verbatim.

### Production socket conventions

The existing `src/punt_lux/paths.py:24-143` (`DisplayPaths`) already
resolves the socket path with this precedence:

1. `$LUX_SOCKET`
2. `$XDG_RUNTIME_DIR/lux/display.sock`
3. `/tmp/lux-$USER/display.sock`

`DisplayPaths` also owns the PID file lifecycle and `ensure()` —
subprocess spawn via `subprocess.Popen([sys.executable, "-m", "punt_lux",
"display", "--socket", ...])` (paths.py:118). PR 3 reuses this
unchanged for the subprocess backend.

### The two backends (`LUX_DISPLAY_IN_PROCESS`)

Plan row 200(b) calls for in-memory + Unix-socket backends. PR 3
implements `LUX_DISPLAY_IN_PROCESS=1` as opt-in for tests; production
default stays Unix-socket subprocess (preserves live agent behavior;
plan's "default" wording is ambiguous — see §9). Two implementations:

```text
src/punt_lux/protocol/connection.py
├── LineSocket             (lifted verbatim from spike)
├── listen_unix            (lifted verbatim)
├── connect_unix           (lifted verbatim)
├── spawn_reader           (lifted verbatim)
└── (these together form the Unix-socket Connection)
```

```text
src/punt_lux/protocol/in_memory_connection.py     (NEW)
└── InMemoryConnection     (queue.SimpleQueue-backed in-process duplex)
```

`InMemoryConnection` exposes the same `.send_line(payload)` /
`.iter_lines()` / `.close()` shape so `DisplayClient` doesn't branch
on which backend it has.

### How the existing DisplayClient hooks in

`src/punt_lux/display_client.py` already calls `DisplayPaths(self._socket_path).ensure()` (paths.py:96) for the subprocess case and connects via
`socket.socket(socket.AF_UNIX, ...)`. PR 3 inserts a backend selector
behind `DisplayClient.connect()`:

```python
def connect(self) -> None:
    if os.environ.get("LUX_DISPLAY_IN_PROCESS") == "1":
        self._connection = InMemoryConnection.from_paired_hub()  # test backend
    else:
        # existing subprocess path: DisplayPaths().ensure() + socket.connect
        # wrapped in a LineSocket so the rest of DisplayClient sees the
        # same shape as in-memory
        ...
```

This means existing tests that already use the subprocess path keep
working; new tests that need fast feedback set `LUX_DISPLAY_IN_PROCESS=1`
in a fixture (see §7 commit iv test naming).

### Subprocess spawn — no new code

PR 3 doesn't add service supervision. `DisplayPaths.ensure()` already
spawns `python -m punt_lux display --socket ...`; the spike's hub
`main()` becomes `src/punt_lux/hub/main.py` invoked the same way once
the migration completes. Through PR 3, the existing
`display/server.py` target is what's spawned.

---

## Section 6 — DisplayClient evolution

### Existing public API (preserved verbatim)

`src/punt_lux/display_client.py:73-618` — all 19 public methods keep
their signatures through PR 3 (`connect`/`close`/`__enter__`/`__exit__`;
`show`/`show_async`; `update`/`update_async`; `set_menu`/`set_theme`/
`clear`/`clear_async`; `ping`/`query`/`recv`; `on_event`/
`remove_callback`; `start_listener`/`stop_listener`;
`declare_menu_item`/`register_menu_item`; `is_connected`/
`listener_active`/`ready_message` properties). `tools/connection.py:55-70`
(`_get_client`) keeps working.

### Internal wiring changes (D7 — Connection added, not wired into DisplayClient)

Original design said `DisplayClient._send` delegates to `Connection`.
Implementation surfaced that production uses length-prefixed framing
(`encode_frame` HEADER_SIZE+length in `protocol/__init__.py:169`) while
the spike's `LineSocket` is newline-delimited — flipping would break
every existing test. **PR 3 resolution:** `DisplayClient` keeps its
existing `encode_message`/`FrameReader` path. The new `Connection`
module lands as a transport in `protocol/connection.py` +
`in_memory_connection.py`, consumed in PR 3 only by
`test_text_outbound_e2e.py::test_in_memory_backend`. Future PRs migrate
DisplayClient to `Connection` in a coordinated wire-flip after the
display server's FrameReader can also flip. `_listener_loop` (line 309)
and `InteractionMessage` parsing stay verbatim (Observer in PR 4).

### What stays verbatim

`recv()` (polling shim, deleted in PR 12 when Observer push lands in
PR 4), `__enter__`/`__exit__`, and the `with DisplayClient() as
client:` idiom in `tools/connection.py` are unchanged.

---

## Section 7 — Internal commit sequence

The eight commits below realize the migration-plan.md PR 3 row 202
sequence. Each passes `make check` + `make snapshot-parity` + local
review (code-reviewer + silent-failure-hunter); each lands its tests in
the same commit (Bar §10).

### (i) NullRenderer + RecordingRenderer + tests

- **Create:** `src/punt_lux/protocol/renderers/null.py`,
  `src/punt_lux/protocol/renderers/recording.py`,
  `src/punt_lux/protocol/renderers/__init__.py` (with `__all__`).
- **Tests:** `tests/render/test_null_renderer.py`,
  `tests/render/test_recording_renderer.py` — assert each `.render()` /
  `.begin()` / `.end()` does the documented no-op or JSONL append.
- **PY-RF-2 consumer:** the test files themselves. RecordingRenderer is
  the test surface used by commit (iii)'s test.
- **No deletion.**

### (ii) Element ABC + Renderer/Decoder/Encoder Protocols + xfail Text test

- **Create:** `src/punt_lux/domain/element_abc.py` (Element ABC lifted
  from spike `element.py`), `src/punt_lux/protocol/renderer.py`
  (Renderer + RendererFactory + Emit), `src/punt_lux/protocol/codec_protocols.py`
  (Decoder + Encoder).
- **Tests:** `tests/domain/test_element_abc.py` —
  template-method `render()` walks children; leaf renders. `tests/protocol/
  test_render_protocols.py` — structural typing checks (`isinstance`).
  `tests/integration/test_text_outbound_e2e.py` (RED, `@pytest.mark.xfail`
  with reason citing commit (iii)).
- **PY-RF-2 consumer:** the xfail test names the path that commit (iii)
  must satisfy; until then it fails as expected.

### (iii) TextElement on ABC + JsonTextDecoder + JsonTextEncoder + ImGuiRendererFactory + ImGuiTextRenderer — RED → GREEN

- **Create:** `src/punt_lux/protocol/elements/text_codec.py`
  (JsonTextDecoder and JsonTextEncoder per §4),
  `src/punt_lux/protocol/element_factory.py`
  (JsonElementFactory — Text-only dispatch in PR 3),
  `src/punt_lux/protocol/encoder_factory.py` (JsonEncoderFactory — Text-only),
  `src/punt_lux/display/renderers/imgui/factory.py` (ImGuiRendererFactory
  per §2), `src/punt_lux/display/renderers/imgui/text.py` (ImGuiTextRenderer
  per §2), `src/punt_lux/display/renderers/imgui/__init__.py`.
- **Modify:** `src/punt_lux/protocol/elements/text.py` — REWRITE per §4
  (delete dataclass; add ABC subclass with sentinel defaults per D1;
  keep `to_dict` / `from_dict` as ≤ 3-line delegators per D5; add
  `_patch` per D6; add `_set_content` / `_set_style` / `_set_tooltip` /
  `_set_color` minimal setters for the scene patch path).
- **Modify:** `src/punt_lux/domain/element_abc.py` — add abstract
  `_patch(patch: dict[str, Any]) -> Self` to the Element ABC (default
  implementation walks the patch dict calling `_set_<key>` per entry;
  TextElement inherits the default). D6.
- **Modify:** `src/punt_lux/scene/manager.py:402-415` — insert
  `isinstance(elem, ABCElement)` branch in `_apply_patch_set`: ABC
  elements route through `elem._patch(valid)`; dataclass elements
  continue through `dataclasses.replace(elem, **valid)`. D6.
- **Modify:** `src/punt_lux/protocol/elements/__init__.py` — register Text
  through `JsonElementFactory` for inbound; encoder factory for outbound;
  keep `_codec` for the other 23 kinds. Dispatch shape per §3.
- **Modify (D2):** `src/punt_lux/protocol/elements/basics.py:39` drops
  the "text" entry from legacy codec registration (Text routes through
  `JsonElementFactory` now); `tests/domain/test_basics_migration.py:312,319`
  rewrites the two `TextElement.from_dict` calls against
  `JsonTextDecoder(...).decode(...)` — equivalent boundary assertions.
- **Tests:** `tests/render/test_text_recording.py` — Text rendered via
  RecordingRenderer asserts `{"op": "render", "kind": "text", "id":
  "t1", "content": "Hello"}`. The xfail from (ii) flips to xpass; remove
  the xfail marker in the same commit.
- **PY-RF-2 consumer:** the test from (ii) is the consumer.
- **No renderer change (D3):** `style` stays `str | None`, so
  `text_renderer.py:34` works unchanged; no tooltip-paint test needed.

### (iv) Connection abstraction + in-memory queue backend + integration test

- **Create:** `src/punt_lux/protocol/connection.py` (LineSocket + helpers
  lifted from spike `connection.py`, adapted: `__new__` per PY-CC-1,
  `logger.exception` per PY-CS-11), `src/punt_lux/protocol/in_memory_connection.py`
  (paired-queue InMemoryConnection per §5).
- **Tests:** `tests/protocol/test_connection_line_socket.py` (send/recv
  loop, partial-line handling, close), `tests/protocol/test_connection_in_memory.py`
  (paired send/recv across the in-memory backend),
  `tests/integration/test_text_outbound_e2e.py::test_in_memory_backend`
  — exercises the new Connection module end-to-end (does NOT route
  through DisplayClient — see D7 in §6).
- **PY-RF-2 consumer:** the integration test exercises Connection.

### (v) Subprocess lifecycle smoke (no DisplayClient changes per D7)

- **No source changes** — per D7 (§6), DisplayClient keeps its
  existing path; Connection wire flip is a future coordinated PR.
- **Tests:** `tests/integration/test_subprocess_lifecycle.py` —
  spawn display via existing `DisplayPaths().ensure()`, send one
  Text scene through unchanged DisplayClient path, close, assert PID
  file removed. Smoke test that Text scenes still flow after commit
  (iii)'s migration.
- **PY-RF-2 consumer:** the lifecycle test.

### (vi) DisplayClient + ImGui paint integration

- **Modify:** `src/punt_lux/display/server.py` — Text render branch
  routes through the new `ImGuiTextRenderer` (via
  `ImGuiRendererFactory`); the other 23 kinds continue through the
  PR-2 `element_renderer` dispatch.
- **Tests:** `tests/integration/test_text_imgui_paint.py` — spawns
  display server, sends a Text scene, asserts visible paint via the
  existing test harness pattern (see `tests/test_show.py` for the
  smoke shape). `tests/render/test_imgui_text_renderer.py` — direct
  ImGuiTextRenderer test against a fake imgui (existing pattern in
  `tests/test_display_*`).
- **PY-RF-2 consumer:** the paint test.

### (vii) WidgetValueProvider deletion

- **Delete:** `src/punt_lux/scene/widget_value_provider.py`.
- **Modify:** `src/punt_lux/scene/manager.py` — remove the import (line
  21), remove the `isinstance(elem, WidgetValueProvider)` branch (line
  76), inline the equivalent direct-method-call dispatch for inputs
  (Slider/Checkbox/InputText/Combo/Radio/Selectable). The PR-2
  elements still have the dispatch-side attributes since they're
  unchanged by PR 3; only the Protocol indirection goes away.
- **Tests:** `tests/test_scene_manager.py` — update the test
  expectations to assert direct dispatch (no Protocol).
- **PY-RF-2:** zero callers of `WidgetValueProvider` remain after this
  commit. Grep verifies.

### (viii) Old Text scaffolding deletion + loose perf smoke

- **Delete:** any orphan Text-specific PR-2 codec methods (already
  gone from `text.py` in commit iii; this commit sweeps any leftover
  `text.to_dict` references in tests, snapshots, etc.).
- **Add:** `tests/perf/test_frame_budget.py` — loose 50ms-per-frame
  budget for 10 Text elements (spike-style harness using the recording
  renderer for deterministic timing; per migration-plan.md PR 3 row
  200 (j)).
- **PY-RF-2:** no new production code; the perf test is the consumer
  of the now-stable Text path.

### Per-commit gates (all commits)

- `make check` — exit 0.
- `make snapshot-parity` — Text wire bytes identical to PR-2 (after
  the §4 PY-TS-14 cleanups, which are byte-equivalent because the
  renderer treats `None` and `""` identically — see acceptance §8).
- `feature-dev:code-reviewer` + `pr-review-toolkit:silent-failure-hunter`
  zero findings.
- OO ratchet (`.oo-baseline.json`) holds or improves.

---

## Section 8 — Acceptance verification map

Per migration-plan.md PR 3 row 208 ("Acceptance"):

| Criterion | Verifying test / command |
|---|---|
| `make snapshot-parity` passes for Text wire bytes | Replays PR-0 characterization snapshots for `show()` calls containing Text; byte-compares serialized `SceneMessage`. §4 PY-TS-14 cleanups are byte-equivalent (absent `style`/`color` stripped in both encoders). |
| `make check` clean | OO ratchet, mypy/pyright, ruff format + lint, radon CC, pylint design. |
| Text e2e through Connection in both backends | `tests/integration/test_text_outbound_e2e.py::test_in_memory_backend` (in-process backend) and `tests/integration/test_subprocess_lifecycle.py::test_text_scene_survives_subprocess_lifecycle` (subprocess backend smoke). |
| Loose perf smoke at 50ms/frame for 10 Text | `tests/perf/test_frame_budget.py::test_ten_text_elements_render_under_50ms_per_frame`. |
| All 29 MCP tools continue to work | Manual smoke per §6 inner-loop step 5; `test_text_outbound_e2e` covers `show` with Text; other 28 grep clean (next row). |
| `to_dict`/`from_dict` on `TextElement` delegator-only (D5) | `grep -A 4 "def to_dict\|def from_dict" src/punt_lux/protocol/elements/text.py` shows ≤ 3 lines per body delegating to `JsonTextEncoder`/`Decoder`. |
| Zero `WidgetValueProvider` references | `grep -rn "WidgetValueProvider" src/punt_lux/ tests/` returns zero lines. |
| 29 MCP tool signatures unchanged | `grep -c "@mcp.tool\|@_query_tool" src/punt_lux/tools/tools.py` returns same count as `main`. |
| Element ABC shape lifted from spike | `grep -n "def render(self) -> None\|def _children" src/punt_lux/domain/element_abc.py` returns two lines. |
| io-model dispatch only on Text in PR 3 | `grep -n 'kind == "text"' src/punt_lux/protocol/elements/__init__.py` returns exactly one line. |

Test file inventory (all NEW in PR 3 unless noted):

- `tests/render/test_null_renderer.py`
- `tests/render/test_recording_renderer.py`
- `tests/render/test_text_recording.py`
- `tests/render/test_imgui_text_renderer.py`
- `tests/domain/test_element_abc.py`
- `tests/protocol/test_render_protocols.py`
- `tests/protocol/test_connection_line_socket.py`
- `tests/protocol/test_connection_in_memory.py`
- `tests/integration/test_text_outbound_e2e.py` (both backends)
- `tests/integration/test_text_imgui_paint.py`
- `tests/integration/test_subprocess_lifecycle.py`
- `tests/perf/test_frame_budget.py`
- (Modified) `tests/test_scene_manager.py` — drops WidgetValueProvider
  expectations.

Directory creation: `tests/render/`, `tests/protocol/`, `tests/domain/`,
`tests/perf/` may be new; create with empty `__init__.py` per existing
pattern.

---

## Section 9 — Open questions

1. **`LUX_DISPLAY_IN_PROCESS` default.** Migration-plan.md PR 3 row
   200 (d) says "default `LUX_DISPLAY_IN_PROCESS=1`" which read
   literally flips the production default to in-process and breaks
   live agents. §5 reads it as "in-process is the test default;
   subprocess stays the production default", preserving behavior.
   **Recommend gvr confirm** as opt-in; amend if plan literally meant
   the opposite.

2. **`src/punt_lux/hub.py` (luxd WebSocket hub) vs new `hub/`
   package.** §1 row 9 proposes a new `hub/` package for the io-model
   Hub alongside the existing `hub.py` MCP-gateway file (different
   responsibilities). The spike is greenfield, so doesn't address
   co-existence. **Recommend gvr confirm:** is `src/punt_lux/hub/`
   acceptable as the io-model Hub home, or should it take a different
   name to avoid confusion?
