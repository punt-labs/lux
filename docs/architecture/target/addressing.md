# Lux Target Addressing Model

**Status:** canonical target for identity and multi-Hub aggregation.
**Ratifies:** DES-089 ("identity is a path") in `DESIGN.md`.

Start with [target.md](./target.md). This document is a sibling to
[ui-model.md](./ui-model.md) (what the UI objects are) and
[topology.md](./topology.md) (how the processes connect). It answers a
question those two do not: when the Display renders something it did not
produce, how is that thing identified — uniquely enough that ImGui never
collides, legibly enough that a human can tell two things apart, and safely
enough that two producers' content can never silently overwrite one
another?

## Problem

The Display is an aggregator. It renders content it did not create, from
producers it does not control, and — per [topology.md](./topology.md) — from
a Hub that may itself aggregate many agents and many users. Today it
aggregates from exactly one Hub connection in practice, but nothing in the
transport enforces that, and the operator has ruled that supporting more
than one Hub is in scope now, not a reserved-and-deferred dimension.

Two things go wrong when a lower layer's identity is used, unqualified, at a
higher layer that can see more than one of that lower layer:

1. **A visible collision.** Dear ImGui raises "N visible items with
   conflicting ID" when two rendered widgets share a label, because ImGui
   uses the label as both display text and identity unless told otherwise.
   Four session panels all titled "Vox" collide the moment a second one
   exists (`lux-whb9`).
2. **A silent collision.** This is the sharper failure, and it is not
   hypothetical — it already happened once, at the layer below this one.
   `HubDisplay` used to store every scene and frame under the literal string
   a client submitted; two connections choosing the same `scene_id` did not
   error, the second silently evicted the first's root (DES-086,
   `lux-ledm`, CHANGELOG 0.25.0). The fix was `ConnectionScopedId`: compose
   the store key from the writing connection's own id, so collision becomes
   unrepresentable rather than merely checked.

The Display's own storage has the identical shape of bug, one layer up, and
it is live in the tree today. `FrameBook` (`display/replica/frame_book.py`)
holds `_scene_to_frame: dict[str, str]` and `_scene_to_owner: dict[str,
int]` — flat dictionaries keyed by the bare Rung-2 scene id string, spanning
every connection the Display has ever seen. `MenuReplica`
(`display/replica/menu_replica.py`) holds `_callback_menus: tuple[WireMenu,
...]`, replaced wholesale on every push. Neither carries a dimension for
"which Hub sent this." `ConnectionId` (`connection_identity.py`) is a
deterministic hash of a client's *self-declared* fields, computed
independently by each Hub process with no cross-Hub coordination — two
different Hubs can and eventually will mint the identical `ConnectionId`
for two different real clients. The day a second Hub connects, its scene
push can silently clobber the first Hub's scene under the identical key,
by the same mechanism DES-086 already found and fixed once. This document
closes that gap before it ships, not after a user finds it.

## Core concept: identity is a path

Each layer that aggregates content knows only what it itself produced. Only
the layer *above* a given aggregator can see that there might be more than
one of it. An applet knows its own label and nothing else; a Hub knows its
own live connections and nothing about other Hubs; the Display is the one
layer that can see more than one Hub. The consequence is structural, not a
style preference: **each layer must namespace what is below it, blind to
what is above it.** Applied recursively down the stack, an item's true
identity is not a label — it is the path from the outermost aggregator that
can see it, down to the producer's own name for it. That is DES-089's
governing phrase, and this document is its full specification.

## The ladder

Three rungs exist. The first two are already shipped, in two different
mechanisms that share one shape. The third does not exist in code today —
it is the subject of this design.

```text
Rung 1 — Producer label            unscoped, freely reused
  "Vox", "Beads", "music-player"
        │
        │  namespaced by the Hub that owns the connection (DES-058, DES-086)
        ▼
Rung 2 — Hub-connection scope       unique within ONE Hub's own registry
  ConnectionScopedId / CallbackInvocation: {connection_id}\x1f{local_id}
        │
        │  namespaced by the Display, across every Hub it holds (THIS DOC)
        ▼
Rung 3 — Hub-of-origin scope         unique across every Hub the Display holds
  LuxAddress: {hub}\x1f{connection_id}\x1f{local_id}
```

