# Display Linkage: Hold Content, Never Chase the Display

**Status:** design, unimplemented. Bead `lux-81t3.1`, epic `lux-81t3`. Mission
`m-2026-09-10-001`. Implementation and the z-spec model are separate
missions, dispatched only after operator ratification of this document.

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

    DISCONNECTED = auto()       # no display connected; nothing held either
    HELD = auto()               # no display connected; content is waiting
    CONNECTED_IDLE = auto()     # display connected; nothing live to show
    CONNECTED_ACTIVE = auto()   # display connected; live content is rendering

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

## 6. The Fix: A Slow, Bounded, Named Retry — Not a Black Hole and Not a Stop

### 6.1 Two backoff regimes, kept separate

The codebase already has two backoff mechanisms and this design adds a
third by reusing one of them, rather than inventing a new mechanism:

| Backoff | Lives in | Paces | Range today |
|---|---|---|---|
| `HubReplicator._backoff` | `replicator.py` | Retrying a batch after ANY `_run_cycle` failure (currently conflates "wedged, connected" and "not connected at all") | `_BASE_BACKOFF_SECONDS=0.1` → `_MAX_BACKOFF_SECONDS=2.0` |
| `RespawnBackoff` | `respawn_backoff.py`, used by `SendRecovery` | Pacing successive `reap()` calls on a display that keeps crashing after reconnect (display-crash-quarantine.md) | `_BASE_DELAY_SECONDS=1.0` → `_MAX_DELAY_SECONDS=30.0`, resets after a stable interval |

Both are correctly scoped to *connected-but-misbehaving* scenarios, where a
few-second cadence is right because the supervisor's own crash-restart
(§7) is expected to resolve things within seconds. Neither is the right
shape for *never-connected-at-all*, which can legitimately last
indefinitely (a display that's off, or on a machine the user hasn't turned
on yet, per §2 item 4). This design adds a **third, distinctly-paced**
backoff for exactly that condition, rather than repurposing either
existing one — conflating them was the root of the 2-second-forever defect
in the first place (§1).

### 6.2 The new not-connected retry curve

Reuse `RespawnBackoff`'s shape (`note_respawn()` / `reset_if_stable()`
already do exactly the right thing — grow on each retry, reset once
stable) by parameterizing its two constants instead of hardcoding a third
copy of the same twelve lines:

```python
# respawn_backoff.py — only the constructor changes; existing callers unaffected
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
```

`HubReplicator` composes a second instance for the not-connected case:

```python
self._disconnected_backoff = RespawnBackoff(base_delay=2.0, max_delay=120.0)
```

Curve: 2s, 4s, 8s, 16s, 32s, 64s, capped at 120s — squarely inside the
operator's stated "once a minute to once every five minutes" band. The
exact numbers are an explicit tunable, not load-bearing: the operator's own
words are "it's not critical what it is." What is load-bearing is the
*shape* — genuinely exponential, genuinely capped one to two orders of
magnitude above the existing 2-second wedged-display ceiling, so an
unattended, no-display Hub settles into a quiet, minute-or-slower poll
instead of a tight loop.

### 6.3 Catching the right exception on its own branch

