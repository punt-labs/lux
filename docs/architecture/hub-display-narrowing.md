# HubDisplay and the Client Door: Design

**Status:** design, amended after the leader's review of `842d4e5d`; for the
leader's final review. No code is written by this document; the implementation
write-set is §9.
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
  cascade, the client registry and the `Hub` (efferent 27 → 23, measured), and
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
| `HubDisplay()` constructions | 1 (the singleton) | 273 in 40 files |
| Consumer constructions in tests that may change signature | n/a | at most 162 sites, 39 files |

So the door slice is about 300 call sites, not 700. The 273 constructions matter
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
consumer the class is not a wide dependency.

| Consumer | Takes | Uses |
|---|---|---|
| `SceneOperations`, `SceneClearer` (via `SceneOperationsDeps`) | `ClientLifecycle` | `arrive`, `renew` |
| `HubSceneWriter` | `ClientLifecycle`, beside its `HubDisplay` | `renew` |
| `PubSubOperations` | `ClientLifecycle` | `renew` |
| `CallbackOperations` | `ClientLifecycle`, `HubClientRegistry`, `ListenerLegs` | `renew`; `named_sessions`; `listener_for`, `register_callback` |
| `IdentityOperations` | `ClientLifecycle`, `HubClientRegistry` | `identify`; `identity_of` |
| `MenuArming` (via `MenuArmingDeps`) | `ClientLifecycle`, `HubClientRegistry` | `renew`, `arm`; `identity_of` |
| `MenuOperationsDeps.write_lock` | `lifecycle.exclusive`, a callable as now | the store lock |
| `HubListenSession`, `HubListenTransport` | `ClientLifecycle`, `ListenerLegs` | `attach`, `identify`, `exclusive`; `detach` |
| `inbox.ensure_writer` | module name `hub_lifecycle` | `exclusive`, `arrive`, `bind_sink` |
| `lifecycle.disconnect_connection` | `ClientLifecycle`, default `hub_lifecycle` | `depart` |
| `LeaseReapSweep` (luxd) | `LeaseReaper` (exists) ← `hub_lifecycle` | `depart_lapsed` |
| `HubMenuRegistry`, `CallbackRouter`, `MenuEventRouter` | `LiveSessions` (exists) ← `hub_clients` | `live_sessions` |
| `CallbackMenuReplica`, `FrameOwnerFacts`, `ClientDetailsOperations` | `HubClientRegistry` | `named_sessions` |
| `ClientListing` | `HubClientRegistry` | `live_sessions` |
| `HubDisplay.apply` | `ClientLifecycle`, `HubClientRegistry` | `renew`, `depart_lapsed`; `session_of` |

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
already takes. `ws_listen`, `inbox.ensure_writer` and menu arming each hold the
store lock across a door step plus a Hub writer or inbox step so a departure
cannot interleave. They take it from the door they already depend on instead of
from `HubDisplay.write_lock`.

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
) -> Self:
    ...

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

`HubDisplay` loses all eleven door members and `_depart`, `_depart_lapsed`. It no
longer imports `ClientLifecycle`'s collaborators.

### 4.4 The composition root

