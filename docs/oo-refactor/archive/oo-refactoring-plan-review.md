# Refactoring Plan Review

Reviewer: Ralph Johnson (rej)
Date: 2026-05-13

## Safety Assessment

### Pre-flight (P.1 through P.6)

**P.1: Fix `_emit_event` recursion bug.** Safe. The bug is real — line 2028 of
`display.py` calls `self._emit_event(event)` recursively instead of
`self._event_queue.append(event)`. The fix is a one-line change. The plan
correctly notes the bug is latent (the `if` branch is never taken in practice),
so fixing it cannot change observable behavior. The specified test is
appropriate.

**P.2: Create `types.py`.** Safe. New file, no existing code changes.

**P.3: Fix `future_annotations` import.** Safe. `apps/__init__.py` is an
empty file (0 bytes). Adding a future import changes nothing at runtime.

**P.4: Fix `public_attr_violations` and `encapsulation_ratio`.** Mostly safe.
The plan says to prefix public attributes with underscore and add `@property`
accessors. For `RenderContext`, this is a **breaking change for user code** —
user-defined `render(ctx)` functions access `ctx.state`, `ctx.dt`, `ctx.frame`,
`ctx.width`, and `ctx.height` directly. Adding `@property` accessors with the
original names preserves the read path, but any user code that *assigns* to
these attributes (e.g., `ctx.state = {}`) would break because properties without
setters reject assignment. The plan does not mention this. `RenderContext` also
has `__slots__`, which complicates the `__init__` to `__new__` conversion in
P.5.

RISK: `RenderContext` attributes are part of the user-facing API. The rename
needs property accessors with setters (not just getters) or the user API breaks.

**P.5: Fix `init_violations` — convert `__init__` to `__new__`.** This is the
highest-risk step in the pre-flight. The plan lists 7 classes:
`TextureCache`, `WidgetState`, `DisplayServer` (in display.py),
`DisplayClient` (in display_client.py), `FrameReader` (in protocol.py),
`RenderContext`, and `CodeExecutor` (in runtime.py).

Specific risks:

1. **`RenderContext` uses `__slots__`.** When a class defines `__slots__`, you
   cannot assign arbitrary attributes on the instance from `__new__` unless
   you assign to the slot names. The pattern `self = super().__new__(cls);
   self._attr = val; return self` works with `__slots__`, but the attribute
   names must match the slot names exactly. The plan says to prefix attributes
   with underscore (P.4), which changes the slot names. The `__slots__`
   declaration must be updated in lockstep. The plan does not mention this
   interaction.

2. **`CodeExecutor.__init__` calls `self._compile()`.** The `__new__`
   conversion must call `self._compile()` before `return self`. This is safe
   as long as `_compile` does not depend on the instance being "fully
   constructed" in some framework sense — and it does not, since it only
   accesses `self.source` (set before the call). Safe.

3. **`DisplayServer.__init__` is 60 lines long.** The mechanical `__init__` to
   `__new__` conversion is straightforward (no `super().__init__` calls) but
   the sheer size increases the chance of a transcription error. The plan
   should specify running the full test suite, which it does via "make check."

4. **`DisplayClient.__init__` is 50 lines.** Same as above — no super calls,
   mechanical conversion.

5. **No subclasses exist** for any of these 7 classes. Verified by grep. No
   `super().__init__()` calls in any of them. The conversion is safe from an
   inheritance standpoint.

6. **None of these classes call `super().__init__()` with arguments.** Verified.
   The conversion to `self = super().__new__(cls)` is correct.

RISK: The P.4 and P.5 interaction with `RenderContext.__slots__` must be
handled carefully. The plan should make this dependency explicit.

**P.6: Establish baseline metrics.** Safe. Measurement only.

### Phase 1: `protocol.py` to `protocol/` package (Steps 1.1–1.3)

**Step 1.1: Move `protocol.py` to `protocol/__init__.py`.** Safe. This is a
file rename with no code changes. All imports resolve because Python treats
`punt_lux.protocol` identically whether it is a module or a package with
`__init__.py`. The characterization test is correctly identified as the
existing test suite.

**Step 1.2: Extract element dataclasses to `protocol/elements.py`.** Safe in
terms of behavior preservation — the re-exports in `__init__` mean all external
imports remain unchanged. The `ElementCodec` with `__init_subclass__` is a
functional change in how registration works, but the public API
(`element_to_dict`, `element_from_dict`) is preserved as wrapper functions.

