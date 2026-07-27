# Display Crash-Loop Quarantine

**Status:** designed and ProB-verified; **implementation deferred** (operator
ruling 2026-07-27 — keep the design, build it if the need re-appears). The
companion model is [`display_crash_loop.tex`](../display_crash_loop.tex) with
two fidelity controls; bead lux-88ka tracks the deferred implementation.

## The defect

A scene that is valid at the Hub can still crash the Display's renderer. During
the B5 demo a `draw` scene passed Hub-side self-validation, replicated to the
Display, and hit a renderer `TypeError` (the `add_rect` argument-order defect,
since fixed). The renderer crash killed the Display process.

The scene did not die with the process. It stayed live in `HubDisplay`, the
authoritative store. So the loop was:

1. The Hub replicates the poison scene to the Display.
2. The Display renders it, crashes, and its process exits.
3. The Hub's next send fails; `SendRecovery` reaps and respawns the Display and
   re-marks **every** live scene for repaint (`recovery.py`, `_remark`).
4. The fresh Display connects, receives the poison scene again, and crashes
   again.

Each respawn opened a new GLFW window that stole macOS keyboard focus, roughly
every ten seconds, until the operator cleared the scenes by hand.

The renderer bug is fixed. The lifecycle gap is not: nothing in the Hub attributes
a Display death to the scene that caused it, and nothing stops a poison scene from
being re-fed to every respawned Display. This document designs that missing
mechanism.

## What the Hub actually knows

The design is bounded by the Hub's real evidence about a Display death, so start
there.

- **The Display process is detached.** `DisplayPaths._spawn` launches it with
  `subprocess.Popen(..., start_new_session=True)` and never retains the handle or
  waits on it. The Hub therefore has **no exit code and no exit signal** for the
  Display. Any attribution rule that depends on reading why the Display died is
  not implementable without adding a supervisor that owns the process handle —
  out of scope, and a larger change than the loop warrants.
- **The Hub learns of a death only through a failed send.** The sole writer to
  the Display is `HubReplicator`'s worker thread. A death surfaces as
  `BlockingIOError` (send timed out — a wedged or crashing peer that stopped
  draining its socket) or `OSError` (dead peer — the socket closed). Both are
  already caught in `replicator.py` (`_push_cycle`).
- **The Hub knows what it was sending.** At the moment a send fails, the worker
  holds the `DrainedBatch` it was pushing — the exact set of scenes in flight.
  That set, and nothing richer, is the evidence a scene caused the death.

So attribution can only be *correlational*: a scene is suspect because it was
being sent when the Display died, and it becomes *attributed* when it is the
common factor across repeated deaths. This is the "N deaths with S in the replica
set" signal named in the contract, made precise below. The "death within M
seconds of replicating S" framing is rejected on its own: a single death within a
window is exactly the transient case (a wedged display, a GPU hiccup) that must
**not** quarantine an innocent scene.

## Question 1 — the attribution rule

**Rule.** The replicator runs in one of two modes and maintains a per-scene death
tally.

- **Batching mode (normal).** The worker coalesces dirty scenes into one
  `DrainedBatch` and sends them together, as it does today.
- **Every death is attributed to its suspect set — no death is free.** The
  suspect set is whatever was in flight when the Display died: in batching mode
  that is the **whole batch**, in isolation mode it is the **single scene** being
  probed. Each scene in the suspect set has its tally incremented. Attributing the
  batched death too is what stops a scene that only ever crashes while coalesced
  from escaping the tally forever.
- **On the first send failure**, the worker switches to **isolation mode**: it
  stops coalescing and sends each live scene in its **own** send, checking the
  connection is alive between sends. From here on every death has a singleton
  suspect, so the tally converges on the true culprit rather than smearing across
  the innocents that shared the first batch.
- A scene that reaches **`ATTRIBUTION_THRESHOLD` (2)** attributed deaths within
  the rolling window **`ATTRIBUTION_WINDOW` (60 s)** is quarantined (Question 2).
  The window is the only decay: a death older than the window no longer counts
  toward the threshold. There is deliberately **no** tally reset on a clean send
  (see the rejected alternatives).
