# Lux Target Addressing Model

> **Archived 2026-09-04 — superseded; retained for history.**
> This was the evaluator-accepted design draft for DES-089. Per operator
> direction (2026-09-04), its architecture content was restructured into
> `docs/architecture/system.tex` §"Identity, Addressing, and Multi-Hub
> Topology," and its implementation plan into
> `docs/architecture/multi-hub-addressing-work.md`. DES-089 in
> `DESIGN.md` remains Status: PROPOSED, pending operator ratification,
> and now points at those two documents instead of this one. This draft
> is kept for the reasoning trail only — do not use it to guide
> implementation. See `docs/archive/README.md` for why this was
> archived.

**Status:** canonical target for identity and multi-Hub aggregation.
**Ratifies:** DES-089 ("identity is a path") in `DESIGN.md`.

Start with [target.md](../architecture/target/target.md). This document
is a sibling to [ui-model.md](../architecture/target/ui-model.md) (what
the UI objects are) and
[topology.md](../architecture/target/topology.md) (how the processes
connect). It answers a
question those two do not: when the Display renders something it did not
produce, how is that thing identified — uniquely enough that ImGui never
collides, legibly enough that a human can tell two things apart, and safely
enough that two producers' content can never silently overwrite one
another?

## Problem

The Display is an aggregator. It renders content it did not create, from
producers it does not control, and — per
[topology.md](../architecture/target/topology.md) — from
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

`title()` joins on `" :: "` rather than `"/"`, even though "identity is a
path" is this document's own governing metaphor. The reason is audience,
not a rejection of the metaphor: `/` reads as a filesystem or URL
segment — plausibly clickable, parseable, or navigable — to the
developer/agent audience this title is shown to, and no part of a
`LuxAddress` title is any of those things; nothing round-trips it back
into rungs (see `LuxAddress`'s docstring, above). `::` is the
namespace-qualification notation that same audience already reads as
"scope, not a route" (C++ scope resolution, Python module paths in
prose), which is the truer signal here.

`hidden_id` is exactly the mission's literal requirement — "derive from
(source-Hub, Hub item id)" — decomposed one level further for OO clarity:
`connection.key` joined with `leaf.key` on `ID_SEPARATOR` *is* the "Hub item
id" (it is the identical string `ConnectionScopedId.compose` or
`CallbackInvocation.menu_id` already produces); `LuxAddress.hidden_id`
prepends the Hub dimension on top of that existing composition rather than
re-deriving it.

`HubId` is the value type a Hub's own identity resolves to. It answers the
question Rung 3 needs settled before anything else can be built on it: what
makes one Hub connection distinct from another — and, per the operator's
ruling that cross-host aggregation is in scope, distinct from a Hub on a
*different machine*, not merely a different process on the same one.

```python
@final
@dataclass(frozen=True, slots=True)
class HubId:
    """A Hub connection's own stable identity — network host plus process.

    Two independent uniqueness axes, kept as two fields rather than folded
    into one, because they are disambiguated by two different mechanisms:

    - ``hostname`` distinguishes one *machine* from another. Once
      cross-host aggregation is real, this can no longer mean "whatever
      ``socket.gethostname()`` happens to return" — a bare hostname is not
      guaranteed unique across a network the way it is trivially unique on
      one box (two laptops both named ``"laptop"`` is a real, common case,
      not a hypothetical one). ``HubId.current()`` below uses
      ``socket.getfqdn()`` rather than ``socket.gethostname()`` for exactly
      this reason — a fully-qualified name is unique wherever DNS makes it
      so, which a bare hostname is not.
    - ``pid`` distinguishes one *process* from another **on the same
      machine** — a same-host development duplicate is exactly the
      deployment `lux-whb9`'s own notes call "nonsense but must work."
      Process id closes that gap the same way ``AppletIdentity`` already
      closes the analogous gap for two applets sharing one session
      (DES-067's ``#{session_pid}`` token) — same shape of problem, same
      shape of fix, reused rather than reinvented. ``pid`` is not
      network-meaningful and never needs to be — the ``hostname`` field is
      the whole of the cross-host uniqueness claim; ``pid`` only ever
      breaks a tie *within* one already-identified host.

    Self-reporting its own FQDN is as far as ``HubId`` itself goes, and it
    is enough for the same-host case, where the Unix-socket directory's
    ``0700`` permission already bounds who can even open a connection to
    declare a ``HubId`` in the first place — a hostile process cannot
    reach the socket to lie about its identity. That trust argument does
    not carry across a network: see "Dependencies on the cross-host
    transport layer," below, for what changes once a connection is not
    already scoped to one trusted user on one machine.
    """

    hostname: str
    pid: int

    @classmethod
    def current(cls) -> Self:
        """This process's own HubId, as it will declare itself to the Display."""
        return cls(socket.getfqdn(), os.getpid())

    @property
    def wire_token(self) -> str:
        """The string this identity declares on the wire.

        Compared for equality only, never parsed — see "Hub identity on the
        wire" below.
        """
        return f"{self.hostname}{ID_SEPARATOR}{self.pid}"
```

