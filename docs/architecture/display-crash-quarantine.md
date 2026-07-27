# Display Crash-Loop Quarantine

**Status:** design for the crash-respawn quarantine (bead lux-88ka).

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
- **On the first send failure**, the worker switches to **isolation mode**: it
  stops coalescing and sends each live scene in its **own** send, checking the
  connection is still alive between sends.
- In isolation mode, when a send fails, the **suspect set is a single scene** —
  the one whose send preceded the failure. That scene's tally is incremented.
- A scene that reaches **`ATTRIBUTION_THRESHOLD` (2)** attributed deaths within
  the rolling window **`ATTRIBUTION_WINDOW` (60 s)** is quarantined (Question 2).
- **Any clean send of a scene resets its tally to zero** — a scene that renders
  without killing the Display has proven itself survivable, and stale suspicion
  must not accumulate across unrelated incidents.
- **Isolation-mode exit.** The worker returns to batching mode after **one full
  clean pass**: a single isolation cycle in which every live scene is sent, each
  in its own send, and none causes a Display death. One clean cycle — not one
  clean send — because the point of isolation is to prove that *no* live scene is
  currently poisonous; a single scene sending cleanly says nothing about the
  others still to be probed. A full clean pass is that proof, so the worker can
  resume coalescing. A quarantined scene is not part of the pass (it is not
  replicated at all), so a poison scene that has been quarantined does not keep
  the worker pinned in isolation.

**The two constants and their defaults.** `ATTRIBUTION_THRESHOLD` and
`ATTRIBUTION_WINDOW` are named constants, not inline literals, so the policy is
one place to read and to tune.

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

**Why isolation mode is the core of the rule.** Batching creates the one hard
false-positive: an innocent scene coalesced into the same batch as the poison
scene is in the suspect set every time the batch is sent, so a naive per-batch
tally would quarantine the innocent scene alongside the guilty one. Isolation
mode removes the ambiguity structurally — the poison scene is the *only* scene in
flight when the Display dies, so the tally can only ever accrue against the true
culprit. The innocent co-batched scene sends cleanly in its own isolated cycle
and has its tally reset.

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
  co-batched scenes.

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
  and the mode transitions; on a send failure in isolation mode it identifies the
  singleton suspect and asks the attribution object to tally it.
- **A new attribution object** (e.g. `domain/hub/crash_attribution.py`) — owns the
  per-scene tally, the window, the threshold, and the batching/isolation mode
  decision. The attribution rule and its thresholds are behaviour on this data,
  not module functions.
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
replicate → crash → attribute → quarantine, proves that a quarantined scene is
never replicated and that the number of crashes is bounded (no infinite respawn),
and carries the fidelity negative control — with the quarantine rule removed, the
model reproduces the unbounded crash-respawn trace. It is kept as a companion to
[`display_lifecycle.tex`](../display_lifecycle.tex) rather than merged into it, so
the ProB-verified bind-race model stays pristine: the bind-race spec governs *who
owns the socket*, this spec governs *whether a poison scene can loop the Display*.
