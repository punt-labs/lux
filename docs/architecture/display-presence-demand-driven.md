# Display Presence: Demand-Driven, Not Keepalive-Forced

**Status:** design, unimplemented. Bead `lux-81t3.1`, epic `lux-81t3`. Mission
`m-2026-09-10-001`. Implementation and the z-spec model are separate
missions, dispatched only after operator ratification of this document.

## 1. Problem, Confirmed Against the Code

The bead's corrected symptom (operator-observed 2026-09-01, 0.32.1): closing
the Lux window terminates `luxd-display.service` /
`com.punt-labs.luxd-display`, and nothing brings it back. A `show()` pushed
to a Hub with a closed display is accepted by the Hub and rendered nowhere.

Tracing the code confirms exactly why, and it is a single missing step, not
a diffuse defect:

- `ClientRegistry.get()` (`src/punt_lux/domain/hub/clients.py:96-108`)
  constructs the Hub's one `DisplayLink` with `auto_spawn=False`, with the
  comment: *"the display's own service unit is its supervisor now; the Hub
  only sends scenes, it never launches a competing process."* That comment
  is correct as far as it goes — before `lux-5uc7`, the Hub raced the
  managed-service supervisor by forking its own competing process
  (`DisplayPaths._spawn()`, a raw `subprocess.Popen`, `src/punt_lux/paths.py:191-205`).
  Removing the Hub-side fork fixed the double-spawn hazard and, as a side
  effect of `KeepAlive`/`Restart=on-failure` no longer racing a second
  supervisor, incidentally fixed the *original* omnipresent-window bug this
  epic opened with.
- But removing the fork removed the **only** code path that ever brought the
  display up on demand, and nothing was put in its place. `DisplayLink.connect()`
  (`src/punt_lux/domain/hub/display_link.py:174-194`) with `auto_spawn=False`
  skips `DisplayPaths.ensure()` entirely and goes straight to a raw
  `socket.connect()`, which raises `RuntimeError` when nothing is listening.
- `replicator_ports.py`'s `DisplayLifecycle` protocol docstring says the
  quiet part out loud: *"Before lux-5uc7, the Hub both reaped a wedged
  display and spawned its replacement... The Hub's remaining lifecycle role
  is killing."* Reaping (killing a wedged display) survived the migration;
  **ensuring never got a managed-service replacement**.
- The failure is silent by construction, not by accident: `HubReplicator._push_cycle`
  (`src/punt_lux/domain/hub/replicator.py:275-305`) only catches
  `BlockingIOError`/`OSError` around a send. `RuntimeError` from a
  not-running `.connect()` escapes to `_run_cycle`'s broad
  `except Exception`, which restores the batch and backs off
  (`_BASE_BACKOFF_SECONDS` → `_MAX_BACKOFF_SECONDS`, `recovery.py`/`replicator.py`).
  The Hub logs `"replicator cycle failed; retrying the batch"` forever, at a
  capped 2-second cadence, and never once asks the supervisor to start the
  service. This is the exact mechanism behind "Hub accepted the push but
  nothing appeared."
- `DisplayLiveness` (`src/punt_lux/domain/hub/liveness.py`), the keepalive
  worker, already does the *right* thing today for the reason the epic
  wanted: it pings and, on failure, drops and reconnects
  (`self._clients.get()`), but `.get()` never spawns anything either, so
  keepalive cannot resurrect a closed display and does not force-spawn an
  unwanted one. Keepalive is not the bug. It is, however, wired to the same
  `ClientRegistry.get()` the demand path uses, which matters below (§5).
- The service supervisors' restart policy already self-heals a *crash*
  without the Hub's help: systemd's unit sets `Restart=on-failure` /
  `RestartSec=5` (`_backend_systemd.py:157-158`) — a non-zero exit is
  auto-restarted, a clean exit is not. macOS's plist sets bare
  `KeepAlive=<true/>` (`_backend_launchd.py:199-200`), which launchd's own
  documented semantics restart on **any** exit, including a clean one — an
  asymmetry with systemd that this design closes (§6, §9).

So the fix is precise: **wire one missing step** — "content wants to go out,
the display isn't running, ask the managed-service supervisor to start it,
wait for the socket, then send" — without reopening the double-spawn hazard
`lux-5uc7` already closed, and without breaking keepalive's already-correct
non-spawning behavior.

## 2. The Presence State Machine

