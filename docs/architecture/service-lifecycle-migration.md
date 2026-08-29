# Service Lifecycle Migration: A Rename Is a Migration, Not a Hope

**Status:** design, unimplemented. Bead `lux-ehzy`, mission `m-2026-08-21-012`.
Implementation is a separate mission after operator ratification.

## 1. Problem Statement and Repro

`LaunchdBackend._remove_legacy_plists` (`src/punt_lux/_backend_launchd.py:187-204`)
cleans up the pre-`lux-5uc7` `com.punt-labs.lux` LaunchAgent when a hub install
runs under the renamed `com.punt-labs.luxd-hub` label. The cleanup call, line
201:

```python
launchctl.run(["launchctl", "unload", "-w", str(legacy)], verb="unload")
legacy.unlink(missing_ok=True)
```

`unload -w` is the **legacy** launchd API — the pre-`bootstrap`/`bootout`
subsystem addressed by plist path rather than by domain target
(`gui/<uid>/<label>`). Every other verb this backend issues —
`stop` (`_backend_launchd.py:105-118`, `bootout`), `start`
(`_backend_launchd.py:135-147`, `bootstrap`), `restart`
(`_backend_launchd.py:120-133`, `kickstart -k`) — already uses the modern
domain-based subsystem. Only `_remove_legacy_plists` and the self-upgrade path
inside `install()` (`_backend_launchd.py:66-80`, `unload -w`/`load -w`,
discussed in §5 alternative 6) still speak the legacy dialect.

**Why `unload -w` fails silently on a `bootstrap`-loaded service:** the two
launchd subsystems do not fully interoperate. A job registered via
`bootstrap` into the GUI domain is not reliably addressable by `unload`,
which expects to have loaded the job itself via the matching legacy `load`
call. When the domains mismatch, `unload -w <plist>` returns exit code 0
(no error) while the job stays registered in launchd's in-memory job table.
`launchctl.run` (`src/punt_lux/_launchctl.py:28-38`) only logs a warning on
**non-zero** exit — a zero exit here is indistinguishable from a real
success, so nothing fires. Line 202 then unconditionally unlinks the plist
file: the file that was the *only* on-disk evidence the LaunchAgent ever
existed is now gone, but the LaunchAgent itself is still alive in launchd's
memory and will be relaunched at every login.

