# Binary Rename Migration: Curing a Stale `~/.local/bin` Shim

**Status:** design, unimplemented. Bead `lux-j169`, mission `m-2026-08-22-001`.
Implementation is a separate mission after operator ratification.

This document extends `docs/architecture/service-lifecycle-migration.md`
(bead `lux-ehzy`, implemented in `_legacy_sweep.py` /
`_legacy_sweep_launchd.py` / `_legacy_sweep_systemd.py`) to a second
rename-train subject: the disk binary a `uv tool install` writes into
`~/.local/bin`, as distinct from the launchd/systemd registration the
`LegacySweep` family already cures. Sections below cite the shipped
`LegacySweep` design by file:line throughout and are explicit about where
this design reuses its shape and where it diverges.

## 1. Problem Statement and Repro

`pyproject.toml:72-75` declares three console scripts:

```toml
[project.scripts]
lux = "punt_lux.__main__:app"
luxd = "punt_lux.luxd:main"
lux-beads = "punt_lux.applets.beads:app"
```

`HUB_SPEC` (`_service_spec.py:69-82`) already renamed the *process* to
`luxd-hub` (`process_name="luxd-hub"`, set via `setproctitle` — see
`pyproject.toml:38-42`'s comment) and the *supervisor identity* to
`com.punt-labs.luxd-hub` / `luxd-hub` (`launchd_label`, `systemd_unit`).
`binary_name` still reads `"luxd"` (`_service_spec.py:74`) — the disk
artifact never followed the rename. `resolve_exec_args()`
(`_service_spec.py:42-58`) resolves `~/.local/bin/luxd`, and every `uv tool
install` reports:

```text
Installed 3 executables: lux, lux-beads, luxd
```

against a process the operator sees in `ps auxw` as `luxd-hub`. The
operator caught this live via `uv tool install` output next to `ps auxw |
grep lux`.

**Live repro, this machine (2026-08-22), confirmed by direct inspection —
not assumed:**

```text
$ ls -la ~/.local/bin/luxd
lrwxr-xr-x  1 jfreeman  staff  55 Aug 22 07:57 /Users/jfreeman/.local/bin/luxd@ -> /Users/jfreeman/.local/share/uv/tools/punt-lux/bin/luxd

$ readlink -f ~/.local/bin/luxd
/Users/jfreeman/.local/share/uv/tools/punt-lux/bin/luxd

$ head -c 200 ~/.local/share/uv/tools/punt-lux/bin/luxd
#!/Users/jfreeman/.local/share/uv/tools/punt-lux/bin/python3
# -*- coding: utf-8 -*-
import sys
from punt_lux.luxd import main
...

$ cat ~/.local/share/uv/tools/punt-lux/uv-receipt.toml
[tool]
requirements = [{ name = "punt-lux", extras = ["display"], path = "..." }]
entrypoints = [
    { name = "lux", install-path = "/Users/jfreeman/.local/bin/lux" },
    { name = "lux-beads", install-path = "/Users/jfreeman/.local/bin/lux-beads" },
    { name = "luxd", install-path = "/Users/jfreeman/.local/bin/luxd" },
]

$ uv tool dir
/Users/jfreeman/.local/share/uv/tools
```

Three facts this design relies on, all verified above rather than assumed:

1. **`~/.local/bin/luxd` is a real symlink** (`lrwxr-xr-x`, `@` suffix,
   `readlink -f` resolves it) — one hop, `~/.local/bin/luxd →
   ~/.local/share/uv/tools/punt-lux/bin/luxd`. The comment at
   `_service_spec.py:45` ("the uv-tool install symlink") is accurate for
   the current uv version on this platform.
2. **The target under `.../tools/punt-lux/bin/` is itself a regular file**
   — a small generated Python launcher with a shebang pointing at the
   tool's private venv interpreter and a hardcoded `from
   punt_lux.luxd import main`.
3. **`uv tool dir` is the authoritative source for the tools root**, not a
   hardcoded `~/.local/share/uv/tools` path literal — it respects
   `UV_TOOL_DIR` overrides and any future default change. §2.4 uses this
   command, not a string literal, to build the ownership check.

**Why this is the same rename-train hazard `LegacySweep` closed, and why
the fix is not automatic:** `uv tool install --force` reconciles the
*currently declared* `[project.scripts]` entries against the receipt
(`uv-receipt.toml`'s `entrypoints` list). When `pyproject.toml`'s `luxd =`
key is renamed to `luxd-hub =`, the next `uv tool install --force` writes
`~/.local/bin/luxd-hub` and updates the receipt to list `luxd-hub` instead
of `luxd` — but it has no reason to touch a file it no longer manages
under the old name. `~/.local/bin/luxd` is not removed. It keeps pointing
at `~/.local/share/uv/tools/punt-lux/bin/luxd`, a file whose *contents*
(the shebang, the `import` line) belong to whatever version of
`punt_lux.luxd:main` was last installed — potentially the fixed, renamed
version, since the underlying venv is shared and reinstalled in place, but
addressable only under a name (`luxd`) that documentation, muscle memory,
and this design's own `HUB_SPEC.legacy_binary_names` (§3) will no longer
recognize as current. An operator who runs bare `luxd` after the rename
either gets a working-but-undocumented alias (confusing: `uv tool install`
told them it's called `luxd-hub` now) or, if a future uv release changes
its reconciliation behavior to prune orphaned shims from the *shared* venv
`bin/` directory while leaving the *top-level* `~/.local/bin/luxd` symlink
dangling, gets a broken command with no explanation. Neither outcome is
"cured, verified, reported" — both are "hope the old name quietly rots."

**Operator's stance, restated from `service-lifecycle-migration.md` §1 and
unchanged for this second rename train:** "A rename is a migration, not a
hope." `lux hub install` must actively remove the artifact left by the old
name, verify it is gone, and abort loud if it cannot — but only after
confirming the artifact is genuinely ours to remove (§6).

## 2. Proposed Primitive

### 2.1 Decision: a distinct sibling primitive, not a `LegacySweep` subtype

The mission asks this directly: extend `LegacySweep`
(`_legacy_sweep.py:62-88`) to a `DiskBinaryLegacySweep`, or propose
something else. **This design proposes a distinct but parallel family** —
`BinarySweep` (Protocol) and `DiskBinaryLegacySweep` (`@final`
implementation) — built on the same shape `LegacySweep` established
(`ServiceSpec`-carried identity, cure-verify-report, fatal-on-failure, one
class composed by `ServiceManager` alongside the existing two), but **not**
literally implementing the `LegacySweep` Protocol. Two reasons, both
substantive rather than stylistic:

**1. The two-step ordering hazard `LegacySweep` exists to prevent has no
analogue here.** `service-lifecycle-migration.md` §1 diagnoses a specific
failure: a launchd/systemd *registration* can outlive its *config file* —
`launchctl print` still finds the job in the supervisor's in-memory table
after the plist is deleted, because `unload`/`load` and
`bootstrap`/`bootout` are two different subsystems that don't fully
interoperate. That is why `LegacyServiceOutcome`
(`_legacy_sweep.py:20-30`) carries **two** separate booleans —
`deregistered` and `config_removed` — and why `sweep()`'s cure order is
strict: deregister, re-verify, *only then* delete the file
(`_legacy_sweep_launchd.py:77-92`, comment at lines 79-82). A disk symlink
has no such split. There is no daemon holding a "registration" for
`~/.local/bin/luxd` independent of the directory entry itself —
`Path.exists()` is the entire state, with no second subsystem to query
separately and no window where the file is gone but the "registration"
lingers. Force-fitting `LegacyServiceOutcome`'s vocabulary onto this
primitive means either faking `deregistered=True` as a permanent no-op
(a report field asserting something never happened) or repurposing the
field's meaning for this one report type — degrading the shared,
already-shipped `describe()` text both `ServiceMigrationError` and `lux
hub doctor` render today (`service-lifecycle-migration.md` §6, §2.3).

**2. The actual hazard for a disk binary is identity, not ordering** — and
`LegacySweep` has no field for it. Deleting the wrong `launchctl` label is
not a live risk: `spec.legacy_launchd_labels`
(`_service_spec.py:36`) names labels *this codebase itself registered*
under `com.punt-labs.*` — there is no ambiguity about who owns
`com.punt-labs.lux`. `~/.local/bin/luxd` carries no such built-in
namespace. Any operator could have a **hand-installed script** named
`luxd` on their `PATH` — a personal alias, a different tool, a leftover
from an unrelated project — and mission input (g) explicitly calls this
out: "safety (don't nuke a real user script that happens to share the
name)." `LegacySweep`'s contract has nothing resembling this check because
it has never needed one; a primitive for disk binaries must add it as a
first-class step, not a bolt-on (§2.4, §6).

Given (1) the outcome vocabulary is wrong-shaped and (2) the actual safety
invariant is different in kind, this is Alternative 5.4's reasoning
(`service-lifecycle-migration.md` §5.4, "cohesion grounds ... a second,
disjoint cluster") applied one level up: not *within* one class, but
*between* two report shapes that would otherwise be forced to share a
type that means something different for each. A distinct `BinarySweep`
family keeps each report's fields honest about what actually happened.

**What genuinely carries over, unchanged:** the family shape
(`Protocol`, composed by `ServiceManager`, structural not inheritance —
`oo.md` "Families share by protocol, not base class"), the
`ServiceSpec`-as-data placement for the legacy identifier (§3, directly
reusing `service-lifecycle-migration.md` §5.2's reasoning), the
cure/verify/report method triad (`sweep`/`is_clean`/`diagnose`), the
fatal-unconditionally-on-failure posture (§5), and reuse of the existing
`ServiceMigrationError` exception type (§5) — the *error class* is the
same ("a rename train left cruft"); only the *outcome shape describing
what was found and done* differs.

### 2.2 No platform dispatch — one class, not two

`LegacySweep` needed `LaunchdLegacySweep`/`SystemdLegacySweep`
(`_platform_dispatch.py:46-53`) because launchd and systemd are genuinely
different subsystems with different commands. `~/.local/bin` and `uv tool
install`'s layout are **not** platform-specific — `uv tool dir` resolves
to `~/.local/share/uv/tools` (XDG-style default) on both macOS and Linux,
and the shim format (a symlink from `~/.local/bin/<name>` into
`<tool_dir>/<package>/bin/<name>`) is uv's own behavior, independent of
the host OS. `DiskBinaryLegacySweep` is therefore a single `@final` class
with no macOS/Linux split, and `_platform_dispatch.py`'s
`PlatformClasses` NamedTuple (`_platform_dispatch.py:39-43`) is
**unaffected** — this primitive is composed directly in
`ServiceManager.__new__`, not routed through `platform_classes()`.

### 2.3 Shape

```text
BinarySweep (Protocol, structural — see oo.md "Families share by protocol")
    sweep() -> BinarySweepReport      # mutating: cure to the clean state
    is_clean() -> bool                # non-mutating: verify only
    diagnose() -> BinarySweepReport   # non-mutating: full report, zero side effects

DiskBinaryLegacySweep(spec: ServiceSpec)     # @final, __slots__
```

```python
@final
@dataclass(frozen=True, slots=True)
class DiskBinaryOutcome:
    """The sweep's result for one legacy disk-binary name."""

    binary_name: str        # e.g. "luxd"
    path: str                # str(Path.home() / ".local" / "bin" / binary_name)
    was_present: bool        # the path existed before sweep() ran
    ownership_verified: bool  # resolved target is inside this package's uv-tool dir
    removed: bool             # unlink() was attempted and did not raise
    verified_clean: bool      # post-attempt Path.exists() is False
    fix_command: str          # "rm <path>" -- valid ONLY when ownership_verified

    def describe(self) -> str:
        """Operator-facing repair line, or "" when already clean.

        When ``ownership_verified`` is False, the rendered text is a
        refusal, not a fix instruction -- see §6.
        """


@final
@dataclass(frozen=True, slots=True)
class BinarySweepReport:
    """The sweep's result across every legacy binary name for one service."""

    outcomes: tuple[DiskBinaryOutcome, ...]

    @property
    def all_clean(self) -> bool:
        return all(o.verified_clean for o in self.outcomes)

    def describe(self) -> str:
        """Render every non-clean outcome as an operator-facing line."""
```

```python
@runtime_checkable
class BinarySweep(Protocol):
    """Cure and verify a service's legacy uv-tool-installed disk binaries."""

    def sweep(self) -> BinarySweepReport: ...
    def is_clean(self) -> bool: ...
    def diagnose(self) -> BinarySweepReport: ...


@final
class DiskBinaryLegacySweep:
    """Remove uv-tool shims left behind by a `[project.scripts]` rename."""

    __slots__ = ("_bin_dir", "_spec", "_tool_root")
    _bin_dir: Path
    _spec: ServiceSpec
    _tool_root: Path | None  # None only if `uv tool dir` could not run -- see §2.4

    def __new__(cls, spec: ServiceSpec) -> Self: ...

    def is_clean(self) -> bool: ...
    def diagnose(self) -> BinarySweepReport: ...
    def sweep(self) -> BinarySweepReport: ...

    def _diagnose_one(self, name: str) -> DiskBinaryOutcome: ...
    def _sweep_one(self, name: str) -> DiskBinaryOutcome: ...
    def _resolve_tool_root(self) -> Path | None:
        """Shell out to `uv tool dir` once; cache the result on the instance."""
    def _is_ours(self, path: Path) -> bool:
        """True iff `path` ultimately resolves under this package's tool dir."""
```

New module: `src/punt_lux/_binary_sweep.py` (value types + Protocol,
mirroring `_legacy_sweep.py`'s role) and
`src/punt_lux/_binary_sweep_disk.py` (the concrete class, mirroring
`_legacy_sweep_launchd.py`'s role as the one-and-only implementation —
named `_disk` rather than `_launchd`/`_systemd` because there is exactly
one implementation, not a platform pair; a `_platform`-suffixed name would
imply a sibling that will never exist).

### 2.4 Ownership verification — the mechanism, grounded in the real shim format (§1)

`_is_ours(path)` answers "is this uv's shim for *this* package," not "does
a file exist at this path." Built from what §1 observed directly, not
assumed:

1. **Resolve the tools root via `uv tool dir`, not a hardcoded path —
   and resolve it symmetrically with the target.** `_resolve_tool_root()`
   runs `uv tool dir` once per `DiskBinaryLegacySweep` instance (mirroring
   `PortGuard.check()`'s `lsof` pattern, `service-lifecycle-migration.md`
   §4 — shell out to the authoritative tool rather than reimplement its
   logic) and caches `Path(stdout.strip()).resolve() / "punt-lux"` as
   `self._tool_root`. The `.resolve()` call is required, not cosmetic:
   point 2 below resolves `target` through `Path.resolve()`, which
   canonicalizes symlinked mount points (on macOS, `/Users/...` is itself
   commonly a symlink to `/System/Volumes/Data/Users/...`); comparing an
   unresolved `_tool_root` against a resolved `target` would compare two
   different spellings of the same path and produce a false refusal on
   any machine where `uv tool dir`'s printed path and the shim's real
   location disagree only in this cosmetic sense. Both sides of the
   comparison in point 3 are resolved the same way, or neither
   comparison is trustworthy. If `uv` is not on `PATH`
   (`FileNotFoundError`), `_tool_root` is `None` and every subsequent
   `_is_ours()` call returns `False` — **absence of the verification tool
   means "cannot verify," which means "do not remove"** (the same
   fail-closed posture `PortGuard.guard()` takes for `status="unknown"`,
   `service-lifecycle-migration.md` §4 lines 308-313). A `_tool_root` of
   `None` fails closed; it is never a safety hazard, only a reliability
   one (an avoidable refusal) — see §4.5 for why concurrent access to this
   per-instance state introduces no additional risk.
2. **Follow whichever shim shape is actually on disk**, because §1's
   inspection shows two hops (`~/.local/bin/luxd` → symlink →
   `<tool_root>/punt-lux/bin/luxd`, itself a regular file with a shebang)
   and a future uv version could collapse this to one hop or change the
   shim format entirely:
   - If `path.is_symlink()`: `target = path.resolve()`.
   - Else, if `path.is_file()`: read the first line; if it starts with
     `#!`, parse the interpreter path after it as `target`. (This handles
     the case, not observed on this machine today but plausible on other
     uv versions/platforms, where `~/.local/bin/<name>` is itself the
     generated shim rather than a symlink to one.)
   - Otherwise (neither a symlink nor a text file with a recognizable
     shebang — a directory, a binary executable, a broken symlink with no
     resolvable target): `target = None`.