| Rung | Owned by | Scope of uniqueness | Shipped mechanism |
|---|---|---|---|
| 1. Producer label | The applet/agent itself | None — every producer may reuse any string | `register_callback(id, label)`; a caller's `scene_id`/`frame_id` |
| 2. Hub-connection scope | The Hub, over its own live connections | Unique within **one** Hub process's registry, not globally | `ConnectionScopedId` (scenes/frames, DES-086); `CallbackInvocation` (menu leaves, DES-058) |
| 3. Hub-of-origin scope | The Display, over every Hub it holds | Unique across every Hub connection the Display currently holds | **Does not exist.** This document specifies it. |

Rung 2's own scope claim is the load-bearing fact this document rests on:
`ConnectionId` is computed *independently, per Hub process*, from fields the
client declares to that Hub. Nothing makes it globally unique — it is not
supposed to be, because a single Hub has no way to know about, let alone
coordinate with, any other Hub. That is exactly why Rung 3 must exist: the
one layer that *can* see more than one Hub is the one layer obligated to
disambiguate them.

## Value types

Identity is an object, not a concatenated string. Two small value classes
compose into the one type that answers "what is this, uniquely and
legibly": `Rung` (one level's key and label) and `LuxAddress` (the three
rungs, composed).

```python
@final
@dataclass(frozen=True, slots=True)
class Rung:
    """One level of a LuxAddress: a stable uniqueness key and a human label.

    ``key`` is opaque and never elided from the hidden id — two Rungs with
    the same ``key`` are the same thing by construction. ``label`` is what a
    human reads, and is shown only when this rung's ambiguity requires it.
    """

    key: str
    label: str


@final
@dataclass(frozen=True, slots=True)
class LuxAddress:
    """The Display's complete identity for one item it aggregates.

    Composed of the three rungs, outermost first — the same order the
    visible title reads in. Never round-tripped: unlike Rung 2's
    ``ConnectionScopedId``, nothing parses a ``LuxAddress`` back into its
    parts. It exists only on the Display side of the wire, purely to answer
    "is this the same item" and "how do I show it."
    """

    hub: Rung         # Rung 3 — which Hub connection produced this
    connection: Rung  # Rung 2 — which connection on that Hub produced this
    leaf: Rung         # Rung 1 — the producer's own name for the item

    @property
    def hidden_id(self) -> str:
        """The ImGui identity: every rung's key, joined, never elided."""
        return ID_SEPARATOR.join((self.hub.key, self.connection.key, self.leaf.key))

    def title(self, *, hub_ambiguous: bool, connection_ambiguous: bool) -> str:
        """The visible title: only genuinely ambiguous rungs are shown.

        The leaf is always shown — it is what the user came to read. Higher
        rungs join it, outermost first, only when more than one live value
        exists for that rung right now.
        """
        shown = [
            rung.label
            for rung, ambiguous in (
                (self.hub, hub_ambiguous),
                (self.connection, connection_ambiguous),
            )
            if ambiguous
        ]
        shown.append(self.leaf.label)
        return " :: ".join(shown)
```

`hidden_id` is exactly the mission's literal requirement — "derive from
(source-Hub, Hub item id)" — decomposed one level further for OO clarity:
`connection.key` joined with `leaf.key` on `ID_SEPARATOR` *is* the "Hub item
id" (it is the identical string `ConnectionScopedId.compose` or
`CallbackInvocation.menu_id` already produces); `LuxAddress.hidden_id`
prepends the Hub dimension on top of that existing composition rather than
re-deriving it.

`HubId` is the value type a Hub's own identity resolves to. It answers the
question Rung 3 needs settled before anything else can be built on it: what
makes one Hub connection distinct from another.

