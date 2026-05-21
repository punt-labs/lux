# Draw Command Validation — Design

Status: design proposal
Bead: lux-4n1b
Sibling decisions: PR #171 (lux-ckad — BeadsBrowser surfaces failures), PR #172 (lux-n5ep — `ElementCodec.from_dict` strict `kind` validation)

## Motivation

A user sent a smoke-test scene with five colored circles:

```json
{"kind": "draw", "id": "smoke", "commands": [
  {"op": "circle", "x": 100, "y": 100, "r": 40, "color": "#FF0000"}
]}
```

The wire payload was valid (a `draw` element with a `commands` list). The display rendered one default-radius white circle at the canvas origin instead of the intended figure, and nothing surfaced an error. The renderer's `_dispatch_draw_cmd` read `cmd.get("cmd", "")` — `""` doesn't match any known type, so the dispatcher silently fell through. Each `_draw_*` helper then read fields with `cmd.get(field, default)`, masking every structural mistake with a default.

This is the same anti-pattern as the two recently-fixed bugs:

- `ElementCodec.from_dict` used to default a missing `kind` to `"text"` (PR #172).
- `BeadsBrowser` used to render "No active issues" when the `bd` shell-out failed (PR #171).

Defaults belong on optional fields. They do not belong in validation. A wrong-schema draw call has *always* rendered the wrong thing — making it raise instead is not a regression, it is the fix the architecture already requires.

---

## 1. Command Catalog

Eight command types reach `_dispatch_draw_cmd` (`src/punt_lux/display/element_renderer.py:1012-1047`). For each, "required" means the renderer cannot draw the intended figure without the field; "optional" means a meaningful default exists.

### 1.1 `line`

Source: lines 1025-1032.

| Field       | Required | Type                          | Default      | Notes                                              |
|-------------|----------|-------------------------------|--------------|----------------------------------------------------|
| `cmd`       | yes      | `"line"`                       | —            | discriminant                                       |
| `p1`        | yes      | `[number, number]`             | —            | structural — `cmd["p1"]` indexes raw, no `.get()`  |
| `p2`        | yes      | `[number, number]`             | —            | structural                                          |
| `color`     | no       | hex string (`"#RRGGBB"`)        | `"#FFFFFF"`  | genuine optional                                   |
| `thickness` | no       | number > 0                     | `1.0`        | genuine optional                                   |

### 1.2 `rect`

Source: `_draw_rect`, lines 1049-1078.

| Field       | Required | Type                          | Default      | Notes                                                          |
|-------------|----------|-------------------------------|--------------|----------------------------------------------------------------|
| `cmd`       | yes      | `"rect"`                       | —            |                                                                |
| `min`       | yes      | `[number, number]`             | `[0, 0]`     | currently `.get(default)` — **silent-failure mask**            |
| `max`       | yes      | `[number, number]`             | `[0, 0]`     | currently `.get(default)` — **silent-failure mask**            |
| `color`     | no       | hex string                     | `"#FFFFFF"`  | genuine optional                                               |
| `thickness` | no       | number > 0                     | `1.0`        | genuine optional                                               |
| `rounding`  | no       | number >= 0                    | `0.0`        | genuine optional                                               |
| `filled`    | no       | bool                           | `False`      | genuine optional                                               |

### 1.3 `circle`

Source: `_draw_circle`, lines 1080-1102.

| Field       | Required | Type                          | Default      | Notes                                              |
|-------------|----------|-------------------------------|--------------|----------------------------------------------------|
| `cmd`       | yes      | `"circle"`                     | —            |                                                    |
| `center`    | yes      | `[number, number]`             | `[0, 0]`     | currently `.get(default)` — **silent-failure mask** (the motivating bug) |
| `radius`    | yes      | number > 0                     | `10`         | currently `.get(default)` — **silent-failure mask** |
| `color`     | no       | hex string                     | `"#FFFFFF"`  | genuine optional                                   |
| `thickness` | no       | number > 0                     | `1.0`        | genuine optional                                   |
| `filled`    | no       | bool                           | `False`      | genuine optional                                   |

### 1.4 `triangle`

Source: `_draw_triangle`, lines 1104-1132.

| Field       | Required | Type                          | Default      | Notes                                              |
|-------------|----------|-------------------------------|--------------|----------------------------------------------------|
| `cmd`       | yes      | `"triangle"`                   | —            |                                                    |
| `p1`        | yes      | `[number, number]`             | —            | raw `cmd["p1"]` — already strict                   |
| `p2`        | yes      | `[number, number]`             | —            | raw `cmd["p2"]` — already strict                   |
| `p3`        | yes      | `[number, number]`             | —            | raw `cmd["p3"]` — already strict                   |
| `color`     | no       | hex string                     | `"#FFFFFF"`  | genuine optional                                   |
| `thickness` | no       | number > 0                     | `1.0`        | genuine optional                                   |
| `filled`    | no       | bool                           | `False`      | genuine optional                                   |

### 1.5 `text`

Source: lines 1039-1043.

| Field   | Required | Type                          | Default      | Notes                                                          |
|---------|----------|-------------------------------|--------------|----------------------------------------------------------------|
| `cmd`   | yes      | `"text"`                       | —            |                                                                |
| `pos`   | yes      | `[number, number]`             | `[0, 0]`     | currently `.get(default)` — **silent-failure mask**            |
| `text`  | yes      | string (any, may be empty)     | `""`         | currently `.get(default)` — drawing empty text is meaningless; **silent-failure mask** if user typoed |
| `color` | no       | hex string                     | `"#FFFFFF"`  | genuine optional                                               |

### 1.6 `polyline`

Source: `_draw_polyline`, lines 1134-1151.

| Field       | Required | Type                          | Default      | Notes                                              |
|-------------|----------|-------------------------------|--------------|----------------------------------------------------|
| `cmd`       | yes      | `"polyline"`                   | —            |                                                    |
| `points`    | yes      | list of `[number, number]` (len >= 2) | `[]` | currently `.get(default)`; renderer no-ops if fewer than 2 points — **silent-failure mask** |
| `color`     | no       | hex string                     | `"#FFFFFF"`  | genuine optional                                   |
| `thickness` | no       | number > 0                     | `1.0`        | genuine optional                                   |
| `closed`    | no       | bool                           | `False`      | genuine optional                                   |

### 1.7 `bezier_cubic`

Source: `_draw_bezier`, lines 1153-1172.

| Field       | Required | Type                          | Default      | Notes                                              |
|-------------|----------|-------------------------------|--------------|----------------------------------------------------|
| `cmd`       | yes      | `"bezier_cubic"`               | —            |                                                    |
| `p1`        | yes      | `[number, number]`             | —            | raw indexing — already strict                      |
| `p2`        | yes      | `[number, number]`             | —            | raw indexing — already strict                      |
| `p3`        | yes      | `[number, number]`             | —            | raw indexing — already strict                      |
| `p4`        | yes      | `[number, number]`             | —            | raw indexing — already strict                      |
| `color`     | no       | hex string                     | `"#FFFFFF"`  | genuine optional                                   |
| `thickness` | no       | number > 0                     | `1.0`        | genuine optional                                   |

### 1.8 The unwritten ninth: unknown `cmd`

The current dispatcher falls through silently when `cmd_type` does not match any branch (line 1047 is the last `elif`; there is no `else`). Sending `{"cmd": "spiral"}` or the motivating bug's `{"op": "circle", ...}` (which produces `cmd_type == ""`) draws nothing and logs nothing. This is the most common failure mode the validator will close.

### 1.9 Summary of structural-vs-optional split

Of the 30+ `.get()` calls in the draw renderer, six are structural fields whose defaults exist only because no validator guarantees presence: `rect.min`, `rect.max`, `circle.center`, `circle.radius`, `text.pos`, `text.text`, `polyline.points`. These are the silent-failure masks. Everything else (`color`, `thickness`, `rounding`, `filled`, `closed`) is a genuine optional.

---

## 2. Where Validation Runs

### 2.1 The three candidates

(a) **`DrawElement.__post_init__`** — runs at construction, including the codec's `_draw_from_dict` path. Validates each command.

(b) **Custom `DrawElement.from_dict`** classmethod — replaces `_draw_from_dict`, validates before constructing.

(c) **Separate `_validate_draw_commands(list[dict])` function** — called from `_draw_from_dict` and optionally from `__post_init__`.

### 2.2 Pick: (a) `__post_init__` validation, on a typed command object

The mature form of this is to stop modeling draw commands as `dict[str, Any]` at all. Each command becomes a frozen dataclass — `LineCmd`, `RectCmd`, `CircleCmd`, etc. — and `DrawElement.commands` becomes `list[DrawCommand]` (a union). The codec parses each dict to the right command class via a registry mirroring `ElementCodec`. Construction validates the structural invariants.

This is option (a) realized properly: validation lives on the dataclass, in `__post_init__`, in the same idiom as `TableFilter` (`table.py:33-41`) and `TableDetail` (`table.py:65-71`). The codec's job is dispatch by tag; the type's job is invariants.

**Why on the dataclass and not in the codec:**

- `TableFilter` validates `column` non-empty and `combo` items in `__post_init__`. Programmatic constructions (not just wire-decoded ones) get the same check. If a future caller builds a `DrawElement` in Python with a bad `CircleCmd`, the bug surfaces at construction, not at render time on a remote display.
- The codec already validates the discriminant (`kind` in `ElementCodec.from_dict`, `type` in `MessageRegistry`). Per-command validation is the same pattern one layer down. The wire layer and the type layer use the same idiom — fewer surprises.
- `frozen=True, slots=True` does not block `__post_init__` validation that only raises. It blocks `__post_init__` that wants to write derived state — that needs `object.__setattr__`, exactly the trick `TableFilter` uses for `_column`. Draw commands don't need derived state; they just need to raise on bad input.

**Why not a free function:**

A `_validate_draw_commands(list[dict])` function called only from the codec leaves the dataclass un-policed. Construct a `CircleCmd` in Python with no `center`, and you get a silently-broken render. Validation belongs with the type.

**Why not a custom `from_dict`:**

A custom `DrawElement.from_dict` that validates is just `__post_init__` with extra indirection. The codec is already a custom `from_dict` (`_draw_from_dict`). Splitting validation between the codec and the dataclass means readers have to look in two places. Keep it on the dataclass.

### 2.3 Concrete shape

```python
@dataclass(frozen=True, slots=True)
class CircleCmd:
    cmd: Literal["circle"] = "circle"
    center: tuple[float, float] = (0.0, 0.0)
    radius: float = 0.0
    color: str = "#FFFFFF"
    thickness: float = 1.0
    filled: bool = False

    def __post_init__(self) -> None:
        _require_point("circle.center", self.center)
        _require_positive("circle.radius", self.radius)
        _require_hex_color("circle.color", self.color)
        _require_positive("circle.thickness", self.thickness)


DrawCommand = LineCmd | RectCmd | CircleCmd | TriangleCmd | TextCmd | PolylineCmd | BezierCubicCmd


@dataclass(frozen=True, slots=True)
class DrawElement:
    id: str
    kind: Literal["draw"] = "draw"
    width: int = 400
    height: int = 300
    bg_color: str | None = None
    commands: tuple[DrawCommand, ...] = ()
    tooltip: str | None = None
```

`commands` becomes a tuple of typed commands. The renderer dispatches on type (one `match` or one isinstance ladder) and reads fields directly — no `.get()` left in the hot path.

The codec uses a small per-command registry:

```python
_DRAW_DECODERS: dict[str, Callable[[Mapping[str, Any]], DrawCommand]] = {
    "line": _line_from_dict,
    "rect": _rect_from_dict,
    "circle": _circle_from_dict,
    ...
}


def _draw_cmd_from_dict(d: Mapping[str, Any], index: int) -> DrawCommand:
    cmd = d.get("cmd")
    if not isinstance(cmd, str) or not cmd:
        msg = f"draw command [{index}] missing or invalid 'cmd' field; got {d!r}"
        raise ValueError(msg)
    decoder = _DRAW_DECODERS.get(cmd)
    if decoder is None:
        known = ", ".join(sorted(_DRAW_DECODERS))
        msg = f"draw command [{index}] has unknown 'cmd' {cmd!r}; expected one of: {known}"
        raise ValueError(msg)
    return decoder(d)
```

Each per-command decoder pulls fields from the dict with explicit defaults for the optional ones and constructs the dataclass. Construction triggers `__post_init__`, which raises a `ValueError` with the command index, command type, and field name. The codec re-raises with the index attached if the underlying message doesn't carry it.

### 2.4 How errors reach the caller

The `show()` MCP tool already converts a dict to an `Element` via `element_from_dict` (`tools/tools.py:131`). That call now raises `ValueError` before the scene reaches the wire. The tool needs to catch and return a string error consistent with its existing error returns (`"error: frame_size must be [width, height]"`, line 135):

```python
try:
    typed_elements = [element_from_dict(e) for e in elements]
except ValueError as exc:
    return f"error: {exc}"
```

This is the same pattern PR #172 established for unknown `kind`. The agent gets a one-line error string. No display round-trip. No silent default render.

`AckMessage` already has an `error: str | None` field (`lifecycle.py:61`), so a future variant could surface render-time errors the same way. That is out of scope here — validation lives at the wire boundary, where the failure happens, not at the renderer.

---

## 3. Error Contract

One exception type. One message format. One place errors surface.

### 3.1 Exception type

`ValueError` for every failure. Matches `ElementCodec.from_dict` (`codec.py:75-93`), `MessageRegistry`, and `TableFilter`. `TypeError` is reserved for wrong-class encode failures (`ElementCodec.to_dict`).

### 3.2 Message format

Every message includes (a) the command index in the parent `commands` list, (b) the command type, (c) the field name, (d) what was expected, (e) what was got. Example messages:

| Failure mode                                  | Message                                                                                       |
|-----------------------------------------------|-----------------------------------------------------------------------------------------------|
| Missing `cmd` field                            | `draw command [2] missing or invalid 'cmd' field; got {'op': 'circle', 'x': 100, ...}`        |
| Empty / non-string `cmd`                       | same as above (`isinstance(cmd, str) and cmd` is the unified check)                            |
| Unknown `cmd` value                            | `draw command [0] has unknown 'cmd' 'spiral'; expected one of: bezier_cubic, circle, line, polyline, rect, text, triangle` |
| Missing required field for known cmd          | `draw command [3] (circle) missing required field 'center'`                                   |
| Wrong type for required field                  | `draw command [1] (circle) field 'center' must be [x, y] number pair; got 'left'`              |
| Out-of-range value                             | `draw command [4] (circle) field 'radius' must be > 0; got -2`                                |
| Wrong-length point                             | `draw command [0] (line) field 'p1' must be [x, y] number pair; got [1, 2, 3]`                |
| Non-numeric coordinate                         | `draw command [0] (line) field 'p1' must be [x, y] number pair; got [1, 'two']`                |
| Polyline with fewer than 2 points              | `draw command [0] (polyline) field 'points' requires at least 2 points; got 1`                |
| Bad hex color                                  | `draw command [2] (rect) field 'color' must be hex color '#RRGGBB' or '#RRGGBBAA'; got 'red'` |

Format rules:

- lowercase, no period (matches the project's user-facing error style)
- the command index is in brackets so it scans
- the command type is parenthetical after the index
- the field name is single-quoted
- the malformed value is included via `!r` so quoting is unambiguous

### 3.3 Where the error surfaces

- **Programmatic construction**: `CircleCmd(...)` or `DrawElement(commands=(...))` raises at the construction site.
- **Wire decode**: `_draw_from_dict` calls `_draw_cmd_from_dict` for each command; the first malformed command raises and aborts decode. Fail-fast, not collect-all — consistent with `ElementCodec`.
- **MCP `show` tool**: `element_from_dict` raises; `show()` catches `ValueError` and returns `f"error: {exc}"`. The agent sees the error in the tool result, not a default-rendered scene.

### 3.4 What `AckMessage.error` is for

`AckMessage.error` (`lifecycle.py:61`) carries render-time errors back from the display. That field already exists and we leave it alone. Wire-decode errors don't need it — they fail before reaching the wire.

---

## 4. Renderer `.get()` Removal

After validation, every structural field is guaranteed present and well-typed. The renderer reads attributes off typed commands instead of dict `.get()`.

### 4.1 Removed `.get()` calls

Line numbers refer to `src/punt_lux/display/element_renderer.py` as of this design.

| Line | Call                                | Disposition |
|------|-------------------------------------|-------------|
| 1021 | `cmd.get("cmd", "")`                 | REMOVE — dispatcher matches on typed command class, not a dict key |
| 1040 | `cmd.get("pos", [0, 0])`             | REMOVE — `TextCmd.pos` guaranteed present |
| 1042 | `cmd.get("text", "")`                | REMOVE — `TextCmd.text` guaranteed present (validator enforces) |
| 1060 | `cmd.get("min", [0, 0])`             | REMOVE — `RectCmd.min` guaranteed present |
| 1061 | `cmd.get("max", [0, 0])`             | REMOVE — `RectCmd.max` guaranteed present |
| 1091 | `cmd.get("center", [0, 0])`          | REMOVE — `CircleCmd.center` guaranteed present (the motivating bug) |
| 1092 | `cmd.get("radius", 10)`              | REMOVE — `CircleCmd.radius` guaranteed > 0 |
| 1146 | `cmd.get("points", [])`              | REMOVE — `PolylineCmd.points` guaranteed (len >= 2 by validator) |

### 4.2 Retained — genuine optional fields

These stay because the field is truly optional and the default is meaningful. They become dataclass defaults instead of `.get()` defaults:

| Line | Call                                | Disposition                                            |
|------|-------------------------------------|--------------------------------------------------------|
| 1022 | `cmd.get("color", "#FFFFFF")`        | KEEP as default on every `*Cmd.color` field            |
| 1023 | `cmd.get("thickness", 1.0)`          | KEEP as default on every `*Cmd.thickness` field        |
| 1062 | `cmd.get("rounding", 0.0)`           | KEEP as `RectCmd.rounding` default                     |
| 1063 | `cmd.get("filled", False)`           | KEEP as `RectCmd.filled` default                       |
| 1093 | `cmd.get("filled", False)`           | KEEP as `CircleCmd.filled` default                     |
| 1118 | `cmd.get("filled", False)`           | KEEP as `TriangleCmd.filled` default                   |
| 1147 | `cmd.get("closed", False)`           | KEEP as `PolylineCmd.closed` default                   |

### 4.3 Code shape after removal

`_dispatch_draw_cmd` collapses to ~30 lines of straight-line dispatch on type. Each `_draw_*` helper drops to 5-15 lines because it reads typed attributes:

```python
def _draw_circle(self, dl: Any, cmd: CircleCmd, ox: float, oy: float) -> None:
    from imgui_bundle import ImVec2

    color = self._to_imgui_color(cmd.color)
    cx, cy = cmd.center
    if cmd.filled:
        dl.add_circle_filled(ImVec2(ox + cx, oy + cy), cmd.radius, color)
    else:
        dl.add_circle(ImVec2(ox + cx, oy + cy), cmd.radius, color, 0, cmd.thickness)
```

The `try/except` at lines 1003-1006 (`Skipping malformed draw command: %s`) can go too — it cannot fire because the dispatcher is total over typed commands. That removes another defensive-coding scar, per PY-EH-5 and PL-PP-3.

---

## 5. Test Plan

Tests live in `tests/test_protocol.py` (validation tests) and `tests/test_tools.py` (the `show()` error path). One test per failure mode per command type, plus roundtrips.

### 5.1 Per-command validation tests

For each command type (`line`, `rect`, `circle`, `triangle`, `text`, `polyline`, `bezier_cubic`):

1. **Happy path construction** — valid required fields, optionals omitted, defaults applied. Asserts the command constructs and serializes round-trip.
2. **Missing each required field** — one test per field, asserts `ValueError` with message containing the field name and command type. Example for `circle`:
   - `test_circle_requires_center` — `CircleCmd(radius=5.0)` raises `ValueError` mentioning `center`.
   - `test_circle_requires_radius` — `CircleCmd(center=(10, 10))` raises `ValueError` mentioning `radius`.
3. **Wrong type on a required field** — at least one per command. Example: `CircleCmd(center="left", radius=5.0)` raises with message mentioning `center` and the expected shape.
4. **Out-of-range** — for `radius`, `thickness`, `rounding`. Example: `CircleCmd(center=(10, 10), radius=-1)` raises with message mentioning `> 0`.

### 5.2 Cross-command validation tests

1. **Unknown `cmd` value** — `_draw_cmd_from_dict({"cmd": "spiral"}, 0)` raises `ValueError` listing the registered types.
2. **Missing `cmd` field** — `_draw_cmd_from_dict({"op": "circle", "x": 100}, 0)` raises with the literal motivating-bug payload. This is the regression test for lux-4n1b.
3. **Empty/non-string `cmd`** — `{"cmd": ""}`, `{"cmd": None}`, `{"cmd": 7}` each raise.
4. **Command index in message** — `_draw_cmd_from_dict({"cmd": "spiral"}, 4)` includes `[4]` in the error message so the failing position is locatable in a long list.
5. **Polyline length** — `PolylineCmd(points=[(1, 1)])` raises (one point can't draw a line).
6. **Color format** — `LineCmd(p1=(0, 0), p2=(1, 1), color="red")` raises with the expected `#RRGGBB`/`#RRGGBBAA` shape.

### 5.3 Roundtrip and integration

1. **Roundtrip per command type** — build → `_draw_to_dict` → `_draw_from_dict` → compare. Existing `test_draw_roundtrip` (`test_protocol.py:873`) is extended to cover each command type. Pure renames update `test_draw_element` (line 145) and `test_draw_element_defaults` (line 154) for the new typed-commands shape.
2. **`show()` returns error on malformed draw** — `tests/test_tools.py` calls `show("s1", [{"kind": "draw", "id": "d", "commands": [{"op": "circle"}]}])` and asserts the return value starts with `"error:"` and mentions `draw command [0]`.
3. **`show()` succeeds on valid draw** — calls `show` with a valid two-command scene and asserts an `ack:` prefix.
4. **Existing draw tests still pass** — `test_draw_element`, `test_draw_element_defaults`, `test_draw_roundtrip`, `test_draw_bg_color_excluded_when_none` either pass unchanged (semantics preserved) or get a mechanical update for the typed-commands shape with no behavior change. The shape change is the only acceptable diff.

### 5.4 Markers and scope

All tests are tier-1 unit tests (no `@pytest.mark.integration`, no display required). They run under `make test`.

---

## 6. Risks and Migration

### 6.1 Existing draw constructions

Grep across `src/` and `tests/` finds three classes of caller:

- **Internal tests** — `tests/test_protocol.py` (4 sites), `tests/test_tools.py` (2 sites). All use schema-correct commands today (`{"cmd": "line", "p1": [0, 0], "p2": [10, 10]}`, `{"cmd": "rect", "min": [10, 10], "max": [50, 50]}`). They need a mechanical update to the typed-commands shape — `cmds=[LineCmd(p1=(0, 0), p2=(10, 10))]` — but the values are valid.
- **Docstring examples** — `tools/tools.py:89` shows the schema-correct form (`{"kind": "draw", "id": "d1", "commands": [...]}`). The docstring is not a runtime caller. It needs a small expansion to document the per-command schema (the validator already implies this).
- **Application code** — `apps/beads.py` does not construct `DrawElement`. No other apps use it. The only production callers go through MCP `show()` from agents, and they construct dicts. Agents see the new error contract via the `show()` tool's return value.

No scene shipped from the codebase will break. The one observed bad caller is the motivating bug — an agent that constructed the wrong schema by hand. That caller is what we are surfacing.

### 6.2 Backwards compatibility

Reject it. No deprecation window, no schema translator, no `{op, x, y, r}` alias for `{cmd, center, radius}`. The project pattern is fail-fast (PR #164 dataclass strictness, PR #172 codec strictness, PR #171 bd-failure surfacing). A misspelled command has always rendered incorrectly; the change makes it raise instead. There is nothing to preserve.

### 6.3 Performance

Validation runs once at decode time per command. Each command is ~5 type/range checks against pre-validated dataclass fields. A scene with 1,000 commands adds ~5,000 cheap branch+compare operations — sub-millisecond on any modern CPU. Render-time cost goes *down* because the renderer no longer hashes 30+ dict keys per frame; it reads slot attributes.

### 6.4 Pyright/mypy fallout

`DrawElement.commands: list[dict[str, Any]]` → `tuple[DrawCommand, ...]` changes the type signature. The internal codec is the only direct user of `commands` as a list of dicts; switching it to typed commands removes the `Any` parameter in the renderer's `cmd: dict[str, Any]` signatures and replaces them with `cmd: CircleCmd` etc. That tightens the type graph in our favor. The `Any` import in `graphics.py` survives only on `tooltip`-irrelevant pieces, if at all.

### 6.5 Cross-element parallels (noted, out of scope)

`TabBarElement.tabs: list[dict[str, Any]]` and `TreeElement.nodes: list[dict[str, Any]]` have the same shape. Not in this design. File follow-up beads after this lands so the same anti-pattern doesn't grow elsewhere.

---

## 7. Why This Makes the Code Better

### 7.1 Cognition

A future contributor adding a new draw command — say, `arc` — reads `CircleCmd` and sees the full contract: dataclass fields, defaults, `__post_init__` checks. They add `ArcCmd` next to it, register it in `_DRAW_DECODERS`, and the renderer dispatches via type. Today the same contributor has to read 200 lines of `element_renderer.py` and notice which `.get()` calls are real defaults and which are missing-field masks. The validator makes the contract co-located with the type.

### 7.2 Debugging

The motivating bug took multiple round-trips: the user shipped a scene, the display drew one circle, the user re-shipped with different commands trying to figure out why colors weren't applied, the screenshot tool confirmed only one circle was drawn, then someone read `_dispatch_draw_cmd` and noticed the `cmd_type == ""` silent fallthrough. With the validator, the first `show()` call returns `"error: draw command [0] missing or invalid 'cmd' field; got {'op': 'circle', 'x': 100, ...}"`. The user fixes the schema, ships once, sees five circles. One round-trip instead of five.

### 7.3 Defensive code reduction

Eight `.get(field, default)` calls disappear from `_dispatch_draw_cmd` and the `_draw_*` helpers (section 4.1). The `try/except (KeyError, IndexError, TypeError, ValueError): logger.debug(...)` block at `element_renderer.py:1003-1006` disappears too — the dispatcher is total over typed commands, so it cannot fire. The renderer becomes shorter and faster (slot attribute reads instead of dict `.get()` indirection). Per PY-EH-5 and PL-PP-3, defensive try/except at non-boundaries was already disallowed; this change removes the last one in the draw path.

### 7.4 Pattern consistency

Strict wire-boundary validation is now the project pattern:

| Site                                  | Pattern                                             | PR / bead   |
|---------------------------------------|-----------------------------------------------------|-------------|
| `ElementCodec.from_dict` — `kind`      | raises `ValueError` on missing/invalid              | PR #172     |
| `MessageRegistry.from_dict` — `type`   | raises (or returns `UnknownMessage` for messages)   | PR #172     |
| `TableFilter.__post_init__`            | raises `ValueError` on empty/bad column             | existing    |
| `TableDetail.__post_init__`            | raises `ValueError` on rows/body mismatch           | existing    |
| `TableElement.__post_init__`           | raises `ValueError` on width/detail mismatch        | existing    |
| `BeadsBrowser`                          | surfaces `bd` failures instead of empty render       | PR #171     |
| `DrawElement` per-command validation    | **this design**                                     | lux-4n1b    |

`DrawElement` was the last `list[dict[str, Any]]` element type with structural fields read by the renderer via `.get()`. Closing this gap completes the "fail loud at the wire boundary" architectural pattern.

### 7.5 What this does NOT fix

- **Other `list[dict[str, Any]]` element fields** — `TabBarElement.tabs`, `TreeElement.nodes`, and `PlotElement.series` have the same anti-pattern in latent form. Not in scope. File follow-up beads.
- **Render-time errors** — texture upload failure for `ImageElement`, font fallback for unsupported glyphs, etc. Those happen after the wire boundary and need a different mechanism (the `AckMessage.error` field exists for this; it is unused for render-time errors today).
- **Agent-side schema discovery** — the validator improves error messages, but agents still write JSON by hand. A separate effort (typed MCP tool signatures or a draw-command builder library) would let agents construct commands in Python with type checking. Out of scope.
- **Coordinate validity** — the validator checks that `center` is a 2-number pair, not that the center is inside the canvas. Drawing offscreen is legal.

### 7.6 OO ratchet movement

Effect on `tools/oo_score.py` metrics, per file:

- `src/punt_lux/display/element_renderer.py`:
  - `module_size` — improves. ~50 net lines removed (8 `.get()` defaults gone, the try/except gone, helper bodies shrink from 15 lines to 5-10).
  - `max_complexity` — improves. `_dispatch_draw_cmd`'s 8-branch elif ladder becomes a typed dispatch with no defensive try/except; cyclomatic complexity drops.
  - `method_ratio` — unchanged (no new free functions).
  - `init_violations`, `public_attr_violations`, `future_annotations` — unchanged.

- `src/punt_lux/protocol/elements/graphics.py`:
  - `module_size` — worse. ~150 lines added (seven `*Cmd` dataclasses with `__post_init__`, the helper validators, the per-command decoder registry). Threshold is 300; the file goes from ~99 lines to ~250 lines. Still under threshold.
  - `classes_per_module` — worse. Adds 7 command classes plus `DrawElement` and `PlotElement`. Module exceeds the 3-class limit (PL-MD threshold).
  - **Mitigation**: split. The seven draw command classes belong in `protocol/elements/draw_commands.py`. `graphics.py` keeps `DrawElement` (with `DrawCommand` union imported) and `PlotElement`. This keeps each module under both `module_size` (300) and `classes_per_module` (3), and respects PY-OO-2 "one concept per module."
  - `method_ratio` — improves. Per-command decoders move from module-level functions to `@classmethod from_dict` on each command class (PY-CC-5 alternative constructor), increasing the method-vs-function ratio.

Net package effect: `display/element_renderer.py` improves on three metrics. `protocol/elements/graphics.py` improves on `method_ratio` while staying within all thresholds via the split. No regressions. The ratchet moves forward.

---

— rmh, 2026-05-21
