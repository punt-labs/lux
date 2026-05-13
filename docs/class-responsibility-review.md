# Peer Review: Class Responsibility Report (v3)

Reviewer: Ralph Johnson (rej) -- Smalltalk specialist, co-author *Design
Patterns: Elements of Reusable Object-Oriented Software*.

## Overall Assessment

The v3 report is the most complete design document this project has
produced.  Every `.py` file in `src/punt_lux/` receives a design
decision: class, justified no-class, or existing-class-reviewed.  The
calibration against the merchants reference project (10K LOC / 5 classes
vs. 2K / 20 classes) makes the structural deficit visible before any
argument begins.  The v2 review's findings -- `_emit_event` recursion
bug, theme/chrome ownership, MessageRouter rejection, event flow
diagram, `_Frame` promotion, ImGui dependency map, extraction order --
are all incorporated.

Three qualities distinguish this report:

1. **Each proposed class cites state, invariant, and collaborations.**
   The test "state + behavior + invariant = class" is applied
   consistently.  The report does not confuse namespaces with objects.

2. **The no-class decisions are argued from principle.**  `hooks.py`
   justifies no-class from the process model (each invocation is a
   separate OS process).  `show.py` justifies no-class from the absence
   of state or shared logic.  Hub path functions are left as functions
   because they are stateless and pure.  This is the right discipline.

3. **The extraction order is designed for incremental correctness.**
   Pure state machines first, ImGui-coupled renderers last.  Each step
   leaves the system working and maximizes testability gain per step.

The report covers every module.  The new modules (service.py, hub.py,
paths.py, config.py, remote.py, beads.py, `__main__.py`) each receive
rigorous analysis with before/after code.  The v2-era modules
(display.py, protocol.py, tools.py, display_client.py) retain their
designs with peer review feedback incorporated.

**Verdict: GO, with modifications noted below.**

---

## Module-by-Module Review

### display.py

**AGREE with modifications.**

The eight-responsibility diagnosis is correct.  DisplayServer at 3,300
lines / 135 methods is the textbook God Object.  The six proposed
extractions (SocketServer, SceneManager, ElementRenderer, TableRenderer,
MenuManager, QueryDispatcher) each satisfy the class test.

**Modification 1: Name the Visitor pattern explicitly as a design
invariant.**  The report calls ElementRenderer "the Visitor pattern
applied to element kinds" -- good.  But the kind-string dispatch
(`_RENDERERS` dict) is the Visitor's `accept/visit` pair spelled in
Python.  When a new element kind is added, one method is added to
ElementRenderer and one entry to the registry.  This is the Open/Closed
Principle at work.  The report would be stronger for naming this
explicitly, because it justifies the class beyond "flat namespace with
shared dependencies."

**Modification 2: Promote the no-bidirectional-import rule to an
enforced invariant.**  The event flow diagram (section near end) shows
acyclic dependencies.  Good.  I would promote "No extracted class
imports DisplayServer; all upward communication is via Callable
parameters" to a numbered invariant.  Making it an invariant means
reviewers can check it mechanically during each extraction PR.  Better
yet, add an `import-linter` or `ruff` rule that forbids
`scene_manager.py` from importing `display`.

**Modification 3: The message routing decision (not a class) is
correct.**  A 40-line stateless dispatcher is a method, not a class.
The code example after extraction is the right size.  The pattern is
what Smalltalk calls a "message send coordinator" -- it reads the message
type and sends to the right collaborator.  No state, no invariant, no
class.

The TextureCache and WidgetState reviews are accurate.  Both are
well-scoped existing classes.  The `_Frame` -> `Frame` promotion is
right -- the underscore prefix signals module-private, which is wrong
when the class moves to `scene_manager.py`.

The v2 review noted that some query handlers need ImGui access
(`_query_get_display_info`, `_query_set_window_settings`).  These
handler *implementations* must stay on DisplayServer and be registered
as `Callable` handlers during QueryDispatcher construction.
QueryDispatcher owns the dispatch table and ring buffers; the handler
implementations for display-wide state live where that state lives.
The v3 report's design is compatible with this constraint but should
state it explicitly.

### protocol.py

**AGREE with the ElementCodec and MessageCodec proposals, with priority
caveat maintained.**