```python
@final
@dataclass(frozen=True, slots=True)
class HubId:
    """A Hub connection's own stable identity — hostname plus process.

    Hostname alone is the natural *visible* identity (DES-089's original
    framing: it is what the user would call "which machine"), but it is not
    enough for the *hidden* key, because more than one Hub process can run
    on one host — a same-host development duplicate is exactly the
    deployment `lux-whb9`'s own notes call "nonsense but must work." Process
    id closes that gap the same way ``AppletIdentity`` already closes the
    analogous gap for two applets sharing one session (DES-067's
    ``#{session_pid}`` token) — same shape of problem, same shape of fix,
    reused rather than reinvented.
    """

    hostname: str
    pid: int

    @classmethod
    def current(cls) -> Self:
        """This process's own HubId, as it will declare itself to the Display."""
        return cls(socket.gethostname(), os.getpid())

    @property
    def wire_token(self) -> str:
        """The string this identity declares on the wire.

        Compared for equality only, never parsed — see "Hub identity on the
        wire" below.
        """
        return f"{self.hostname}{ID_SEPARATOR}{self.pid}"
```

## Every aggregated surface, uniformly

The mission is explicit that this cannot be solved per-surface, ad hoc, one
bug at a time — the whole point of `lux-whb9` surfacing is that the same
mistake will recur at the next surface unless one mechanism owns it. Four
surfaces the Display aggregates today or imminently:

| Surface | Rung 1 (today) | Rung 2 (today) | Rung 3 (this doc) | Current leaf renderer | Status |
|---|---|---|---|---|---|
| Menus (Clients, Windows) | `register_callback`'s `label` | `CallbackInvocation.menu_id` | `LuxAddress.hidden_id` on the `MenuItem` | `MenuItem(label, activate)` in `entries.py`, `windows_menu.py` — **keys on the bare label today** | `lux-whb9` (hidden), `lux-pgkp` (visible) |
| Frames / windows | `frame_title`/`frame_id` a caller names | `ConnectionScopedId` (DES-086) | `LuxAddress.hidden_id` on the frame's ImGui window id | `Frame.title` used directly as ImGui window label | `lux-pgkp` |
| Scenes | `scene_id` a caller names | `ConnectionScopedId` (DES-086) | Storage key in `FrameBook._scene_to_frame`/`_scene_to_owner` | Flat `dict[str, ...]` keyed by the bare Rung-2 string — **the silent-collision surface described above** | net-new (no bead yet — see below) |
| Tree nodes | none — `TreeNode` carries no id today | none — inert per its own docstring | `LuxAddress.hidden_id` once a node has one | N/A — `TreeElement` has no selection model yet | `lux-kob7` (adds Rung 1 *and* Rung 2 together; must land Rung-3-ready) |

For every one of these, the same two renderings apply, from the one
`LuxAddress`:

1. **The hidden ImGui id** — `LuxAddress.hidden_id` — never the label, never
   the bare Rung-2 string alone. Positional and redrawn every frame is
   fine; nothing parses it back, ever.
2. **The visible title** — `LuxAddress.title(...)` — hostname-anchored,
   with a rung elided the moment it is unambiguous. One Hub, one connection
   aggregated: `"Vox"`. Two connections sharing a repo, one Hub: `"lux (2)
   :: Vox"`. Two Hubs: `"pembroke :: lux (2) :: Vox"`.

### The shared helper every leaf renderer must use

A single Display-side component — call it `AddressBook`, composed wherever
`MenuReplica` and `SceneReplica` already live — is the one place that:

- tracks the live set of connected `HubId`s and, per Hub, the live set of
  connections (generalizing what `SocketListener`/`HubReconciliation`
  already track per fd — see below, this is mostly relabeling existing
  bookkeeping, not new bookkeeping);
- computes rung ambiguity **once per frame or per menu build**, the same
  cadence `MenuReplica.menu_model()` already rebuilds every frame so every
  item reads live state;