- **Isolation-mode exit — only on a stable interval.** The worker returns to
  batching mode only after the Display has served for **`STABLE_INTERVAL`** with
  **no death at all** — not after one clean pass, and not on a quarantine. Any
  death, of any scene, restarts the interval. This is what catches an
  *intermittently* poisonous scene: isolation persists across its clean renders
  until it crashes enough times to be quarantined, instead of exiting the moment
  it happens to render cleanly. A quarantined scene is not replicated, so once the
  crashing scenes are all quarantined the interval finally elapses and the worker
  resumes coalescing.

**The three constants and their defaults.** `ATTRIBUTION_THRESHOLD`,
`ATTRIBUTION_WINDOW`, and `STABLE_INTERVAL` are named constants, not inline
literals, so the policy is one place to read and to tune.

- **`ATTRIBUTION_THRESHOLD` = 2.** One isolated death admits a non-scene cause
  (memory pressure, a driver fault) that coincided with a render; requiring the
  *same* scene to be the sole suspect twice excludes the one-off. Two is the
  smallest value that does so — a genuinely poison scene, which crashes the
  renderer on every render, reaches it in the immediate next cycle, so the guard
  costs one extra crash over a threshold of 1 while removing the whole class of
  transient false positives. A higher threshold only buys more crashes before the
  loop is caught, for no gain in precision.
- **`ATTRIBUTION_WINDOW` = 60 s.** The window scopes "repeated" so that two deaths
  separated by hours — a scene that rendered fine all afternoon and crashed once
  now, then crashed again much later for an unrelated reason — are not fused into
  a false attribution. Sixty seconds is comfortably longer than the observed
  crash-respawn period (a respawn plus re-feed cycled roughly every ten seconds),
  so a real poison scene reaches the threshold well inside one window, while the
  window is short enough that two genuinely unrelated deaths rarely fall in it.
  The tally of a scene whose second death falls outside the window restarts from
  that death, not from zero-plus-one, so the window slides rather than resets
  abruptly.
- **`STABLE_INTERVAL` ≥ `ATTRIBUTION_WINDOW` (so, 60 s).** The isolation-exit
  interval is deliberately tied to the attribution window, and this tie is what
  makes false-positive-freedom provable rather than merely likely. An innocent
  scene gains a tally only from a *batched* death, and there is at most one
  batched death per batching episode (the first death is what switches the worker
  into isolation). A *second* batched death against the same innocent requires the
  worker to have exited isolation and returned to batching — which happens only
  after `STABLE_INTERVAL` with no death. Because that interval is at least one
  attribution window, the innocent's first batched increment has aged out of the
  window before any second batched increment can land. An innocent therefore never
  holds more than one in-window attributed death, and `ATTRIBUTION_THRESHOLD` is
  two, so an innocent is never quarantined. Setting `STABLE_INTERVAL` shorter than
  the window would break exactly this argument.

**The worst-case crash count, per isolation episode.** Every death is attributed
to its suspect set, so the first batched death already advances every scene it
hit — including each poison scene — by one. Each poison scene then needs
`ATTRIBUTION_THRESHOLD − 1` further *isolated* crashes to reach the threshold and
be quarantined. The worst case for one isolation episode is therefore `1 +
(ATTRIBUTION_THRESHOLD − 1) * |poison|` crashes: the single batched death that
trips isolation, then one further crash per poison scene (at
`ATTRIBUTION_THRESHOLD` = 2). This bound holds **per episode**, for any scene that
crashes at least once per `STABLE_INTERVAL` — including an intermittent scene whose
clean stretches stay shorter than the interval, since isolation persists across
its clean renders and its crashes accumulate to the threshold within the one
episode. That covers the actual B5 defect, a scene that crashes on essentially
every render.

