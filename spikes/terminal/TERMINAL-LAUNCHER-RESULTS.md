# Terminal launcher: machine enablement and live menu path

The operator clarified the lifecycle: selected machines run luxd-pty via enable;
the running daemon registers Terminal; executing the menu command launches a
terminal. The initial Display-bootstrap proposal was removed, not shipped.

## Operator surface

After installing this branch with the terminal extra and its installed binary:

```sh
lux terminal enable
lux terminal status
lux terminal restart   # explicit owner restart ends held programs
lux terminal disable   # stops held programs and removes registration
```

Enable installs/starts the local launchd/systemd service via existing Lux
backends. It does not configure other hosts, run through MCP/REST or start from
Display rendering. Status is read-only. Repeated enable does not restart an
active owner. The supervisor resolves `~/.local/bin/luxd-pty`; it does not install
an unmerged checkout automatically. No normal service was enabled/replaced here.

An explicit foreground `luxd-pty --socket <private path>` is a debugging path.
For full isolation its HOME/Hub must also be private. `--no-menu` retains headless
empty-only idle exit and is used by native/lifecycle benchmark fixtures.

## Menu and click behavior

One explicit app identity backs the daemon's REST and persistent Hub listener.
Terminal registers after each handshake, with lease/renewal/reconnect behavior
matching voxd Music. Registration starts no shell. A pushed callback publishes
one Terminal scene/session; repeat click reopens it without spawning a second
program. Previously opened content is restored after Hub restart. Exited screens
stay exited, not silently respawned; a new-session/manager UI is separate scope.

The native owner stays single-threaded. Hub I/O runs in a bounded supervised
helper process that watches its actual parent via getppid, not PID-file guesses.
Spawn failure stays outside owner lifetime, exit is observed/reaped with WNOHANG,
retry is bounded, and core cleanup is unconditional. This replaced a trial
listener thread before commit because multithreaded forkpty risks deadlocks.

## Actual isolated proof

`check_menu_launcher.py` runs full private Hub/Display/owner processes. A private
test-only route calls the production callback router with the Hub's own leaf ID,
just below OS pixel hit-testing. This route is not added to production code.

- Display alone leaves the PTY socket absent: no implicit machine enablement.
- Owner starts, registers Terminal, and has **zero sessions** before the callback.
- Routed menu command publishes scene; actual Display attaches and starts shell
  PID **71367**, owner **71362**, Display **71361**.
- A program marker is visible in the PID-selected/OCR screenshot. A repeated
  callback keeps that same shell PID.
- Hub **71360** restarts as **71411** on a fresh port. Registration and the opened
  scene restore with the same shell PID and visible marker.
- Owned Hub/Display/owner/helper/shell stop; socket and private instance removed.

Raw report: `results/menu-launcher.json`. Screenshots: `menu-launched.png`,
`menu-restored.png`. Reproduce without touching normal services:

```sh
LUX_CAPTURE_SCRIPT=../lux/scripts/screenshot_macos.py \
  timeout 120 .venv/bin/python -m spikes.terminal.check_menu_launcher
```

This proves menu routing/projection/real-window output and recovery, **not**
physical mouse hit-testing or calibrated keyboard-to-pixel latency. The prior
OS-keyboard probe gap remains explicit.

## Automated verification

Tests cover register-before-shell, callback reuse, rejection/error containment,
no-menu lifetime, unstarted helper cleanup, bounded helper restart/spawn failure,
real parent death, supervisor/CLI enable-disable policy and read-only status.
Real assembled Hub registration/callback integration complements actual-window
proof. Supervisor operations are mocked; none installs on the operator's machine.

Native in-process fork tests are run separately from Hub/CLI fixtures that can
create background threads, rather than suppressing Python's fork warning.

Final scoped make check: **850 passed, 22 integrations deselected**; separately
all **22 integrations passed** in sequential isolated sets (6 native, 16 service).
Whole-repository strict typing: zero errors, seven existing ImGui source warnings.
Lint/OO/coupling/suppression gates pass; source suppressions remain **123**. Wheel
and source builds succeed. No test daemon/helper remains. Normal services were
not installed, enabled or replaced.

Current verification and remaining product/merge/platform/security gaps are in
STEP4-REVIEW.md. This launcher change supersedes the lazy-start claims in the
historical step-4 handoff; it does not authorize main merge or installation.
