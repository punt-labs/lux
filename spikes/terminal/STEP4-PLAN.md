# Step 4 plan: `luxd-pty`, PTYs out of the Display

Transport clarification: the direct Display → `luxd-pty` socket described below
is only a latency baseline for measuring the Hub path. Production terminal
traffic goes through the Hub; this historical plan does not implement the relay.

Subsequent operator clarification supersedes demand-start policy: selected
machines run the supervised owner via `lux terminal enable`; the daemon registers
Terminal and its callback launches the scene. Display never implicitly enables
it. Current evidence: TERMINAL-LAUNCHER-RESULTS.md and ADR-0008. The stage logs
below preserve the historical sequence.

Written before the code. Supersedes the architecture explorations in
`STEP4-DESIGN.md`, `step4-options.html` and `merged-architecture.html`, which
stay as records of the research. This plan is deliberately smaller than any of
them.

## Goal

Shells survive a Display restart, crash or upgrade. Nothing else.

Today (ADR-0006) each terminal's PTY and Ghostty state live inside the Display
process. Step 4 moves them into a small process per user, `luxd-pty`, that the
Display attaches to. On attach the Display gets a snapshot of the screen, then
live bytes; it sends keys back. When the Display goes away the daemon keeps
reading, so the next attach is just another snapshot.

## Not the goal

