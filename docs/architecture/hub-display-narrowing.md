# HubDisplay and the Client Door: Design

**Status:** design, for the leader's review. No code is written by this
document; the implementation write-set is §9.
**Bead:** `lux-ghhf`. Mission `m-2026-10-22-021`; worker `gvr`, evaluator `rmh`.
**Scope (leader ruling, 2026-10-22):** the *client door* only — how a connection
becomes, stays and stops being a Hub client, and who may ask. Narrowing
`HubDisplay`'s scene reads, frame, writer and quarantine forwards (about 370 call
sites) is the Hub store's existing wide-facade debt on `main`. It is a separate
unit and is not designed here, except where it constrains this one (§6, §8).
**Companion models, unchanged by this design:** `docs/menu_presence.tex`,
`docs/menu_presence_locks.tex`, `docs/connection_lease_reaping.tex`.

I read `DESIGN.md` DES-055, 057, 058, 064, 093, 094, 095, 096, 097 and 098 in
full and DES-067's problem and decision, both menu-presence models,
`lease-reap-cascade.md`, and every module named in the contract, before writing
this. I measured call-site counts and metrics from the tree rather than quoting
them (§2, §6).

## Brief

**What this changes.** Today every client-door caller reaches the door through
`HubDisplay`: on this branch as `display.parts.lifecycle.renew(...)`, on `main`
as `display.renew_contact(...)`, `display.clients.session_of(...)` and six more
members. After this change a caller is constructed with the one narrow thing it
uses — a `Protocol` that `ClientLifecycle` or `HubClientRegistry` satisfies — and
`HubDisplay` has no door members at all. The door objects are built once, by a
factory, and handed out by the composition root.

**How it leaves the system better.**

- *Coupling.* Against `main`, `HubDisplay` stops importing the departure
  cascade, the client registry and the `Hub` (efferent 26 → 23, measured), and
  stops being the way a caller reaches a lifecycle it never asked a store about.
  Fifteen source files (§2) stop reaching the door through `HubDisplay` or
  `HubParts`; each names the one capability it calls.
- *Cohesion.* The state-machine step that the menu-presence model proved correct
  — registry write, ownership release, mark, sink, under one store lock — is
  reached through *one* object, so "no caller is trusted to remember" becomes
  true of the call graph and not only of the class. `HubDisplay` keeps what is
  genuinely store coordination (§4.4).
- *Module boundaries.* The seam between the scene store and the client registry
  becomes two small ports (`WriteContact`, `SessionLookup`) instead of a shared
  object graph that both reach into.
- *Testability.* A consumer is unit-tested with a three-line recording fake of its
  port, with no store, no lock and no registry (§4.8).

**Approach chosen.** Interface segregation at the consumer: one `Protocol` per
capability a caller uses, defined once in `domain/hub/client_ports.py`, satisfied
structurally by the objects that already exist. Construction moves out of
`HubDisplay.__new__` into `HubStoreFactory`, a root-confined builder with a guard
test. Process singletons are exported by name, never as a record.

**Rejected** (§7): the `HubParts` bundle; the `StoreLookups` grab-bag; keeping
forwarding methods on `HubDisplay`; a `ClientDoor` record handed to callers; one
fat `ClientContact` port; injecting the raw `StoreLock`.

**Four things the leader must rule before implementation dispatches** (§8): the
`SceneQuarantine` extraction fails the coupling gate on `hub_display.py` as
specified (LCOM 0.74 against a 0.636 baseline), and I give the numbers; whether
`client_sessions` and `client_repos` leave with the door; whether the door owns
its compound critical section (`exclusive()`); and whether a root-confined
builder record is acceptable at all.

## 1. What the door is, and what is not in this unit

The client door is nine operations on a connection's registration and the reads
of the roster:

| Kind | Operation | Today's home (branch tip) |
|---|---|---|
| write | arrive, identify, attach, renew, arm, bind_sink, depart, depart_lapsed, present_as | `ClientLifecycle` (`client_lifecycle.py`) |
| read | session_of, identity_of, named_sessions, live_sessions, repos, `legs` | `HubClientRegistry` (`hub_clients.py`) |
| read | client_sessions | `HubReads.client_sessions` (`hub_reads.py:96`), a pure pass-through to `live_sessions` |

On `main` these are ten public `HubDisplay` members — `register_client`,
`identify_client`, `is_client`, `renew_contact`, `bind_departure_sink`,
`clients`, `drop_connection`, `reap_lapsed_leases`, `client_sessions`,
`client_repos` — and two private helpers, `_depart` and `_depart_lapsed`. The
leader's list names the first eight; I add `client_sessions` and `client_repos`
(§8, D2).

**Not in this unit.** `HubDisplay.reader`, `.frames`, `.dismissal`, `.write_seam`,
`scene_roots`, `resolve`, `owner_of`, `elements_owned_by`, `element_count`,
`scene_owners`, `live_scene_ids`, `all_scene_ids`, the four quarantine members,
`replace_scene`, `show_scene`, `apply`, `write_lock`. These stay on `HubDisplay`
exactly as they are on `main`. Their callers keep calling `display.X(...)`.

## 2. Facts on the ground

Counts are from `81bfb8a5` plus `ccfb474b` (this branch), by grep over `src/` and
`tests/`.

