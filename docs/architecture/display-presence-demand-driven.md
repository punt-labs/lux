# Display Linkage: Hold Content, Never Chase the Display

**Status:** implemented. Bead `lux-81t3.1`, epic `lux-81t3`. This document
was the design ratified before implementation (mission `m-2026-09-10-001`);
the shipped code lives in `src/punt_lux/domain/hub/` (`clients.py`,
`replicator.py`, `liveness.py`, `disconnected_retry.py`, `display_linkage.py`)
and the z-spec model is `docs/display_linkage.tex`. Retained as the design
record — see §10 for the write-set this document's implementation followed.

**This revision supersedes an earlier draft of this document wholesale.**
The earlier draft designed the Hub *opening* the display on demand
(`ServiceManager.for_display().start()` from Hub code, a `presence` state
with an `OFF` veto, a `get()`/`acquire()` split). The operator ruled that
direction out entirely, verbatim: *"if I type `lux display stop` the
process is gone. So yes, pushing content will not execute `lux display
start`. And honestly when we are done, the display and hub probably won't
even be on the same machine."* The bead's own original framing — "window
OPENS when content is pushed" — is **overridden** by this ruling. Two
follow-on refinements from the operator (below) further shaped the
corrected fix's retry cadence. This document is the corrected design.
Everything the Hub does now is: **hold content it cannot deliver, keep
trying to reach a display at a bounded and eventually slow cadence, never
touch the display's process lifecycle, and say clearly what it is doing.**

## 1. Problem, Confirmed Against the Code

The bead's corrected symptom (operator-observed 2026-09-01, 0.32.1): closing
the Lux window terminates `luxd-display.service` /
`com.punt-labs.luxd-display`, and content pushed while it's down black-holes
— accepted by the Hub, rendered nowhere, with no visibility into what
happened.

Tracing the code confirms the exact mechanism, and it turns out to be a
**cadence** defect, not a missing capability:

- `ClientRegistry.get()` (`src/punt_lux/domain/hub/clients.py:96-108`)
  constructs the Hub's one `DisplayLink` with `auto_spawn=False` — correct,
  and staying correct under this revision: the Hub dials out to the
  display's socket and never forks or starts anything. When nothing is
  listening, `DisplayLink.connect()` (`display_link.py:174-194`) raises
  `RuntimeError`.
- `HubReplicator._push_cycle` (`replicator.py:275-305`) only special-cases
  `BlockingIOError`/`OSError` around a send — both mean "a display *was*
  connected and the send to it just failed" (wedged or dead peer), and
  `SendRecovery.recover()` handles those by reaping/reconnecting. A
  `RuntimeError` from `.get()` — "no display was ever connected to begin
  with" — is a **different** condition, but today it isn't caught
  specifically at all: it escapes to `_run_cycle`'s broad
  `except Exception`, which calls `self._recovery.restore(batch)` (correctly
  — nothing is lost) and then `self._back_off()`.
- **The defect is `_back_off()`'s cadence, confirmed by reading it, not
  guessed:**

  ```python
  def _back_off(self) -> None:
      """Sleep the current retry delay, then grow it toward the cap."""
      time.sleep(self._backoff)
      self._backoff = min(self._backoff * 2, _MAX_BACKOFF_SECONDS)
  ```

  with `_BASE_BACKOFF_SECONDS = 0.1` and `_MAX_BACKOFF_SECONDS = 2.0`. This
  **does climb correctly** — 0.1s, 0.2s, 0.4s, 0.8s, 1.6s, 2.0s — it is not
  stuck or reset-only. It plateaus at a 2-second cadence and **stays there
  forever**, because nothing ever reaches the clean-cycle branch
  (`_run_cycle`'s `self._backoff = _BASE_BACKOFF_SECONDS` reset) while no
  display is connected. A 2-second cadence is a sensible ceiling for "a
  display that was just connected is being reaped and is expected back
  within a few seconds" (the scenario this backoff was actually written
  for — a wedged/crashed send failure). It is the wrong ceiling for "no
  display has been connected for an indefinite, possibly very long time,"
  which is `RuntimeError`'s actual meaning, and which the code today cannot
  even tell apart from the wedged case because it never catches
  `RuntimeError` on its own branch.
- The result: an idle, no-display Hub spins at a tight 2-second cadence
  indefinitely, logging `"replicator cycle failed; retrying the batch"`
  every cycle as though something is actively broken, with nothing telling
  an operator or agent that content is sitting held, waiting for a display
  that isn't there.
- `DisplayLiveness` (the keepalive worker, `liveness.py`) is unaffected by
  any of this — it already only pings and reconnects
  (`self._clients.get()`), never spawns, and is not part of the bug.

**The corrected fix, confirmed against the operator's rulings below:**
retrying is fine and required — it's how content reconnects once a display
later appears, wherever it is. The fix is the retry's **cadence**: back off
exponentially to a genuinely slow steady state (on the order of a minute or
slower, per the operator, not 2 seconds), hold the content safely the whole
time (already true — nothing is lost today), reconcile it the moment a
display connects (already true, DES-068), and make "content is held, no
display connected" **visible** so nobody is guessing during the slow-retry
window.

## 2. Operator Ruling — What This Design Does and Does Not Do

Stated explicitly because it reverses the original bead framing and the
earlier draft of this document:

1. **The Hub never starts, spawns, stops, or otherwise controls the
   display's process lifecycle. Not deferred — removed as a design
   direction entirely.** No code path in `domain/hub/` may call
   `ServiceManager.for_display().start()`/`.stop()`/`.restart()`, under any
   circumstance, including as a "helpful" fallback after repeated failures.
2. **`lux display stop` means the process is gone, and pushing content does
   not bring it back.** This is already true today and this design does not
   change it — it is stated here because the earlier draft's `ensure`
   mechanism would have violated it.
3. **The display is entirely user/service-controlled.** A human runs
   `lux display start`/`stop`, or the OS service supervisor
   (launchd/systemd) starts it at login or restarts it after a crash, per
   its own configured policy (§7). The Hub is a client of that socket, never
   an operator of that process.
4. **Design for the Hub and display on different machines.** The
   Hub-to-display leg is a same-host `AF_UNIX` socket today, but DES-090
   describes it becoming a network transport. Any design where the Hub
   reaches out to start the display is architecturally wrong on its face
   once the two are not guaranteed to be co-located — you cannot `start()`
   a service on a machine you have no privileged access to. This design
   assumes nothing about co-location anywhere (§8).