**Live repro (operator's machine, 2026-08-21):** PID 14100, owned by the
pre-rename `com.punt-labs.lux` label, held port 8430 with 20 minutes of
uptime. Every `launchctl kickstart -k com.punt-labs.luxd-hub` spawned a new
`luxd` under the *new* label, which immediately failed `bind()` with
`EADDRINUSE` and exited — because the old process, still alive, held the
port. `lux hub restart` appeared broken; it was working correctly against
the new label, and the new process was dying on every single invocation.

**Why the existing tests didn't catch this:** `TestLegacyPlistCleanup` and
`TestSystemdLegacyUnitCleanup` (`tests/test_service.py:284-371`) patch
`subprocess.run` to unconditionally return `returncode = 0` regardless of
which command was issued. They assert the plist file is deleted — which it
was, even under the buggy code — and never assert *which* launchctl verb ran
or that the service was actually deregistered. A test suite that is blind to
the difference between `unload` and `bootout` will pass identically whether
the fix is present or absent. §7 designs the fixture that closes this gap.

**Operator's stance, verbatim (2026-08-21):** "A rename is a migration, not
a hope." The install step must actively cure the machine to the new state,
verify the cure, and abort loud if it cannot.

## 2. Proposed Primitive

### 2.1 Shape: a `LegacySweep` family, composed by `ServiceManager` — not a method on `ServiceBackend`

Two abstract methods could have been added to `ServiceBackend`
(`_backends.py:44-89`): `sweep_legacy() -> LegacySweepReport` and
`is_clean() -> bool`. §5.1 explains why this was rejected. The adopted shape
is a standalone class family:

```text
LegacySweep (Protocol, structural — see oo.md "Families share by protocol")
    sweep() -> LegacySweepReport      # mutating: cure to the clean state
    is_clean() -> bool                # non-mutating: verify only

LaunchdLegacySweep(spec: ServiceSpec)     # @final, __slots__
SystemdLegacySweep(spec: ServiceSpec)     # @final, __slots__
```

Each concrete class reads its target identifiers from `ServiceSpec` (§2.2),
never from a hardcoded string comparison. `ServiceManager.__new__`
(`service.py:63-73`) already dispatches `LaunchdBackend`/`SystemdBackend` by
platform; it gains a second dispatch alongside it:

```python
sweep_cls = LaunchdLegacySweep if detect_platform() == "macos" else SystemdLegacySweep
self._legacy_sweep = sweep_cls(cls._SPEC)
```

`LegacySweep` is a `Protocol`, not an `ABC` with shared implementation —
`LaunchdLegacySweep` and `SystemdLegacySweep` share no code (the launchd and
systemd command sets are unrelated) and each satisfies the contract
structurally, matching every existing platform split in this module
(`ServiceBackend` is the one exception, and it's an `ABC` because `install`,
`uninstall`, `stop`, `start`, `restart`, `is_active`, `config_path` are
seven methods with real cross-cutting call-graph expectations from
`ServiceManager`; `LegacySweep`'s two-method contract has no shared
implementation to inherit).

### 2.2 `ServiceSpec` gains the legacy identity as data

`ServiceSpec` (`_service_spec.py:22-35`) is a frozen dataclass; it already
carries `launchd_label` and `systemd_unit` as this service's *current*
platform identity. It gains two more fields for its *historical* identity:

```python
@dataclass(frozen=True, slots=True)
class ServiceSpec:
    ...
    legacy_launchd_labels: tuple[str, ...] = ()
    legacy_systemd_units: tuple[str, ...] = ()
    health_port: int | None = None  # see §4
```

`HUB_SPEC` sets `legacy_launchd_labels=("com.punt-labs.lux",)`,
`legacy_systemd_units=("lux",)`, `health_port=DEFAULT_HUB_PORT`. `DISPLAY_SPEC`
leaves all three at their empty/`None` defaults — the sweep and the port
guard both no-op naturally on an empty tuple or a `None` port, with no
`if spec.launchd_label != "com.punt-labs.luxd-hub": return` string
special-case anywhere (§5.2 rejects that shape, which is what
`_backend_launchd.py:196` does today).

A future rename train (the disk-binary rename `luxd` → `luxd-hub` the
operator has already flagged as separate scope) adds one label to one
tuple in `_service_spec.py`. No sweep class, no backend, and no call site
changes.

### 2.3 `LegacySweepReport` — a value type, not a bare bool

```python
@final
@dataclass(frozen=True, slots=True)
class LegacyServiceOutcome:
    """The sweep's result for one legacy identifier (a launchd label or systemd unit)."""

    identifier: str  # e.g. "com.punt-labs.lux" or "lux.service"
    was_present: bool  # registered/loaded before the sweep ran
    deregistered: bool  # the bootout/disable call reported success
    config_removed: bool  # the plist/unit file was deleted
    verified_clean: bool  # post-sweep is_clean() re-check passed for this identifier


@final
@dataclass(frozen=True, slots=True)
class LegacySweepReport:
    """The sweep's result across every legacy identifier for one service."""

    outcomes: tuple[LegacyServiceOutcome, ...]

    @property
    def all_clean(self) -> bool:
        return all(o.verified_clean for o in self.outcomes)

    def describe(self) -> str:
        """Render every non-clean outcome as an operator-facing repair line."""
```

`describe()` is the method `ServiceMigrationError` and `lux hub doctor` both
call to render the same text — one code path producing the diagnostic
message on both the CLI's mutating and non-mutating branches.

## 3. State Model

There is no state machine. `sweep()` is a single idempotent, unconditional
action: attempt the cure, verify it, report what happened. This is the
direct payoff of the State Pattern rejection in §5.1 — "clean" and
"has-legacy-registration" are not two behaviorally distinct modes the class
switches between; they are the two possible *outcomes* of one operation,
recorded as data (`LegacyServiceOutcome.verified_clean`) rather than
dispatched on as class identity.

**"Clean," precisely, per platform:**

- **launchd:** for every label in `spec.legacy_launchd_labels`,
  `launchctl print gui/<uid>/<label>` exits non-zero (service not found in
  the domain) **and** `~/Library/LaunchAgents/<label>.plist` does not exist
  on disk. Both conditions, not either — a lingering plist with no loaded
  service is not "clean" (a subsequent unrelated `load` could resurrect it),
  and a loaded service with no plist is not "clean" either (exactly the bug
  in §1: the file was already gone).
- **systemd:** for every unit in `spec.legacy_systemd_units`,
  `systemctl --user status <unit>.service` exits `4` (unit could not be
  found) **and** `~/.config/systemd/user/<unit>.service` does not exist on
  disk.

**`is_clean()` verifies without mutating** by running only the two read
commands above (`launchctl print` / `systemctl status`, plus a `Path.exists()`
check) and never `bootout`, `bootstrap`, `unlink`, or `write_config_atomic`.
It is safe to call from a read-only diagnostic (`lux hub doctor` with no
flags, §6) with zero side effects, and `sweep()` calls it twice internally:
once to skip the cure entirely when a label is already clean (idempotency —
running `sweep()` on an already-clean machine issues zero `launchctl`/
`systemctl` mutating calls), and once after the cure to populate
`verified_clean` per outcome.

## 4. Failure Semantics

Every failure in the legacy-cure path is **fatal** — no `|| warn`, no
"proceeding with load" fallthrough (the shape at `_backend_launchd.py:76-80`
today, discussed as its own finding in §5.6). Concretely:

**Identifier-loop semantics.** `sweep()` iterates every identifier in
`spec.legacy_launchd_labels` (or `legacy_systemd_units`) to completion —
it does **not** short-circuit and raise on the first failure. Each
identifier gets the full four-step treatment below independently, its
`LegacyServiceOutcome` is appended to the accumulating `LegacySweepReport`
regardless of whether that identifier ended clean or not, and only after
every identifier has been attempted does `sweep()` check
`report.all_clean` and raise once, with the complete report, if any
identifier failed. An operator whose machine accumulated cruft from two
rename trains sees both failures in one `lux hub doctor` or one failed
`lux hub install` — not the first failure, then a second cycle to
discover the next one after fixing it by hand.

**`sweep()`, per identifier:**

1. If `is_clean()` already holds for this identifier → no-op, record
   `was_present=False, deregistered=False, config_removed=False,
   verified_clean=True`. (Handles the common case: no legacy install ever
   existed.)
2. Otherwise, run the deregister command (`launchctl bootout` /
   `systemctl --user disable --now`). Record its exit status.
3. Re-run the read-only check. If it now reports clean, delete the config
   file (`unlink(missing_ok=True)`, per §4.1's concurrency note) and record
   `config_removed=True`. **The config file is only ever deleted after step
   3 confirms deregistration succeeded** — the exact ordering fix for the
   bug in §1, where the file was deleted unconditionally regardless of
   whether the unload actually worked. `config_removed=True` is set from
   the deletion call completing without raising, not from a subsequent
   `Path.exists()` re-check — the design relies on `unlink()`'s own Python
   semantics (it raises `OSError` on a real failure — permissions, disk
   error — and `missing_ok=True` only suppresses the specific
   already-gone case) rather than a second stat call to confirm the
   deletion. Any raised `OSError` other than "already gone" propagates
   uncaught out of `sweep()`, consistent with the fatal-by-default posture
   elsewhere in this design.
4. If step 3 still reports the identifier as registered — the deregister
   command lied about its exit code, or launchd/systemd genuinely refused —
   record `verified_clean=False` for this identifier's `LegacyServiceOutcome`
   and **move on to the next identifier**, per the loop semantics above; this
   step never raises by itself. The config file for a failed identifier is
   **left in place**, deliberately: an unreachable service with a config
   file on disk gives the operator something to `launchctl print` or
   `systemctl status` against when diagnosing; a deleted file with a
   still-live service (today's bug) gives them nothing.

Once every identifier has been attempted, `sweep()` checks
`report.all_clean`; if `False`, it raises `ServiceMigrationError` (new
exception, `_service_errors.py`) exactly once, carrying the complete
`LegacySweepReport.describe()` — every failed identifier's repair line, not
just the first. `ServiceManager.install()` propagates `ServiceMigrationError`
uncaught — `install()` aborts, `lux hub install` exits non-zero, and the
operator sees every failing identifier and its exact manual command in one
pass (`describe()` includes them all — see §6 for the rendered text). This
is fatal by construction: there is no code path in which `install()` can
complete while `all_clean` is `False`.

**Port conflict (§ design question f):** report and abort, never kill. A
foreign process bound to port 8430 has no verifiable identity — `PortGuard`
(below) can observe *that* something holds the port, but not *what* it is
beyond a pid and a listening socket. `LegacySweep`'s deregister calls are
safe to automate because they target a launchd label or systemd unit **this
codebase itself defined and registered** — the identity is ours. A port
number carries no such guarantee: an unrelated developer tool, a stale test
fixture, or literally any other process could be squatting on 8430, and
`kill`ing a pid identified only by "is listening on this port" is a blast
radius decision this design refuses to make unattended (PL-PP-3 defensive
coding at a non-boundary, applied in reverse — this is a boundary, and the
correct boundary behavior is to refuse and hand control back, not to guess).

```python
@final
class PortGuard:
    """Verify the hub's port is either free or already ours; never both nor foreign."""

    __slots__ = ("_spec",)

    def __new__(cls, spec: ServiceSpec) -> Self: ...

    def check(self) -> PortGuardResult:
        """Non-mutating: who (if anyone) holds spec.health_port."""

    def guard(self) -> None:
        """Raise PortConflictError unless check() positively confirms free-or-ours."""
```

```python
@final
@dataclass(frozen=True, slots=True)
class PortGuardResult:
    """The outcome of one port check: exactly one of these four states."""

    status: Literal["free", "ours", "foreign", "unknown"]
    pid: int | None  # the holding pid, when status is "foreign"; else None
```

`check()` shells out to `lsof -nP -iTCP:<port> -sTCP:LISTEN -t` (present by
default on macOS and on most Linux distributions; absent on some minimal
containers). If no pid holds the port, `status="free"`. If the holding pid
equals `pgrep_pid(spec.process_name)` (`_backends.py:20-41`, already
platform-agnostic and already used elsewhere in this module), `status="ours"`.
If a different pid holds it, `status="foreign"` with that pid recorded. If
`lsof` itself is not on `PATH` (`FileNotFoundError`), `check()` logs a
warning and returns `status="unknown"` rather than raising — `check()` is a
query, and a query that cannot determine the answer reports that fact as
data rather than refusing to return.

**`guard()` is fail-closed: only `"free"` and `"ours"` pass.** `"foreign"`
raises `PortConflictError` naming the pid and the inspection command
(`lsof -nP -iTCP:8430 -sTCP:LISTEN`), as before. `"unknown"` **also raises**
— a missing `lsof` means `guard()` cannot positively confirm the port is
either free or already ours, and proceeding on an unconfirmed assumption is
exactly the silent-pass-through this whole design exists to close out (§1).
`check()` (the read-only query used by `lux hub doctor` with no flags, §6)
surfaces `"unknown"` as an informational line for the operator to read;
`guard()` (the enforcement gate `install()` and `doctor --fix` call) never
treats "cannot verify" as "assume safe." `LegacySweep`'s own fatal check
(§3-§4) remains the primary guarantee for legacy-label state and is
unaffected either way — `PortGuard` is the second, independent check that
catches a foreign process with no plist/unit at all (e.g. one started by
hand), and it now holds the same fail-closed standard `LegacySweep` does.

`ServiceManager.install()` only invokes `PortGuard` when
`self._SPEC.health_port is not None` — `DISPLAY_SPEC` has no fixed port and
is unaffected.

### 4.1 Concurrency

Two concurrent invocations — `lux hub install` run twice by accident, or
`lux hub install` racing `lux hub doctor --fix` — are safe by construction
for everything except one narrow window addressed below, and that window
fails safe rather than corrupting state.

**`LegacySweep.sweep()`.** `launchctl bootout`/`systemctl --user disable
--now` are supervisor-side idempotent by the platform's own contract: a
second `bootout` issued against a label already torn down returns a
non-zero exit ("No such process" / target not found) rather than
corrupting anything, and `sweep()` never gates on that exit code directly
— it gates only on the post-deregister `is_clean()` re-check (§4 step 3),
which both racers evaluate independently against the real, converged
launchd/systemd state. Config-file deletion uses `unlink(missing_ok=True)`
(the same pattern already in use at `_backend_launchd.py:97,202` for the
non-racing case) specifically so that the racer who loses the delete race
— because the other one already removed the file — gets a silent no-op
rather than a `FileNotFoundError` crash. The one real hazard is a TOCTOU
window if both racers issue their deregister call within the same instant:
one racer's post-check could observe a transient "still registered" state
microseconds before the platform fully commits the teardown, and that
racer raises `ServiceMigrationError` for an identifier that is, in fact,
about to be clean. This is a **spurious fatal failure, not an unsafe
state** — it can never produce the ordering violation this design exists
to prevent (a deleted config file with a still-live service), because each
racer only deletes after its *own* re-check passes. A spurious raise
self-heals: the operator (or an automated retry) re-runs `lux hub install`
or `lux hub doctor --fix` and the second pass observes the now-fully-settled
clean state. Given the failure mode is "abort and retry converges," not
"silent corruption," and concurrent `lux hub install` invocations are an
unusual operator action rather than routine automation, this design does
not add a file lock. `PortGuard.check()`/`.guard()` are pure reads (`lsof`,
`pgrep`) with no mutation and no race hazard at all. Concurrent plist/unit
**content** writes during `install()`'s own rewrite step are handled by the
existing `write_config_atomic` (atomic rename) — unrelated to this design
and unaffected by it.

## 5. Rejected Alternatives

### 5.1 State Pattern for legacy/clean states (PY-DP-3)

Considered representing "has legacy registration" / "clean" as two states
with distinct transition methods, per PY-DP-3's trigger ("a class that
behaves differently depending on internal state, with explicit transition
methods"). Rejected: the two conditions are not behaviorally distinct enough
to justify the machinery. `sweep()` does exactly the same sequence of
operations regardless of which state it starts in — check, maybe cure, maybe
raise — the "state" only ever changes what `sweep()` reports, never what it
*does*. A single `sweep()` that runs unconditionally and is idempotent by
construction (§3) is simpler, has no transition graph to get wrong, and
matches the actual failure mode this design closes: a state machine adds a
place to encode "assume clean, skip the check" as a valid transition, which
is precisely the optimism the operator's ruling forbids.

### 5.2 Legacy identity as a per-backend constant vs. a per-`ServiceSpec` attribute

Considered hardcoding the legacy label/unit name as a class-level constant
inside `LaunchdLegacySweep`/`SystemdLegacySweep`, mirroring how
`_backend_launchd.py:196` today special-cases
`if self._spec.launchd_label != "com.punt-labs.luxd-hub": return`. Rejected
in favor of the `ServiceSpec` fields in §2.2, because:

- The legacy name is intrinsic to what a **service** is (its own naming
  history), not to how a given **platform** supervises it — the same
  reasoning that already put `launchd_label` and `systemd_unit` on
  `ServiceSpec` rather than inside the backend classes.
- A string-equality special case inside the sweep class is exactly the kind
  of hardcoded backend logic PY-IC-7 (Open-Closed) flags: adding the next
  legacy label means editing sweep-class logic. A tuple field means editing
  one line of data in `_service_spec.py`, with `DISPLAY_SPEC`'s empty tuple
  requiring no special case at all — it is data that happens to be empty,
  not a branch that happens to `return`.
- It generalizes for free to the disk-binary rename train the operator has
  already scoped as a follow-on: append one label, one unit name, zero code.

### 5.3 `lux hub doctor` as a `lux hub install` alias vs. a dedicated command

Considered telling operators to simply re-run `lux hub install` to repair a
broken state, since `install()` already runs the sweep unconditionally.
Rejected: `install()` also rewrites the plist/unit file and reloads/restarts
the *current* service (`_backend_launchd.py:82-88`,
`_backend_systemd.py:56-63`) — more mutation than a repair-only operation
needs, and it offers no read-only mode. An operator diagnosing "is my
machine clean" before deciding to act needs a query that touches nothing;
`install()` cannot be that query. §6 adopts a dedicated `doctor` command
with distinct check-only and `--fix` modes, both calling the identical
`LegacySweep`/`PortGuard` objects `install()` itself uses (§2.1) — same code
path, different entry points, per the mission's explicit constraint.

### 5.4 `sweep()`/`is_clean()` as methods on `ServiceBackend` vs. a separate class

Considered adding `sweep_legacy()` and `is_clean()` directly to the existing
`ServiceBackend` ABC (`_backends.py:44-89`) alongside `install`/`uninstall`/
`stop`/`start`/`restart`. Rejected on cohesion grounds (PL-CO-1/PL-CO-2): a
`ServiceBackend`'s five lifecycle methods all read `self._spec.launchd_label`
(or `.systemd_unit`) and `self._plist_path` (or `._unit_path`) — one cluster
of shared instance state. A sweep method reads
`self._spec.legacy_launchd_labels` and iterates plist paths derived from
*other* labels entirely — a second, disjoint cluster. Bolting it onto
`ServiceBackend` would raise that class's LCOM (fraction of method pairs
sharing no state) past the PL-CO-1 `0.8` ceiling and merge two
responsibilities — supervise the current service; repair a historical one —
into one class, the exact PL-CO-2 "more than two disjoint method clusters"
smell. A dedicated `LegacySweep` family (§2.1), composed by `ServiceManager`
the same way `ServiceBackend` already is, keeps each class's methods
touching one cluster of state.

### 5.5 Automated `kill` on port conflict vs. report-and-abort

Covered in §4: rejected because a pid identified only by "holds port 8430"
carries no verifiable ownership, and killing a process on that evidence
alone is an unacceptable blast radius for an install-time sweep to take
unattended.

### 5.6 REQUIRED implementation scope: `install()`'s own upgrade path still uses `unload -w`/`load -w`

`LaunchdBackend.install()` (`_backend_launchd.py:66-88`) unloads and
reloads the **current** label — not a legacy one — using the same legacy
`unload -w`/`load -w` pair this design replaces for the legacy-cleanup path,
and it explicitly tolerates a non-zero unload with a warning-and-continue
(`_backend_launchd.py:76-80`) before proceeding to `load -w` anyway. This is
the identical anti-pattern (legacy API, silent-swallow-on-failure) applied
to the service's *own* label during an in-place binary-path upgrade, rather
than to a renamed predecessor. It did not cause the operator's 2026-08-21
incident (that was the legacy-label path), but it is the same class of bug,
sitting nine lines above the one that did, and it is a matter of when — not
whether — the next in-place upgrade hits the identical silent no-op.

This is not an optional cleanup deferred to the leader's judgment. It is a
**hard acceptance criterion of the implementation mission**:
`_backend_launchd.py:66-88` must be rewritten to use `bootout` + `is_clean()`
verification, fatal on failure, no continue-on-failure fallthrough — the
exact primitive and the exact discipline §2-§4 define, applied to the
current label as a one-identifier sweep against itself rather than to a
historical one. The primitive already does what this call site needs;
shipping `LegacySweep` while leaving `_backend_launchd.py:66-88` on the
legacy API is shipping half the fix for one instance of the bug class and
leaving the other instance live in the same file, in the same method,
nine lines away. The implementation mission's write-set includes both
call sites; its acceptance criteria include a test proving
`_backend_launchd.py:66-88` no longer issues `launchctl unload` or
`launchctl load`, mirroring §7.2's verb-assertion test for the
legacy-cleanup path.

## 6. `lux hub doctor` Command Surface

New subcommand in `src/punt_lux/cli/hub.py`, alongside `install`/`uninstall`/
`start`/`stop`/`restart`/`status` (`cli/hub.py:33-111`).

```text
lux hub doctor              # read-only: is_clean() + PortGuard.check()
lux hub doctor --fix        # mutating: sweep() + PortGuard.guard()
```

No other arguments — `doctor` diagnoses the hub only (`DISPLAY_SPEC` has no
legacy identifiers and no fixed port; there is nothing for it to check).

**Output, clean:**

```text
luxd hub: clean
  legacy labels: none registered
  port 8430: owned by luxd-hub (pid 41213)
```

**Output, dirty, without `--fix`:**

```text
luxd hub: DIRTY
  legacy label com.punt-labs.lux: still registered (launchctl print found it)
    fix: launchctl bootout gui/501/com.punt-labs.lux
  port 8430: held by pid 14100 (not luxd-hub)
    inspect: lsof -nP -iTCP:8430 -sTCP:LISTEN

Run 'lux hub doctor --fix' to repair automatically, or apply the commands
above by hand.
```

Every "fix:" and "inspect:" line comes from `LegacySweepReport.describe()`
(§2.3) and `PortGuardResult`'s equivalent — the same text `ServiceMigrationError`
carries when `install()` aborts, so the manual-recovery instructions an
operator sees from `doctor` and from a failed `install` are always
identical.

**Output, dirty, with `--fix`, repair succeeds:**

```text
Repairing...
  removed legacy label com.punt-labs.lux
luxd hub: clean
  legacy labels: none registered
  port 8430: owned by luxd-hub (pid 41213)
```

**Output, dirty, with `--fix`, repair fails** (deregister ran but
verification still finds it registered — the fatal case in §4):

```text
Repairing...
  legacy label com.punt-labs.lux: bootout ran (rc=0) but is still registered
luxd hub: DIRTY — automatic repair failed
  fix manually: launchctl bootout gui/501/com.punt-labs.lux
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | Clean, or `--fix` ran and reached a clean state |
| 1 | Dirty, `--fix` not passed (diagnostic only, nothing was changed) |
| 2 | `--fix` passed but the machine is still not clean after repair (fatal — matches `ServiceMigrationError`) |

`doctor` without `--fix` calls `LegacySweep.is_clean()` and
`PortGuard.check()` only — zero mutating calls, safe to run repeatedly and
safe to run in CI or a health-check script. `doctor --fix` calls
`LegacySweep.sweep()` and `PortGuard.guard()` — the identical objects and
methods `ServiceManager.install()` invokes (§2.1, §4) — so a repair via
`doctor --fix` and a repair via a fresh `lux hub install` cure the same
machine state through the same code, never two implementations that could
drift.

## 7. Test Fixture Design

### 7.1 Why the current fixtures are insufficient

`TestLegacyPlistCleanup` and `TestSystemdLegacyUnitCleanup`
(`tests/test_service.py:284-371`) patch `subprocess.run` to return
`returncode = 0` unconditionally and assert only that the plist/unit file is
gone afterward. They would pass identically against the buggy `unload -w`
code and the fixed `bootout` code — they never inspect *which* command ran,
and they never touch a real launchd/systemd domain, so they cannot detect
the cross-domain no-op that caused the incident. Both classes are kept and
extended (§7.2) but a real fixture (§7.3) is required to close the gap they
leave.

### 7.2 Unit-level regression tests (tier 1, `make test`, mocked)

Two new tests in `tests/test_service.py`, alongside the existing
`TestLegacyPlistCleanup`/`TestSystemdLegacyUnitCleanup` classes:

- **Verb assertion.** Patch `launchctl.run` (the actual call site, per the
  existing pattern at `test_service.py:427` — never the module-level
  `subprocess` object) and assert the sweep's call args are
  `["launchctl", "bootout", ...]` and `["launchctl", "print", ...]` — never
  `["launchctl", "unload", ...]`. Grep-provable: `"unload"` must not appear
  in any argument list the sweep issues.
- **Fidelity control — the exact bug.** Mock `launchctl print` to report
  "found" (exit 0) both before *and after* `bootout` runs (simulating a
  supervisor call that silently failed to deregister — the exact behavior
  the operator hit). Assert `LegacySweep.sweep()` raises
  `ServiceMigrationError`, and assert the plist file **still exists**
  afterward — proving the ordering fix in §4 step 3: no file deletion
  without confirmed deregistration. Without this test, a regression back to
  §1's bug would pass every other test in the suite, exactly as it did the
  first time.

### 7.3 Fidelity-control integration test (tier 3, `@pytest.mark.e2e`, real launchd/systemd)

Simulating "operator upgrading from a `bootstrap`-loaded pre-rename install"
requires a real `bootstrap` call — no mock can reproduce the cross-domain
no-op, because the no-op is a property of the real launchd/systemd
subsystem, not of this codebase's logic. New test module
`tests/e2e/test_legacy_sweep.py`:

**macOS (`@pytest.mark.skipif(platform.system() != "Darwin")`):**

1. Generate a scratch label: `com.punt-labs.lux-test-{os.getpid()}-{uuid4().hex[:8]}`
   — collision-safe under parallel test runs.
2. Write a minimal plist to `~/Library/LaunchAgents/<scratch label>.plist`
   with `ProgramArguments = ["/bin/sleep", "300"]`, `RunAtLoad = true`,
   `KeepAlive = false` (no respawn loop to fight during teardown).
3. `launchctl bootstrap gui/$(id -u) <scratch plist>` — this is the **real
   modern-domain registration**, not `load`, reproducing exactly the
   registration path every current `lux hub install` uses and the one the
   pre-rename installer used.
4. Assert `launchctl print gui/$(id -u)/<scratch label>` exits 0 (loaded) —
   confirms setup succeeded before testing the sweep against it.
5. Construct `LaunchdLegacySweep` with a throwaway `ServiceSpec` whose
   `legacy_launchd_labels = (scratch_label,)`.
6. Run `sweep()`. Assert `report.all_clean` is `True`.
7. Assert `launchctl print gui/$(id -u)/<scratch label>` now exits non-zero
   (not found) — the fidelity check this design exists to prove: a
   `bootstrap`-registered service is actually gone after the sweep, not just
   file-absent.
8. Teardown, in a `finally` / pytest fixture yield, unconditional even on
   assertion failure: `launchctl bootout gui/$(id -u)/<scratch label>` (best
   effort, ignore failure — it may already be gone) and delete the plist if
   it still exists. A failed test run must never leave a zombie scratch
   LaunchAgent on the dev machine or CI runner.

**Linux (`@pytest.mark.skipif(platform.system() != "Linux")`):**

Same shape against `systemctl --user`: write a scratch unit
`lux-test-{pid}-{hex}.service` with `ExecStart=/bin/sleep 300`, `systemctl
--user daemon-reload`, `systemctl --user enable --now <unit>`, confirm
`systemctl --user status <unit>` exits 0/3 (found), run `SystemdLegacySweep`,
assert `sweep()` reports clean and `systemctl --user status <unit>` now
exits `4` (unit could not be found). Teardown: `systemctl --user disable
--now <unit>` best-effort, delete the unit file, `daemon-reload`.

Both tests are `@pytest.mark.e2e` — real process-lifecycle tests against the
real supervisor, exactly tier 3 in `tests/CLAUDE.md`'s pyramid ("CLI args,
process lifecycle, wire protocol end-to-end"), not part of the default
`make test` gate, run via `make test-e2e`.

## 8. Migration Path for Already-Broken Installs

No separate one-time migration tool is needed, and no manual `launchctl
bootout` step needs to be documented as a required action, because the fix
does not change *where* the sweep runs — `ServiceManager.install()` already
calls it unconditionally on every invocation, and `lux hub install` is
already idempotent by design (install.sh's comment at line 105 states this
directly, and `install.sh:111` calls it on every install/upgrade run). The
only change is the sweep's *internal mechanism* (§2-§4). Once an operator
upgrades to a `punt-lux` release containing this fix:

```sh
uv tool install --force punt-lux[display]==<fixed-version>
lux hub install
```

`lux hub install`'s existing unconditional sweep call now runs the corrected
`LegacySweep.sweep()`, which finds the zombie `com.punt-labs.lux`
registration, `bootout`s it, verifies via `launchctl print`, and only then
deletes the (already-absent, in the operator's case) plist file. No
operator action beyond the ordinary upgrade-and-reinstall sequence they
would run anyway is required.

The bead's documented stopgap (`launchctl bootout
gui/$(id -u)/com.punt-labs.lux; rm ~/Library/LaunchAgents/com.punt-labs.lux.plist`)
remains valid for anyone who cannot upgrade immediately, but is no longer a
required step once the fixed binary is installed — `lux hub doctor` (§6)
becomes the documented way to confirm the machine reached a clean state
after upgrading, replacing "run this shell command and hope" with a command
whose output states unambiguously whether the cure succeeded.

## Related Documents

- Bead `lux-ehzy` — the incident and its immediate fix scope.
- `src/punt_lux/service.py`, `_backend_launchd.py`, `_backend_systemd.py`,
  `_backends.py`, `_service_spec.py`, `_launchctl.py` — the current
  implementation this design extends.
- `docs/architecture/target/target.md` — unrelated to this design; service
  lifecycle is outside the Hub/Display protocol boundary.
