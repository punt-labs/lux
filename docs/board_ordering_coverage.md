# Board Ordering: Test Partitions and Coverage

Companion to [`board_ordering.tex`](./board_ordering.tex) and its three
fidelity controls. The spec proves what the design guarantees; this document
says which partitions of that state space the tests must exercise, and what a
test has to do to count as covering one.

The rule the whole document rests on: **a test that stubs the mechanism is a
gap, not coverage.** A test that monkeypatches the push, or drives one worker
where the property is about two, exercises the premise rather than the
mechanism. Each partition below names what must be real.

## The model in one paragraph

Every board carries the `BoardOrder` place its load took when it *began*. The
slot keeps the board with the later place; the display shows whatever a push
last wrote. The spec's five properties are: the slot never goes backwards
(I1), the glass never goes backwards (I2), at rest the glass shows the newest
board any push settled on (I3), the glass never runs ahead of the slot (I4),
and the glass never shows a board the slot refused (I5).

## What the implementation must do

Three obligations, from `board_ordering.tex` §8. Every partition below tests
one of them.

1. **Every push reads the slot inside the push region** — not a board captured
   before the raise, and not the board this worker just loaded.
2. **A refresh stores before it pushes** — store, then push what the slot holds.
3. **The failure message comes from the slot** — the state holding no board
   carries the reason it holds none, so "render what the slot holds" covers the
   failure as it covers the placeholder. Failing that, the message is pushed
   inside the push region and only when the glass shows no board.

And one structural obligation: the push region is a lock held across the socket
write, taken outside the slot's lock and never the other way round.

## Where the tests are

Every partition below is covered by a test in
[`tests/applets/test_board_ordering.py`](../tests/applets/test_board_ordering.py)
unless the table says otherwise. The mapping:

| Partition | Test |
|---|---|
| P1 | `test_two_pushes_land_in_the_order_they_were_taken` |
| P2 | structurally unconstructable since lux-81t3.5 (DES-088) removed the client-side raise -- see "P2 and P3" below |
| P3 | structurally unconstructable since lux-81t3.5 (DES-088) -- see "P2 and P3" below |
| P4 | `test_a_refresh_stores_its_board_before_it_shows_it` |
| P5 | `test_a_board_the_slot_refused_never_reaches_the_display` |
| P6 | structurally unconstructable, for a distinct reason from P2/P3 -- see "P6" below |
| P7 | `test_the_first_placeholder_of_a_session_still_appears` |
| P8 | `test_the_failure_message_never_lands_over_a_board`, and at the service level `test_a_board_that_arrives_mid_click_outlives_the_click_that_failed` in [`test_beads_service.py`](../tests/applets/test_beads_service.py) |
| P9 | `test_the_failure_message_appears_when_there_is_nothing_to_lose` |
| P10 | `test_the_slot_keeps_the_board_whose_load_began_last`, over the slot's own contention in [`test_board_slot.py`](../tests/applets/test_board_slot.py) |
| P11 | `test_nothing_writes_the_display_from_outside_the_push_region` |
| P12 | `test_a_store_landing_during_a_push_leaves_the_display_one_behind` |

Eight of them fail against the pre-region code, which is the fidelity result:
with the region's lock and re-read removed and the refresh's push moved back
in front of its store, P1–P6, P8 and P11 fail and P7, P9, P10 and P12 still
pass — the same split the models report, since I1 holds in every variant and
P12 asserts a state the committed design also reaches. P2's failure is the
review's own witness: the display ends on `lux-stale` after the refresh landed
`lux-fresh`.

## What the implementation looks like

The obligations landed as four collaborators, in case a later reader is looking
for them by name:

- `applets/board_glass.py` — the push region: the lock, held across the write,
  with the slot read inside it.
- `applets/applet_board.py` — the load, the slot and the region as one object,
  so that keeping a board and showing it are one call apart and in that order.