The diagnosis is accurate.  The 95-line `message_from_dict` if/elif
chain and the 120-line `_register_serializers` closure factory are
manual vtables.  The proposed `_register_message` pattern replaces both.

The `__init_subclass__` design for ElementCodec is structurally sound.
The report is honest that the gain is structural, not functional, and
that the line count is roughly the same.  This honesty is why priorities
9 and 10 are correct.  Do display.py first.

One observation the report does not make: the 24 element dataclasses
are Value Objects.  They have identity (the `id` field) but are
otherwise immutable snapshots.  Serialization belongs on the codec, not
on the value object.  The rejected alternative (instance methods without
a registry) is correctly rejected -- deserialization requires dispatch
on the `kind` string before a class instance exists.

The FrameReader review is correct.  Well-scoped, no changes needed.

### tools.py

**AGREE.**

The query decorator eliminates 150 lines of identical boilerplate across
15 tools.  The before/after examples are convincing.  The concrete
decorator design is clean.

The ToolState class is correctly flagged as optional and lower priority
than the decorator.  The five module-level variables are a class waiting
to be born, but the decorator is higher value per effort.

**Carry-forward from v2 review:** verify FastMCP compatibility
empirically.  The decorated function's return type (`dict | None`) vs.
the wrapper's actual return type (`str`) could affect tool schema
generation.  Call `mcp.list_tools()` after applying the decorator to one
tool and check the schema.  If the return annotation matters, override
`wrapper.__annotations__["return"]`.

One naming observation: `_with_reconnect` is a Proxy pattern variant --
it intercepts a call, detects failure, repairs the connection, and
retries.  Naming it helps the team recognize the pattern elsewhere.

### display_client.py

**AGREE.**

The migration proposal (three legacy methods -> `query()` wrappers,
three queues removed) is correct.  The legacy methods should become
deprecated wrappers, not deleted immediately, because `inspect_scene`
is part of the public API and called by tools.py.

The `_dispatch_or_buffer` simplification (removing three `isinstance`
checks) and `close()` cleanup (dropping three `_drain_queue` calls)
follow automatically.

Priority 8 is correct -- independent of the display.py decomposition.

### `__main__.py`

**AGREE.**

The three proposals are all correct:

1. **DoctorChecker** satisfies the class test: it accumulates
   CheckResult state across check methods and provides aggregate
   properties (passed, failed).  The current closure-based `_check`
   callback is the ad-hoc version of what the class makes explicit.
   Before/after: 65 lines -> 7 lines in the command body.

2. **Hub restart move to service.py** is correct.  `_restart_hub` is
   daemon lifecycle management (SIGTERM, wait for death, wait for
   respawn).  That is exactly what service.py owns.

3. **Typer sub-app** (`lux hub install` instead of `lux hub-install`)
   follows Typer's design patterns.  The hook commands already use this
   pattern (hook_app), show commands use it (show_app), and now hub
   commands join (hub_app).  Three examples make it a pattern.

The report's observation that `__main__.py` is a wiring coordinator
(the Facade pattern, same role as `Game.__new__` in merchants) is
correct.  The report is right to reject a CLIApp class wrapper -- Typer's
`app` instance is the state.

### service.py

**AGREE.**

The Strategy pattern diagnosis is textbook.  The parallel function sets
(`_launchd_install` / `_systemd_install`, etc.) operating on the same
state with the same interface, dispatched via `if plat == "macos"`, is
the defining symptom.

ServiceBackend ABC + LaunchdBackend + SystemdBackend is the right
decomposition.  ServiceManager as the context that resolves and
delegates is also right.

**One strengthening observation:** the report says "makes adding a third
platform (FreeBSD, container) a single new class."  This is the
Open/Closed Principle.  The current code requires modifying `install`
and `uninstall` to add an `elif` for each new platform.  The Strategy
version requires adding a new class and a new branch in
`_resolve_backend`.  The new platform's logic is self-contained -- you
cannot accidentally break macOS when adding FreeBSD.

The backward-compatible module-level wrappers are the right transition
strategy.

### hub.py

**AGREE.**