5. **A retry is not a black hole, and retrying is not the thing being
   fixed.** Two clarifying rulings arrived after the operator's initial
   scrap of the ensure-based design, both folded in below:
   - *"The hub can retry and that is fine, but it needs some type of
     exponential backoff to a slow retry state."* Retrying is correct
     behavior, not the defect; the defect is that today's retry never
     slows down past 2 seconds (§1, §6).
   - *"It should increase to something like once a minute or once every
     five minutes. It's not critical what it is."* The exact number is the
     operator's explicit non-concern; §6 picks one value in that band and
     names it as a tunable, not a load-bearing constant.

What survives from the earlier draft, unchanged in substance: the precise
root-cause trace (§1, now corrected in its conclusion), the DES-088
orthogonality argument (§5), and the multi-host introspection surface —
which this revision makes **more** central, since "which Hub is holding
this content, and is a display even watching it" is now the primary
observability question, not a secondary caveat.

**A second review pass (gvr, evaluating commit `6731b1c5`) found the
operator-ruling front sound — grep-confirmed, no Hub process-control of the
display — but flagged real, code-verified mechanism gaps in how the
corrected fix was sketched: a blocking `time.sleep` that would itself defeat
prompt rediscovery, an outcome type that let two backoffs fire on one cycle,
a keepalive worker not held to the same discipline as the replicator, a
missing read accessor, and an `Optional` field that should have been a
discriminated pair. §6, §9, §10, and §12 below are revised again to close
those gaps; §1 through §5, §7, §8, and §11's first two entries are
otherwise unchanged from that pass.**

## 3. The Corrected Model: Hold, Reconcile, Never Control