Four states, matching the mission's naming. Three of the four are **pure
derivations** of two observable facts and one piece of Hub-held intent —
there is deliberately almost no state to get out of sync with reality:

```text
PresenceState.classify(off: bool, is_running: bool, live_scene_count: int) -> PresenceState

    off                                     -> OFF
    not off and not is_running              -> CLOSED
    not off and is_running and count == 0   -> IDLE
    not off and is_running and count  > 0   -> OPEN
```

| State | Meaning | Who observes it |
|---|---|---|
| `OFF` | The Hub refuses to connect to, populate, or start the display. An absolute veto, independent of whether a process happens to be running. | `_off` flag, held by the Hub. |
| `CLOSED` | Not vetoed; no live display process. The resting state — true both "never started" and "user closed it." | `DisplayPaths.is_running()` |
| `OPEN` | Not vetoed; display running; at least one live Hub scene. | `is_running()` + `HubDisplay.live_scene_ids()` |
| `IDLE` | Not vetoed; display running; zero live Hub scenes. The window is present and usable as a launcher (World/Clients menus, beads applet) with nothing to show. | `is_running()` + `live_scene_ids()` |

The only state `CLOSED` vs `OFF` distinguishes is *whose decision it was* —
the user's (or a crash, or "never asked yet") vs. the Hub's own veto. Both
present identically at the OS level (`is_running() == False`); the `_off`
flag is the one bit of memory this design needs beyond what is already
observable, and it changes only on an explicit `presence_set` call (§7).

### Transitions and triggers

| From | Trigger | To | Mechanism |
|---|---|---|---|
| any | `presence_set(off)` | `OFF` | Sets `_off = True`. Does **not** stop an already-running display (§8, rejected alternative). |
| `OFF` | `presence_set(on)` | `CLOSED` (or `OPEN`/`IDLE` if a process happens to already be running out-of-band) | Sets `_off = False`; no action taken to open anything. |
| `CLOSED` | content push (a scene becomes dirty and the replicator needs to send it) | `OPEN` | `ClientRegistry.acquire()` sees `not is_running()`, calls `DisplayPresence.ensure_running()` → `ServiceManager.for_display().start()`, polls for the socket, then connects (§4). |
| `CLOSED` | content push, but `ensure_running()` fails (not installed, supervisor refuses, timeout) | `CLOSED` | The batch is restored and backed off exactly as today; the failure is now attributable (a named error), not silent. |
| `OPEN` | last live scene disposed everywhere | `IDLE` | Purely observational — `live_scene_ids()` becomes empty. No transition code needed. |
| `IDLE` | new content pushed | `OPEN` | Purely observational. |
| `OPEN`/`IDLE` | user closes the OS window (clean exit) | `CLOSED` | The socket drops; the next `.get()`/`.acquire()` observes `is_running() == False`. |
| `OPEN`/`IDLE` | process crash (non-zero exit) | supervisor auto-restarts per its own policy (`Restart=on-failure` / the corrected `KeepAlive`, §9); once the socket is live again, the next `.get()`/`.acquire()` reconnects and `_connect_and_reconcile` repaints every live scene (DES-068) | Stays `OPEN`/`IDLE` from an external observer's point of view; the Hub never had to "ensure" anything, because the *supervisor's own contract* is the crash-recovery path, not the Hub's. |
| `OPEN`/`IDLE` | crash outlives the supervisor's restart attempts | `CLOSED` once observed down | Same as user-close, from the Hub's point of view — it cannot and need not distinguish "gave up" from "closed." The next content demand re-ensures. |

No state machine library, no explicit transition methods, no stored
enum beyond one boolean. This directly follows the reasoning
`service-lifecycle-migration.md` §5.1 already used to reject a `LegacySweep`
state pattern: "clean" and "dirty" were not two behaviorally distinct modes,
they were two *outcomes* of one idempotent operation. The same is true here
— `CLOSED`, `OPEN`, and `IDLE` are outcomes of observing reality, not modes
a class switches between.

## 3. Presence vs. DES-088's Content/Visibility Axes

DES-088 settled a different, narrower question: for one already-open
display, does a *frame's* content (client-owned: `show`/`update`/dispose)
or its *visibility* (user-owned: close/collapse/dock/raise) get written by
a given event? DES-088's rule — a content event never writes visibility, a
visibility event never writes content — governs frames **inside** a running
display.

