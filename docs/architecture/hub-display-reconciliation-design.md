# Hub/Display Scene Reconciliation on Identify

- **Status:** proposed for DES-068; the three ratification-required decisions listed at the end received operator ruling on 2026-08-15 (all three recommendations accepted). Implementation is a separate, later mission tracked under `lux-e9vy`.
- **Proposed ADR number:** DES-068 (next after DES-067).
- **Author:** gvr, design mission `m-2026-08-15-004`.
- **Evaluator:** rmh.

## Abstract

Killing and restarting `luxd` drops its in-memory `HubDisplay` — the Hub's
only copy of what scenes exist. The Display was never told to forget
anything, so it keeps rendering the scenes the dead `luxd` last sent it.
Nothing will ever correct this: the fresh `luxd` has no record of those
scenes and no reason to resend them. Selection and scrolling on the ghost
scenes keep working, because that is Display-local widget state; clicks that
require a Hub-side handler dispatch into an owner file descriptor that maps
to nothing, and silently do nothing. The bug heals only if some other agent
happens to redraw the same scene id. This document proposes **manifest-on-
identify with single-owner preemption**: the Hub, immediately after every
successful connect to the Display, declares the complete set of scene ids it
currently holds as authoritative; the Display purges every scene not on that
list; and at most one connection may hold the Hub's declared identity at a
time, so a restart cannot leave two live claimants fighting over the same
scenes.

## The invariant

> After a connection carrying the Hub's declared identity completes a
> connect and its manifest has been processed, every scene the Display
> still holds is either (a) named in that manifest or (b) owned by the
> identifying fd itself. No other scene survives — including scenes the
> Display cannot attribute to any live connection (orphans, reassigned to
> `_ORPHAN_FD` by `reassign_scenes_of` after their prior owner
> disconnected), because those are exactly the ghosts this design closes.

This refines the bead's target ("the Display's set of scenes converges to
the Hub's authoritative set after a Hub client identifies") in one way worth
being explicit about: convergence is not "wait and it will match eventually."
It is a hard cutover at manifest-receipt time, because nothing else will ever
correct a scene the fresh Hub does not know to resend.

## Current mechanics (what actually happens today)

Traced against the code as of 2026-08-15, not the target docs:

1. **`HubDisplay` is memory-only, by design** (post-B7; see
   `src/punt_lux/domain/hub/hub_display.py`). A `luxd` process restart
   constructs a brand-new `hub_display` singleton with zero scenes,
   zero clients, zero owners. Nothing on disk backs it. This was a
   deliberate architectural choice, not an oversight — persisting
   `HubDisplay` across restarts is explicitly the rejected alternative in
   the bead, and rightly so (see Alternatives Rejected).

2. **`luxd` holds exactly one socket connection to the Display**, via
   `ClientRegistry` (`src/punt_lux/domain/hub/clients.py`), which lazily
   constructs and reconnects a single `DisplayLink` under the name
   `"lux-mcp"` (`_DISPLAY_CLIENT_NAME`, `clients.py:25`). Every scene that
   reaches the Display — from any agent, any REST caller, any applet's
   push through `luxd` — flows over this one connection. There is no
   other writer (`HubReplicator` is the sole background sender,
   `domain/hub/replicator.py`).

3. **The Display never distinguishes "the same Hub reconnecting" from "a
   different Hub process."** `DisplayLink._post_handshake`
   (`domain/hub/display_link.py:217`) sends a `ConnectMessage(name="lux-mcp")`
   after every low-level socket connect. `RenderLoop._handle_connect`
   (`display/render_loop.py:582`) records the name against the new file
   descriptor and does nothing else. There is no generation counter, no
   "here is what I hold" declaration, nothing that lets the Display tell a
   resumed process from a fresh one.

4. **A disconnect orphans scenes; it never removes them.**
   `SocketListener.remove_client` → `RenderLoop._on_client_disconnected`
   (`render_loop.py:532`) → `SceneReplica.reassign_scenes_of` (via
   `FrameBook.reassign_scenes_of`, `display/replica/frame_book.py:132`)
   reassigns every scene the departed fd owned to a surviving co-owner in
   the same frame, or to the sentinel `_ORPHAN_FD = -1`
   (`render_loop.py:79`) when none remains. The frame and its scenes stay
   installed and keep rendering. This is correct behavior for the case the
   comment on `reassign_scenes_of` documents — "scenes persist across a
   disconnect" — because a session's UI is meant to survive that session
   (`HubDisplay.drop_connection`'s docstring makes the identical claim on
   the Hub side). The bug is not that scenes persist; it is that nothing
   ever decides they should stop persisting once their sole possible owner
   is gone for good.

5. **Interactions on an orphaned scene fail silently, not loudly.**
   `InteractionDelivery._deliver_one` (`display/interaction_delivery.py:76`)
   resolves `owner_fd` via `scene_to_owner`, looks up
   `fd_to_client.get(owner_fd)`, gets `None` for an orphan, and returns
   `False`. The caller's contract is "stays queued for retry," but nothing
   will ever make `fd_to_client.get(-1)` succeed. `PendingInteractions`
   (`display/pending_interactions.py`) exists precisely to bridge *transient*
   Hub dropouts — it holds a click until `DEFAULT_MAX_AGE` and then evicts it
   with compensation. That machinery already works correctly for a brief
   network blip where the *same* `luxd` process reconnects. It cannot help
   here, because reconnecting does not restore what the click needed: a live
   owner for the scene.