`HubDisplay` is already the authoritative store for scene content
(`hub_display.py`'s own docstring: "Every write runs under `StoreLock`");
nothing about that changes. The correction is entirely about how the
**replicator** — the one worker that tries to deliver that content to a
display — behaves when there is no display to deliver to:

- **Content is never lost.** A scene that becomes dirty while no display is
  connected stays live in `HubDisplay` and stays marked dirty on the
  `DirtySignal`. This is already true today (`SendRecovery.restore`
  re-queues the batch) and this design does not change the storage side at
  all — only the retry cadence and the visibility of the waiting state.
- **A (re)connect reconciles everything held, exactly once.** This
  mechanism already exists and is unchanged: `ClientRegistry._connect_and_reconcile`
  (DES-068) declares the fresh connection's manifest and marks every
  currently-live scene (and the menu) dirty the moment `.get()` succeeds
  after having been disconnected. The replicator's very next cycle sends
  everything held. No new reconciliation code is needed — the existing
  connect-success hook already IS the "hold, then repaint on reconnect"
  mechanism; the only thing missing was giving the *disconnected* interval
  a sane cadence and a name.
- **The Hub never touches the display's process.** Confirmed by this
  design's write-set (§9): grep for `ServiceManager` inside `domain/hub/`
  after implementation must return zero hits tied to the display spec.

## 4. `DisplayLinkage` — an Observed Classification, Not a Controlled State

Four classifications, purely derived from two facts the Hub already has —
no new stored state, because there is nothing for the Hub to decide here,
only something to observe:

```python
from __future__ import annotations

from enum import Enum, auto
from typing import Self


class DisplayLinkage(Enum):
    """How the Hub currently sees its one display connection.

    Purely observational: the Hub never causes a transition between these
    states, it only reports which one currently holds. The display's
    process lifecycle belongs entirely to the user and the service
    supervisor (§7) — never to this enum or anything that computes it.
    """

    DISCONNECTED = auto()  # no display connected; nothing held either
    HELD = auto()  # no display connected; content is waiting
    CONNECTED_IDLE = auto()  # display connected; nothing live to show
    CONNECTED_ACTIVE = auto()  # display connected; live content is rendering

    @classmethod
    def classify(cls, *, connected: bool, live_scene_count: int) -> Self:
        """Classify from two observed facts — no stored transition state."""
        if not connected:
            return cls.HELD if live_scene_count > 0 else cls.DISCONNECTED
        return cls.CONNECTED_ACTIVE if live_scene_count > 0 else cls.CONNECTED_IDLE
```

| State | Meaning |
|---|---|
| `DISCONNECTED` | No display connected; the Hub holds nothing either — a quiet, healthy idle Hub. |
| `HELD` | No display connected; the Hub holds live content it cannot currently deliver. This is the state this design makes visible (§9) and paces sanely (§6). |
| `CONNECTED_IDLE` | Display connected; zero live scenes. Still a valid resting state — the window is present and usable (menus, applets) with nothing to show. |
| `CONNECTED_ACTIVE` | Display connected; live content is rendering. |

### Transitions and triggers — every one external to the Hub's own action

| From | Trigger | To |
|---|---|---|
| `DISCONNECTED` | an agent pushes content | `HELD` |
| `HELD` | the held content is withdrawn (disposed) before any display connects | `DISCONNECTED` |
| `DISCONNECTED`/`HELD` | a display connects — a human ran `lux display start`, the OS service supervisor started it at login, or the supervisor auto-restarted it after a crash | `CONNECTED_IDLE` (nothing was held) or `CONNECTED_ACTIVE` (held content is reconciled, DES-068) |
| `CONNECTED_ACTIVE` | last live scene disposed while still connected | `CONNECTED_IDLE` |
| `CONNECTED_IDLE` | new content pushed while connected | `CONNECTED_ACTIVE` |
| `CONNECTED_*` | the display disconnects — `lux display stop`, the user closing the window, or a crash the supervisor hasn't yet restarted | `DISCONNECTED` or `HELD`, depending on whether content is still live |

Every trigger in that table is something a user, a supervisor, or an agent
pushing/disposing content does. None is a Hub action. This is the literal
shape of "the Hub never controls the display" — there is no cell in this
table where the Hub causes the *left* column to change; it only computes
which cell it's in.

## 5. `DisplayLinkage` vs. DES-088's Content/Visibility Axes

DES-088 settled a narrower, one-layer-down question: for one already-open
display, does a *frame's* content (client-owned: `show`/`update`/dispose)
or its *visibility* (user-owned: close/collapse/dock/raise) get written by
a given event? Its rule — a content event never writes visibility, a
visibility event never writes content — governs frames **inside** a
running display process.

`DisplayLinkage` is one layer up: it governs whether the **display process
itself** is there to hold any frames at all. DES-088 has nothing to say
about a display that isn't running. The two compose cleanly and do not
overlap:

- `DisplayLinkage` answers: "is there a display process, and does the Hub
  hold anything for it?"
- DES-088 answers, once `DisplayLinkage` is `CONNECTED_*`: "of the frames it
  holds, which are on-screen?"

A user closing the **last** ImGui frame inside a running display (a
DES-088 visibility event) does not touch `DisplayLinkage` at all — the
process is still running, so linkage stays `CONNECTED_*` regardless of
whether the closed frame's scenes are still live (DES-088 keeps a closed
frame's scenes; `live_scene_count` is unaffected by mere frame closure).
`DisplayLinkage` only reacts to the **process** disappearing or
appearing — a coarser, different gesture than DES-088's per-frame close
button. This design adds nothing to, and does not reinterpret, any DES-088
mechanism.

## 6. The Fix: A Slow, Bounded, Interruptible Retry

**Load-bearing correction from review.** The first pass of this section
paced the not-connected retry with a raw `time.sleep(delay)` inside the
replicator's own worker thread. That is wrong on its own terms: it commits
the Hub's *only* sender thread to sleeping out the full current delay —
up to 120s once backed off — before it so much as attempts another
connect, which makes invariant 6 (§12, "a connect promptly breaks out of
the slow-retry state") false as written. A user who runs `lux display
start` right after the Hub has climbed deep into its backoff would see
held content stay blank for up to two minutes. Retrying slowly and
rediscovering promptly are both required (§2 item 5); a blocking sleep
cannot deliver both at once. §6.3 below replaces it with an interruptible
wait. A second defect in the same area — a boolean outcome type that let
the wedged-display backoff *also* fire on a not-connected cycle — is fixed
in §6.1 by making the outcome a genuine three-way discrimination instead
of asking a `bool` to carry three meanings.

### 6.1 Three outcomes, not one boolean

`_CycleOutcome.recovered: bool` was asked to distinguish three different
things: a clean send, a connected-but-misbehaving send that `SendRecovery`
healed, and no display connected at all. The `RuntimeError` branch
returned `recovered=True` — the only value available — which is
indistinguishable, to `_run_cycle`, from "a wedged display was just
healed." `_run_cycle` then called `self._back_off()` (the *wedged-display*
backoff) **in addition to** the disconnected wait that had already run
inside `_push_cycle` — every not-connected cycle was paying two
uncoordinated sleeps, not one.

The fix is a `Literal` tag, not a bespoke class per branch — this is an
internal control-flow result with no behavior attached to the tag beyond
which branch `_run_cycle` takes, the same shape `DrainedBatch` already uses
for its own `shutting`/`has_work` discrimination:

```python
@final
@dataclass(frozen=True, slots=True)
class _CycleOutcome:
    """The result of one push cycle — exactly one of three distinct causes.

    ``clean``: a real send succeeded; ``emptied`` names scenes to reclaim.
    ``recovered``: a send failed while CONNECTED (wedged or dead peer) and
    ``SendRecovery`` healed it — the wedged-display backoff advances.
    ``disconnected``: no display was connected at all — nothing to reap or
    heal; the disconnected-backoff advances instead. These two backoffs
    are mutually exclusive by construction: a cycle can match only one
    `except` branch in `_push_cycle`, so there is no path where both are
    touched in the same cycle.
    """

    outcome: Literal["clean", "recovered", "disconnected"]
    emptied: tuple[SceneId, ...] = ()
```

```python
def _run_cycle(self, batch: DrainedBatch) -> None:
    try:
        result = self._push_cycle(batch)
    except Exception:
        if batch.shutting:
            logger.exception("replicator shutdown flush failed; dropping the batch")
            return
        logger.exception("replicator cycle failed; retrying the batch")
        self._recovery.restore(batch)
        self._back_off()
        return
    if result.outcome == "disconnected":
        return  # _push_cycle already restored the batch and waited (§6.3)
    if result.outcome == "recovered":
        if not batch.shutting:
            self._back_off()
        return
    self._backoff = _BASE_BACKOFF_SECONDS
    self._reclaim_emptied(result.emptied)
```

The `disconnected` branch does nothing further — no reclaim, no
`_back_off()` — which is what makes "never advances the wedged backoff on
a disconnected cycle" true by construction rather than by convention:
there is no code path left that could call `self._back_off()` for a
`disconnected` outcome.

### 6.2 Two independently-tuned backoff curves

The codebase already has two backoff mechanisms; this design adds a third
by reusing one of them rather than inventing a new mechanism:

| Backoff | Lives in | Paces | Range today |
|---|---|---|---|
| `HubReplicator._backoff` | `replicator.py` | The wedged/dead-peer `recovered` outcome | `_BASE_BACKOFF_SECONDS=0.1` → `_MAX_BACKOFF_SECONDS=2.0` |
| `RespawnBackoff` | `respawn_backoff.py`, used by `SendRecovery` | Pacing successive `reap()` calls on a display that keeps crashing after reconnect (display-crash-quarantine.md) | `_BASE_DELAY_SECONDS=1.0` → `_MAX_DELAY_SECONDS=30.0`, resets after a stable interval |

Both are correctly scoped to *connected-but-misbehaving* scenarios, where a
few-second cadence is right because the supervisor's own crash-restart
(§7) is expected to resolve things within seconds. Neither is the right
shape for the `disconnected` outcome, which can legitimately last
indefinitely (a display that's off, or on a machine the user hasn't turned
on yet, per §2 item 4). Reuse `RespawnBackoff`'s shape (`note_respawn()` /
`reset_if_stable()` already do exactly the right thing — grow on each
retry, reset once stable) by parameterizing its two constants instead of
hardcoding a third copy of the same twelve lines, and adding the one
non-mutating accessor introspection needs (§9) that the class did not
previously expose:

```python
# respawn_backoff.py — only the constructor and one new property change;
# existing callers (crash-respawn pacing) are unaffected by the defaults.
def __new__(
    cls,
    clock: Callable[[], float] = time.monotonic,
    base_delay: float = _BASE_DELAY_SECONDS,
    max_delay: float = _MAX_DELAY_SECONDS,
) -> Self:
    self = super().__new__(cls)
    self._clock = clock
    self._delay = base_delay
    self._max_delay = max_delay
    self._last_respawn_at = None
    return self


@property
def current_delay(self) -> float:
    """Return the delay `note_respawn` would apply next — read-only, no mutation."""
    return self._delay
```

`HubReplicator` composes a second instance for the `disconnected` case:

```python
self._disconnected_backoff = RespawnBackoff(base_delay=2.0, max_delay=120.0)
```

Curve: 2s, 4s, 8s, 16s, 32s, 64s, capped at 120s — squarely inside the
operator's stated "once a minute to once every five minutes" band. The
exact numbers are an explicit tunable, not load-bearing: the operator's own
words are "it's not critical what it is." What is load-bearing is the
*shape* — genuinely exponential, genuinely capped one to two orders of
magnitude above the existing 2-second wedged-display ceiling — combined
with the interruptible wait in §6.3, which is what keeps that slow cap from
also making rediscovery slow.

### 6.3 Never a blocking sleep: an interruptible wait, coordinated with `DisplayLiveness`

The mechanism that actually satisfies both "slow steady state" and "prompt
rediscovery" at once: the disconnected wait blocks on a `threading.Event`
that ANY successful `ClientRegistry.get()` — from the replicator's own next
retry, or from `DisplayLiveness`'s independent probe (§6.4) — sets. The
event lives on `ClientRegistry`, the one existing choke point both threads
already call through, not as a second object the replicator has to import
and wire separately:

```python
# clients.py — ClientRegistry gains one field and two methods
_reconnected: threading.Event  # set on a fresh connect; consumed by wait_for_reconnect


def get(self) -> DisplayLink:
    with self._lock:
        was_connected = self._client is not None and self._client.is_connected
        if self._client is None:
            self._client = DisplayLink(
                name=_DISPLAY_CLIENT_NAME, kind="hub", auto_spawn=False
            )
        self._setup_apps()
        if not self._client.is_connected:
            self._connect_and_reconcile(
                self._client
            )  # raises RuntimeError if unreachable
        if not self._client.listener_active:
            self._client.start_listener()
        if not was_connected:
            self._reconnected.set()  # wakes anyone in wait_for_reconnect, immediately
        return self._client


def wait_for_reconnect(self, timeout: float) -> bool:
    """Block up to `timeout`s for a fresh connect from EITHER thread.

    Deliberately does NOT hold `self._lock` while waiting — `Event.wait`
    is thread-safe on its own, and holding the registry lock here for up
    to `timeout` seconds would block every other caller (`DisplayLiveness`,
    an MCP tool's `.get()` for an unrelated query) for the same window,
    which is exactly the kind of Hub-wide stall this design exists to
    prevent. Returns whether it woke early (`True`) or timed out (`False`).
    """
    woke = self._reconnected.wait(timeout)
    self._reconnected.clear()
    return woke
```

`HubReplicator`'s `disconnected` branch replaces the raw sleep with this:

```python
def _push_cycle(self, batch: DrainedBatch) -> _CycleOutcome:
    try:
        emptied = self._attempt(batch)
    except RuntimeError:
        self._recovery.restore(batch)
        self._wait_disconnected()
        return _CycleOutcome(outcome="disconnected")
    except BlockingIOError as exc:
        ...  # unchanged — wedged-display recovery, SendRecovery / RespawnBackoff(1.0, 30.0)
    except OSError as exc:
        ...  # unchanged — dead-peer reconnect
    return _CycleOutcome(outcome="clean", emptied=emptied)


def _wait_disconnected(self) -> None:
    """Wait for the current disconnected delay, breakable by a reconnect."""
    delay = self._disconnected_backoff.note_respawn()
    self._log_disconnected(delay)
    self._clients.wait_for_reconnect(delay)
```

`ClientProvider` (`replicator_ports.py`) gains `wait_for_reconnect` in its
structural contract alongside `get`/`drop`; `KeepaliveClients` does not —
only the replicator waits, `DisplayLiveness` only ever sets the event as a
side effect of its own successful `get()`.

**Why this satisfies invariant 6 concretely, not just by naming it:** the
replicator's wait is bounded by `min(disconnected_delay, time until
DisplayLiveness's next successful probe)`, and `DisplayLiveness`'s probe
runs on its own, much shorter cadence (§6.4) regardless of how deep the
replicator's own backoff has climbed. A user starting the display is
discovered by the *cheap, frequent* prober, not the *slow, patient* sender
— the two are coordinated through one shared signal instead of one thread
trying to be both fast and slow at once.

On a clean cycle, `_run_cycle` resets `_disconnected_backoff` to a fresh
`RespawnBackoff(base_delay=2.0, max_delay=120.0)` immediately — no
stability window needed here, unlike the crash-quarantine `RespawnBackoff`,
because "reconnected and sent successfully" is unambiguous in a way
"hasn't crashed again yet" is not.

### 6.4 `DisplayLiveness` is not exempt — quiet, and paced on purpose

**Correction from review — do not claim this worker is "not part of the
bug."** `DisplayLiveness.check_once()` pings on a fixed
`CONNECTION_TIMING.keepalive_interval` (today, a couple of seconds)
forever, with zero backoff, and its `_probe()` logs a `WARNING` on every
single failed probe. While the display is legitimately, correctly
disconnected, that is a Hub background worker hammering the same socket at
a fixed short interval indefinitely and warning about it every time —
exactly the pattern the operator's ruling targets, whether or not it ever
tries to *spawn* anything. It needs the same discipline as the replicator,
not an exemption, and it doubles as the mechanism §6.3 depends on for
prompt rediscovery, so the fix is "quiet and explicitly paced," not "leave
it alone" and not "slow it down to the replicator's own multi-minute cap"
either — that would defeat the very rediscovery §6.3 relies on it for.

```python
_DISCONNECTED_PROBE_INTERVAL = 5.0  # a few seconds slower than the connected
# ping cadence — visibly relaxed, still
# well inside "prompt" for invariant 6


class DisplayLiveness:
    ...
    _disconnected: bool  # tracks whether the last cycle found a live peer
    __slots__ = (..., "_disconnected")

    def _run(self) -> None:
        interval = self._interval
        while not self._stop.wait(interval):
            try:
                self.check_once()
            except Exception:
                logger.exception("liveness cycle failed; continuing")
            interval = (
                self._interval
                if not self._disconnected
                else _DISCONNECTED_PROBE_INTERVAL
            )

    def check_once(self) -> None:
        if self._probe() or self._probe():
            self._disconnected = False
            return
        if not self._disconnected:
            logger.info(
                "display not connected; probing every %.0fs until it returns",
                _DISCONNECTED_PROBE_INTERVAL,
            )
        self._disconnected = True
        self._clients.drop()
        self._probe()

    def _probe(self) -> bool:
        try:
            return self._clients.get().ping(self._ping_timeout) is not None
        except (OSError, RuntimeError):
            return False  # no per-failure log — check_once logs the transition once
```

Two cadences, both explicit and justified, not one unexamined fixed
interval doing double duty: the normal `_interval` while connected (needed
for interaction responsiveness — unchanged), and the slower, named
`_DISCONNECTED_PROBE_INTERVAL` while not — long enough to visibly relax
relative to the connected cadence, short enough that a display starting up
is discovered within a handful of seconds, satisfying §6.3's "cheap,
frequent prober" role without itself becoming the thing that hammers the
socket forever. A successful `get()` here — whether from this probe or the
replicator's own next retry — is what sets `ClientRegistry._reconnected`
(§6.3); no additional code is needed in `liveness.py` for the wake itself,
it is inherited from the one choke point both threads already share.

### 6.5 Logging: state the condition, don't cry wolf

Today's `logger.exception("replicator cycle failed; retrying the batch")`
fires every cycle, indistinguishable from a genuine failure, training an
operator to ignore it. The corrected behavior, in both the replicator and
`DisplayLiveness`: log once, at `INFO`, on the transition *into* the
not-connected state, and at `DEBUG` (or not at all) on every subsequent
already-waiting cycle — the state is expected and already visible through
introspection (§9), so the log's job is a breadcrumb for someone reading
logs, not a recurring alarm.

## 7. Honoring a User Stop or Close — Scoped to the Display's Own Service Spec

Two distinct user gestures both need to *stay down* until the user or
service infrastructure — never the Hub — brings the display back:

1. **`lux display stop`** — already correct today. `LaunchdBackend.stop()`
   deliberately uses `bootout`, not `unload`, specifically because bare
   `KeepAlive=true` would otherwise have launchd respawn the job on the
   `SIGTERM` `stop` sends; `bootout` deregisters the job from the domain
   entirely, so there is nothing left to respawn it
   (`_backend_launchd.py:132-145`'s own docstring states this). No change
   needed.
2. **The user closing the OS window**, without going through `lux display
   stop` — the job stays *loaded* (bootstrapped), and only the process
   exits. Whether that exit is auto-resurrected depends entirely on the
   supervisor's restart policy, and the two platforms disagree today:
   - Linux: `_backend_systemd.py:157` sets `Restart=on-failure` — a clean
     exit (`rc=0`) is **not** auto-restarted. Already correct.
   - macOS: `_backend_launchd.py:199-200` sets bare `<key>KeepAlive</key><true/>`.
     launchd's documented semantics for the bare-boolean form restart the
     job on **any** exit, including a clean one — closing the window would
     be immediately resurrected by launchd itself, one layer below
     anything the Hub does. This is the one asymmetry this design fixes.

**Fix, scoped to `DISPLAY_SPEC` only — `HUB_SPEC`'s restart semantics do not
change** (a distinct finding from review: the Hub has no user-facing
"window" gesture to honor, and its own bare-`KeepAlive`/always-restart
posture is correct and untouched). `ServiceSpec` gains one field:

```python
@dataclass(frozen=True, slots=True)
class ServiceSpec:
    ...
    restart_on_crash_only: bool = False  # False preserves today's behavior for HUB_SPEC
```

`DISPLAY_SPEC` sets `restart_on_crash_only=True`; `HUB_SPEC` is left at the
default, unchanged. `LaunchdBackend._plist_content()` branches on the
field:

```xml
<!-- restart_on_crash_only=True (DISPLAY_SPEC): -->
<key>KeepAlive</key>
<dict>
    <key>SuccessfulExit</key>
    <false/>
</dict>

<!-- restart_on_crash_only=False (HUB_SPEC, unchanged): -->
<key>KeepAlive</key>
<true/>
```

`_backend_systemd.py` needs no change — `Restart=on-failure` already
applies identically to both specs today and is already correct for both;
only launchd has the asymmetry. This must be verified against real launchd
behavior during implementation (the exact interaction between
`SuccessfulExit=false` and a signal-terminated exit versus a `sys.exit(0)`
call is a platform detail this design states with the correct intent but
has not executed and confirmed).

**Footnote — a pre-existing, out-of-scope asymmetry.** `HUB_SPEC`'s own
restart posture already differs by platform today: macOS's bare
`KeepAlive=true` restarts the Hub on any exit, Linux's `Restart=on-failure`
restarts it only on a crash. This design does not touch `HUB_SPEC` (§2
item 1's rationale, restated above), so it neither introduces nor corrects
that asymmetry — noted here so it isn't mistaken for something this design
was silent about by oversight rather than by scope.

## 8. Cross-Host Forward Compatibility

Nothing in this design assumes the Hub and the display share a machine.
The Hub-to-display leg is a same-host `AF_UNIX` socket today
(`DisplayPaths._default_path()` resolves `$XDG_RUNTIME_DIR`/`/tmp/lux-$USER`),
and DES-090 describes it becoming a network transport for the cross-host
case. Every mechanism this design relies on survives that transition
unchanged, because none of them assume co-location:

- **Dialing out** (`ClientRegistry.get()`'s `.connect()` call) is a plain
  client-of-a-socket operation whether the socket is a Unix path or a
  network address — swapping the transport changes the address, not the
  shape of "try to connect; if refused, that's `DISCONNECTED`/`HELD`; if it
  succeeds, reconcile."
- **The retry cadence** (§6) has no notion of "the same machine, so it
  should be back soon" baked into it — a minute-to-five-minutes cadence is
  exactly as sensible whether the display is down the hall or on a laptop
  that's currently closed on the other side of a network.
- **The Hub never issuing a process-control call** (§2 item 1) is the
  precondition that makes cross-host safe at all — a design that called
  `ServiceManager.for_display().start()` cannot survive the display moving
  to a machine the Hub has no privileged access to, which is exactly why
  that direction was ruled out.

The one thing this design does NOT attempt is cross-host aggregation itself
(many Hubs, one display, or vice versa) — that is DES-089/090's own,
separate, unimplemented scope. This design's job is narrower and
prerequisite: make sure nothing here has to be rewritten when that scope
lands.

## 9. Multi-Host / Host-Identity Introspection — Now Central

The bead's own evidence — "pembroke Hub vs. keble display" — is not a
wire-protocol multi-Hub-aggregation problem; each host runs its own
independent Hub+display pair today (the socket is same-host only), so the
actual failure was an operator (or an agent on their behalf) pushing to the
wrong host's Hub — one nobody is looking at. Now that `HELD` is an expected,
possibly long-lived state rather than an error, telling *which* Hub is
holding content, on *which* host, is the primary way an agent or operator
notices "I pushed here, but nothing will ever render, because nobody is
watching this Hub" — more central than in the earlier draft, not a
secondary caveat.

New, pure Hub-side (no display round-trip needed — that's the point)
operation and wire model, mirroring `DisplayModeOperations`'s existing
"reads local/Hub state only" shape.

**Correction from review:** the first pass gave this model a
`retry_delay_seconds: float | None`, `None` exactly when connected — a
discriminated state (connected vs. disconnected) smuggled through an
`Optional`, the pattern the lux OO standard's Five Rules #5 exists to
catch (and the same shape `OpError`/`DisplayModeState` already avoid via a
`kind: Literal[...]` discriminant elsewhere in this codebase). Split into
two variants instead: `retry_delay_seconds` is a plain, required `float`
on the variant where it means something, and does not exist at all on the
other — and `linkage` is narrowed per variant too, so
`ConnectedLinkState` cannot claim to be `"held"` and `DisconnectedLinkState`
cannot claim to be `"connected_active"`, which the flat four-way `Literal`
never prevented.

```python
# operations/models/display_link.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["ConnectedLinkState", "DisconnectedLinkState", "DisplayLinkState"]


class ConnectedLinkState(BaseModel):
    """The Hub currently has a live display connection."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["connected"] = "connected"
    linkage: Literal["connected_idle", "connected_active"]
    live_scene_count: int
    hub_host: str  # socket.gethostname() — which machine this Hub is on
    hub_pid: int  # os.getpid() — which Hub process, for a same-host duplicate


class DisconnectedLinkState(BaseModel):
    """The Hub has no display connection right now; content may be held."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["disconnected"] = "disconnected"
    linkage: Literal["disconnected", "held"]
    live_scene_count: int
    retry_delay_seconds: float  # required here — this variant IS the "waiting" state
    hub_host: str
    hub_pid: int


DisplayLinkState = ConnectedLinkState | DisconnectedLinkState
```

```python
# operations/display_link.py
from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_linkage import DisplayLinkage
from punt_lux.operations.models.display_link import (
    ConnectedLinkState,
    DisconnectedLinkState,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.clients import ClientRegistry
    from punt_lux.domain.hub.replicator import HubReplicator
    from punt_lux.domain.ids import SceneId

__all__ = ["DisplayLinkOperations"]


@final
class DisplayLinkOperations:
    """Report the Hub-to-display link and any content held on it — no proxying."""

    _clients: ClientRegistry
    _live_scene_ids: Callable[[], frozenset[SceneId]]
    _replicator: HubReplicator
    __slots__ = ("_clients", "_live_scene_ids", "_replicator")

    def __new__(
        cls,
        clients: ClientRegistry,
        live_scene_ids: Callable[[], frozenset[SceneId]],
        replicator: HubReplicator,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._live_scene_ids = live_scene_ids
        self._replicator = replicator
        return self

    def get_link(self) -> ConnectedLinkState | DisconnectedLinkState:
        """Return the current linkage classification and host identity."""
        count = len(self._live_scene_ids())
        connected = self._clients.is_connected
        host, pid = socket.gethostname(), os.getpid()
        state = DisplayLinkage.classify(connected=connected, live_scene_count=count)
        match state:
            case DisplayLinkage.DISCONNECTED | DisplayLinkage.HELD:
                return DisconnectedLinkState(
                    linkage="held" if state is DisplayLinkage.HELD else "disconnected",
                    live_scene_count=count,
                    retry_delay_seconds=self._replicator.disconnected_delay,
                    hub_host=host,
                    hub_pid=pid,
                )
            case DisplayLinkage.CONNECTED_IDLE | DisplayLinkage.CONNECTED_ACTIVE:
                return ConnectedLinkState(
                    linkage=(
                        "connected_active"
                        if state is DisplayLinkage.CONNECTED_ACTIVE
                        else "connected_idle"
                    ),
                    live_scene_count=count,
                    hub_host=host,
                    hub_pid=pid,
                )
```

`ClientRegistry` gains a cheap read-only `is_connected` property
(`self._client is not None and self._client.is_connected` — no lock, no
I/O) so this operation never has to attempt a connect just to answer a
read. `HubReplicator` gains a small `disconnected_delay` property exposing
`self._disconnected_backoff.current_delay` (§6.2's new accessor) for the
same reason — introspection should show the operator not just "held" but
"and the Hub will try again in about N seconds," so a person watching
doesn't have to guess whether it's about to retry or settled into the
slow steady-state.

Surfaced via a new read-only MCP tool `display_link_get` (no arguments,
alongside the existing `display_mode_get`/`display_state_get` reads) and a
CLI verb, `lux display link`. Both work with no display connected at all —
verified explicitly in the write-set's test plan (§10 item 11), since a
surface that only answers while connected would be useless for exactly the
state it exists to report.

## 10. Concrete Implementation Write-Set

For the follow-on implementation mission. Every item is grounded in a
specific file this design read.

1. **New** `src/punt_lux/domain/hub/display_linkage.py` — `DisplayLinkage`
   enum with `classify()` (§4). Pure, no I/O, trivially unit-testable.
2. **Modify** `src/punt_lux/domain/hub/respawn_backoff.py` —
   parameterize `RespawnBackoff.__new__` with `base_delay`/`max_delay`
   (defaulting to today's `_BASE_DELAY_SECONDS`/`_MAX_DELAY_SECONDS`, so the
   existing crash-respawn caller is unaffected); add the read-only
   `current_delay` property (§6.2).
3. **Modify** `src/punt_lux/domain/hub/clients.py` (`ClientRegistry`) —
   - Add the `_reconnected: threading.Event` field, set inside `get()` on a
     fresh connect (`if not was_connected: self._reconnected.set()`) (§6.3).
   - Add `wait_for_reconnect(timeout: float) -> bool`, deliberately not
     holding `self._lock` while waiting (§6.3).
   - Add the cheap read-only `is_connected` property (§9).
   - `get()`'s own connect/reconnect shape is otherwise unchanged — no
     ensure, no split; the earlier draft's `acquire()`/veto machinery is
     fully removed, not merely unused.
4. **Modify** `src/punt_lux/domain/hub/replicator_ports.py` — add
   `wait_for_reconnect` to the `ClientProvider` Protocol (not
   `KeepaliveClients`) (§6.3).
5. **Modify** `src/punt_lux/domain/hub/replicator.py` — this is the item
   the earlier write-set understated; it now covers `_run_cycle` and
   `_CycleOutcome` explicitly, not just `_push_cycle`:
   - Replace `_CycleOutcome.recovered: bool` with
     `outcome: Literal["clean", "recovered", "disconnected"]` (§6.1).
   - `_run_cycle` gains the explicit `disconnected` branch that neither
     reclaims via `_reclaim_emptied` nor calls `_back_off()` (§6.1) — the
     structural fix for the double-sleep defect review found.
   - The second backoff is extracted into its own collaborator,
     `DisconnectedRetry` (new `src/punt_lux/domain/hub/disconnected_retry.py`,
     wrapping `RespawnBackoff` plus the wait and its once-per-transition log),
     held as `self._disconnected_retry: DisconnectedRetry`.
   - `_push_cycle` catches `DisplayNotConnectedError` (not a generic
     `RuntimeError`) on its own branch and calls
     `self._disconnected_retry.wait(self._clients, since_gen=...)` (§6.3)
     instead of a raw `time.sleep`.
   - Logging: `INFO` on transition into the not-connected state, `DEBUG` on
     repeats (§6.5).
   - New `disconnected_delay` read-only property (returns
     `self._disconnected_backoff.current_delay`) for §9's introspection.
6. **Modify** `src/punt_lux/domain/hub/liveness.py` (`DisplayLiveness`) —
   the coordinated cadence and quiet logging in §6.4: the new
   `_DISCONNECTED_PROBE_INTERVAL` constant, the `_disconnected: bool` field,
   `_run`'s adaptive interval, and `_probe`'s per-failure `WARNING` removed
   in favor of `check_once`'s one transition-only `INFO` log.
7. **New** `operations/models/display_link.py` (`ConnectedLinkState`,
   `DisconnectedLinkState`) and `operations/display_link.py`
   (`DisplayLinkOperations`), composed into `operations/facade.py`
   alongside the existing concern classes (§9).
8. **New** MCP tool `display_link_get` (read-only, no arguments) and CLI
   verb `lux display link`, mirroring the existing `display_mode_get`/
   `lux display mode` read shape.
9. **Modify** `src/punt_lux/_service_spec.py` — add
   `restart_on_crash_only: bool = False` to `ServiceSpec`; set
   `restart_on_crash_only=True` on `DISPLAY_SPEC` only (§7). `HUB_SPEC` is
   not touched.
10. **Modify** `src/punt_lux/_backend_launchd.py` — `_plist_content()`
    branches on `spec.restart_on_crash_only` to emit the dict form
    (`SuccessfulExit: false`) or the existing bare `<true/>` (§7). No
    change to `_backend_systemd.py` — already correct for both specs.
11. **Tests**:
    - `DisplayLinkage.classify` — a pure-function truth table (4 branches,
      no fakes).
    - `RespawnBackoff.current_delay` — reflects the pending delay without
      mutating it; a second read returns the same value.
    - `_CycleOutcome`/`_run_cycle` — a fake `ClientProvider` whose `get()`
      raises `RuntimeError` drives the `disconnected` branch: assert
      `_back_off()` (the wedged-backoff sleep) is never invoked on that
      path — the specific double-sleep regression review found — and
      assert the batch is restored (content not lost).
    - `HubReplicator` disconnected curve — assert the delay sequence
      matches the 2s→120s curve across repeated cycles (fidelity check for
      the exact cadence, not just "some backoff exists"), and that a
      subsequent successful `get()` resets it.
    - `ClientRegistry.wait_for_reconnect` — a thread sets `_reconnected`
      while another is blocked in `wait_for_reconnect(60.0)`; assert the
      waiter returns `True` in well under a second, not anywhere near the
      60s timeout — the fidelity check for prompt rediscovery regardless of
      backoff depth. A second test asserts `wait_for_reconnect` does not
      hold `self._lock` for its duration (a concurrent `.get()` from
      another thread completes while the wait is in flight).
    - `ClientRegistry.is_connected` — reflects the underlying `DisplayLink`
      state with no I/O.
    - `DisplayLiveness` — with a fake `KeepaliveClients` whose `get()`
      always raises `RuntimeError`: assert exactly one `INFO` log fires
      (on the transition), assert no `WARNING` fires across repeated
      cycles, and assert the loop's wait interval becomes
      `_DISCONNECTED_PROBE_INTERVAL` after the first failure.
    - `DisplayLinkOperations.get_link()` — with a fake `ClientRegistry`
      reporting not-connected and a nonzero live-scene count, assert the
      return is a `DisconnectedLinkState` with `linkage == "held"` and a
      populated `retry_delay_seconds`; with a fake reporting connected,
      assert the return is a `ConnectedLinkState` with no
      `retry_delay_seconds` field at all (not merely `None`). Neither case
      requires a display fixture.
    - `_backend_launchd.py` — a unit test asserting the two `KeepAlive`
      renderings (`restart_on_crash_only=True` → dict form;
      `restart_on_crash_only=False` → bare `<true/>`), and a fidelity check
      that `HUB_SPEC`'s rendered plist is byte-identical before and after
      this change.
    - **Grep-provable safety check (§12 invariant 5)**: a test (or a
      `make check`-wired grep) asserting no source file under
      `src/punt_lux/domain/hub/` references `ServiceManager` in connection
      with `DISPLAY_SPEC`/`DisplayServiceManager`.
12. **CHANGELOG** entry under `## [Unreleased]`.
13. **z-spec model** — **done** (z-spec mission `m-2026-09-10-002`,
    jms): a new specification, `docs/display_linkage.tex`, not an
    extension of `docs/hub_replicator.tex`. That spec's own `Repl` schema
    has exactly one thread that ever touches the display connection; this
    design's entire novelty is a *second* thread (`DisplayLiveness`)
    dialing the same registry, coordinated through a shared
    `threading.Event` consulted without holding the registry's lock, plus
    two independently-tuned backoff curves — none of which exists in
    `hub_replicator.tex`'s carrier or invariants. Grafting a second actor
    onto that already-verified, committed regression artifact would force
    re-deriving its six proven invariants (I1–I6) under an interleaving
    they were never checked against, for new invariants that are
    orthogonal to them. `display_linkage.tex` cross-references
    `hub_replicator.tex` for the reconciliation hook (DES-068) it already
    models, rather than re-deriving it. All eight §12 invariants and
    deadlock-freedom model-check clean at `DEFAULT_SETSIZE 2`
    (7,464 states). Both mandatory fidelity controls reproduce the exact
    symptoms: (a) collapsing the tri-state outcome onto the shared backoff
    makes `discBackoff` unreachable past its base value while the shared
    counter plateaus at the wedge backoff's low cap; (b) deleting the
    early-wake exit from the wait makes a display reconnect not promptly
    break the replicator out — reachable and stable while the replicator
    stays parked. Coverage: `docs/display_linkage_coverage.md`.

## 11. Rejected Alternatives

**The earlier draft's demand-open design** (`DisplayPresence.ensure_running()`
calling `ServiceManager.for_display().start()` from `ClientRegistry.acquire()`,
gated by an `OFF` veto flag). Rejected by explicit operator ruling (§2): it
requires the Hub to have privileged control over the display's process,
which is false today only by convention and will be structurally false
once the two are on different machines (§8). Documented here rather than
silently dropped, because the root-cause trace in §1 is genuinely reused —
only the conclusion drawn from it changes.

**Stop retrying once disconnected** (an intermediate idea raised while
correcting the above: treat `HELD` as terminal until some external signal
says "try again"). Rejected by explicit operator ruling: *"The hub can
retry and that is fine... it needs some type of exponential backoff to a
slow retry state,"* not a cessation of retries. Retrying is how content
reconnects when a display later appears with nobody having to nudge the
Hub; the defect was always the cadence, never the existence of the retry.

**A single shared backoff object for both the wedged-and-connected case and
the never-connected case.** Considered reusing `HubReplicator._backoff`
(0.1s→2.0s) for both, just raising its cap. Rejected: the two scenarios
have genuinely different expected timescales — a wedged display is
expected back within seconds because the supervisor's own crash-restart is
in flight (§7); a fully disconnected display may legitimately stay that
way for hours. One shared cap is a compromise that serves neither well; two
independently-tuned backoffs (§6.2), reusing one existing class
parameterized rather than duplicated, serve both correctly with a two-line
change.

## 12. Safety Invariants — Required Before Implementation (z-spec)

Re-derived for the corrected model; the earlier draft's veto-centric
invariants (`off ⇒ never-open`, etc.) are moot — there is no veto and no
Hub-initiated open to guard against anymore. This remains a genuine
interleaving problem (content push, disconnect, reconnect, and the retry
timer, all potentially concurrent) and the mission's own trigger for
mandatory z-spec still applies.

1. **Content is never lost while disconnected.** Every scene marked dirty
   (or already live) while `DisplayLinkage` is `DISCONNECTED`/`HELD`
   remains in `HubDisplay`'s authoritative store and on the dirty signal;
   no interleaving of push, disconnect, and retry drops, forgets, or
   silently discards a batch.
2. **A (re)connect reconciles all held content exactly once.** The
   moment `DisplayLinkage` transitions from not-connected to connected,
   every currently-live scene (and the menu) is marked dirty exactly
   once — none missed, none double-sent for the same reconnect event.
3. **Neither concurrent actor on `ClientRegistry` blocks or spins on a
   missing display.** Scope explicitly includes `DisplayLiveness` as well
   as `HubReplicator` — both call `.get()` on the same registry from
   separate threads. Every dial attempt resolves in bounded time (the
   connect timeout); `HubReplicator`'s interval between send-retry attempts
   is always governed by the disconnected-backoff's current delay (never a
   tight unbounded loop), and `DisplayLiveness`'s own probe interval is
   always one of exactly two named values — `_interval` or
   `_DISCONNECTED_PROBE_INTERVAL` — never an unbounded tight loop either.
4. **The disconnected-backoff curve is genuinely exponential and reaches a
   slow steady state, not merely bounded.** Across a sustained
   disconnection, successive delays strictly increase up to the configured
   cap (§6.2's 2s→120s, or whatever the implementation tunes it to) and
   then hold at the cap — the specific defect this design fixes (§1: a
   curve that climbs but plateaus too low) must be the exact thing the
   model can distinguish from a correct curve.
5. **The Hub never issues a process-control call to the display.** No
   code path in `domain/hub/` (replicator, recovery, liveness, client
   registry) calls `ServiceManager.start()`/`.stop()`/`.restart()` for the
   display, under any circumstance — checkable by grep (§10 item 11) and by
   the model, as the absolute form of the operator's ruling.
6. **A display connect promptly breaks out of the slow-retry state, via the
   specific mechanism §6.3 defines, not merely "eventually."** Concretely:
   `HubReplicator._wait_disconnected` blocks on
   `ClientRegistry.wait_for_reconnect`, which returns the instant `.get()`
   succeeds from *either* thread; `DisplayLiveness` probes at
   `_DISCONNECTED_PROBE_INTERVAL` regardless of how deep the replicator's
   own backoff has climbed. This must not degrade to "within the current
   backoff delay," which is the exact claim the original blocking-`time.sleep`
   sketch made and which review found false.
   **Scope, as amended by `docs/display_linkage.tex`'s own I6 paragraph
   (z-spec mission `m-2026-09-10-002`, jra-evaluated):** the *mechanism* —
   an early-wake path distinct from the timeout, present, reachable, and
   destroyed exactly by reverting `wait_for_reconnect` to a blocking sleep
   — is what the Z model proves, by reachability of `wokenEarly = set` and
   by that state becoming unreachable under the reverted fidelity variant.
   The literal "within one probe tick" bound is a real-time claim an
   untimed Z model has no clock to state, let alone prove; it rests on two
   facts the model proves true by construction (the wait never holds
   `ClientRegistry._lock`, so the prober's own dial is never blocked by a
   parked replicator) and one fact outside the model entirely (the
   prober's actual 5-second cadence, and the real thread scheduler's
   fairness between the wake and the timeout). The implementation mission
   should treat "within one probe tick" as an empirical property to verify
   against the running system (§10 item 11's
   `ClientRegistry.wait_for_reconnect` test, timing-asserted), not as a
   claim this or any Z model discharges.
7. **A `disconnected`-classified cycle never advances the wedged-display
   backoff, and vice versa.** Structurally guaranteed by `_CycleOutcome`'s
   three-way `Literal` (§6.1) — `_run_cycle` has no code path that calls
   both `self._back_off()` (wedged) and `_wait_disconnected` (disconnected)
   for the same cycle — but "structurally guaranteed in the sketch" is a
   claim to verify, not a substitute for verifying it: the model must show
   no reachable state advances both counters from one batch.
8. **Deadlock-freedom, with `DisplayLiveness` modeled as a second
   concurrent actor.** `ClientRegistry._lock` (an `RLock`), the
   replicator's dirty-signal wait/drain loop, `HubReplicator`'s blocking
   `wait_for_reconnect` call, and `DisplayLiveness`'s independent probe
   loop never produce a cyclic wait. The specific claim to check, not just
   assume: `wait_for_reconnect` does not hold `ClientRegistry._lock` for
   the duration of its wait (§6.3), so `DisplayLiveness`'s own `.get()` —
   and any MCP-tool thread's `.get()` for an unrelated query — can still
   acquire the lock and complete while the replicator is parked waiting for
   exactly one of them to wake it.

## Related Documents

- Bead `lux-81t3.1`; epic `lux-81t3`.
- [`../../DESIGN.md`](../../DESIGN.md) — DES-088 (visibility axis), DES-089
  (identity is a path; multi-Hub), DES-090 (cross-host transport).
- [`../display_lifecycle.tex`](../display_lifecycle.tex) →
  [`../display_lifecycle.pdf`](../display_lifecycle.pdf) and
  [`../display_lifecycle_coverage.md`](../display_lifecycle_coverage.md) —
  the process-singleton socket lifecycle this design's connect/disconnect
  observation already relies on.
- [`../hub_replicator.tex`](../hub_replicator.tex) →
  [`../hub_replicator.pdf`](../hub_replicator.pdf) and
  [`../hub_replicator_coverage.md`](../hub_replicator_coverage.md) — models
  Hub→Display replication including the DES-068 connect-success re-mark
  hook this design's reconciliation leans on; the likely extension target
  for §12's invariants rather than a wholly new spec (§10 item 11).
- [`./service-lifecycle-migration.md`](./service-lifecycle-migration.md) —
  the managed-service model (`ServiceManager`, `ServiceSpec`) this design
  deliberately does NOT call into from Hub code; still the reference for
  `ServiceSpec`'s existing shape that §7's `restart_on_crash_only` field
  extends.
- `src/punt_lux/domain/hub/clients.py`, `replicator.py`, `recovery.py`,
  `respawn_backoff.py`, `liveness.py`, `hub_display.py`,
  `_backend_launchd.py`, `_backend_systemd.py`, `_service_spec.py` — the
  current implementation this design extends.