`_active_sessions` as module-level mutable state shared between two
route handlers is the textbook "class waiting to be born."  SessionHub
encapsulates this correctly.

The three arguments (test fragility, extensibility, ownership hint from
`build_app`) are sound.  Priority 13 reflects the small absolute size
correctly.

### paths.py

**AGREE with both the class and no-class decisions.**

DisplayPaths satisfies the class test: the socket path is the identity,
and six of eight functions take it as a parameter.  Parameter threading
is the classic signal.

Hub path functions as no-class is correct.  Stateless pure functions
derived from constants.  The module is the namespace.

**One observation:** DisplayPaths is an instance of the Parameter Object
pattern.  The socket path is threaded through six functions; making it a
constructor argument is exactly what Parameter Object describes.  Naming
it helps the team recognize the same pattern in config.py.

### config.py

**AGREE.**

ConfigManager encapsulates the config file path (resolved once) and
provides typed read/write access.  LuxConfig as a frozen dataclass is a
Value Object -- no behavior to add.

Priority 15 is appropriate.  The config has one field.  The class adds
testability but the functional benefit is small until there are more
config fields.

### hooks.py

**AGREE -- no class.**

The justification is sound on two levels:

1. **Process model:** each hook invocation is a separate OS process.
   No in-process state survives across invocations.

2. **Function structure:** each handler takes input as a parameter and
   returns or emits output.  No shared mutable state.

A `HookDispatcher` class would have a constructor that takes no
arguments and methods that reference no instance state.  The module is
the namespace.  Correct decision, rigorous reasoning.

### remote.py

**AGREE.**

ProxyConfigFile encapsulates the file path and atomic write mechanics.
The testability gain (construct with a temp path instead of
monkeypatching a module constant) is real.

**On the size concern:** class decisions are about state and invariant,
not line count.  The file path is the state.  The atomic write is the
invariant.  85 lines is fine.

### apps/beads.py

**AGREE.**

BeadsBrowser encapsulates a pipeline: load -> build_payload ->
build_elements -> render.  The pipeline operates on shared constants
that are configuration of the browser, not universal constants.

The report correctly identifies that the class has no persistent state.
The value comes from making the application object explicit and
providing a single point for future configuration.

The backward-compatible wrappers are the right transition pattern.

### runtime.py

**AGREE -- both existing classes are correct.**

RenderContext is a per-frame context with `__slots__`.  CodeExecutor
compiles user code with error isolation.  `hot_reload` preserves state
across source changes -- the Factory Method pattern.  Well-scoped, no
changes needed.

### show.py

**AGREE -- no class.**

One Typer command delegating to `beads.py` and `DisplayClient`.  The
analysis of why `render_beads_board` and the `beads` CLI command are
separate (library vs. CLI callers) is correct.

### `__init__.py`

**AGREE -- not applicable.**

Package export surface.  No behavior, no state.  After module splits,
imports must be updated, but the structure is correct.

---

## Extraction Order

**AGREE with the proposed 1-17 ordering.**

The ordering follows three correct principles:

1. **Pure state machines first** (SceneManager, SocketServer,
   QueryDispatcher) -- zero ImGui dependency, highest testability gain.

2. **ImGui-coupled components second** (ElementRenderer, MenuManager)
   -- require GPU context or mock for testing.

3. **Independent refactors in parallel** (tools.py query decorator,
   DisplayClient migration) -- do not depend on display.py
   decomposition.

After extractions 1-6, DisplayServer shrinks from 3,300 lines / 135
methods to ~600 lines / 20 methods.

**Refinement: add a verification gate.**  After extraction 4
(QueryDispatcher), run the existing test suite and verify everything
passes before proceeding to the ImGui-coupled extractions (5-6).  The
pure extractions (1-4) are where mistakes are cheapest to fix.

**Carry-forward from v2:** extracting QueryDispatcher (currently 4)
before TableRenderer (currently 3) would mean all fully-pure classes are
done before tackling the partially-pure TableRenderer (whose filter
logic is pure but rendering logic needs ImGui).  Either order works;
this is a judgment call.

---

## Missing Items