Same-host duplicates keep the DES-064-style `(n)` numbering exactly as
round 1 specified — two Hubs sharing one `hostname` (their FQDN resolves
identically because they are, in fact, the same machine) disambiguate by
`pid`, then render as `pembroke`, `pembroke (2)`, precisely as before.
Nothing about that visible-title behavior changes; only the *source* of
the `hostname` field's trustworthiness does, and only cross-host.

## Hub identity on the wire

Round 1 left this as an open fork — reuse `ConnectMessage.name`, or add a
dedicated field — and recommended reuse, following DES-067's precedent for
the same shape of tradeoff. **The operator ruled the opposite way
(2026-09-04): a dedicated `hub_id` field.** `name` keeps its existing,
narrower meaning — "what a human calls this connection," the string a
frame title or a menu already attributes content to — and does not also
carry the Hub's own machine-and-process identity. The two concerns were
never actually the same concern; round 1's reuse recommendation traded
away exactly the separation the rest of this document argues for
everywhere else, to save one field.

```python
@dataclass(frozen=True, slots=True)
class ConnectMessage:
    """Client identifies itself to the display server.

    ``name`` is display attribution — unchanged, still the string frame
    titles and menu namespaces read. ``hub_id`` is a separate concern: a
    ``kind="hub"`` connection's own ``HubId.wire_token``, absent for
    ``kind="test"`` connections because a test backdoor is not a real Hub
    and has no ``HubId`` to declare.
    """

    name: str
    kind: Literal["hub", "test"]
    hub_id: str | None = None  # absent for kind="test"; HubId.wire_token for kind="hub"
    type: Literal["connect"] = "connect"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict, omitting an absent hub_id."""
        d: dict[str, Any] = {"type": self.type, "name": self.name, "kind": self.kind}
        if self.hub_id is not None:
            d["hub_id"] = self.hub_id
        return d
```

**A note on `hub_id: str | None` and the OO stance (python.md Rule 5).**
This is precisely the shape Rule 5 asks a discriminated type to replace —
`hub_id`'s presence is not genuinely "absent," it is fully determined by
`kind`: `kind="hub"` always carries it, `kind="test"` never does. This
document keeps the plain Optional as a deliberate, scoped exception rather
than splitting `ConnectMessage` into `HubConnectMessage` /
`TestConnectMessage`, for two reasons: `kind`'s discriminating role is
already load-bearing today, so the coupling is not new; and a full
message-type split is a materially larger wire change than the
single-field addition this section otherwise commits to, out of proportion
to this mission's scope. The discriminated-type split is the correct
long-term shape and is noted here as an explicit follow-on, to be taken up
if `kind`'s branching grows beyond this one field — not passed over
silently.

`ClientRegistry.get()` (`domain/hub/clients.py`) is the one production
writer of a `kind="hub"` `ConnectMessage`; it constructs
`hub_id=HubId.current().wire_token` in place of today's hardcoded
`_DISPLAY_CLIENT_NAME` passed as `name`. `name` itself does not disappear
— it keeps carrying whatever human-facing label the Hub process wants
attributed (today, still a fixed string; nothing in this document requires
that to become more elaborate).