RISK: The `__init_subclass__` approach changes the registration mechanism. If
any external code directly accesses `_ELEMENT_SERIALIZERS` or
`_ELEMENT_DESERIALIZERS` dicts, the behavior changes. The plan should verify
no external callers reference these private dicts.

**Step 1.3: Extract message dataclasses to `protocol/messages.py`.** Same
assessment as 1.2. The `MessageCodec` registry replaces the 30-branch
`message_from_dict` if/elif chain with a dict lookup. The behavior is
identical for all known message types. The `UnknownMessage` fallback is
preserved.

RISK: The `message_from_dict` replacement changes the code path for
deserialization. The plan should require that the existing
`tests/test_protocol.py` exercises every message type before this step. If
any message type is untested, a subtle deserialization difference could go
undetected.

### Phase 2: `display.py` extractions (Steps 2.1–2.6)

**Step 2.1: Extract `SceneManager`.** Safe. The plan specifies 8
characterization tests before extraction. The callback design
(`emit_event`, `on_scene_replaced`) avoids circular imports. The state
partitioning is clean — SceneManager owns scene graph state, DisplayServer
owns the event queue and widget state swap.

**Step 2.2: Extract `SocketServer`.** Safe. The plan specifies 4
characterization tests. The callback design (`on_message`,
`on_client_disconnected`, `on_error`) avoids circular imports.

RISK: The `_remove_client` method currently calls into scene ownership
transfer code. The plan correctly identifies this and replaces it with a
callback, but the callback must be tested for the ownership-transfer case
specifically.

**Step 2.3: Extract `TableRenderer`.** Safe. The filter logic is pure
Python. The 5 characterization tests exercise the pure logic. The ImGui
rendering is tested by the existing display test suite.

**Step 2.4: Extract `QueryDispatcher`.** Safe. The plan correctly
identifies which query handlers move (those with no display-wide state
dependency) and which stay (those needing ImGui/window state). The
`Callable` read-accessor pattern avoids importing SocketServer or
MenuManager.

RISK: The lambda accessors (`lambda: self._socket_server._client_names`)
reach into SocketServer's private attributes. This works but creates a
hidden coupling. The plan should note that SocketServer should expose these
as properties.

**Step 2.5: Extract `ElementRenderer`.** Safe, but the plan acknowledges no
new pure-logic tests are possible (ImGui required). The existing test suite
is the verification. The widget state handoff
(`element_renderer.widget_state = ...`) is an explicit assignment, not a
shared reference — good.

**Step 2.6: Extract `MenuManager`.** Safe. The plan specifies 3
characterization tests for `_sanitize_menu_items` (pure logic). The callback
design for theme/chrome selection avoids circular imports.

**Circular import risk across Phase 2.** The plan's invariant #1 ("no
extracted class imports DisplayServer") is the right guard. The callback
pattern prevents upward imports. The `types.py` file provides shared type
aliases. No circular import risk if the invariant is maintained.

**Extraction order.** The plan orders: SceneManager, SocketServer,
TableRenderer, QueryDispatcher, ElementRenderer, MenuManager. This is safe
because each extraction is independent — later extractions do not depend on
earlier ones being complete. QueryDispatcher references SceneManager, but the
plan accounts for this by having QueryDispatcher receive a SceneManager
instance. If SceneManager has not been extracted yet, QueryDispatcher would
receive DisplayServer methods wrapped as callables. The plan should clarify
this dependency.

### Phase 3: `tools.py` refactor (Steps 3.1–3.2)

**Step 3.1: Add `_query_tool` decorator.** Safe. The decorator wraps existing
function bodies without changing behavior. The `functools.wraps` preserves
function metadata. The FastMCP compatibility check is a good safeguard.

RISK: The decorator changes the function signature from the perspective of
FastMCP's schema introspection. The plan correctly identifies this and
specifies a `mcp.list_tools()` verification step. However, the `fn` return
type of `dict | None` may confuse FastMCP if it introspects annotations to
generate the tool schema. The plan mentions overriding
`wrapper.__annotations__["return"]` as a fallback — this should be mandatory
verification, not optional.

**Step 3.2: `ToolState` class.** Marked optional. Safe if done. The
`ContextVar` subtlety is correctly identified.

### Phase 4: `display_client.py` migration (Steps 4.1–4.2)

**Step 4.1: Deprecate three methods.** Safe. The wrappers delegate to
`query()`, which already exists. The `DeprecationWarning` is correct.

