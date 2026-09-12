# Agent-Menu Lifecycle: Model-Check Result and Test-Partition Coverage

Companion to `docs/menu_lifecycle.tex`, following the format of
`docs/connection_lease_reaping_coverage.md`. This is a **modeling-mission**
artifact (bead `lux-m3xr`, PR #495, design
`docs/architecture/agent-menu-dispatch.md`, DES-098): the model is the
merge gate for the three concurrency/lifecycle defects the implementation
review surfaced, and the partitions below are the contract the fix's tests
must cover. A partition left unchecked when the fix lands is a gap, not a
missing row.

## Why this model exists (the z-spec determination)

The design's Section 6 stated a tripwire: the menu-event enqueue reuses
proven mechanics *unless* it needs a new lock or a new acquisition order,
in which case z-spec becomes **required**. The implementation review found
the tripwire tripped. Three defects, each of the concurrency /
stateful-lifecycle class the repo's z-spec policy makes model-checking
mandatory for, and the same *class* recurring across the delivery, the
departure, and the store paths — the recurrence signal:

- **D1** (`inbox.py:110-125`, `offer`) — the tripwire itself. The enqueue is
  not atomic with departure: `offer` reads the queue under `_inboxes_lock`,
  releases the lock, then puts. A `drop_session` in that window lands the put
  in an orphan and `offer` returns `True` — `MenuEventRouter.deliver` reports
  `"delivered"` for a click no `recv()` will drain. A **false-positive
  delivery**; the click is silently lost. The current docstring's claim that
  the orphan case is "no delivery to a departed session, no leaked entry" is
  false — the caller is *told delivered*.
- **D2** (departure cascade wiring) — `inbox.drop_session` is bound into the
  shared `DepartureCascade` (via `inbox.ensure_writer` →
  `HubDisplay.bind_departure_sink`) and fires on every departure trigger;
  the menu prune (`OPERATIONS.drop_session` → `MenuOperations.drop_session`
  → `HubMenuRegistry.drop_session`) is wired **only** to
  `session_cleanup.py:48`, the graceful/SDK-idle teardown leg. On the
  lease-lapse path (`reap_lapsed_leases` → `_depart_lapsed` → `cascade`)
  nothing prunes the menu registry, so a timer-reaped owner's bar entry
  never leaves `_by_owner`.
- **D3** (`operations/menus.py:67-72`, `set_menu`) — admit/store TOCTOU.
  `MenuArming.admit` renews, arms, and checks the caller live-and-identified
  under `StoreLock`, then releases it; `HubMenuRegistry.set_menus` records the
  bar afterward under the menu registry's own separate lock. A departure in
  that window stores a bar for an already-departed owner — the departure
  already swept the registry, so nothing revisits it.

The model refines `docs/connection_lease_reaping.tex`'s departure cascade:
`DepartGraceful`/`DepartLapsed` here sweep the **menu registry** and the
**inbox** as cascade legs, exactly as that model swept scene ownership,
subscriptions, and the writer binding. MO (below) is that model's I5/I7
"leaving the registry is one event, however triggered" applied to a fourth
cascade leg.

## The invariants, and how they are checked

Both properties are kept **out** of the state schema (a safety invariant
placed in the state invariant is enforced as a guard on every successor,
silently disabling the operation that would break it). Each is checked by
the reachability of its **negation**: `NOT found` against the fixed spec
means the invariant holds on every reachable state; `FOUND` against a
fidelity control means the control reproduces the defect.

- **M1 — no false-positive delivery (orphan put).**
  `¬(reported = ddelivered ∧ lost = fset)`. A click reported delivered is
  not sitting in a queue that was *already gone at put time*. **`NOT found`**
  against `menu_lifecycle.tex` at `DEFAULT_SETSIZE 3` (3,993 states, 10
  operations covered, no deadlock). **`FOUND`** against
  `menu_lifecycle_d1_buggy.tex`.