| | Source | Tests |
|---|---|---|
| `.parts.lifecycle` | 16 sites, 11 files | 187 sites, 38 files |
| `.parts.clients` | 12 sites, 7 files | 87 sites, 29 files |
| `reads.client_sessions` | 1 (`client_listing.py:51`) | 12 |
| **Client door total** | **29 sites, 15 files** | **286 sites, 48 files** |
| `.parts.reads/.frames/.reader/.quarantines/.seam/.dismissal`, excluding `client_sessions` (not this unit) | 22 | 350 |
| `HubDisplay()` constructions | 1 (the singleton) | 279 in about 44 files |

The two halves sum to the 687 `.parts.` sites on the branch (51 source, 636 test).
So the door slice is about 315 call sites, not 700. The 279 constructions matter
more than the 286 door sites: the constructor signature changes (§4.5), so every
test that builds a store is touched once, mechanically.

The source sites, by consumer:

- `operations/scenes.py:109` (`arrive`); `pubsub.py:57,87` (`renew`);
  `scene_writer.py:85,118` (`renew`); `identity.py:56,67`;
  `callbacks.py:105,106,110,128`; `menu_arming.py:48,49,52`;
  `menu_arming_deps.py:35` (`present_as`); `frame_owner_facts.py:79`;
  `client_details_port.py:64`; `client_listing.py:51`.
- `ws_listen.py:157,158,199,281` (`write_lock`, `attach`, `identify`,
  `legs.detach`).
- `domain/hub/inbox.py:90,91,95`; `lifecycle.py:39`;
  `replicator_instance.py:43,48,52,60`; `luxd.py:173` (`LeaseReapSweep`).

`HubDisplay.apply` is the only *store* code that touches the door
(`hub_display.py:234,235,238`: `renew`, `depart_lapsed(exclude)`, `session_of`).

Two of the narrow ports I need already exist and are already used the way this
design wants: `LiveSessions` (`callback_ports.py`, taken by `CallbackRouter`,
`MenuEventRouter` and `HubMenuRegistry`) and `LeaseReaper`
(`lease_reap_sweep.py`, taken by `LeaseReapSweep`). `ExpiryFrames`
(`expiry_sweep.py`) shows the same pattern on the frame side. It is house style;
this unit finishes applying it to the door.

## 3. ADRs and models that bound this work

| Entry | What it fixes | Here |
|---|---|---|
| DES-055 One Code Path | Every surface is a thin adapter over one operation; `Operations.for_store` wires "every collaborator injected — no singletons". | **Builds on.** `for_store` takes the lifecycle and registry as explicit arguments; it still reaches no singleton. |
| DES-057 Client Identity | One identity for both legs; leases; `identify` is how identity is recorded. | **Builds on.** `IdentityRecording.identify` is the one recording path for REST and the listen leg. |
| DES-058 / 064 / 067 | The Clients menu is the live roster; an entry exists exactly while its registrant holds a lease; grouping by (repo, session). | **Builds on.** Presence stays lease-filtered and is changed only inside `ClientLifecycle`. |
| DES-093 Display Linkage | The Hub never controls the display process. | Not touched. |
| DES-094 Liveness is a heuristic | Leases reap a dead connection; reaping is not a trust boundary. | **Builds on.** The sweep still calls `depart_lapsed`. |
| DES-095 Facade, not weaker gates | Reconcile complexity and coupling ratchets with a facade; never weaken a gate. | **Builds on.** `HubStoreFactory` and `client_ports.py` are the mediators that keep each module's fan-out honest. |
| DES-096 / 097 Bounded bless | A within-cap, first-edge, tool-computed bless; over-cap and regressing is refused. | **Builds on, and binds** (§6): LCOM above the 0.5 cap is not blessable. |
| DES-098 Unified menu dispatch | One shared `MenuDepartureSink`; a click reaches its owning session. | **Builds on.** The sink is still one shared object seated once. |
| `menu_presence.tex` | Every change to who the Clients menu lists marks the menus and leaves exactly one sink bound, in one step under the store lock; the registry never fires a hook. | **Keeps all of it** (§4.7). |
| `menu_presence_locks.tex` | Store lock, then registry lock; one edge; no cycle. | **Keeps** (§4.7). |
| `connection_lease_reaping.tex` I5, I6 | Departure and ownership release are one event; a live writer is never reaped by its own or another's write. | **Keeps.** `apply`'s prologue is unchanged. |

**Supersedes:** no ADR. It supersedes the *shape* introduced by commit `81bfb8a5`
(`HubParts`, `HubDisplay.parts`) and the pre-`81bfb8a5` shape of door pass-throughs
on `HubDisplay`. §10 drafts DES-101 to record that.

DES-099 and DES-100 (draft/accepted Details and connection-rung work) touch the
Clients menu's *content* and are unaffected.

## 4. Design

### 4.1 Who owns what

| Object | Owns | Locks |
|---|---|---|
| `ClientLifecycle` | Every transition of a connection's registration, one step each: registry write, ownership release, cascade tail, and the presence debt (mark and sink). | Store write lock, then registry lock. |
| `HubClientRegistry` | The sessions, their leases, the roster names, the listen legs. State only: it never calls out of its own lock. | Registry lock. |
| `ClientLifecycleFactory` | Building both of the above over a `Hub` and a clock. Kept from `81bfb8a5`. | n/a |
| `HubStoreFactory` (new) | Building the shared primitives (`StoreLock`, `OwnerTracker`), the door, and the `HubDisplay` over them. | n/a |
| `HubDisplay` | Store coordination (§4.4). **No client member.** | Store lock. |

Nothing else owns a door concern. In particular `MenuPresence` stays a private
detail of `ClientLifecycle`; no consumer sees it.

### 4.2 The ports

