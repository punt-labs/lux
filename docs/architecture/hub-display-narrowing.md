# HubDisplay and the Client Door: Design

**Status:** design, amended twice: after the leader's review of `842d4e5d`, and
after the first implementation attempt was measured against the ratchets (§4.7,
§4.8, §5, §6 are the second amendment). For the leader's final review. No code is
written by this document; the implementation write-set is §9.
**Bead:** `lux-ghhf`. Mission `m-2026-10-22-021`; worker `gvr`, evaluator `rmh`.
**Scope (leader ruling, 2026-10-22):** the *client door* only — how a connection
becomes, stays and stops being a Hub client, and who may ask. Narrowing
`HubDisplay`'s scene reads, frame, writer and quarantine forwards is the Hub
store's existing wide-facade debt on `main`. It is a separate unit.
**Baseline (leader ruling):** the tree after `git revert 81bfb8a5`, which returns
the scene side and the tests to their pre-`HubParts` shape in one commit. Every
count and metric below is taken at `81bfb8a5^`, the parent of the reverted commit.
**Companion models, unchanged by this design:** `docs/menu_presence.tex`,
`docs/menu_presence_locks.tex`, `docs/connection_lease_reaping.tex`.

I read `DESIGN.md` DES-055, 057, 058, 064, 093, 094, 095, 096, 097 and 098 in
full and DES-067's problem and decision, both menu-presence models,
`lease-reap-cascade.md`, and every module named in the contract. Counts and
metrics are measured from the tree, not quoted (§2, §6).

## Brief

**What this changes.** Today every client-door caller reaches the door through
`HubDisplay`: `display.lifecycle.renew(...)`, `display.clients.session_of(...)`,
`display.renew_contact(...)`, `display.register_client(...)` and seven more
members. After this change a caller is constructed with the cohesive class it
uses — `ClientLifecycle` for door *writes*, `HubClientRegistry` for door *reads* —
and `HubDisplay` has no door member at all. A small builder, `HubStoreFactory`,
makes the shared lock and ownership map, the door, and the store over them, once.

**How it leaves the system better.**

- *Coupling.* `HubDisplay` stops importing the client lifecycle, the departure
  cascade, the client registry and the `Hub` (efferent 27 → 21, measured on a prototype; six imports, because
  `OwnerTracker` and `StoreLock` become annotation-only), and
  stops being the way fourteen source files reach a lifecycle they never asked a
  store about.
- *Cohesion.* The step the menu-presence model proved — registry write, ownership
  release, mark, sink, under one store lock — is reached through one object, so
  "no caller is trusted to remember" is true of the call graph, not only of the
  class. `HubDisplay` keeps what is store coordination (§4.3).
- *Module boundaries.* The seam between the scene store and the client registry is
  two constructor arguments, not a shared object graph.

**Approach chosen.** Each caller takes the concrete class it uses. A `Protocol`
is added only where a real dependency direction needs one, and none does (§4.2).
Construction leaves `HubDisplay.__new__` for `HubStoreFactory`. Process
singletons are exported by name from one module.

**Rejected** (§7): the `HubParts` bundle; the `StoreLookups` grab-bag; forwarding
methods on `HubDisplay`; a `ClientDoor` record handed to callers; eleven
single-method `Protocol`s; late binding.

**Rulings applied** (§8): `SceneQuarantine` is not extracted in this unit
(Q-C); `client_sessions` and `client_repos` leave with the door; the lifecycle
owns its compound critical section (`exclusive()`); a small builder is fine and
the confinement guard test is dropped.

## 1. What the door is, and what is not in this unit

The client door is nine operations on a connection's registration, and the reads
of the roster:

| Kind | Operation | Home at the baseline |
|---|---|---|
| write | arrive, identify, attach, renew, arm, bind_sink, depart, depart_lapsed, present_as | `ClientLifecycle` (`client_lifecycle.py`) |
| read | session_of, identity_of, named_sessions, live_sessions, repos, `legs` | `HubClientRegistry` (`hub_clients.py`) |
| read | client_sessions | `HubReads`, a pure pass-through to `live_sessions` |

`HubDisplay` fronts all of it today with eleven members: `register_client`,
`identify_client`, `is_client`, `renew_contact`, `bind_departure_sink`,
`drop_connection`, `reap_lapsed_leases`, the `lifecycle` and `clients`
properties, `client_sessions` and `client_repos`. All eleven go.

**Not in this unit, and unchanged.** `reader`, `frames`, `dismissal`,
`write_seam`, `scene_roots`, `resolve`, `owner_of`, `elements_owned_by`,
`element_count`, `scene_owners`, `live_scene_ids`, `all_scene_ids`, the four
quarantine members with their inline `QuarantineRegistry`, `replace_scene`,
`show_scene`, `apply`, `write_lock`. Their callers keep calling `display.X(...)`.

## 2. Facts on the ground

By grep at `81bfb8a5^`. A receiver-restricted pattern, so these are lower bounds
for the tests.

| | Source | Tests |
|---|---|---|
| Door call sites | 28 sites, 14 files | 272 sites, 44 files |
| `HubDisplay(` constructions | 1 (the singleton) | 326 in 50 files (re-counted at HEAD; the first draft said 273 in 40) |
| Consumer constructions in tests that may change signature | n/a | at most 162 sites, 39 files |

So the door slice is about 300 call sites, not 700. The 326 constructions matter
more than the 272 door sites: the constructor signature changes (§4.3), so every
test that builds a store is touched once, mechanically.

Source files with door sites: `operations/scenes.py`, `pubsub.py`, `identity.py`,
`callbacks.py`, `menu_arming.py`, `menu_arming_deps.py`, `frame_owner_facts.py`,
`client_details_port.py`, `client_listing.py`, `ws_listen.py`,
`domain/hub/inbox.py`, `lifecycle.py`, `scene_writer.py`,
`replicator_instance.py`; the sweep is wired in `luxd.py`.

`HubDisplay.apply` is the only *store* code that touches the door
(`renew`, `depart_lapsed(exclude)`, `session_of`).

Two narrow ports already exist and are used the way this design wants:
`LiveSessions` (`callback_ports.py`, taken by `CallbackRouter`,
`MenuEventRouter` and `HubMenuRegistry`) and `LeaseReaper`
(`lease_reap_sweep.py`, taken by `LeaseReapSweep`). They stay where they are.

## 3. ADRs and models that bound this work

