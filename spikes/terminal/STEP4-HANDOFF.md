# Step 4 terminal daemon — final scheduled handoff

The 12-run sequence has produced a working bounded local owner/replica spike.
**The central lifetime goal is demonstrated. Full product/merge acceptance is
not complete.** No PR, merge or canonical architecture adoption is authorized.

## Repository and authority

- Separate clone: `~/Coding/punt-labs/lux-terminal-spike`.
- Branch: `spike/terminal-ghostty`; ratchet comparison base `3712972`.
- Normal `~/Coding/punt-labs/lux` services/checkouts were not changed by this work.
- ADR-0007 and STEP4-PLAN.md describe this implementation. Exploratory architecture
  HTML/design proposals do not authorize changes to Lux/Vox/biff topology.
- README, changelog, known limitations and STEP4-REVIEW.md hold the current ledger.

## What works and is evidenced

- Local `luxd-pty` owns PTYs/program groups and authoritative native terminals.
  Display holds replaceable replicas. Programs survive viewer close and actual
  Display SIGKILL/restart, including visible marker restoration after Hub replay.
- Binary snapshots retain both screens/history/bounded parser continuation;
  automatic program replies have one owner. Versions are negotiated strictly.
- Credit includes snapshot fragments. Bounded backlog replaces lost unsent tail
  with an authoritative repaint; outstanding credit debt survives reset.
- Multiple production replicas and two actual GUI windows share one program.
  Crash of one window leaves the survivor updating; replacement rejoins the same
  daemon/program. PID-selected/OCR screenshots back the claim.
- Lazy detached startup, lifetime OS claim, guarded stale socket reclamation and
  empty-only idle exit. Stable private lock/log inodes persist intentionally.
- Bounded wire batching improves the recorded ACK-backlog/flood-input behavior.
  Local cold/warm/burst timing is measured and qualified, not a WAN or maximum-
  throughput guarantee.
- Review fixes: unavailable initial snapshot retries after parser ground rather
  than permanent FAILED; wrong stream direction rejected; operation allocation/
  grouped cleanup faults isolated without swallowing operator stop/interrupts.
- Formal safety models, fidelity mutations, PDFs and coverage maps. Short real
  lifecycle/resource cycles, not an unbounded soak proof.

## Final verified checkpoint

- **835 focused tests passed**; 19 integrations deselected from scoped make check.
- Separately **all 19 integration tests passed** under timeout.
- Whole-repository strict typing: zero errors, seven existing ImGui source warnings.
- Lint and OO/coupling/suppression gates pass without relaxed thresholds; source
  suppression count remains **123**.
- Twenty lifecycle cycles preserve PID/screen through reattach, including exited
  programs that do not respawn; kill leaves no sessions. Daemon FD count stays 6
  at cycles 2/10/20, sampled direct-child lists empty. Parent FD count stays 6.
  RSS samples rise 496 KiB, not evidence of an unbounded memory-leak guarantee.
- Owned test programs/daemons/Displays/Hubs were stopped/reaped as applicable,
  temporary sockets/instances removed. No test daemon remains.
- The full macOS suite was deliberately not run under the operator constraint.

## Explicit incomplete work

1. **Valid real keyboard input and calibrated first-pixel timing beside a heavy
   table/flood.** The diagnostic renders terminal plus 1,000 rows, but PID-targeted
   OS events never establish a warm response. Driver/focus versus product input
   issue is unresolved. No global keyboard fallback or transport-input substitution
   was used. It is documented as incomplete, not a passing acceptance test.
2. Long-duration native/Python memory, descriptors, process descendants, log
   retention and many-terminal/application rendering soak. Short cycles do not
   close these gaps.
3. Broader macOS suite when authorized; Linux credentials/PTY/spawn/packaging/fonts.
4. Independent protocol/native-lifetime/security review and shipping policy,
   including shell authority, consent, session namespace and resource diagnostics.
5. Reconcile with current main only if authorized, without changing quality gates
   or touching normal services. Adopted spike ADRs require canonical DES decisions.

Known limits include one-second cold connection retry, slower flooded terminal
input, private native API pinned to pyghostty 0.1.4 and no daemon-upgrade process
persistence. No remote transport, agent terminal API, replay, mesh/blackboard or
voice integration is delivered by this bounded step.

## Evidence map / next starting point

- STEP4-LIVE.md + `results/window-*`, `results/two-windows-*`: actual-window evidence.
- STEP4-PERFORMANCE.md + raw reports: measured local responsiveness and limitations.
- STEP4-LIFECYCLE-CYCLES.md + raw report: bounded resource/lifecycle observations.
- STEP4-KEYBOARD-PROBE.md + incomplete status: unresolved OS-input diagnostic.
- STEP4-REVIEW.md: precise acceptance and merge prerequisite ledger.
- docs/adr/0007-independent-terminal-owner-and-replicas.md: current spike decision.
- docs/pty_*_coverage.md: formal-model boundaries and complementary test evidence.

If continuing, start with the unresolved owned-window input-driver/focus
investigation or obtain an operator-assisted physical-key check. Do not relabel
prior ping/replica timing as keyboard-to-pixel evidence. Preserve the isolated
instance and timeout discipline and commit signed checkpoints before broadening
scope. No time estimates or automatic merge actions are part of this handoff.
