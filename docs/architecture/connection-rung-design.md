# Connection Rung and Host Facts — Design

**Beads:** `lux-xrli` (the connection rung) and the DES-099 host-facts
amendment. **Status:** delivered (DES-100, DES-099 amendment). The text below
is the accepted design. As built, it differs in these names and placements:

- A frame's title and label live on one `FrameHeading` (`Frame.heading`, told
  through `adopt`/`relabel`); there is no `Frame.scope_label` or `Frame.title`
  attribute.
- The Scope builder is the public `tools.scope()`, and `Scope` lives in
  `domain/scope.py` (re-exported by `operations`) with `observed` and
  `in_process` constructors. `Scope.peer_host` is `Scope.client_host`.
- The observed host is one immutable `ClientHost` value, captured at each door
  by `ClientHost.of_connection` and required on every lifecycle and registry
  write, so it is recorded on every contact, not on identification only.
  `ClientSession.peers` is `client_hosts`, backed by `ClientHosts`;
  `observed_from` takes a `ClientHost`.
- `SessionWrite.identified` is `restated` (identity, a new host, or a revival),
  and `SessionWrite.attached` is `SessionWrite.recorded(...).seated(listener)`.
- The Hub host is `Hub.hostname`, a lazily cached `HubId.current().hostname`,
  carried on `ClientList` and `ClientFacts`, not a `HubPorts` field or a
  per-client row.
**Rulings (both settled, not re-opened here):** DES-100 (the connection rung
is always shown) and the DES-099 amendment of 2026-10-22 (the `i` popup and
Details report the client host and the Hub host). Both are in `DESIGN.md`.
No ADR is drafted in this document; the first draft of DES-100 that lived
here is superseded by the settled entry.

## Problem

Two things an operator needs to know about a window are missing from the
Display.

**Whose window is it?** Two Claude sessions in one repo, on one Hub, produce
frames whose titles collide: both Details panes read `claude`, both Vox panels
read `Vox`. Even with one session, a bare `Beads` or `Vox` never says which
repo it belongs to, because the same applets run in every repo by design. The
Clients menu tells sessions apart (`lux`, `lux (2)`) because the Hub computes
that label (DES-064/067) while it builds the menu. The Display cannot, because
a frame arrives as `(hub, frame_id, title)` and the Hub-computed
connection-scope label is never attached to it.

DES-089 specifies a connection rung, and `LuxAddress.title()` can compose it.
But `AddressRendering.title_for` hard-codes `connection_ambiguous=False`, and
`AddressBook.connection_ambiguous(hub)` counts Display-to-Hub *links* (one fd
per Hub), not the Hub's *clients*. It can never be true on a single Hub. The
rung's input — a label — is missing from the wire.

**Where is it running?** Neither the `i` popup nor Details says which machine
the client connected from, nor which machine the Hub is on. That is the one
fact an operator needs once clients and Hubs span machines.

Both gaps are the same shape: a fact the Hub knows about a frame's owner that
the Display does not receive. They share one path (the owner facts the Hub
sends with every frame), so one design covers both.

## ADRs consulted

Each row says whether this design builds on the ADR or amends it.

| ADR | Relationship | What it contributes or changes |
|-----|--------------|--------------------------------|
| DES-057 (client identity) | Builds on | One identity covers REST and the WebSocket listen leg; `connection_for` makes it one connection id. The host report for a multi-transport client follows from this (Part B, "One identity, several transports"). |
| DES-064 (Clients menu) | Builds on | The roster label (`lux`, `lux (2)`) is the connection-rung text. Its 2026-08-02 renumbering means labels *move* on departure; the carried label must follow. |
| DES-067 (grouping by repo and session) | Builds on | Two applets of one session share a `MenuGroupKey` and one label, so they read `lux :: Beads` and `lux :: Vox`. Under the always rule nobody counts scopes any more, so DES-067's "do not count them as two scopes" caveat becomes vacuous. |
| DES-086 (`ConnectionScopedId`) | Builds on | The stable Rung-2 key is already inside every composed `frame_id` and `hidden_id`. The label is never a key. |
| DES-088 (visibility vs content) | Builds on | A label is content and rides a content resend. It writes `Frame.scope_label` and nothing on placement or visibility. A closed frame stays closed across a relabel. |
| DES-089 (identity is a path) | **Amends** (via DES-100) | The Hub rung keeps its elision rule. The connection rung no longer elides. `LuxAddress.title`'s flag for that rung is renamed. `hidden_id` and every storage key are untouched; its governing invariant (keys derive from the full address, never a label) is kept. |
| DES-090 (cross-host trust) | Builds on | The principle that a self-reported host is not trusted is applied to the client host (observed, never declared). Gate 2 makes the Hub host a verified fact (Part B, "Hub host"). |
| DES-099 and its amendment | **Amends** (its title clause, by DES-100) and implements (its host clause) | The callback-less Details window title is now `label :: program`. The host clause is built here. |
| DES-100 (connection rung always shown) | Implements | Parts A in full. |
| DES-101 (client door is a lifecycle callers hold) | Builds on, and constrains | Every new write goes through `ClientLifecycle`; every new read goes to `HubClientRegistry` or `ClientListing`. No `HubDisplay` member is added and nothing reaches through it (Part B, "Flow"). |

