# Bounded Agent-Subscribe Inbox: Model-Check Result and Test-Partition Coverage

Companion to `docs/menu_lifecycle_bounded_inbox.tex`, following the format of
`docs/menu_lifecycle_coverage.md`. This is a **modeling-mission** artifact
(bead `lux-wk3p`, branch `chore/lux-m3xr-quality-followups`): the model is the
merge gate for the bounded-inbox leaf-lock fix gvr is building in parallel for
`src/punt_lux/domain/hub/inbox_queue.py`, and the partitions below are the
contract the fix's tests must cover. A partition left unchecked when the fix
lands is a gap, not a missing row.

## Why this model exists (the z-spec determination)

`lux-wk3p` bounded the per-connection Agent-Subscribe inbox: `BoundedInbox.put`
drops the oldest undelivered message when the queue is at capacity
(`INBOX_CAPACITY = 32`), a backstop against a subscriber whose `recv` leg has
stopped draining. Code review then found that `put`'s overflow is a non-atomic
check-then-act,

```python
if self._queue.qsize() >= self._capacity:  # (1) check
    self._drop_oldest()  # (2) drop the front
self._queue.put(message)  # (3) enqueue
```

run by **two producers that do not share a lock**:

- **Publish fan-out** — `Hub.publish` → the session's Hub writer (`inbox.py`'s
  `_writer`) → `inbox_for(cid).put(msg)`. `inbox_for` takes the registry lock
  `_inboxes_lock` only to look the inbox up, then **releases** it; the `put`
  runs with no lock held.
- **Menu-click offer** — `MenuEventRouter.deliver` → `inbox.offer(cid, msg)`,
  whose `get`-then-`put` runs **inside** `_inboxes_lock` (the D1 hold of
  `menu_lifecycle.tex`).

One producer runs `put` outside `_inboxes_lock` and the other inside it, so the
registry lock serializes neither against the other, and steps (1)(2)(3) tear.
This is the concurrency/interleaving class the repo's z-spec policy makes
model-checking **mandatory** for. It is sharpened by two facts: the fix
**introduces a lock** (contradicting the implementer's prior "no new lock"
self-assessment), and that lock **nests** under `_inboxes_lock` on the offer
path — so deadlock-freedom must be *proven*, not assumed.

## The fix the model reviews (for gvr)