One module, `domain/hub/client_ports.py`, defines every door `Protocol` (PY-IC-9).
Each is `runtime_checkable`, as `LiveSessions` and `DirtyMarker` already are, so a
conformance test can assert the real objects satisfy them. A port names what a
*caller* does, not what the provider is.

```python
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.named_sessions import NamedSessions
    from punt_lux.domain.ids import ConnectionId


@runtime_checkable
class Arrival(Protocol):
    """A connection announces itself and renews its lease."""

    def arrive(self, connection_id: ConnectionId) -> None: ...


@runtime_checkable
class ContactRenewal(Protocol):
    """A write is contact: renew the lease iff the caller is registered."""

    def renew(self, connection_id: ConnectionId) -> None: ...


@runtime_checkable
class ClientContact(Arrival, ContactRenewal, Protocol):
    """Show-and-write callers: arrive on a first show, renew on every write."""


@runtime_checkable
class IdentityRecording(Protocol):
    """A connection declares who it is."""

    def identify(self, connection_id: ConnectionId, identity: ClientIdentity) -> None: ...


@runtime_checkable
class ListenLegLifecycle(IdentityRecording, Protocol):
    """The listen leg's two lifecycle calls, and the critical section it needs."""

    def attach(
        self, connection_id: ConnectionId, identity: ClientIdentity,
        listener: CallbackListener,
    ) -> None: ...

    def exclusive(self) -> AbstractContextManager[bool]: ...


@runtime_checkable
class MenuArmingContact(ContactRenewal, Protocol):
    """Admission to own a menu bar: renew, then bind the shared menu sink."""

    def arm(self, connection_id: ConnectionId) -> None: ...


@runtime_checkable
class Departure(Protocol):
    """A graceful disconnect: deregister, release, run the cascade tail."""

    def depart(self, connection_id: ConnectionId) -> None: ...


@runtime_checkable
class WriteContact(ContactRenewal, Protocol):
    """What a store write owes the door before it checks ownership (I6)."""

    def depart_lapsed(
        self, exclude: frozenset[ConnectionId] = frozenset()
    ) -> frozenset[ConnectionId]: ...


@runtime_checkable
class IdentityLookup(Protocol):
    def identity_of(self, connection_id: ConnectionId) -> ClientIdentity | None: ...


@runtime_checkable
class SessionLookup(Protocol):
    def session_of(self, connection_id: ConnectionId) -> ClientSession | None: ...


@runtime_checkable
class NamedSessionSource(Protocol):
    def named_sessions(self) -> NamedSessions: ...
```

`LiveSessions` and `LeaseReaper` already exist and are reused unchanged. Eleven
public names, under the 15-name cap. The module imports only under
`TYPE_CHECKING`, so its efferent coupling is 0.

`ClientLifecycle` satisfies `Arrival`, `ContactRenewal`, `ClientContact`,
`IdentityRecording`, `ListenLegLifecycle`, `MenuArmingContact`, `Departure`,
`WriteContact` and `LeaseReaper`. That is interface segregation working as
intended: the provider is wide, each client sees one slice. It requires exactly
one new method on the provider, `exclusive()` (D3, §8), and no other change to
`client_lifecycle.py`.

`HubClientRegistry` satisfies `IdentityLookup`, `SessionLookup`,
`NamedSessionSource` and `LiveSessions`.

Concrete types are taken directly where the provider is already single-purpose,
and a `Protocol` would only restate it: `ListenerLegs` (the registry's listener-slot
view) is taken as itself by `CallbackOperations` and `HubListenSession`.

### 4.3 Who is given which port

| Consumer | Today | Constructor takes | Satisfied by |
|---|---|---|---|
| `SceneOperations`, `SceneClearer` | `parts.lifecycle.arrive/renew` | `ClientContact` (via `SceneOperationsDeps`) | lifecycle |
| `HubSceneWriter` | `parts.lifecycle.renew` ×2 | `ContactRenewal` beside its store | lifecycle |
| `PubSubOperations` | `parts.lifecycle.renew` ×2 | `ContactRenewal` | lifecycle |
| `CallbackOperations` | renew; `parts.clients.legs.*`; `named_sessions` | `ContactRenewal`, `ListenerLegs`, `NamedSessionSource` | lifecycle, `clients.legs`, clients |
| `IdentityOperations` | `identify`; `session_of` | `IdentityRecording`, `IdentityLookup` | lifecycle, clients |
| `MenuArming` | renew, `identity_of`, arm | `MenuArmingContact`, `IdentityLookup` | lifecycle, clients |
| `MenuOperationsDeps.write_lock` | `display.write_lock` | `lifecycle.exclusive` (a callable, as now) | lifecycle |
| `HubListenSession` | `write_lock`, `attach`, `identify`, `legs.detach` | `ListenLegLifecycle`, `ListenerLegs` | lifecycle, `clients.legs` |
| `HubListenTransport` | `HubDisplay` | the same two, to hand on | root |
| `inbox.ensure_writer` | `hub_display.write_lock`, `parts.lifecycle.arrive/bind_sink` | module name `hub_lifecycle` | lifecycle |
| `lifecycle.disconnect_connection` | `parts.lifecycle.depart` | `Departure` (default `hub_lifecycle`) | lifecycle |
| `LeaseReapSweep` (luxd) | `parts.lifecycle` | `LeaseReaper` (exists) | lifecycle |
| `HubMenuRegistry`, `CallbackRouter`, `MenuEventRouter` | `parts.clients` | `LiveSessions` (exists) | clients |
| `CallbackMenuReplica` | `parts.clients` | `NamedSessionSource` | clients |
| `FrameOwnerFacts`, `ClientDetailsOperations` | `parts.clients.named_sessions` | `NamedSessionSource` | clients |
| `ClientListing` | `parts.reads.client_sessions` | `LiveSessions` | clients |
| `HubDisplay` (`apply`) | `lifecycle`, `clients` it built itself | `WriteContact`, `SessionLookup` | lifecycle, clients |