Kept out on purpose, so the branch stays mergeable and does not pre-decide the
Vox Rooms architecture (`docs/concepts/vox-rooms/prfaq.tex`, "the code merges
later, if at all"):

- Any client other than the Display. Agents reading screens, principals,
  consent, trust levels: later, on top of the same two operations.
- Any transport other than a local Unix socket.
- Daemon upgrades that keep shells (the Holder/Core process split). The seam
  is kept as two modules; the split is not built.
- The Hub. It does not know the daemon exists. Terminal bytes never pass
  through it (ADR-0006's rule stands).
- Themes, scrollback search, Linux testing, and the rest of
  `docs/terminal-known-limitations.md`.

## Shape

```
  Display process                         luxd-pty process (one per user)
  ┌─────────────────────────┐             ┌──────────────────────────────┐
  │ terminal element        │   Unix      │ Core                         │
  │ renderer, painter       │   socket    │   Session: Ghostty + state   │
  │ key encoder (ADR-0004)  │◀══════════▶ │   snapshot, attach, viewers  │
  │ Ghostty replica/session │  attach/    │ Holder                       │
  │ (fed from the socket)   │  send       │   spawn, read, write, resize │
  └─────────────────────────┘             │   reap, pump with budget     │
                                          └──────────────┬───────────────┘
                                                      PTY│
                                                   ┌─────┴─────┐
                                                   │ zsh / vim │
                                                   └───────────┘
```

Two operations, plus housekeeping:

| Operation | Direction | Meaning |
|---|---|---|
| `attach(session, command, cols, rows)` | Display → daemon | Create the session if it does not exist (with `command`), then stream: one snapshot, then bytes until detach. |
| `send(session, bytes)` / `resize(session, cols, rows)` | Display → daemon | Keys to the PTY; a new size. |
| `list`, `kill` | Display → daemon | Housekeeping. |
| `exited(status)` | daemon → Display | The program ended. The session stays until killed; the Display shows `[process exited]` as the spike does today. |

## Wire protocol

Framed, binary, on a Unix stream socket. Every frame is
`[channel u32 LE][kind u8][len u32 LE][payload]`, payload at most 1 MiB
(small on purpose: a keystroke must not queue behind a large frame).

- Channel 0 carries control messages: one JSON object per frame. Requests have
  an `id`; replies echo it.
- Each attach gets its own channel. On it the daemon sends `SNAPSHOT`, then
  `DATA` frames; the Display sends `DATA` (keys), `RESIZE` and `CREDIT`.
  A snapshot larger than the frame cap is transferred in bounded chunks with
  a declared total length; the client applies it only when complete.
- Frame kinds: `DATA`, `SNAPSHOT`, `CREDIT`, `RESIZE`, `CLOSE`, and
  generation-two `SNAPSHOT_START` carrying reset metadata.
- Flow control: a channel starts with 256 KiB of credit; the Display returns
  credit as it consumes. A viewer more than 4 MiB behind gets a fresh
  `SNAPSHOT` instead of the backlog.

This is herdr-core's framing with fewer kinds. It is kept in
`src/punt_lux/wire/stream/` so a later client can reuse it, but no later
client is built here.

## Snapshot

Two forms, chosen per attach:

- **Binary** (`ghostty_snapshot_encode` / decoder): includes both screens,
  scrollback and a half-received escape sequence when continuation tracking
  was enabled before output was fed. Tracking is bounded at 64 KiB; exceeding
  that bound postpones attach until the parser returns to ground state.
  This is the normal same-version attach format.
- **VT repaint** (Ghostty's formatter, `FORMAT_VT`, with modes, keyboard
  flags, charsets and cursor): a visible-state fallback, not an exact emulator
  checkpoint. It has no history or parser continuation. Negotiated separately;
  a version mismatch must never silently promise lossless restoration.

Rules, from the research (`STEP4-DESIGN.md`):

1. A snapshot carries modes (mouse, bracketed paste, alternate screen, kitty
   keyboard flags), not just cells.
2. The cut between snapshot and tail falls on a parser boundary: the daemon
   snapshots at ground state, or uses the binary form, which carries the
   partial sequence.
3. The VT repaint has a tested recipe. The naive formatter output replays one
   row off; the recipe fixes that and the test proves it.

## Security model, for this step only

Same-user only, enforced by the operating system:

- Socket at `<lux state dir>/pty/luxd-pty.sock`, directory mode 0700, socket
  created under umask 077.
- The daemon refuses to start if the directory exists with the wrong owner or
  mode (tmux's check).
- The peer's uid is checked on every connection (`SO_PEERCRED` on Linux,
  `LOCAL_PEERCRED` on macOS); a different uid is closed without a reply.

Access to the socket is a shell as the user. That is true of tmux and herdr
and cannot be dressed up; the policy layer that distinguishes clients is out
of scope here.

## Code layout

```
src/punt_lux/
  wire/stream/
    __init__.py
    frames.py        framing: encode/decode, kinds, size cap          (pure, tested)
    messages.py      control messages as dataclasses + JSON codec      (pure, tested)
  pty/
    __init__.py
    __main__.py      `python -m punt_lux.pty` / the `luxd-pty` entry point
    holder.py        PTY ownership: spawn, read, write, resize, reap, tail
    core.py          sessions, Ghostty per session, snapshots, viewers, credit
    server.py        the socket: listen, peer check, frame dispatch, lifecycle
    snapshot.py      binary + VT snapshot/restore recipe                (pure, tested)
    paths.py         socket path, state dir, permission checks
  display/terminal/
    remote.py        the Display's client: attach, feed the replica, send keys
    (sessions.py and pty.py move to pty/; the rest is unchanged)
```

The `terminal/ffi*.py` modules are the shared pyghostty boundary, without
Display or GPU imports. They own native allocation and terminal release.
No daemon module accesses private handles directly.

## Quality bar

The branch is to be mergeable, so every stage meets Lux's bar as the spike
did not:

- Type hints throughout; `ruff`, strict `mypy` and `pyright` clean on the new
  packages.
- Unit tests in `tests/` for every pure module (frames, messages, snapshot
  recipe) and for the core's session and credit logic with a fake holder.
- One integration test that starts the daemon, attaches twice, kills the first
  client, and compares screens. Hard `timeout` on every test; no blocking
  `waitpid`.
- `make check-oo`, `make check-coupling` and `make check-suppressions` run at
  the end of each stage; regressions fixed, not blessed.
- No apostrophes or em dashes in prose; sentences under thirty words.
- Each stage is one or more signed commits with a message that says what it
  proves.

## Stages

Each stage ends with a measurable result written into this file's log.

### Stage 1: the snapshot recipe

Pure code, no daemon, no socket.

- `pty/snapshot.py`: `encode_binary`, `restore_binary`, `paint_vt`,
  and the version check.
- `ffi.py`: the formatter and snapshot calls.
- Tests: snapshot a terminal in each known state into a fresh terminal and
  compare cells, cursor, title and modes. States: plain scrolled text; vim on
  the alternate screen; mouse tracking on; bracketed paste on; a cut
  mid-escape-sequence; a 200x60 screen with 10,000 lines of scrollback.
- Fix the off-by-one found in research, with the test that shows it.

Done when: binary snapshots round-trip retained parser and screen state;
VT paints round-trip the supported visible-state cases. A VT paint cannot
round-trip an unfinished sequence; callers must wait for parser ground.

### Stage 2: daemon with one session, Display as client

- `wire/stream/`: framing and messages, with tests.
- `pty/holder.py`: `pty.py` moved and given the pump loop, without a frame
  budget (the daemon has no frames).
- `pty/core.py`, `pty/server.py`, `pty/paths.py`: one session, one
  viewer, no credit yet.
- `display/terminal/remote.py`: the Display attaches and feeds its replica.
  `TerminalSessions` and `_pump_terminals` removed.

Done when: typing in the real Lux window feels the same as the spike, and
`yes` in one terminal does not drop the frame rate of a table next to it.
Record: keystroke round trip, bytes per second the daemon reads, Display
frame time under flood.

### Stage 3: restart and multiple viewers

- Credit and the 4 MiB lag rule.
- Several viewers per session; the last one to type or resize sets the size.
- Reconnect: kill the Display, start it, compare the screen to the daemon's.

Done when: the screen is identical after a restart, two Displays show the same
session, and the reconnect time is measured. Record it.

### Stage 4: lifecycle

- Start on demand: the first Display that needs the daemon starts it, with the
  user's environment (the spike's `user_environment()`), detached from the
  Display.
- A session ends when killed, or stays as `[process exited]` after its program
  exits until killed.
- The daemon exits when it has had no sessions and no clients for a while.
- Nothing leaks: no orphaned shells or transient sockets; isolated test instances
  are removed after their owners stop. Private reusable lock/log files persist
  under ADR-0007's inode-safe runtime-state policy.

Done when: a start, use, Display-restart, kill, exit cycle leaves no owned process
or socket. The original zero-file wording is superseded by ADR-0007; stable
private lock/log state is not claimed as a transient leak.

### Stage 5: hygiene

- ADR-0007 superseding ADR-0006.
- `docs/terminal-known-limitations.md` updated.
- Spike behavioral checks that still matter live in `tests/`; remaining research
  scripts are retained with an explicit historical/non-production artifact index.
- Ratchets run and clean.

## Decisions deferred to measurements

- **Holder in Python or Rust.** Python first. Stage 2's bytes-per-second and
  flood numbers decide. The Holder is the only piece that would move.
- **Snapshot history length.** The screen plus a bounded history on attach;
  the bound is set from stage 3's reconnect timing.

## Log

### Stage 1 — snapshot primitives

- 45 tests pass in 0.51 s under a hard 60 s limit. They compare visible text,
  renderer rows (including styles), cursor, modes and title. They also cover
  returning from alternate screen, history, malformed input, partial CSI input,
  and continuation overflow followed by recovery.
- Binary snapshots require continuation tracking to be enabled before feeding
  output. The previous claim that any terminal could snapshot mid-sequence was
  wrong. Tracked terminals retain at most 64 KiB of parser continuation.
- Native encoder and formatter buffers are freed with `ghostty_free` after
  copying. Decoder-created terminals receive the same finalizer as pyghostty's
  normal terminal constructor.
- Ruff, mypy and pyright pass on this stage. The suppression ratchet passes.
  The original OO/coupling failures were resolved in the quality pass below.
- No daemon or Display connection is implemented yet. Stage 2 is next.

### Quality pass before stage 2

- Replaced constructor-time public assignments with private typed state and
  property-backed APIs. Constructors follow the repository's `__new__` pattern.
- Native snapshot/access adapters own their codec operations. VT repaint is an
  object bound to its source terminal; field-layout decoding belongs to its
  value types. Split cell-style data from row data and extracted appearance.
- Extracted renderer bindings, static leaf specs, window setup, frame hint
  translation and terminal activity from their coordinators. Removed the
  private `_strip_none` re-export; its consumer imports the utility directly.
- Fixed native view-resource cleanup and added an idempotent close test.
- Added terminal wire round-trips and window-setup tests. Updated the renderer
  kind-count assertion from 25 to 26, explicitly including terminal.
- All new source modules meet OO thresholds. Existing touched modules show
  improvements without regressions against `3712972`. Coupling and suppression
  checks pass; suppression count stays 123.
- Registered the passing scores through `make update-oo` and
  `make update-coupling`, including their generated audit logs. No thresholds
  were changed, and no regressions were blessed.
- `make check BASE_REF=3712972` passes with the test portion scoped through
  `PYTEST_ADDOPTS`: 682 terminal, protocol, renderer and frame tests. Lint and
  typing cover the whole repository. Pyright reports no errors and seven
  missing-source warnings for native ImGui modules.
- The full macOS test suite was deliberately not run, per the operator's
  earlier constraint. Broader suite and live-window verification remain merge
  prerequisites; this pass does not claim the whole branch is merge-ready.

### Stage 2 — framing checkpoint

- Added a native-independent `protocol/pty` package with immutable frames and
  an incremental, bounded decoder. Header layout follows the plan.
- Receives are capped at 64 KiB and payloads at 1 MiB. Invalid headers fail
  immediately; malformed input and truncated EOF poison the decoder so the
  connection owner cannot resume using a desynchronized stream.
- 38 tests cover every frame kind, every split through a sample header and
  payload, byte-at-a-time input, coalesced channels, maximum payload, invalid
  channel values, oversize declarations and truncated EOF.
- Socket service, control messages and daemon integration are not built yet
  at this framing checkpoint; the control checkpoint below adds requests.

### Stage 2 — control and ordering checkpoint

- Added immutable hello, attach, list and kill requests with owned codecs and
  a runtime-checkable structural contract. Validation is strict: bounded
  UTF-8 JSON, exact fields, duplicate-key rejection, positive integer ids,
  bounded grid sizes and identifier-only session names.
- 43 control tests cover typed round-trips, malformed input and direct
  construction validation. The scoped `make check` now passes 763 tests;
  repository-wide lint/type and all three ratchets pass.
- Added `docs/pty_attach.tex`, its compiled PDF and a coverage report.
  The two-viewer model checks all 830 states and 4,171 transitions for
  snapshot-prefix correctness, no tail before snapshot completion, and
  detach leaving the terminal process running.
- Fidelity checks reproduce both a bad snapshot cut and the original
  in-Display disconnect/termination defect. The corrected model finds neither.
- This is not a proof of daemon lifecycle, peer authentication or eventual
  delivery. The coverage report names the missing core and real-PTY tests.
- Request handling, replies, daemon IO and Display integration are next.

### Stage 2 — held-process and core checkpoint

- Moved PTY ownership out of the Display package into `pty/holder.py`.
  The existing in-Display stand-in uses this holder until remote attachment
  replaces it; this module move alone does not yet preserve shells on restart.
- Added bounded input buffering for short writes/EAGAIN, explicit child
  reaping with WNOHANG, and guarded, idempotent descriptor closure. Exec failure
  always exits the forked child, including unexpected exceptions.
- Added a native-independent process port and a headless session core.
  Sessions parse output with no viewers, capture exact byte positions, do not
  respawn on reattach, and keep failed cleanup tracked for retry.
- The authoritative parser alone answers terminal queries. A parser failure
  prevents publishing a snapshot with a false output cut. A typed native IO
  owner explicitly releases Ghostty resources after process closure.
- Six real-PTY integration tests pass under an outer timeout. They cover large
  input, final output/status, multiple exec failure paths and a real headless
  core being inspected and used without respawning its program.
- `docs/pty_child.tex` and its PDF model PID ownership. ProB checks 28 states
  and 75 transitions. Mutations reproduce signalling a reaped PID and
  forgetting a child before reap. The coverage document states the limits.
- Replies, socket service and Display integration remain outstanding at this
  core checkpoint; the service checkpoint below adds replies and Unix IO.

### Stage 2 — foreground service checkpoint

- Added `luxd-pty`, a foreground Unix service with private endpoint checks,
  kernel peer-UID authentication and hello/version negotiation before creation.
- Added bounded nonblocking peer output queues and success/failure replies.
  Sessions survive socket CLOSE/EOF. Explicit kill and daemon shutdown own
  process termination. One session failure does not discard another's output.
- The native bindings moved into shared `terminal/`, removing the daemon's
  accidental GPU import. A `terminal` extra installs pyghostty without ImGui,
  Pillow, numpy or OpenGL; an import-guard test verifies that separation.
- Three independent-daemon integration tests pass: disconnect/reconnect keeps
  the same PID and screen; pre-hello creation is denied; mismatch stays unready.
- Added `pty_peer.tex`, its PDF and coverage report. ProB explores 49 states
  and 176 transitions without unauthorized or pre-hello creation. The weakened
  creation guard produces an immediate counterexample.
- Credit accounting, multiple viewers per session, automatic startup and
  actual Display integration remain outstanding at this service checkpoint.

### Stage 2 — Display attachment checkpoint

- Replaced the in-Display PTY registry with `RemoteSessions` and a nonblocking
  connection/replica pool. Display shutdown closes only its connection and
  native replicas. It never sends session kill.
- Snapshot adoption replaces the terminal, render cache, selection and encoders
  together. Replicas do not answer program queries. Grid changes wait for an
  authoritative resize notification before resizing the replica.
- The daemon publishes explicit exit notices; reconnecting to an exited
  program keeps it exited, without respawning.
- Production replica-pool integration tests restore the same PID and screen.
  Isolated actual-window tests pass normal close/restart and SIGKILL/restart;
  the same program survives, and the new Display owns the viewer binding.
  Evidence and test limits are recorded in `STEP4-LIVE.md`.
- The daemon still requires manual startup. Credit, lag repaint, multiple
  viewers and performance measurements remained open at this checkpoint.

### Stage 3 — viewer flow and multicast

- Added independent 256 KiB credit windows, including snapshot fragments.
  ACKs may return only actual in-flight bytes. Snapshot resets preserve old
  debt rather than minting a second window.
- Unsent live tail is bounded at 4 MiB. Overflow requests an authoritative
  repaint; pending initial snapshots finish rather than being restarted by
  every burst. Capture that is temporarily unavailable is retried with backoff.
- Several viewers share one process. Input/resize selects the active grid,
  broadcasts fresh snapshots, and passive geometry does not fight the owner.
- The client assembles snapshots in a separate bounded transfer object and
  acknowledges fragments before the whole snapshot is applied.
- Wire generation two adds `SNAPSHOT_START`. Older versions are rejected by
  hello; they are not allowed to misinterpret reset metadata as native bytes.
- Finite 5 MiB burst integration: the fast viewer reaches END while another
  withholds credit; the slow viewer then catches up by repaint. No endless
  flood process is used.
- Credit/reset model: 1,024 states and 5,249 transitions, no violations.
  Mutations reproduce minted credit and output across a dropped-tail gap.
- Automatic startup, idle daemon exit and timing/performance evidence remained
  open at this checkpoint.

### Stage 4 — lazy owner and safe lifecycle

- Display-side connection failure starts a missing daemon with the current
  interpreter, argument-vector posix_spawn, setsid and detached stdio. The UI
  does not wait for launch. Startup children are polled with WNOHANG; Display
  close never kills the owner. Spawn cooldown prevents repeated contenders.
- A lifetime nonblocking flock is acquired before stale cleanup, bind and
  listen, and retained through endpoint/session cleanup. No pid-file age or
  unguarded unlink is used. Stable private lock/log files intentionally remain.
- Owned stale socket is reclaimed only after refused connection and matching
  inode. Existing live listeners, foreign/non-socket nodes and symlinks are
  preserved or rejected. Shared private-directory validation is headless.
- An empty daemon exits after 30 seconds with no clients and no retained
  sessions. Detached live programs and retained exited screens prevent idle
  exit. Socket removal is inode-safe; claim is released after core cleanup.
- Model checks all 53 states / 208 transitions; no ownership or unsafe-idle
  violation. Mutations expose replacing an active claim and stopping with a
  client still attached. Spec, PDF and coverage report are committed.
- Real integration covers simultaneous detached launchers, crash/stale socket
  replacement, short-idle empty shutdown, and a production RemotePool cold
  start followed by viewer close and reconnect for explicit session kill.
- Scoped `make check` passes 816 tests; separately all 17 integrations pass.
  Full typing has zero errors (seven existing ImGui source warnings), all
  ratchets pass against 3712972, suppression count remains 123. No test daemon
  remains. Main Lux services are untouched.
- Timing/scene-isolation measurements, actual-window cold-start/restart proof,
  superseding ADR and final hygiene remained at this checkpoint. Broader macOS
  verification stays a merge prerequisite; no merge or PR is requested.

### Stage 5 — window evidence and bounded measurements

- Actual isolated macOS window lazily starts the owner. Program PID 66887 and
  daemon PID 66826 survive Display SIGKILL/restart; Hub replay restores the
  visible marker. PID-selected/OCR-checked screenshots and logs back this up.
  A too-early blank restart screenshot was rejected and the check corrected.
- Added reproducible finite-burst benchmarks and raw reports. Warm attach
  median/p95 5.013/5.276 ms (10 samples). Cold startup 1,126.099 ms includes the
  pool's one-second retry delay; not a sub-50 ms cold-start claim.
- Found tiny CREDIT frames accumulating ahead of input when one frame was
  flushed per pump. Bounded 64 KiB coalescing preserves FIFO and partial sends;
  tests include 32 varied chunk partitions. Smaller PTY slice was tried and
  reverted after measurement showed no improvement.
- Same-observer before/after burst-input median/p95: 93.943/279.429 ms to
  60.586/70.034 ms. Full pool pump p95 0.171 ms; no GUI render loop in that test.
  Input during flood is still slower than idle and remains an explicit limit.
- Actual GUI: 20 Hub/Display pings overlap a finite paced 5 MiB burst. Median/
  p95 14.928/15.906 ms versus quiet-idle 59.021/62.573 ms (output wakes render
  loop). This does not measure keyboard-to-pixel latency or GPU FPS.
- Scoped `make check`: 821 passing tests, all gates pass, no added suppressions.
  Separately 17 integration tests pass. Owned test children/sockets cleaned.
- See STEP4-PERFORMANCE.md and STEP4-LIVE.md. Superseding ADR, final design/doc
  hygiene, targeted review and merge-prerequisite checklist remain. Full macOS
  suite has not been run under the operator constraint.

### Stage 5 — targeted review and decision handoff

- ADR-0007 records current ownership, framing/credit, lazy lifecycle and local
  shell-authority scope, superseding ADR-0006's Display lifetime/pump decision.
- Added STEP4-REVIEW.md: implemented evidence is separated from still-unmet
  original acceptance experiments and merge prerequisites. No merge approval
  is implied. Two real simultaneous GUI windows, real keyboard/pixel under a
  heavy neighboring table, soak/many-terminal tests and broader platform/suite
  checks are not claimed as complete.
- Review reproduced a permanent FAILED replica when initial snapshot attach
  happened during a 70,000-byte unfinished OSC sequence. Initial unavailable
  snapshots now close only that viewer connection for bounded reconnect. The
  integration recovers at parser ground with the same PID; no program kill.
- Replica rejects daemon-to-viewer CREDIT/RESIZE instead of silently ignoring
  invalid stream directions. Added unit tests; current native ownership comment
  points at the shared headless codec rather than the removed Display module.
- Stable private lock/log retention and historical research-script retention
  are explicit plan clarifications, not zero-file/deletion claims. Artifact
  index identifies old scripts/options as evidence, not shipping dependencies.
- Scoped make check: 823 tests pass with 18 integration deselected; separately
  all 18 integrations pass. Whole typing/lint and all ratchets pass, suppression
  count 123 unchanged; no test daemon remains.
- Remaining bounded proof and merge work is enumerated in STEP4-REVIEW.md.

### Stage 5 — transport faults and actual multi-window proof

- Operation allocation and grouped allocation/cleanup errors previously escaped
  the control transport and could trigger daemon-wide cleanup. ControlFailures
  now returns a bounded nonempty failure reply to the caller, preserves pending
  cleanup ownership and leaves other sessions alive. Twelve socket/core fault
  cases include empty messages and preserve SystemExit/KeyboardInterrupt,
  including BaseExceptionGroup forms. Actual process-wide OOM recovery is not
  claimed.
- Two simultaneous real Displays (7542/7740), each with an isolated Hub, share
  daemon 7626/program 7688. PID-selected/OCR screenshots show the same program.
  SIGKILL of one window leaves the other receiving a new update; replacement
  Display 8054 rejoins the same program/daemon. Owned instances are cleaned.
- `check_two_windows.py`, raw report and four screenshots retain reproducible
  evidence. Normal Lux services and Hub topology are untouched.
- Scoped make check: **835 passed**, 18 integration deselected; separately all
  **18 integration tests pass**. Whole typing/lint and all ratchets pass, source
  suppressions remain 123. No test daemon remains.
- Keyboard-to-pixel/heavy-table experiments were not started before the operator
  requested this checkpoint. Soak, platform, independent review and broader
  macOS verification remain explicit gaps. No PR or merge is authorized.

### Keyboard/table probe — incomplete evidence

- Actual isolated window renders the terminal and six-column 1,000-row table;
  geometry and PID-selected screenshot/OCR verify both. Permission preflight
  reports capture and event posting allowed.
- PID-targeted Quartz key events do not produce the expected warm response,
  despite focus attempts. The bounded probe fails before finite-burst/key
  samples. Driver/focus versus product input issue is unresolved; no keyboard
  latency numbers or successful keyboard/pixel acceptance are claimed.
- No system-wide keyboard fallback or relabeling of transport input was used.
  Owned program/daemon/Display/Hub and private instance are cleaned. Normal Lux
  is untouched. No production code changes or acceptance relaxation.
- STEP4-KEYBOARD-PROBE.md, explicit incomplete status JSON and setup/unverified
  input screenshots preserve the finding. The helper is labeled exploratory,
  not a passing test. Last production verification remains 835 focused tests,
  18 integrations and all quality gates.

### Final scheduled checkpoint — short lifecycle/resource cycles

- Added five-cycle real-daemon regression coverage for create/input/detach/
  reattach/retained exit/explicit kill. PID and retained screen stay unchanged;
  exited programs do not respawn and each kill leaves no sessions.
- A separate bounded 20-cycle benchmark observes daemon numeric FD set
  [0,1,2,3,4,5] after cycles 2/10/20, empty direct-child lists and unchanged
  parent FD count. RSS rises 496 KiB between warm/final snapshots. This is not
  long-duration memory/descendant/soak proof or maximum throughput evidence.
- Owned program/daemon cleanup/reaping, socket removal and private instance
  deletion complete. Normal Lux is untouched; no test daemon remains.
- Final scoped make check: **835 passed**, 19 integrations deselected; separately
  all **19 integration tests pass**. Whole strict typing/lint and all ratchets
  pass; source suppressions remain 123. Full macOS suite remains unrun under
  the operator constraint.
- STEP4-HANDOFF.md summarizes delivery/evidence and incomplete product/merge
  acceptance. Central shell lifetime separation is demonstrated; unresolved
  keyboard/pixel, long-duration/platform/broader-suite and independent review
  gaps are not hidden or marked complete. No PR or merge is authorized.