- **M1b — no live-recipient loss (offer-then-drop-discards).**
  `¬(lostLive = fset)`. A menu event put onto a *live* inbox that a departure
  then tears down is never lost to a connection *still in the registry* — the
  discard only ever strikes an already-departed recipient. This is the distinct
  window a round-6 review raised: the base model's atomic `MenuDeliver`
  abstracts it away (no token for the enqueued event, atomic departure), so it
  is proved in the companion refinement `menu_lifecycle_delivery.tex`, which
  adds a `pending` token, a `Drain`, and a two-phase departure (registry
  discard then inbox teardown — the code's `HubDisplay._depart` order).
  **`NOT found`** against `menu_lifecycle_delivery.tex` at `DEFAULT_SETSIZE 3`
  (1,220 states, 8 operations covered, no deadlock). **`FOUND`** against
  `menu_lifecycle_delivery_reorder_buggy.tex` (cascade legs reversed). The
  reviewer's exact interleaving — a stale-read delivery landing in the
  doomed-but-present inbox of an already-deregistered connection — is confirmed
  *reachable and benign*: `Connect(c); Arm(c); DepartRegistry(c);
  MenuDeliver(c)` reaches `c ∈ pending ∩ hasInbox ∧ c ∉ registered ∧
  departPhase = tinbox`, and the subsequent `DepartInbox(c)` discards it with
  `lostLive = fclear`.
- **MO — menu-ownership integrity.**
  `¬∃ c: c ∈ menuOwner ∧ c ∉ registered`, i.e. `menuOwner ⊆ registered`. No
  session owns a bar unless it is live. **`NOT found`** against
  `menu_lifecycle.tex` (same run). **`FOUND`** against both
  `menu_lifecycle_d2_buggy.tex` and `menu_lifecycle_d3_buggy.tex`.
- **Positive outcomes reachable** (the invariants are not vacuous):
  `reported = ddelivered ∧ lost = fclear` **FOUND**;
  `∃ c: c ∈ menuOwner ∧ c ∈ registered` **FOUND**;
  `reported = dgone` **FOUND** — all against the fixed spec.
- **Deadlock-freedom and the structural state invariant.** Full
  `-model_check` over the reachable state space: **no deadlock**, all
  operations covered, at `DEFAULT_SETSIZE 3` — fixed spec 3,993 states, D1
  control 26,620, D2 control 17,496, D3 control 49,572.

### Isolation of the fidelity controls

Each control differs from the fixed spec in exactly one operation and
violates exactly one invariant:

| Control | Differs in | M1 negation | MO negation |
|---|---|---|---|
| `menu_lifecycle_d1_buggy.tex` | `MenuDeliver` → `OfferBegin*`/`OfferEnd` (offer split) | **FOUND** | `NOT found` |
| `menu_lifecycle_d2_buggy.tex` | `DepartLapsed` drops the `menuOwner` sweep | `NOT found` | **FOUND** |
| `menu_lifecycle_d3_buggy.tex` | `SetMenu` → `SetMenuAdmit`/`SetMenuStore` (admit/store split) | `NOT found` | **FOUND** |

The companion delivery refinement (`menu_lifecycle_delivery.tex`) carries its
own control for the M1b window:

| Control | Differs in | M1b negation (`lostLive = fset`) |
|---|---|---|
| `menu_lifecycle_delivery_reorder_buggy.tex` | departure legs run in the wrong order — `DepartInboxFirst` (inbox teardown) before `DepartRegistryAfter` (registry discard) | **FOUND** |

Against the fixed `menu_lifecycle_delivery.tex` the same goal is `NOT found`.
The control demonstrates that the code's discard-before-cascade order
(`HubDisplay._depart` runs `_clients.discard` before `_cascade.run` →
`inbox.drop_session`, under one `StoreLock` hold) is load-bearing: reverse it
and a delivered-but-undrained click is lost to a still-live recipient.

The witness traces are the ones named in the spec's Fidelity section: D1,
`OfferBeginPresent(c); DepartGraceful(c); OfferEnd`; D2,
`Connect(c); Identify(c); SetMenu(c); LeaseLapse(c); DepartLapsed(c)`; D3,
`Connect(c); Identify(c); SetMenuAdmit(c); DepartGraceful(c); SetMenuStore`.
ProB's search order is not obliged to return the identical trace on every
run; the `FOUND`/`NOT found` verdict is what the gate checks.

## The lock/order the fix requires that is NOT in connection_lease_reaping

D1's and D2's fixes introduce **no new lock and no new order** (this is why
the design judged the common case safe):

- **D1** — atomicity *within* `_inboxes_lock`: `offer`'s `get` and `put`
  under one hold of the lock it already takes. `MenuEventRouter.deliver`'s
  live-set read (client-registry lock, released) → `offer` (`_inboxes_lock`)
  is the exact order `CallbackRouter.route` already uses.
- **D2** — one more sink on the `DepartureCascade`, which already runs under
  `StoreLock` on every departure path.

D3's fix **does** introduce a new nesting, and it is named here explicitly
per the mission's requirement: the admit-liveness check and the
`set_menus` store must fall under one `StoreLock` hold, so the menu
registry's own lock (`HubMenuRegistry._lock`) is acquired **inside**
`StoreLock` — the order **`StoreLock` → `HubMenuRegistry._lock`**, which the
shipped code does not have (`set_menus` runs under the menu lock alone,
after `StoreLock` is released). This is deadlock-free because it points the
same direction as D2's fix: the departure cascade's menu sink also fires
under `StoreLock` and then takes the menu lock. Both the store path and the
departure path acquire the two locks in the same order, so the
acquisition graph gains only edges pointing one way, and a cycle needs two.
`StoreLock` is the outer lock on every Hub path today; the menu registry
lock joining as a consistently-inner lock is one more caller taking the
locks in the order every existing caller already does.

## The write-set the model proves correct (for gvr)

The model's product. Each fix is the minimal change that makes the
corresponding invariant hold, and the model proves it does.

| Defect | File | Fix the model proves |
|---|---|---|
| **D1** | `src/punt_lux/domain/hub/inbox.py` (`offer`) | Hold `_inboxes_lock` across **both** the `get` and the `put` — move `inbox.put(message)` inside the `with _inboxes_lock:` block. Then a `drop_session` cannot interleave: a present inbox receives the put atomically (`return True`), an absent one returns `False` (→ `provider_gone`). Correct the docstring: the orphan case does *not* occur under the fix; the pre-fix code reported delivered into it. (Equivalent-but-inferior: re-check membership after the put and `return False` on an orphan — the model proves the one-hold form; prefer it.) |
| **D2** | departure cascade wiring — `src/punt_lux/domain/hub/inbox.py`/`menu_registry.py`/`operations/menu_arming.py` + `hub_display.py` cascade | Bind `HubMenuRegistry.drop_session` (or `MenuOperations.drop_session`) as a `DepartureSink` via `HubDisplay.bind_departure_sink`, the same way `inbox.drop_session` is bound in `inbox.ensure_writer`. Arm it when the owner is admitted (the `MenuArming.admit` → `ensure_writer` moment is the natural site). It then fires from `_depart` **and** `_depart_lapsed` (every trigger), under `StoreLock`, not only from `session_cleanup.py`'s graceful leg. |
| **D3** | `src/punt_lux/operations/menus.py` (`set_menu`) | Hold `StoreLock` across the admit-liveness check and the `set_menus` store — run the `set_menu` body inside `hub_display.write_lock()` (reentrant, so `admit`→`ensure_writer`'s own acquisition nests), with `set_menus` called within that hold. No departure can interleave between the liveness gate and the store. Introduces the `StoreLock → HubMenuRegistry._lock` nesting named above (deadlock-free). |

## Operation partitions and their tests

Each row names a behaviour a test must exercise; the "Expected covering
test" column names where the test belongs, not one that exists today.
Replace each placeholder with the real test name when the fix lands.

| Partition | Meaning | Expected covering test |
|---|---|---|
| **MD1 (deliver-to-live, D1 happy)** | a click for a live session with a live inbox lands on that inbox and is reported delivered | `tests/domain/hub/test_menu_event.py::test_a_click_for_a_live_inbox_is_delivered` |
| **MD2 (offer atomic, the D1 regression)** | a `drop_session` racing an `offer` never yields a reported-delivered click in a dropped queue — either the put lands on the live inbox and reports delivered, or the inbox is already gone and it reports `provider_gone`; never delivered-into-orphan | `tests/domain/hub/test_inbox.py::test_offer_racing_drop_session_never_reports_a_false_delivery` — the direct regression test for D1 |
| MD3 (provider-gone, live-check) | a click for a session gone from the live set is `provider_gone`, not delivered | `tests/domain/hub/test_menu_event.py::test_a_click_for_a_departed_session_is_provider_gone` |
| MD4 (provider-gone, no inbox) | a click for a live session with no inbox (never armed / already dropped) is `provider_gone`, not delivered | `tests/domain/hub/test_inbox.py::test_offer_to_a_session_without_an_inbox_returns_false` |
| MD5 (offer-then-drop-discards, benign) | a click delivered onto a live inbox that a departure then tears down is lost only when its recipient has already departed — never for a still-registered session — and the departed owner's bar is re-pushed by the departure cascade, not the click path | `tests/domain/hub/test_menu_event.py::test_a_click_delivered_then_departed_is_lost_only_for_a_gone_recipient` (proved by `menu_lifecycle_delivery.tex` M1b; the test asserts the departure re-push, not click-path re-push) |
| **MW1 (all-paths-withdraw, the D2 regression)** | a session's bar leaves the menu registry on **every** departure trigger — graceful disconnect, SDK idle-reap, **and** the lease-lapse timed sweep | `tests/domain/hub/test_menu_registry.py::test_a_timer_reaped_owners_bar_leaves_the_registry` — the direct regression test for D2 |
| MW2 (graceful withdraw) | `drop_connection` prunes the departing session's bar in the same step it removes it from the registry | `tests/domain/hub/test_hub_display.py::test_graceful_disconnect_prunes_the_menu_bar` |
| MW3 (departed bar never renders) | `wire_snapshot`/`menu_bar` filter to the live set, so a stale bar never renders even in the pre-prune window | `tests/domain/hub/test_menu_registry.py::test_wire_snapshot_excludes_a_departed_owner` (existing behaviour the fix must not weaken) |
| **MS1 (no-store-for-departed, the D3 regression)** | a `set_menu` whose owner departs between admit and store never leaves a bar for a session no longer live — the store is refused, or runs under the same lock the departure takes so no window exists | `tests/operations/test_menus.py::test_set_menu_racing_a_disconnect_never_stores_for_a_departed_owner` — the direct regression test for D3 |
| MS2 (admitted store) | a live, identified session's `set_menu` records its bar under it and arms its inbox | `tests/operations/test_menus.py::test_set_menu_records_the_bar_for_an_identified_owner` |
| MS3 (anonymous refused) | an unidentified (or unregistered) session's `set_menu` is refused; nothing armed, nothing stored | `tests/operations/test_menus.py::test_set_menu_refuses_an_anonymous_session` |
| MO1 (ownership integrity, invariant) | at no point does the registry hold a bar for a session absent from the live set, across interleaved set/deliver/depart | `tests/operations/test_menus.py::test_menu_ownership_never_outlives_the_session` (property-style, over interleavings) |
| DL1 (deadlock-freedom) | the set/deliver/depart state machine has no reachable dead state | covered by `probcli -model_check` in this spec; no unit-test counterpart |

Partitions in **bold** are the direct regression requirement for D1
(MD2), D2 (MW1), and D3 (MS1). A suite that covers MD1/MW2/MS2 (the happy
paths) but not MD2/MW1/MS1 would look complete and still miss all three
defects — precisely the "looked complete, wasn't" recurrence the org's
z-spec mandate names, here caught before a third empirical review round.

## When to re-run

Re-run `fuzz` and the `probcli` goal checks for **both**
`docs/menu_lifecycle.tex` (M1 orphan-put, MO) and its companion
`docs/menu_lifecycle_delivery.tex` (M1b live-recipient loss) whenever
`inbox.py`'s `offer`/`drop_session`/
`ensure_writer`, `menu_registry.py`'s `set_menus`/`drop_session`,
`menu_event.py`'s `MenuEventRouter.deliver`, `operations/menus.py`'s
`set_menu`, `operations/menu_arming.py`'s `admit`, `hub_display.py`'s
`_depart`/`_depart_lapsed`/`drop_connection`, `departure_cascade.py`, or
`session_cleanup.py` change.