| Entry | What it fixes | Here |
|---|---|---|
| DES-055 One Code Path | Every surface is a thin adapter over one operation; `Operations.for_store` wires "every collaborator injected — no singletons". | **Builds on.** `for_store` takes the lifecycle and registry as arguments and still reaches no singleton. |
| DES-057 Client Identity | One identity for both legs; leases; `identify` is how identity is recorded. | **Builds on.** `ClientLifecycle.identify` stays the one recording path for REST and the listen leg. |
| DES-058 / 064 / 067 | The Clients menu is the live roster; an entry exists exactly while its registrant holds a lease; grouping by (repo, session). | **Builds on.** Presence stays lease-filtered and changes only inside `ClientLifecycle`. |
| DES-093 Display Linkage | The Hub never controls the display process. | Not touched. |
| DES-094 Liveness is a heuristic | Leases reap a dead connection; reaping is not a trust boundary. | **Builds on.** The sweep still calls `depart_lapsed`. |
| DES-095 Facade, not weaker gates | Reconcile the ratchets with a facade or mediator; never weaken a gate. | **Builds on.** `HubStoreFactory` is the mediator that keeps `HubDisplay`'s fan-out honest. |
| DES-096 / 097 Bounded bless | A within-cap, first-edge, tool-computed bless; over-cap and regressing is refused. | **Builds on, and binds** (§6, §8): LCOM above the 0.5 cap is not blessable. |
| DES-098 Unified menu dispatch | One shared `MenuDepartureSink`; `set_menu` holds the store lock across admit and store (the one edge store lock → `HubMenuRegistry._lock`). | **Builds on, and keeps** the edge (§4.5). |
| `menu_presence.tex` | Every change to who the Clients menu lists marks the menus and leaves exactly one sink bound, in one step under the store lock; the registry never fires a hook. | **Keeps all of it** (§4.5). |
| `menu_presence_locks.tex` | Store lock, then registry lock; one edge; no cycle. | **Keeps** (§4.5). |
| `connection_lease_reaping.tex` I5, I6 | Departure and ownership release are one event; a live writer is never reaped by its own or another's write. | **Keeps.** `apply`'s prologue is unchanged. |

**Supersedes:** no ADR. It replaces the *shape* of door access on `HubDisplay`
(pass-through members and the `lifecycle`/`clients` properties). §10 drafts
DES-101 to record that. DES-099 and DES-100 touch the Clients menu's *content* and
are unaffected.

## 4. Design

### 4.1 Who owns what

| Object | Owns | Locks |
|---|---|---|
| `ClientLifecycle` | Every transition of a connection's registration, one step each: registry write, ownership release, cascade tail, and the presence debt (mark and sink). | Store write lock, then registry lock. |
| `HubClientRegistry` | The sessions, their leases, the roster names, the listen legs. State only: it never calls out of its own lock. | Registry lock. |
| `HubStoreFactory` (new) | Building the shared `StoreLock` and `OwnerTracker`, the registry, the cascade, the lifecycle, and the `HubDisplay` over them. | n/a |
| `HubDisplay` | Store coordination (§4.3). **No client member.** | Store lock. |

`MenuPresence` stays a private detail of `ClientLifecycle`; no consumer sees it.

### 4.2 What each caller takes