Also consulted: `docs/architecture/multi-hub-addressing-work.md` (W4
`AddressBook`), `docs/architecture/hub-display-narrowing.md` (the DES-101
shape), `docs/frame_info_popup.tex` (the popup renders a replicated snapshot
and owns no fact of its own), and `system.tex` §"Identity, Addressing, and
Multi-Hub Topology".

Code read: `display/replica/{lux_address,address_book,address_rendering,
frame_book,scene_eviction,scene_departure,scene_replica}.py`,
`display/menus/{frame_info_popup,connection_panel,windows_menu}.py`,
`display/dock_pill.py`, `protocol/messages/{scene,scene_codec}.py`,
`protocol/compositions/client_details.py`,
`domain/hub/{client_session,session_write,hub_clients,listener_legs,
client_lifecycle,client_roster,menu_presence,owner_tracker,frame_owner_facts,
scene_snapshot}.py`, `domain/hub_id.py`,
`operations/{identity,scope,client_listing,client_identity_facts,
frame_owner_facts,canonical_frame_owner,details_scene,client_details,
client_details_port,ports}.py`, `operations/models/query_clients.py`,
`rest/identity.py`, `ws_transport.py`, `ws_listen.py`, `mcp_endpoint.py`,
`tools/{server,tools}.py`, `session_key.py`, `connection_identity.py`,
`transport_policy.py`, `luxd.py`, `hub_composition.py`.

## Decisions

1. **The Hub sends the label; the Display shows it whenever it is present.**
   A frame carries the DES-064/067 roster name of its canonical owner (`lux`,
   `lux (2)`). The Display composes `label :: title` for every frame that has
   one. There is no collision test, no peer set, and no ambiguity input.
2. **One optional frame-spec field, `frame_scope_label`**, beside
   `frame_owner_facts`, resolved from the same canonical owner in the same
   call.
3. **The label lives on `Frame`**, beside `title`, adopted the way `title`,
   flags and layout are: a push that omits it leaves the last value alone.
4. **Label moves are pushed, not polled.** A roster release that changes a
   survivor's label, and an identification, mark that connection's scenes
   dirty; the ordinary replicator path resends them.
5. **`hidden_id` does not change.** Only the visible title does.
6. **The two host facts are two more rows in the owner facts and in the
   Details table.** `Client host` is what the Hub observed on the connection's
   transport. `Hub host` is the Hub's own canonical hostname. No new message,
   no reverse DNS, no client declaration.
7. **The observed peer is captured at the three client doors and stored on
   `ClientSession`.** It is written in the same registry write as the identity,
   so a resend triggered by identification already carries it.

## Part A — The connection rung is always shown (DES-100)

### What the title is

For a frame F on Hub H with scope label S and base title T:

```python
title = hub_part + (f"{S} :: " if S is not None else "") + T
# hub_part is "<hub label> :: " only while more than one Hub is aggregated
```

Properties, each a test:

- **Solo and scoped:** `lux :: Beads`, `vox :: Vox`. One session is not a
  reason to hide whose window it is.
- **Two sessions, one repo:** `lux :: Vox` and `lux (2) :: Vox`.
- **Two applets of one session:** `lux :: Beads` and `lux :: Vox` (DES-067
  gives them one label).
- **Unscoped (anonymous `show()`, or an owner the Hub cannot name):** the plain
  title, exactly as today. Absence has one meaning, shared with
  `frame_owner_facts`.
- **Two Hubs:** `pembroke :: lux :: Vox`. The Hub rung keeps DES-089's rule:
  elided while one Hub is connected.
- **Visibility is ignored.** There is no peer set to be affected by a closed or
  docked frame, so DES-088's concern (closing one panel must not rename
  another) holds by construction.

| Hubs | Frame has a label | Title |
|------|-------------------|-------|
| 1 | no | `Vox` |
| 1 | yes | `lux (2) :: Vox` |
| 2 | no | `pembroke :: Vox` |
| 2 | yes | `pembroke :: lux (2) :: Vox` |

Two Hubs minting the same label never interact: nothing counts across frames.
The Hub rung's own `pembroke (2)` numbering is untouched.

### Wire change

`SceneMessage` gains one field in the frame spec (not the scene — a frame has
one title, so it has one scope):

```python
frame_scope_label: str | None = None
```

Codec: `_strip_none` omits it when absent. `decode` accepts a non-empty `str`;
anything else (non-string, empty) decodes to `None` and logs a warning,
exactly as `_parse_owner_facts` degrades. No version bump. An old Hub with a
new Display, or the reverse, decodes the field as absent and the title stays
plain: additive, not breaking.

