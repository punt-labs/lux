# Scene / Display Packaging and Naming Design

**Status:** delivered. Ratified by the operator 2026-08-08 (Q1-Q3, Q5 accepted
as recommended; Q4 overridden — the packaging move landed before `lux-ttey.3`
ruled on `SceneManager`'s fate, reversing this doc's own default
recommendation). Implemented as two units: Unit A (§5.1, bead `lux-i7y3`, PR
[#318](https://github.com/punt-labs/lux/pull/318)) and Unit B (§§5.2-5.4, bead
`lux-2gp3`, PR [#319](https://github.com/punt-labs/lux/pull/319)), both merged
2026-08-09. The target layout in §5 and the naming convention in §4 are now
the current architecture, not a proposal.

**Scope:** the `scene/` package, the `display/` package, the Display-adjacent
parts of `domain/`, and the Display-tier modules currently sitting loose at the
top of `src/punt_lux/`.

**Grounding:** [target.md](target/target.md) and
[topology.md](target/topology.md). Every placement below is justified by the
Hub/Display authority model those documents define, not by taste.

## 1. The problem, stated once

Two rounds of investigation in the same epic — the DomainPump/`Display`
confusion, and the `SceneManager` question — each spent real effort untangling
overlapping names before they could state their actual question. The overlap:

- `HubDisplay` (`domain/hub/`) — the Hub's authoritative store.
- `Display` (`domain/`) — a second store, test-only, being deleted.
- `DisplayServer` (`display/`) — the ImGui render loop.
- `SceneManager` (`scene/`) — the render loop's scene and frame bookkeeping.
- `MenuManager` (`display/`) — the render loop's menu bookkeeping.

Three of the five carry the word `Display` for three different meanings. Two
carry `Manager`, which names no job at all. And `SceneManager` sits in a
top-level package named for a domain noun, while the only thing that constructs
it sits in a package named for a tier.

The confusion is not that these names are ugly. It is that the directory
structure and the class names carry no information about which tier owns the
state, so the reader has to re-derive the tier from the code every time. That
re-derivation is what this design removes.

## 2. The organizing principle

target.md gives exactly one axis that matters here:

> The Hub wins every disagreement. The Display is a replica, not a second
> authority.

topology.md gives the operational form of it: the Display "holds a full copy of
the UI it is rendering. It does not own the real behavior of that UI," and the
Hub "may resend the whole UI" whenever it changes.

That yields a mechanical placement test, applicable to any module without
argument:

> **The reconstruction test.** If the Display process died right now and
> respawned, would this state come back because the Hub re-sent it? If yes, the
> state is a replica and the module is Display-tier. If the state would be lost
> because nothing else holds it, the module is Hub-tier — it *is* the
> authority.

Frames, the scenes inside them, the widget state keyed to those scenes, the
menu bar the Hub replicated: all reconstructed from a Hub re-send. All
Display-tier. `HubDisplay`'s element index, owner map, and scene presentations:
lost. Hub-tier.

A third category exists and must not be confused with either: the wire types in
`protocol/` are tier-neutral, because both tiers speak them. That is why
`protocol/` is a legitimate top-level package and `scene/` is not — `scene` is a
domain noun that exists on *both* tiers, so a package named for it gives no
home to anything.

## 3. Inventory

### 3.1 `scene/` — every module is Display-tier

| Module | Class | Role | Tier verdict |
|---|---|---|---|
| `scene/manager.py` | `SceneManager` | Routes a received `SceneMessage` into its frame; owns per-scene `WidgetState` and stale-id notification | Display replica |
| `scene/frame.py` | `Frame` | One inner window: title, scenes, tab order, minimized flag, placement | Display replica |
| `scene/frame_book.py` | `FrameBook` | The frame collection plus the scene→frame and scene→owner maps and cascade placement | Display replica |
| `scene/widget_state.py` | `WidgetState` | Per-scene key/value slots for in-flight widget arbitration across ImGui frames | Display replica |
| `scene/element_walk.py` | `SceneTreeWalk`, `ListSlot`, `AbcNode`, `ElementLocation` | Element-tree navigation over a replicated scene: locate, collect ids, detach | Display replica |
| `scene/rgba_buffer.py` | `RgbaBuffer` | The color picker's `WidgetState` value accessor for `ContinuousEditArbiter` | Display rendering |

Confirmation by import graph, not by reading: every production importer of
`punt_lux.scene` is under `display/`, or is one of the two top-level modules in
§3.3 whose only importer is `display/server.py`. Nothing in `domain/`,
`domain/hub/`, `operations/`, `rest/`, or `tools/` imports `scene/` at all.
`scene/` is a Display-tier package wearing a top-level, tier-neutral name.

### 3.2 `display/` — the render loop and its collaborators

| Module | Class | Role |
|---|---|---|
| `display/server.py` | `DisplayServer` | The render loop and socket coordinator; owns everything below (1,082 lines — over the 300-line target) |
| `display/menu_manager.py` | `MenuManager` | Holds the menu state the Hub replicated, composes it with the display's own menus, hands one model to both surfaces |
| `display/menus/` | `MenuModel`, `MenuBar`, `WorldPanel`, `OwnMenus`, `WireMenu`, … | The menu model and its two rendered projections |
| `display/renderers/` | one adapter per element kind | Turn replicated elements into ImGui calls |
| `display/texture_cache.py` | `TextureCache` | Image texture upload |
| `display/geometry.py`, `geometry_capture.py` | painted-rect capture | Geometry introspection |
| `display/frame_commands.py`, `frame_placement.py`, `frame_tiling.py` | frame window operations | Frame chrome |
| `display/dock_bar.py`, `dock_pill.py`, `window_chrome.py`, `idle_screen.py` | display chrome | |
| `display/evictions.py`, `evicted_compensation.py` | eviction bookkeeping | |
| `display/interaction_delivery.py`, `pending_interactions.py` | outbound interaction routing to the Hub | |
| `display/auto_click.py`, `paint_clock.py`, `glfw_window.py`, `glfw_loader.py`, `macos.py`, `markdown_font.py` | render-loop mechanics | |

This package is internally coherent. Its problem is not what it contains but
what it is missing: the six `scene/` modules and the five top-level modules
below.

### 3.3 Display-tier modules loose at the top of `src/punt_lux/`

| Module | Class | Only production importer | Tier verdict |
|---|---|---|---|
| `query_dispatcher.py` | `QueryDispatcher` | `display/server.py` | Display |
| `scene_inspector.py` | `SceneInspector` | `display/server.py` | Display |
| `scene_inspection.py` | `SceneInspection` | `scene_inspector.py` | Display |
| `socket_server.py` | `SocketServer` | `display/server.py`, `display/interaction_delivery.py` | Display |
| `types.py` | `OnSceneReplacedFn` and two unused aliases | `scene/manager.py` | Display |

These are the same accretion in a different form: Display-tier modules parked at
the package root, where the root reads as "shared by everything."

### 3.4 Display-adjacent `domain/`

| Module | Class | Status |
|---|---|---|
| `domain/hub/hub_display.py` | `HubDisplay` | The Hub-authoritative store. target.md names it. Stays. |
| `domain/hub/scene_writer.py`, `scene_presentation.py`, `scene_snapshot.py` | Hub-side scene write/read | Stay. Note they prove `scene` is a two-tier noun. |
| `domain/hub/replicator.py`, `display_workers.py` | The Hub→Display replication leg | Stay in `domain/hub/` — this is the Hub's outbound side, not the Display. |
| `domain/display.py` | `Display` | **Being deleted** by a separate in-flight mission. Treated below as already gone. |
| `display_client.py` (top level) | `DisplayClient` | The **Hub's** socket client of the display; constructed only in `domain/hub/clients.py`. Misfiled and misleadingly named — see §5.4. |

Layering is currently clean in the one direction that matters and has one
wrinkle in the other: nothing under `domain/` imports `punt_lux.display.*`, and
nothing under `display/` imports `domain.hub.*` — except
`display/server.py`, which reaches into `punt_lux.display_client` for a
`no_op_emit` helper. That is a Display-tier module importing a Hub-tier module
for a two-line default. §5.4 removes it.

## 4. The naming convention

Three clauses. They are meant to be short enough to remember and mechanical
enough to apply without a discussion.

### N1 — The package names the tier; nothing else does

Every module lives in the package of the tier that owns its state, decided by
the reconstruction test in §2:

| Package | Tier | Contains |
|---|---|---|
| `domain/hub/` | Hub | Authoritative state, ownership, handler dispatch, the replication leg |
| `domain/` (non-hub) | tier-neutral domain | Element ABC, events, validation — the vocabulary both tiers share |
| `display/` | Display | The render loop, the replica it renders, input capture |
| `protocol/` | wire | Element and message types both tiers speak |
| `operations/`, `rest/`, `tools/`, `__main__.py` | client surfaces | Thin adapters over the engine |

Corollary, and the specific rule `scene/` breaks: **no top-level package is
named for a domain noun.** A domain noun — scene, frame, element, menu — exists
on both tiers, so a package named for one tells the reader nothing about who
owns what is inside it. Domain nouns name *modules and classes inside* a tier
package, where the tier is already established by the path.

### N2 — A class names its job, never its tier

A class in `display/` never needs `Display` in its name; a class in
`domain/hub/` never needs `Hub`. The path already said it. When both a package
and a class carry the tier, the reader learns nothing from the second one and,
worse, starts to believe the two are different things — which is precisely how
`Display`, `HubDisplay`, and `DisplayServer` came to mean three things.

One grandfathered exception, and only one: `HubDisplay`. target.md and
topology.md name it, it is the term the whole architecture discussion uses, and
it is the one place where `Display` means "the UI being displayed" rather than
the process tier. See open question Q1.

### N3 — No `*Manager`, no `*Handler`, no bare `*Server`

These suffixes name "a thing that does things with X." They are the names a
class gets when nobody decided what it is, which is exactly the accretion this
design exists to stop. Name the thing instead. The good names already in the
tree are the model: `FrameBook`, `TextureCache`, `PaintClock`, `ElementIndex`,
`OwnerTracker`, `RootRegistry`. Each says what it *is*.

For Display-tier state specifically, prefer a name that says it is a replica —
`SceneReplica`, `MenuReplica`. The whole point of the tier model is that the
Display is not authoritative, and a name that says so removes the question
before it is asked.

## 5. Target layout

### 5.1 `scene/` is dissolved into `display/replica/`

`scene/` ceases to exist as a package. Its contents move into a new
`display/replica/` subpackage, which holds exactly the state the Display keeps
because the Hub sent it.

| From | To | Class rename |
|---|---|---|
| `scene/manager.py` | `display/replica/scene_replica.py` | `SceneManager` → `SceneReplica` |
| `scene/frame.py` | `display/replica/frame.py` | — |
| `scene/frame_book.py` | `display/replica/frame_book.py` | — |
| `scene/widget_state.py` | `display/replica/widget_state.py` | — |
| `scene/element_walk.py` | `display/replica/element_walk.py` | — |
| `scene/rgba_buffer.py` | `display/renderers/rgba_buffer.py` | — |
| `display/menu_manager.py` | `display/replica/menu_replica.py` | `MenuManager` → `MenuReplica` |

Justification, per module and per target.md:

- The five scene modules pass the reconstruction test — every frame, scene,
  and widget slot they hold is re-derivable from a Hub re-send, which is the
  Display's defined relationship to its content ("the Display replaces its
  previous copy", target.md §Replication Policy). They are replica state, and
  the package now says so.
- `MenuManager` moves for the same reason and its own docstring says why: it
  "holds the menu state the Hub replicates." Grouping it with the scene replica
  puts every piece of Hub-originated Display state in one place, and leaves
  `display/menus/` as what it actually is — the model and its two rendered
  projections.
- `RgbaBuffer` moves the other way, to `display/renderers/`, because it is not
  replica state: it is a renderer's accessor for a `WidgetState` slot, and its
  siblings for text and float already live under `display/renderers/imgui/`.

The result is that `display/` has three internal layers the reader can see from
the directory listing alone: `replica/` (what the Hub sent), `renderers/` (how
it is painted), `menus/` (the menu model and its surfaces), with the render
loop and its mechanics at the package root.

### 5.2 The loose top-level Display modules move in

| From | To | Class rename |
|---|---|---|
| `query_dispatcher.py` | `display/query_dispatcher.py` | `QueryDispatcher` → `QueryRouter` (N3) |
| `scene_inspector.py` | `display/scene_inspector.py` | — |
| `scene_inspection.py` | `display/scene_inspection.py` | — |
| `socket_server.py` | `display/socket_server.py` | `SocketServer` → `SocketListener` (N3) |
| `types.py` → `OnSceneReplacedFn` | `display/replica/scene_replica.py` | — |

`types.py`'s other two aliases, `EmitEventFn` and `OnClientDisconnectedFn`, have
zero importers anywhere in `src/` and are deleted with the module.

### 5.3 `DisplayServer` is renamed

| From | To | Class rename |
|---|---|---|
| `display/server.py` | `display/render_loop.py` | `DisplayServer` → `RenderLoop` |

By N2 the class is in `display/` already, so `Display` in the name adds nothing;
by N3 `Server` names no job. `RenderLoop` is what the class is and what its own
docstring already calls it. This is a rename and a file move only — the
1,082-line decomposition this module still owes is a separate, larger piece of
work and is not folded in here. See open question Q3.

### 5.4 `display_client.py` moves to the Hub

`DisplayClient` is the Hub's socket client of the display process. It is
constructed only in `domain/hub/clients.py`. It is Hub-tier by the
reconstruction test and by topology.md's statement that the Hub "owns … the
connection to one or more Displays."

| From | To | Class rename |
|---|---|---|
| `display_client.py` | `domain/hub/display_link.py` | `DisplayClient` → `DisplayLink` |

The `no_op_emit` helper that `display/server.py` currently imports from it moves
to `display/replica/` as the Display-side default it actually is, which removes
the one Display→Hub import in the tree.

### 5.5 What does not change

Stated explicitly so an implementation mission does not go looking:

- `domain/hub/` keeps its name, its layout, and `HubDisplay` (subject to Q1).
  Its `scene_writer`, `scene_presentation`, and `scene_snapshot` modules stay
  where they are — they are the Hub's scene concern, and under N1 the path is
  what distinguishes them from `display/replica/scene_replica.py`.
- `protocol/`, `operations/`, `rest/`, `tools/`, `applets/`, `apps/` are
  untouched.
- `display/renderers/`, `display/menus/`, and every other `display/` module not
  named above keep their names and locations.
- No behavior changes anywhere. This is a move-and-rename design; every change
  is import rewiring plus symbol renames, and the test suite is the check.

## 6. Change summary for the implementation mission

Sized as roughly two rollback-coherent units. Each is mechanical, and `make
check` plus the existing suite is the verification.

**Unit A — dissolve `scene/`, form `display/replica/`.** Move the six `scene/`
modules per §5.1, move `MenuManager` in and rename it, move `RgbaBuffer` to
`display/renderers/`, fold `OnSceneReplacedFn` in and delete `types.py`, rename
`SceneManager` → `SceneReplica`, delete the `scene/` package. Roughly 60
importing files, most of them tests; `tests/` mirrors the source layout, so the
test files move with their subjects.

**Unit B — pull the loose Display modules in, rename the render loop, move the
Hub's display client out.** §§5.2–5.4.

Both units are ratchet-relevant: `SceneReplica` inherits `SceneManager`'s
238-line module and `RenderLoop` inherits an 1,082-line one, so the OO baseline
must be updated and staged with the commits, and the implementation mission
should take a real improvement in whichever module it is sitting in rather than
the minimum that clears the check.

Not in scope, but named so nobody has to rediscover them:

- `display/server.py` is 1,082 lines against a 300-line target. Renaming it does
  not fix that.
- `runtime.py` (`CodeExecutor`, `RenderContext`) has no production importer at
  all — only `tests/test_runtime.py`. That is an orphan module under PL-MD-5 and
  wants a bead, not a slot in this design.

## 7. Open questions — decisions needed before implementation

Each has a recommendation. None is buried in the prose above.

**Q1. Does `HubDisplay` keep its name?** Under N2 it should not — it is in
`domain/hub/`, so the `Hub` prefix is redundant, and `Display` there means the
UI rather than the tier, which is the very ambiguity this design attacks. A
consistent rename would be `UiStore` or `ElementStore` in
`domain/hub/ui_store.py`.

*Recommendation: keep `HubDisplay`, grandfathered, and say so in the rule.*
target.md and topology.md name it repeatedly; renaming it invalidates the
canonical architecture documents to buy consistency in a class that no longer
collides with anything once `domain/display.py` is gone and `DisplayServer`
becomes `RenderLoop`. The collision drops from three to one, and one is not a
collision.

**Q2. Is `display/replica/` the right shape, or should the six modules go flat
into `display/`?** Flat is fewer moving parts; a subpackage makes the replica
boundary visible in the directory listing and keeps `display/` from growing to
thirty-odd loose modules.

*Recommendation: the `display/replica/` subpackage.* The whole objective is
that the tier model is legible from the structure, and "here is everything the
Hub sent us" is the single most useful thing that structure can say.

**Q3. Is the `DisplayServer` → `RenderLoop` rename in this work, or does it wait
for the decomposition of that module?** Doing it now means touching a file that
is about to be split; waiting means the `Display`-named collision survives.

*Recommendation: rename now, decompose later.* The rename is a move plus a
symbol change and does not conflict with a later split — the split will produce
new modules beside `render_loop.py`, not edit its name again.

**Q4. What happens to `SceneManager` if `lux-ttey.3` retires it?** That question
explicitly waits on this design and is not re-litigated here.

*Recommendation: the packaging design is agnostic to it.* If the class
survives, it is `SceneReplica` in `display/replica/scene_replica.py`. If
`lux-ttey.3` folds its remaining behavior into `FrameBook`, then `FrameBook`
lives at the same path under the same rules and `scene_replica.py` never
appears. Either outcome satisfies §5.1; sequence Unit A after ttey.3's ruling to
avoid moving a file that is about to be deleted.

**Q5. `QueryDispatcher` → `QueryRouter` and `SocketServer` → `SocketListener`
are N3 consequences, not problems anyone reported.** They can be skipped without
weakening the tier model.

*Recommendation: do them.* Leaving two `*Dispatcher`/`*Server` names in the
tree immediately after writing N3 is how a rule stops being a rule. They are
cheap — two symbols, five importing files.
