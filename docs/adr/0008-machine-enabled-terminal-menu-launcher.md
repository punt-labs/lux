# ADR-0008: Machine-enabled owner registers the Terminal launcher

- **Status:** Accepted for the spike after explicit operator clarification.
- **Date:** 2026-11-18
- **Supersedes:** ADR-0007's demand-start operational policy. Native ownership,
  replicas, snapshots, credit and Display-independent program lifetime remain.
- **Requirement:** luxd-pty runs on chosen machines via enable; the running daemon
  registers a menu item; executing it launches a terminal, like voxd Music.

## Decision

`lux terminal enable` installs/starts the local launchd/systemd service through
Lux's existing supervisor backend. `disable` stops held programs and removes
registration; status is read-only; restart explicitly ends the owner's programs.
These are local operator commands, not MCP/REST authority and not remote-machine
configuration. The installed executable must include the `terminal` dependency.
No actual normal-service installation was performed while implementing this.

Display connects to an available owner only. It does not start a daemon on
startup, on rendering a terminal element or after a failed connection. That
would defeat machine selection. A foreground owner remains an explicit debugging
path; it can use an isolated HOME/Hub/socket without supervisor registration.

The owner declares one app identity, `luxd-pty`, for its REST and persistent Hub
listen legs. After every handshake it registers callback `terminal`, label
`Terminal`. Lease renewal/reconnect uses the existing public LuxClient listener
mechanism. No polling clicks, agent turn, hardcoded Display menu or Hub topology
change is introduced. Registration does not start a shell.

The callback publishes/reopens one Terminal scene with named session
`luxd-pty-terminal`. Repeat launch retains one program/session; exits stay exited,
not silently respawned. A previously opened scene is re-published after Hub
reconnect; a never-opened scene is not. A new-session/management UI remains
separate scope. Hub/projection failures are isolated from native PTY ownership.

## Native owner and helper lifetime

Hub I/O runs in an owned helper **process**, not a background thread in the
PTY owner. `forkpty` from a multithreaded process is deprecated and can deadlock;
adding a listener thread would undermine the process-lifetime work. The core
still executes all PTY/native work on its single owner loop.

The owner starts the helper with an argument vector and a new process session,
observes/reaps with existing WNOHANG ownership rules, and restarts an unexpected
exit with bounded retry. Spawn failure logs and retries instead of terminating
held shells. Helper shutdown is bounded and core cleanup is unconditional.

The helper watches `getppid()` against the actual spawning owner and exits on
reparenting. It does not test guessed PID-file age or signal an inferred owner.
A real parent-death regression covers owner loss before/after helper startup.

Menu-enabled lifetime stays available without sessions as a supervised app.
Explicit `--no-menu` uses the original continuous empty-only 30-second idle exit.
The earlier daemon safety model describes that headless branch; no new liveness
proof is inferred for the supervised app/helper from it.

## Evidence and boundaries

- Supervisor and CLI policy tests mock operations: no installation/mutation of
  normal machine services. Idempotent enable does not restart an active owner;
  status does not enable anything. Missing-owner Display test proves no spawn.
- Real assembled Hub and independent daemon: menu registers with zero sessions,
  push-routed callback installs Terminal scene; repeated launch remains one scene.
- Isolated actual Hub/Display/owner proof: callback routing below the OS hit-test
  launches a shell visible in a PID-selected/OCR screenshot; repeat preserves
  PID. Restarting the Hub restores registration and scene with the same shell.
- This routing test is not proof of physical OS menu hit-testing or calibrated
  keyboard-to-pixel latency. The earlier keyboard-driver gap remains explicit.
- Existing native/query/credit/lifetime tests run in no-menu mode. Native in-process
  fork tests are run separately from Hub-thread fixtures, not warning-suppressed.

Prior art was checked locally and through Qodo: Vox
`src/punt_vox/voxd/music_player/lux_subscription.py:228-266` and
`lux_clients.py:32-78` at retrieved main `17d8729`. The current branch's public
callback/listener and supervisor contracts govern the actual implementation.

## Adoption

This is code on the isolated spike branch, not a main merge, installation onto
normal Lux services, remote enablement or shipping approval. See
`spikes/terminal/TERMINAL-LAUNCHER-RESULTS.md` for commands, raw evidence, current
validation and remaining acceptance/security/platform gaps.
