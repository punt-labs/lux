# ADR-0007: Independent terminal owner; Display holds replaceable replicas

- **Status:** Accepted for `spike/terminal-ghostty`, not canonical Lux architecture.
  The lazy-start operational policy below is superseded by
  [ADR-0008](0008-machine-enabled-terminal-menu-launcher.md): machine enablement
  controls the running owner and its Terminal menu registration.
- **Date:** 2026-11-18
- **Supersedes:** ADR-0006's Display-owned process lifetime and PTY pump. Its
  `terminal` element/session naming decision remains.
- **Evidence:** `spikes/terminal/STEP4-PLAN.md`, `STEP4-LIVE.md`,
  `STEP4-PERFORMANCE.md`; `docs/pty_{attach,child,peer,credit,daemon}.tex` and
  their coverage reports; `tests/pty/` and `tests/wire/model/test_pty_*.py`.

## Context

A shell must survive Display restart, crash and upgrade. Display ownership
cannot satisfy that goal. Owning PTYs in the Hub would merely move the
failure boundary to Hub restart. Relaying terminal traffic through the Hub
does not require it to own the PTYs: production uses that relay, while this
spike's direct Display connection is only its latency baseline.

The bounded task is local terminal lifetime separation, not a merger of Lux,
Vox or biff, a distributed blackboard, a remote transport or an agent API.
Exploratory architecture HTML/design notes are not authority for this decision.

## Decision

### Owner and replicas

- One local `luxd-pty` per endpoint owns PTY masters, program process groups and
  authoritative Ghostty terminals. The default endpoint is per user. Explicit
  short socket paths permit isolated test instances, not multiple owners of
  the same endpoint.
- In the latency baseline, Display attaches directly over a Unix socket. It owns
  replaceable native screen replicas and render/input resources, never the
  programs. Production terminal bytes and input go through the Hub between
  Display and `luxd-pty`; that relay is not implemented here. The baseline Hub
  still stores and replicates the element that names the session.
- The daemon parses output even with no viewers. Only the authoritative parser
  answers automatic program queries; replicas do not duplicate those replies.
- Named sessions start once. A conflicting explicit command is refused by the
  daemon. A program that exits retains its screen/exit status and never respawns
  because an element is repainted or a Display reconnects.
- Viewer close/detach and scene removal do not imply kill. Explicit session kill
  or daemon shutdown terminates held processes with bounded cleanup/reaping.
  Display crash survival does **not** imply daemon crash/upgrade survival.

### Attach and flow

- Normal attach requires matching wire generation and Ghostty snapshot version.
  The current wire generation is three; failure replies identify retryable
  operation faults separately from permanently invalid requests. A binary native snapshot carries both
  screens, bounded history and parser continuation. Its cut precedes all live
  tail bytes sent to that viewer.
- Continuation tracking is enabled before parsing and bounded at 64 KiB. When
  a checkpoint is unavailable, live lag repaint waits/retries. An unavailable
  initial attach closes that viewer connection so the Display's bounded
  reconnect path can retry after parser ground, rather than remaining FAILED.
  Programs and other peers are not terminated. Persistent snapshot size/resource
  failures still need product-level diagnostics/limits.
- VT paint remains an explicit visible-state fallback utility, not a lossless
  checkpoint or a negotiated wire-version downgrade. Version mismatches fail.
- Every viewer has an independent 256 KiB credit window, including snapshot
  fragments. ACKs return only outstanding debt. Receivers acknowledge retained
  fragments before whole-snapshot adoption, permitting transfers larger than
  a window without deadlock.
- Unsent tail is bounded at 4 MiB. Overflow drops only unsent backlog and
  requests a fresh snapshot. Old in-flight debt survives reset. An unfinished
  initial snapshot is not restarted by every output burst. Wire-v2
  SNAPSHOT_START marks repaint/resize replacement metadata.
- Multiple viewers share one process. The last viewer to type or request a
  resize sets the grid; all viewers receive authoritative size/snapshot state.
  Passive geometry preserves its desired grid and does not fight the active
  viewer on every render. This is not collaboration arbitration/ACL policy.