**The deliberately tolerated case: a scene that crashes slower than the
interval.** A scene whose crashes are spaced *further apart* than
`STABLE_INTERVAL` is a different matter, and the design treats it as a **transient,
on purpose**. Such a scene crashes in a batch (tally 1), the worker isolates,
the scene then renders cleanly for a full `STABLE_INTERVAL`, isolation exits and
its tally ages out of the window, and a later crash starts over from tally 1. It
is **never quarantined**, and its crash count is therefore **not** bounded by the
per-episode formula — it crashes about once per `STABLE_INTERVAL`, indefinitely,
each such crash rate-limited by `RespawnBackoff`. This is the correct trade, not a
gap: the `ATTRIBUTION_WINDOW` exists precisely to classify two deaths more than a
window apart as *unrelated*, so a scene that only crashes once every few minutes
is, by the same rule, indistinguishable from a string of independent transient
one-offs. Quarantining it would mean quarantining genuine transients — a scene
that crashed once an hour ago and once now — which is the false positive the
window was built to avoid. The no-infinite-respawn guarantee is thus precisely:
**no respawn loop faster than once per `STABLE_INTERVAL`**; a slower, backoff-paced
trickle from a rare crasher is tolerated by design.

**Why isolation mode is the core of the rule.** Batching alone creates one hard
false-positive: an innocent scene coalesced into the same batch as the poison
scene shares the batched death, so a per-batch tally with no further discipline
would drive the innocent toward the threshold alongside the guilty scene.
Isolation mode narrows the suspect set to one so that *after* the first death the
tally can only accrue against the true culprit — the innocent never becomes a
singleton suspect. That leaves exactly one way an innocent can be hit twice: two
batched deaths in two batching episodes. The `STABLE_INTERVAL` ≥
`ATTRIBUTION_WINDOW` tie closes that last gap, as the constants block above shows,
so the innocent's lone batched increment always ages out before a second can
arrive.

**Alternatives considered and rejected.**

- *Exit codes / a Display supervisor.* Rejected: the Display is detached, so this
  needs a new supervising parent that owns the `Popen` handle and reaps it —
  a larger structural change than the loop requires, and it still would not tell
  the Hub *which scene* rendered at the crash, only that the process died.
- *A "scene S crashed me" message from the Display before it dies.* Rejected: a
  renderer `TypeError` unwinds the frame; there is no reliable point to
  synchronously flush a structured blame message to the Hub before the process
  exits, and a design that depends on the dying process cooperating is not
  robust. (Errors the Display *does* manage to report land in `list_errors` and
  are attached to the quarantine record opportunistically — see Question 2 — but
  attribution does not depend on them arriving.)
- *Time-window-only attribution ("any death within M s of sending S").* Rejected:
  it is exactly the transient false-positive case and it cannot separate
  co-batched scenes.
- *Per-batch tally without isolation.* Rejected: quarantines innocent
  co-batched scenes — batched attribution is safe only because isolation narrows
  every subsequent death to a singleton and the stable-interval exit caps an
  innocent at one in-window batched increment.
- *Attribute only isolation-mode deaths (batched deaths cost nothing).* Rejected:
  a scene that crashes the Display only while coalesced with others — never as an
  isolation singleton — would never accrue a tally, so it would crash, trip
  isolation, render cleanly as a singleton, and loop forever. Every death must be
  attributed to its suspect set for the tally to catch such a scene.
- *Exit isolation on one clean pass, or on a quarantine.* Rejected: both let an
  intermittently poisonous scene escape and both reopen the innocent false
  positive. A one-clean-pass exit returns to batching the moment a flaky scene
  renders cleanly, so its next crash is an unattributed batched death and the loop
  never closes. Exit-on-quarantine returns to batching as soon as one culprit is
  caught, which permits a second batched death — and a second innocent increment —
  inside one attribution window. Only exit on a `STABLE_INTERVAL` ≥
  `ATTRIBUTION_WINDOW` of no deaths at all both waits out a flaky scene and forces
  any innocent's first increment to age out before a second can land.
- *Reset a scene's tally to zero on any clean send.* Rejected: it reopens the
  loop for an *intermittently* poisonous scene. A scene that crashes the renderer
  on only some renders (a data-dependent or nondeterministic defect) would send
  cleanly between crashes, and each clean send would reset its tally, so it would
  never reach the threshold — the Display would crash and respawn forever, exactly
  the loop this design exists to kill. Time-decay of stale suspicion is instead
  provided by the sliding `ATTRIBUTION_WINDOW`: an old, unrelated death ages out
  of the window, while repeated deaths inside the window still accumulate. The
  window discards suspicion by *age*, which is correct; a clean-send reset would
  discard it by a *survival* signal that an intermittent crasher does not honestly
  give.