3. **Ownership verified iff `target` is not `None` and
   `target.is_relative_to(self._tool_root)`.** This is a path-component
   containment check (`Path.is_relative_to`, stdlib since 3.9 — the
   project already targets 3.13+), **not** a raw string prefix
   comparison. `str.startswith()` was the first shape considered and is
   rejected here as unsafe: `self._tool_root` is
   `<uv_tool_dir>/punt-lux`, and a *sibling* tool directory whose name
   merely starts with the same characters —
   `<uv_tool_dir>/punt-lux-devtools/bin/luxd`, a real, differently-owned
   uv tool an operator could plausibly have installed — satisfies
   `str(target).startswith(str(self._tool_root))` (the string
   `".../punt-lux-devtools/bin/luxd"` does start with `".../punt-lux"`)
   while being a completely different, unrelated package's shim.
   `is_relative_to()` compares path components, not characters:
   `Path(".../punt-lux-devtools/bin/luxd").is_relative_to(Path(".../punt-lux"))`
   is `False`, because `punt-lux-devtools` is not equal to, nor a child
   path segment under, `punt-lux` — it is a sibling. `is_relative_to()`
   is the correct primitive precisely because "points somewhere inside
   punt-lux's own uv tool directory" (still the invariant this design
   needs, since the shim's exact filename under
   `<tool_root>/punt-lux/bin/` may legitimately differ from the top-level
   name mid-rename-train) means *directory containment*, not *string
   overlap*.