**Step 4.2: Remove deprecated methods.** Deferred to a future release. Not
a risk for this plan — the step is clearly labeled as post-deprecation.

### Phase 5: Smaller module refactors (Steps 5.1–5.7)

All seven steps follow the same pattern: wrap module-level functions in a
class, keep backward-compat wrappers. Each is a standard Extract Class
refactoring. No implicit behavior changes.

**Step 5.3b: Hub sub-app CLI change.** `lux hub-install` becomes
`lux hub install`. This is a **breaking CLI change**. The plan specifies
backward-compat aliases (hidden commands), which is the correct mitigation.
However, hook scripts that invoke `lux hub-install` would break if the
aliases are not tested.

**Step 5.1: `ServiceManager.__init__` uses `__init__`, not `__new__`.** The
code example in the plan shows `def __init__(self)` on `ServiceManager`,
`LaunchdBackend`, and `SystemdBackend`. This contradicts the project's
`PY-CC-1` rule and the P.5 pre-flight step. These new classes should use
`__new__`.

## Comprehensiveness Assessment

### Metric-by-metric analysis

**1. `method_ratio` (current: 0.35, target: >= 0.80).** The aggregate is the
*average* of per-file `method_ratio` values across all modules.

The plan adds classes to: `display.py` (already has classes), `config.py`,
`paths.py`, `remote.py`, `service.py`, `hub.py`, `apps/beads.py`. It adds
new files: `scene_manager.py`, `socket_server.py`, `table_renderer.py`,
`query_dispatcher.py`, `element_renderer.py`, `menu_manager.py`, `doctor.py`,
`types.py`, and the `protocol/` sub-modules.

Files that *remain at method_ratio 0.0*: `hooks.py` (4 functions, 0 classes),
`show.py` (1 function, 0 classes). The plan explicitly says these stay
function-only.

Files that will have *mixed* ratios: `tools.py` (32 top-level functions,
0-1 classes — Step 3.2 is optional), `__main__.py` (~15 remaining functions
after DoctorChecker extraction, 0 classes at module level).

Post-refactoring estimate: The new extraction files (scene_manager.py,
socket_server.py, etc.) will each have method_ratio near 1.0 (all-class
files). The protocol sub-modules will have mixed ratios (dataclass classes
counted as having methods). But `tools.py` at 0.0, `hooks.py` at 0.0,
`show.py` at 0.0, and `__main__.py` near 0.0 will drag the average down.

With ~25 files, and about 6 files at or near 0.0, the average will be
roughly `(19 * ~0.8 + 6 * ~0.05) / 25 = ~0.62`. This is below the 0.80
target.

VERDICT: **method_ratio will likely NOT pass.** The plan does not address
`tools.py` (32 functions, optional ToolState only wraps 5), `__main__.py`
(22 functions), `hooks.py`, or `show.py`.

**2. `encapsulation_ratio` (current: 0.95, target: >= 1.0).** P.4 addresses
all 6 public attr violations in `runtime.py` and 1 in `protocol.py`.

VERDICT: **Will pass** after P.4.

**3. `avg_params` (current: 0.84, target: <= 4.0).** Already passing. The
plan does not introduce high-parameter functions.

VERDICT: **Will pass.**

**4. `max_complexity` (current: 30, target: <= 10).** The aggregate uses
`max()` across all files. The two functions at complexity 30 are:

- `message_from_dict` in `protocol.py` (complexity 30) — the 30-branch
  if/elif chain. Step 1.3 replaces this with a registry lookup. The new
  `message_from_dict` is ~6 lines with complexity ~3.

- `_render_table` in `display.py` (complexity 20) — Step 2.3 extracts this
  to `TableRenderer`. The function itself is not decomposed; it moves
  wholesale. If the method body stays intact, its complexity stays at 20.

After Phase 1, the `protocol.py` complexity 30 drops. After Phase 2, the
`display.py` complexity 20 remains in `table_renderer.py`. The next highest
is `_handle_message` at 14, then `_render_plot` at 13.

VERDICT: **Will NOT pass.** The plan reduces max from 30 to ~20 (from
`_render_table`, now in `table_renderer.py`). Still above the target of 10.
The plan does not decompose `_render_table`, `_handle_message`,
`_render_plot`, `_render_paged_group`, `_render_modal`, `_flush_events`,
`_dismiss_scene`, `_close_frame`, or `_auto_click_buttons` — all at
complexity 11-20. At least 6 functions exceed the target of 10.