Give `BoundedInbox` its **own internal lock** (`boxLock`), held across the whole
compound `put` **and** across `_drop_oldest`, `get`, `drain`, and `depth`. It is
a fresh lock, distinct from the registry's `_inboxes_lock`. Holding it across
the compound makes (1)(2)(3) atomic; guarding `get`/`drain`/`depth` under it
closes the same tear against a concurrent `recv` (see B2's witness below).

The model's `boxLock` guard on `get` and a blocking dequeue that must never
hold a lock across its wait are, on the face of it, two requirements that
cannot both be met by a plain `threading.Lock` — hold the lock and you stall
every producer for the whole timeout; drop the lock (as the round-1 fix,
`e618d971`, did, leaving `get` deliberately unguarded) and the check-vs-recv
tear this model exists to close is still open. `threading.Condition` is what
reconciles them: its lock is held for the compound (satisfying the guard) but
`wait`/`wait_for` **releases** that lock for the duration of the actual block
and only reacquires it to recheck the predicate, so the wait itself holds
nothing. This is not a modeling nicety — it is the specific mechanism the
model's Drain guard requires and a plain `Lock` cannot supply without
sacrificing one of the two properties.

## Fidelity: mapping the model onto `threading.Condition` (round 2, `009cd21e`)

The shipped fix (`009cd21e`) realizes `boxLock` as a single
`threading.Condition` shared by `put`, `_drop_oldest`, `get`, `drain`, and
`depth`. The model's abstractions map onto it exactly, with no change to the
Z text required:

- **`boxLock = bfree` / `boxLock = b{offer,publish}`** ↔ the Condition's
  underlying lock unheld / held. Every method enters via `with self._cond:`,
  so exactly one caller is ever inside the block — the mutual exclusion
  `OfferPut`/`PubPut`/`Drain` all assume.
- **`OfferPut`/`PubPut` (the atomic compound)** ↔ `put`'s `if len(...) >=
  capacity: self._drop_oldest(); self._queue.append(message)`, all inside one
  `with self._cond:` — the check, the drop, and the append never interleave
  with another caller's, because no other caller can be inside the block at
  the same time.
- **`Drain` (guarded on `boxLock = bfree`, "holds no lock in a wait state of
  its own")** ↔ `get`'s `self._cond.wait_for(lambda: len(self._queue) > 0,
  timeout)`. While the predicate is false, `wait_for` calls `wait()`, which
  releases the condition's lock for the actual blocking period — exactly the
  "no lock held while waiting" the model requires — and reacquires it only to
  recheck the predicate. When the predicate is already true (or becomes true),
  the reacquire-check-`popleft()`-return runs as one atomic step under the
  lock, which is what the single-step `Drain` operation abstracts.
- **The one-way edge `regLock → boxLock`** ↔ `inbox.offer` holding
  `_inboxes_lock` across `inbox.put(message)`, which enters `with self._cond:`
  while still inside the `with _inboxes_lock:` block. At the time of this
  round, `inbox_depth_for` and `drain_inbox` release `_inboxes_lock` before
  calling into the inbox, and `drop_session` never touches the inbox's lock at
  all — so the graph has the single edge the model proves acyclic.
  `inbox_queue.py` holds no reference to `_inboxes_lock`, so the reverse edge
  the deadlock control adds is not merely avoided by discipline, it is
  unreachable by construction. (`_writer` is corrected below in round 3 — at
  this round it still released `_inboxes_lock` before calling `put`, the
  un-nested shape the round-3 section replaces.)

No revision to `menu_lifecycle_bounded_inbox.tex`'s schemas was needed for
*this* round: the model states `boxLock`'s guard and release abstractly enough
to cover the Condition mechanism without naming it, and the round-1 `Lock`
design's failure to guard `get` is exactly the case the model's Drain guard
was already written to reject. Round 3, below, is the round that does revise
the schemas — a different producer's lock nesting, not this round's Condition
substitution.

## Fidelity: the publish path's own `regLock → boxLock` nesting (round 3, `c2f1c289`)

Copilot's re-review of `c2f1c289` (bead `lux-wk3p` round 2 of the PR, this
model's round 3) found that the schemas above still gave the publish producer
an un-nested `boxLock`: `PubAcqBox` fired straight from `pidle` with no
`regLock` precondition, modelling `_writer` calling `inbox_for(cid).put(msg)`
with the registry lock already released. That was accurate for the code as it
stood through round 2, but `c2f1c289` changed `_writer` itself:

```python
def _writer(message: ObserverMessage) -> None:
    with _inboxes_lock:
        _inbox_for_locked(connection_id).put(message)
```

`_inboxes_lock` (`regLock`) now encloses the whole `BoundedInbox.put` call,
which internally still acquires and releases its own condition lock
(`boxLock`). The publish path therefore nests `regLock → boxLock` exactly as
`offer` already did — the same edge, now climbed by both producers instead of
one.

`menu_lifecycle_bounded_inbox.tex` is revised to match:

- `REGH` gains no new values beyond what the deadlock control already had
  (`rfree | roffer | rpublish`) — `rpublish` is now live in the fixed model,
  not only in the reverse-edge control.
- `PPHASE` changes from `pidle | pbox` to `pidle | preg | pboth`, the same
  three-phase shape `OPHASE` already gives the offer producer.
- A new operation, `PubAcqReg`, precedes `PubAcqBox` and models entering the
  `with _inboxes_lock:` block. `PubAcqBox` is now guarded on `preg` (was
  `pidle`) and `PubPut` releases *both* locks together (was `boxLock` alone),
  matching `OfferPut`.

The deadlock argument's conclusion is unchanged — one edge direction, no
cycle — but it is now stated for two callers of that edge instead of one; see
the revised "Deadlock-freedom and the one-way lock edge" section of the
`.tex` file. Re-running the full suite after the revision:

- `fuzz menu_lifecycle_bounded_inbox.tex` — clean.
- `probcli -model_check -p DEFAULT_SETSIZE 2` — **no deadlock**, all 7
  operations covered (`OfferAcqReg`, `OfferAcqBox`, `OfferPut`, `PubAcqReg`,
  `PubAcqBox`, `PubPut`, `Drain`), 16 states, 26 transitions — the same state
  count as before the revision, because the publish producer's extra phase
  value replaces states the old un-nested `pbox` phase already occupied
  rather than adding new ones.
- B1 (`depth > cap`) — **NOT found**. B2 (`spuriousDrop = fset`) — **NOT
  found**. Both re-checked against the revised schemas.
- Positive reachability (`depth = cap`, `boxLock = bpublish`) — both **FOUND**,
  so the revision is not vacuously safe by never exercising the publish path.
- `menu_lifecycle_bounded_inbox_nolock_buggy.tex` — unaffected by this round
  (it never referenced `REGH`/`regLock` at all); B1 and B2 negations still
  **FOUND**.
- `menu_lifecycle_bounded_inbox_deadlock_buggy.tex` — its own header comment
  is corrected to describe the reverse-edge hypothetical against the
  round-3-fixed baseline rather than the pre-round-3 "publish never holds
  `regLock`" claim; its schemas (already carrying `rpublish` and a
  three-value `PPHASE` from when this control was first written) needed no
  change. Deadlock still **FOUND**.

This closes the specific gap Copilot named: the model, the coverage verdict,
and the shipped lock graph now agree that `_writer` holds `regLock` across the
whole put.

## The obligations, and how they are checked

The two safety properties are kept **out** of the state schema (a safety
invariant placed in the state invariant is enforced as a guard on every
successor, silently disabling the operation that would break it). Each is
checked by the reachability of its **negation**: `NOT found` against the fixed
spec means it holds on every reachable state; `FOUND` against a control means
the control reproduces the defect. Deadlock-freedom is the default `-model_check`
deadlock check.

- **B1 — bound integrity.** `depth ≤ cap`, checked as `depth > cap`.
  **`NOT found`** against `menu_lifecycle_bounded_inbox.tex` at
  `DEFAULT_SETSIZE 2` (16 states, all 7 operations covered — `PubAcqReg`
  joined the count in round 3 — no deadlock). **`FOUND`** against
  `menu_lifecycle_bounded_inbox_nolock_buggy.tex` (overshoot).
- **B2 — drop minimality (no double-drop).** `¬(spuriousDrop = fset)`: a
  `_drop_oldest` fires only from a genuinely full inbox, never discarding a
  message that had room. Checked as `spuriousDrop = fset`. **`NOT found`**
  against the fixed spec (same run). **`FOUND`** against the no-lock control
  (double-drop).
- **Deadlock-freedom.** Full `-model_check` over the reachable state space:
  **no deadlock**, all operations covered, at `DEFAULT_SETSIZE 2` (16 states).
  The inbox lock is a **leaf**: the only nesting is `regLock → boxLock`, taken
  by both the offer path and — as of round 3 (`c2f1c289`) — the publish path;
  no path takes `regLock` while holding `boxLock`. **`FOUND`** (a deadlock)
  against `menu_lifecycle_bounded_inbox_deadlock_buggy.tex`, which inverts the
  publish path's own climb into the reverse order.
- **Positive outcomes reachable** (the invariants are not vacuous):
  `depth = cap` **FOUND**; `boxLock = bpublish` **FOUND** (the publish producer
  is exercised) — both against the fixed spec.

### Isolation of the fidelity controls

| Control | States | Differs in | Negation reached |
|---|---|---|---|
| `menu_lifecycle_bounded_inbox_nolock_buggy.tex` | 161 | inbox lock removed; compound `put` split into `Check`/`DropStep`/`EnqAfterDrop`/`EnqPlain`, two producers interleaving | **B1 `depth > cap` FOUND** and **B2 `spuriousDrop = fset` FOUND** |
| `menu_lifecycle_bounded_inbox_deadlock_buggy.tex` | 6 | publish path acquires `regLock` while holding `boxLock` (`PubAcqReg`) — the reverse edge | **deadlock FOUND** |

Witness traces (ProB's search order need not return these exact traces; the
`FOUND`/`NOT found` verdict is what the gate checks):

- **Overshoot** — build to `depth = cap - 1`, then `Check(toffer); Check(tpublish);
  EnqPlain(toffer); EnqPlain(tpublish)` → `depth = cap + 1`.
- **Double-drop** — reach `depth = cap`, `Check(toffer)` (decides drop), then a
  `Drain` (recv) or a second producer's `DropStep` lowers `depth` below `cap`,
  then `DropStep(toffer)` fires at `depth < cap` → `spuriousDrop = fset`. That a
  `Drain` between check and drop also triggers it is why the fix must guard
  `get`/`drain` under `boxLock` too, not only `put`.
- **Deadlock** — `OfferAcqReg` (offer holds `regLock`, wants `boxLock`);
  `PubAcqBox` (publish holds `boxLock`, wants `regLock`) → no operation enabled.

## The lock/order the fix requires, stated explicitly

The fix adds one nesting, `regLock → boxLock`, and as of round 3 (`c2f1c289`)
**both** producers climb it the same way:

- `offer` holds `regLock` (`_inboxes_lock`) across `inbox.put`, which takes
  `boxLock`;
- the publish `_writer` now holds `regLock` across the whole of
  `BoundedInbox.put` too — it no longer releases `regLock` before calling
  `put`;
- `inbox_depth_for` and `drain_inbox` read the inbox out under `regLock`,
  release it, then take `boxLock` alone for `depth`/`drain`;
- `drop_session` takes `regLock` alone and never touches `boxLock`.

No path takes `regLock` while holding `boxLock`, and no path takes `boxLock`
with no outer lock and then reaches for `regLock`. The acquisition graph has
exactly one edge *direction*, `regLock → boxLock`, now used by two callers
instead of one; a cycle needs two, so there is no deadlock — the same
one-direction-edge structure `menu_lifecycle.tex` established for the D3
`StoreLock → HubMenuRegistry._lock` edge. The reverse-edge control shows the
property is load-bearing: invert the publish path's own climb into
`boxLock → regLock` and ProB finds the cycle.

## M1 and M1b are preserved

The bounded inbox and its lock do not disturb the delivery properties the
companions prove; both were re-checked unchanged and still hold
(`NOT found` at `DEFAULT_SETSIZE 3`):

- **M1** (`menu_lifecycle.tex`, no false-positive delivery) rests on `offer`
  holding `_inboxes_lock` (`regLock`) across its `get` and `put`, serialized
  against `drop_session`. `boxLock` is internal to the `BoundedInbox` the `get`
  returned; it neither loosens nor moves that `regLock` hold. Unaffected.
- **M1b** (`menu_lifecycle_delivery.tex`, no live-recipient loss) rests on the
  departure removing the connection from the registry before the cascade tears
  the inbox down. The bounded inbox changes neither the departure ordering nor
  the registry-discard step, and the second (publish) producer only ever calls
  `put`. Unaffected.

The bounded drop is a **separate, intentional** overflow policy (`INBOX_CAPACITY`,
mirroring the callback hold's `_HOLD_CAPACITY`), not an M1b violation: M1b forbids
loss from the delivery/departure *race*, not the capacity backstop, which is what
B1/B2 govern.

## Operation partitions and their tests

Each row names a behaviour a test must exercise; the "Covering test" column
names the real test in the file the fix landed in,
`tests/domain/test_inbox_queue.py` (note: `domain/`, not `domain/hub/`).

| Partition | Meaning | Covering test |
|---|---|---|
| **BB1 (bound under concurrent producers, the overshoot regression)** | two producers putting concurrently into a near-full inbox never leave `depth > cap` | `tests/domain/test_inbox_queue.py::test_two_producers_at_capacity_keep_the_bound_exact` — the direct regression test for overshoot |
| **BB2 (single drop per over-capacity admission, the double-drop regression)** | a producer putting into a full inbox concurrent with another put or a `recv` drops exactly one oldest, never discarding a message that had room | `tests/domain/test_inbox_queue.py::test_two_producers_at_capacity_keep_the_bound_exact` (exact final `depth == capacity` rules out both overshoot and double-drop under concurrent producers) and `tests/domain/test_inbox_queue.py::test_a_real_guarded_consumer_never_tears_puts_compound` (a racing `recv` never spuriously lowers a drop's observed length below `capacity - 1`) — the direct regression tests for double-drop; `tests/domain/test_inbox_queue.py::test_a_dequeue_between_puts_check_and_drop_causes_a_spurious_drop` is the deterministic fidelity witness reproducing the tear when the guard is bypassed |
| BB3 (put under capacity) | a `put` into an inbox below capacity enqueues without dropping; `depth` rises by one | `tests/domain/test_inbox_queue.py::test_under_capacity_is_a_plain_fifo` |
| BB4 (put at capacity) | a single `put` into a full inbox drops the oldest and enqueues the newest; `depth` stays at `cap` | `tests/domain/test_inbox_queue.py::test_at_capacity_drops_the_oldest_and_keeps_the_newest` (drop-and-admit) and `tests/domain/test_inbox_queue.py::test_a_full_inbox_warns_when_it_drops` (the loss is logged) |
| BB5 (drain under the lock) | a `recv`/`drain`/`depth` racing a `put` never observes or produces a torn queue (the `get`/`drain`/`depth` legs are under `boxLock`) | `tests/domain/test_inbox_queue.py::test_a_real_guarded_consumer_never_tears_puts_compound` |
| **DL1 (leaf-lock deadlock-freedom)** | the offer path and, as of round 3, the publish path (both `_inboxes_lock` → inbox lock) never deadlock; no path takes `_inboxes_lock` while holding the inbox lock, and no path takes the inbox lock and then reaches back for `_inboxes_lock` | covered by `probcli -model_check` in this spec; the grep-provable code check is that no `BoundedInbox` method acquires `_inboxes_lock` |

Partitions in **bold** are the direct regression requirement for overshoot
(BB1), double-drop (BB2), and deadlock-freedom (DL1). A suite that covers the
happy paths (BB3/BB4) but not BB1/BB2 would look complete and still miss both
race defects.

A sixth test, `tests/domain/test_inbox_queue.py::test_a_non_positive_capacity_is_rejected_at_construction`
(parametrized over `capacity=0` and `capacity=-1`), guards a precondition the
model assumes rather than states: every B1/B2 partition above reasons about a
queue bounded by a *positive* `capacity`. It is not a BB-row of its own — it is
a construction-time invariant (PY-CC-2/PY-EH-1), not a concurrency
interleaving — but it is what turns "the model assumes `capacity >= 1`" into
"the class enforces `capacity >= 1`," closing the gap a `capacity=0` or
negative construction would otherwise leave under every partition above.

## When to re-run

Re-run `fuzz` and the `probcli` goal checks whenever `inbox_queue.py`'s
`put`/`_drop_oldest` or its lock, or `inbox.py`'s
`offer`/`_writer`/`inbox_for`/`drop_session` (the lock nesting), change. Re-run
the companions' checks (`menu_lifecycle.tex`, `menu_lifecycle_delivery.tex`)
too: M1 and M1b are proved there, and this change is designed to leave them
untouched.
