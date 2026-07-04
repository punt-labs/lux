# Display Lifecycle: Test-Partition Coverage Audit

Companion to `docs/display_lifecycle.tex`. Derives the test partitions
(Test Template Framework style) from the Z operation schemas, then maps them
against the existing tests in `tests/test_socket_server.py` and
`tests/test_paths.py`. The bar is that the spec's partitions are covered by a
test, not merely that the model-check passed.

Spec-operation → code mapping:

| Spec operation | Code |
|---|---|
| `Probe` | `DisplayPaths._probe` / `is_running` |
| `CleanupStale` | `DisplayPaths.cleanup_stale` / `_clear_dead_files` |
| `Bind` / `BindFail` / `Listen` | `SocketServer.setup` |
| `LoseRaceLive` | `setup` early-return on `is_running` |
| `Reap` / `ReapDead` | `DisplayPaths.reap` |
| `AcquireBindLock` / `ReleaseBindLock` | `DisplayPaths.bind_lock` |
| `AcquireSpawnLock` / `ReleaseSpawnLock` | `DisplayPaths._spawn_lock` (`ensure`, `reap`) |
| `Crash` | environmental — simulated by stale sockets / `display.stop()` |
| `Reset` | `ensure` re-entry |

## 1. Partitions

### Probe(a?) — over `socketStatus`

| # | Partition | Expected |
|---|---|---|
| P1 | `sabsent` (no socket file) | DEAD |
| P2 | `slistening`, owner answers ReadyMessage | READY (live) |
| P3 | `slistening`, owner accepts but no handshake | ACCEPTING (live) |
| P4 | `sstale` (file present, no listener) | DEAD (refused) |
| P5 | **`sbound` — bound, fd open, `listen` not yet called** | **DEAD (the window)** |
| P6 | live owner, connect times out (overloaded) | ACCEPTING (presence wins) |
| P7 | live owner, connect raises EMFILE/ENFILE | ACCEPTING (ambiguous ≠ dead) |
| P8 | live owner, malformed / non-object / recursion reply | ACCEPTING |
| P9 | non-socket file at path | DEAD |
| P10 | recycled PID file, no listener | DEAD (identity from socket, not PID) |

### CleanupStale(a?) — guard `socketStatus ∈ {sstale, sbound}`, unlink → `sabsent`

| # | Partition | Expected |
|---|---|---|
| C1 | `sstale` dead socket | unlinked |
| C2 | non-socket file | unlinked |
| C3 | broken symlink | unlinked |
| C4 | guard-false: `slistening` (live, ready) | preserved |
| C5 | guard-false: `slistening` accepting-but-silent | preserved |
| C6 | guard-false: ambiguous probe (timeout / EMFILE) | preserved |
| C7 | symlink to a live socket | preserved |
| C8 | **`sbound` owned by another (fresh bind in the window)** | **must NOT unlink — bind lock serialises** |

### Bind(a?) / BindFail(a?)

| # | Partition | Expected |
|---|---|---|
| B1 | `sabsent` → success | `sbound`, returns True |
| B2 | `sstale` cleaned, then `sabsent` → success | rebinds, returns True |
| B3 | `sbound` not owned → EADDRINUSE/EEXIST (BindFail) | lostRace, returns False |
| B4 | non-race OSError (EACCES) | raises (fail loud) |

### Listen(a?)

| # | Partition | Expected |
|---|---|---|
| L1 | owner branch (`a? ∈ owner`): bound → listening | path goes `slistening` |
| L2 | orphan branch (`a? ∉ owner`, buggy-variant only) | path unchanged — unreachable under lock |

### LoseRaceLive(a?) / Exit(a?)

| # | Partition | Expected |
|---|---|---|
| R1 | probe reads `slistening` (live owner) → concede | returns False, live socket untouched |
| R2 | lost racer exits, mutates nothing but own phase | no state change to winner |

### Reap(a?) / ReapDead(a?)

| # | Partition | Expected |
|---|---|---|
| K1 | live owner (`slistening`), PID file agrees | terminate via peer-pid, clear |
| K2 | live owner, no PID file | terminate via socket peer credential |
| K3 | live owner, divergent/stale PID file | signal socket owner, not the file value |
| K4 | live-but-silent owner | resolve owner, terminate (not unlink-only) |
| K5 | owner survives SIGKILL | raise |
| K6 | owner dies only on SIGKILL (async) | confirmed dead, no spurious raise |
| K7 | zombie owner (PID slot held, socket released) | socket authoritative → clear |
| K8 | clean exit between probe and peer read | re-check dead, clear, no raise |
| K9 | non-positive peer pid | refuse — never `os.kill(0)` |
| K10 | live socket, unresolvable owner | refuse — no PID-file fallback |
| K11 | dead owner (`≠ slistening`) | clear files, no kill |
| K12 | **cleanup runs under bind lock (`bindLock = ∅` guard)** | **must not unlink a concurrent binder's fresh socket** |

