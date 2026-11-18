# Terminal spike artifacts

These files are research/evidence, not the canonical Lux target architecture.
Production code is under `src/punt_lux/{ptyd,terminal,display/terminal,protocol/pty}`.
Automated behavioral checks are under `tests/ptyd`, `tests/protocol` and `tests/render`.
No production module imports the experimental harnesses in this directory.

## Current step-4 handoff

- `STEP4-HANDOFF.md`: final scheduled status; central lifetime goal demonstrated,
  full product/merge acceptance explicitly incomplete.
- `STEP4-LIFECYCLE-CYCLES.md`, `lifecycle_bench.py`: 20 bounded create/reattach/
  exit/kill resource cycles, not long-duration soak.
- `STEP4-PLAN.md`: bounded implementation plan and chronological checkpoints.
- `STEP4-LIVE.md`: actual-window lifetime and visible replay evidence.
- `STEP4-PERFORMANCE.md`, `results/`: reproducible measured observations/limits.
- `STEP4-REVIEW.md`: acceptance ledger and outstanding merge prerequisites.
- `daemon_bench.py`: finite local production-replica benchmark; run with timeout.
- `check_daemon_window.py`: isolated macOS live check; requires the reviewed
  screenshot helper from Lux main (read-only), ffmpeg, tesseract and permission.
- `check_two_windows.py`: two isolated real Hubs/Displays share one PTY owner;
  crash/survivor/rejoin evidence with PID-selected screenshots.
- `probe_keyboard_table.py`, `STEP4-KEYBOARD-PROBE.md`: incomplete OS-input
  diagnostic. Table/terminal render, but warm input delivery is not established;
  not a passing acceptance check or keyboard-latency result.
- `docs/adr/0007-independent-terminal-owner-and-replicas.md`: current spike decision.

## Historical, not current implementation instructions

`STEP1.md`–`STEP3.md` and the older engine, local transport, rendering, recording,
comparison and live-input scripts document how the spike reached step 4. Their
Display-owned lifetime and throughput numbers must not be treated as current
results. Retained recordings/checks are valuable fidelity evidence; they are
not silently included in the scoped repository test run.

`STEP4-DESIGN.md`, `step4-options.html` and `merged-architecture.html` are
exploratory proposals. They contain deferred options and unmeasured claims.
The implementation plan/current ADR and canonical Lux DESIGN/target docs win.
Do not use those pictures as permission to merge products or change Hub topology.

The original hygiene plan suggested deleting every unused spike script. They
are instead retained and explicitly classified as historical research, not
production dependencies or shipping tests. Deleting evidence to make a checklist
look complete would not improve the product. Any eventual packaging/merge can
choose an archive policy explicitly.