**5. `avg_complexity` (current: 2.70, target: <= 5.0).** Already passing.

VERDICT: **Will pass.**

**6. `module_size` (current: 3680, target: <= 300).** The aggregate uses
`max()`. The plan reduces `display.py` from 4,208 to ~900 lines. However,
`element_renderer.py` is projected at ~1,200 lines, `protocol/elements.py`
at ~900 lines, `protocol/messages.py` at ~800 lines, `tools.py` at ~900
lines, `display_client.py` at ~600 lines.

VERDICT: **Will NOT pass.** The largest file will be `element_renderer.py`
at ~1,200 lines, still 4x the 300-line target. The plan acknowledges this
("justified by 24 parallel render methods that share one responsibility")
but the metric does not accept justifications — it measures lines.

**7. `classes_per_module` (current: 3.35, target: <= 3).** The aggregate is
an average. The current score is 3.35 because `protocol.py` has 49 classes
and `display.py` has 4 classes. After the split:

- `protocol/elements.py`: Will contain ~26 element dataclasses + helper
  types (`TableFilter`, `TableColumn`, `Patch`, `TableDetail`) +
  `_ElementBase` mixin. That is ~30 classes. This single file will have
  `classes_per_module = 30`, which alone produces an average contribution
  much larger than 3.

- `protocol/messages.py`: Will contain ~20 message dataclasses + helper
  types. About 22 classes.

The average across ~25 files: most files have 0-2 classes, but
`elements.py` at 30 and `messages.py` at 22 will push the average to
roughly (30 + 22 + ~15 scattered) / 25 = ~2.7. This might barely pass.

Actually, the dataclasses ARE counted by `_count_classes`. Each element
dataclass is a separate ClassDef. With `protocol/__init__.py` at ~0 classes
(re-exports only), `elements.py` at ~30, `messages.py` at ~22, and the
remaining ~22 files averaging ~0.5 classes each, the average is
(30 + 22 + ~11) / 25 = ~2.5.

VERDICT: **Likely passes**, but marginal. If the implementer puts all 48
element/message dataclasses into just two files, the per-file count is high
but the average across 25 files dilutes it below 3.

**8. `class_to_func_ratio` (current: 0.31, target: >= 0.5).** Averaged
across files. Same concern as `method_ratio` — files with 0 classes and
many functions (tools.py, hooks.py, show.py, `__main__.py`) drag the average
down.

VERDICT: **Will likely NOT pass** for the same reasons as `method_ratio`.
The plan leaves `tools.py` (0 classes, 32 functions), `hooks.py` (0, 4),
`show.py` (0, 1), and `__main__.py` (0-1 classes, ~15 functions) as-is.

**9. `init_violations` (current: 3, target: == 0).** The aggregate uses
`max()`. P.5 converts all 7 `__init__` methods to `__new__`. However, Step
5.1 introduces *new* classes (`ServiceManager`, `LaunchdBackend`,
`SystemdBackend`) with `__init__` in the example code. The plan's code
examples show `def __init__(self)` on these new classes.

VERDICT: **Will NOT pass** if the new classes in Phase 5 use `__init__` as
shown in the plan's code examples. The plan must use `__new__` for all new
classes.

**10. `public_attr_violations` (current: 6, target: == 0).** Aggregate uses
`max()`. P.4 fixes all 7 violations (6 in runtime.py, 1 in protocol.py).

VERDICT: **Will pass** after P.4, assuming no new public attrs are introduced.

**11. `future_annotations` (current: 0, target: == 1).** Aggregate uses
`min()`. P.3 fixes `apps/__init__.py`. The new files (`types.py`,
`scene_manager.py`, etc.) must all include `from __future__ import
annotations`. The plan does not explicitly state this for every new file,
but the `types.py` example shows it.

VERDICT: **Will pass** if every new file includes the import. The plan
should make this an explicit invariant.

### Summary of metrics after plan execution