```python
# domain/hub/hub_store_factory.py
@final
class HubStoreFactory:
    """Builds the shared primitives, the client door, and the store over them."""

    def __new__(cls, hub: Hub = default_hub, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        lock = StoreLock()
        owners = OwnerTracker()
        self._clients = HubClientRegistry(clock)
        self._lifecycle = ClientLifecycle(self._clients, owners, DepartureCascade(hub), lock)
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

**Process singletons** — new `domain/hub/store_instance.py`, in the house style of
`replicator_instance.py` and `details_instance.py`:

```python
_store = HubStoreFactory(hub)
hub_display: HubDisplay = _store.display
hub_lifecycle: ClientLifecycle = _store.lifecycle
hub_clients: HubClientRegistry = _store.clients
```

`domain/hub/__init__.py` re-exports the three names; `hub_display.py` no longer
defines a singleton. The modules that import the singleton from `hub_display.py`
(`clients.py`, `inbox.py`, `lifecycle.py`, `replicator_instance.py`) import the
specific name they use from `store_instance`.

**Roots that hand the objects on** (the only places that name the singletons):

- `hub_composition.py` — `HubComposition.operations()` passes `hub_lifecycle` and
  `hub_clients` to `Operations.for_store` and to the Details and frame-owner
  recipes. Nothing under `operations/` reaches a singleton, as its docstring
  requires.
- `replicator_instance.py` — builds `HubMenuRegistry`, `CallbackRouter`,
  `MenuEventRouter` and `CallbackMenuReplica` over `hub_clients`.
- `ws_transport.py` — `HubListenTransport.for_hub()` over `hub_lifecycle` and
  `hub_clients.legs`.
- `luxd.py` — `LeaseReapSweep(hub_lifecycle)`.

`Operations.for_store` gains two keyword arguments, `lifecycle` and `clients`. It
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
   `menu_lifecycle.tex`), is unchanged: `MenuOperationsDeps.write_lock` becomes
   `lifecycle.exclusive`, the same `StoreLock`. The acquisition graph keeps its
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
`HubStoreFactory(hub, clock).{display,lifecycle,clients}`; the factory is the
test's composition root and a test takes only the property it uses.
`tests/hub_harness.py::IsolatedHub` is rebuilt over the factory and
monkeypatches the three `store_instance` names instead of one.

`tests/domain/test_hub_store_factory.py` carries the cases that prove the wiring:
the lifecycle and the registry share one registration; a departure empties it; a
write by a registered caller renews its lease; a write sweeps other lapsed
connections but never its own caller; lifecycle and store release ownership under
the same lock instance.

## 5. Migration

The leader runs `git revert 81bfb8a5` first (C0). After it, three commits, each
passing `make check`, each wiring every caller in the same commit.

| Commit | What | Size |
|---|---|---|
| **C1** Consumers | Every consumer in §4.2 is constructed with `ClientLifecycle`, `HubClientRegistry` or `ListenerLegs`; `ClientLifecycle.exclusive()` is added; the `present_as` seat moves into `Operations.for_store`; `LeaseReaper`'s method is renamed `depart_lapsed` to match the lifecycle; `ClientListing` reads `clients.live_sessions()` and `HubReads.client_sessions` and its `_clients` are deleted. Roots pass `display.lifecycle` and `display.clients`, which still exist. The tests that construct these consumers move first to the new signatures. | 14 source files, up to 162 test constructions in 39 files (only signature changes are touched) |
| **C2** The flip | `HubStoreFactory`, `store_instance`; `HubDisplay.__new__` takes `(lock, owners, lifecycle, clients, clock)`; all eleven door members, `_depart`, `_depart_lapsed` and the singleton leave `hub_display.py`; roots read the singletons. One scripted rewrite of the tests in the same commit (below). | `hub_display.py`, 8 roots; 273 constructions, about 272 door sites |
| **C3** Docs | DES-101, and `system.tex`'s `HubDisplay` section (the subsection "HubDisplay: the Authoritative Store"). | docs only |

The C2 test rewrite is deterministic. In each file that builds a store, bind
`store = HubStoreFactory()` and `display = store.display`; then
`display.register_client(c)` → `store.lifecycle.arrive(c)`, `identify_client` →
`.identify`, `drop_connection` → `.depart`, `reap_lapsed_leases()` →
`.depart_lapsed()`, `renew_contact` → `.renew`, `bind_departure_sink` →
`.bind_sink`, `display.lifecycle.X` and `display.clients.X` → `store.lifecycle.X`
and `store.clients.X`, `display.client_sessions()` →
`store.clients.live_sessions()`, and `display.is_client(c)` →
`store.clients.session_of(c) is not None`. Scene-only tests that never touch the
door become `display = HubStoreFactory().display`. The full suite is the check.

C2 is the largest commit and the most mechanical; it cannot be split without a
period in which `HubDisplay()` and `HubStoreFactory` both construct stores, which
is a shim. C1 first leaves C2 a small source change plus the scripted rewrite.

## 6. Metrics

Signals, never targets. Measured with the `oo_coupling.py` definitions (LCOM over
`self._*` attribute sets per method pair; efferent over top-level `punt_lux`
imports) on real source at `main` and at the baseline, and on a model of the
post-change class for the last column. My re-implementation reproduces `main`'s
0.636 exactly. It gives 0.737 for `81bfb8a5^` where the leader quoted 0.766; the
gap does not change any conclusion.

For `hub_display.py`:

| | `main` | baseline (`81bfb8a5^`) | this design |
|---|---|---|---|
| avg LCOM | 0.636 | 0.737 (33 methods) | **0.606** (22 methods) |
| efferent coupling | 26 | 27 | **23** |
| lines | 466 | 450 | ≈ 365 |
| `__new__` parameters | 2 | 2 | 5 |
| public names | 5 | 5 | 5 |

- *LCOM.* The door's methods shared `_lock` and `_clients` with each other and
  with `apply`; removing the eleven of them improves the file against both `main`
  and the baseline, and `0.606` is below `main`'s `0.636`, so `check-coupling`
  sees an improvement. It is still above the 0.5 cap, which is `main`'s debt and
  is not regressed. This number depends on Q-C (§8): with `SceneQuarantine`
  extracted and four forwarders kept, the same model gives 0.738 and DES-096/097
  refuse the bless.
- *Efferent.* −4 runtime imports: `client_lifecycle`, `departure_cascade`,
  `hub_clients`, `hub`. The file stays far over the cap of 7 because it still
  constructs the scene collaborators; that is `main`'s debt.
- *Parameters.* `__new__` goes from 2 to 5. That raises avg parameters on the
  file; deleting the eleven one- and two-parameter door members offsets part of
  it. Not measured, since `oo_score` needs the code. The five are exactly the
  dependencies the old signature hid.
- *Lines.* Estimated, not measured.

Other files, expected direction and why:

| File | Expected | Why |
|---|---|---|
| `hub_reads.py` | avg LCOM down | `client_sessions` was the only method using `_clients`, disjoint from every other; it leaves with the field. |
| `client_lifecycle.py` | flat | `exclusive()` touches `_lock`, shared with every other method. |
| `hub_store_factory.py` (new) | efferent 7, avg LCOM 0.5 | `StoreLock`, `OwnerTracker`, `HubClientRegistry`, `DepartureCascade`, `ClientLifecycle`, `HubDisplay`, `Hub`; one constructor and three one-attribute properties. Both are exactly at their caps, which are inclusive. A new file is judged strictly, so this is the one place a refusal is plausible. The fallback is to move the registry, cascade and lifecycle construction back into a `ClientLifecycleFactory` (the file the revert removes), which brings the builder to 5. |
| `store_instance.py` (new) | efferent 2, no class | The factory and `hub`. |
| `ws_listen.py` | avg params up | `display` becomes `lifecycle` and `legs`: constructor 7 → 8. |
| `scene_writer.py`, `callbacks.py`, `scene_deps.py` | avg params up by one | A lifecycle beside the store (or registry) they already take. |

Every "avg params up" row replaces one hidden wide dependency with named ones. I
expect `check-oo` to pass them on the improvement elsewhere in the same files and
have not tried to fit them under a number. Anything that does not pass and is
within cap is the leader's to bless; anything over cap is not, and the fix is a
design change, not a bless.

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

**Left for the leader.** Whether `HubDisplay` should take `HubClientRegistry` only
for `session_of`. The alternative is one new lifecycle method,
`owner_for(connection_id) -> Owner`, which removes `HubDisplay`'s second door
dependency and takes the constructor to four parameters. I did not take it: it adds
a method to the lifecycle for the store's convenience. Say if you want it.

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

**New.** `src/punt_lux/domain/hub/hub_store_factory.py`,
`src/punt_lux/domain/hub/store_instance.py`,
`tests/domain/test_hub_store_factory.py`.

**Changed, domain.** `hub_display.py` (constructor; door members, `_depart`,
`_depart_lapsed` and the singleton out), `client_lifecycle.py` (`exclusive()`),
`hub_reads.py` (`client_sessions` and `_clients` out), `inbox.py`, `lifecycle.py`,
`clients.py`, `replicator_instance.py`, `scene_writer.py`, `lease_reap_sweep.py`
(method name), `domain/hub/__init__.py`.

**Changed, operations and surfaces.** `operations/facade.py`, `scenes.py`,
`scene_deps.py`, `scene_clearing.py`, `pubsub.py`, `callbacks.py`, `identity.py`,
`menu_arming.py`, `menu_arming_deps.py`, `menus.py`, `client_listing.py`,
`client_details.py`, `client_details_port.py`, `frame_owner_facts.py`,
`canonical_frame_owner.py`; `ws_listen.py`, `ws_transport.py`, `luxd.py`,
`hub_composition.py`.

**Tests.** The 44 test files with door sites and the 40 with a `HubDisplay()`
construction (largely the same files); `tests/hub_harness.py`.

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
> `HubClientRegistry` for door reads, `ListenerLegs` for the listener slot. The
> shared `StoreLock` and `OwnerTracker` are created by `HubStoreFactory`, which
> builds the door and then the store over them; process singletons are exported
> by name from `store_instance.py`. A `Protocol` is added only where a real
> dependency direction requires one.
>
> **Rejected.** `HubParts`; forwarding methods; a `ClientDoor` record; one
> `Protocol` per call; a late-bound store.
>
> **Consequences.** Constructors name what they use. The lock order and every
> menu-presence invariant are unchanged. Scene reads, frames, writer and
> quarantine remain on `HubDisplay`; narrowing them, and extracting
> `SceneQuarantine`, are a separate unit.