This is a read-only, side-effect-free check — safe to call from
`diagnose()`/`is_clean()` with zero mutation, the same non-mutating
guarantee `LegacySweep.diagnose()` provides
(`_legacy_sweep_launchd.py:37-42`).

## 3. `ServiceSpec` Gains the Legacy Binary Names as Data

Directly reusing `service-lifecycle-migration.md` §5.2's reasoning — the
legacy name is intrinsic to what a *service* is, not to *how* it is
supervised, so it belongs on `ServiceSpec` as a tuple field, empty by
default, requiring zero special-casing at any call site:

```python
@dataclass(frozen=True, slots=True)
class ServiceSpec:
    ...
    legacy_launchd_labels: tuple[str, ...] = ()
    legacy_systemd_units: tuple[str, ...] = ()
    legacy_binary_names: tuple[str, ...] = ()   # new
    health_port: int | None = None

    def resolve_exec_args(self) -> list[str]:
        # binary_name changes from "luxd" to "luxd-hub" -- a plain data
        # edit, not part of this design; resolve_exec_args()'s logic
        # (_service_spec.py:42-58) is unaffected.
        ...
```

`HUB_SPEC` adds `legacy_binary_names=("luxd",)` alongside its existing
`binary_name="luxd-hub"` (renamed as part of the same PR, per the bead's
scope — not a design decision, a data edit). `DISPLAY_SPEC` leaves the
field at its empty-tuple default: its `binary_name="lux"` was never
renamed, so `DiskBinaryLegacySweep(DISPLAY_SPEC)` iterates zero names and
`sweep()`/`is_clean()` are no-ops by construction, exactly like
`LegacySweep` on `DISPLAY_SPEC` today (`_service_spec.py:85-95`, empty
`legacy_launchd_labels`/`legacy_systemd_units`).