| Metric | Current | After plan | Target | Pass? |
|--------|---------|-----------|--------|-------|
| method_ratio | 0.35 | ~0.62 | >= 0.80 | NO |
| encapsulation_ratio | 0.95 | 1.0 | >= 1.0 | YES |
| avg_params | 0.84 | ~0.84 | <= 4.0 | YES |
| max_complexity | 30 | ~20 | <= 10 | NO |
| avg_complexity | 2.70 | ~2.5 | <= 5.0 | YES |
| module_size | 3680 | ~1200 | <= 300 | NO |
| classes_per_module | 3.35 | ~2.5 | <= 3 | YES (marginal) |
| class_to_func_ratio | 0.31 | ~0.52 | >= 0.5 | MARGINAL |
| init_violations | 3 | 0 or 3+ | == 0 | DEPENDS |
| public_attr_violations | 6 | 0 | == 0 | YES |
| future_annotations | 0 | 1 | == 1 | YES |

## Specific Concerns

1. **`_render_table` complexity not reduced.** The function has cyclomatic
   complexity 20. Step 2.3 moves it to `TableRenderer` but does not
   decompose it. After the move, `_render_table` remains the system's
   second-highest-complexity function. The plan needs an explicit
   sub-step to decompose this method into smaller methods on
   `TableRenderer` (e.g., `_render_header`, `_render_body`,
   `_render_footer`, `_apply_filters_and_paginate`). Similarly for
   `_render_plot` (13), `_render_paged_group` (12), `_render_modal`
   (12), and at least 4 other functions above 10.

2. **`message_from_dict` replacement is correct but needs test
   coverage.** The 30-branch if/elif chain is replaced by a registry.
   The plan should require that every branch in the existing
   `message_from_dict` has a round-trip test (serialize-deserialize)
   before the registry replacement. Without this, a registration typo
   could silently drop a message type.

3. **`tools.py` method_ratio stays at 0.0.** The plan marks `ToolState`
   as optional and does not address the 32 MCP tool functions. These are
   registered via `@mcp.tool()` decorator, which makes class extraction
   non-trivial — FastMCP registers functions, not methods. The plan
   should either: (a) acknowledge that `tools.py` will not reach
   `method_ratio >= 0.80`, or (b) propose a `ToolRegistry` class with
   `@mcp.tool()` wrappers that delegate to methods.

4. **`hooks.py` and `show.py` method_ratio stays at 0.0.** The plan
   correctly argues these are stateless dispatchers, but the metric does
   not distinguish justified function-only modules from unjustified ones.
   At 0.0, each file drags the aggregate average down.

5. **`__main__.py` class_to_func_ratio stays near 0.0.** After extracting
   `DoctorChecker`, `__main__.py` still has ~15 Typer commands and 0
   classes. Typer commands are by nature top-level functions. The plan
   does not address this.

6. **New classes in Phase 5 use `__init__` in code examples.**
   `ServiceManager.__init__`, `LaunchdBackend.__init__`,
   `SystemdBackend.__init__`, `SessionHub.__init__`,
   `DoctorChecker.__init__`, `DisplayPaths.__init__`,
   `ConfigManager.__init__`, `ProxyConfigFile.__init__`,
   `BeadsBrowser` (no constructor shown). The plan's invariant from P.5
   says "convert `__init__` to `__new__`" but the Phase 5 code examples
   contradict this. If implemented as shown, `init_violations` will
   *increase* — from 3 (after P.5 fixes the original 7) to 8+.

7. **`module_size` cannot reach <= 300 for `element_renderer.py`.** The
   plan projects 1,200 lines for this file. 24 render methods averaging
   50 lines each makes 1,200. The only way to meet the 300-line target
   is to split ElementRenderer into per-kind files (e.g.,
   `renderers/text.py`, `renderers/table.py`). The plan does not propose
   this.

8. **`RenderContext.__slots__` + `__init__` to `__new__` + public attr
   rename interaction.** `RenderContext` declares `__slots__` with the
   public names (`"dt"`, `"frame"`, etc.). P.4 renames these to `_dt`,
   `_frame`, etc. P.5 converts `__init__` to `__new__`. The `__slots__`
   tuple must be updated to match the new private names. The plan does
   not mention this three-way dependency. If any of the three changes
   is done independently, the others break.

9. **`protocol/elements.py` classes_per_module.** This file will contain
   ~30 ClassDef nodes. The metric `classes_per_module` is averaged
   across all files. With 25 files, a single file at 30 contributes
   30/25 = 1.2 to the average. Combined with other files' contributions,
   the average should stay below 3. However, if the per-file threshold
   view is used for enforcement (the `--threshold` flag shows per-file
   FAIL), `elements.py` will show `classes_per_module = 30 FAIL`.