**Wire compatibility versus feature completeness — these are not the same
question.** `ConnectMessage.from_dict` treats `hub_id` as optional, so an
old sender's dict (no `hub_id` key) still decodes without error — parsing
is backward-compatible by construction, no `PROTOCOL_VERSION` bump forced
by the shape of the change alone. But *multi-Hub correctness* is not
backward-compatible in the same sense: a real `kind="hub"` connection that
omits `hub_id` cannot be safely disambiguated at Rung 3, so every
Display-side store keyed by `HubId` (see "What must change," below) must
treat a missing `hub_id` on a `kind="hub"` connection as a hard error, not
a silent single-Hub fallback — silently tolerating it would resurrect
exactly the "collision passes unnoticed" failure mode this whole document
exists to close.

**This is a cross-repo commitment.** `topology.md` and the DES-063 applet
model both name vox and z-spec as processes that run their own Hub
connections (`applets/README`). Both must add `hub_id` to the
`ConnectMessage` they send, in lockstep with this change landing here —
per the org's cross-repo breaking-change protocol (`CLAUDE.md` §"Cross-repo
breaking changes": notify, agree, land together, verify end-to-end,
release together). This is listed explicitly as a coordination requirement
on net-new bead 1, below, not left implicit.

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
- computes each rung's **ambiguity** — a pure cardinality test, not a label
  comparison — **once per frame or per menu build**, the same cadence
  `MenuReplica.menu_model()` already rebuilds every frame so every item
  reads live state. A rung is ambiguous, and therefore shown, exactly when
  more than one live value exists for that rung right now — this is the
  whole of `LuxAddress.title`'s docstring, restated here so the two never
  drift apart again;
- separately, once a rung *is* shown, reuses DES-064's collision-numbering
  rule and DES-067's `(repo, session_pid)` grouping verbatim to compute
  that rung's own **label text** — whether two shown siblings' own names
  happen to read as the identical string (`"lux"` and `"lux"` becoming
  `"lux"` / `"lux (2)"`) — for both the *connection* rung (as shipped) and
  the *hub* rung (this document, one level up). **This is a second, later
  job, not the same job as elision.** Ambiguity decides *whether* a rung
  shows at all; DES-064/067 numbering decides *what a shown rung's label
  reads as*. Two Hubs named `pembroke` and `walnut`, each aggregating a
  connection that produces a leaf named `Vox`: the hub rung's cardinality
  is 2, so it shows on *both* — `pembroke :: Vox` and `walnut :: Vox` —
  regardless of the fact that `pembroke` and `walnut` do not collide as
  strings and so never touch the DES-064/067 numbering path at all. Reading
  the reused-mechanism note below as license to skip a rung whenever its
  own label happens to be unique reintroduces the exact bare-title
  collision (`"Vox"` shown twice, unqualified) this document exists to
  close — see "Problem," above;
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

**Operator ruling (2026-09-04): cross-host is in scope now.** One Display
aggregates Hubs across multiple machines, not only multiple `luxd`
processes on one host. This section covers both cases, and is precise
about where the line between them falls: the addressing model below —
rungs, `LuxAddress`, `AddressBook`, per-store keying — is transport-agnostic
and applies identically whether a Hub reaches the Display over a Unix
socket or a network socket. What is *not* transport-agnostic, and does not
belong in this document, is how a remote Hub establishes that connection
in the first place — that is a separate transport-and-trust design,
introduced in "Dependencies on the cross-host transport layer," below.

### What already works, unmodified