### Locks

| # | Partition | Expected |
|---|---|---|
| S1 | `AcquireSpawnLock` serialises concurrent `ensure` | exactly one spawn |
| S2 | `reap` holds spawn lock vs concurrent `ensure` | ensure blocks until release |
| S3 | reap→ensure gap: display raced in mid-gap is reused | one display |
| S4 | `AcquireBindLock` blocks a concurrent `setup` | second setup stalls until release |
| S5 | **spawn lock and bind lock held concurrently (different agents)** | **no deadlock — lock order spawn→bind** |

## 2. Coverage table

| Partition | Covering test | Status |
|---|---|---|
| P1 | `test_paths.py::TestIsRunning::test_no_socket_file` | COVERED |
| P2 | `test_live_server_answers`, `test_probe_distinguishes_accepting_from_ready` | COVERED |
| P3 | `test_bound_socket_without_handshake_is_alive`, `test_probe_silent_owner_is_fast_accepting` | COVERED |
| P4 | `test_stale_socket_no_listener`, `test_probe_refused_socket_is_dead` | COVERED |
| **P5** | — | **GAP-1** |
| P6 | `test_probe_connect_timeout_is_accepting_and_preserves_socket` | COVERED |
| P7 | `test_probe_connect_resource_error_is_accepting_and_preserves_socket` | COVERED |
| P8 | `test_probe_malformed_frame_is_accepting`, `test_probe_nonobject_payload_is_accepting`, `test_probe_recursion_error_reply_is_accepting` | COVERED |
| P9 | `test_removes_non_socket_file` (via `is_running`) | COVERED |
| P10 | `test_recycled_pid_is_not_alive` | COVERED |
| C1 | `TestCleanupStale::test_removes_dead_socket`, `test_rebinds_over_stale_socket` | COVERED |
| C2 | `test_removes_non_socket_file` | COVERED |
| C3 | `test_clear_dead_files_removes_broken_symlink` | COVERED |
| C4 | `test_preserves_live_socket` | COVERED |
| C5 | `test_preserves_accepting_but_silent_socket` | COVERED |
| C6 | `test_probe_connect_timeout...`, `test_probe_connect_resource_error...` (call `cleanup_stale`, assert `path.exists()`) | COVERED |
| C7 | `test_clear_dead_files_preserves_symlink_to_live_socket` | COVERED |
| **C8** | partial — `test_bind_lock_blocks_concurrent_setup` (lock held, but holder binds nothing) | **GAP-2** |
| B1 | `test_setup_creates_socket`, `test_returns_true_on_cold_bind` | COVERED |
| B2 | `test_rebinds_over_stale_socket` | COVERED |
| B3 | `test_returns_false_on_bind_race` | COVERED |
| B4 | `test_propagates_non_race_oserror` | COVERED |
| L1 | `test_returns_true_on_cold_bind` (asserts listening `server_sock`) | COVERED |
| L2 | — (buggy-variant only; unreachable under lock — correctly untested) | N/A |
| R1 | `test_returns_false_and_preserves_live_owner` | COVERED |
| R2 | `test_returns_false_and_preserves_live_owner` (winner fd/inode intact) | COVERED |
| K1 | `test_reap_live_terminates_owner` | COVERED |
| K2 | `test_reap_live_without_pid_uses_socket_owner` | COVERED |
| K3 | `test_reap_live_prefers_socket_owner_over_stale_pid` | COVERED |
| K4 | `test_reap_terminates_accepting_but_silent_owner` | COVERED |
| K5 | `test_reap_raises_when_owner_survives_termination` | COVERED |
| K6 | `test_reap_confirms_sigkill_death_no_spurious_raise` | COVERED |
| K7 | `test_reap_zombie_owner_confirmed_dead_via_socket` | COVERED |
| K8 | `test_reap_clean_exit_between_probes_is_not_an_error` | COVERED |
| K9 | `test_reap_refuses_non_positive_peer_pid` | COVERED |
| K10 | `test_reap_raises_when_owner_unresolved_no_pid_fallback` | COVERED |
| K11 | `test_reap_dead_clears_files_without_kill` | COVERED |
| **K12** | partial — `test_reap_holds_lock_against_concurrent_ensure` covers the SPAWN lock, not reap's bind-lock cleanup vs a binder | **GAP-4** |
| S1 | `test_concurrent_ensure_spawns_once` | COVERED |
| S2 | `test_reap_holds_lock_against_concurrent_ensure` | COVERED |
| S3 | `test_make_restart_ensure_reuses_display_spawned_in_reap_gap` | COVERED |
| S4 | `test_bind_lock_blocks_concurrent_setup` | COVERED |
| **S5** | — | **GAP-3** |