10. **Backward-compat wrappers contradict `PL-PP-1`.** The project rules
    in `.claude/rules/python-prohibited-patterns.md` state: "No
    backwards-compatibility shims. When code changes, callers change."
    The plan specifies backward-compat wrapper functions at every
    extraction step. This is a direct contradiction. The plan should
    either: (a) update all callers in the same PR (matching PL-PP-1), or
    (b) explicitly override PL-PP-1 for this refactoring with a stated
    rationale. Given the plan's "one extraction per PR" invariant,
    option (a) is the correct approach — move the code and update all
    callers in the same PR.

11. **Extraction order dependency: QueryDispatcher references
    SceneManager.** Step 2.4 (QueryDispatcher) takes a `SceneManager`
    instance in its constructor. If executed before Step 2.1
    (SceneManager extraction), QueryDispatcher would need to reference
    DisplayServer methods instead. The plan lists the steps as ordered
    within a phase, so this is safe *if the order is followed*. But the
    plan says "Steps across phases can sometimes be parallelized" — this
    intra-Phase-2 dependency should be made explicit.

12. **`config.py` has `class_to_func_ratio = 0.0` currently.** The
    existing `LuxConfig` is a dataclass, which `oo_score.py` counts as a
    class. The per-file score shows 0.0, which means the tool is NOT
    counting it. After adding `ConfigManager`, the file will have 1 real
    class + 1 dataclass + ~3 remaining wrapper functions. The ratio
    depends on whether the dataclass is counted. Based on the current
    score of 0.0 with 1 dataclass and 5 functions, the dataclass IS
    being counted (0 non-type classes / (0 + 5) = 0.0). Wait — the
    `_count_classes` method counts ALL non-Protocol/TypedDict classes
    including dataclasses. But config.py shows 0 classes in the per-file
    output. Let me re-examine: `LuxConfig` is `@dataclass(frozen=True)`.
    The `_is_type_definition` check only excludes Protocol and TypedDict.
    The `_count_classes` method should count it. Yet the per-file output
    shows `classes_per_module = 0`. This suggests `_count_classes` IS
    excluding dataclasses via some other mechanism, or the file has
    changed. In any case, this does not affect the plan's correctness.

## Recommendation

**REVISE.** The plan is well-structured and the extraction designs are sound.
The callback-based decoupling pattern is correct. The characterization-test-first
discipline is the right approach. But the plan has four gaps that will leave
metrics failing after full execution:

### Required revisions

**A. Decompose high-complexity functions (max_complexity).** Add explicit
sub-steps to decompose `_render_table` (CC=20), `_handle_message` (CC=14),
`_render_plot` (CC=13), `_render_paged_group` (CC=12), `_render_modal`
(CC=12), and `_flush_events` (CC=12) into smaller methods. Each of the 24
`_render_*` methods that exceeds CC=10 needs Extract Method applied until
every method is at or below 10. This can be done during the extraction steps
(2.3 for table, 2.5 for the rest) rather than as separate steps.

**B. Address `method_ratio` and `class_to_func_ratio` for `tools.py` and
`__main__.py`.** These two files have 54 combined top-level functions and
0-1 classes. Together they contribute ~0.0 to both ratio averages across 2
of 25 files. The plan needs a strategy — even if the strategy is "these
files are inherently function-based (MCP tool registrations, Typer commands)
and the metric will be addressed by adding enough class-based files to raise
the average." State the expected post-refactoring value and whether it
passes.

**C. Use `__new__` in all Phase 5 code examples.** The plan's code examples
for `ServiceManager`, `LaunchdBackend`, `SystemdBackend`, `SessionHub`,
`DoctorChecker`, `DisplayPaths`, `ConfigManager`, `ProxyConfigFile` all show
`__init__`. These must use `__new__` to avoid reintroducing `init_violations`.

**D. Reconcile backward-compat wrappers with `PL-PP-1`.** Either remove the
wrapper functions and update all callers in the same PR, or explicitly
override `PL-PP-1` for this refactoring with a deprecation timeline.

### Advisory (not blocking)

- Make the `RenderContext.__slots__` + P.4 + P.5 interaction explicit.
- Add round-trip tests for every message type before the `message_from_dict`
  registry replacement.
- Note that `module_size` will not reach 300 for `element_renderer.py` and
  state whether this is accepted as a known exception.
- Clarify the intra-Phase-2 ordering dependency (QueryDispatcher needs
  SceneManager to exist first).
- Require `from __future__ import annotations` as an explicit invariant for
  every new file.
