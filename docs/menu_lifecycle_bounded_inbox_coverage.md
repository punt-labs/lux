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
  while still inside the `with _inboxes_lock:` block. Every other caller of a
  `BoundedInbox` method (`_writer`, `inbox_depth_for`, `drain_inbox`) releases
  `_inboxes_lock` before calling into the inbox, and `drop_session` never
  touches the inbox's lock at all — so the graph has the single edge the model
  proves acyclic. `inbox_queue.py` holds no reference to `_inboxes_lock`, so
  the reverse edge the deadlock control adds is not merely avoided by
  discipline, it is unreachable by construction.

No revision to `menu_lifecycle_bounded_inbox.tex`'s schemas is needed: the
model states `boxLock`'s guard and release abstractly enough to cover the
Condition mechanism without naming it, and the round-1 `Lock` design's failure
to guard `get` is exactly the case the model's Drain guard was already written
to reject.

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
  `DEFAULT_SETSIZE 2` (16 states, 6 operations covered, no deadlock).
  **`FOUND`** against `menu_lifecycle_bounded_inbox_nolock_buggy.tex`
  (overshoot).
- **B2 — drop minimality (no double-drop).** `¬(spuriousDrop = fset)`: a
  `_drop_oldest` fires only from a genuinely full inbox, never discarding a
  message that had room. Checked as `spuriousDrop = fset`. **`NOT found`**
  against the fixed spec (same run). **`FOUND`** against the no-lock control
  (double-drop).
- **Deadlock-freedom.** Full `-model_check` over the reachable state space:
  **no deadlock**, all operations covered, at `DEFAULT_SETSIZE 2` (16 states).
  The inbox lock is a **leaf**: the only nesting is `regLock → boxLock` (offer
  path); the publish path takes `boxLock` alone; no path takes `regLock` while
  holding `boxLock`. **`FOUND`** (a deadlock) against
  `menu_lifecycle_bounded_inbox_deadlock_buggy.tex`, which adds the reverse edge.
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

The fix adds one nesting: `offer` holds `regLock` (`_inboxes_lock`) across
`inbox.put`, which now takes `boxLock` — the edge **`regLock → boxLock`**. Every
other `boxLock` holder takes it alone:

- the publish `_writer` runs `put` after `inbox_for` released `regLock`;
- `inbox_depth_for` and `drain_inbox` read the inbox out under `regLock`,
  release it, then take `boxLock` for `depth`/`drain`;
- `drop_session` takes `regLock` alone and never touches `boxLock`.

No path takes `regLock` while holding `boxLock`. The acquisition graph is the
single edge `regLock → boxLock`; a cycle needs two, so there is no deadlock —
the same one-direction-edge structure `menu_lifecycle.tex` established for the
D3 `StoreLock → HubMenuRegistry._lock` edge. The reverse-edge control shows the
property is load-bearing: add `boxLock → regLock` and ProB finds the cycle.

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

Each row names a behaviour a test must exercise; the "Expected covering test"
column names where the test belongs, not one that exists today. Replace each
placeholder with the real test name when the fix lands.

| Partition | Meaning | Expected covering test |
|---|---|---|
| **BB1 (bound under concurrent producers, the overshoot regression)** | two producers putting concurrently into a near-full inbox never leave `depth > cap` | `tests/domain/hub/test_inbox_queue.py::test_concurrent_puts_never_exceed_capacity` — the direct regression test for overshoot |
| **BB2 (single drop per over-capacity admission, the double-drop regression)** | a producer putting into a full inbox concurrent with another put or a `recv` drops exactly one oldest, never discarding a message that had room | `tests/domain/hub/test_inbox_queue.py::test_concurrent_overflow_drops_exactly_one` — the direct regression test for double-drop |
| BB3 (put under capacity) | a `put` into an inbox below capacity enqueues without dropping; `depth` rises by one | `tests/domain/hub/test_inbox_queue.py::test_put_below_capacity_enqueues` |
| BB4 (put at capacity) | a single `put` into a full inbox drops the oldest and enqueues the newest; `depth` stays at `cap` | `tests/domain/hub/test_inbox_queue.py::test_put_at_capacity_drops_oldest` |
| BB5 (drain under the lock) | a `recv`/`drain`/`depth` racing a `put` never observes or produces a torn queue (the `get`/`drain`/`depth` legs are under `boxLock`) | `tests/domain/hub/test_inbox_queue.py::test_recv_racing_put_is_consistent` |
| **DL1 (leaf-lock deadlock-freedom)** | the offer path (`_inboxes_lock` → inbox lock) and the publish path (inbox lock alone) never deadlock; no path takes `_inboxes_lock` while holding the inbox lock | covered by `probcli -model_check` in this spec; the grep-provable code check is that no `BoundedInbox` method acquires `_inboxes_lock` |

Partitions in **bold** are the direct regression requirement for overshoot
(BB1), double-drop (BB2), and deadlock-freedom (DL1). A suite that covers the
happy paths (BB3/BB4) but not BB1/BB2 would look complete and still miss both
race defects.

## When to re-run

Re-run `fuzz` and the `probcli` goal checks whenever `inbox_queue.py`'s
`put`/`_drop_oldest` or its lock, or `inbox.py`'s
`offer`/`_writer`/`inbox_for`/`drop_session` (the lock nesting), change. Re-run
the companions' checks (`menu_lifecycle.tex`, `menu_lifecycle_delivery.tex`)
too: M1 and M1b are proved there, and this change is designed to leave them
untouched.