Presence is one layer up: it governs whether the **display process itself**
exists at all. DES-088 has nothing to say about a display that is not
running — there is no frame to be visible or invisible if there is no
window. The two are orthogonal and compose cleanly:

- Presence answers: "is there a display process to hold any frames?"
- DES-088 answers, once presence is `OPEN`/`IDLE`: "of the frames it holds,
  which are on-screen?"

A user closing the **last** ImGui frame inside a running display (a DES-088
visibility event) does not, by itself, touch presence at all — the process
is still running, so presence stays `OPEN` while `live_scene_count` may
still be nonzero (a closed-but-not-disposed frame keeps its scenes per
DES-088) or drops to zero and presence reads `IDLE`. Presence only reacts to
the **process** disappearing (the OS window's own close, or a crash) — a
different, coarser gesture than DES-088's per-frame close button. This
design does not add, rename, or reinterpret any DES-088 mechanism; it adds
the layer above it that DES-088 assumed but never specified.

## 4. Demand-Path Wiring Against the Managed-Service Model

**The rule this design enforces: "ensure" means asking the supervisor to
start its managed unit and waiting for the socket — never forking a
competing process.** `DisplayPaths._spawn()`/`ensure()`'s raw
`subprocess.Popen` path is retired from the Hub's demand path entirely (it
may still serve a bare, service-less dev workflow — see §10 write-set item
7 — but the Hub never calls it again).

New component, `DisplayPresence`, in `src/punt_lux/domain/hub/presence.py`,
alongside `clients.py` and `replicator.py`:

```python
from __future__ import annotations

from enum import Enum, auto
from typing import Self, final

from punt_lux.paths import DisplayPaths
from punt_lux.service import (
    DisplayServiceManager,
    ServiceActionFailedError,
    ServiceNotInstalledError,
)

__all__ = ["DisplayPresence", "EnsureOutcome", "PresenceState"]


class PresenceState(Enum):
    """The four presence states — derived, never stored except the veto."""

    OFF = auto()
    CLOSED = auto()
    OPEN = auto()
    IDLE = auto()

    @classmethod
    def classify(
        cls, *, off: bool, is_running: bool, live_scene_count: int
    ) -> PresenceState:
        """Return the state implied by observed facts plus one held veto."""
        if off:
            return cls.OFF
        if not is_running:
            return cls.CLOSED
        return cls.OPEN if live_scene_count > 0 else cls.IDLE


class EnsureOutcome(Enum):
    """The result `DisplayPresence.ensure_running` reports — never raises.

    A veto or a supervisor failure is an ordinary, expected outcome here
    (PY-EH-4/PY-EH-8): the caller (`ClientRegistry`) decides whether its own
    contract requires turning a given outcome into an exception.
    """

    ALREADY_RUNNING = auto()
    STARTED = auto()
    VETOED = auto()
    FAILED = auto()


@final
class DisplayPresence:
    """Own the one piece of presence memory (`off`) and the ensure step.

    Composes the display's `ServiceManager` and `DisplayPaths` — the same
    two collaborators `DisplayRestart` already composes for its own
    supervisor-call-then-poll shape, which this class mirrors rather than
    reinventing.
    """

    _manager: DisplayServiceManager
    _paths: DisplayPaths
    _off: bool
    __slots__ = ("_manager", "_off", "_paths")

    def __new__(
        cls,
        manager: DisplayServiceManager | None = None,
        paths: DisplayPaths | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._manager = manager if manager is not None else DisplayServiceManager()
        self._paths = paths if paths is not None else DisplayPaths()
        self._off = False
        return self

    @property
    def is_off(self) -> bool:
        """Return whether the Hub currently vetoes the display."""
        return self._off

    def state(self, live_scene_count: int) -> PresenceState:
        """Classify current presence given the caller's live-scene count."""
        return PresenceState.classify(
            off=self._off,
            is_running=self._paths.is_running(),
            live_scene_count=live_scene_count,
        )

    def set_off(self) -> None:
        """Veto the display. Does not stop an already-running process (§8)."""
        self._off = True

    def set_on(self) -> None:
        """Lift the veto. Does not itself open anything (§8)."""
        self._off = False

    def ensure_running(self, timeout: float = 30.0) -> EnsureOutcome:
        """Ask the supervisor to start the display; poll until ready.

        Callers must check `is_off` first — this method assumes the veto
        gate has already been passed, so the one check lives in one place
        (`ClientRegistry`, the actual boundary where Hub/display contact
        begins) rather than being repeated defensively here (PL-PP-3).

        Idempotent against a supervisor already mid-restart (e.g. the
        display just crashed and `Restart=on-failure`/`KeepAlive` is
        already bringing it back): `start()` on an already-active or
        already-activating unit either no-ops or reports a failure that
        this method treats as informational, not fatal — the poll below is
        the actual ground truth, not the supervisor call's return code.
        """
        if self._paths.is_running():
            return EnsureOutcome.ALREADY_RUNNING
        if not self._manager.is_active:
            try:
                self._manager.start()
            except (ServiceNotInstalledError, ServiceActionFailedError):
                # Do not return FAILED yet — a concurrent supervisor-driven
                # restart (crash racing this call) can still bring the
                # socket up; the poll below is authoritative, not this
                # call's return code (see docstring).
                pass
        return self._await_ready(timeout)

    def _await_ready(self, timeout: float) -> EnsureOutcome:
        """Poll `is_running()` until ready or timeout — the ground truth."""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._paths.is_running():
                return EnsureOutcome.STARTED
            time.sleep(0.1)
        return EnsureOutcome.FAILED


display_presence: DisplayPresence = DisplayPresence()
```