Where a consumer needs two ports, the two arrive as two constructor arguments. It
is not folded into a combined type, because the two come from different providers
and combining them would invent a class with no owner (§7, R5).

`IdentityOperations.current` today asks `session_of` for a whole session and
extracts `.identity`; it will ask `identity_of`. Same answer (`identity_of` is
`sessions.get(c, ANONYMOUS).identity`, a single atomic dict read), one fewer
object in the caller's hands. That is the only place this design changes a call
rather than the object it is made on.

### 4.4 What `HubDisplay` still owns, and why

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

Those four, plus the scene-side forwards that stay on it by §1, are all
`HubDisplay` is. It depends on the door through exactly two ports, both read at the
head of `apply`:

```python
def __new__(
    cls,
    lock: StoreLock,
    owners: OwnerTracker,
    contact: WriteContact,
    sessions: SessionLookup,
    clock: Callable[[], float] = time.monotonic,
) -> Self:
    ...

def apply(self, connection_id, update):
    with self._lock.write():
        self._contact.renew(connection_id)
        self._contact.depart_lapsed(frozenset({connection_id}))
        match update:
            case AddElement(scene_id=sid, parent_id=pid, element=elem):
                owner = Owner.from_session(connection_id, self._sessions.session_of(connection_id))
                ...
```

`lock` and `owners` are the two primitives the store and the lifecycle *share*
(the lifecycle releases ownership under the same lock the store mutates under).
Being shared, neither can be created by one side; the factory creates them and
gives both sides the same instance. This is the only reason the constructor grows
from two parameters to five.

`HubDisplay` loses: `register_client`, `identify_client`, `is_client`,
`renew_contact`, `bind_departure_sink`, `clients`, `drop_connection`,
`reap_lapsed_leases`, `_depart`, `_depart_lapsed`, `client_repos`, and (D2)
`client_sessions`. It no longer imports `DepartureCascade`, `HubClientRegistry`
or `Hub`.

### 4.5 The composition root

```python
# domain/hub/hub_store_factory.py
@final
class HubStoreFactory:
    """Builds the shared primitives, the client door, and the store over them."""

    def __new__(cls, hub: Hub = default_hub, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        lock = StoreLock()
        owners = OwnerTracker()
        door = ClientLifecycleFactory(hub, clock)
        self._lifecycle = door.build(owners, lock)
        self._clients = door.registry
        self._display = HubDisplay(lock, owners, self._lifecycle, self._clients, clock)
        return self

    @property
    def display(self) -> HubDisplay: ...
    @property
    def lifecycle(self) -> ClientLifecycle: ...
    @property
    def clients(self) -> HubClientRegistry: ...
```

Three members, each a different object a root hands to a different consumer. It
imports `StoreLock`, `OwnerTracker`, `ClientLifecycleFactory`, `HubDisplay` and
the default `Hub` at runtime: efferent 5.

**Why this is not `HubParts`.** `HubParts` was reachable from every consumer
(`display.parts`) and carried eight collaborators; consumers chose a field at each
call. `HubStoreFactory` is reachable from *nothing*: `HubDisplay` has no reference
to it, no class stores one, and no constructor or `for_store` signature mentions
its type. It is read exactly once per process, in `store_instance.py`, where its
three properties are unpacked into three module names. A guard test (§4.8) makes
that a failing build rather than a convention. Tests use it as their composition
root, which is what a test of the real wiring should do.

The factory's defaults (`hub=default_hub`, `clock=time.monotonic`) mirror the
defaults `HubDisplay.__new__` has today, so the 279 test constructions rewrite
mechanically: `HubDisplay()` → `HubStoreFactory().display`.

**Process singletons** — new `domain/hub/store_instance.py`, in the house style of
`replicator_instance.py` and `details_instance.py`:

```python
_store = HubStoreFactory(hub)
hub_display: HubDisplay = _store.display
hub_lifecycle: ClientLifecycle = _store.lifecycle
hub_clients: HubClientRegistry = _store.clients
```

`_store` is module-private. `domain/hub/__init__.py` re-exports the three names;
`hub_display.py` no longer defines a singleton. The four modules that import the
singleton from `hub_display.py` (`clients.py:15`, `inbox.py:18`, `lifecycle.py:17`,
`replicator_instance.py:22`) import the specific name they use from
`store_instance`.

**Roots that hand ports on** (the only places that name the singletons):

- `hub_composition.py` — `HubComposition.operations()` passes `hub_lifecycle` and
  `hub_clients` to `Operations.for_store` and the Details/frame-owner recipes.
  Nothing under `operations/` reaches a singleton, as its docstring requires.
- `replicator_instance.py` — builds `HubMenuRegistry`, `CallbackRouter`,
  `MenuEventRouter` and `CallbackMenuReplica` over `hub_clients`.
- `ws_transport.py` — `HubListenTransport.for_hub()` over `hub_lifecycle` and
  `hub_clients.legs`.
- `luxd.py:173` — `LeaseReapSweep(hub_lifecycle)`.