**Optional, not required, and why this is not the `hub_id` mistake.** DES-089
made `hub_id` required because every connecting `kind` could supply it, so
`None` meant nothing. The question is the same here: what does an absent value
mean? It has one honest meaning, shared with `frame_owner_facts`: the Hub has
no name for this frame's owner right now (the owner is unidentified, since
only identified sessions are named, or departed between snapshot and push). A
sender genuinely cannot always populate it. A required `str` with `""` for
"none" is `Optional` with a sentinel and is rejected.

**Rejected wire shapes.** A scope key beside the label (the stable key is
already the leading segment of the composed `frame_id`; a second key is a
second identity to drift). The label on the scene rather than the frame (a
frame composes scenes from several connections; a per-scene label would let the
title follow whichever scene was sent last, the defect `CanonicalFrameOwner`
exists to prevent). A Hub-composed full title (duplicates `LuxAddress` and
cannot see the Hub rung).

### Hub change: one call, one owner, two answers

Extend the existing owner resolution rather than add a parallel one.
`FrameOwnerFactsReader.facts_for_frame(frame_id)` becomes one call returning
one value, `FrameOwnership(rows, scope_label)`, both resolved from the frame's
canonical scene (`CanonicalFrameOwner._canonical_scene`) and its
first-appearance owner. Two port methods would resolve the canonical scene
twice and could answer from different owners if a scene departed between the
calls.

`FrameOwnerFacts.facts_for` already reads `named = clients.named(...)` once;
`scope_label` is `named.name` from that same read, so the two answers cannot
disagree. `None` for both when the owner holds no live named session. The Null
Object returns `FrameOwnership(None, None)`. `SceneSnapshot.push` passes both
onto `ScenePresentation.push` and `DisplayLink.send_scene`, which fill
`frame_owner_facts` and `frame_scope_label`. The port rename is a rename train
inside one repo: no alias, every caller changes.

### Display change

The label lives on `Frame` as `scope_label: str | None`, next to `title`.
`FrameBook._adopt_presentation` already encodes the rule "an omitted field
means leave it, never reset it"; the label joins it.

- **Adopt on a framed scene** (`FrameBook._born` and `_adopt_presentation`): a
  push carrying a label sets it; a push carrying `None` leaves the last one.
  This is the departure guarantee `OwnerFactsCache` gives the rows: the Hub's
  `None` for a departed owner never blanks a title.
- **Carry on eviction** (`SceneEviction.from_frame`): when the removed scene
  was the frame's oldest, the frame takes the Hub's word for the label,
  including `None`, exactly as it does for the rows; otherwise the label is
  untouched. `SceneDeparture.of_empty_push` passes the empty push's
  `frame_scope_label` where it passes `frame_owner_facts`, and
  `from_other_frame` passes `None`, as it does for the rows.
- **No new store.** The earlier draft added a `FrameScopeStore` and generalised
  `OwnerFactsCache` into a `HeldValue[T]`. The always rule removes the reason:
  the label needs no cross-frame lookup, and a field on the frame is disposed
  with the frame, so there is no prune to forget. A parallel store would
  duplicate `adopt`, `prune` and the carry at four call sites for a value that
  is one string.
- **`LuxAddress.title`**: the `connection_ambiguous` parameter is renamed
  `connection_shown` and means "this frame has a label". The docstring changes
  from "only genuinely ambiguous rungs are shown" to: the Hub rung is shown
  when ambiguous, the connection rung when labelled. A rename train; the five
  call sites in `test_lux_address.py` change with it.
- **`AddressBook`** loses `connection_ambiguous(hub)`. It counted the wrong
  cardinality and now has no caller. `note_connection` and
  `forget_connection` stay: they track Hub liveness and label retirement.
  `address_for` already accepts a connection label; `AddressRendering` passes
  the frame's.
- **`AddressRendering.frame_title(frame)`** builds the address with the
  frame's label as the connection rung and passes
  `connection_shown=frame.scope_label is not None`. `title_for` stops
  hard-coding `False`. It is the one seam for every frame title.
- **Every frame title goes through that seam.** `windows_menu.py:110` and
  `dock_pill.py:55,79,83` read raw `frame.title` today, so they show neither
  rung. `WindowsMenu` takes the seam as a `Callable[[Frame], str]` (the pattern
  `FrameInfoPopup` already uses for `frame_for`), and `DockPill.at` takes the
  title string the dock bar computed. Note this newly gives both surfaces the
  Hub rung too; that is the intended consequence of DES-089's "one seam". The
  `i` popup and `query_dispatcher.py:120` keep the base title and add
  `scope_label`, so agents can introspect both.
- **A guard test** (like `test_per_frame_tracing.py`): no display module other
  than the seam reads `Frame.title` for display.