1. **No test strategy is specified.**  The report identifies which
   classes are testable without ImGui (the ImGui dependency table is
   excellent), but does not say which tests to write first.
   Recommendation: write characterization tests for SceneManager
   *before* extracting it.  Test the current DisplayServer methods that
   will move to SceneManager.  This establishes the contract.  Then the
   extraction is a mechanical move with coverage already in place.

2. **ContextVar subtlety in ToolState.**  The report mentions
   `_session_key: ContextVar` as state that moves into ToolState.
   ContextVar is tied to asyncio task context.  Moving it into a class
   instance requires care -- the ContextVar must remain at module scope
   or be accessed via the class, not stored as instance state.  This is
   a subtle point that could cause a bug.

3. **Carry-forward: utility function placement.**  The v2 review flagged
   color helpers (`_parse_color`, `_color_to_hex`, `_to_imgui_color`,
   `_widget_value`) and tree-walking utilities (`_collect_ids`,
   `_find_element`, `_get_children`) as needing explicit placement after
   extraction.  The v3 report does not address this.  Color helpers go
   with ElementRenderer; tree-walking utilities go with SceneManager.
   Call this out in the extraction PRs.

4. **Carry-forward: `_auto_click_buttons` disposition.**  The v2 review
   flagged this 90-line test-mode method.  It stays on DisplayServer
   gated by `_test_auto_click`, or moves to a test helper module.

5. **Carry-forward: `_emit_event` recursion bug.**  The v2 review
   identified an infinite recursion at line 2024.  This must be fixed
   before or during the first extraction, because every extracted class
   that emits events depends on this method.

6. **Callback type aliases.**  Several extractions introduce callback
   signatures (`on_client_disconnected`, `on_scene_replaced`,
   `emit_event`).  Define these as `TypeAlias` in a shared location
   (protocol.py or a new `types.py`) so both sides of each extraction
   agree on the contract.

---

## Risks

1. **Circular dependency during extraction.**  The report's constraint
   ("No extracted class imports DisplayServer") is correct.  Enforce it
   with an `import-linter` rule or a CI check.

2. **WidgetState ownership during scene switches.**  DisplayServer must
   set `element_renderer.widget_state` to the correct per-scene
   WidgetState before each render pass.  The existing code does this
   swap in `_render_scene_tab` and `_render_framed_scene`.  Both paths
   must be preserved.  If two extractions (SceneManager and
   ElementRenderer) land simultaneously, the handoff must be
   coordinated.  The extraction order (SceneManager first,
   ElementRenderer fifth) addresses this implicitly, but call out the
   handoff as a known coupling point.

3. **Large diff, working system.**  The system works today.  A
   refactoring this size touches every method in a 4,200-line module.
   Mitigation: one class per PR, each PR leaves tests green and the
   display server functional.  Do not batch extractions.

4. **Backward compatibility of module-level wrappers.**  Several
   proposals (service.py, config.py, beads.py) keep module-level
   functions as wrappers around class instances.  The wrappers should be
   deprecated with `warnings.warn` in the extraction PR and removed in a
   subsequent release.

5. **FastMCP decorator interaction.**  The `_query_tool` decorator's
   return type annotation must be verified empirically.  See the
   tools.py section above.

---

## Recommendation

**GO.**

The report is complete, rigorous, and ready to guide implementation.
Every module has a design decision.  The proposed classes satisfy the
state + behavior + invariant test.  The no-class decisions are argued
from principle.  The extraction order is correct for incremental safety.

The modifications I recommend:

- Name the Visitor and Open/Closed patterns explicitly in
  ElementRenderer and ServiceBackend.
- Promote "no extracted class imports DisplayServer" to an enforced
  invariant with a CI check.
- Write characterization tests for SceneManager before extracting it.
- Define callback type aliases in a shared location.
- Fix the `_emit_event` recursion bug before starting extraction.
- Assign explicit placement for color helpers and tree-walking utilities
  in the extraction PRs.

None of these change the fundamental design.  They reduce risk during
implementation.

The merchants reference project maps well: `Game` as Facade maps to
DisplayServer after extraction; `RoundController` as lifecycle manager
maps to SceneManager as state machine; `Captain` as domain object with
Strategy maps to ServiceBackend/LaunchdBackend/SystemdBackend.  The
patterns are the same; the domain is bigger.  That is the right
relationship.