**`Operations.for_store`** gains two keyword arguments, `lifecycle` and `clients`.
It also seats the production menu sink — `lifecycle.present_as(replicator,
MenuDepartureSink(menu_registry, replicator))` — visibly, as its first statement.
Today that mutation hides inside `MenuArmingDeps.over` (`menu_arming_deps.py:35`),
a "deps" constructor with a side effect on a shared object. Moving it into
`for_store` changes no behaviour (the same call, once, before serving) and lets
`MenuArmingDeps` become the plain dataclass its name says it is. The model's
invariant, that presence is silent until seated, is unchanged.

### 4.6 The back-edge, and construction order

`apply` is called back by an installed element: a scene-root's observer fires
`RootRemovalRouter.route`, which calls `HubDisplay.apply`. That cycle exists
today and stays inside `HubDisplay.__new__` (the router is built over
`self.apply`, as now). Nothing about the door joins it: `HubDisplay` is constructed
*after* the lifecycle, and the lifecycle never reaches the store except through
the `StoreLock` and `OwnerTracker` it was handed.

Construction order is therefore: `StoreLock`, `OwnerTracker`, registry and cascade
(`ClientLifecycleFactory`), `ClientLifecycle`, `HubDisplay`. No late binding, no
setter, no mutable wiring on the path.

### 4.7 Invariants kept, and how

1. **One step per presence change** (`menu_presence.tex` P1, P2). Every
   presence-changing registry write — `record`, `renew_if_registered`,
   `attach`, `discard`, `reap_lapsed_locked` — is called only from `ClientLifecycle`
   methods. After this change a consumer cannot call one: the ports expose lifecycle
   *verbs* and registry *reads*, never registry writes. The two registry writers
   outside the lifecycle today are `ListenerLegs.register_callback` and `.detach`;
   they are unchanged (the Observation in §8).
2. **The registry never fires a hook.** Untouched: `HubClientRegistry` imports
   nothing new and still returns a `PresenceChange` for the caller, inside its own
   lock, to pay.
3. **Store-then-registry lock order** (`menu_presence_locks.tex`). Each
   lifecycle method takes the store write lock first, then the registry's.
   Registry reads take the registry lock alone. No port hands out the registry
   lock. `exclusive()` returns the *store* lock; a caller that holds it and then
   calls the lifecycle or a registry read only ever adds the registry edge after the
   store edge. `HubDisplay.apply` calls `contact.renew` and `contact.depart_lapsed`
   while already holding the store lock, exactly as it does now. The one edge
   DES-098 D3 added, store lock → `HubMenuRegistry._lock` (`set_menu` holds the
   store lock across admit and store, `menu_lifecycle.tex`), is unchanged:
   `MenuOperationsDeps.write_lock` becomes `lifecycle.exclusive`, the same
   `StoreLock`. The acquisition graph keeps its edges and gains none, so the
   deadlock proofs stand without re-running.
4. **A write is contact before ownership** (I6). The prologue of `apply` is
   unchanged and still precedes the match.
5. **One shared departure sink.** `present_as` is called once, in
   `Operations.for_store`; `arm` and `bind_sink` remain idempotent under the
   cascade's equality dedup.
6. **No singleton in `operations/`** (DES-055). Strengthened: the lifecycle and
   registry arrive as arguments, and a test can build the whole engine from fakes.

No model changes. I add no state and no transition; `exclusive()` is the lock the
lifecycle already takes in every method. If the Observation in §8 is taken up
later, it extends the model first.

### 4.8 Tests, and how they get the same wiring

**Unit tests of a consumer** pass a recording fake of its port. For example:

```python
@dataclass
class RecordingContact:
    renewed: list[ConnectionId] = field(default_factory=list)

    def renew(self, connection_id: ConnectionId) -> None:
        self.renewed.append(connection_id)


def test_publish_renews_the_caller() -> None:
    contact = RecordingContact()
    PubSubOperations(hub, contact, ports).publish("t", request, scope=scope)
    assert contact.renewed == [scope.connection_id]
```

`PubSubOperations`, `IdentityOperations`, `MenuArming`, `ClientListing`,
`CallbackMenuReplica`, `FrameOwnerFacts`, `ClientDetailsOperations`, `LeaseReapSweep`
and `disconnect_connection` need no store at all. This is where the 286 door
sites mostly go: tests that built a store only to reach a door.

**Wiring tests** (store, door and writes together: apply renews and sweeps, a
departure empties the registry and releases ownership, the menu mark and sink fire
once) use `HubStoreFactory(hub, clock).{display,lifecycle,clients}`. The factory is
the test's composition root; a test takes only the property it uses. The fixture
helper `tests/hub_harness.py::IsolatedHub` is rebuilt over the factory and
monkeypatches the three `store_instance` names instead of one.

**Conformance:** `tests/domain/test_client_ports.py` asserts, per port, that the
real lifecycle or registry is an `isinstance`. A method renamed on the provider
fails here before it fails at a call site.

**Confinement guard:** `tests/domain/test_store_confinement.py` is an AST scan of
`src/` (the repo already guards structure this way: `tests/test_per_frame_tracing.py`,
the `DisplayLink` construction guard). It fails if (a) any `src` module other than
`store_instance.py` imports `HubStoreFactory`; (b) any `src` module defines an
attribute, parameter or return annotated `HubStoreFactory`; (c) `HubDisplay` has
an attribute named `lifecycle`, `clients` or `parts`; (d) `HubParts` exists.

`tests/domain/test_hub_parts.py` is deleted in step M7; its five cases move to the
factory's wiring tests.

## 5. Migration

Nine commits (M1–M8, with M7 in two parts), each passing `make check`, each wiring
every caller in the same commit and deleting the path it replaces (PY-RF-2). Tests lead: in each
step the consumer's test moves first to the port-shaped construction it will have,
then the consumer. A step that moves a constructor signature updates its
`for_store` root and its tests in that commit.