- reuses DES-064's collision-numbering rule and DES-067's `(repo,
  session_pid)` grouping verbatim for the *connection* rung's ambiguity and
  label, and applies the identical numbering algorithm one level up for the
  *hub* rung — same mechanism, two call sites, not two mechanisms;
- exposes exactly one construction path: `address_for(hub, connection_key,
  connection_label, leaf_key, leaf_label) -> LuxAddress`.

No leaf renderer may construct a `MenuItem`, a frame title, a scene entry,
or (once `lux-kob7` lands) a tree-node row directly from a bare label ever
again — each goes through `AddressBook.address_for` and renders
`.hidden_id` / `.title(...)`. This is the mechanism `lux-whb9`'s own
description asks for: "a shared helper the leaf renderers MUST use so new
menus/lists cannot reintroduce label-keyed identity." One `AddressBook`,
many renderers consuming it, is the identical shape as DES-059's "one
`MenuModel`, two projections" — a second source of truth is exactly the
class of drift this repo keeps re-solving one way.

## Multi-Hub topology

The operator's belief that multi-Hub support is "not much complexity" is
correct for the case the current transport can actually support, and this
section makes that case concrete enough to implement. It is also precise
about the one case the transport cannot support without a larger change —
see the open question below.

### What already works, unmodified

The Hub-to-Display leg is a Unix domain socket
(`display/socket_server.py`, `AF_UNIX`, mode `0700`) — the Display is
already a multi-connection server, accepting an arbitrary number of client
fds. Several pieces of the multi-Hub story are, concretely, *already built*,
for a reason unrelated to multi-Hub:

- **Per-connection scene ownership.** `FrameBook.scene_to_owner` already
  maps `scene_id -> fd`, and `InteractionDelivery._deliver_one` already
  routes a scene-bearing interaction to its owning fd, not to whichever
  connection happens to be "the" Hub. This path is multi-Hub-safe today,
  unmodified, because it was already written per-connection for DES-068's
  reconnect/purge story.
- **Per-connection manifest purge.** `HubReconciliation.handle_manifest`
  already scopes purge to the identifying fd's own scenes. A second Hub's
  manifest cannot purge a first Hub's scenes, because the purge predicate
  is already `fd`-scoped.
- **Preemption is already keyed by declared identity, not "the" Hub.**
  `SocketListener.hub_fd_for(name)` and
  `HubReconciliation._preempt_stale_hub` already look up and evict a stale
  connection *sharing the identical declared name* — never any `kind="hub"`
  fd. The only reason this reads as "single Hub" today is that every Hub
  process declares the identical hardcoded name, `_DISPLAY_CLIENT_NAME =
  "lux-mcp"` (`domain/hub/clients.py`). Change what populates that field to
  a real per-process identity, and the *existing* preemption code already
  does the right thing: a genuine reconnect (same identity) still
  preempts its own stale fd; two distinct Hubs (distinct identities) do
  not preempt each other at all. No change to the preemption logic itself
  is required — see "Hub identity on the wire" below.

### What must change

1. **A Hub declares a real `HubId`, not a constant.** `ClientRegistry.get()`
   constructs `DisplayLink(name=_DISPLAY_CLIENT_NAME, kind="hub", ...)`
   unconditionally; `_DISPLAY_CLIENT_NAME` becomes `HubId.current().wire_token`
   (or an equivalent, see the wire-encoding fork below).
2. **Every Display-side store keyed by a Rung-2 string gains the Hub
   dimension.** `FrameBook._scene_to_frame`, `_scene_to_owner`,
   `MenuReplica._callback_menus`, `_agent_menus` — each currently a flat
   structure spanning every connection — must key or partition by `HubId`
   as well as the Rung-2 string, so a second Hub's identically-shaped key
   cannot alias a first Hub's entry. The exact data-structure shape (a
   `dict[HubId, dict[str, ...]]` versus a single `dict[LuxAddress-derived
   key, ...]`) is an implementation decision for the specialist mission,
   not a design-time commitment; the *requirement* — no aggregated store may
   be keyed by a bare Rung-2 string once more than one Hub can write to it
   — is the design-time commitment.