### Details window titles (DES-099)

The callback-less Details frame is installed with `owner=connection`, so its
canonical owner is the connection itself and its label is that connection's
roster name. The window therefore reads `lux :: z-spec`, `ethos (2) ::
z-spec`, Hub-prefixed across Hubs. This is the missing half of DES-099's
"built by the Display's `AddressBook`", and the clause DES-100 amended
("a rung elided whenever unambiguous").

### Label churn

Labels move only through `ClientRoster.release` (a group's last member
departs, its base goes to the senior numbered survivor) and arrive through
`names_for` (a connection first named). Both happen under the registry lock in
`hub_clients.py`.

- `ClientRoster.release` returns the survivors whose held label changed (a diff
  of `held()` before and after). `HubClientRegistry.discard` and
  `reap_lapsed_locked` return that set.
- `ClientLifecycle.depart` and `depart_lapsed` receive it and ask
  `MenuPresence` to mark every scene those connections own dirty, using the
  `OwnerTracker` they already hold (`keys_for`). `MenuPresence` is the right
  owner: a label move is a roster-name change, the event the menus already pay
  for. The registry lock is released when `discard` returns. The dirty signal
  is a leaf (DES-101), and `arriving_as` already marks dirty under the store
  lock, so this adds no lock edge.
- **Identification** marks the connection's own scenes dirty when its identity
  changed. `SessionWrite` already holds `before` and `after`; it gains an
  `identified` property (the identity differs). The registry's `record` and
  `attach` return the `SessionWrite` instead of only its `PresenceChange`, and
  `ClientLifecycle._announce` reads both from it. Presence cannot be the
  trigger: a repo-kind client that registers no callback earns no menu entry,
  so presence is unchanged, yet it has just been named. Identity is
  idempotent per REST request, so the mark fires once per real change, not once
  per request.
- Only a real change marks anything. A departure that moves no label marks
  nothing, and a plain `show()` resend carries the current label and the
  Display's adoption of an equal value is a no-op.

DES-088: a label rides the same full-scene resend as any content change. It
writes `Frame.scope_label` and nothing on placement. A test pins that a
label-moving resend leaves a closed frame closed, extending
`test_a_replace_leaves_a_closed_frame_closed`.

## Part B — Client host and Hub host (DES-099 amendment)

### The two facts

- **Client host** is the peer address the Hub *observed* on the connection's
  transport at connect: `127.0.0.1` or `::1` for a local client, the remote
  address otherwise. It is the address string as the socket reported it. It is
  never read from a header, a declaration, or reverse DNS.
- **Hub host** is the frame's `HubId.hostname`. Its source in this design is the
  Hub's own `HubId.current().hostname`, computed once at composition.

Both are rows: `("Client host", ...)` and `("Hub host", ...)`, placed after
`Connection` in `ClientDetails.rows()`. That single method feeds the `i` popup
(through `FrameOwnerFacts`) and the Details scene (through `DetailsScene`), so
the two can never disagree, and the Display needs no change: it renders the
rows it is given. No new message, no new mechanism.

### Where the observed address is captured

Luxd has three client doors. Each already reads the caller's identity there,
and each framework object already carries the observed peer as Starlette's
`HTTPConnection.client`: the address of the accepted TCP socket.

| Door | Where the peer is read | How it reaches the Hub |
|------|------------------------|------------------------|
| MCP streamable HTTP | `McpAsgiApp.__call__`: `Request(scope).client`, beside the `session_key` it already reads | A second `ContextVar` bound with the session key (`bind_session` takes the peer and `unbind_session` releases both tokens). The MCP session task is spawned inside the `initialize` request's context, so the peer is the one observed at connect, as the key already is. `tools/tools.py:_scope()` builds `Scope(connection, peer_host)`. |
| REST | `RestCaller.resolve`: `request.client` | `Scope(connection, peer_host)`; `session_identify_command` already carries `scope` to `IdentityOperations.identify`. |
| WebSocket listen leg | `HubListenTransport._endpoint`: `websocket.client` | `HubListenSession` takes `peer` and passes it to `ClientLifecycle.attach` and to the per-frame `identify`. |
| Hub-to-Display (cross-host) | Nowhere. See below. | Not applicable. |

**The cross-host Hub-to-Display leg captures nothing, by design.** On that leg
the Hub is the party being identified, not a client of the Hub. The Display
already holds the verified fact: DES-090's Gate 2 rejects a connection whose
`hub_id` hostname differs from the mTLS certificate's SAN. The client host is
Hub-observed and rides the owner facts to the Display; the Display never
observes a client's address and must not guess one.

