# Terminal launcher — machine opt-in, identical daemon/menu flow to Vox

Requested after step-4 hand testing. Operator clarification wins over the first
Display-bootstrap proposal: luxd-pty runs only on chosen machines via enable;
that running daemon registers Terminal; the menu command launches the terminal.

Prior art checked locally and via Qodo: Vox lux_menu/lux_clients/lux_subscription
(main 17d8729, retrieved mirror dated Nov 16); this branch's public LuxClient
callback/listener APIs and ServiceManager are authoritative for integration.

## Lifecycle and scope

1. `lux terminal enable` installs/starts this machine's supervised `luxd-pty`,
   using Lux's existing launchd/systemd backend. `disable` explicitly stops held
   programs and removes registration. Status is read-only. No automatic enable
   on Display startup, terminal rendering, another machine or Hub startup.
2. Enabled/running daemon holds an explicit app identity and persistent Hub
   listener. Register Terminal after every handshake; lease/keepalive/reconnect
   restore it. Hub failure must not end PTY ownership. Registration starts no shell.
3. Menu command publishes/reopens one Terminal scene/session, with no agent turn
   or click polling. Closing/reopening preserves the shell; exited screens do
   not silently respawn. New-session manager UI is separate work.
4. The PTY owner remains single-threaded for safe forkpty. Hub async I/O runs in
   a supervised helper process, not a new owner thread. Helper watches getppid
   (not PID-liveness heuristics), exits with parent, is polled/reaped with WNOHANG
   and restarted boundedly on unexpected exit. Shutdown is bounded and always
   closes owner resources even if helper cleanup fails.
5. Menu-enabled daemon is a long-lived available application. `--no-menu` retains
   continuous empty-only idle exit for headless diagnostics/tests. A foreground
   debugging process can explicitly exercise the same menu registration path.
6. Display connects only to the available machine owner; missing service is a
   visible connection/enablement issue, never implicit machine enablement.
7. All tests disable normal-Hub registration or use an isolated Hub HOME. No
   actual supervisor enable/install/disable is run against normal services.

## Acceptance/checkpoint

- Unit policy tests for supervisor enable/disable and CLI read-only status.
- Real assembled Hub/daemon: entry appears with no sessions, push click publishes
  Terminal scene; repeat/reconnect use the same session metadata.
- Existing native/query/credit/PID/lifetime tests continue to pass in no-menu mode.
- Parent-loss/helper restart and bounded teardown coverage.
- Isolated actual-window menu/launcher evidence, keeping API-routed click evidence
  distinct from physical OS hit testing.
- Strict typing/lint/OO/coupling/suppression gates unchanged, scoped macOS tests
  only, integrations sequential under timeout, signed branch commit/push.

## Explicit exclusions

No product merger, remote transport, broad macOS suite, main installation,
normal-service restart, PR or merge. The hand-test instance has stopped/cleaned.
This is new requested launcher work, not a retroactive claim that step 4 already
had machine enablement or a daemon-owned menu.