(`import time` is written inline above only to keep the sketch legible; the
real module puts it at the top per PY-CS-10.)

`ClientRegistry` (`clients.py`) gains the veto gate and a second, distinct
acquisition method — **not** a second implementation of the same protocol
method, because the two callers need genuinely different contracts:

```python
def _reject_if_off(self) -> None:
    """Refuse any Hub/display contact while presence is vetoed."""
    if display_presence.is_off:
        msg = "display presence is off; refusing to connect or populate it"
        raise RuntimeError(msg)

def get(self) -> DisplayLink:
    """Return a connected DisplayLink — reconnect only, never ensure.

    Used by DisplayLiveness (KeepaliveClients). Never starts the service:
    a keepalive tick that ensured a closed display back into existence
    would be the exact omnipresence bug this epic already fixed, in a new
    disguise.
    """
    with self._lock:
        self._reject_if_off()
        ...  # unchanged below this line

def acquire(self) -> DisplayLink:
    """Return a connected DisplayLink, ensuring the service first if down.

    Used by HubReplicator/SendRecovery (ClientProvider) — the one path
    where there is real content that wants to go out, which is the only
    condition under which the demand path may bring the display up.
    """
    with self._lock:
        self._reject_if_off()
        if self._client is None:
            self._client = DisplayLink(
                name=_DISPLAY_CLIENT_NAME, kind="hub", auto_spawn=False
            )
        self._setup_apps()
        if not self._client.is_connected and not DisplayPaths().is_running():
            outcome = display_presence.ensure_running()
            if outcome is EnsureOutcome.VETOED:
                raise RuntimeError("display presence is off")  # unreachable: gated above
            if outcome is EnsureOutcome.FAILED:
                msg = "display did not become ready via its managed service"
                raise RuntimeError(msg)
        if not self._client.is_connected:
            self._connect_and_reconcile(self._client)
        if not self._client.listener_active:
            self._client.start_listener()
        return self._client
```