**`Scope` carries the peer.** `Scope` is already the per-request carrier of
who the caller is and is built at exactly the doors that matter. It gains
`peer_host: str | None = field(default=None, compare=False)`. `compare=False`
because the peer is a fact about this contact, not part of the scope's
identity: two scopes for one connection must stay equal. The in-process client
library (`client/facade.py`, `cli/_shared.py`) builds `Scope` without it and
is unaffected. The alternative, a new `peer` parameter threaded through
`facade.identify`, `SessionOps`, the command and the tool, touches four
signatures to carry what one defaulted field carries.

`None` is a genuine absence: Starlette's `client` is `None` when the server
reports no peer. Those contacts record nothing.

**Do not read forwarding headers.** Uvicorn's `proxy_headers` defaults to
true, and with its default `forwarded_allow_ips` of `127.0.0.1` it rewrites
`scope["client"]` from an `X-Forwarded-For` header sent by any loopback caller.
That would turn a client declaration into the "observed" address. The design
sets `proxy_headers=False` on the `uvicorn.Config` in `luxd.py`, with a
comment, and a test that a request carrying `X-Forwarded-For: 10.9.9.9` is
recorded as its socket peer. luxd has no reverse proxy in front of it.

**Today every observed host is loopback.** `LoopbackTransportPolicy` refuses
any off-loopback bind, so MCP, REST and the listen leg only ever see
`127.0.0.1` (or `::1`). The field is built to be correct the day that policy
loosens, but the doc is honest about what it reports now: a client reaching
luxd through an SSH port-forward is observed as `127.0.0.1`, because that is
the transport the Hub sees. "Observed" is precisely that and no more.

### Where it is stored

On `ClientSession`, as `peers: tuple[str, ...]` (the distinct hosts observed,
in first-seen order), with `observed_from(host: str | None) -> ClientSession`
that returns a session with `host` appended unless it is `None` or already
present. Every method that rebuilds a session (`renewed`, `with_identity`,
`with_callback`, `attached`, `detached`) carries `peers` forward. No lock
changes: the registry's lock already guards every session write.

Rejected: a side map in the registry keyed by connection (a second structure
to keep in step with the session map and the departure cascade, for a value
that is born and dies with the session); a field on `ClientIdentity` (it is a
declaration, validated and hashed into the connection id; mixing in an
observation breaks "never a client declaration").

### Flow into the facts (DES-101 shape)

```text
door ──Scope(peer_host)──▶ IdentityOperations.identify ──▶ ClientLifecycle.identify(conn, identity, peer)
WS   ──peer────────────────────────────────────────────▶ ClientLifecycle.attach(conn, identity, listener, peer)
                                   │
                  HubClientRegistry.record / legs.attach (SessionWrite.recorded / attached)
                                   │   ClientSession.observed_from(peer)
                                   ▼
ClientListing._client(entry) ──▶ HubClient(client_hosts=[...], hub_host=...)
                                   ▼
ClientIdentityFacts.build() ──▶ ClientDetails(client_hosts, hub_host) ──▶ rows()
                                   ▼                                           ▼
                       FrameOwnerFacts (i popup)                  DetailsScene (Details)
```

- The write goes through `ClientLifecycle`, as DES-101 requires.
  `IdentityOperations` and `HubListenSession` already hold the class
  (`ClientLifecycle`); neither gains a `HubDisplay` member. `identify` and
  `attach` each take one more argument; `arrive` does not. An anonymous
  contact has no facts to render (only named sessions have an `i` popup), so
  recording the peer where an identity is declared is sufficient.
- The read goes through `ClientListing` over `HubClientRegistry`, as both
  readers already do. `HubClient` gains `client_hosts: list[str]` and
  `hub_host: str`; `ClientIdentityFacts` and `ClientDetails` take them from
  the `HubClient` they already receive. `FrameOwnerFacts` and `DetailsScene`
  do not change.
- `hub_host` reaches `ClientListing` as a fifth constructor argument from
  `HubPorts` (`ports.hub_host`), set once by `HubComposition.ports()` through
  a cached `HubComposition.hub_host()`. It is computed once, in composition,
  because `HubId.current()` calls `socket.getfqdn()`, which can resolve DNS
  and must not run per push or at import. `ClientListing` is built in three
  places (`facade.py`, `frame_owner_facts.py`, `client_details_port.py`), all
  from `ports`.
- `hub_host` appears on every `HubClient`. The redundancy is tens of bytes
  and is meaningful for introspection ("which Hub holds this session"); the
  alternative, threading a Hub-wide string through `FrameOwnerFacts`,
  `ClientDetailsOperations`, `DetailsScene` and `ClientIdentityFacts`, touches
  four classes to avoid it.
- An unobserved client reports `Client host: unknown`. It is not `none`
  (which in this table means a genuinely absent optional such as a
  repository): the host exists, the Hub did not observe it. It is never
  defaulted to `127.0.0.1`.

### Hub host: why the Hub's own value is the verified one