3. **Scene-less interaction dispatch must stop broadcasting.**
   `InteractionDelivery._deliver_one` has two paths: scene-bearing events
   already route correctly per point above; scene-less events (a menu-bar
   or World-panel click, which carries no `scene_id`) currently
   **broadcast to every connected client**, on the documented assumption
   that exactly one Hub is listening and its fallback handler will resolve
   the leaf. With more than one Hub connected, a broadcast delivers every
   Hub's menu click to every Hub — and because `CallbackInvocation`'s
   `connection_id` is only unique *within* the originating Hub (see
   Problem, above), a second Hub receiving a stray click is not merely
   wasted work, it is a live risk of that Hub misrouting the click to one
   of its own sessions whose `connection_id` happens to collide. The fix
   is structural, not a new mechanism: once callback menus are stored
   per-`HubId` (point 2), the Display already knows, at menu-composition
   time, which Hub contributed a given `CallbackInvocation` — thread that
   `HubId` through the `ClickTarget`/`MenuHandlers` closure
   (`display/menus/menu_click.py`) so `InteractionDelivery.deliver`
   receives an event that already names its one target fd, and drop the
   broadcast fallback entirely for menu-sourced events.
4. **Connect needs no new logic.** A new Hub process opens a new socket
   connection and sends its own `ConnectMessage`; the Display's existing
   accept loop requires no change to accept it — it already accepts an
   unbounded number of fds.
5. **Disconnect needs no new logic beyond dropping the departed `HubId`
   from `AddressBook`'s live set,** so a solo survivor's rung re-elides
   (the DES-064-amendment rule, "when a name is released the base it frees
   goes to the senior client still numbered against it," generalized one
   layer up to Hubs, reusing the identical mechanism rather than a new
   one). Every other disconnect concern — per-fd scene reaping, lease
   sweep — is already fd-scoped and needs no change.

### Discovery — deliberately none

Per the operator's instruction not to over-engineer this: there is no Hub
registry, no discovery protocol, no broadcast, no new authentication
handshake. A Hub connects to the Display's already-published Unix socket
path exactly as it does today — `DisplayPaths.socket_path`, one
well-known filesystem location per user. "Discovery" is unlocking the door
that is already open: a second `luxd` process finds and connects to the
identical socket the first one did, because nothing about the socket path
is Hub-specific today. Nothing new needs to be built for a Hub to *find*
the Display; the entire multi-Hub design is about what happens *after*
that already-working connect.

## Governing invariant

> For any item the Display renders as part of a collection it aggregates —
> a menu entry, a frame or window, a scene, a tree node — that item's
> storage key and its ImGui widget id both derive from the item's full
> `LuxAddress` (hub, connection, leaf). Neither may derive from a bare
> human label, nor from a Rung-2-or-lower id alone, once more than one Hub
> can contribute to that collection.

This is checkable, and it is structural rather than behavioral: it becomes
a type discipline once `LuxAddress` (or an equivalent triple carrying
`HubId`) is the actual key type of every aggregated store, not merely a
rendering-time convenience computed and discarded. A store typed
`dict[str, Frame]` for something more than one Hub can populate is the
violation, visible at the type signature — `str` cannot carry the Hub
dimension, so any `str`-keyed aggregated store is holding a promise it
cannot keep. Concretely, one regression test is the load-bearing check: two
synthetic Hub connections independently producing colliding Rung-2 strings
(construct both with the identical `connection_id` and `local_id`, since
`connection_identity.py`'s hash makes this a real, not merely theoretical,
possibility) must produce two distinct entries in the Display's storage,
never one clobbering the other.

**Not a z-spec candidate.** This invariant is a naming/keying discipline,
not a concurrency property, a lock discipline, or a stateful protocol with
an interleaving to exhaust. There is no shared mutable resource two threads
race over here — each Hub's fd is handled by the existing single-threaded
socket-callback dispatch, serially, per WORKFLOW.md's z-spec trigger list.
A structural test (the collision regression above) plus code review that
every aggregated store's key type carries `HubId` is the right-sized
verification; a formal model would be modeling a naming convention, not a
protocol.