Multi-agent contention (Invariants 1 & 3) is additionally covered
probabilistically by `test_concurrent_setup_single_winner` (10 threads × 4
rounds). It is timing-dependent, so it does not deterministically force the
`sbound`-window interleaving — that is GAP-2.

## 3. Ranked gaps

### GAP-1 (HIGH) — the `sbound` DEAD-probe mechanism is untested

Partition P5. No test stands up a socket that is **bound, fd open, `listen`
not yet called** and asserts the probe reads DEAD. This premise — a
bound-but-not-listening socket refuses `connect`, so a probe reads it dead — is
the entire reason the bind lock exists. `test_returns_false_on_bind_race`
*monkeypatches* the probe to DEAD rather than exercising the real mechanism.

- Module: `tests/test_paths.py`, class `TestIsRunning`.
- Test: `test_bound_not_listening_socket_probes_dead`.
- Asserts: bind an `AF_UNIX` socket to the path, do **not** call `listen()`,
  keep the fd open; `DisplayPaths(path)._probe() is SocketLiveness.DEAD` and
  `is_running() is False`. (Close the fd only in teardown.)

### GAP-2 (HIGH) — no deterministic two-winner regression

Partition C8. The round-2 defect was: a concurrent cleanup unlinks a socket
another process has just bound but not yet listened on. The current defence is
the bind lock. `test_bind_lock_blocks_concurrent_setup` holds the lock but the
holder binds nothing, so it never asserts that a **freshly bound (not
listening) socket survives** a concurrent cleanup/setup. This is the exact
interleaving the model reproduces in the buggy variant.

- Module: `tests/test_socket_server.py`, class `TestSetupArbitration`.
- Test: `test_fresh_bind_survives_concurrent_setup_in_window`.
- Asserts: thread A takes `DisplayPaths(path).bind_lock()`, binds a socket to
  the path **without** `listen()`, and holds the lock; thread B calls
  `SocketServer.setup(path)` and blocks; while B is blocked, assert A's bound
  socket file is intact (same inode — capture `os.stat(path).st_ino` before and
  after) and `server_sock is None` for B; release the lock and join. This
  deterministically encodes "cleanup must never unlink a fresh bind."

### GAP-3 (MEDIUM) — two-lock deadlock-freedom is untested

Partition S5, Invariant 4. No test asserts the spawn lock and the bind lock can
be held **concurrently by different agents** without a cyclic wait. `ensure`
holds the spawn lock while the display it spawns takes the bind lock; the design
claim is that the fixed lock order (spawn-outer, bind-inner, never both by one
agent) makes deadlock impossible.

- Module: `tests/test_paths.py`, new class `TestLockOrdering`.
- Test: `test_spawn_and_bind_locks_coexist_without_deadlock`.
- Asserts: thread A holds `_spawn_lock()`, thread B holds `bind_lock()`
  simultaneously (both enter within a bounded barrier); each then acquires and
  releases the *other* lock in the spawn→bind order; both threads complete
  within a timeout (e.g. `join(timeout=5)` succeeds, `is_alive()` is False). A
  deadlock would hang the join.

### GAP-4 (MEDIUM) — reap's cleanup under the bind lock is untested

Partition K12. `reap` clears dead files via `_clear_dead_files_locked`, which
takes the **bind** lock so it cannot unlink a socket a concurrent binder just
created. The existing lock test (`test_reap_holds_lock_against_concurrent_ensure`)
exercises the **spawn** lock only.

- Module: `tests/test_paths.py`, class `TestReap`.
- Test: `test_reap_cleanup_holds_bind_lock_against_binder`.
- Asserts: hold `DisplayPaths(path).bind_lock()` in thread A (simulating a
  binder mid-window); in thread B call `reap()` on a dead-socket path; B's
  `_clear_dead_files_locked` must block on the bind lock and must not unlink
  while A holds it; on release, B proceeds. Assert no unlink occurred during the
  hold.

Gaps 1 and 2 are the merge-critical pair — they are the mechanism and the
regression for the exact defect `fix/lux-h29e-bind-race` addresses. Gaps 3 and
4 harden the two-lock discipline the model proves deadlock-free.