| Step | Commit | Callers moved | Size |
|---|---|---|---|
| **M1** | Restore the scene side. `HubDisplay` regains `scene_roots`, `resolve`, `owner_of`, `elements_owned_by`, `element_count`, `scene_owners`, `live_scene_ids`, `all_scene_ids`, `reader`, `frames`, `dismissal`, `write_seam` and the four quarantine members; `HubParts` shrinks to `lifecycle` and `clients`. | 22 source, 350 test sites, `display.parts.X.m` → `display.m` | mechanical |
| **M2** | `client_ports.py` with `Arrival`, `ContactRenewal`, `ClientContact`; scenes, scene clearing, writer, pub/sub. | 6 source files | small |
| **M3** | `IdentityRecording`, `IdentityLookup`, `MenuArmingContact`; add `ClientLifecycle.exclusive()`; identity, menu arming, `MenuOperationsDeps`; the explicit `present_as` seat in `for_store`. | 7 source files | small |
| **M4** | `ListenLegLifecycle`; `HubListenSession`, `HubListenTransport`. | 2 source files | small |
| **M5** | `NamedSessionSource`; `CallbackOperations` + `ListenerLegs`, `CallbackMenuReplica`, `FrameOwnerFacts`, `ClientDetailsOperations`, `ClientListing`; delete `HubReads.client_sessions` and its registry reference (D2). | 6 source files | small |
| **M6** | `Departure`; `disconnect_connection`, `inbox.ensure_writer`, `LeaseReapSweep` wiring in `luxd.py`. | 3 source files | small |
| **M7a** | Tests only: every test that builds a store does so through one helper that, for now, wraps `HubDisplay()` and `display.parts`. `HubDisplay()` → helper; `display.parts.lifecycle/clients` → helper properties. Per-directory commits. | 279 + 286 test sites | mechanical |
| **M7b** | The flip: `HubStoreFactory`, `store_instance`, new `HubDisplay.__new__`, `WriteContact`/`SessionLookup`; the helper is re-implemented over the factory (a few lines); delete `HubParts`, `HubDisplay.parts`; roots read the singletons. | 1 source module of substance, 8 roots | medium |
| **M8** | Guards and docs: the two guard tests, DES-101, `system.tex`'s `HubDisplay` section. | docs, 2 tests | small |

M7a before M7b is deliberate: it removes the 565-site test churn from the commit
that changes the constructor, so the flip reviews as one small source change and a
helper edit. Through M2–M6 the roots still read `display.parts.lifecycle` and
`.clients`; that, and `HubParts`'s two fields, are the transitional scaffold M7b
deletes. They are not a shim: no consumer survives on them past its own step.

**Trap in M1.** `main` names the replicable-scenes read `live_scene_ids` and the
all-scenes read `all_scene_ids`; this branch renamed them
`SceneReader.replicable_scene_ids` and `SceneReader.live_scene_ids`. M1 must keep
`main`'s two names *and meanings* on `HubDisplay`, as one-line forwards
(`live_scene_ids` → `replicable_scene_ids`, `all_scene_ids` → the reader's
`live_scene_ids`), or callers silently swap semantics. `SceneReader.replicable_scene_ids`
is one of the contract's kept pieces and survives.

## 6. Metrics

Signals, never targets. Measured with the `oo_coupling.py` definitions (LCOM over
`self._*` attribute sets per method pair; efferent over top-level `punt_lux`
imports) on the real `main` source, and on a model of the post-change class. My
re-implementation reproduces `main`'s 0.636 exactly. It gives 0.737 for
`0df928c7`, where the leader quoted 0.766; the 0.766 may be a later tree state, and
the gap does not change any conclusion below.

For `hub_display.py`:

| | `main` | tip (`81bfb8a5`) | door out only | door out + `SceneQuarantine`, forwards kept |
|---|---|---|---|---|
| avg LCOM | 0.636 | 0.267 (6 methods) | **0.606** | **0.738** |
| efferent coupling | 26 | 25 | **23** | 23 |
| lines | 466 | 259 | ≈ 385 | ≈ 365 |
| public names | 5 | 5 | 5 | 5 |

- *LCOM.* The door's methods shared `_lock` and `_clients` with each other and with
  `apply`, so they were holding the pass-through methods' LCOM down. Removing
  them *alone* gives 0.606: better than `main`. Extracting `SceneQuarantine` while
  `HubDisplay` keeps four forwarders to it removes the `_lock` those four shared
  with the rest and gives 0.738, which regresses against 0.636 and is over the 0.5
  cap, so DES-096/097 refuse to bless it. This is the reverse of what the
  extraction is for, and I report it as D1 (§8) rather than choose. The 0.267 at
  the tip is not an improvement to preserve: it came from deleting every
  forwarder, which is the call-site churn M1 reverses and the follow-on unit
  would redo, by narrowing the callers instead.
- *Efferent.* −3: `departure_cascade`, `hub_clients`, `hub`. The file stays far
  over the cap of 7 because it still constructs the scene collaborators; that is
  `main`'s debt, not regressed.
- *Parameters.* `HubDisplay.__new__` goes from 2 to 5 parameters (§4.4). That
  raises avg parameters on the file; deleting twelve one- and two-parameter door
  forwards offsets part of it. Not measured, since `oo_score` needs the code. The
  five are exactly the dependencies the old signature hid.

Other files, expected direction and why:

| File | Expected | Why |
|---|---|---|
| `hub_reads.py` | avg LCOM down | `client_sessions` was the only method using `_clients`, disjoint from every other; it leaves with the field. |
| `client_lifecycle.py` | unchanged-to-flat | `exclusive()` touches `_lock`, shared with every other method. |
| `client_ports.py` (new) | efferent 0, public names 11 | `Protocol`s are exempt from LCOM. |
| `hub_store_factory.py` (new) | efferent 5 | A builder is a mediator (DES-095). |
| `store_instance.py` (new) | efferent 2 | The factory and `hub`. |
| `ws_listen.py` | avg params up | `display` becomes `lifecycle` + `legs`: constructor 7 → 8 parameters. |
| `scene_writer.py`, `scene_deps.py`, `callbacks.py` | avg params up by one | A new port beside the store they already take. |
| `scenes.py` (`SceneOperations`) | none | The port rides in `SceneOperationsDeps`, already a parameter object. |

Every "avg params up" row replaces one hidden wide dependency with named ones. I
expect check-oo to pass them on the improvement elsewhere in the same files and
have not tried to fit them under a number. Anything that does not pass and is
within cap is the leader's to bless; anything over cap is not, and the fix is a
design change, not a bless.

## 7. Alternatives rejected

**R1. `HubParts` / `HubDisplay.parts`.** A record of eight collaborators reachable
from the facade. It dropped one metric by moving the fan-out into the consumers,
which then reach through the bundle — `display.parts.lifecycle.renew(...)` is two
hops where the caller needs one, and it fixes none of the dependencies: a
`PubSubOperations` still cannot be built without a store that has a lifecycle, a
frame authority, a reader and four more. Rejected by the leader and the operator;
agreed. It is a service locator, so Demeter and interface segregation are both
violated at every call.

**R2. `StoreLookups` (and any grab-bag of reads).** An earlier bundle of lookups
over the store, retired to `.tmp/retired/store_lookups.py`. Same defect as R1 in a
smaller size: a class whose methods are chosen by the *provider's* shape, not by
what any caller needs. Not applicable to the door, where the providers are already
small cohesive classes.

**R3. Keep forwarding methods on `HubDisplay`.** Ten one-line methods that each
call `self._lifecycle.x(...)`. Callers stay unchanged, which is the appeal. But
that is the wide-facade shape that drove LCOM from 0.636 to 0.766: each forwarder
touches one private attribute disjoint from the rest. It also leaves `HubDisplay`
as the thing every consumer's constructor names.

**R4. A `ClientDoor` record (`lifecycle`, `registry`) handed to consumers.**
Smaller and more cohesive than `HubParts`, but a consumer holding it must still
choose a field per call, and a consumer that needs one field would be given two.
The record would be reached through, which is R1.

**R5. One fat `ClientContact` port.** `arrive`, `renew`, `identify`, `arm`,
`attach`, `depart` and the rest in one `Protocol`. Equivalent to taking
`ClientLifecycle` itself, and no more testable: every fake implements nine
methods. The small ports cost one line each and let a fake be one method long.

**R6. Inject the raw `StoreLock` (a `StoreWriteLock` port) into `ws_listen`,
`inbox` and menus.** Possible, and it removes `exclusive()` from the lifecycle. It
makes three more consumers hold the store-wide lock as an independent object, and
the compound steps they run — attach plus bind a writer; arrive plus bind a sink
plus inbox — are client-registration steps that the model already treats as the
lifecycle's. See D3.

**R7. Late-bound wiring (a `bind(display)` step).** Tempting because `HubDisplay`
and the door look mutually dependent. They are not: the door depends on the lock
and owners, not on the store, so construction order is acyclic (§4.6). No late
binding is needed, and none is introduced.

**R8. `HubDisplay` takes the factory.** `HubDisplay(factory)` would restore the
two-parameter constructor. It also makes the store depend on its own builder and
hides the five real dependencies again.

## 8. Decisions for the leader

**D1. `SceneQuarantine` extraction against the coupling gate.** As instructed,
`SceneQuarantine` stays extracted and `HubDisplay` keeps the four quarantine
members. That configuration gives `hub_display.py` avg LCOM ≈ 0.738 against a
0.636 baseline. Since it is over the 0.5 cap and a regression, the bless refuses
it; the PR fails `check-coupling` on this file. The options and their measured
LCOM:

| | Option | avg LCOM |
|---|---|---|
| Q-A | Extracted; `HubDisplay` keeps four forwards (as instructed) | 0.738 |
| Q-B | Extracted; its 2 source and ~39 test call sites hold it directly; `HubDisplay` drops the forwards | ≈ 0.70 (reference model: 17 methods) |
| **Q-C** | **Do not extract in this unit.** `HubDisplay` keeps the inline registry, observers and `_lift_quarantine` as on `main`; `scene_quarantine.py` rides with the follow-on that narrows quarantine's call sites | **0.606** |
| Q-D | Extracted, and `HubDisplay` forwards under its own `self._lock` as `main` does | ≈ 0.606 |

Q-D is rejected: it reads the lock into forwarders that `SceneQuarantine` already
locks, only to share an attribute. That games the metric; the redundancy is the
signal the metric is giving. Q-B is the better design and still fails the gate; it
belongs to the follow-on unit with the rest of the read narrowing. **I recommend
Q-C.** It is the only option under which this PR passes without a design change to
unrelated code, and the extraction loses nothing by waiting: its benefit is
realised only when callers hold it. The design in §4 is written to hold under any
of the four; only the body of `HubDisplay`'s quarantine members differs.