- `CachedBoard.shows` / `CachedBoard.said` — a state puts *itself* on the
  display and says what the click's line should call it; the region chooses
  which state, and notes what actually went up rather than what the click
  intended.
- `applets/blank_board.py` and its two states — the placeholder and the failure
  message are things a state *holds*, so obligation 3's clean shape holds: the
  message goes up the way a board does, through the same region.

## Partitions

### P1 — Two pushes, opposite completion order (I2)

Two workers each push; their socket writes complete in the reverse of the order
they began. The test must show the display ends at the newer board.

- What must be real: two threads actually contending for the push region, and a
  push whose write can be made to complete late. Stubbing the push to be
  instantaneous removes the partition.
- Failing form (the defect): the older write lands last and stays.
- This is the partition the four review rounds kept re-finding.

### P2 and P3 — structurally unconstructable since lux-81t3.5 (DES-088)

P2 ("a captured board versus a stored one", I2, obligation 1) and P3 ("a click
that stands down", I2) both gated a stood-down or in-flight click's
`acknowledge` phase at its **raise** — the client-side round trip to the
display that used to sit between "observe the slot" and "push." lux-81t3.5
(DES-088) removed that round trip: raising a frame is now a Display-local act
with no Hub client op, so `acknowledge` performs no I/O between reading the
slot and calling `BoardGlass.shows`, which itself re-reads the slot fresh,
under its own lock, immediately before every push. There is no longer a
gateable point between "observe" and "push" on a click's own thread, so both
partitions are no longer constructible — not merely untested, structurally
absent. The invariant they protected (I2: the display never shows what a
pusher captured before a newer board landed) still holds, now by
construction; the interleaving that remains reachable — two writers both
inside `BoardGlass`'s lock — is P1's test. See the `# --- P2 ---` /
`# --- P3 ---` comment blocks in
[`test_board_ordering.py`](../tests/applets/test_board_ordering.py) for the
full reasoning kept beside the code it concerns.

### P4 — Refresh: store before push (I4, obligation 2)

A single refresh, no concurrency at all.

- Assertion: at no point between the load returning and the push landing does
  the display hold a board the slot does not. Concretely: the store happens
  first, and the push carries the slot's board.
- The current code violates this on every refresh, so this partition is a
  regression test with a one-worker witness — the cheapest test in the set and
  the one that would have caught the second half of the defect.

### P5 — Warm-up stores, click pushes an older board (I5)

A click's load begins; a reconnect fires the warm-up on another thread; the
warm-up's load begins later and stores first; the click's load returns.

- Assertion: the click does not put its own board on the display, because the
  slot refused it. The display shows the warm-up's board or the previous one —
  never the refused one.
- What must be real: the warm-up must go through `BeadsService.prefetch`, which
  stores and does not push. A test that also pushes from the warm-up removes
  the asymmetry the partition is about.

### P6 — Placeholder must not blank a board (I2) — structurally unconstructable

The slot holds no board, a click settles on the placeholder, and a board lands
on the display before the placeholder does.

- Assertion (as originally stated): the placeholder does not reach the
  display.
- Boundary partner of P7: the *first* placeholder of a session must reach it.

**Reconsidered for round 2 (lux-81t3.5).** Unlike P2/P3, P6 does not lose its
gateable point — `BoardGlass.shows`'s socket write (the `pushes` gate
`test_a_store_landing_during_a_push_leaves_the_display_one_behind` already
exercises) is untouched by this change. The question is whether gating there,
rather than at the deleted raise, still constructs the race. It does not,
for a stronger, distinct reason: `BoardGlass._lock` fully serialises every
call to `shows` — read-then-write, one writer at a time — so for P6 to hold, a
board's own `shows` call would have to complete and land *before* the
placeholder's `shows` call reads the slot. But a completed push can only be
observed by a later reader (the lock guarantees it), so a placeholder-click
that reads an empty slot proves no board's push has landed yet, and any push
still holding the lock blocks every other caller — including a real board's —
until it releases. A store landing mid-push (`BoardSlot.store` does not take
this lock) cannot retroactively change what a push already in flight sends;
that is exactly the gap P12 measures and names as accepted staleness, not a
P6-shaped violation. Gating `pushes` this way reconstructs P12's scenario
(`test_a_store_landing_during_a_push_leaves_the_display_one_behind`, which
proves the earlier-decided value lands and a later store does not
retroactively pre-empt it) — not a new one. See the `# --- P6 ---` comment
block in
[`test_board_ordering.py`](../tests/applets/test_board_ordering.py) for the
full reasoning kept beside the code it concerns.