6. **The existing recovery path already solves the opposite-direction
   problem, and solves it well.** `SendRecovery.recover`
   (`domain/hub/recovery.py:57`) — reap-and-respawn a wedged Display, or
   just reconnect to a dead one — always ends by re-marking every one of
   `HubDisplay.live_scene_ids()` dirty
   (`SendRecovery._remark`, `recovery.py:78`), so a Display that crashed and
   came back empty gets fully repainted from the Hub's still-intact memory
   within one coalesce cycle. This works because in that direction the
   Hub's memory is the one thing that did *not* get wiped. `lux-e9vy` is the
   mirror case — the Display's memory survives, the Hub's does not — and the
   existing machinery has nothing that runs in that direction at all.

The bead's own description — "heals only when a producer re-pushes" — is the
precise diagnosis. For a `luxd` process restart, no producer with knowledge
of the old scene will ever exist again. The healing condition is
unsatisfiable by construction, not merely unlikely.

## Why "sync-on-identify" as literally sketched does not work

The bead's fix-direction sketch — "Hub re-pushes its full scene set on
connect" — is the right instinct pointed at a store that, after the
restart that actually causes this bug, has nothing to push. A fresh
`luxd`'s "full scene set" is the empty set. Re-pushing it re-pushes nothing,
and the ghosts stay exactly as ghostly as before. Any design here has to
start from that fact: the Hub cannot tell the Display what to keep by
resending content it does not have. It can only tell the Display what it
*currently* has — which, on a genuine restart, is a manifest that is empty
or small — and let the Display act on the *absence* of a claim, not the
presence of a resend.

This reframes the three candidates from the mission's success criteria:

- **(a) SYNC-ON-IDENTIFY**, taken literally, does not fix the restart case
  (see above) — but a manifest-shaped version of it does, because a
  manifest carries a claim even when it is empty. This is what I am
  proposing, refined.
- **(b) HUB-SNAPSHOT-ON-CONNECT** is nearly the same idea under a different
  name — "a new wire message carries the Hub's scene manifest." I am
  adopting this framing explicitly: the new message is not a resend, it is
  a declaration of current holdings.
- **(c) BOUND-EXPIRY** (a generation token, stale scenes cleared after a
  bound) solves a real problem — giving the Display a way to tell "old
  Hub" from "new Hub" — but does it with a *timer*, which either fires too
  early (evicting a scene the new Hub was about to legitimately reclaim,
  mid-reconnect) or too late (a window where ghosts are still live and
  clickable). A manifest needs no timer: it is a synchronous, ordered
  message on the same connection as the identify, so there is no window to
  bound.

## Decision: manifest-on-identify with single-owner preemption

### The shape

1. **At most one connection may hold the Hub's declared identity
   (`kind="hub"`, a `name`) at a time.** When a new connection identifies
   with that identity, the Display forcibly disconnects any other live
   connection already holding it, before processing anything else from the
   new connection. This is the same "no two winners" property
   `display_lifecycle.tex` already proves for the socket-bind race,
   applied one layer up, to connection identity instead of the socket
   path. It closes the interleaving hazard below.

2. **A connection identified as `kind="hub"` sends its manifest immediately
   after `ConnectMessage`, before any `SceneMessage`.** The manifest names
   every scene id `HubDisplay.live_scene_ids()` currently holds — empty on
   a cold or post-restart connect, the full live set on an ordinary
   reconnect where the Hub process itself never died.