## Reconciliation with existing design

- **DES-088 (visibility is the Display's own axis).** Orthogonal, not in
  tension. `LuxAddress` answers "which storage slot, which widget id";
  `FrameVisibility` answers "is it painted." DES-088's own rule — "a
  content event never writes visibility" — extends cleanly: Rung 3 is a
  content-identity concern exclusively, and touches nothing DES-088 owns.
  A closed frame keeps its `LuxAddress` exactly as an on-screen one does.
- **DES-064 / DES-067 (Clients-menu grouping and `(n)` collision
  numbering).** Reused, not superseded, not duplicated. The *connection*
  rung's ambiguity and label computation is the identical mechanism
  DES-064/067 already ship for grouping applet connections by `(repo,
  session_pid)` and numbering same-repo collisions. This document applies
  that same algorithm one rung higher, to Hub-of-origin collisions on one
  host — the deployment `lux-whb9`'s own notes already anticipated
  ("`pembroke`, `pembroke (2)`").
- **DES-086 (scenes and frames cannot alias across connections).** Rung 2
  is unchanged by this document. `ConnectionScopedId` and its "collision
  unrepresentable, not merely checked" property continue to hold exactly
  as shipped. This document extends the identical discipline one layer up,
  closing the analogous gap DES-086 closed for same-Hub connections — now
  for cross-Hub connections. The throughline is the point: the same class
  of bug, caught by the same kind of fix, one layer higher, because a new
  layer of aggregation was added above the one DES-086 already secured.
- **DES-058 (the menu is sessions' callbacks).** `CallbackInvocation`
  (Rung 2) is unchanged. This document wraps it in a `LuxAddress`; it does
  not alter how a session registers a callback or how a click round-trips
  to `CallbackInvocation.from_menu_id` — that parse still resolves against
  the *originating Hub's own registry*, which is exactly why misrouting a
  stray broadcast to the wrong Hub (Multi-Hub topology, point 3, above) is
  a real risk this document closes, not a hypothetical one.
- **`FrameRef` (historical, DES-089's working title, `lux-81t3.2`).**
  `FrameRef` was a call-site ergonomic wrapper — `connection_id` +
  `local_id` bundled into one value object purely to drop a parameter from
  the now-removed client-facing `raise_frame` operation (introduced
  `bec389c3`, removed in PR #446 when DES-088 retired every
  client-facing display-modification operation). It carried no rung this
  document does not already have in `ConnectionScopedId`, and it no longer
  exists in the tree — nothing here depends on or revives it. This
  document is DES-089's actual specification; `FrameRef`'s docstring
  citation of DES-089 was the first, partial use of the name, not the
  design itself.

## Implementation bead map

Existing open beads become children of this one ratified design rather
than independent one-offs:

| Bead | What it implements | Rung(s) |
|---|---|---|
| `lux-whb9` | The hidden ImGui id, menus — `AddressBook.address_for(...).hidden_id` on `MenuItem` construction | 2 → 3 |
| `lux-pgkp` | The visible scoped title, frames and menus — `.title(...)` | 1, 2, 3 |
| `lux-kob7` | `TreeNode` gets an id and a Hub-authoritative `TreeSelectionModel` (mirroring `TableSelectionModel`) — must mint Rung 1 *and* Rung 2 together, Rung-3-ready from the start rather than retrofitted | 1, 2 |

Net-new beads this document's multi-Hub topology requires, not yet filed
(the leader files these, per this mission's contract — listed, not
created):

1. **Hub identity on the wire.** `ConnectMessage` carries a real `HubId`
   instead of the hardcoded `_DISPLAY_CLIENT_NAME`; `ClientRegistry`
   constructs it from `HubId.current()`. Depends on the wire-encoding fork
   below being ruled on first.
2. **Per-Hub-keyed Display storage.** `FrameBook`'s scene/frame maps and
   `MenuReplica`'s callback/agent-menu tuples gain the Hub dimension —
   Multi-Hub topology, point 2, above.
3. **`AddressBook` component.** The shared per-frame ambiguity/labeling
   helper every leaf renderer routes through — the mechanism section,
   above. This is the natural single write-set for `lux-whb9` and
   `lux-pgkp` to share, rather than each bead inventing its own partial
   version.
4. **Scene storage collision test.** The regression test named in
   "Governing invariant," above — two Hubs, colliding Rung-2 strings, two
   distinct entries required. Should land with beads 1–3, not deferred.
5. **Menu-click routing fix.** Retire `InteractionDelivery`'s
   scene-less broadcast fallback in favor of routing by the originating
   `HubId` — Multi-Hub topology, point 3, above. Depends on bead 2 (a
   `HubId` must already be attached to each stored callback menu before a
   click can be routed by it).

## Open questions — need an operator ruling before implementation dispatches

This document does not silently resolve either of these; both are real
either/or decisions the design mission's contract does not settle.

1. **Same-host multi-Hub versus cross-host multi-Hub.** Every mechanism
   this document specifies is same-host: the Hub-to-Display transport is
   an `AF_UNIX` domain socket (`display/socket_server.py`), which cannot
   be reached from a different machine — this is a transport-level fact,
   not a policy choice. `HubId`'s hostname component reads, in the
   originating bead notes, as though cross-host aggregation was the
   mental model ("network-unique, no registry — makes the address
   literally X's host:display.screen"), but the current wire cannot carry
   a Hub's traffic across hosts at all. This document designs and
   specifies the same-host case in full — multiple `luxd` processes on
   one machine, one Display, which is the case the operator's "not much
   complexity" ruling actually matches, since it needs zero transport
   change. **Ruling needed:** is cross-host Hub aggregation in scope for
   this epic at all, now or later? If yes, it needs a materially larger
   follow-on design — a network transport, an authentication story beyond
   the current same-user-localhost trust model (`transport_policy.py`
   refuses any off-loopback bind today), and is a different mission, not
   an extension of this one. If no (recommended, given the operator's own
   framing of the scope as "not much complexity"), that should be stated
   explicitly so `HubId`'s hostname component is understood as "which
   machine, for a human reading the title" rather than "the network
   address a second Hub connects across."
2. **Hub identity on the wire: reuse `ConnectMessage.name`, or add a new
   field.** `ConnectMessage` has exactly two fields today, `name: str` and
   `kind: Literal["hub", "test"]`. Populating `name` with
   `HubId.current().wire_token` needs no wire-protocol version bump and no
   cross-repo coordination — every consumer of `ConnectMessage` already
   treats `name` as an opaque display-attribution string. Adding a
   dedicated typed field (`hub_id: str | None`) is cleaner in intent —
   `name` keeps meaning "what a human calls this connection," a genuinely
   separate concern from "which Hub process this is" — at the cost of a
   wire-format bump every Hub-side writer must observe (vox and z-spec
   both run Hub processes per `applets/README` and the DES-063 applet
   model). This is the identical shape of tradeoff DES-067 already ruled
   on for an analogous problem (parse a token out of an existing field
   versus add a first-class field to `ClientIdentity`) and settled on
   "parse from the existing field now; add the first-class field only
   when the next real reason to bump the wire arrives." **Recommendation:**
   follow that precedent — reuse `name`, encode `HubId.wire_token` into
   it, parse it back where the Hub dimension is needed. **Ruling
   needed:** confirm before `lux-whb9`/net-new bead 1 dispatch, since it
   is a wire-format commitment other repos' Hub-running code depends on.

## Related target docs

- [target.md](./target.md)
- [topology.md](./topology.md)
- [ui-model.md](./ui-model.md)
- [element-contract.md](./element-contract.md)
- [introspection-api.md](./introspection-api.md)