## Question 2 — quarantine semantics

**Storage.** A quarantined scene stays in `HubDisplay`. The Hub remains
authoritative for it; quarantine is a replication decision, not a deletion. What
changes is that the scene is **excluded from replication**: the replicator skips
it when draining a batch, and — the load-bearing change against the loop —
`SendRecovery` never re-marks it. `recovery.py`'s `_remark` today re-marks
`live_scene_ids()`; it must re-mark `live_scene_ids() \ quarantined` instead. That
single exclusion is what breaks the feed to every respawned Display.

**The quarantine record.** Quarantine is not a bare flag; it carries the evidence
an agent needs to fix its tree. A `QuarantineRecord` value holds the attributed
death count, the timestamp of the most recent attributed death, and — when the
Display managed to report a render error to the Hub before dying — the error text
pulled from the display-side error log. The record is owned by the store's scene
entry, not by a parallel status channel.

**The introspection surface.** Quarantine reuses the existing inspection shapes
rather than inventing a new one. `list_scenes` already reports per-scene owners
and errors; a quarantined scene reports a `status` of `quarantined` (a
`Literal`, not a commented string) and its `QuarantineRecord`. `inspect_scene`
surfaces the same record. No new tool, no parallel status stream — the contract's
"use the existing `list_scenes` owners/errors patterns" is met by extending the
scene entry the query path already reads.

**Reaching the owning agent.** Two paths, both already present:

- *Pull:* the owning agent's next write targeting the quarantined scene (an
  `update`/`show` to that scene id) returns an error result carrying the
  `QuarantineRecord`, so an agent that keeps operating on the scene learns why it
  went dark on its very next call.
- *Push:* an agent subscribed to the scene receives the quarantine as an event on
  the Hub pub-sub channel, so an agent that is not actively writing still finds
  out.

**Un-quarantine — only on an explicit owner action, never automatically.**

- An **update/replace** of the scene by its owner lifts the quarantine: new roots
  are a different tree, presumed fixed, so the scene re-enters replication and its
  tally resets. This is the normal recovery path — the agent reads the record,
  fixes the offending element, re-shows, and the scene renders.
- An explicit **clear** of the scene removes it (and its quarantine) entirely.
- **Nothing lifts a quarantine on its own.** A quarantined scene left untouched
  stays quarantined, because nothing about it changed to make it safe to render.
  An automatic retry would walk straight back into the loop.

**Alternatives considered and rejected.**

- *Delete the poison scene from the store.* Rejected: it destroys the agent's
  work and the evidence, and it breaks the target-architecture invariant that the
  Hub is authoritative for installed UI. Quarantine keeps the scene inspectable
  and recoverable.
- *A separate quarantine/status channel.* Rejected by the contract and by
  simplicity: the scene entry the query path already reads is the right home for
  the record.
- *Automatic un-quarantine after a cool-down.* Rejected: the scene is unchanged,
  so a timed retry re-enters the loop. Only a real change to the tree (an owner
  update) is evidence the poison is gone.

## Question 3 — focus on respawn

**The primary fix is the loop, not the window hint.** The focus storm is a
*symptom* of unbounded respawning: each respawn opens a fresh GLFW window and
macOS activates the new process. Quarantine plus respawn backoff (Question 4)
removes the storm at its source — after at most `ATTRIBUTION_THRESHOLD` deaths the
poison scene stops being replicated, so the Display stops crashing and stops being
respawned. Once the loop is broken, a legitimate respawn happens at most once per
genuine crash, and one focus grab on a real recovery is acceptable — arguably
correct, since the user should see the recovered Display.

**What is achievable if we want to suppress even the single grab.** GLFW exposes
two relevant levers, and they differ in reachability through HelloImGui:

- **`GLFW_FOCUS_ON_SHOW` (0x0002000C)** is a *runtime window attribute*, settable
  with `glfwSetWindowAttrib` after the window exists. The Display already owns a
  ctypes wrapper for exactly this kind of call — `GlfwWindow` in
  `display/glfw_window.py` sets `GLFW_DECORATED` and opacity on the live window by
  address. Extending it with `set_focus_on_show(False)`, called from the Display's
  `post_init` callback, is reachable and low-risk. It governs focus on subsequent
  `glfwShowWindow` calls.
- **`GLFW_FOCUSED` (0x00020001)** is a *creation hint*, which must be set with
  `glfwWindowHint` **before** `glfwCreateWindow`. HelloImGui owns window creation
  inside `immapp.run`, and does not expose a pre-create GLFW-hint hook. So
  suppressing the **initial** creation-time focus grab is **not cleanly reachable**
  without patching HelloImGui or resorting to a fragile post-creation workaround.

**The macOS-specific limit, stated honestly.** On macOS, window focus is tied to
`NSApplication` activation: when a new process creates its first window, the OS
activates that app and moves keyboard focus to it, before any GLFW attribute the
Python code can set takes effect. The lever that genuinely prevents this is the
app's activation policy (`NSApplicationActivationPolicyAccessory` /
`LSUIElement`), which stops the app stealing focus — but it also removes the app
from the Dock and changes how the user reaches the window, which is a UX change
beyond this bug's scope. **Conclusion:** the initial focus grab of a freshly
spawned Display cannot be fully suppressed on macOS through GLFW/HelloImGui alone.
The design does not claim spawn-hidden. It relies on quarantine + backoff to make
that grab happen at most once per genuine crash, and offers the reachable
`GLFW_FOCUS_ON_SHOW` attribute as the knob to suppress focus on *re-show* of an
existing window.

## Question 4 — respawn backoff

**Both mechanisms are needed and they compose.** They bound different quantities:

- **Quarantine bounds the count.** A poison scene can crash the Display at most
  `ATTRIBUTION_THRESHOLD` times before it is quarantined and stops being
  replicated. Without quarantine, respawn backoff alone yields a *slow* infinite
  loop — the Display still crashes and respawns forever, just less often, and it
  still steals focus on every respawn, forever. Backoff alone does not terminate.
- **Backoff bounds the rate.** Between the first death and quarantine, the Display
  is respawned once per attributed death. Without backoff, those respawns are a
  rapid burst of focus-stealing windows in the seconds before quarantine catches.
  Quarantine alone does not pace that burst.

**Design.** A **respawn backoff distinct from the existing send-retry backoff.**
`replicator.py` already has a send-retry micro-backoff (`_BASE_BACKOFF_SECONDS`
0.1 s doubling to `_MAX_BACKOFF_SECONDS` 2 s) that resets on any clean *send*
cycle. That is the wrong reset condition for respawn pacing: a poison scene can
produce a clean send of an *innocent* isolated scene in the same cycle it later
crashes on the poison one, which would reset a shared counter. The respawn backoff
is therefore its own object with its own state:

- It grows on each respawn (1 s → 2 s → 4 s → … up to a cap, e.g. 30 s), spacing
  successive respawns further apart.
- It resets **only** after the Display has *served without a death* for a stable
  interval — not on a clean send, but on demonstrated Display stability. A Display
  that stays up is healthy; a Display that keeps dying keeps its backoff climbing.

Packaging the growth-and-reset policy as a small class (a `RespawnBackoff` value
that owns its current delay and the reset rule) keeps the policy — behaviour — on
the data it governs, per PY-OO-5, rather than as free counters threaded through
the recovery code.

**Alternative considered and rejected.** *Reuse the send-retry backoff for
respawn.* Rejected: its reset-on-clean-send condition fires too eagerly under
isolation mode (an innocent scene sending cleanly would reset the respawn pacing),
and its 2 s cap is too tight to meaningfully space respawns. Respawn pacing needs
its own state and its own reset condition.

## Proposed write set for the implementation mission

The design names the affected objects; the implementation mission decides how to
split them.

- **`domain/hub/recovery.py`** — `SendRecovery._remark` excludes quarantined
  scenes from the re-mark (the load-bearing loop break); `recover` drives the
  respawn through the new `RespawnBackoff` and records the attribution for the
  suspect scene.