A future rename train — the mission's own framing, "the same class of
stale-state-on-rename hazard" — adds one name to one tuple in
`_service_spec.py`. No new sweep class, no new call site.

## 4. Invocation Point

### 4.1 Composition: unconditional, not platform-dispatched

`ServiceManager.__new__` (`service.py:60-72`) currently composes
`_backend` and `_legacy_sweep` via `platform_classes(detect_platform())`
and `_port_guard` directly (`PortGuard(cls._SPEC)`, no platform lookup —
`PortGuard` is already platform-uniform per
`service-lifecycle-migration.md` §4). `_binary_sweep` follows the
`_port_guard` pattern, not the `_legacy_sweep` pattern, because §2.2
established there is no platform split to dispatch:

```python
class ServiceManager:
    __slots__ = ("_backend", "_binary_sweep", "_legacy_sweep", "_port_guard")
    _backend: ServiceBackend
    _binary_sweep: BinarySweep
    _legacy_sweep: LegacySweep
    _port_guard: PortGuard

    def __new__(cls) -> Self:
        ...
        self._backend = classes.backend(cls._SPEC)
        self._legacy_sweep = classes.legacy_sweep(cls._SPEC)
        self._binary_sweep = DiskBinaryLegacySweep(cls._SPEC)  # new, direct
        self._port_guard = PortGuard(cls._SPEC)
        return self
```

### 4.2 Call site: `ServiceManager.install()`, grouped with the identity cure

```python
def install(self) -> str:
    """Cure any legacy registration and port conflict, then install."""
    self._legacy_sweep.sweep()
    self._binary_sweep.sweep()          # new
    if self._SPEC.health_port is not None:
        self._port_guard.guard()
    self._backend.install()
    ...
```