The Hub-to-Display leg is, today, a Unix domain socket
(`display/socket_server.py`, `AF_UNIX`, mode `0700`) — the Display is
already a multi-connection server, accepting an arbitrary number of client
fds. Several pieces of the multi-Hub story are, concretely, *already
built*, for a reason unrelated to multi-Hub, and — because every one of
them is written against "a connection" in the abstract, not against
`AF_UNIX` specifically — every one of them survives a same-host-to-network
transport change unmodified, not merely by coincidence:

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
   unconditionally; `_DISPLAY_CLIENT_NAME` becomes `HubId.current().wire_token`,
   carried on the dedicated `hub_id` field — see "Hub identity on the wire,"
   above.
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
4. **Connect, same-host: no new logic.** A new same-host Hub process opens
   a new socket connection and sends its own `ConnectMessage`; the
   Display's existing accept loop requires no change to accept it — it
   already accepts an unbounded number of fds. **Connect, cross-host: out
   of this document's scope by design** — see "Dependencies on the
   cross-host transport layer," below. Once a remote Hub's connection is
   established and authenticated by that layer, everything from this point
   forward (points 1–3, 5, and the per-surface treatment) applies
   identically; this document does not need a second version of the
   addressing model for the cross-host case, only a second version of how
   the connection got there.
5. **Disconnect needs no new logic beyond dropping the departed `HubId`
   from `AddressBook`'s live set,** so a solo survivor's rung re-elides
   (the DES-064-amendment rule, "when a name is released the base it frees
   goes to the senior client still numbered against it," generalized one
   layer up to Hubs, reusing the identical mechanism rather than a new
   one). Every other disconnect concern — per-fd scene reaping, lease
   sweep — is already fd-scoped and needs no change, on any transport.