- **`domain/hub/replicator.py`** — the two-mode (batching / isolation) send loop
  and the mode transitions; on a send failure it hands the attribution object the
  suspect set (the whole batch in batching mode, the singleton being probed in
  isolation mode) and consults it for the current mode and the isolation-exit
  decision.
- **A new attribution object** (e.g. `domain/hub/crash_attribution.py`) — owns the
  per-scene windowed tally, the threshold, the batching/isolation mode, and the
  `STABLE_INTERVAL` exit decision. It attributes every death to its suspect set,
  quarantines a scene at the threshold, and returns to batching only after a
  death-free `STABLE_INTERVAL` (≥ `ATTRIBUTION_WINDOW`). The attribution rule, the
  three constants, and the mode/exit policy are behaviour on this data, not module
  functions.
- **A new `RespawnBackoff`** (its own module or beside the attribution object) —
  owns the respawn delay growth and the serve-stably reset rule.
- **The scene store** (`domain/hub/hub_display.py` / the scene entry it holds) —
  carries the `quarantined` state and the `QuarantineRecord`; excludes quarantined
  scenes from `live_scene_ids()` for replication; clears quarantine on an owner
  update/clear.
- **A new `QuarantineRecord`** value class (`Literal` status, death count, last
  death time, optional captured render error) — a frozen slotted value on the
  scene entry.
- **`operations/queries.py`** and the `list_scenes` / `inspect_scene` result
  models — surface the `quarantined` status and record through the existing scene
  query path.
- **The write path** (`operations/scenes.py` or the write seam) — return the
  `QuarantineRecord` as an error result when an owner writes to a quarantined
  scene, and publish the quarantine to subscribers.
- **`display/glfw_window.py`** — optional `set_focus_on_show(False)` on the live
  window, called from the Display's `post_init`, as the reachable focus-on-reshow
  knob (with the macOS creation-time limit documented above).

## Formal model

The crash-loop lifecycle is a stateful protocol with a safety-critical
termination property ("a poison scene cannot loop the Display forever"), so it is
model-checked, not merely tested. The Z specification is the companion spec
[`display_crash_loop.tex`](../display_crash_loop.tex): it models
replicate → crash → attribute → quarantine with both send modes, batched
attribution, an *intermittently* poisonous scene (one that renders cleanly on
some isolation probes), and the stable-interval exit. ProB proves three
properties: a quarantined scene is never replicated, the per-episode crash count
is bounded (`crashes ≤ 1 + (ATTRIBUTION_THRESHOLD − 1) · |crasher|`, the
no-infinite-respawn property), and an innocent scene is never quarantined. The
bound holds for an intermittent scene whose clean stretches stay shorter than the
interval — the case the model represents. The model abstracts the timed
`STABLE_INTERVAL` exit by its clock-free consequence (`IsolExit` is enabled once
no non-quarantined crasher remains), which is sound exactly under the
once-per-interval assumption; the deliberately tolerated slower-than-interval
transient — never quarantined, crashing once per interval — is out of the model's
scope by construction, and is a tolerated behaviour, not a loop, so it needs no
clock in the model.

The spec carries two fidelity negative controls, one per corrective clause, each
striking exactly that clause and reproducing the loop it prevents.
[`display_crash_loop_buggy.tex`](../display_crash_loop_buggy.tex) strikes the
quarantine effect: the deterministic render → crash → respawn loop returns,
unbounded. [`display_crash_loop_earlyexit_buggy.tex`](../display_crash_loop_earlyexit_buggy.tex)
weakens the isolation-exit guard so the worker leaves isolation early and wipes
the tally: the *intermittent*-crasher loop returns (`BatchCrash → Respawn →
IsolExit → BatchCrash …`, the tally reset to zero each pass), which is the direct
evidence that the `STABLE_INTERVAL` ≥ `ATTRIBUTION_WINDOW` tie is load-bearing.

The spec is kept as a companion to
[`display_lifecycle.tex`](../display_lifecycle.tex) rather than merged into it, so
the ProB-verified bind-race model stays pristine: the bind-race spec governs *who
owns the socket*, this spec governs *whether a poison scene can loop the Display*.