The ruling says the Hub host is the frame's `HubId.hostname`, transport-verified
for a cross-host Hub. The Display holds that `HubId` per frame, so the popup
could append it Display-side. This design does not, for two reasons. A
Display-side row would give the popup one source and the Hub-built Details
table another for the same label. And the two values cannot diverge on a live
connection: DES-090's Gate 2 rejects the connection outright when the Hub's
declared hostname does not match its certificate SAN, and over the `AF_UNIX`
leg the `0700` socket directory is the trust argument. So the hostname the Hub
reads from `HubId.current()` is, for every Hub the Display accepts, the
verified hostname of the frame's `HubId`. A test pins this: the composed
`hub_host` equals `HubId.current().hostname`, which is what
`HandshakeConnector` declares.

If the leader prefers the literal reading (the popup's row taken from
`frame.hub.hostname` on the Display), it is a three-line change in
`FrameInfoPopup`'s caller and costs only the two-source divergence above. I am
recording this as a reading, not a fork.

### One identity, several transports (DES-057)

REST and the WebSocket leg of one identity resolve to one connection id
(`connection_for`). Both contacts record their peer against that one session,
and `observed_from` keeps the distinct hosts in first-seen order. A client
that connects over REST and the WebSocket from one machine reports one host:
`Client host: 127.0.0.1`. The same identity connecting from two machines
(possible only once the bind policy loosens, and already conflated into one
connection by DES-057's identity derivation) reports both:
`Client host: 10.0.0.5, 127.0.0.1`.

Two alternatives were considered. First observed wins: arbitrary, and it would
hide a second machine behind the first. Last observed wins: it flaps between
machines on a client that uses both. A set is the only answer that is neither
arbitrary nor a loss of information, and it is one tuple, not a new type.

The MCP door has one wrinkle that follows from DES-057, not from this design:
sessions sharing a `session_key` share one connection (`SessionKey`), and the
peer recorded is that of the request that created the first session task.

## Cross-repo impact

Hub-to-Display, plus an additive field on `HubClient`. `SceneMessage` is built
by `DisplayLink` inside luxd; a search of `vox/src` and `z-spec/src` finds no
`SceneMessage`, `ClientList` or `HubClient` consumer. Both talk to the Hub
through REST, MCP and the library, and never to the Display. The new fields
are additive and optional, so no coordinated release is needed and the
cross-repo breaking-change protocol is not triggered.

## z-spec determination

**Not required.** Per the lux rule (concurrency, lock discipline, stateful
protocol, or a recurring defect class), none applies:

- No new lock and no new lock edge. The label and peer are written in
  registry writes that already hold the registry lock; the dirty marking runs
  after the registry lock is released and takes only the leaf dirty signal
  (DES-101).
- No new interleaving class. A label read at push time races a concurrent
  departure, and converges by the argument that already governs menus: every
  label-moving change marks its owners dirty after committing, and the later
  push reads the registry fresh. `menu_lifecycle.tex` and `hub_replicator.tex`
  model the dirty-then-fresh-read discipline this reuses. The observed peer is
  write-once per host and append-only; a stale read shows a shorter list.
- No state machine: the Display side is a pure function of the frame's own
  fields.
- The recurrence signal has not fired: this is the first round on this defect.

A roundtrip-plus-convergence test is the right instrument.

## Implementation write-set

The implementation mission decides final names; each concern below must land.
Grouped by commit (next section).

### Hub label path

- `protocol/messages/scene.py`, `scene_codec.py`: `frame_scope_label`.
- `domain/hub/frame_owner_facts.py` (the port and its Null Object, now
  returning `FrameOwnership`), `scene_snapshot.py`, `scene_presentation.py`,
  `display_link.py`: carry it.
- `operations/frame_owner_facts.py`, `operations/canonical_frame_owner.py`:
  resolve both answers from the canonical owner in one call.

### Display title path

- `display/replica/frame.py`, `frame_book.py`, `scene_eviction.py`,
  `scene_departure.py`: `Frame.scope_label` and its adopt and carry rules.
- `display/replica/lux_address.py`, `address_book.py`, `address_rendering.py`.
- `display/menus/windows_menu.py`, `display/dock_pill.py`,
  `display/query_dispatcher.py`, and the one place `render_loop.py` wires the
  seam into the first two.

### Label churn

- `domain/hub/client_roster.py`, `hub_clients.py`, `session_write.py`,
  `client_lifecycle.py`, `menu_presence.py`.

### Observed host

- `domain/hub/client_session.py`, `session_write.py`, `hub_clients.py`,
  `listener_legs.py`, `client_lifecycle.py`.
- `operations/scope.py`, `operations/identity.py`.
- Doors: `mcp_endpoint.py`, `tools/server.py`, `tools/tools.py`,
  `rest/identity.py`, `ws_transport.py`, `ws_listen.py`, and `luxd.py`
  (`proxy_headers=False`).

### Host rows

- `operations/models/query_clients.py`, `operations/client_listing.py`,
  `operations/client_identity_facts.py`,
  `protocol/compositions/client_details.py`, `operations/ports.py`,
  `hub_composition.py`.

**Docs** (the leader authors `DESIGN.md` and `CHANGELOG.md`):
`docs/architecture/system.tex` §Addressing (the "scope label does not reach
the Display" note and the per-surface table) and `CHANGELOG.md`.
`.oo-baseline.json` and `.oo-audit.jsonl` move only through the leader's
`make update-oo`; the implementer writes no ratchet file.

## Predicted metric movement

The ratchet metrics are signals, not targets, and I have not run the scorer.
This is a prediction from the shape of the diff.

**Files that grow** (a parameter, a field, a few lines each): `client_session.py`
(a field and `observed_from`, plus five constructor calls that carry it),
`session_write.py`, `hub_clients.py`, `listener_legs.py`, `client_lifecycle.py`
(`identify` and `attach` gain an argument; relabel marking adds a method),
`menu_presence.py`, `client_roster.py`, `scope.py`, `tools/server.py`,
`ws_listen.py`, `query_clients.py`, `client_listing.py` (five constructor
parameters), `client_details.py`, `frame.py`, `scene_eviction.py`,
`scene_departure.py`, `frame_owner_facts.py` (domain and operations),
`scene.py` and its codec, `windows_menu.py`, `dock_pill.py`.

**Files at risk of a cap or ratchet regression, and what to do about it:**

- `client_lifecycle.py`: it gains a method and two parameters, and its LCOM
  is the metric to watch. Marking belongs on `MenuPresence`, not on the
  lifecycle, to keep it from absorbing a second concern.
- `render_loop.py` (about 1,100 lines, over its 300-line target): wiring the
  title seam into the Windows menu and dock bar must not grow it. If it does,
  the implementer extracts in the same commit; the file's own rule rejects the
  PR otherwise.
- `hub_clients.py`: `record` and `attach` change return type. Keep the change
  to the return value; do not add a method.

**Files that shrink or simplify:** `address_book.py` (loses
`connection_ambiguous`), `lux_address.py` (`title` stops needing a second
ambiguity input), `address_rendering.py` (a hard-coded `False` becomes the
frame's own fact). The `connection_key` set inside `AddressBook._connections`
is now read only for liveness; narrowing it is a candidate for the ratchet's
"at least one improved" requirement, not an obligation of this design.

No file in this design needs a new abstraction beyond `FrameOwnership` (a
two-field value the port needed to avoid two calls). I expect the commit that
removes `connection_ambiguous` to carry the improvement the ratchet asks for.
The implementer should not manufacture one elsewhere.

## Test plan

### Happy

- Wire roundtrip (`tests/test_protocol.py`): `frame_scope_label` present
  roundtrips; absent produces no key.
- Title: solo scoped `lux :: Beads`; two sessions in one repo `lux :: Vox` and
  `lux (2) :: Vox`; two applets of one session `lux :: Beads`, `lux :: Vox`;
  two Hubs `pembroke :: lux (2) :: Vox` (the four-row table above).
- Windows menu and dock pill show the same title as the window.
- Label follows departure: sessions `lux` and `lux (2)`; the first departs;
  the survivor's scenes are marked dirty, the resend carries `lux`, and the
  title reads `lux :: Vox`.
- Identification: scenes shown before identification (no label) are resent
  with it once the connection is named, including a repo-kind client that
  registers no callback.
- Canonical owner: a frame of scenes from two connections carries the oldest
  scene's owner's label on every scene send, and rows and label come from the
  same owner (the one-call port).
- Host rows: a REST-identified client reports `Client host: 127.0.0.1` in both
  the popup rows and the Details table, and `Hub host` equals
  `HubId.current().hostname`.
- Per door: MCP, REST and the WebSocket leg each record their socket peer
  (an IPv6 loopback `::1` case for one of them).
- One identity, several transports: REST then WebSocket from one host reports
  one host; a second distinct host appends in first-seen order; repeats do
  not duplicate.

### Invalid

- `frame_scope_label` non-string, empty, or `7`: decoded to `None`, a warning
  is logged, the title stays plain.
- A request carrying `X-Forwarded-For: 10.9.9.9` records its socket peer, not
  `10.9.9.9` (`proxy_headers=False`).
- A client declaring a host in its identity fields: nothing reads it; the
  recorded host is the observed one.

### Boundary

- An anonymous `show()` (no owner): plain title, no `i` rows.
- A departure that moves no label marks no scene.
- Identification repeated per REST request marks once, not once per request.
- A label-moving resend leaves a closed frame closed and moves neither
  `active_tab` nor cascade slot (DES-088).
- A `None` from a departed owner leaves the frame's last label in place; an
  empty push for the oldest scene takes the Hub's word, including `None`.
- Two Hubs sharing a frame id and a label do not cross-contaminate.

### Missing dependency

- `ASGI client` is `None`: the contact records nothing, and the row reads
  `Client host: unknown` (never `127.0.0.1`).
- The reader is not yet bound (`NoFrameOwnerFacts`): `FrameOwnership(None,
  None)`; a send before composition still works.
- An old Hub (no `frame_scope_label`) with a new Display: plain titles, no
  error. A new Hub with an old Display: the unknown field is ignored.
- `HubPorts` built without a `hub_host` is a type error (a required field),
  not a silent default.

### Guards

- No display module other than the seam reads `Frame.title` for display.
- `AddressBook` has no `connection_ambiguous`.

**Demo** (`make restart`, expected result written first). Open a second Claude
session in the same repo; run Vox and Details in both. `list_frames` and
`inspect_scene` show both `scope_label`s, and `make screenshot` shows
`lux :: Vox` and `lux (2) :: Vox`; Read the PNG. Open the `i` glyph: `Client
host: 127.0.0.1` and `Hub host` is this machine's FQDN. Close one session:
within one replication cycle the survivor reads `lux :: Vox` and a window the
user had closed stays closed. Invalid input: a payload with
`frame_scope_label: 7` is logged and ignored. Boundary: a frame from an
anonymous `show()` has no rung.

## Commit order

Each commit leaves `make check` green on its own.

1. **Hub carries the label.** Wire field and codec; `FrameOwnership` in the
   port, Null Object, canonical owner and facts reader; snapshot,
   presentation and link carry both. Tests: codec, canonical owner, one-call
   consistency. The Display receives the field and ignores it.
2. **Display shows the label.** `Frame.scope_label` with adopt and carry;
   `LuxAddress.title` rename; `AddressBook.connection_ambiguous` removed;
   `AddressRendering`, Windows menu, dock pill, query dispatcher; the guard
   test. Titles read `label :: title`. This is where the improvement the
   ratchet asks for should land.
3. **Labels follow the roster.** `release` returns moved survivors;
   `SessionWrite.identified`; `record` and `attach` return the write;
   lifecycle marks relabelled and newly identified connections' scenes dirty
   through `MenuPresence`. Tests: departure, identification, no-op cases,
   DES-088.
4. **The Hub observes the peer.** `ClientSession.peers` and `observed_from`;
   the registry writes; `ClientLifecycle.identify` and `attach`;
   `Scope.peer_host`; the three doors; `proxy_headers=False`. Nothing reads
   the field yet. Tests: per door, forwarding header, `None` peer, several
   transports.
5. **The facts report both hosts.** `HubClient`, `ClientListing`,
   `ClientIdentityFacts`, `ClientDetails.rows()`, `HubPorts.hub_host` and its
   cached composition. Tests: rows in popup and Details, `Hub host` equality,
   `unknown`.

Then the leader's docs commit (`system.tex`, `CHANGELOG.md`, and the
`DESIGN.md` pointer), the ratchet blessing, and the demo. Commits 1 to 3 are
Part A (DES-100) and 4 to 5 are Part B; they share the owner-facts path but
not each other's code, so a failure in one half does not block the other, and
each half reverts on its own.

## Rejected, in one place

- Showing the connection rung only on a title collision (DES-089's elision;
  the first draft of this design). Superseded by DES-100.
- A `FrameScopeStore` and a generic `HeldValue[T]`: the label has no
  cross-frame lookup, and a frame field is disposed with the frame.
- A Hub-composed full title; a per-scene label; a scope key beside the label;
  a required `str` with `""` for none; polling the roster for label changes.
- A client-declared hostname, and reverse DNS at connect (the DES-099 ruling's
  own rejections).
- Threading `peer` as a fourth parameter through the identify chain, instead
  of a defaulted `Scope` field.
- A side map for peers, and a peer field on `ClientIdentity`.
- First- or last-observed-wins for a multi-transport client.
- A Display-side `Hub host` row in the popup (two sources for one label).
- A reverse proxy's `X-Forwarded-For` as the "observed" address.

## Notes for the leader

None of the following blocks the design; each is a judgment the ADRs leave to
the designer, recorded so the evaluator can overrule it.

1. **Hub host is Hub-built, not Display-appended.** Argued above from Gate 2.
   The literal reading of the ruling is a three-line alternative.
2. **`Scope.peer_host` with `compare=False`.** Chosen over a threaded
   parameter. It adds an optional field to a frozen dataclass whose other
   fields are identity.
3. **`proxy_headers=False` is a config change to luxd** forced by "never a
   client declaration". It has no effect on current clients (no proxy).
4. **Today the host is always loopback.** True of the doors until
   `LoopbackTransportPolicy` loosens; no ADR changes that here.
5. **`DESIGN.md` has no entry for the peer capture or the label field's
   home.** The DES-099 amendment and DES-100 already state the outcomes; this
   document is the specification. Say if you want a DES-102 for the
   `proxy_headers` decision.