3. **On receipt of a manifest, the Display purges every scene not owned
   by the identifying fd AND not named in the manifest — one scene at a
   time, not one frame at a time.** A mixed frame (some scenes manifested
   or fd-owned, some not) keeps its qualifying scenes and loses only the
   ghosts; a frame emptied by this pass is closed by the same code path
   that already closes an emptied frame today. Per-scene removal uses
   `SceneReplica.dismiss_framed_scene` (already the shape for
   "one-scene-goes-away, frame may or may not survive"); the frame-level
   `_close_frame(frame_id, notify=False)` path
   (`render_loop.py:1027`) is used only when the pass empties a frame,
   and its `notify=False` branch — documented for exactly this shape
   ("disconnect cleanup where the departing client's fd is already
   removed and surviving clients should not be notified") but with no
   caller today — gets its first real caller here. Widget state discards
   for each purged scene as a side effect of `dismiss_framed_scene`
   (which already calls `self._widget_state.discard(scene_id)` per the
   existing per-scene close path); queued interactions for purged
   elements are dropped through the same `_notify_stale` →
   `_drain_stale_events` fan-out, no new plumbing.

4. **A scene the manifest names but does not yet own on the Display is left
   as-is, still attributed to whatever fd (possibly an orphan) it had.**
   Ownership self-corrects the moment the Hub actually resends that scene's
   content (`FrameBook.record_owner` runs unconditionally on every
   `handle_framed_scene`, `frame_book.py:153`, whether the scene is new to
   the frame or a replace). This is the case that matters for an ordinary
   reconnect after a network blip: nothing is purged, because the manifest
   names everything the Display is already showing, and the content
   refresh that was always going to happen (`SendRecovery._remark` already
   re-marks every live scene dirty on that recovery path) repaints it
   within one coalesce window. No flicker, no purge, for the common case
   this design must not regress.

5. **A `luxd` restart, concretely:** the fresh process connects, sends
   `ConnectMessage(kind="hub", name="lux-mcp")`, preempts nothing (the old
   connection is almost certainly already gone by the time anyone
   reconnects, since a killed process closes its sockets immediately), then
   sends `HubManifestMessage(scene_ids=())` — empty, because the fresh
   `HubDisplay` has nothing yet. Every frame on the Display, having no
   scene named in that empty manifest and no scene owned by the new fd,
   is purged in one pass. The screen goes blank exactly once, at the
   moment truth actually changed, rather than staying wrong forever. Any
   agent that calls `show()` again afterward gets the completely ordinary
   new-scene path — nothing about this design changes how a scene is
   created.

### Why the immediate purge is correct and not merely convenient

The natural worry about an unconditional, un-timed purge is: what if the
Hub was about to reclaim that scene and just hadn't gotten to it yet? The
manifest answers this directly, because it is not a hint, it is a
declaration of current truth sent by the one process authorized to make
that declaration. If a scene is not in the manifest, the Hub that produced
the manifest does not consider that scene live — not "doesn't yet," but
"as of the moment it looked, does not." There is no legitimate state in
which the Hub is about to reassert a scene it just told the Display, in the
same breath as identifying itself, that it does not hold. Target.md's
Replication Policy already states the rule this design is an instance of:
"the Hub wins every disagreement." A manifest is the Hub disagreeing with
whatever the Display currently believes, as loudly and as early as
possible.

## Alternatives rejected

**Naive purge-on-every-identify (no manifest, no scoping).** Purge
everything the moment any `kind="hub"` connection identifies, full stop.
This is simpler to state, but it breaks the ordinary-reconnect case: every
network blip would flash the screen to black and repaint, even though
nothing was ever actually wrong. The manifest costs one small message and
buys back that entire class of unnecessary disruption. Rejected because it
optimizes for implementation simplicity over the demo-gate reality — a user
watching the display during a routine `SendRecovery` reconnect should see
nothing happen.

**BOUND-EXPIRY (candidate (c), a generation token with a timeout).**
Considered seriously — see the reframing above. Rejected because it trades
a message (already required for other reasons — see the wire-protocol
section) for a timer, and a timer is strictly worse here: it introduces a
window where a genuinely-stale scene is still clickable (dispatches into
nothing, the exact bug this design fixes) and a second window, on the other
side of the same bound, where a legitimately-reclaimed scene could be
evicted out from under an in-progress reconnect if the bound is set too
tight. The manifest is synchronous and ordered on one connection; a timer
is neither.

**Persisting `HubDisplay` across restarts (rejected in the bead, and I
agree).** This would make "the fresh Hub's manifest is empty" untrue by
construction, sidestepping the whole reconciliation problem. It contradicts
the deliberate post-B7 decision that `HubDisplay` is memory-only, adds a
persistence format that has to stay in lockstep with the element schema,
and does not even fully solve the problem — a scene owned by a connection
whose owning *agent* process also died offers no guarantee its handlers are
still meaningful to re-run against a Hub that has since restarted. Scene
persistence is a much bigger, riskier change for a narrower win than
reconciliation.

**Routing reconciliation through the existing app-level pub-sub channel.**
Target.md is explicit that pub-sub topics are app-defined business events,
not system-level facts about connection identity (the same reasoning
DES-065 used to reject routing its notification signal through pub-sub).
"The Hub you were talking to is gone and a new one has arrived" is a
system-level fact about the Hub/Display leg, not a business event any app
defines. It belongs in the lifecycle message family, alongside `ConnectMessage`
and `ReadyMessage`, not in `ObserverMessage`.

## Wire-protocol change

Both changes land in `src/punt_lux/protocol/messages/lifecycle.py`, the
existing home for connection-lifecycle messages (`ReadyMessage`,
`ConnectMessage`, `AckMessage`, `PingMessage`, `PongMessage`,
`UnknownMessage`) — this is the same concern (identify and connect, not
scene content), so a new dataclass in the same module keeps the module
cohesive rather than starting a same-purpose sibling module.

**1. `ConnectMessage` gains a `kind` field.**

```python
kind: Literal["hub", "test"]  # no default — every caller declares explicitly
```

**Two variants, no default.** Every connection to the Display socket
declares its intent at identify time. `"hub"` is the writer identity
(singleton per name, preemption applies, manifest processed,
`SceneMessage` accepted) — the only caller is `luxd`'s
`ClientRegistry` (`domain/hub/clients.py`). `"test"` is the
read-only observer identity — query messages accepted (`list_scenes`,
`screenshot`, etc.), any `SceneMessage` from an test fd is
rejected with a named error surfaced to `list_errors` and the fd
closed. A connection that omits `ConnectMessage` entirely, or attempts
any other pre-scene traffic before it, is closed — no implicit default,
no ambiguous kind.

The absence of a `"direct"` writer variant is deliberate and reflects
the target architecture: per `target.md`, "a lux client never talks to
the Display." The only legitimate writer to the Display socket is
`luxd`; the only legitimate non-writer is a read-only inspector.
Anything else (an old-style `LuxClient` connecting straight to the
socket and pushing scenes the Hub never sees — the bug named in
`lux-s4wg`) was silently accepted before this design and is loudly
rejected after it. **This design closes `lux-s4wg` as a side effect.**

**2. A new `HubManifestMessage`, in the same module.**

```python
@dataclass(frozen=True, slots=True)
class HubManifestMessage:
    """The declaring Hub's complete, authoritative set of live scene ids.

    Sent by a kind="hub" connection immediately after ConnectMessage and
    before any SceneMessage. Empty on a fresh Hub-process restart; the full
    live set on an ordinary reconnect. On receipt, the Display purges every
    scene not named here AND not owned by the identifying fd — orphaned
    scenes from a prior Hub die (owner reassigned to _ORPHAN_FD) are
    swept by the same rule.
    """
    scene_ids: tuple[str, ...]
    type: Literal["hub_manifest"] = "hub_manifest"
```

Kept as its own message rather than a field bolted onto `ConnectMessage`,
because the two have different single responsibilities — "who I am" versus
"what I currently hold" — and only the latter needs to be resent-able
independent of identity in a hypothetical future (e.g., a periodic
resync); conflating them would force every future `ConnectMessage` reader
to reason about scene-id lists it does not care about.

**3. `SceneReplica` (`display/replica/scene_replica.py`) gains one new
read-only query**, in the same style as its existing `resolve_scene`,
`frame_of_scene`: given the identifying fd and the manifest's scene-id
set, return every `(frame_id, scene_id)` pair that qualifies for purge —
a scene qualifies when it is neither owned by the identifying fd nor
named in the manifest. The query performs no writes; the caller
(`RenderLoop`) drives the removal loop through
`SceneReplica.dismiss_framed_scene(frame_id, scene_id)` for each pair,
and `_close_frame(frame_id, notify=False)` fires (already the existing
behavior of the per-scene close path) exactly when a frame runs out of
scenes. Per-scene granularity means a mixed frame (some scenes ghosts,
some scenes legitimately manifested or fd-owned) loses only its ghosts,
not the whole frame.

**4. `SocketListener` (`display/socket_server.py`) needs to track
`(kind, name)` per fd, not just `name`.** `register_client_name` becomes
(or gains a sibling to) a call that records both, so `RenderLoop` can look
up "is any other live fd currently declared `kind="hub"`" for the
preemption step, and "is this scene's current owner fd a `kind="hub"`
connection" is no longer needed as a separate lookup once preemption
guarantees at most one exists.

**5. `RenderLoop` (`display/render_loop.py`) gains preemption-on-connect and
a manifest handler.** `_handle_connect` (`render_loop.py:582`), on a
`kind="hub"` identify, first finds and force-disconnects (via
`SocketListener.remove_client`) any other fd already declared `kind="hub"`
with the same `name`, *before* recording the new one — this is what makes
the "at most one Hub-kind connection at a time" invariant hold across the
message-ordering race described in Concurrency below. `_handle_message`
gains a branch for `HubManifestMessage`, calling the new `SceneReplica`
query and closing each returned frame id with `notify=False`.

**6. `ClientRegistry` (`domain/hub/clients.py`) gains one choke point for
"a fresh low-level connect just succeeded," used by both of its two
reconnect call sites (`get()`'s lazy connect and `with_reconnect`'s retry
connect) — today these are two separate call sites that could drift.
Consolidating them into one path is a correctness requirement, not a
nice-to-have: it is the only way to guarantee `ConnectMessage` and
`HubManifestMessage` are sent together, in order, on every path that
establishes a fresh socket, with no call site able to forget the manifest.
That path sends `ConnectMessage(kind="hub", name="lux-mcp")`, sends
`HubManifestMessage(scene_ids=hub_display.live_scene_ids())`, and marks
every one of those same ids (plus the menu) dirty on the replicator — the
same content-refresh `SendRecovery._remark` already performs for its own
recovery path. This also means `SendRecovery._remark`'s explicit re-mark
becomes redundant with the new connect-success hook for the paths that
route through `ClientRegistry`; the implementation should unify them
rather than keep two copies of "what happens right after a fresh connect"
in the codebase.

**Required OO cleanup riding along, not optional:** `lifecycle.py`'s codec
is still the old free-function shape (`_connect_to_dict` /
`_connect_from_dict` and siblings, `register_codecs`), unlike
`SceneMessage`'s already-migrated class-based `to_dict` / `from_dict`
(`protocol/messages/scene.py`). Lux's own CLAUDE.md already flags this as
the one remaining procedural corner in the message-codec migration ("fix a
message codec onto its class when you touch the file"). Any implementation
mission touching `lifecycle.py` for this change must migrate
`ConnectMessage`, `ReadyMessage`, `AckMessage`, `PingMessage`,
`PongMessage`, `UnknownMessage`, and the new `HubManifestMessage` onto
class-based codecs in the same PR — not add the new field to the old
procedural shape and leave the corner exactly as procedural as before.

## The client-identity dimension

**Two variants, no default, and no writer beyond `"hub"`.** The
`kind`/`name` pair on `ConnectMessage` is a *new*, minimal identity
dimension that exists purely on the Hub↔Display socket leg. It has
exactly two values: `"hub"` (the writer, singleton per name, only
legitimate producer of `SceneMessage`) and `"test"` (a read-only
observer, needed today only so tests can inspect a running Display
without spinning up a whole Hub around it). There is no third writer
variant. Per `target.md`, the Display serves exactly one producer —
`luxd` — and nothing else has any legitimate reason to push scenes
directly. Anything that tried before this design was silently accepted
(bug: `lux-s4wg`); after it, any `SceneMessage` from a non-`"hub"` fd
is rejected loudly.

The `"test"` name is deliberate: it announces what the mode IS,
namely a test-only backdoor. A production caller declaring
`kind="test"` reads as wrong at the call site instead of blending in
as an ambiguous "option." Alternative names like `"direct"` were
rejected precisely because they sound like a supported connection
mode — they aren't.

This identity is not the same thing as DES-057's `ClientIdentity`
(`kind: "mcp-session" | "cli" | "applet" | "app"`), and I am not
merging them. DES-057 identifies *who is talking to the Hub* — many
distinct agents, sessions, and applets, aggregated by the one Hub. The
identity this design adds identifies *who is talking to the Display* —
which, in the current architecture, is always exactly one writer
(`luxd`, representing the aggregate of everyone DES-057 already
distinguishes) plus a bounded set of read-only test observers.
Conflating the two would require every scene crossing the Hub→Display
leg to carry its original DES-057 owner's identity all the way
through, so the Display could do per-DES-057-identity purge scoping —
a materially bigger change, useful only once a second, independent Hub
process exists to purge separately from the first. That is explicitly
**future** scope (target.md's "maximum scope: many users with many
agent/app UIs aggregated by one Hub"), not `lux-e9vy`'s scope.

**What the deliberately narrow version still buys, for free:** because
purge scoping is keyed by `(kind, name)` rather than by raw fd or by "purge
everything," a second, *differently-named* Hub identity (a real
multi-tenant future) would already purge only its own prior incarnation's
scenes, never another tenant's — the design does not have to be revisited
to add that; it falls out of using `(kind, name)` as the scoping key
instead of `kind` alone. What genuinely is deferred is finer scoping
*within* one Hub's aggregate (per-agent purge rather than per-Hub-process
purge) — not needed to fix `lux-e9vy`, and not worth the wire-protocol
weight of threading DES-057 identity through every scene for a case that
does not exist yet.

**"Same Hub reconnected" versus "different Hub took over the socket."** In
the current single-process-per-name model, the Display cannot and does not
need to distinguish these — both cases identify with the same `(kind="hub",
name="lux-mcp")` pair, and the manifest already tells the Display exactly
what to do either way: purge what the manifest does not name, leave the
rest. The single-owner preemption rule (item 1 in the Decision) exists
precisely so this ambiguity is safe rather than a race — whichever
connection is currently declaring the identity is authoritative, and a new
one taking over immediately evicts whichever one it is replacing rather
than letting two connections both believe they own the name.

## The widget-state dimension

**Rule: widget state survives exactly as long as the scene's frame does,
and no longer.** This falls straight out of reusing `close_frame`
unchanged — `close_frame` already discards `WidgetStateStore` entries for
every scene it removes (`scene_replica.py:174`, `self._widget_state.discard
(scene_id)`), the same as a user-initiated frame close does today. A purged
scene's selection, scroll position, and in-progress text are gone. When
that scene id reappears later — because some agent called `show()` again,
possibly the fresh Hub reasserting exactly the same content it manifested
as absent a moment ago is not possible by definition, but a *new* `show()`
of the same id certainly is — `upsert_scene_in_frame` treats it as
genuinely new to the frame (`scene_replica.py:127`, `is_new = msg.id not in
frame.scenes`), which calls `self._widget_state.open(msg.id)` fresh. There
is no special-cased "restore the old widget state because it's the same
scene id as before" path, and there should not be one: widget state is
explicitly described in `target.md` as "opened and discarded with its
scene lifetime," and the scene's lifetime, from the Display's point of
view, just ended. A scene surviving a Hub restart with its scroll position
intact would be a coincidence of implementation, not a guarantee anyone
asked for.

## The announce-on-arrival dimension

**Rule: reconciliation-triggered re-appearance follows whichever rule is
currently authoritative for "new scene arrival" — DES-065, not DES-060 —
and must not reintroduce focus-steal.** After a purge, any scene an agent
subsequently shows again lands through the completely ordinary
`upsert_scene_in_frame` "new to this frame" path (same code as any other
first-time `show()`), which is exactly the path DES-060 gated to
unminimize/focus/select-tab, and exactly the path DES-065 (settled,
superseding DES-060, implementation tracked under `lux-mxvy`) retires that
behavior from — `show()` becomes a notification, never a window-raise. This
design adds no new "is this a reconciliation re-appearance" special case
and needs none: whatever DES-065's shipped state of `is_new` handling is at
the time this design's implementation lands, N scenes reappearing after a
restart get exactly the same treatment as N scenes appearing for any other
reason. There is a real sequencing dependency worth naming explicitly: if
this design's implementation merges *before* `lux-mxvy` retires DES-060's
focus-steal, a `luxd` restart followed by an agent re-populating several
scenes would currently unminimize and steal focus for each one in turn —
the exact user-hostile behavior DES-065 exists to kill, just triggered by a
restart instead of a routine update. This is not a reason to block this
design on `lux-mxvy`; it is a reason to flag the interaction so whichever
lands second does not silently regress the other's promise.

## The z-spec question — required

**Decision: z-spec is required for this design**, on two independent
grounds, either one of which is sufficient on its own.

**Ground 1 — this is a stateful protocol with an order invariant, which
CLAUDE.md's z-spec rule requires regardless of recurrence count.** The
core safety property — "purge for a given identify always completes before
any scene install attributed to the new connection is accepted" — is
exactly the "operations must follow order Z" shape the z-spec rule names
as REQUIRED on its own, independent of how many times a similar bug has
been seen before. It is not a hypothetical ordering concern: `SocketListener
.poll_clients` (`socket_server.py:173`) drains every readable client in one
`select()` pass per frame, in `self._clients` list order. If a straggling
`SceneMessage`, buffered in the OS receive queue from the *old*,
about-to-be-superseded Hub connection, is still unread at the moment the
new connection's identify and manifest are processed in the same frame,
the order those two fds are visited in decides whether that straggler:
(a) installs a scene, gets immediately purged by the manifest processed
right after it in the same frame — correct, if accidental — or (b) is
processed *after* the manifest, in which case it silently re-materializes
exactly the ghost the manifest just told the Display to forget (`FrameBook
.ensure`, `frame_book.py:79`, happily recreates a frame that was just
closed). Single-owner preemption (forcibly disconnecting the old fd as
part of processing the new identify) is what is supposed to close this
hole — the model has to prove it actually does, across every interleaving,
not just the one I traced by hand.

**Ground 2 — recurrence.** `lux-e9vy` and `lux-tfn1` (filed 2026-08-14,
still open) are two occurrences of the identical structural defect: a
registry keyed by a connection identifier goes stale when the identified
party dies or restarts, and the registry is used against that stale
identifier with no liveness check, silently. `lux-e9vy` is the Display's
`scene_to_owner` map going stale against a dead Hub fd; `lux-tfn1` is the
Hub's own dispatch registry going stale against a dead connection id on the
*other* leg of the same architecture. Two independent occurrences of "stale
connection identifier used silently" meets the bar the recurrence rule
sets for stopping empirical patching and formalizing. I am not proposing
this design's z-spec cover `lux-tfn1` as well — the fix mechanisms differ
enough (this is a Hub→Display leg; `lux-tfn1` is Hub-internal registry
hygiene) that one model covering both would be forcing a shared shape onto
two different state machines. But the recurrence is real, and it is the
second independent trigger for treating this specific design formally
rather than as another round of empirical testing.

**Schema, sketched (implementation detail for the mission that writes
`docs/hub_display_reconciliation.tex`, following the pattern of the
existing `hub_replicator.tex` / `hub_replicator_coverage.md` pair):**

- **Carrier:** a small bounded set of connection ids (2–3, enough to model
  "old Hub fd," "new Hub fd," and one unrelated `kind="test"` read-only
  connection) and a small bounded set of scene ids (2–3).
- **State schema:** `hubOwner : CONNECTION_ID` (partial — the connection
  currently holding `kind="hub"`, or undefined), `sceneOwner : SCENE_ID
  ⇸ CONNECTION_ID` (partial function; an orphan is simply absent from the
  domain or mapped to a distinguished `ORPHAN` value), `manifested :
  ℙ SCENE_ID` (the most recent manifest's contents).
- **Operations:** `HubIdentify` (a connection declares `kind="hub"`;
  preempts and disconnects any existing `hubOwner`), `HubManifest`
  (the current `hubOwner` declares `manifested`; every `sceneOwner` entry
  not in `manifested` and not owned by `hubOwner` is removed), `SceneInstall`
  (only ever attributed to the current `hubOwner`), `ConnectionDrop`
  (models both an ordinary disconnect and the preemption-triggered forced
  disconnect — `sceneOwner` entries pointing at the dropped connection
  become `ORPHAN`, not removed, matching `reassign_scenes_of`'s real
  behavior).
- **Invariants to model-check:**
  - **I1 (no-stale-owner):** every entry in `sceneOwner` is either owned by
    the live `hubOwner`, or is `ORPHAN` and present in the most recent
    `manifested` set (i.e., legitimately awaiting reclaim, not a ghost).
  - **I2 (only-live-hub-installs):** in every trace, a `SceneInstall` is
    accepted only when its source connection is the current `hubOwner`. A
    `SceneInstall` attributed to a preempted connection — one whose
    `HubIdentify` has since been superseded — is dropped, not applied. This
    is the ordering property single-owner preemption exists to close: a
    straggling `SceneInstall` still buffered from an old Hub connection
    cannot re-materialize a scene the new Hub's manifest just purged,
    because by the time it would be processed, its source is no longer the
    `hubOwner`. Normal post-restart traffic — a `show()` from the *current*
    `hubOwner` for a scene not in that Hub's original manifest — is
    accepted; the invariant scopes to the source connection's live-Hub
    status, not to the manifest's contents.
  - **I3 (no-two-hub-winners):** at every state, `hubOwner` is undefined or
    a single connection id — never two.
  - **I4 (deadlock-freedom):** `HubIdentify` always eventually reaches a
    state where preemption (if any) has completed — no interleaving traps
    the model in a state where an old and new claimant are both partially
    processed.
- **Fidelity control (mandatory):** the same model with the single-owner
  preemption step in `HubIdentify` removed (i.e., a second `HubIdentify`
  can coexist with the first) must exhibit a trace that violates I1 or I2
  — either a stale `sceneOwner` entry surviving a manifest that did not
  name it (I1), or a `SceneInstall` from an old, superseded connection
  landing after the new manifest processed (I2). With preemption in
  place, ProB must find no such trace. This mirrors exactly how
  `display_lifecycle.tex` validates itself against the singleton-bind race
  it protects.
- **Test partitions:** derived from the spec via `/z-spec:partition` once
  written; audited against the actual test suite via `/z-spec:audit` before
  the implementation PR merges, per the standard workflow.

## Test surface

- **Unit, over `SceneReplica` directly (no sockets):** construct two
  distinct owner fds, install scenes under fd A, call the new stale-frames
  query with fd B as the identifying connection and a manifest that omits
  A's scenes — assert A's frames are candidates and B's (empty) are not.
  Repeat with A's scene id *included* in the manifest — assert nothing is
  a candidate. Assert widget state is discarded for purged scenes and
  untouched for retained ones.
- **Unit, over `RenderLoop._handle_connect` / `_handle_message`:** a faked
  socket pair, two sequential `ConnectMessage(kind="hub", ...)` from
  different fds — assert the first fd is forcibly removed
  (`SocketListener.remove_client` called) before the second is recorded.
  Assert `notify=False` reaches `_close_frame` for manifest-driven purges
  (no `frame_close` event sent to a dead owner) versus `notify=True` for
  the existing user-initiated close paths (regression guard — this design
  must not change those call sites' behavior).
- **Harness / subprocess, mirroring `tests/integration/test_subprocess_lifecycle.py`:**
  spin up a real Display process, connect a first Hub-identified client,
  push a scene, kill that connection (simulating `luxd` death without
  killing the Display), connect a *second* Hub-identified client with an
  empty manifest, and assert — via the testion surface
  (`list_scenes` equivalent on the Display's own query path, not a
  Hub-mediated read, since the point is to observe the Display's own state
  directly) — that the first scene is gone. Then push a new scene under
  the second connection and confirm it renders normally, exercising that
  reconciliation does not wedge subsequent ordinary traffic.
- **The demo gate (required by `WORKFLOW.md` regardless of this design):**
  `luxd`'s own `list_scenes` (Hub-side, from `HubDisplay`) and the
  Display's own scene listing, captured *before* a real `make restart`-style
  kill-and-respawn of `luxd` alone (leaving the Display running) and again
  *after*. Before: both show the same scenes. Immediately after the kill
  (Display still up, `luxd` down): the Display still shows the old scenes
  (expected — nothing has reconciled yet, this captures the bug's starting
  condition for contrast). After the fresh `luxd` reconnects: the Display's
  list converges to whatever the fresh `HubDisplay` actually holds (empty,
  unless something re-populates it), and a fresh `show()` call renders and
  is clickable normally.

## Impacts on other ADRs

- **DES-057 (Client Identity).** No change to `ClientIdentity` or its
  `ClientKind` vocabulary. This design adds a structurally similar but
  deliberately separate identity dimension on a different leg (Hub↔Display,
  not agent↔Hub) — see the client-identity section above for why merging
  them is out of scope, not merely deferred out of laziness.
- **DES-060 / DES-065 (announce-on-arrival / window visibility).** No new
  special case; reconciliation re-appearance rides whichever rule is
  currently shipped. Flags a sequencing dependency with `lux-mxvy` (see
  the announce-on-arrival section) that the implementation mission should
  check against at merge time, not before — if DES-065's retirement of
  focus-steal has shipped by then, there is nothing to coordinate; if not,
  the implementer should confirm this design's purge-and-repaint path does
  not call the retiring focus/unminimize code either directly or through
  `upsert_scene_in_frame`'s `is_new` branch.
- **`hub_replicator.tex` / `docs/architecture/mcp-display-liveness.md`.**
  No change to the replicator's own model or invariants — this design adds
  a new message the replicator's connection layer sends once per connect,
  and consolidates `SendRecovery._remark`'s re-mark-everything behavior
  with the new connect-success hook (see the wire-protocol section) rather
  than duplicating it, but does not touch coalescing, torn-read exclusion,
  or the send-failure recovery invariants `hub_replicator.tex` already
  proves. Worth a note in that spec's revision history when the
  consolidation lands, not a re-verification of its own invariants.
- **`lux-88ka` (deferred crash-quarantine design).** Orthogonal — that bead
  is about the Display crashing and the *Hub* deciding how much to trust a
  respawned, possibly-different Display (quarantine a scene until the new
  Display proves it can render it safely). This design is about the
  *Display* deciding how much to trust a respawned, possibly-different Hub.
  Structurally similar problem, opposite direction, and I see no reason
  the two need a shared mechanism — but whoever eventually implements
  `lux-88ka` should read this document first, because the "who declares
  truth, and how does the other side know to distrust its own memory"
  framing transfers directly.
- **`lux-tfn1`.** Not fixed by this design (different leg, different
  registry) — see the z-spec recurrence argument above. Should be
  filed/kept as its own fix, informed by whatever this design's z-spec
  process surfaces about the general shape of "stale connection identifier
  used silently" defects.

## Verification

- `make check-oo` must show improvement on every touched file, per the
  ratchet — the `lifecycle.py` codec migration (required, not optional, per
  the wire-protocol section) is itself a substantial OO paydown opportunity
  the implementation mission should not under-scope.
- The z-spec model (`docs/hub_display_reconciliation.tex` +
  `docs/hub_display_reconciliation_coverage.md`) is the merge gate for the
  ordering/preemption correctness claims — "provably no interleaving
  installs a stale scene as if fresh," not "the test passed fifty times."
- The demo gate described above is mandatory regardless of the z-spec
  result, per `WORKFLOW.md`'s standing rule that a design's own model does
  not substitute for driving the real entry point.

## Provenance

- Bead: `lux-e9vy` (P1, silent-failure class).
- Design mission: `m-2026-08-15-004`.
- Files read to ground this design: `src/punt_lux/domain/hub/display_link.py`,
  `src/punt_lux/domain/hub/clients.py`, `src/punt_lux/domain/hub/hub_display.py`,
  `src/punt_lux/domain/hub/replicator.py`, `src/punt_lux/domain/hub/recovery.py`,
  `src/punt_lux/display/socket_server.py`, `src/punt_lux/display/render_loop.py`,
  `src/punt_lux/display/replica/scene_replica.py`,
  `src/punt_lux/display/replica/frame_book.py`,
  `src/punt_lux/display/interaction_delivery.py`,
  `src/punt_lux/display/pending_interactions.py`,
  `src/punt_lux/protocol/messages/lifecycle.py`,
  `src/punt_lux/protocol/messages/scene.py`,
  `src/punt_lux/domain/hub/client_identity.py`,
  `docs/architecture/target/target.md`, `docs/architecture/target/topology.md`,
  `docs/architecture/mcp-display-liveness.md`, `DESIGN.md` (DES-057, DES-058,
  DES-060, DES-063, DES-065, DES-066, DES-067).
- Related, read for context, not modified by this design: `lux-tfn1`,
  `lux-88ka`, `lux-mxvy`.

---

## Proposed ADR text for `DESIGN.md`

The paragraphs above are the design record; the following is what I would
paste into `DESIGN.md` once this is ratified and implemented, matching the
existing DES-NNN format.

> ## DES-068: Hub/Display Scene Reconciliation — Manifest-on-Identify With Single-Owner Preemption
>
> **Status:** proposed (design mission `m-2026-08-15-004`, bead `lux-e9vy`)
>
> **Problem.** `HubDisplay` is memory-only; killing `luxd` loses it entirely.
> The Display never learns anything died, so it keeps rendering the dead
> process's scenes — selection still moves (Display-local), but Hub-composed
> behavior (a click needing a handler) dispatches into an owner fd that maps
> to nothing and silently does nothing. Nothing self-heals, because the
> fresh `luxd` has no memory of the old scenes to ever resend.
>
> **Decision.** Every connection identifying as the Hub (`ConnectMessage
> .kind="hub"`) sends a `HubManifestMessage` naming every scene id its
> `HubDisplay` currently holds, immediately after identifying and before any
> scene content. On receipt, the Display purges every scene not named in the
> manifest AND not owned by the identifying fd — orphaned scenes (owner
> reassigned to `_ORPHAN_FD` after a prior Hub died) are swept by the same
> rule; scenes the manifest names or the identifying fd owns are left
> untouched, pending the Hub's own repaint. At most one connection may hold
> a given Hub identity
> live at a time — a new identify forcibly disconnects any predecessor,
> closing the interleaving where a straggling message from the old
> connection could re-materialize a scene the manifest just purged.
>
> **Alternatives rejected.** Literal sync-on-identify / full resend (the
> fresh Hub has nothing to resend, so this is a no-op exactly when it
> matters most); a generation-token with a timed expiry (trades a message
> the design needs anyway for a timer, which is strictly worse — a window
> where stale content is still live, and a window on the other side where a
> legitimate reclaim can be evicted); persisting `HubDisplay` across
> restarts (reopens the deliberate post-B7 memory-only decision for a
> narrower win); routing the signal through app pub-sub (a system fact about
> connection identity, not an app-defined business event).

---

## Decisions requiring operator ratification

**Ratification note (2026-08-15):** the operator ruled on all three
decisions below this session; each recommendation was accepted. The
alternatives are preserved for design provenance. When the sections
above (notably the z-spec section, which frames its requirement as a
"Decision") speak of a settled outcome, they now describe the ratified
position; the framing below is preserved as the record of the
recommendation-and-ruling exchange, not a still-open question.

Everything above is a decision I am making and defending — the mission
asked for the design a specialist would stand behind, not a menu. The three
items below are different in kind: each is a cost, schedule, or priority
trade-off that depends on information (release timing, appetite for
verification overhead on this specific PR, priority ordering against a
different in-flight epic) that belongs to the operator, not to a design
mission reasoning from the code alone.

**Decision 1: z-spec is required, and that means a full ProB track in the
implementation mission, not a lighter check.** I am confident in the
*requirement* (Ground 1 — the order invariant — triggers it independent of
the recurrence argument), but "required" here means: a new spec file, a
fidelity control that reproduces the shipped bug, invariant model-checking
over a bounded carrier, and a partition/audit pass before merge — the same
weight `hub_replicator.tex` carried. Recommend: keep it required, exactly
as scoped in this document. Alternative: treat it as strongly-recommended
rather than a merge gate, given `lux-tfn1`'s "second occurrence" status is
my own structural judgment call, not an operator-ruled precedent the way
the display-lifecycle rounds were. Trade-off I cannot resolve alone: the
z-spec track measurably lengthens the implementation mission versus a
faster ship with strong test coverage but no formal model; only the
operator can weigh that against the standing project-wide z-spec policy.

**Decision 2: whether to consolidate `SendRecovery._remark` with the new
`ClientRegistry` connect-success hook in the same PR.** I recommend
consolidating — leaving two separate "resend everything after a fresh
connect" code paths is exactly the kind of duplication this codebase's
standards forbid, and the design section above explains why. But
`SendRecovery` is code `hub_replicator.tex` already formally verifies;
touching it inside this PR means either extending that spec to cover the
consolidated path (larger, safer, more PR weight) or asserting — as I did
above — that the consolidation doesn't change any invariant the existing
spec covers and skipping re-verification (smaller PR, a judgment call about
a previously-verified module I should not make unilaterally). Alternative:
leave `SendRecovery._remark` untouched, add the new hook as a fully
separate mechanism, and accept the duplication as a known, named debt for a
later PR. Trade-off I cannot resolve alone: how much weight to add to this
PR versus banking a known duplication.

**Decision 3: sequencing against `lux-mxvy` (DES-065's implementation).**
I recommend implementing this design on its own schedule, with an explicit
merge-time check (not a hard dependency) that `lux-mxvy`'s retirement of
DES-060's focus-steal has landed before this design's purge-and-repaint
path ships, so a restart cannot reintroduce focus-stealing through the
back door. Alternative: block this design's implementation until
`lux-mxvy`/DES-065 ships cleanly, removing the window entirely rather than
managing it with a merge-time check. Trade-off I cannot resolve alone:
`lux-e9vy` is P1 (a silent failure of Hub-composed behavior, live on main
today) and `lux-mxvy` is a P2 epic still landing pieces (most recently PRs
348 through 350) — whether a P1 silent-failure fix should wait on an
unrelated P2 epic's completion is a priority ordering call, not a
design-correctness call.
