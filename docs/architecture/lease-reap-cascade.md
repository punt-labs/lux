# Lease-Reap Departure Cascade: Design

**Status:** shipped. Both forks (§3, §4) were ratified as designed (Option A;
bring `register_client`/`identify_client` under `StoreLock`) and implemented —
`domain/hub/departure_sinks.py`, `domain/hub/departure_cascade.py`, the
`HubDisplay` wiring, and round 3 of the companion model below. See §10 for
one known, out-of-scope residual left open by this implementation.
**Bead:** `lux-vvmt`. Companion model: `docs/connection_lease_reaping.tex`
(round 3, extending round 2's bead `lux-d84d`) and its coverage audit,
`docs/connection_lease_reaping_coverage.md`. Companion design:
`docs/architecture/target/target.md`, especially the DES-088 content/visibility
split and its discussion of what a Hub resend may and may not overwrite.

I read `target.md` in full, including DES-088, and both `connection_lease_reaping.tex`
and its coverage audit in full — the Depart/TimedReap/Claim schemas, the I1–I6
invariants, and the H1/H2/H3 fidelity controls — before writing this. What
follows extends that model; it does not restate it.

## 1. The problem, grounded in the code

`connection_lease_reaping.tex` models one thing precisely: when a connection
leaves `HubClientRegistry`'s live set, does the scene ownership it held come
back to `unowned` in the same atomic step? Round 2 answers yes, for all three
paths (`Depart`, `TimedReap`, `Claim`'s embedded sweep), and I5/I6 are proven
against that model. The model is honest about its own scope — its "Read first"
list names `hub_display.py` and `session_cleanup.py` — but it deliberately
abstracts `drop_connection` down to registry-plus-ownership, because that was
the reported bug's shape (`lux-d84d`: a connection persisting 25.79h). It does
not model the rest of what a *graceful* disconnect actually does.

That rest is real code, and it is wider than the model:

- `session_cleanup.py:43-54` (`SessionCleanup.run`) runs two independent legs:
  the menu-drop leg, and `disconnect_connection(self._connection_id,
  drop_session)`.
- `lifecycle.py:31-51` (`disconnect_connection`) does **three** things in
  order: `hub_display.drop_connection(connection_id)` (registry + ownership),
  `hub.on_disconnect(connection_id)` (drops every subscription and the writer
  binding — `hub.py:133-141`), then the caller-supplied `on_disconnect`
  sink — today always `inbox.drop_session` (`inbox.py:90-98`), which frees the
  per-connection `queue.SimpleQueue` the MCP `recv` tool reads from.

`hub_display.drop_connection` (`hub_display.py:412-419`) only ever calls
`self._depart(connection_id)` (`hub_display.py:438-445`), which is
registry-discard plus `OwnerTracker.release_all` — nothing else. The other two
legs of the cascade are orchestrated **outside** `HubDisplay`, in
`lifecycle.py`, and `lifecycle.disconnect_connection` has exactly one call
site: `session_cleanup.py:53`.

`reap_lapsed_leases` (`hub_display.py:421-427`, the `TimedReap` realization,
driven by `LeaseReapSweep.sweep()` at `lease_reap_sweep.py:60-62`) and the
Claim-embedded sweep inside `apply` (`hub_display.py:385-387`, `self._depart_lapsed(exclude=...)`)
both call `_depart_lapsed` (`hub_display.py:429-436`) directly. Neither goes
anywhere near `lifecycle.py`. So neither one ever calls `hub.on_disconnect`,
and neither one ever fires `inbox.drop_session`. A connection reaped by the
timer, or swept aside by someone else's `apply`, keeps its Hub subscriptions,
keeps its writer binding, and keeps its inbox queue forever (or rather: for as
long as the process runs — nothing else will ever drop them, because nothing
else refers to that connection id again).

This is not a hypothetical gap. It is the literal shape of H1/H2/H3 one layer
up: three departure triggers, and only one of them (the one that happens to
route through `lifecycle.py`) does the full job.

### 1.1 A sharper failure than a leak: stale subscription inheritance on reconnect

The leak alone (unbounded growth of `_subscriptions`/`_writers`/`_inboxes`
dicts keyed by dead connection ids) is bad. But `connection_for`
(`connection_identity.py:39-45`) derives a **stable** `ConnectionId` from a
client's declared identity fields (`kind`, `name`, `repo`, `agent`) — this is
explicitly so a client using both REST and the WebSocket listen leg is one
connection across both transports (`connection_identity.py:1-19`). That means
a same-identity reconnect very often reuses the **identical** connection id,
not a fresh one — the Z model's `Connect(c2, i1)` with `c1 ≠ c2` (I3/I4's
framing) is the abstraction for a *distinct-id* reconnect; the common real
case is `c1 = c2`.

Walk it through: connection `C` times out — its lease lapses, `TimedReap`
fires, `HubClientRegistry` drops it, `OwnerTracker` releases its scenes. Its
Hub subscriptions and writer binding are untouched (today's bug). A new
session under the same identity reconnects, deriving the same `C`. It calls
`inbox.ensure_writer(C)` (`inbox.py:74-87`):

```python
def ensure_writer(connection_id: ConnectionId) -> None:
    hub_display.register_client(connection_id)
    if hub.has_writer(connection_id):
        return
    ...
```

`hub.has_writer(C)` is **still true** — the old writer binding was never
dropped. `ensure_writer` returns early, never calling `hub.register_writer`
for the new session. The new session's inbox writer closure is never
installed. Worse: whatever topics the *departed* session subscribed to are
still live in `SubscriptionRegistry._by_connection[C]` (`subscription_registry.py:39`),
so a fresh session that never called `subscribe()` itself inherits its dead
predecessor's subscriptions the moment `Hub.publish` next fans out on one of
those topics. This is not a resource leak; it is a reconnecting client
silently starting from a stranger's state. It is the reason the fix must not
be "eventually converges" — the window in which it is wrong is exactly the
window in which a fast reconnect (which `connection_for` exists to make easy)
can land.

## 2. Design goal

Every departure trigger — `Depart` (graceful disconnect, SDK idle-reap),
`TimedReap` (the lease backstop), and `Claim`'s embedded sweep-of-others
(`apply`) — must run the *identical* four-part cascade, in the same atomic
step, for every connection it removes:

1. drop the client-registry entry (`HubClientRegistry` — unchanged, already
   correct per I5/I6)
2. release its scene ownership (`OwnerTracker.release_all`/`release_departed` —
   unchanged, already correct)
3. drop its Hub subscriptions and writer binding (`Hub.on_disconnect` —
   **currently only reached by `Depart`, via `lifecycle.py`**)
4. fire its transport-owned per-connection sink (today: `inbox.drop_session` —
   **currently only reached by `Depart`, via `lifecycle.py`**)

"Same atomic step" is not decoration — §4 below shows a real race if steps
3–4 are bolted on to the *outside* of the existing critical section rather
than run inside it.

## 3. Fork 1 — where does the sweep reach the transport-layer sink?

This is the fork the mission asked me to surface. Two shapes:

### Option A — a shared `connection_id → sink` registry, domain-resident

Add a small domain-layer collaborator, e.g. `DepartureSinks`, living beside
`WriterRegistry` in `domain/hub/` (same shape: `bind`/`drop`/`fire`, at most
one sink per connection id — mirrors `writer_registry.py:37-64` almost
exactly). A transport module that owns per-connection side state — today,
only `inbox.py` — registers itself once, at connect time (inside
`ensure_writer`, alongside `hub.register_writer`). A single coordinator that
already knows about `HubClientRegistry`, `OwnerTracker`, `Hub`, and
`DepartureSinks` runs all four cascade steps for every connection any
departure trigger removes.

#### Option A — pros

- Extends the *already-ratified* round-2 principle ("one coordinator... every
  departure trigger funnels through that one step") uniformly to subs/writer/
  inbox instead of leaving them as a bolt-on that only one trigger reaches.
- `TimedReap` and `Claim`'s sweep, which each remove a *set* of connections in
  one pass, get the full cascade per member of that set for free — no new
  plumbing needed at each trigger's call site.
- Keeps the dependency arrow correct (PL-MD-1 / PY-IC-8): the coordinator
  lives in `domain/hub/`, `inbox.py` already lives in `domain/hub/` and
  already imports `hub`/`hub_display` — registering a sink is the same
  direction of dependency `inbox.py` already has, not a new one.
- Generic against future transports. A second transport kind (say, a
  REST-only session with its own SSE queue) registers its own sink the same
  way; the coordinator's code does not grow a second hardwired import.

#### Option A — cons

- New abstraction to design, review, and hold to the OO rules (§6).
- The sink runs *inside* the coordinator's critical section (see §4), so it
  must be documented as non-reentrant and non-blocking — a constraint on
  every future sink author, not just the first one.

### Option B — split: domain sweep does `hub.on_disconnect`; a separate transport-layer sweep derives departure for the inbox

`HubDisplay._depart`/`_depart_lapsed` call `hub.on_disconnect` directly
(`Hub` is a domain-layer sibling of `HubDisplay`, so this is legal by
PL-MD-1 with zero new coupling to a transport module). Steps 1–3 are then
correct everywhere. Step 4 (inbox) is left to an independent, transport-layer
periodic task that diffs "connections currently in `HubClientRegistry`"
against "connections holding an inbox queue" and calls `drop_session` for any
id that fell out of the first set.

#### Option B — pros

- No new cross-cutting abstraction for the (today, singular) inbox case;
  each layer's cleanup stays local.
- Closes 3 of 4 cascade steps with a minimal, obviously-correct change:
  two call sites gain one line each.

#### Option B — cons, and why I recommend against it

- It reintroduces, for the inbox specifically, exactly the pattern round 2's
  own ruling eliminated for ownership: a **derived, poll-based** signal
  ("the registry no longer contains you") standing in for a **pushed,
  atomic** one. The round-2 addendum's entire argument for adding `TimedReap`
  was that a connection's departure must not depend on some other party's
  activity or on a read happening to run at the right moment (`connection_lease_reaping.tex`
  §"TimedReap", the "25.79 hours, nobody wrote or disconnected it" evidence).
  A diff-based inbox sweep is precisely that dependency, moved one layer up,
  for the one piece of state (§1.1) where the window matters most.
  Reproducing it is not a smaller version of the problem this bead exists to
  close — it is the same problem, filed against a different noun.
- It does not extend to I5's shape ("leaving the registry iff released,
  however triggered") at all — there is no invariant linking "C left the
  registry" to "C's inbox is gone" *in the same step*; a new, separate,
  weaker guarantee would have to be stated and proven for it, and the
  natural one ("eventually, bounded by the sweep's own poll interval, on top
  of the lease's own TTL") is worse than what step 3 gets by inheriting the
  existing atomic coordinator.
- Two independent timers (`LeaseReapSweep` at `lease_reap_sweep.py:32`'s
  15s poll, plus a new inbox-diff sweep) now exist for what is conceptually
  one lifecycle event. That is a second, competing "one coordinator" claim,
  which is the exact anti-pattern the round-2 intro names as the root cause
  of H1/H2/H3: *the code has no single place where "leave" and "release" are
  the same atomic step, for every trigger.*

**Recommendation: Option A.** Extend the existing, ratified single-coordinator
principle to the full cascade rather than reintroducing a second,
weaker-guarantee mechanism for the one piece of state that most needs the
strong one.

## 4. Fork 2 — a race the naive version of Option A introduces (found while grounding this, not asked for, but load-bearing)

Bolting `hub.on_disconnect(C)` and `sinks.fire(C)` onto the *end* of
`_depart_lapsed`, inside `HubDisplay`'s own `self._lock.write()`
(`hub_display.py:433-436`), is not enough by itself. Here is the trace that
breaks it:

1. `TimedReap` calls `_depart_lapsed`, which takes `StoreLock.write()` and
   calls `self._clients.reap_lapsed_locked(exclude)` (`hub_clients.py:185-197`,
   itself under `HubClientRegistry._lock` — a *different*, registry-internal
   lock). `C` is popped from `_sessions`. `StoreLock` is still held.
2. **Race window.** A new session under the same identity reconnects,
   deriving the same `C` (§1.1). It calls `inbox.ensure_writer(C)` →
   `hub_display.register_client(C)` (`hub_display.py:161-163`) →
   `self._clients.record(C)` (`hub_clients.py:70-82`). **This path never
   takes `StoreLock`** — `register_client`/`identify_client`
   (`hub_display.py:161-169`) call straight into `HubClientRegistry`, which
   only takes its own internal lock. Nothing here waits for step 1's
   `StoreLock` hold to release. The registry now shows `C` as a fresh, live
   session, and (in `ensure_writer`'s continuation) a new writer gets bound
   for `C`.
3. `_depart_lapsed` (still running, still holding `StoreLock` from step 1)
   reaches the new cascade tail and calls `hub.on_disconnect(C)`. This
   **unconditionally** drops every subscription and the writer binding for
   connection id `C` — including the one step 2 just installed for the
   *new*, live, reconnected session.

The result: a legitimate reconnect's brand-new writer binding is retroactively
destroyed by a reap that, from the registry's point of view, is already
stale by the time its cascade tail runs. This is a genuinely new hazard —
today's code cannot produce it, because today's `_depart_lapsed` never
touches `Hub` at all. It is a direct consequence of doing the fix well
enough to close §1.1, and it must be closed in the same design, not left for
implementation to discover.

**Root cause:** `register_client`/`identify_client` are the real-code
realization of the Z model's `Connect`/`Renew` operations, but unlike every
other registry-mutating operation (`_depart`, `_depart_lapsed`, `apply`), they
do not take `StoreLock`. `HubDisplay`'s own module docstring already states
the discipline it holds everywhere else — "every write runs under
`StoreLock`... the lock discipline is the store's own behavior and never
escapes to the caller" (`hub_display.py:22-26`) — `register_client`/
`identify_client` are an existing gap relative to that stated discipline, not
a deliberate exception; nothing in the docstring or the code names a reason
they should be different, and prior to this cascade extension the gap was
invisible because the only thing `register_client` could race against was
plain registry bookkeeping, which already serialized correctly through
`HubClientRegistry`'s own lock.

**Recommended fix:** bring `register_client` and `identify_client`
(`hub_display.py:161-169`) under `self._lock.write()`, matching every other
mutating method on the class. Once they do, the cascade tail added to
`_depart`/`_depart_lapsed` — still run inside the *same* `StoreLock.write()`
hold that removed `C` from the registry — is correctly serialized against
any concurrent reconnect: whichever operation acquires `StoreLock` first
completes in full (registry state *and* cascade) before the other can begin,
which is precisely the "whichever fires first wins, and correctly" argument
`connection_lease_reaping.tex` §"Invariants" already makes for `TimedReap`
vs. `Depart` — extended to cover `TimedReap`/`Depart` vs. `Connect`/`Renew`,
which the existing proof does not currently claim.

This is the one place I am asking for an explicit ruling rather than just
recommending: **bringing `register_client`/`identify_client` under
`StoreLock` is a small, mechanical change with a large blast radius** — every
call site that identifies a connection (`inbox.ensure_writer`,
`tools/subscribe_tools.py`, any REST/WS identify path) now contends for a
lock that is also held across the whole of `apply`, `replace_scene`, and
`show_scene`. I believe this is correct and necessary (§4 shows why), but it
is a locking-discipline change to a hot path, not a pure addition, and it is
the kind of change the org's z-spec mandate exists to gate — see §5.

## 5. Model extension: round 3 of `connection_lease_reaping.tex`

This is the same state machine the existing spec governs — connections
departing `CONN` — and the org's own recurrence rule applies directly: *"The
moment the same class of defect surfaces across two or more fix/review
rounds — stop... formalize the state machine."* H1/H2/H3 was round 1 →
round 2's lesson: an under-scoped `Depart` abstraction that looked complete
and wasn't. §1 of this document is the identical lesson recurring at round 2
→ round 3: `Depart`/`TimedReap`/`Claim` were modeled as registry+ownership
only, and the real code's fuller cascade (subs, writer, inbox) was out of
frame. That is the recurrence signal. **A fresh, separate spec is not
warranted — extending `connection_lease_reaping.tex` as its third round is**,
for the same reason round 2 extended round 1 rather than starting over: it is
one lifecycle, and the coverage doc's own instruction ("re-run... whenever
`hub_display.py`'s `drop_connection`/`apply`/`_reap_and_release`... or
`session_cleanup.py` change") already anticipates exactly this change as a
re-verification trigger.

Sketch of the extension (for the implementation mission's z-spec skill to
carry out in full, not prescribed in detail here):

- **New state components**, one per cascade leg not yet modeled, kept as
  coarse booleans matching the existing abstraction style (`TSTATE`/`LSTATE`
  are already booleans-with-names, not richer structures):
  `hasSubs : CONN → BOOL`, `hasWriter : CONN → BOOL`,
  `inboxNonEmpty : CONN → BOOL`. Topic identity and message content are out
  of scope — I7 only needs "any subscription exists," not which.
- **New invariant, I7 — departure clears the full cascade:**
  `¬∃ c : CONN | c ∉ registered ∧ (hasSubs(c) ∨ hasWriter(c) ∨ inboxNonEmpty(c))`.
  The general form, in the same style as I5's "however triggered": no
  reachable state has a connection outside `registered` while any of the
  three still shows true.
- **`Depart` and `TimedReap`** each gain three more `⊕` terms, setting
  `hasSubs'(c?)`, `hasWriter'(c?)`, `inboxNonEmpty'(c?)` to `false` in the
  same predicate that already zeroes `owner` for `c?` — textually the same
  shape of change both operations already carry from round 1 → round 2.
- **`Claim`'s embedded sweep** gains the same three terms for every `c2` it
  sweeps (not for `c?` itself — the `c2 ≠ c?` exclusion that closes H3/I6
  is untouched and must stay).
- **`Connect` and `Renew` move under the same discipline `Depart`/`TimedReap`/
  `Claim` already have** — §4's finding. Concretely: state, as a precondition
  or a documented enabling assumption, that `Connect`/`Renew` and
  `Depart`/`TimedReap`/`Claim` are *mutually exclusive* steps (no interleaving
  where a `Connect(c?, i?)` sees a `registered` that a concurrently-running
  `Depart`/`TimedReap` has only half-updated) — which is the specification of
  §4's "bring `register_client` under `StoreLock`" fix, not a new fact about
  the running system to discover, but a precondition that must hold once the
  fix lands, and that the fidelity control below must show is violated
  *without* it.
- **Fidelity control 4 — cascade-incomplete (reproduces §1's actual bug).**
  Change only `TimedReap` and `Claim`'s sweep to omit the three new
  conjuncts, leaving `Depart` correct. Trace: `Connect(c1)`; a subscribe/
  writer-bind/inbox-write modeled abstractly as `hasSubs'(c1) = hasWriter'(c1)
  = inboxNonEmpty'(c1) = true`; `TransportDies(c1)`; `LeaseLapse(c1)`;
  `TimedReap(c1)` — buggy: `c1 ∉ registered'` but all three flags remain
  `true`. Goal `FOUND` against the control, `NOT found` against the fixed
  spec. This is the sharpest fidelity control of the four, because it
  reproduces the *actual reported shape* of the bug precisely: the graceful
  path (`Depart`) is fine; the two lapse-triggered paths are not.
- **Fidelity control 5 — reconnect-races-reap (reproduces §4's finding).**
  Model `Connect`/`Renew` *without* the mutual-exclusion precondition against
  `TimedReap`: an interleaving where `TimedReap(c1)` and a same-id
  `Connect(c1, i1)` (§1.1: same id, not a fresh one) run with the cascade's
  `hasWriter'(c1) = false` landing *after* `Connect`'s `hasWriter'(c1) = true`
  — i.e., the two operations' effects apply out of the order their real-world
  causes occurred in. Goal: `∃` a reachable state where `c1 ∈ registered ∧
  hasWriter(c1) = false` after a `Connect` that should have left it `true`.
  `FOUND` against the unguarded control; `NOT found` once `Connect`/`Renew`
  are specified as mutually exclusive with `Depart`/`TimedReap`/`Claim` (the
  StoreLock fix's formal counterpart).
- **Deadlock check, re-run.** §4's fix nests two real locks
  (`StoreLock`, then `HubClientRegistry._lock`) on a path (`register_client`)
  that previously took only the inner one. The existing model's "two-lock
  concern is moot by construction" argument (`connection_lease_reaping.tex`
  §"Invariants", "The two-lock concern is moot by construction") rests on
  *removal* and *release* being one update inside one object; extending that
  argument to *registration* needs its own sentence, not an assumed
  extension — the model should state explicitly that `Connect`/`Renew`
  becoming `StoreLock`-guarded introduces no new lock-acquisition order
  (`StoreLock` is always taken before any inner registry lock, on every
  path, both before and after this change), so no new cycle is possible, and
  the full `-model_check` should be re-run to confirm no deadlock over the
  extended carrier.

I did **not** write the full `.tex` for this round — that is implementation
work, and per the mission's terms I am not prescribing the write-set beyond
naming what round 3 must contain. The implementation mission's z-spec skill
(`z-spec:code2model` → `z-spec:check` → `z-spec:test` → the mandatory fidelity
check → `z-spec:partition`/`z-spec:audit`) carries this out in full, and the
result is committed as `docs/connection_lease_reaping.tex` round 3 (extending
the existing file, not a new one) plus updated fidelity controls and coverage
audit.

## 6. New types, held to the OO rules

Two small classes fall out of §3's recommendation; both should be designed
against the cited rules (the mission asked that any new type follow PY-OO-5,
Protocol-not-base-class, Literal-over-str, discriminated-over-Optional):

- **`DepartureSink` — a `runtime_checkable` `Protocol` with one method**,
  `__call__(self, connection_id: ConnectionId) -> None`. This is PY-DP-11
  (single-method interface) applied directly: `inbox.drop_session` already
  has exactly this shape (`inbox.py:90`, `def drop_session(connection_id:
  ConnectionId) -> None`), so it satisfies the protocol with zero
  modification — no base class, no registration, structural typing per the
  family-by-protocol rule in `oo.md`.
- **`DepartureSinks` — a small registry class**, same shape as
  `WriterRegistry` (`writer_registry.py:26-76`): `bind`, `drop`, `fire`,
  at-most-one sink per `ConnectionId`, backed by a plain
  `dict[ConnectionId, DepartureSink]` (PY-EN-1: private, `__slots__` as a
  tuple, `@final`, `__new__` not `__init__` per PY-CC-1). `fire` is a
  value-producing-nothing operation on a possibly-absent key — this is one of
  the genuinely-optional cases PY-TS-14 names explicitly ("dict.get(key,
  default=None) returns None when the key is absent because absence is the
  API"): most connections have no sink (no transport-owned side state to
  release), so `fire` on an unbound connection id is a documented no-op, not
  an error — unlike `WriterRegistry.writer_for`, which raises because a
  subscription with no recipient is a bug. State that distinction explicitly
  in the class's docstring so a future reader does not "fix" `fire` into
  raising.

Whatever coordinator composes `HubDisplay`, `Hub`, and `DepartureSinks` (§3,
name left to the implementation mission — the design mission's job is the
shape, not the identifier) should itself be `@final`, constructed via
`__new__`, and should not duplicate `HubDisplay`'s own `_depart`/
`_depart_lapsed` logic — it calls into them (or a public equivalent
`HubDisplay` exposes) and adds the two new steps, matching PY-IC-6 (single
responsibility): `HubDisplay` continues to own registry+ownership;
`Hub` continues to own subs+writer; the coordinator owns *sequencing them
together, atomically, for one connection or one swept set*, and that
sequencing is its entire job.

`lifecycle.py`'s `disconnect_connection` either becomes a thin call into this
coordinator, or is folded away entirely once the coordinator exists — either
way, its `on_disconnect: Callable[[ConnectionId], None]` parameter
(`lifecycle.py:33`) should be replaced by the registered-sink lookup, since
after this change there is exactly one caller (`session_cleanup.py:53`) and
it no longer needs to *pass* the sink per call — it registers it once, at
connect time, alongside `hub.register_writer`.

## 7. Verification — run and prove it, via the parallel introspection work

The mission names `lux-221j`'s in-flight introspection extension
(`writer_bound`/`inbox_depth` on `list_clients`, plus `get_display_state`) as
the intended verification surface. Today, `ClientListing._client`
(`client_listing.py:65-90`) builds `HubClient` from `subscribed_topics`
(`self._hub.topics_for(connection_id)`) and `owned_scenes`
(`self._display.elements_owned_by(connection_id)`) — it does not yet report
writer state or inbox depth; those are exactly the two facts `lux-221j` adds,
and they are exactly the two facts this bug hides today (a departed
connection's writer binding and inbox queue are invisible to any current
introspection call).

**The run-and-prove**, once both land:

1. Connect a victim connection `V` (a distinct identity, so it does not
   collide with the operator's own session). Subscribe it to a topic. Bind
   its writer (`inbox.ensure_writer`, in the ordinary MCP-session path).
   Queue one event onto its inbox (publish once on the subscribed topic from
   a second connection).
2. Confirm via `list_clients()` (extended): `V` shows `writer_bound: true`
   and `inbox_depth: 1`, and `subscribed_topics` includes the topic.
3. Let `V`'s lease lapse (either wait out its TTL, or — for a fast test —
   construct the Hub with an injected clock, per the existing pattern in
   `HubClientRegistry.__new__(clock=...)`, and advance it past the TTL).
4. Trigger one `TimedReap` pass (`LeaseReapSweep.sweep()` — the deterministic
   test hook named in `lease_reap_sweep.py:60-62`, no need to wait out the
   real 15s poll).
5. Assert, via `list_clients()`: `V` is **absent** from the client list
   (already true today — this is the part that already works).
6. Assert, via `list_clients()` **before** it is absent is not possible (`V`
   is gone) — so the assertion is instead: query `get_display_state()` /
   the Hub's own `topics_for`/`has_writer` through whatever read surface
   `lux-221j` exposes for a *specific* connection id even after it has left
   the client list (an inbox-depth/writer-bound check keyed by connection id,
   not requiring the connection still be "current"), and assert both are now
   false/zero. If `lux-221j`'s surface only reports live clients, this is a
   design note the two missions must reconcile: proving a cascade fully fired
   sometimes requires observing the *absence* of state for an id that has
   already left the roster, which is a slightly different introspection need
   than "list the live clients."
7. Boundary condition: repeat steps 1–2 with **no** subscription and **no**
   inbox write (a connection that only ever registered) — confirm `TimedReap`
   is a no-op on `hasSubs`/`hasWriter`/`inboxNonEmpty` for it, matching TR3's
   existing "ownerless connection, no-op on owner" partition extended to the
   three new flags.
8. Missing-dependency / invalid-input case: fire `TimedReap` when
   `DepartureSinks` has no sink bound for the swept connection at all (the
   ordinary case — most connections, e.g. `cli`-kind ones, have no
   transport-owned side state) — confirm this is a documented no-op (§6) and
   not a raised error, since a raise there would mean one connection with no
   inbox blocks the sweep from departing every other connection in the same
   pass.

## 8. Proposed implementation write-set

Not prescribed in interior detail — the implementation mission decides how to
decompose — but the design above touches:

- `domain/hub/hub_display.py` — `register_client`/`identify_client` gain
  `self._lock.write()`; `_depart`/`_depart_lapsed` gain the two new cascade
  steps (or delegate to the new coordinator).
- `domain/hub/hub.py` — no change to `on_disconnect` itself; it is now called
  from more places.
- **New**: a `DepartureSink` protocol + `DepartureSinks` registry (§6),
  likely `domain/hub/departure_sinks.py`, sibling to `writer_registry.py`.
- **New**: the coordinator (§3/§6) — a new module, or (if the evaluator finds
  the responsibilities genuinely belong there) additional methods on
  `HubDisplay` itself; the design mission's judgment is that a new class is
  cleaner (§6's PY-IC-6 argument), but this is exactly the kind of call the
  implementation specialist is better placed to make once writing the code,
  and it is not gated on an operator ruling.
- `domain/hub/lifecycle.py` — `disconnect_connection` shrinks or is retired
  in favor of the coordinator; `on_disconnect` parameter likely removed.
- `inbox.py` — `ensure_writer` registers its `drop_session` sink alongside
  `hub.register_writer`.
- `session_cleanup.py` — `SessionCleanup.run`'s `disconnect` leg
  (`session_cleanup.py:50-54`) simplifies once `on_disconnect` is no longer a
  per-call argument.
- `docs/connection_lease_reaping.tex` — round 3 (§5), extending the existing
  file.
- `docs/connection_lease_reaping_coverage.md` — new partitions for I7 and the
  reconnect-race fidelity control, alongside the existing table.
- Tests: `test_hub_display_ownership.py` (existing file per the coverage
  audit) gains the cascade-completeness partitions; a new test exercises the
  §4 race directly (two threads or an explicit interleave harness — Python's
  GIL does not save this, since `register_client`'s current code has no lock
  held across its whole span relative to `StoreLock`).

## 9. Summary — the two decisions I am asking the operator to ratify

1. **Fork 1 (§3):** shared `DepartureSinks` registry + a single coordinator
   that runs the full four-step cascade for every departure trigger
   (Option A), rather than splitting the cascade across a domain-reachable
   `hub.on_disconnect` call plus a second, independent, poll-based
   transport-layer sweep for the inbox (Option B). **Recommend Option A** —
   Option B reintroduces, for the inbox specifically, the exact
   derived-signal pattern round 2 eliminated for ownership, for the one
   piece of state (§1.1) where the window matters most.
2. **Fork 2 (§4, discovered during grounding, not in the original ask):**
   bring `register_client`/`identify_client` under `StoreLock.write()` so the
   cascade's subs/writer/inbox release cannot race a same-identity reconnect
   that lands inside the window between "removed from the registry" and "the
   coordinator's cascade tail runs." **Recommend yes** — without it, the fix
   for §1 introduces a live-reconnect writer-binding corruption bug that does
   not exist in the code today. This is a locking-discipline change to a hot
   path (every `identify`/`register_client` call now contends for the same
   lock `apply`/`replace_scene`/`show_scene` already hold), which is why I am
   surfacing it as a decision rather than folding it silently into the
   write-set.

Both decisions are also, independently, decisions about the *shape* of round
3 of `connection_lease_reaping.tex` (§5) — the model cannot be written until
these are settled, since Fork 2 in particular determines whether `Connect`/
`Renew` need a new mutual-exclusion precondition against the departure
operations that the current, round-2 model does not state.

## 10. `ensure_writer` and the `/ws` listen leg's registration are both closed

Two more entry points install fresh Hub-side state the same way
`register_client`/`identify_client` do, and both were found to share the same
race: `inbox.ensure_writer` (`inbox.py`) and `HubListenSession`'s handshake
prologue (`ws_listen.py`, the `/ws` transport a WebSocket listener such as
Vox's music-control leg connects over).

`ensure_writer` ran `hub_display.register_client` (`StoreLock`-guarded, §4),
then a `hub.has_writer` check, `hub.register_writer`, and
`hub_display.bind_departure_sink` — the last three outside the lock, so a
departure trigger could in principle interleave between the check and
`register_writer` and depart the very connection that is mid-reconnect. The
whole sequence now runs inside `with hub_display.write_lock():`; `StoreLock`
is reentrant, so `register_client`'s own internal lock acquisition nests
inside it without change.

`HubListenSession._attach_and_register_writer` (extracted from `run`'s
prologue) had the identical shape one layer up: `HubClientRegistry
.attach_listener` — itself a renewing registration, structurally the same as
`register_client` — followed by `hub.register_writer`, neither under
`StoreLock`. A same-identity WebSocket reconnect landing inside a departure
cascade's registry-removal-to-cascade-tail window had its fresh listener and
writer wiped out by the stale cascade's tail. `HubListenSession` now carries
a `HubDisplay` reference (threaded through `HubListenTransport`) and wraps
both calls in `with self._display.write_lock():`.

Both closures follow the same reasoning §4 gives for `register_client`: the
lock is already reentrant and already the outermost lock on every path, so
extending its reach to these two write-registration sequences adds no new
lock-acquisition order and closes the race outright rather than leaving a
narrower, TTL-bounded version of it open.