### P7 — The first placeholder still appears (liveness of the cold click)

Cold session, nothing loaded, nothing on the display, one click.

- Assertion: the placeholder is pushed.
- Why it matters: this is the partition a strict monotone push counter breaks.
  ProB reports `BlankStage` never covered in
  `board_ordering_gate_only_buggy.tex` — the counter suppresses every place-0
  push, including this one. Any future ordering mechanism must be checked
  against this partition before it is believed.

### P8 — Failure message must not blank a board (I2, obligation 3)

The slot holds no board and a load fails while another worker has put a board
on the display.

- Assertion: the red message does not replace the board.
- If obligation 3 is met by moving the reason into the no-board state, this
  partition is covered by P6's mechanism and the test asserts the same thing
  about a different content.

### P9 — Failure message does appear when there is nothing to lose (liveness)

Cold session, nothing on the display, `bd` fails.

- Assertion: the red message reaches the display and names the reason.
- Boundary partner of P8, and the one that stops P8's fix from becoming
  "never show errors".

### P10 — The slot's own ordering (I1)

Two loads, the later-starting one returning first, both stored.

- Assertion: the slot holds the later-starting board regardless of return
  order, and a state holding no board never displaces one that does.
- This is already the shipped `BoardSlot` behaviour and I1 holds in every
  variant including the buggy ones. Listed for completeness: it is the
  partition that must not regress while the push is being changed.

### P11 — Lock discipline (deadlock-freedom)

Not a runtime test but a review obligation, because a deadlock test is a test
that hangs.

- The push region's lock is acquired outside the slot's lock, never inside it.
  Grep obligation: no acquisition of the push lock anywhere within the slot's
  critical section.
- `board_slot.py`'s module docstring currently states that there is no second
  lock to order the slot's against. That sentence becomes false with this
  change and must be replaced by the ordering.

### P12 — The boundary that is not closed

One generation of staleness survives: a store landing between a push's read of
the slot and its write leaves the display one board behind, because the slot's
lock is not held across a socket write. This is reachable in the committed
model and violates nothing.

- No test asserts its absence. A test that did would be asserting a property
  the design does not have.
- If a test is written for this region at all, it asserts the weaker true
  thing: the display is never *ahead* of the slot and never *behind* a board it
  has already shown.

## Coverage of the model's operations

ProB reports all operations covered for `board_ordering.tex` (270 states, 657
transitions, exhaustive) and for `board_ordering_reread_only_buggy.tex` (945
states). `board_ordering_gate_only_buggy.tex` leaves `BlankStage` uncovered,
which is the finding recorded in P7 rather than a modelling gap.

| Model | States | I1 | I2 | I3 | I4 | I5 |
|---|---|---|---|---|---|---|
| `board_ordering.tex` (committed) | 270 | holds | holds | holds | holds | holds |
| `board_ordering_current_buggy.tex` | 3275 | holds | **fails** | **fails** | **fails** | **fails** |
| `board_ordering_gate_only_buggy.tex` | 530 | holds | **fails** | **fails** | **fails** | **fails** |
| `board_ordering_reread_only_buggy.tex` | 945 | holds | **fails** | **fails** | holds | holds |

Re-run `fuzz` and the goal checks whenever `board_slot.py`, `held_board.py`,
`no_board.py`, `board_channel.py`, or `beads_service.py` changes. The commands
are in each document's header.