Placed immediately after `_legacy_sweep.sweep()` and before
`_port_guard.guard()`: both `_legacy_sweep` and `_binary_sweep` cure
*naming* cruft left by past rename trains (§2.1's shared error class);
`_port_guard` checks *runtime* state (who currently holds the port), a
different concern. There is no ordering dependency between
`_legacy_sweep` and `_binary_sweep` — they touch disjoint subsystems (a
supervisor's job table vs. a directory entry) — so this placement is a
readability grouping, not a correctness requirement.

### 4.3 Why not "before `uv tool install` writes the new binary"

Mission design question (e) asks whether the cure should run "before uv
writes the new binary." It cannot, and does not need to: by the time
`lux hub install` executes at all, the `lux` binary invoking it was
*itself* just written by the preceding `uv tool install --force`
(`install.sh:87-93`, then `install.sh:110-111` runs `"$BINARY" hub
install`). There is no code path in which this codebase's own cure logic
runs before `uv` has already written `~/.local/bin/luxd-hub` — the
binary implementing the cure does not exist until that write completes.
This is not a gap: `LegacySweep`'s cure has the identical property today
(it also only runs inside `lux hub install`, strictly after `uv tool
install`) and closed the original incident correctly. The property that
matters is not "runs before the new artifact exists" but "runs
unconditionally, on every install, before the *old* artifact can mislead
anyone" — which `ServiceManager.install()`'s existing idempotent,
always-invoked-on-every-run design already guarantees (§7).

### 4.4 `install.sh` — no changes required

`install.sh` never references `luxd` directly; every reference is through
the `lux` CLI verb (`"$BINARY" hub install`, `"$BINARY" hub restart`, see
`install.sh:110-118`) or the `$BINARY` variable itself, which names `lux`
(`install.sh:24`), the one script whose name was never renamed. The
binary-sweep cure rides entirely inside `lux hub install`'s existing call
graph (§4.2) with zero edits to `install.sh`.

### 4.5 Concurrency

Directly parallels `service-lifecycle-migration.md` §4.1's treatment for
`LegacySweep` — two concurrent invocations of `lux hub install` (run
twice by accident, or racing `lux hub doctor --fix`) are safe by
inspection, and the one narrow race window fails closed rather than
corrupting anything:

- **`_resolve_tool_root()` holds no shared state.** It is a per-instance,
  per-process cache (`self._tool_root`, set once in `__new__` or lazily on
  first use) — there is no module-level or cross-process cache to
  desynchronize, and each racer's `uv tool dir` subprocess call is an
  independent read against `uv`'s own configuration, not against
  anything this design writes. Two racers each resolve their own
  `_tool_root` from scratch; there is no ordering between them to get
  wrong.
- **`Path.resolve()` on a symlink under concurrent modification does not
  raise.** `Path.resolve()` defaults to `strict=False`: if another racer
  (or the operator, or a future `uv tool install --force`) removes or
  rewrites `~/.local/bin/luxd` between this racer's `path.is_symlink()`
  check and its `path.resolve()` call, `resolve()` still returns a best-
  effort resolved path rather than raising `FileNotFoundError` — the
  ownership check degrades to "resolved against whatever was there a
  moment ago," not to a crash. If the racer's `resolve()` happens to
  return a path that no longer exists at all, the immediately-following
  `_sweep_one` re-check (§5, step 5's `Path.exists() or
  Path.is_symlink()`) already treats "gone" as `verified_clean=True` —
  the racer that observes a mid-flight removal converges to "clean"
  rather than raising on stale information.
- **`unlink(missing_ok=True)` makes a losing racer's removal step a
  no-op, not a crash.** The same pattern already established for both
  `LegacySweep` implementations
  (`_legacy_sweep_launchd.py:84`/`_legacy_sweep_systemd.py:92`,
  `service-lifecycle-migration.md` §4.1) and reused here in §5 step 4: if
  Racer A's `unlink()` wins the race, Racer B's subsequent `unlink()`
  call against the now-already-gone path raises nothing —
  `missing_ok=True` absorbs it, and Racer B's re-check (step 5) finds the
  file gone and records `verified_clean=True` for its own outcome. Both
  racers converge to the same "clean" report; neither corrupts the
  other's work, and neither ever produces the ordering violation this
  whole design family exists to prevent (§2.1: an artifact deleted before
  its "is this real" check is confirmed) — here, unlike the launchd case,
  there is no analogous violation to produce at all, because deletion is
  the *entire* cure, not a second step gated on a first.
- **No file lock is added**, for the same reasons
  `service-lifecycle-migration.md` §4.1 gives for `LegacySweep`: the
  failure mode under concurrency is "a spurious refusal that self-heals
  on retry," never silent corruption, and concurrent `lux hub install`
  invocations are an unusual operator action, not routine automation this
  design needs to optimize for.

## 5. Failure Semantics

Mirrors `service-lifecycle-migration.md` §4's fatal-by-default posture,
applied to the different outcome shape:

- **`sweep()` iterates every name in `spec.legacy_binary_names` to
  completion** — no short-circuit on the first failure, matching
  `LegacySweep._sweep_one` per-identifier independence
  (`_legacy_sweep_launchd.py:46-53`). Every `DiskBinaryOutcome` is
  appended to the accumulating `BinarySweepReport` regardless of outcome.
- **Per name, `_sweep_one`:**
  1. `path = self._bin_dir / name`. If `not path.exists() and not
     path.is_symlink()` (a dangling symlink still needs removing, so
     existence alone under-counts — check both): `was_present=False`,
     `verified_clean=True`, no-op. (The common steady-state case once the
     migration has run once.)
  2. Otherwise, `ownership_verified = self._is_ours(path)`.
  3. If `ownership_verified` is `False`: **refuse**. Record
     `removed=False, verified_clean=False`, `fix_command` names the exact
     manual inspection command (`ls -la <path>` / `readlink -f <path>`),
     not a blind `rm` — the operator must confirm identity by hand before
     deleting anything this codebase could not verify (§6).
  4. If `ownership_verified` is `True`: `path.unlink(missing_ok=True)` —
     `unlink()` removes the directory entry itself (correct for both a
     symlink and a regular shim file; it never follows the symlink to
     delete the target). Any `OSError` other than "already gone"
     (permissions, a race) propagates uncaught, matching
     `service-lifecycle-migration.md` §4 step 3's reliance on `unlink()`'s
     own semantics rather than a second stat call.
  5. Re-check `path.exists() or path.is_symlink()` after the unlink
     attempt; record `verified_clean` from that re-check, not from the
     unlink call completing without raising — the same distrust-the-first-
     signal discipline `LegacySweep` applies to `bootout`'s exit code
     (`_legacy_sweep_launchd.py:78-83`: a call reporting success is not
     proof; re-verify against the real state).
- **`sweep()` raises `ServiceMigrationError` once**, after every name has
  been attempted, if `not report.all_clean` — reusing the existing
  exception type from `_service_errors.py:21-27` rather than introducing a
  parallel one, because the caller-facing contract ("a rename train left
  the machine dirty; here is the full report") is identical even though
  the report's internal shape differs. `ServiceManager.install()`
  propagates it uncaught, exactly as it does today for the legacy-label
  sweep (`service.py:86`, no `except` around either call).

**A refusal (`ownership_verified=False`) is fatal, not a warning.** Bead
`lux-j169`'s design constraint list states "fatal on failure" and the
mission's evaluator brief singles out "silent-swallow" as a rejection
criterion. An unrecognized `~/.local/bin/luxd` blocks `lux hub install`
exactly as a stuck legacy launchd label does — the operator sees the
`describe()` text (§8), inspects the file by hand, and either deletes it
themselves (if it is genuinely stale) or renames their own script out of
the way. This is a deliberate design choice to prefer a loud, rare false
positive (the exceedingly unlikely case of an operator's own unrelated
`luxd` script) over a quiet, catastrophic false negative (deleting
someone's real file because "it had the right name").

## 6. Safety: Never Nuke a Real User Script

This is the design's central new invariant, absent from `LegacySweep`
because `LegacySweep`'s identifiers (`com.punt-labs.*` labels) carry
built-in, unambiguous ownership. A disk binary does not. The safety
argument, stated plainly:

- **The check is positive, not permissive.** `_is_ours()` must return
  `True` before anything is removed; the default for "cannot determine"
  is `False` (§2.4 point 1: no `uv` on `PATH` → refuse). There is no
  code path where an unrecognized file is removed because the check
  "couldn't hurt to try."
- **The check inspects the *target*, not the *name*.** Two operators'
  files can share the string `luxd`; the resolved-path check
  distinguishes "resolves inside `<uv tool dir>/punt-lux/`" (ours) from
  "resolves anywhere else, or nowhere" (not provably ours). A
  hand-written `~/bin/luxd` shell script that a `PATH` search happens to
  find first is a different `path` object entirely (a different
  directory) and is never even examined by this sweep, which only ever
  looks inside `~/.local/bin/` — the one directory `uv tool install`
  itself writes into.
- **A `PL-PP-3`-flavored boundary, correctly treated as one.** Verifying
  an external tool's on-disk artifact before mutating it is exactly the
  system-boundary case `PL-PP-3` (`.claude/rules/python-prohibited-
  patterns.md`) carves out from "no defensive coding at non-boundaries" —
  this is a boundary (another program's managed state), and the correct
  boundary behavior is to verify positively, not to trust the filename.

## 7. Verification

**Non-mutating, from a running install:**

```bash
uv run python -c "
from punt_lux._binary_sweep_disk import DiskBinaryLegacySweep
from punt_lux._service_spec import HUB_SPEC
report = DiskBinaryLegacySweep(HUB_SPEC).diagnose()
print(report.describe() or 'clean')
"
```

**From the CLI, read-only** — extends the existing `lux hub doctor`
surface (`cli/hub.py:82-98`) rather than adding a new command:
`ServiceManager.doctor()`/`doctor_fix()` (`service.py:159-165`) already
call `DoctorResult.diagnose`/`DoctorResult.repair`
(`_doctor_result.py:34-82`), which take `legacy_sweep` and `port_guard` as
parameters. Both gain a third parameter, `binary_sweep: BinarySweep`, and
`DoctorResult` gains a `binary: BinarySweepReport` field alongside
`legacy: LegacySweepReport` and a `_binary_lines()` render method beside
`_legacy_lines()`/`_port_lines()` (`_doctor_result.py:104-125`). `is_clean`
(`_doctor_result.py:84-87`) extends to `self.legacy.all_clean and
self.binary.all_clean and self.port.status in _CLEAN_PORT_STATUSES`.

```bash
lux hub doctor
```

Expected output once clean:

```text
luxd hub: clean
  legacy labels: none registered
  legacy binaries: none present
  port 8430: owned by luxd-hub (pid 41213)
```

Expected output while dirty (the operator's current state, §9):

```text
luxd hub: DIRTY
  legacy binary /Users/jfreeman/.local/bin/luxd: still present
    fix: rm /Users/jfreeman/.local/bin/luxd
  port 8430: owned by luxd-hub (pid 41213)

Run 'lux hub doctor --fix' to repair automatically, or apply the commands
above by hand.
```

Expected output if ownership cannot be verified (the refusal case, §6):

```text
luxd hub: DIRTY
  legacy binary /Users/jfreeman/.local/bin/luxd: present but NOT verified as a punt-lux shim
    inspect: readlink -f /Users/jfreeman/.local/bin/luxd
    this file was left in place -- verify by hand before removing it
```

**Post-cleanup assertion, shell-level, for CI or a runbook:**

```bash
test ! -e ~/.local/bin/luxd && test ! -L ~/.local/bin/luxd && echo "clean"
```

(`-e` alone is insufficient for a dangling symlink; `-L` catches that
case, matching `_sweep_one` step 1's `exists() or is_symlink()` check,
§5.)

## 8. Test Fixture Design

### 8.1 Unit-level (tier 1, `make test`, real filesystem in `tmp_path`, no real `uv`)

New `tests/test_binary_sweep.py`, structured after
`tests/test_service.py`'s `TestLegacyPlistCleanup` class
(`service-lifecycle-migration.md` §7.2's pattern):

- **Fixture setup, mirroring §1's real layout exactly** — a fake
  `~/.local/bin` and a fake uv tool root under `tmp_path`, with
  `DiskBinaryLegacySweep._resolve_tool_root()`'s `uv tool dir` subprocess
  call patched (not the filesystem check) to return the fake tool root's
  path, so the ownership-resolution *logic* is exercised for real against
  real `Path.resolve()` calls:

  ```python
  def _plant_owned_shim(tmp_path: Path, bin_dir: Path, name: str) -> Path:
      """Reproduce the exact two-hop shape observed on the real machine."""
      tool_root = tmp_path / "uv-tools" / "punt-lux" / "bin"
      tool_root.mkdir(parents=True)
      shim = tool_root / name
      shim.write_text("#!/fake/venv/bin/python3\nfrom punt_lux.luxd import main\n")
      shim.chmod(0o755)
      link = bin_dir / name
      link.symlink_to(shim)
      return link
  ```

- **Positive case.** Plant an owned shim via `_plant_owned_shim`. Run
  `sweep()`. Assert `report.all_clean`, the symlink no longer exists
  (`not link.exists() and not link.is_symlink()`), and
  `outcome.ownership_verified is True`.
- **Negative case — the safety invariant (§6), this is the test that
  matters most.** Plant a file at the same path pointing *outside* the
  fake tool root — e.g. `bin_dir / "luxd"` as a real regular file with
  `#!/bin/sh\necho "my own script"\n`, not a symlink at all. Run
  `sweep()`. Assert it raises `ServiceMigrationError`, assert the file
  **still exists** afterward (proving the refusal never unlinks), and
  assert `outcome.ownership_verified is False`.
- **Negative case — the sibling-package false positive (§2.4 point 3),
  proving `is_relative_to()` over `startswith()`.** Plant a shim that
  resolves into a *different but name-adjacent* tool directory:

  ```python
  def _plant_sibling_package_shim(tmp_path: Path, bin_dir: Path, name: str) -> Path:
      """Reproduce the exact false-positive `str.startswith()` accepted:
      a sibling uv tool whose directory name merely starts with ours."""
      sibling_root = tmp_path / "uv-tools" / "punt-lux-devtools" / "bin"
      sibling_root.mkdir(parents=True)
      shim = sibling_root / name
      shim.write_text("#!/fake/venv/bin/python3\nfrom other_pkg import main\n")
      shim.chmod(0o755)
      link = bin_dir / name
      link.symlink_to(shim)
      return link
  ```

  With `self._tool_root` resolving to `tmp_path / "uv-tools" /
  "punt-lux"`, `target` resolves to
  `tmp_path / "uv-tools" / "punt-lux-devtools" / "bin" / name`. Assert
  `sweep()` raises `ServiceMigrationError`, the symlink **still exists**
  afterward, and `outcome.ownership_verified is False`. This is the
  regression test for the exact defect djb's review caught: a
  `str(target).startswith(str(self._tool_root))` implementation passes
  this fixture (the string `".../punt-lux-devtools/bin/luxd"` does start
  with `".../punt-lux"`) and would unlink a foreign package's shim; a
  `target.is_relative_to(self._tool_root)` implementation correctly
  refuses, because `punt-lux-devtools` is a sibling path component, not a
  child of `punt-lux`. Without this fixture in the suite, a regression
  from `is_relative_to()` back to `startswith()` — the exact shape of
  code most readers reach for first — passes every other test, exactly
  the gap `service-lifecycle-migration.md` §7.2's fidelity-control
  discipline exists to close.
- **Idempotency.** Run `sweep()` on a `bin_dir` with no `luxd` entry at
  all (steady state, post-migration). Assert zero filesystem calls beyond
  the existence check — `was_present=False` for every outcome, matching
  `LegacySweep`'s already-established idempotency contract
  (`service-lifecycle-migration.md` §3).
- **`uv` absent.** Patch the `uv tool dir` subprocess call to raise
  `FileNotFoundError`. Plant an owned-looking shim (symlink into a
  tool-root-shaped path). Assert `sweep()` still raises
  `ServiceMigrationError` and the shim is untouched — "cannot verify" must
  never silently degrade into "assume safe" (§2.4 point 1, mirroring
  `PortGuard.guard()`'s `"unknown"` handling,
  `service-lifecycle-migration.md` §4 lines 308-313).

### 8.2 Fidelity-control integration test (tier 3, `@pytest.mark.e2e`)

A real `uv tool dir` call, no mocking of the subprocess boundary, run
against a real filesystem tree shaped like `~/.local/bin` but rooted in a
scratch `tmp_path` (never the operator's real `~/.local/bin` — this test
must not touch the real home directory):

```python
@pytest.mark.e2e
def test_binary_sweep_against_real_uv_tool_dir(tmp_path: Path) -> None:
    """Same shape as §8.1's positive case, but resolves through the REAL
    `uv tool dir` subprocess call -- the one thing a mock cannot prove:
    that this design's parsing of uv's actual stdout format is correct."""
```

This closes the same gap `service-lifecycle-migration.md` §7.1 names for
the launchd/systemd sweep: a fully-mocked test proves the *logic* is
internally consistent but cannot prove it agrees with the *real* external
tool's actual output format. Given `uv tool dir` prints one line with no
flags or JSON mode to negotiate, the blast radius of a real-subprocess
test is small and the fidelity payoff is exactly the class of bug this
whole design exists to prevent (misreading the tool's actual behavior).

## 9. Migration Path for the Operator's Current State

No separate one-time migration tool, matching
`service-lifecycle-migration.md` §8's reasoning: `ServiceManager.install()`
already runs unconditionally and idempotently on every `lux hub install`
invocation (`install.sh:111`, run on every install *and* every upgrade).
Once §4's change ships, the existing upgrade sequence cures the machine
with no additional operator action:

```sh
uv tool install --force punt-lux[display]==<fixed-version>
lux hub install
```

Concretely, on this operator's own machine, tracing through §1's captured
state: after `uv tool install --force` with the fixed release,
`~/.local/bin/luxd-hub` is written fresh (new name, new receipt entry) and
`~/.local/bin/luxd` is **left exactly as captured in §1** — untouched by
uv, because it is not one of the entrypoints the new receipt declares.
`lux hub install`'s existing call to `self._legacy_sweep.sweep()`
(unaffected by this change) then reaches the new
`self._binary_sweep.sweep()` (§4.2), which:

1. Finds `~/.local/bin/luxd` present (§1's `ls -la` output).
2. Resolves it: symlink → `~/.local/share/uv/tools/punt-lux/bin/luxd`.
3. Confirms `~/.local/share/uv/tools/punt-lux/bin/luxd` starts with
   `uv tool dir`'s reported root (`~/.local/share/uv/tools`) + `punt-lux`
   — `ownership_verified=True`.
4. Unlinks `~/.local/bin/luxd`.
5. Re-checks: gone. `verified_clean=True`.

No operator action beyond the ordinary upgrade-and-reinstall sequence is
required. `lux hub doctor` (§7) becomes the documented way to confirm the
cure took, both before upgrading (to see the dirty state named explicitly,
not inferred from `uv tool install` chatter) and after (to see `clean`),
the same role `lux hub doctor` already plays for the launchd/systemd
sweep.

## 10. Rejected Alternatives

### 10.1 `uv tool install --force` handling this natively

Considered relying on `uv tool install --force` to prune orphaned
entrypoint shims from a prior install of the same tool. Rejected: §1's
receipt inspection shows `uv` tracks entrypoints *per current
`pyproject.toml`* — the tool has no way to know that `luxd` was
*intentionally* dropped (a rename) versus a script the project simply no
longer ships, and even if a future `uv` version added reconciliation
logic for this case, this codebase would be depending on unreleased,
unversioned behavior of a tool it does not control, with no way to detect
at runtime whether the installed `uv` version actually implements it. The
mission's own framing states this directly: "uv only knows about
currently-declared scripts." `LegacySweep` already established the
precedent of this codebase owning its own cure logic rather than trusting
an external supervisor to clean up after a rename (`launchctl`/`systemctl`
do not know that `com.punt-labs.lux` was superseded by
`com.punt-labs.luxd-hub` either) — the same reasoning applies here.

### 10.2 A separate `lux migrate` command

Considered a standalone, explicitly-invoked migration command an operator
would need to remember to run once after upgrading. Rejected for the same
reason `service-lifecycle-migration.md` §5.3 rejected re-running `lux hub
install` as a repair mechanism, but pointed the other way: `lux hub
install` is *already* the command every operator runs on every upgrade
(`install.sh:111`), and it is already unconditional and idempotent. Adding
a second command an operator must separately remember to invoke
reintroduces exactly the "hope, not migration" failure mode the operator's
stance rejects — a cure that depends on someone remembering to ask for it
is not a cure, it is a manual step with extra ceremony. §9's zero-action
migration path is only possible because the sweep rides inside a step
that already runs unconditionally.

### 10.3 Trusting `uv-receipt.toml` as the sole ownership signal

Considered parsing `~/.local/share/uv/tools/punt-lux/uv-receipt.toml`'s
`entrypoints` list (§1) as the authority for "is `luxd` still uv-managed,"
using Python 3.13's stdlib `tomllib` (no new dependency). Rejected as the
*sole* mechanism, though it remains a candidate optional secondary signal
for a later PR: the receipt's schema is an internal uv implementation
detail with no stability guarantee across uv releases (unlike `uv tool
dir`, which is a documented, stable subcommand), and — more importantly —
by the time `DiskBinaryLegacySweep.sweep()` runs, `uv tool install --force`
has *already* rewritten the receipt to the post-rename entrypoint list
(§1: `entrypoints` reflects whatever `pyproject.toml` currently declares,
not history). The receipt tells you what uv currently manages, not what
uv *used* to manage and no longer does — exactly the information this
sweep needs and the receipt does not retain. The resolved-path check
(§2.4) answers the right question directly: "does this file still point
into our tool directory," independent of what the receipt says today.

### 10.4 Blind `unlink()` with no ownership check

Considered removing `~/.local/bin/<legacy_name>` unconditionally once
`legacy_binary_names` names it, on the reasoning that `LegacySweep`
doesn't verify ownership of `com.punt-labs.lux` either. Rejected per §6 —
the two subjects are not equivalent. A launchd label under
`com.punt-labs.*` cannot collide with anything an operator would have
installed themselves; a file named `luxd` in `~/.local/bin` can. Skipping
the ownership check trades a rare false-positive refusal (§5's stated
preference) for a rare but catastrophic false-negative deletion — the
exact failure mode the mission's evaluator brief names explicitly
("silent-swallow-of-safety").

## Related Documents

- `docs/architecture/service-lifecycle-migration.md` — the `LegacySweep`
  precedent this design extends; §5.2 (data-on-`ServiceSpec` reasoning),
  §5.4 (cohesion-driven separate-class reasoning), §4 (fatal-by-default,
  `PortGuard`'s fail-closed `"unknown"` handling), §8 (idempotent-install
  migration-path reasoning) are each cited above.
- Bead `lux-ehzy` — the launchd/systemd incident and its fix scope.
- Bead `lux-j169` — this design's scope.
- `src/punt_lux/_service_spec.py`, `_legacy_sweep.py`,
  `_legacy_sweep_launchd.py`, `_legacy_sweep_systemd.py`,
  `_platform_dispatch.py`, `_doctor_result.py`, `_service_errors.py`,
  `service.py`, `cli/hub.py`, `pyproject.toml`, `install.sh` — the current
  implementation this design extends or touches.