Q-C has a cost the leader should see before ruling: `SceneReader.replicable_scene_ids`
reads quarantined ids from `SceneQuarantine`. Without the extraction it is
withdrawn with it, and `HubDisplay.live_scene_ids` computes the replicable set
inline as it does on `main`. Q-C therefore defers two of the contract's four kept
pieces, not one. Both come back, with their callers, in the follow-on.

**D2. `client_sessions` and `client_repos` leave `HubDisplay` with the door.** They
are registry reads, not store reads. `client_repos` has no source caller on
`main` or here (dead); `client_sessions` has one (`ClientListing`), which takes
`LiveSessions`. Leaving them would force `HubDisplay` to keep a registry
reference solely to forward two reads. **I recommend removing both** and deleting
`HubReads.client_sessions`.

**D3. The door owns its compound critical section: `ClientLifecycle.exclusive()`.**
`ws_listen`, `inbox.ensure_writer` and menu arming each hold the store lock across
a door step plus a Hub writer or inbox step so a departure cannot interleave.
Today they take it from `HubDisplay.write_lock`, which would leave all three
depending on `HubDisplay` for nothing but a lock. `exclusive()` returns the same
reentrant `StoreLock`, adds no edge to the lock graph, and is the lock the
lifecycle's own methods already take. Alternative: R6. **I recommend
`exclusive()`.**

**D4. `HubStoreFactory` as the one root-confined record.** It is the only
multi-member object in the design. §4.5 explains why it is not `HubParts`, and
the confinement guard makes that checkable. The alternative with no record at all
is module-level wiring in `store_instance.py` and a hand-copy of the same wiring
in the test helper; I rejected it because a test that re-types production wiring
tests the re-typing. If the operator will not accept a root-confined record under
any name, say so and I will redesign around that constraint.

**Observation (not a decision).** `ListenerLegs.register_callback`
(`callbacks.py:110`) and `ListenerLegs.detach` (`ws_listen.py:281`) change who the
Clients menu lists but are performed *outside* `ClientLifecycle`, with the mark
raised by the caller (`callbacks.py:123`, `ws_listen.py:283`). That is the
"caller is trusted to remember" shape `menu_presence.tex` exists to remove.
`menu_presence.tex:133-135` elides the callback route as "the same obligation on a
different transition". I leave both as they are: moving them is a change to the
verified model and should extend the model first. They are why `ListenerLegs`
survives in the ports table as a concrete handle. I recommend a bead.

## 9. Implementation write-set

The design names it; the implementation mission's contract should list these.

**New.** `src/punt_lux/domain/hub/client_ports.py`,
`src/punt_lux/domain/hub/hub_store_factory.py`,
`src/punt_lux/domain/hub/store_instance.py`,
`tests/domain/test_client_ports.py`, `tests/domain/test_hub_store_factory.py`,
`tests/domain/test_store_confinement.py`.

**Changed, domain.** `hub_display.py` (constructor, door members out, singleton
out), `client_lifecycle.py` (`exclusive()`), `hub_reads.py`
(`client_sessions` and `_clients` out), `client_lifecycle_factory.py` (unchanged
interface; confirm), `inbox.py`, `lifecycle.py`, `clients.py`,
`replicator_instance.py`, `callback_menu.py`, `scene_writer.py`,
`domain/hub/__init__.py`. Deleted: `hub_parts.py`.

**Changed, operations and surfaces.** `operations/facade.py`, `scenes.py`,
`scene_deps.py`, `scene_clearing.py`, `pubsub.py`, `callbacks.py`, `identity.py`,
`menu_arming.py`, `menu_arming_deps.py`, `menus.py`, `client_listing.py`,
`client_details.py`, `client_details_port.py`, `frame_owner_facts.py`,
`canonical_frame_owner.py`; `ws_listen.py`, `ws_transport.py`, `luxd.py`,
`hub_composition.py`.

**Tests.** The 48 test files that match `parts\.(lifecycle|clients)` or
`reads\.client_sessions` under `tests/`, `tests/hub_harness.py`, and the files
with a `HubDisplay()` construction (about 44, mostly the same files).
`tests/domain/test_hub_parts.py` is deleted.

**Docs.** `DESIGN.md` (DES-101), `docs/architecture/system.tex` (the
`HubDisplay` store section, lines 416 onward), this document's status line.
`CHANGELOG.md`: none; the change is internal and not user-visible.

## 10. Draft DES-101

> **DES-101: The client door is a lifecycle callers hold, not a store they ask.**
>
> **Context.** The menu-presence fix made every change to who the Clients menu
> lists one `ClientLifecycle` step. `HubDisplay` still fronted it: ten
> forwarding members on `main`, then a `HubParts` bundle reached through the
> facade. Both leave every caller depending on the store for a capability it does
> not own, and the first drove `hub_display.py`'s avg LCOM from 0.636 to 0.766.
>
> **Decision.** `HubDisplay` has no client member. A caller is constructed with
> the narrow `Protocol` it uses (`client_ports.py`), satisfied structurally by
> `ClientLifecycle` or `HubClientRegistry`. The shared `StoreLock` and
> `OwnerTracker` are created by `HubStoreFactory`, which builds the door and then
> the store over them; the factory is confined to `store_instance.py` and to
> tests by a guard. Process singletons are exported by name.
>
> **Rejected.** `HubParts`; forwarding methods; a `ClientDoor` record; one fat
> port; a late-bound store.
>
> **Consequences.** Constructors name what they use. The lock order and every
> menu-presence invariant are unchanged. Scene reads, frames, writer and
> quarantine remain on `HubDisplay`; narrowing them is a separate unit.