- Framing caps payloads at 1 MiB and socket reads at 64 KiB. Display socket
  pumps are byte/time bounded. A socket send coalesces at most 64 KiB of ordered
  frames, preserving partial-send tails and avoiding one tiny ACK per pump.

### Lazy start and lifecycle

- First use starts a missing owner with the current interpreter, an argument
  vector, posix_spawn/setsid and detached stdio. Display does not wait for
  startup and never kills the owner on close. Startup children are polled with
  WNOHANG, not a blocking wait; retries are bounded by a cooldown.
- A nonblocking lifetime flock precedes stale cleanup, bind and listen. It is
  retained through endpoint/session cleanup; the kernel releases it on crash.
  The reusable lock inode is never unlinked, avoiding old/new-inode split locks.
- Private directory/lock/log/socket validation and kernel same-UID credentials
  establish the local boundary. Stale cleanup removes only an owned refused
  socket with unchanged device/inode. Live listeners, symlinks and non-socket
  nodes are not silently removed. Other connection errors do not authorize unlink.
- An empty owner exits after a continuous 30-second interval with no clients
  **and no sessions**. Retained exited screens count as sessions until killed.
  The socket is transient; private reusable lock/log files intentionally remain.
  The early plan's literal “no file remains” is superseded by this inode-safe
  runtime-state policy, not claimed as a completed zero-file cleanup result.
- Programs get HOME/USER/LOGNAME/SHELL from the user database and exclude
  Display-only runtime variables. An isolated Display HOME does not become a
  shell's login home.

### Security and resource scope

Same UID is shell authority for this spike. It is not an agent capability,
consent check, per-room authorization, signed remote protocol or sandbox.
Rendering a terminal command starts a program; product adoption must review
who can cause that rendering and what namespace/lifetime policy applies.
Do not infer consent merely from the daemon socket's UID check.

The service caps sessions/peers and wire buffers. Native history is 10,000
lines and encoded snapshots are capped at 16 MiB. These bounds are not a
complete per-user memory budget, soak proof or log-rotation policy.

## Consequences and measured limits

- Actual macOS windows demonstrate lazy start and visible restoration after
  Display SIGKILL/restart. PID-selected screenshots and OCR verify the marker
  after Hub replay; PID persistence alone is not repaint proof.
- Direct-path replica warm attach median/p95 was 5.013/5.276 ms (10 samples).
  Cold startup was 1,126.099 ms and includes the pool retry interval.
- Bounded wire batching improved measured flooded-input p95 from 279.429 to
  70.034 ms. Flooded input remains slower than quiet input. These finite local
  observations do not establish maximum throughput or sub-50 ms flood latency.
- The actual Hub/Display ping path remains responsive during the measured
  paced burst. Ping is not keyboard-to-pixel or GPU FPS measurement.
- Formal models check bounded attach, child ownership, peer authorization,
  credit/reset and claim/idle safety; deliberate mutations find violations.
  They do not prove native fidelity, scheduler fairness, OS behavior or absence
  of leaks over an unbounded run. Coverage reports state those gaps.
- Focused automated checks, strict whole-repository typing/lint and all quality
  ratchets pass without threshold relaxation or added source suppressions.
  Broader macOS tests remain intentionally unrun under the operator constraint.
  This is not an assertion that the branch is merge-ready.

## Alternatives considered

- **Keep the program in Display:** cannot survive its crash; rejected.
- **Move it into Hub:** couples program lifetime to Hub and expands scope;
  rejected for this step.
- **Route bytes through Hub:** required for production; not implemented by this
  latency baseline. NATS/remote transport remains outside this spike's scope.
- **Unbounded output queues or dropping bytes without reset:** memory growth or
  invalid replica state; rejected in favor of credit and authoritative repaint.
- **ANSI repaint as complete persistence:** loses history/continuation and other
  native state; rejected as the normal matching-version attach path.
- **Rust daemon first:** no evidence requires the rewrite. Python orchestration
  plus native Ghostty remains the implementation; measurements constrain claims.

## Adoption prerequisites

See `spikes/terminal/STEP4-REVIEW.md` for the acceptance ledger, known limits,
review findings and outstanding merge checks. No PR, rebase into main or merge
is authorized by this ADR. Canonical Lux decisions still require DES entries
and operator approval if this work is adopted.