`ClientProvider` (`replicator_ports.py`) is renamed from `.get()` to
`.acquire()` — a Protocol name change, not a shim — so its structural
contract states what it actually promises ("get me a connection, ensuring
the display exists") distinctly from `KeepaliveClients.get()` ("get
whatever connection currently exists"). Every call site inside
`HubReplicator`/`SendRecovery` that sends real content
(`_send_scene`, the menu-send branch in `_attempt`, `_attempt_isolating`'s
send, `SendRecovery.recover`'s post-drop reconnect) moves from
`self._clients.get()` to `self._clients.acquire()`.

## 5. Honored, Not Permanent: How "Close" Self-Heals on the Next Push

Nothing new has to detect "the user closed the window" as a distinct event
from "the process crashed" — see §1's finding that systemd's
`Restart=on-failure` (and the corrected `KeepAlive`, §9) already treat a
clean exit and an abnormal exit differently, entirely inside the
supervisor, with zero Hub involvement. From the Hub's side, both cases look
identical: `is_running()` is `False`, `CLOSED` is the classification, and
`acquire()` will happily call `ensure_running()` on the very next content
push, exactly as it would for a display that had never been opened at all.

"Honored" falls out of `get()` (keepalive) never calling `ensure_running()`
— a closed display stays closed through any number of keepalive ticks with
nothing pushed. "Not permanent" falls out of `acquire()` (the demand path)
always trying `ensure_running()` when not running and not vetoed — the very
next `show()` reopens it. No flag named "was this closed by the user"
exists anywhere, because no code path needs to ask that question — the only
question that matters is "is content trying to go out right now," and that
question is exactly what distinguishes `get()`'s callers from `acquire()`'s.

## 6. The `display:off` Veto Point

**Design decision, stated explicitly rather than left implicit.** The
existing `display:off`/`display:on` control
(`operations/models/config.py`'s `DisplayModeRequest`/`DisplayModeState`,
`operations/display_mode_store.py`) is a **per-repo, client-side, advisory**
setting: it lives in `<repo>/.punt-labs/lux.md`, is read by
`display_mode_get`, and its write path (`cli/display.py:_set_mode`)
explicitly bypasses the Hub — the comment there even says "same shape the
deleted Hub round trip produced." Its intended consumer is the calling
agent, deciding for itself whether to invoke `show()` at all for a given
repo, the same shape as vox's per-repo `enabled` marker. It is not, and
never has been, enforced by the Hub or the demand path — there is no code
anywhere that reads it before a scene is pushed.

Redefining that per-repo file as the Hub's presence veto is rejected: a
Hub aggregates content from many repos and possibly many concurrent
sessions (target.md's "one Hub, many agent/app UIs"), and the physical
display is one shared resource. A per-repo file cannot arbitrate "repo A
says off, repo B says on, what does the one shared window do" — that
question has no answer in the current data model, because scenes are keyed
by `ConnectionScopedId` (DES-086), not by filesystem repo path, and
threading "repo" through the connection/identity model to make that
arbitration possible is an identity-layer change (DES-089's territory), not
a presence-layer one.

**What this design adds instead**: a new, Hub-instance-scoped presence
control — `display_presence.set_off()`/`set_on()` (§4) — which is the
`_off` flag `PresenceState.classify` reads. This is the literal "absolute
veto" the mission asks for: `ClientRegistry._reject_if_off()` is checked
before *any* Hub/display contact, in both `get()` and `acquire()`, so a
vetoed Hub never connects, never sends a manifest, never repaints a
scene — regardless of whether the trigger was a content push, a keepalive
tick, or (per §8) an out-of-band process that happens to be running. It is
new surface (a new operation, MCP tool, and CLI verb — §10 write-set item
6), deliberately independent of the existing per-repo file, which keeps
working exactly as it does today for its existing, narrower job.

The relationship between the two controls (should setting the per-repo file
off for the currently-active repo also flip the new Hub-level flag?) is an
open question for a later design, not resolved here — folding them
together requires the repo-aware connection identity this design
deliberately does not build.

## 7. Keepalive Maintains, Never Force-Spawns

`DisplayLiveness` needs exactly one behavioral change, and it is a
tightening, not new logic: `check_once()`/`_probe()` should short-circuit
to a debug-level no-op when `DisplayPaths().is_running()` is already
`False`, rather than calling `self._clients.get()` and logging a
`WARNING`-level "liveness probe failed" every interval. Today that warning
fires once per `keepalive_interval` for as long as the display is
legitimately, correctly `CLOSED` — a purely cosmetic problem (it does not
spawn anything, because `get()` never ensures), but a real one: a log that
warns continuously about an expected, healthy state trains an operator to
ignore warnings.

No other change is needed. `get()` (§4) never calls `ensure_running()`, so
keepalive maintains exactly what its name says — the *connection* to a
display that is supposed to be there — and never spawns a display that
isn't wanted. This is the direct fix for the epic's original complaint
("today's 2-second liveness worker unconditionally spawns and resurrects
the window"): that complaint was already resolved by `auto_spawn=False`;
this design's job is only to make sure the *replacement* mechanism
(`acquire()`'s `ensure_running()`) never leaks into keepalive's path.

## 8. Empty-but-Open Is Valid; Off Does Not Retract an Open Window

`IDLE` (§2) is a first-class resting state, not a transient one to be
swept away. A display with zero live scenes stays exactly as reachable as
one with content — the World/Clients menus, the beads applet, and any
other launcher affordance keep working, and nothing times it out or closes
it. This falls directly out of `PresenceState.classify` treating `IDLE` as
a plain classification of `is_running() and count == 0`, with no special
"idle too long, tear it down" logic anywhere.

**Rejected alternative: `set_off()` also stops an already-running
display.** Considered making the veto retroactive — killing the display
via `ServiceManager.for_display().stop()` the moment presence turns off,
so "off" always means "no window, period." Rejected because: (1) the
mission's stated invariant is specifically about a **content push** not
opening the display while off, not about tearing down a window the user is
currently looking at; (2) forcibly closing a window mid-interaction because
a flag flipped elsewhere is a surprising, unrequested side effect with no
upside the gate at `_reject_if_off()` doesn't already provide; (3) it
introduces a genuine race between "stop the service" and "a click just in
flight on that same display" with no corresponding safety win, since the
gate already guarantees the Hub sends nothing further to it. The chosen
design (§4, §6) is purely a **forward-looking** veto: nothing new gets in
while off; whatever was already there before the veto was set is left
alone. The one residual gap — an out-of-band actor (a user running
`lux display start` by hand, or `RunAtLoad` firing at the next login) bringing
the process up while the Hub is off — is deliberately left as a non-issue
rather than "fixed" by killing it: `_reject_if_off()` still refuses to
connect to it, so the Hub never populates it with content either way, and
respecting an explicit manual `lux display start` (rather than fighting it)
is the more conservative failure mode.

## 9. Cross-Platform Restart-Policy Asymmetry (Discovered, In Write-Set)

§1 already named this: macOS's plist sets bare `<key>KeepAlive</key><true/>`
(`_backend_launchd.py:199-200`). launchd's documented semantics for the
bare-boolean form are "restart on **any** exit, including a clean one" —
unlike systemd's `Restart=on-failure`, which only restarts on a non-zero
exit. If the display's OS-window-close path exits cleanly (`rc=0`), the two
platforms currently disagree about whether "honored, not permanent" (§2,
§5) actually holds: Linux honors the close (the unit stays down until the
Hub's demand path brings it back); macOS's `KeepAlive=true` would
immediately resurrect it, regardless of what this design does at the Hub
layer, because the resurrection happens one layer below the Hub entirely.

**Required implementation-mission fix**: change the plist's `KeepAlive` key
from the bare boolean to the dictionary form restricting restart to
abnormal exits only —

```xml
<key>KeepAlive</key>
<dict>
    <key>SuccessfulExit</key>
    <false/>
</dict>
```

— which is the macOS-side statement of the identical policy systemd's
`Restart=on-failure` already encodes. This must be verified against real
launchd behavior during implementation (the exact interaction between
`SuccessfulExit=false` and a signal-terminated exit, versus a `sys.exit(0)`
call, is a platform detail this design states with the correct intent but
does not claim to have executed and confirmed).

## 10. Concrete Implementation Write-Set

For the follow-on implementation mission. Every item below is grounded in
a specific file this design read, not a placeholder.

1. **New** `src/punt_lux/domain/hub/presence.py` — `PresenceState`,
   `EnsureOutcome`, `DisplayPresence`, singleton `display_presence` (§4).
2. **Modify** `src/punt_lux/domain/hub/clients.py` — add
   `_reject_if_off()`; add `acquire()`; keep `get()` non-ensuring (§4, §7).
3. **Modify** `src/punt_lux/domain/hub/replicator_ports.py` — rename
   `ClientProvider.get` → `ClientProvider.acquire` (structural contract
   change, not a shim — PL-PP-1).
4. **Modify** `src/punt_lux/domain/hub/replicator.py` and `recovery.py` —
   every call site sending real content (`_send_scene`, the menu-send
   branch of `_attempt`, `_attempt_isolating`, `SendRecovery.recover`'s
   post-drop reconnect) moves from `self._clients.get()` to
   `self._clients.acquire()`.
5. **Modify** `src/punt_lux/domain/hub/liveness.py` — `_probe()` /
   `check_once()` short-circuits to a debug no-op when
   `DisplayPaths().is_running()` is already `False`, instead of calling
   `get()` and warning every interval (§7).
6. **New** Hub-scoped presence control surface, mirroring the existing
   `display_mode_get`/`DisplayModeOperations` shape:
   - `operations/models/presence.py` — a `PresenceStateReply` (`kind`,
     `state: Literal["off","closed","open","idle"]`, plus the host-identity
     fields from §11) and a `PresenceRequest` (`mode: Literal["on","off"]`).
   - `operations/presence.py` — `PresenceOperations`, composed into
     `operations/facade.py` alongside `DisplayModeOperations`.
   - MCP tools in `tools/display_write_tools.py` (`presence_set`) and a
     read tool/CLI verb (`lux display presence`, or extend `lux display
     state`) for `presence_get`.
7. **Modify** `src/punt_lux/paths.py` — `DisplayPaths.ensure()`/`_spawn()`
   (the raw-`Popen` path) is no longer reachable from any Hub code path
   after items 2–4 land. Leave it in place only for the bare,
   service-less dev/test entry points that still legitimately want a
   direct fork (grep every remaining caller after items 2–4 to confirm
   none are Hub-facing; if all remaining callers are test-only or
   `lux display serve --socket` foreground dev usage, consider whether
   `ensure()` should be deleted outright rather than left as a second,
   now-Hub-unreachable way to bring up a display — a decision for the
   implementation mission, not prescribed here per the design-mission
   write-set-is-the-output rule).
8. **Modify** `src/punt_lux/_backend_launchd.py` — `KeepAlive` from bare
   `<true/>` to `{"SuccessfulExit": false}` (§9).
9. **Tests**:
   - `PresenceState.classify` — a pure-function truth table (trivial,
     4 branches, no fakes needed).
   - `ClientRegistry.acquire()`/`get()` — veto behavior with a fake
     `DisplayPresence`/`DisplayServiceManager`: `acquire()` calls
     `ensure_running()` when down and not vetoed; `get()` never does;
     both raise when vetoed regardless of `is_running()`.
   - `DisplayLiveness` — no `WARNING` log and no `get()` call when
     `is_running()` is `False` (fidelity control for §7).
   - E2E (tier 3, mirroring `DisplayRestart`'s existing shape in
     `display_restart.py`): stop the display via `lux display stop`, push a
     scene through the Hub, assert the display comes back via
     `ServiceManager.start()` (spy/assert on the supervisor call, not a
     raw-`Popen` process count) and the scene renders. A second e2e case
     asserts `presence_set(off)` then a push never calls
     `ServiceManager.start()` at all.
10. **CHANGELOG** entry under `## [Unreleased]`.
11. **z-spec model** (`docs/display_presence.tex`, separate mission after
    ratification) — the seven invariants in §12, following
    `display_lifecycle.tex`'s existing shape: flat state schema, one `Init`,
    ProB model-check of every invariant plus deadlock-freedom, a fidelity
    control that reproduces the exact bug in §1 when the fix is reverted
    (drop `acquire()`'s ensure call → the model must exhibit "content
    pushed, display closed, nothing ever renders").

## 11. Multi-Host Introspection Surface (DES-089 Caveat)

The bead's evidence — "pembroke Hub vs keble display" — is not a
wire-protocol multi-Hub-aggregation problem (DES-089/090's cross-host
transport is a separate, unimplemented companion design). It is simpler and
narrower: the Hub-to-Display leg is a same-host `AF_UNIX` socket today
(`DisplayPaths._default_path()` resolves `$XDG_RUNTIME_DIR`/`/tmp/lux-$USER`
— always local), so **each host runs its own independent Hub+Display
pair**, and the failure mode is an operator (or an agent acting on their
behalf) pushing to the wrong host's Hub — one they are not physically
looking at.

This design does not build cross-host aggregation. It surfaces enough for
an agent or operator to catch the mismatch themselves: every presence read
(`presence_get`, and `display_state_get` while at it) includes the Hub's
own host identity, using data already available with no new transport:

```python
@dataclass(frozen=True, slots=True)
class HubHostIdentity:
    """Which machine and process this Hub is — enough to catch a
    wrong-host push, without any cross-host transport (DES-090's job,
    not this design's)."""

    hostname: str  # socket.gethostname()
    pid: int  # os.getpid() — the Hub process, not the display's
    socket_path: str  # DisplayPaths().socket_path — always same-host
```

Included in `PresenceStateReply` (§10 item 6). An agent or CLI reading
`lux display presence` sees, alongside the state, exactly which host's Hub
it just queried — the same information an operator would need to notice
"I'm on pembroke, but I meant to push to keble." This is intentionally
minimal: it is a diagnostic surface, not a fix, and it reuses the identity
shape DES-089 already establishes (`HubId` = hostname + pid) rather than
inventing a parallel one.

## 12. Safety Invariants — Required Before Implementation (z-spec)

The mission's own trigger for mandatory formal verification applies here:
this is a stateful lifecycle with genuine interleaving between
content-push, user-close, `display:off`, keepalive, and supervisor
start/stop — the same class of problem `display_lifecycle.tex` already
solved for the socket-bind race, one layer below this one. **None of these
seven are optional; all must be ProB-model-checked, with a fidelity control
reproducing this design's own bug (§1) when the fix is reverted, before the
implementation mission is dispatched.**

1. **`off ⇒ never-open`.** While presence is `OFF`, no code path — demand
   push, keepalive tick, or an out-of-band process racing a `set_off()` —
   ever causes the Hub to connect to, populate, or start the display.
2. **`wanted-and-not-off ⇒ eventually-a-display`.** If content is live and
   presence is not `OFF`, `ensure_running()` is eventually attempted and,
   absent a persistent external failure (not installed, supervisor
   refuses), the display becomes running. (Liveness, not just safety.)
3. **`user-close-while-idle ⇒ stays-closed`.** Once the display transitions
   to not-running with no content demanding it, it remains `CLOSED`
   indefinitely under keepalive alone — no background process reopens it
   without a fresh content push.
4. **No two-supervisor-call race (`no-two-winners`).** Two concurrent
   triggers for `ensure_running()` (two racing pushes, or a push racing
   keepalive's own reconnect) never result in two overlapping
   `ServiceManager.start()` calls disagreeing about outcome — the
   `ClientRegistry` lock plus `is_active()`/poll-for-ground-truth
   composition (§4) is the claimed mechanism; this must be proven, not
   assumed.
5. **`set_off` mid-`ensure_running()` leaves no stale window.** A
   `presence_set(off)` arriving while an `ensure_running()` call is in
   flight must not result in the Hub treating that in-flight call's
   eventual success as license to send content afterward — the *next*
   `acquire()`'s veto check, not the in-flight call's own completion, is
   what must govern.
6. **Deadlock-freedom.** `ClientRegistry._lock` (an `RLock`) plus the
   synchronous subprocess calls inside `ServiceManager.start()`/`is_active`
   (`launchctl`/`systemctl`) never produce a cyclic wait — this is a new
   lock/external-process combination not covered by
   `display_lifecycle.tex`'s existing spawn-lock/bind-lock ordering, and
   needs its own check.
7. **Crash-restart does not defeat `OFF`.** A supervisor-level auto-restart
   (crash → `Restart=on-failure`/corrected `KeepAlive`) that brings the
   process back up while presence is `OFF` must never result in the Hub
   reconnecting to or repainting it — the specific interleaving of a
   crash-restart racing a `presence_set(off)` that invariant 1 states in
   general.

## Related Documents

- Bead `lux-81t3.1`; epic `lux-81t3`.
- [`../../DESIGN.md`](../../DESIGN.md) — DES-088 (visibility axis), DES-089
  (identity is a path; multi-Hub), DES-090 (cross-host transport).
- [`../display_lifecycle.tex`](../display_lifecycle.tex) →
  [`../display_lifecycle.pdf`](../display_lifecycle.pdf) and
  [`../display_lifecycle_coverage.md`](../display_lifecycle_coverage.md) —
  the process-singleton socket lifecycle this design's `is_running()`
  ground truth already relies on; the reference shape for §12's z-spec
  model and its coverage audit.
- [`./service-lifecycle-migration.md`](./service-lifecycle-migration.md) —
  the managed-service model (`ServiceManager`, `ServiceSpec`,
  `LegacySweep`) this design's `ensure_running()` builds directly on; also
  the precedent for treating a spurious supervisor-call failure as
  self-healing rather than fatal (§4's `ensure_running()` docstring).
- `src/punt_lux/display_restart.py` — the existing
  supervisor-call-then-poll-for-witnesses shape `DisplayPresence.ensure_running`
  mirrors.
- `src/punt_lux/domain/hub/clients.py`, `replicator.py`, `recovery.py`,
  `replicator_ports.py`, `liveness.py`, `paths.py`, `service.py`,
  `_backend_launchd.py`, `_backend_systemd.py`, `_service_spec.py` — the
  current implementation this design extends.