`RuntimeError` (no display was ever connected — `.get()`'s failure mode)
must be distinguished from `BlockingIOError`/`OSError` (a display *was*
connected and the send just failed) at the point they're raised, not left
to fall through to the same catch-all:

```python
def _push_cycle(self, batch: DrainedBatch) -> _CycleOutcome:
    try:
        emptied = self._attempt(batch)
    except RuntimeError:
        # No display connected at all — nothing to reap or heal, just wait.
        self._recovery.restore(batch)
        delay = self._disconnected_backoff.note_respawn()
        self._log_disconnected(delay)
        time.sleep(delay)
        return _CycleOutcome(recovered=True, emptied=())
    except BlockingIOError as exc:
        ...  # unchanged — wedged-display recovery, self._recovery / RespawnBackoff(1.0, 30.0)
    except OSError as exc:
        ...  # unchanged — dead-peer reconnect
    return _CycleOutcome(recovered=False, emptied=emptied)
```

A clean cycle (a real send succeeded) resets `_disconnected_backoff` to a
fresh `RespawnBackoff(base_delay=2.0, max_delay=120.0)` immediately — no
stability window needed here, unlike the crash-quarantine `RespawnBackoff`,
because "reconnected and sent successfully" is unambiguous in a way
"hasn't crashed again yet" is not (there is no analogous flapping risk to
guard against).

### 6.4 Logging: state the condition, don't cry wolf

Today's `logger.exception("replicator cycle failed; retrying the batch")`
fires every cycle, indistinguishable from a genuine failure, training an
operator to ignore it. The corrected behavior: log once, at `INFO`, on the
transition *into* `HELD`/`DISCONNECTED` ("no display connected; N scene(s)
held, next retry in Ns"), and at `DEBUG` on every subsequent already-waiting
cycle — the state is expected and already visible through introspection
(§9), so the log's job is a breadcrumb for someone reading logs, not a
recurring alarm.

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
"reads local/Hub state only" shape:

```python
# operations/models/display_link.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["DisplayLinkState"]


class DisplayLinkState(BaseModel):
    """The Hub's own view of its display connection and any content held.

    Answerable with zero display round-trip — that is the entire point:
    this must work precisely when `linkage` is DISCONNECTED or HELD.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    linkage: Literal["disconnected", "held", "connected_idle", "connected_active"]
    live_scene_count: int
    retry_delay_seconds: float | None  # current not-connected backoff delay; None when connected
    hub_host: str   # socket.gethostname() — which machine this Hub is on
    hub_pid: int    # os.getpid() — which Hub process, for a same-host duplicate
```

```python
# operations/display_link.py
from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.display_linkage import DisplayLinkage
from punt_lux.operations.models.display_link import DisplayLinkState

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

    def get_link(self) -> DisplayLinkState:
        """Return the current linkage classification and host identity."""
        count = len(self._live_scene_ids())
        connected = self._clients.is_connected
        linkage = DisplayLinkage.classify(connected=connected, live_scene_count=count)
        return DisplayLinkState(
            linkage=linkage.name.lower(),
            live_scene_count=count,
            retry_delay_seconds=None if connected else self._replicator.disconnected_delay,
            hub_host=socket.gethostname(),
            hub_pid=os.getpid(),
        )
```

`ClientRegistry` gains a cheap read-only `is_connected` property
(`self._client is not None and self._client.is_connected` — no lock, no
I/O) so this operation never has to attempt a connect just to answer a
read. `HubReplicator` gains a small `disconnected_delay` property exposing
the current `_disconnected_backoff` delay for the same reason —
introspection should show the operator not just "held" but "and the Hub
will try again in about N seconds," so a person watching doesn't have to
guess whether it's about to retry or settled into the five-minute
steady-state.

Surfaced via a new read-only MCP tool `display_link_get` (no arguments,
alongside the existing `display_mode_get`/`display_state_get` reads) and a
CLI verb, `lux display link`. Both work with no display connected at all —
verified explicitly in the write-set's test plan (§10 item 8), since a
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
   existing crash-respawn caller is unaffected) (§6.2).
3. **Modify** `src/punt_lux/domain/hub/replicator.py` —
   - Compose a second backoff instance,
     `self._disconnected_backoff = RespawnBackoff(base_delay=2.0, max_delay=120.0)`.
   - `_push_cycle` catches `RuntimeError` on its own branch, distinct from
     `BlockingIOError`/`OSError` (§6.3).
   - Logging: `INFO` on transition into the not-connected state, `DEBUG` on
     repeats (§6.4).
   - New `disconnected_delay` read-only property for §9's introspection.
4. **Modify** `src/punt_lux/domain/hub/clients.py` — add a cheap read-only
   `is_connected` property to `ClientRegistry` (§9). No other change —
   `get()` keeps its current shape and behavior exactly (no ensure, no
   split; the earlier draft's `acquire()`/veto machinery is fully removed,
   not merely unused).
5. **New** `operations/models/display_link.py` (`DisplayLinkState`) and
   `operations/display_link.py` (`DisplayLinkOperations`), composed into
   `operations/facade.py` alongside the existing concern classes (§9).
6. **New** MCP tool `display_link_get` (read-only, no arguments) and CLI
   verb `lux display link`, mirroring the existing `display_mode_get`/
   `lux display mode` read shape.
7. **Modify** `src/punt_lux/_service_spec.py` — add
   `restart_on_crash_only: bool = False` to `ServiceSpec`; set
   `restart_on_crash_only=True` on `DISPLAY_SPEC` only (§7). `HUB_SPEC` is
   not touched.
8. **Modify** `src/punt_lux/_backend_launchd.py` — `_plist_content()`
   branches on `spec.restart_on_crash_only` to emit the dict form
   (`SuccessfulExit: false`) or the existing bare `<true/>` (§7). No change
   to `_backend_systemd.py` — already correct for both specs.
9. **Tests**:
   - `DisplayLinkage.classify` — a pure-function truth table (4 branches,
     no fakes).
   - `HubReplicator` — a fake `ClientProvider` whose `get()` raises
     `RuntimeError` drives the not-connected branch: assert the batch is
     restored (content not lost), assert the delay sequence matches the
     2s→120s curve across repeated cycles (fidelity check for the exact
     cadence, not just "some backoff exists"), assert a subsequent
     successful `get()` resets the delay.
   - `ClientRegistry.is_connected` — reflects the underlying `DisplayLink`
     state with no I/O.
   - `DisplayLinkOperations.get_link()` — with a fake `ClientRegistry`
     reporting not-connected and a nonzero live-scene count, assert
     `linkage == "held"` and the call requires no display round-trip
     (constructed with no display fixture at all).
   - `_backend_launchd.py` — a unit test asserting the two `KeepAlive`
     renderings (`restart_on_crash_only=True` → dict form;
     `restart_on_crash_only=False` → bare `<true/>`), and a fidelity check
     that `HUB_SPEC`'s rendered plist is byte-identical before and after
     this change.
   - **Grep-provable safety check (§11 invariant 5)**: a test (or a
     `make check`-wired grep) asserting no source file under
     `src/punt_lux/domain/hub/` references `ServiceManager` in connection
     with `DISPLAY_SPEC`/`DisplayServiceManager`.
10. **CHANGELOG** entry under `## [Unreleased]`.
11. **z-spec model** (`docs/display_linkage.tex` or an extension of the
    existing `docs/hub_replicator.tex` — that spec already models
    Hub→Display replication including the connect-success re-mark hook
    (DES-068) this design leans on, per `docs/README.md`'s coverage table,
    so extending it may be more accurate than a fresh document; the
    implementation mission should confirm which after reading it) — the
    seven invariants in §11, with a fidelity control that reproduces this
    design's own root cause (§1) when the fix is reverted: catching
    `RuntimeError` on the generic branch again must reproduce "the backoff
    plateaus at 2s and never reaches the slow steady state."

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
independently-tuned backoffs (§6.1), reusing one existing class
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
3. **The Hub never blocks or spins on a missing display.** Every dial
   attempt resolves in bounded time (the connect timeout); the interval
   between attempts is always governed by the disconnected-backoff's
   current delay, never a tight unbounded loop.
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
   display, under any circumstance — checkable by grep (§10 item 9) and by
   the model, as the absolute form of the operator's ruling.
6. **A display connect promptly breaks out of the slow-retry state.**
   Regardless of how deep into the backoff curve the Hub currently is (even
   sitting at the 120s cap), the very next cycle after a display becomes
   reachable sends the held content and resets the curve — the Hub is never
   "committed" to waiting out its current delay once a display is actually
   there.
7. **Deadlock-freedom.** `ClientRegistry._lock` (an `RLock`), the
   replicator's dirty-signal wait/drain loop, and the disconnected-backoff's
   own sleep never produce a cyclic wait or a scenario where a new content
   push cannot eventually be observed because the replicator thread is
   parked.

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