6. **Elision churn under connect/disconnect is an accepted trade-off, not
   a defect.** Because ambiguity is recomputed live (see "The shared
   helper," above), a title that was bare a moment ago can silently gain a
   `hub ::` prefix the instant an unrelated second Hub connects, and lose
   it again the instant that Hub disconnects — driven by an event that has
   nothing to do with the item itself. This is a different case from the
   renaming churn point 5 already handles (a base name being reassigned
   between existing siblings); here, an item's own identity never
   changes, only how much of its address is worth showing. This document
   accepts the churn rather than mitigating it: `LuxAddress.title()` is
   always an accurate answer for the population that exists right now, a
   user who has learned to read it once is never shown a *wrong* title,
   and a mitigation (a sticky prefix once ever seen, a transient
   highlight) is real complexity purchased for a case the operator's own
   scope note already treats as simple.

### Discovery — same-host

Per the operator's instruction not to over-engineer this: there is no Hub
registry, no discovery protocol, no broadcast, no new authentication
handshake, for the same-host case. A Hub connects to the Display's
already-published Unix socket path exactly as it does today —
`DisplayPaths.socket_path`, one well-known filesystem location per user.
"Discovery" is unlocking the door that is already open: a second `luxd`
process finds and connects to the identical socket the first one did,
because nothing about the socket path is Hub-specific today. Nothing new
needs to be built for a same-host Hub to *find* the Display; the entire
same-host multi-Hub design is about what happens *after* that
already-working connect.

### Discovery and connection, cross-host — delegated, not designed here

A remote Hub cannot reach an `AF_UNIX` socket; "connect to the same
socket" is not a framing that survives crossing a machine boundary, and
this document does not attempt to supply one. How a remote Hub learns the
Display's network endpoint, how that connection is initiated, and how it
is authenticated are questions for the companion transport-and-trust
design named in "Dependencies on the cross-host transport layer," below —
`djb`'s domain, dispatched separately. What this document commits to is
narrower and is stated precisely there: once that layer hands the
addressing layer a connection with a verified `HubId` attached, this
document's model takes over identically to the same-host case. The
boundary is deliberate and exact: **endpoint resolution and connection
initiation are the transport layer's job; everything from "a connection
with a verified identity exists" onward is this document's job.**

## Dependencies on the cross-host transport layer

This document does not design a network transport or an authentication
mechanism — that is `djb`'s domain, and it is a materially larger, separate
design: a network transport in place of (or alongside) the current
`AF_UNIX` leg, and a trust model beyond the current same-host,
filesystem-permission trust boundary (`LoopbackTransportPolicy` already
refuses any off-loopback bind for luxd's *other* leg, the MCP/REST surface
— the Hub-to-Display leg has no analogous policy today because it has
never needed one; cross-host is exactly what gives it a reason to). That
design is specified in
[cross-host-transport.md](./cross-host-transport.md), and was not part of
this mission's write-set.

What *is* this document's job is to state, precisely, what the addressing
layer requires from that transport — so the two documents compose without
overlap, and so `djb`'s design has a contract to satisfy rather than a
blank page. Five requirements:

1. **Authenticate before content.** The transport MUST authenticate a
   connecting Hub and deliver its *verified* `HubId` to the Display before
   any scene, menu, or other content-bearing message from that connection
   is accepted. A `SceneMessage` or `CallbackMenuMessage` arriving ahead of
   a verified identity has nowhere safe to be filed — every per-surface
   store in "What must change," above, is keyed by `HubId` from the first
   write.
2. **The addressing layer trusts `HubId` as authenticated, and performs no
   authentication of its own.** Once the transport hands `HubId` to the
   Display, this document's mechanisms — `AddressBook`, the per-store Hub
   dimension, the collision-numbering rule — treat it as ground truth.
   Verifying that the claimed identity is genuine is entirely the
   transport's responsibility; nothing in this document re-checks it, and
   nothing in this document should have to.
3. **`HubId` MUST be stable across reconnects.** The same Hub process
   presenting a new connection after a drop (network blip, restart) must
   receive back the identical `HubId` it held before, not a fresh one —
   otherwise every per-`HubId`-keyed store fragments across the
   reconnect, and `AddressBook`'s live-set bookkeeping (`Multi-Hub
   topology`, point 5) sees a disconnect-then-connect pair instead of one
   continuous Hub. How the transport achieves that stability — a
   reissued credential bound to the same identity, a reconnect token, a
   certificate the Hub retains across restarts — is the transport's
   design choice; the *stability property itself* is this document's
   requirement.
4. **The transport owns endpoint/address resolution and connection
   initiation.** DNS, static configuration, a discovery protocol, a
   registry — whichever mechanism a remote Hub uses to find the Display's
   network endpoint and open the connection is entirely outside this
   document's model, exactly as stated in "Discovery and connection,
   cross-host," above.
5. **`ConnectMessage.hub_id` (see "Hub identity on the wire," above) is
   the wire carrier for the verified identity, sent as the first frame
   after the transport's own handshake completes.** The addressing
   layer's per-`HubId` storage keying is inert until this frame arrives;
   ordering matters, and the transport's handshake MUST complete, including
   authentication, before this frame is trusted.

**A genuine new fork this expansion surfaces — flagged, not resolved
here.** `HubId.hostname` (see "Value types," above) is today a
self-reported string the Hub computes locally (`socket.getfqdn()`) and
declares on the wire; the same-host trust argument for accepting it
at face value is that the `AF_UNIX` socket directory's `0700` permission
already keeps a hostile process from reaching the socket to lie. That
argument does not extend to a network connection. Requirement 1, above,
only says the transport must deliver a *verified* `HubId` — it does not
settle *what the transport verifies*, and there are two materially
different answers:

- **(a) Verify the self-reported hostname is truthful** — the transport
  authenticates the connecting process and additionally attests that its
  claimed FQDN is not forged (e.g., cross-checked against a certificate's
  subject name or a reverse-DNS lookup), and `HubId.hostname` keeps
  meaning exactly what it means today: a real, verified network name.
- **(b) Treat the human-readable hostname as a cosmetic label only, and
  make the true uniqueness key an opaque transport-assigned credential**
  (a certificate identity, an mTLS SPIFFE-style ID, a connection-scoped
  token) that `HubId` would need a third field to carry, with `hostname`
  demoted to "whatever the Hub claims, shown to a human, never trusted for
  uniqueness."

(a) keeps `HubId` exactly as specified in this document and matches the
existing precedent of trusting a declared field once a connection is
authenticated (DES-086, DES-058). (b) is more defensive — it asks the
transport to guarantee "this credential is unique and genuine," a
narrower and more tractable claim than "this hostname string is unique
and genuine" — at the cost of a third `HubId` field and a real/cosmetic
split this document does not currently have. This document takes no
position between them; both satisfy requirement 1 as stated, and the
choice belongs to the cross-host transport design, informed by whatever
authentication mechanism it selects.

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
  numbering).** Reused for **labeling**, not for **elision** — the two are
  different jobs, kept distinct in "The shared helper every leaf renderer
  must use," above. Whether the *connection* or *hub* rung shows at all is
  a pure cardinality test (`LuxAddress.title`'s ambiguity flags); DES-064/
  067's collision-numbering rule only decides what a rung's own label
  reads as once it is already shown, when two shown siblings happen to
  share a name. This document reuses that same numbering algorithm one
  rung higher, for Hub-of-origin label collisions on one host — the
  deployment `lux-whb9`'s own notes already anticipated ("`pembroke`,
  `pembroke (2)`") — without touching the separate cardinality test that
  decides whether the hub rung shows at all.
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

1. **Hub identity on the wire.** `ConnectMessage` gains the dedicated
   `hub_id` field specified in "Hub identity on the wire," above;
   `ClientRegistry` constructs it from `HubId.current().wire_token`.
   **Cross-repo coordination required before this bead closes**: vox and
   z-spec both run Hub processes (`applets/README`, DES-063) and must add
   `hub_id` to their own `ConnectMessage` sends in the same release window,
   per the org's cross-repo breaking-change protocol — notify both repos'
   agents, get explicit agreement, land together, verify end-to-end.
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

## Resolved design forks

Round 1 of this design surfaced two either/or decisions rather than
resolve them silently. The operator has since ruled on both
(2026-09-04); this section is the record of what was asked, what was
decided, and why — the design-doc equivalent of a PEP's "Rejected
Alternatives," kept for the reader who wonders why the document reads the
way it does rather than the other plausible way.

1. **Same-host multi-Hub versus cross-host multi-Hub.** Round 1 specified
   only the same-host case in full and recommended cross-host stay
   explicitly out of scope, noting the transport-level fact that an
   `AF_UNIX` socket cannot be reached from a different machine. **Ruled:
   cross-host is in scope, now.** The operator chose this knowing it
   needs a network transport and an authentication story beyond the
   current same-host, filesystem-permission trust boundary — see
   "Multi-Hub topology" and "Dependencies on the cross-host transport
   layer," above, for how this document accommodates that without
   redesigning the addressing model itself, which remains
   transport-agnostic and unchanged by this ruling.
2. **Hub identity on the wire: reuse `ConnectMessage.name`, or add a new
   field.** Round 1 recommended reuse, following DES-067's precedent for
   an analogous tradeoff ("parse from the existing field now; add the
   first-class field only when the next real reason to bump the wire
   arrives"). **Ruled: add a dedicated `hub_id` field.** The operator
   judged that the precedent-driven minimalism traded away exactly the
   separation this document argues for everywhere else — "what a human
   calls this" and "which Hub process this is" are different concerns,
   and cross-host aggregation is a second, independent reason the wire
   needed to change regardless of which way this fork was decided. See
   "Hub identity on the wire," above, for the field and its cross-repo
   coordination requirement.

## Related target docs

(Paths below are relative to this archived document's location,
`docs/archive/`; both moved here together, so the archived
cross-host-transport.md link is unchanged.)

- [../architecture/target/target.md](../architecture/target/target.md)
- [../architecture/target/topology.md](../architecture/target/topology.md)
- [../architecture/target/ui-model.md](../architecture/target/ui-model.md)
- [../architecture/target/element-contract.md](../architecture/target/element-contract.md)
- [../architecture/target/introspection-api.md](../architecture/target/introspection-api.md)
- [cross-host-transport.md](./cross-host-transport.md) — the
  transport-and-trust design this document depends on (see
  "Dependencies on the cross-host transport layer," above); DES-090,
  `djb`'s domain, dispatched separately. Also archived here.