A caller takes the concrete, cohesive class it uses. `ClientLifecycle` and
`HubClientRegistry` are each one concept with one reason to change; handing a
consumer the class is not a wide dependency. A consumer takes the door **only
when it does door work** (a transition of a connection's registration); a write
to the scene store is contact by the store's own rule (§4.7), so scene writers
take the store alone.

| Consumer | Takes | Uses |
|---|---|---|
| `SceneOperations` (via `SceneOperationsDeps`) | `HubDisplay` only | `arriving_as` (in `install`), `write_lock` (§4.9) |
| `SceneClearer`, `HubSceneWriter` | `HubDisplay` only | `writing_as` (store) |
| `PubSubOperations` | `ClientLifecycle` | `renew` |
| `CallbackOperations` | `ClientLifecycle`, `ListenerLegs` | `renew`; `listener_for`, `register_callback` |
| the `Clients` menu read (`MenuOperationsDeps.callback_menus`) | `CallbackMenuReplica` (over `HubClientRegistry`) | `callback_menus` |
| `IdentityOperations` | `ClientLifecycle`, `HubClientRegistry` | `identify`; `identity_of` |
| `MenuArming` (via `MenuArmingDeps`) | `ClientLifecycle`, `HubClientRegistry` | `renew`, `arm`; `identity_of` |
| `MenuOperationsDeps.write_lock` | `display.write_lock`, unchanged (F6) | the store lock |
| `HubListenSession`, `HubListenTransport` | `ClientLifecycle`, `ListenerLegs` | `attach`, `identify`, `exclusive`; `detach` |
| `inbox.ensure_writer` | module name `hub_lifecycle` | `exclusive`, `arrive`, `bind_sink` |
| `lifecycle.disconnect_connection` | `ClientLifecycle`, default `hub_lifecycle` | `depart` |
| `LeaseReapSweep` (luxd) | `LeaseReaper` (exists) ← `hub_lifecycle` | `depart_lapsed(frozenset())` (F1) |
| `HubMenuRegistry`, `CallbackRouter`, `MenuEventRouter` | `LiveSessions` (exists) ← `hub_clients` | `live_sessions` |
| `CallbackMenuReplica` | `HubClientRegistry` | `named_sessions` |
| `ClientListing` | `HubDisplay`, `HubClientRegistry` | `live_sessions`, `named_sessions`; `elements_owned_by` |
| `FrameOwnerFacts`, `ClientDetailsOperations` | `ClientListing` (no registry) | `named`, `facts` (§4.8) |
| `HubDisplay.apply`, `writing_as` | `ClientLifecycle`, `HubClientRegistry` | `renew`, `depart_lapsed`; `session_of` |

`ListenerLegs` is the registry's listener-slot view, already a single-purpose
class. It is taken as itself, built by `clients.legs`, so no caller reaches through
the registry to it.

`IdentityOperations.current` asks `session_of` for a whole session and extracts
`.identity` today; it will ask `identity_of`. Same answer (`identity_of` is
`sessions.get(c, ANONYMOUS).identity`, one atomic dict read). It is the one place
this design changes a call rather than the object a call is made on.

**Does `HubDisplay.apply` need a `Protocol` to avoid a cycle? No.** `hub_display.py`
already imports `ClientLifecycle` and `HubClientRegistry` at runtime at the
baseline. I checked the import closure: `client_lifecycle.py` reaches three
modules (itself, `menu_presence`, `null_dirty_marker`) and `hub_clients.py`
reaches seventeen, and neither closure contains `hub_display` or the
`punt_lux.domain.hub` package initialiser. The door depends on the lock and the
ownership map, not on the store. A `Protocol` there would be a type with nothing
to invert.

**The rule.** A new `Protocol` exists only where a real dependency direction
requires one — a lower layer that must not name the concrete class above it, or a
cycle. Neither occurs in the door: every consumer is in `domain/hub`, `operations/`
or a presentation module, all of which may import `domain/hub`. A fake that is one
method shorter is not a reason.

**One addition to the provider.** `ClientLifecycle.exclusive()` returns the store
lock's write context, the same reentrant `StoreLock` every lifecycle method
already takes. `ws_listen` and `inbox.ensure_writer` each hold the store lock
across a door step plus a Hub writer or inbox step so a departure cannot
interleave, and after this change neither holds a `HubDisplay`; they take the lock
from the door they already depend on. Menu arming does not need it, and
`MenuOperationsDeps.write_lock` stays `display.write_lock` (F6): a non-door caller
is not routed through the lifecycle for the store lock.

### 4.3 What `HubDisplay` still owns, and why

`HubDisplay` is the store's *coordinator*: the operations that must span several
store collaborators in one hold of the store write lock.

- `apply` — renew the caller, depart the other lapsed connections, *then* check
  ownership and mutate index, owners, installer, remover, seam and quarantine.
  One atomic step; the order is `connection_lease_reaping.tex` I6.
- `replace_scene` — evict a scene's roots and lift its quarantine, then
  re-install each root through `apply`.
- `show_scene` — `replace_scene` and `FrameLifecycle.present` under one hold, so a
  snapshot never pairs new roots with an old presentation.
- `write_lock` — the store's critical section for scene writers.
- `arriving_as(connection_id)` — `write_lock`, with the caller's arrival recorded
  first: showing a scene is the caller reaching the Hub, so the caller registers
  and then writes under the same hold (§4.9).
- `writing_as(connection_id)` — `write_lock`, with the caller's lease renewed
  first: the contact half of `apply`'s prologue for a write that does not go
  through `apply` (§4.7).

Plus the scene-side forwards that §1 leaves alone. It depends on the door through
two collaborators, both read at the head of `apply`:

```python
def __new__(
    cls,
    lock: StoreLock,
    owners: OwnerTracker,
    lifecycle: ClientLifecycle,
    clients: HubClientRegistry,
    clock: Callable[[], float] = time.monotonic,
) -> Self: ...


def apply(self, connection_id, update):
    with self._lock.write():
        self._lifecycle.renew(connection_id)
        self._lifecycle.depart_lapsed(frozenset({connection_id}))
        match update:
            case AddElement(scene_id=sid, parent_id=pid, element=elem):
                session = self._clients.session_of(connection_id)
                owner = Owner.from_session(connection_id, session)
                ...
```

`lock` and `owners` are the two primitives the store and the lifecycle *share*
(the lifecycle releases ownership under the same lock the store mutates under).
Being shared, neither can be created by one side; the factory creates them and
gives both sides the same instance. That is why the constructor grows from two
parameters to five, and why `hub` leaves it: only the cascade needs the `Hub`.

`HubDisplay` loses all eleven door members. (`_depart` and `_depart_lapsed`, which
the first draft listed here, do not exist at the baseline: the stale docstring at
`departure_cascade.py:3` named them, and C1 corrects it.) It no longer imports
`ClientLifecycle`'s collaborators.

### 4.4 The composition root

```python
# domain/hub/hub_store_factory.py
@final
class HubStoreFactory:
    """Builds the shared primitives, the client door, and the store over them."""

    def __new__(
        cls, clock: Callable[[], float] = time.monotonic, hub: Hub = default_hub
    ) -> Self:
        self = super().__new__(cls)
        lock = StoreLock()
        owners = OwnerTracker()
        self._clients = HubClientRegistry(clock)
        self._lifecycle = ClientLifecycle(
            self._clients, owners, DepartureCascade(hub), lock
        )
        self._display = HubDisplay(lock, owners, self._lifecycle, self._clients, clock)
        return self

    @property
    def display(self) -> HubDisplay: ...
    @property
    def lifecycle(self) -> ClientLifecycle: ...
    @property
    def clients(self) -> HubClientRegistry: ...
```

The revert removes `ClientLifecycleFactory`; this builder does its job and is not
a second one. It is read exactly once per process, where its three properties are
unpacked into three module names, and by tests as their composition root. The
defaults (`hub=default_hub`, `clock=time.monotonic`) mirror `HubDisplay.__new__`
today, so a test construction rewrites to `HubStoreFactory().display`.

**Process singletons** — at the bottom of `domain/hub/hub_store_factory.py`, the
module that owns the build. (A first draft put them in a module of their own,
`store_instance.py`; a module of bare singletons has no class, and the new-file
strict rule on `method_ratio` and `class_to_func_ratio` refuses it. Beside the
factory they add no import, so the module's efferent coupling stays at 7, and no
cycle arises: everything that imported `store_instance` already imported through
this module.)

```python
_store = HubStoreFactory(hub)
hub_display: HubDisplay = _store.display
hub_lifecycle: ClientLifecycle = _store.lifecycle
hub_clients: HubClientRegistry = _store.clients
```

`domain/hub/__init__.py` re-exports the three names *instead of* the
`HubDisplay`, `UnknownElementError` and `UnknownSceneError` names it re-exports
today. Nothing in `src/` or `tests/` imports those three from the package (grep
at HEAD); dropping them keeps the package at 15 public names and 10 imported
modules, so the roots that import several singletons from the package gain no
import. `hub_display.py` no longer defines a singleton. The modules that import
the singleton from `hub_display.py` (`clients.py`, `inbox.py`, `lifecycle.py`,
`replicator_instance.py`) import the specific name they use from `hub_store_factory`.

**Roots that hand the objects on** (the only places that name the singletons):

- `hub_composition.py` — `HubComposition.operations()` passes `hub_lifecycle`,
  `hub_clients` and `hub_callback_menus` to `Operations.for_store`, and
  `hub_clients` to the Details and frame-owner recipes. Nothing under `operations/` reaches a singleton, as its docstring
  requires.
- `replicator_instance.py` — builds `HubMenuRegistry`, `CallbackRouter`,
  `MenuEventRouter` and `CallbackMenuReplica` over `hub_clients`, and exports the
  `CallbackMenuReplica` it already builds inline as `hub_callback_menus`.
- `ws_transport.py` — `HubListenTransport.for_hub()` over `hub_lifecycle` and
  `hub_clients.legs`.
- `luxd.py` — `LeaseReapSweep(hub_lifecycle)`.

**Factory parameter order (F3).** `HubStoreFactory.__new__` takes
`(clock, hub)`, the order `HubDisplay.__new__` has today, so a positional
`HubDisplay(clock)` rewrites to `HubStoreFactory(clock)` without a mis-bind. The
design's first draft had them reversed.

`Operations.for_store` gains three keyword arguments, `lifecycle`, `clients` and
`callback_menus` (§4.8). It
seats the production menu sink — `lifecycle.present_as(replicator,
MenuDepartureSink(menu_registry, replicator))` — visibly, as its first statement.
Today that mutation hides inside `MenuArmingDeps.over` (`menu_arming_deps.py`), a
"deps" constructor with a side effect on a shared object. Moving it changes no
behaviour (the same call, once, before serving) and lets `MenuArmingDeps` be the
plain dataclass its name says. The model's invariant, that presence is silent
until seated, is unchanged.

**Construction order and the back-edge.** `apply` is called back by an installed
element: a scene-root's observer fires `RootRemovalRouter.route`, which calls
`HubDisplay.apply`. That cycle exists today and stays inside `HubDisplay.__new__`
(the router is built over `self.apply`, as now). The door does not join it:
`HubDisplay` is built *after* the lifecycle, and the lifecycle reaches the store
only through the `StoreLock` and `OwnerTracker` it was handed. Order:
`StoreLock`, `OwnerTracker`, registry, cascade, lifecycle, `HubDisplay`. No late
binding.

### 4.5 Invariants kept, and how

1. **One step per presence change** (`menu_presence.tex` P1, P2). The registry's
   presence-changing writes — `record`, `renew_if_registered`, `attach`,
   `discard`, `reap_lapsed_locked` — have exactly one caller in `src/`:
   `ClientLifecycle` (checked by grep at the baseline). With concrete classes the
   type system does not stop a future caller from using them; the call graph
   does today, and review holds it. That is the price of not minting a `Protocol`
   per call, and the leader has judged it worth paying. The two registry writers
   outside the lifecycle are `ListenerLegs.register_callback` and `.detach`; they
   are unchanged (the Observation in §8).
2. **The registry never fires a hook.** `HubClientRegistry` imports nothing new
   and still returns a `PresenceChange` for the caller, inside its own lock, to pay.
3. **Store-then-registry lock order** (`menu_presence_locks.tex`). Each
   lifecycle method takes the store write lock, then the registry's. Registry reads
   take the registry lock alone. Nothing hands out the registry lock. `exclusive()`
   returns the *store* lock; a caller that holds it and then calls the lifecycle or
   a registry read only ever adds the registry edge after the store edge.
   `HubDisplay.apply` calls `renew` and `depart_lapsed` while already holding the
   store lock, as now. The one edge DES-098 D3 added, store lock →
   `HubMenuRegistry._lock` (`set_menu` holds the store lock across admit and store,
   `menu_lifecycle.tex`), is unchanged: `MenuOperationsDeps.write_lock` stays
   `display.write_lock`, and `exclusive()` is the same `StoreLock`. The acquisition graph keeps its
   edges and gains none, so the deadlock proofs stand without re-running.
4. **A write is contact before ownership** (I6). The prologue of `apply` is
   unchanged and still precedes the match.
5. **One shared departure sink.** `present_as` is called once, in
   `Operations.for_store`; `arm` and `bind_sink` stay idempotent under the
   cascade's equality dedup.
6. **No singleton in `operations/`** (DES-055). Strengthened: the lifecycle and
   registry arrive as arguments.

No model changes. I add no state and no transition; `exclusive()` is the lock the
lifecycle already takes in every method. If the Observation in §8 is taken up, it
extends the model first.

### 4.6 Tests

Consumer tests construct the consumer with a real `ClientLifecycle` and
`HubClientRegistry` from `HubStoreFactory` — cheap objects with no I/O — and assert
on observable state (`clients.session_of(...)`, the registry's live set). Wiring
tests (apply renews and sweeps others, a departure empties the registry and
releases ownership, the menu mark and sink fire once) use
`HubStoreFactory(clock, hub)`; the factory is the test's composition root.
`tests/hub_harness.py::IsolatedHub` is rebuilt over the factory and
patches the package's `hub_display` name, as before.

**No reach-through in tests (F4).** A test binds `store = HubStoreFactory(...)`
once in its fixture or setup, then names the three objects it uses —
`display = store.display`, `lifecycle = store.lifecycle`, `clients = store.clients`
— and passes *those* to helpers. Call sites read `lifecycle.arrive(c)` and
`clients.session_of(c)`; none reads `store.lifecycle.X`, which would be the
two-hop shape the operator rejected in `HubParts`. A helper that took
`display: HubDisplay` only to reach the door takes `lifecycle` or `clients`
instead; a helper that needs the store keeps `display`. The count is 326
`HubDisplay(` constructions in 50 test files (grep at HEAD, as the evaluator
found), not the 273 in 40 files of the first draft.

**The D5 identify-race test** (`test_identity_menu.py`, "a departure between the
before snapshot and the record still marks and binds") spied by assigning
`store.identify_client`, a member that no longer exists and a class
(`ClientLifecycle`) that is `@final` and slotted. Two seams replace it, neither of
which patches anything:

1. *A real interleave through the public lock.* The test thread takes
   `with lifecycle.exclusive():`, starts `ops.identify(...)` on a worker thread
   (it blocks on the store lock), calls `lifecycle.depart(conn)` on the test
   thread inside the same hold (reentrant), snapshots `spy.menu_marks`, and
   leaves the `with`. The worker's identify then runs wholly after the
   departure. This is the interleaving the test names, produced by the lock the
   design guarantees, and it uses only `exclusive()`, which exists for exactly
   this purpose. The assertions are the existing ones.
2. *If a thread is judged too heavy for a unit test:* call `lifecycle.depart(conn)`
   and then `ops.identify(...)` in sequence. The two are equivalent because
   `identify` is one critical section: a departure either precedes the whole step
   or follows it, never lands inside it, which is `menu_presence.tex` P1. The
   "before snapshot" the test was named for no longer exists to straddle.

I recommend (1) and a second test of (2)'s sequence only if (1) proves flaky.

`tests/domain/test_hub_store_factory.py` carries the cases that prove the wiring:
the lifecycle and the registry share one registration; a departure empties it; a
write by a registered caller renews its lease; a write sweeps other lapsed
connections but never its own caller; lifecycle and store release ownership under
the same lock instance; and `writing_as` renews the caller's lease and holds the
store lock.

### 4.7 Contact on the write path (second amendment)

The first implementation attempt handed `ClientLifecycle` to every consumer that
used to call `display.renew_contact`. The ratchets said the consumers now took the
store *and* the door, when most of them do no door work. I re-read each renew
against the code. The rule that falls out: a consumer takes the door only for
door work, and "a write to the scene store is contact" is the store's rule.

`HubDisplay.apply` already renews the caller in its prologue (I6). Which renews
are therefore redundant?

| Consumer | Its renew | Redundant with a store write it already makes? |
|---|---|---|
| `HubSceneWriter.apply` | renew, then validate and commit | **No.** Field patches commit through `write_seam`, which never reaches `apply`; only removals do. A field-only batch, or one rejected whole, would be no contact at all, which is what I6 ("a live writer is never reaped by its own write") forbids. The renew is the *store's* contact rule applied to a write that bypasses `apply`. |
| `HubSceneWriter.clear` | renew, then `apply` per owned root | Partly (each `apply` renews), but an owner with nothing to clear still makes contact today. Same answer. |
| `SceneClearer` | none of its own; through the writer | n/a |
| `SceneOperations.install` | `arrive` | **No, and it is door work, but the store's to do (§4.9).** `apply` renews *iff registered*; `arrive` registers. A client that only ever shows is still a client (the docstring on `install`), and `replace_scene` says "a write registers nobody: a session comes only from its own arrival". |
| `PubSubOperations._contact` | `renew`, then `ports.ensure_writer` | For subscribe, publish and receive the production port (`inbox.ensure_writer`) runs `arrive`, which renews, so the renew is redundant *with that implementation*. The port's contract is "bind the session's inbox writer; idempotent", the tests inject fakes, and `unsubscribe` calls no port at all: it renews and nothing else. Deleting the renew would couple the concern to an incidental behaviour of `inbox.py` and drop contact on `unsubscribe`. Kept. Its only door act is the lease, so it takes `ClientLifecycle`. |
| `CallbackOperations.register_callback` | `renew`, then `listener_for` | No; renew-iff-registered is door work. |
| `MenuArming.admit` | `renew`, identity check, `arm` | No; door work. |
| `IdentityOperations.identify` | `identify` | It *is* the door transition. |

So the writer pair loses its door dependency by giving the store the half of the
rule that is the store's. `HubDisplay` gains one method:

```python
@contextmanager
def writing_as(self, connection_id: ConnectionId) -> Iterator[None]:
    """Hold the store lock as ``connection_id``, its lease renewed first."""
    with self._lock.write():
        self._lifecycle.renew(connection_id)
        yield
```

It is store coordination of the same kind as `apply`'s prologue, over the two
members `apply` already uses (`_lock`, `_lifecycle`), so it shares state with
`apply` and does not add a disjoint cluster. It is not one of the eleven forwarders
(R3): those exposed the door; this holds the store's lock for a write. `HubSceneWriter.apply`
and `.clear` use it in place of `write_lock()` plus `renew_contact`, and
`HubSceneWriter(display)` and `SceneClearer(display, replicator)` keep their
baseline signatures. The leader's other options are weaker: deleting the renew
changes I6 for field-only writes, and leaving it on the writer makes two
scene-write classes depend on the door for a rule the store owns.

**Should the one `Operations` entry point own "a request is contact" (DES-055)?
No.** Three reasons, from the code:

1. *Contact depends on the request being accepted.* Reserved topics are refused
   "before any contact" (`PubSubOperations`), a bad wire tree is rejected in
   `render` before `install` arrives, and an anonymous `menu_set` renews and is
   then refused. A facade-level renew either runs before those checks, changing
   behaviour (a rejected request would extend a lease), or re-implements their
   branching.
2. *There are three different acts, not one.* `arrive` registers, `renew`
   extends iff registered, and reads do neither (`inspect_scene`, `identity_of`,
   `pending_callbacks`, `list_*`; a read changes nothing,
   `connection_lease_reaping.tex`). "Every scope-taking entry point renews" would
   make reads contact.
3. *It moves the call sites without removing any.* Roughly a dozen facade methods
   would call the lifecycle, and the one class every surface passes through would
   take a door dependency. DES-055 asks the facade to be a thin delegating surface.

The owner of the rule is the concern that knows whether its request was accepted,
and the store for writes that bypass `apply`.

### 4.8 The callback and frame-owner shapes (second amendment)

**`CallbackOperations`.** At C1 it held `_lifecycle`, `_clients` and `_legs`;
`register_callback` used the first and third, `callback_menus` the second, so the
class split into disjoint clusters (LCOM 0.533 to 0.6, over the 0.5 cap, so not
blessable). The cause is that it carries a second concern. `callback_menus()` is
the registry's naming view, and `CallbackMenuReplica` (the replicator's read)
already composes the identical expression, `CallbackMenu.from_named(clients.
named_sessions())`. That is duplication, not a shared job. The shape:

- `CallbackMenuReplica` gains `callback_menus() -> list[Menu]`; it already owns
  `_clients` and the read, and both its methods read `self._clients`.
- `CallbackOperations(lifecycle, legs, router, replicator)` loses `callback_menus`
  and `_clients`. `register_callback` is the one door act (renew, read the leg,
  write under it).
- `CallbackMenuSource` is satisfied by `CallbackMenuReplica`. The roots hand it in:
  `replicator_instance.py` already builds one inline for the `HubReplicator` and
  exports it as `hub_callback_menus`; `Operations.for_store` takes it as a keyword.

Measured on the prototype: `callbacks.py` LCOM 0.533 to 0.5 and efferent 4 to 3,
both improved.

**Folding `register_callback`/`detach` into `ClientLifecycle` now? No, and the
honest answer is that it is not needed.** Folding is the right end state: it
removes `ListenerLegs` from `CallbackOperations` and both listen classes. But it
changes who announces a presence change, which is the model extension tracked as
`lux-s9rl`, and `menu_presence.tex` must be extended and model-checked first. The
listen classes did not regress `check-coupling` in the C1 measurement
(`ws_listen.py`, `ws_transport.py` only regress OO size and parameter counts), so
nothing here forces the fold. The leader's ruling (b) stands; if the leader pulls
`lux-s9rl` into this unit, `CallbackOperations` becomes `(lifecycle, router,
replicator)` and the listen classes drop `legs`.

**`FrameOwnerFacts`.** It does not need the registry. Its `_named` read, and the
identical `ClientDetailsOperations._named`, find one connection among the named
live sessions. Two copies of "read several fields of `NamedSessions` and build a
`NamedSession`" is PY-OO-5: it belongs on the class.

- `NamedSessions.named(connection_id, fallback) -> NamedSession | None` is that
  method.
- `ClientListing`, which already holds the registry for `live_sessions`, gains
  `named(connection_id)`, the one place the unnamed fallback (`"client"`) lives.
- `FrameOwnerFacts(display, listing)` and `ClientDetailsOperations(listing,
  installer)` take the `ClientListing` they only ever reached through
  `QueryOperations.client_facts`. `QueryOperations` is unchanged from the baseline.
  `ClientDetailsOperations` loses the registry parameter it has at the baseline.
- The three `for_store` recipes (`FrameOwnerFacts`, `CanonicalFrameOwner`,
  `ClientDetailsPort`) take `clients`, to build the `ClientListing`.

### 4.9 The show path goes through the store (third amendment)

`SceneOperations.install` is the one scene verb that does door work: it `arrive`s
the caller, then installs. Giving that class a `ClientLifecycle` made the class
itself disjoint (`install` stopped sharing `_display` with `update`) and raised its
LCOM from 0.6 to 0.667, over the cap, so not blessable. A Command-pattern split
into `ShowScene`, `UpdateScene` and `ClearScene` cured that class but moved the
cost to the facade (0.845 to 0.854, also over the cap), and CI scores the facade as
touched. The leader's ruling: do not split in this unit; give the store the
symmetric half of `writing_as`.

```python
@contextmanager
def arriving_as(self, connection_id: ConnectionId) -> Generator[None]:
    """Hold the store lock as ``connection_id``, its arrival recorded first."""
    with self._lock.write():
        self._lifecycle.arrive(connection_id)
        yield
```

`SceneOperations.install` becomes `with self._display.arriving_as(cid): return
self._installer.install(submission, owner=cid)`. The class holds `_display` and
`_installer` exactly as at HEAD, so `SceneOperationsDeps` keeps its four fields,
`SceneOperations` and `SceneClearer` have their baseline signatures, and the facade,
`OperationsConcerns` and `ConvenienceOperations` are unchanged apart from the door
arguments of `for_store`. `scenes.py` LCOM stays at 0.6.

**Soundness, checked against the code.**

- *Details never arrives.* `ClientDetailsOperations` installs through
  `SceneInstaller` directly (`_shown`), never through `SceneOperations.install`, so
  it does not pass through `arriving_as` and an inspected client's lease is not
  renewed. Nothing else calls `arriving_as`; `TestWhoAnInstallRegisters` covers the
  Details-shaped install and still passes, and
  `test_a_write_through_apply_registers_nobody` pins that the store itself never
  registers.
- *Lock order.* The install now runs inside one store-lock hold, including its
  `mark_dirty` calls to the replicator. `DirtyMarker.mark_dirty` is queue-only: it
  takes the replicator signal's condition for the length of a set insert and
  never reaches back into the store. `SceneOperations.update` already calls
  `mark_dirty` inside its `write_lock` hold, so the edge store lock to signal lock
  exists today. No edge is added, and no cycle (the worker drains the signal and
  releases it before it reads the store).
- *Behavior.* The arrival and the install were two lock holds and are now one. The
  window between them, in which a departure could slip between the `arrive` and
  the install, is gone; the outcome (a registered caller who then installs) is
  otherwise the same.

The Command conversion and the naming fix (no `Operations`/`Concerns`/`Deps`
suffixes) are one consistent change across every concern, and belong together in
bead `lux-x4ex`, not in this unit.

## 5. Migration

The leader runs `git revert 81bfb8a5` first (C0, done as `64c75f48`). After it,
**one implementation commit and one docs commit** (second amendment).

The first plan split the work into C1 (consumers take the door classes) and C2
(the flip). The C1 measurement showed the split is a ratchet trap, not just a
convenience: C1 on its own regresses `check-oo` on 28 metrics in 20 files and
`check-coupling` on four, with no offsetting improvement, because the improvement
(`hub_display.py` losing eleven members and six imports) arrives only with the
flip. The two are one rollback-coherent unit and are judged on their net numbers.

| Commit | What |
|---|---|
| **Implementation** | `HubStoreFactory` with the singletons beside it, `HubDisplay.writing_as`; `HubDisplay.__new__` takes `(lock, owners, lifecycle, clients, clock)`; all eleven door members and the singleton leave `hub_display.py`; every consumer in §4.2 takes the class it uses; `ClientLifecycle.exclusive()`; the `present_as` seat moves into `Operations.for_store`; `LeaseReaper.depart_lapsed(exclude)` (F1); `CallbackMenuReplica.callback_menus` (§4.8); `NamedSessions.named` and `ClientListing.named` (§4.8); `departure_cascade.py` docstring (F5); the whole test migration. |
| **Docs** | DES-101 (the leader writes it) and `system.tex`'s subsection "HubDisplay: the Authoritative Store". |

**The test migration** is mechanical per construction site and wholly checked by
the suite. In each file that builds a store, bind once, then pass the objects
down (§4.6): `store = HubStoreFactory(...)`; `display = store.display`;
`lifecycle = store.lifecycle` and `clients = store.clients` only where used. Then
`display.register_client(c)` becomes `lifecycle.arrive(c)`, `identify_client`
`lifecycle.identify`, `drop_connection` `lifecycle.depart`, `reap_lapsed_leases()`
`lifecycle.depart_lapsed(frozenset())`, `renew_contact` `lifecycle.renew`,
`bind_departure_sink` `lifecycle.bind_sink`, `display.clients.X` `clients.X`,
`display.lifecycle.X` `lifecycle.X`, `display.client_sessions()`
`clients.live_sessions()`, and `display.is_client(c)`
`clients.session_of(c) is not None`. Scene-only tests become
`display = HubStoreFactory(...).display`. **Arguments are keyword** (`clock=`,
`hub=`) wherever a call site passed them by position, although the factory now
takes `(clock, hub)` like the old constructor, so nothing can bind a clock as a
hub (F3). The count is 326 `HubDisplay(` constructions in 50 files (F4).

**The green gate needs the leader.** The net regression list in §6 is all within
cap except one item, and `check-oo` and `check-coupling` fail on any regressed
metric. The commit can be made only after the leader blesses the within-cap list
(DES-096/097) and rules on the one over-cap item (§8). The worker's job is to
produce the tree, run `make check`, and report the numbers; it does not bless.

## 6. Metrics

Signals, never targets. Measured with the repository's own tools,
`tools/oo_coupling.py` and `tools/oo_score.py`, run on three trees and compared
file by file:

- **HEAD** (`64c75f48`, the revert baseline), exported with `git archive`.
- **The first implementation attempt** (C1 alone, the uncommitted tree: consumers
  take the door, `HubDisplay` unchanged).
- **The revised design**, as a source-only prototype of the whole merged change
  in a scratch tree (`.tmp/proto`; the tests are not in it, and neither tool reads
  them). It is the design of §4, not a stand-in.

### `hub_display.py`

| | `main` (the ratchet baseline) | HEAD | first attempt (C1) | revised design |
|---|---|---|---|---|
| avg and max LCOM | 0.636 | 0.737 | 0.728 | **0.593** |
| efferent coupling | 26 | 27 | 27 | **21** |
| `module_size` | | 382 | | **342** |
| `avg_params` | | 1.03 | | 1.30 |
| `avg_complexity` | | 1.21 | | 1.30 |
| public names | 5 | 5 | | 4 |

LCOM and efferent are better than the baseline's `main` values (0.636, 26), so
`check-coupling` sees `hub_display.py` improve, as the design intended. Efferent
falls by six, not four: `client_lifecycle`, `departure_cascade`, `hub_clients`,
`hub`, and also `owner_tracker` and `store_lock`, which the file now names only
in annotations (`TYPE_CHECKING`). The `avg_params` and `avg_complexity` rise is
the arithmetic of deleting many one-line, one-parameter members and widening
`__new__` to five parameters (leader ruling (a)); both are far inside their caps
(4.0 and 5.0).

### What the first attempt's regressions were, and what became of them

| First attempt | Cause | Now |
|---|---|---|
| `scene_writer.py`, `scene_clearing.py` params and size | a lifecycle beside the store, for a renew | gone (§4.7: `writing_as`) |
| `callbacks.py` LCOM 0.533 to 0.6 (over cap) | `_legs` disjoint from `_clients` | 0.5, improved (§4.8) |
| `frame_owner_facts.py` LCOM 0 to 0.333 | a registry used by one method | gone (§4.8) |
| `hub_display.py` `max_lcom`, `avg_lcom`, efferent | the door members still there | improved (the flip) |
| `facade.py`, `hub_composition.py`, `__init__` efferent | a new import per new name | held by moving the re-exports (§4.4) and passing `callback_menus` in (§4.8); the facade keeps its HEAD imports (§4.9) |

### Predicted regressions after the merge, against HEAD

Every item the tools report as worse than HEAD on the revised prototype, with the
cap that applies. `check-coupling` caps: efferent 7, public names 15, avg LCOM
0.5; `check-oo` caps: `avg_params` 4.0, `module_size` 300, `avg_complexity` 5.0.
`top_level_statements` has no cap.

`check-coupling`:

| File | Metric | HEAD to revised | Cap |
|---|---|---|---|
| `client_lifecycle.py` | max, avg LCOM | 0.073 to 0.076 | within |
| `client_listing.py` | max, avg LCOM | 0.333 to 0.5 | **at** cap (inclusive), within |
| `identity.py` | max, avg LCOM | 0 to 0.333 | within |
| `replicator_instance.py` | public names | 4 to 5 | within |
| `hub_store_factory.py` (new) | efferent, LCOM | 7, 0.5 | **at** both caps; new files are judged by the same `<=`, but there is no margin: one more runtime import fails it. The fallback is the one in the first draft (build registry, cascade and lifecycle in a small `ClientLifecycleFactory`, bringing the builder to 5). |

`check-oo` as the prototype predicted it (all within cap; the measurement below
supersedes it): `callback_menu.py` size 81 to 84;
`client_lifecycle.py` size 103 to 111; `hub_display.py` `avg_params`,
`avg_complexity` (above); `hub_reads.py` `avg_params` 1.4 to 1.5,
`avg_complexity` 1.2 to 1.25; `lease_reap_sweep.py` size 59 to 61, `avg_params`
0.5 to 0.75; `lifecycle.py` `top_level_statements` 1 to 2; `named_sessions.py`
size 130 to 136, `avg_params` 0.73 to 0.81, `avg_complexity` 1.4 to 1.44;
`replicator_instance.py` size 60 to 62, `top_level_statements` 7 to 8;
`hub_composition.py` size 85 to 101; `callbacks.py` `avg_params` 1.0 to 1.33,
`avg_complexity` 1.57 to 1.67; `canonical_frame_owner.py` size 55 to 64,
`avg_params` 1.6 to 1.8; `client_details_port.py` size 58 to 63, `avg_params` 2.0
to 2.33; `client_listing.py` size 74 to 89, `avg_params` 1.5 to 1.6,
`top_level_statements` 2 to 3; `facade.py` size 276 to 289, `avg_params` 1.38 to
1.47; `frame_owner_facts.py` `avg_params` 1.75 to 2.33, `avg_complexity` 1.5 to
1.67; `identity.py` size 53 to 55, `avg_params` 1.33 to 1.67; `ws_listen.py` size 245 to 250,
`avg_params` 0.82 to 0.91; `ws_transport.py` size 101 to 108, `avg_params` 1.4 to
1.6. The largest value reached is `facade.py` at 289 of 300 and `avg_params` at
2.33 of 4.0.

Every one of these is a named dependency where a hidden one stood, or a line or
two that a new name costs. None is a design defect; all need the leader's bless
because the tools refuse any regressed metric. The `check-oo` improvement the
ratchet also requires comes from `hub_display.py` (`module_size` 382 to 342,
and the removal of eleven members), `client_details.py` (a parameter and a
method gone) and `callbacks.py`/`hub_display.py` coupling.

**Measured on the implemented tree (the real `make check`).** `check-coupling`
scopes itself to the files committed since the merge base, so before the code is
committed it checks only the files earlier commits on the branch touched, and
reports `client_lifecycle.py` LCOM 0.073 to 0.076 (within cap). Scoring every file
this change touches against the coupling baseline gives the full list the
post-commit run will show: that one, plus `identity.py` LCOM 0 to 0.333,
`client_listing.py` LCOM 0.333 to 0.5 (at the cap), and `replicator_instance.py`
public names 4 to 5, all within cap; and the new files, none over
(`hub_store_factory.py` at efferent 7 and LCOM 0.5, both exactly at their caps).
There is **no over-cap regression**: `scenes.py` stays at LCOM 0.6, `facade.py` at
0.845, and `queries.py` is untouched. The improvements: `hub_display.py` (efferent
26 to 21, LCOM 0.636 to 0.593, public names 5 to 4), `callbacks.py` (efferent 4 to
3, LCOM 0.533 to 0.5), `client_details.py` (LCOM 0.667 to 0), `named_sessions.py`
(LCOM 0.411 to 0.4), `frame_owner_facts.py` (efferent 4 to 2) and
`menu_arming_deps.py` (efferent 2 to 1). `check-oo` reports twenty-six regressed
metrics in fourteen files, every one within cap; the largest is `facade.py`
`module_size` 284 to 287 of 300 and `frame_owner_facts.py` `avg_params` 2.33 of 4.0.

## 7. Alternatives rejected

**R1. `HubParts` / `HubDisplay.parts`.** A record of eight collaborators reachable
from the facade. It lowered one metric by moving the fan-out into the consumers,
which then reach through the bundle: `display.parts.lifecycle.renew(...)` is two
hops where the caller needs one, and a `PubSubOperations` still cannot be built
without a store that has a lifecycle, a frame authority, a reader and four more.
It is a service locator, so Demeter and interface segregation are both violated
at every call. Rejected by the leader and the operator; agreed. The leader's
revert removes it.

**R2. `StoreLookups` (and any grab-bag of reads).** An earlier bundle of lookups
over the store, retired to `.tmp/retired/store_lookups.py`. The same defect as R1
in a smaller size: a class whose methods are chosen by the provider's shape, not
by what any caller needs. It does not apply to the door, whose providers are
already small cohesive classes.

**R3. Keep forwarding methods on `HubDisplay`.** Eleven one-line methods, each
calling `self._lifecycle.x(...)` or `self._clients.x(...)`. Callers stay
unchanged, which is the appeal. But that is the wide-facade shape that took LCOM
from 0.636 to 0.737: each forwarder touches one private attribute disjoint from
the rest, and `HubDisplay` stays the thing every consumer's constructor names.

**R4. A `ClientDoor` record (`lifecycle`, `registry`) handed to consumers.**
Smaller and more cohesive than `HubParts`, but a consumer holding it must still
choose a field per call and would be given two when it needs one. It would be
reached through, which is R1.

**R5. Eleven single-method `Protocol`s** (`Arrival`, `ContactRenewal`,
`IdentityRecording`, and so on) in a `client_ports.py`, the design in `842d4e5d`.
It maximises interface segregation and costs eleven types, a conformance test and a
guard to keep them honest, for a dependency that `ClientLifecycle` and
`HubClientRegistry` already express as two cohesive classes. The one structural
benefit, that nothing can call a registry write, is held today by the call graph
(§4.5). Over-engineered for the problem; withdrawn at the leader's direction.

**R6. Late-bound wiring (a `bind(display)` step).** Tempting because `HubDisplay`
and the door look mutually dependent. They are not: the door depends on the lock
and the ownership map, not on the store, so construction order is acyclic (§4.4).
No late binding is needed, and none is introduced.

**R7. `HubDisplay` takes the factory.** `HubDisplay(factory)` would restore the
two-parameter constructor. It also makes the store depend on its own builder and
hides the five real dependencies again.

## 8. Rulings applied, and what is left

The leader ruled on the four questions in `842d4e5d`.

**D1 → Q-C. `SceneQuarantine` is not extracted in this unit.** The revert takes
`scene_quarantine.py`, `HubParts`, `ClientLifecycleFactory` and
`SceneReader.replicable_scene_ids` away together; quarantine stays inline in
`HubDisplay` (`QuarantineRegistry`, the observer list, `_lift_quarantine`) as on
`main`, and `live_scene_ids` computes the replicable set there. All of them return,
with their callers, in the follow-on unit. For the record, the measured LCOM of the
options on this file: extracted with four forwarders kept 0.738; extracted with
callers holding it directly ≈ 0.70; extracted but forwarding under `HubDisplay`'s
own lock ≈ 0.606 (rejected as metric-gaming, the redundancy is the signal);
not extracted **0.606**. Only the last passes `check-coupling` without a design
change to unrelated code.

**D2 → yes.** `client_sessions` and `client_repos` leave `HubDisplay` and
`HubReads`. `client_repos` has no caller; `ClientListing` reads
`clients.live_sessions()`.

**D3 → yes.** `ClientLifecycle.exclusive()` (§4.2).

**D4 → a small builder is fine; the confinement guard is dropped.** No AST scan
test. The builder is three properties and one constructor; the review that rejected
`HubParts` is the guard.

**Leader rulings on the evaluation (applied).** (a) `HubDisplay` takes
`HubClientRegistry` for `session_of`; there is no `owner_for` on the lifecycle (the
lifecycle is the write side). (b) `ListenerLegs.register_callback` and `.detach`
stay as they are in this unit; bead `lux-s9rl` folds them in, model first (§4.8).

**Second amendment (after the C1 measurement).** §4.7 (contact belongs to the
store for writes that bypass `apply`, and to each concern for door acts; not to the
facade), §4.8 (`CallbackMenuReplica` carries the Clients-menu read; `FrameOwnerFacts`
and `ClientDetailsOperations` take `ClientListing`), one implementation commit
(§5), and the predicted net regressions with their caps (§6).

**Left for the leader.** Nothing is over cap. Everything in §6 is within cap and is
the leader's to bless as a list.

**Observation (not a decision).** `ListenerLegs.register_callback`
(`callbacks.py`) and `ListenerLegs.detach` (`ws_listen.py`) change who the Clients
menu lists but are performed *outside* `ClientLifecycle`, with the mark raised by
the caller. That is the "caller is trusted to remember" shape `menu_presence.tex`
exists to remove, and `menu_presence.tex:133-135` elides the callback route as
"the same obligation on a different transition". I leave both as they are: moving
them changes the verified model and should extend the model first. I recommend a
bead.

## 9. Implementation write-set

The design names it; the implementation mission's contract should list these.

**New.** `src/punt_lux/domain/hub/hub_store_factory.py` (the factory and the singletons),
`tests/domain/test_hub_store_factory.py`.

**Changed, domain.** `hub_display.py` (constructor; the eleven door members and
the singleton out; `writing_as` in), `client_lifecycle.py` (`exclusive()`),
`hub_reads.py` (`client_sessions` and `_clients` out), `inbox.py`, `lifecycle.py`,
`clients.py`, `replicator_instance.py` (`hub_callback_menus`), `scene_writer.py`
(`writing_as`), `lease_reap_sweep.py` (`depart_lapsed(exclude)`),
`callback_menu.py` (`callback_menus`), `named_sessions.py` (`named`),
`departure_cascade.py` (docstring, F5), `domain/hub/__init__.py` (re-exports).

**Changed, operations and surfaces.** `operations/facade.py`, `scenes.py`
(`arriving_as`), `pubsub.py`, `callbacks.py`, `identity.py`,
`menu_arming.py`, `menu_arming_deps.py`, `client_listing.py`,
`client_details.py`, `client_details_port.py`, `frame_owner_facts.py`,
`canonical_frame_owner.py`; `ws_listen.py`, `ws_transport.py`, `luxd.py`,
`hub_composition.py`.

**Tests.** The 50 test files with a `HubDisplay(` construction (326 sites) and the
44 with door sites (largely the same files); `tests/hub_harness.py`;
`tests/domain/test_hub_store_factory.py`; the D5 test (§4.6).

**Docs.** `DESIGN.md` (DES-101), `docs/architecture/system.tex` (the subsection
"HubDisplay: the Authoritative Store"). `CHANGELOG.md`: none; the change is
internal and not user-visible.

## 10. Draft DES-101

> **DES-101: The client door is a lifecycle callers hold, not a store they ask.**
>
> **Context.** The menu-presence fix made every change to who the Clients menu
> lists one `ClientLifecycle` step. `HubDisplay` still fronted it with eleven
> forwarding members, which drove `hub_display.py`'s avg LCOM from 0.636 to 0.737
> and left every caller depending on the store for a capability it does not own.
>
> **Decision.** `HubDisplay` has no client member. A caller is constructed with
> the cohesive class it uses: `ClientLifecycle` for door writes,
> `HubClientRegistry` for door reads, `ListenerLegs` for the listener slot; a
> scene write is contact by the store's own rule (`HubDisplay.writing_as`). The
> shared `StoreLock` and `OwnerTracker` are created by `HubStoreFactory`, which
> builds the door and then the store over them; process singletons are exported
> by name from `hub_store_factory.py`. A `Protocol` is added only where a real
> dependency direction requires one.
>
> **Rejected.** `HubParts`; forwarding methods; a `ClientDoor` record; one
> `Protocol` per call; a late-bound store.
>
> **Consequences.** Constructors name what they use. The lock order and every
> menu-presence invariant are unchanged. Scene reads, frames, writer and
> quarantine remain on `HubDisplay`; narrowing them, and extracting
> `SceneQuarantine`, are a separate unit.
