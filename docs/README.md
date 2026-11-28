# Docs Guide

Use this file when the repo's documentation feels contradictory, or to find
the right document for a question. Every document under `docs/` is listed
here with its status, or through the linked migration and Vox Rooms indexes.

Lux has documentation for:

- the current/intermediate implementation
- the target architecture
- coding standards
- formal models (Z specs with ProB model-checks and coverage audits)
- completed migrations and delivered designs (historical records)
- alternative concepts

These are not the same thing.

## Start Here

- [architecture/target/target.md](./architecture/target/target.md)
  Canonical target architecture for the rewrite.
- [architecture/system.tex](./architecture/system.tex)
  Current/intermediate architecture. This is the org-standard current-system
  document.

If the question is "what are we rewriting toward?", start with the target docs.
If the question is "what does the code approximately do today?", use
`system.tex`.

## Users and Integrators

- [library.md](./library.md) — the Python library guide: `LuxClient`,
  the persistent `LuxHubClient` listener, and connecting to `luxd`'s MCP
  endpoint directly. The [README](../README.md) is for users; this is the
  developer companion.
- [user-guide.md](./user-guide.md) — how a session connects to `luxd`, how
  session menus and the `lux-beads` applet work, and the permission rules
  `lux enable` writes.

## Terminal Spike (latency baseline)

- [adr/README.md](./adr/README.md) — experimental terminal decision records,
  not canonical Lux architecture. The direct Display → `luxd-pty` Unix socket
  is only a latency baseline for measuring the production Hub path. Production
  terminal traffic goes through the Hub; the branch does not yet implement
  that relay.
- [../spikes/terminal/README.md](../spikes/terminal/README.md) — research,
  measurements and historical implementation checkpoints for the baseline.
- [terminal-known-limitations.md](./terminal-known-limitations.md) — terminal
  product gaps, not a declaration of production readiness.

## Coding Standard

- [standards/python-oo.md](./standards/python-oo.md)

This is the repo-level implementation standard. It is where Lux's OO-only
policy and ratchet enforcement live. It is not an architecture document.

## Workflow

- [WORKFLOW.md](./WORKFLOW.md) — the three nested loops (backlog, PR,
  mission) every change in this repository runs through.

## Target Architecture

- [architecture/target/README.md](./architecture/target/README.md)
- [architecture/target/topology.md](./architecture/target/topology.md)
- [architecture/target/ui-model.md](./architecture/target/ui-model.md)
- [architecture/target/element-contract.md](./architecture/target/element-contract.md)
- [architecture/target/introspection-api.md](./architecture/target/introspection-api.md)

These documents describe the intended Hub-authoritative architecture. The
identity ladder, multi-Hub aggregation, and cross-host transport and trust
model (DES-089, DES-090) are specified directly in
[architecture/system.tex](./architecture/system.tex) — it now covers
multi-Hub/cross-host in addition to the current/intermediate
implementation, per operator direction (2026-09-04) that an
evaluator-accepted architecture design folds into `system.tex` rather than
staying a standalone target markdown. The implementation plan for both is
[architecture/multi-hub-addressing-work.md](./architecture/multi-hub-addressing-work.md).

## Delivered Designs

Design documents whose work shipped. Each carries a status banner; they remain
the reference for how their subsystem is built.

- [architecture/one-code-path.md](./architecture/one-code-path.md) — the
  typed `Operations` facade, REST front door, thin adapters (epic `lux-7gcz`,
  v0.20.0/v0.21.0).
- [architecture/menu-capability-model.md](./architecture/menu-capability-model.md)
  — the session-and-callback menu model (operator-ruled 2026-07-29; the
  earlier "capability" abstraction it once proposed is withdrawn).
- [architecture/mcp-display-liveness.md](./architecture/mcp-display-liveness.md)
  — the Hub replicator: dirty-signal coalescing, bounded sends, reap/reconnect
  recovery. Modeled by `hub_replicator.tex` below.
- [architecture/e2e-harness-design.md](./architecture/e2e-harness-design.md)
  — the in-process end-to-end business-event loop harness (ships in
  `tests/e2e/`).
- [architecture/client-identity.md](./architecture/client-identity.md) — the
  diagnosis and ratified policy behind DES-057 (operator-ruled 2026-07-28:
  durable session-scene lifetime, `identify` + challenge, anonymous REST
  rejected); the shipped shape (PRs #290-#292) evolved past several of this
  document's specifics — DES-057 in `DESIGN.md` is authoritative for those.
- [architecture/scene-display-packaging-design.md](./architecture/scene-display-packaging-design.md)
  — the `scene/` → `display/replica/` dissolution and the N1/N2/N3 naming
  convention (operator-ratified 2026-08-08; PRs #318-#319).
- [architecture/display-introspection.md](./architecture/display-introspection.md)
  — the `display_state_get` operation: a Hub-mediated, connection-scoped
  proxy to the Display's own widget/frame state (bead `lux-221j`).
- [architecture/hub-display-narrowing.md](./architecture/hub-display-narrowing.md)
  — the client door leaves `HubDisplay`: callers hold `ClientLifecycle`,
  `HubClientRegistry` or `ClientListing`, and every presence change is one
  store-locked lifecycle step (DES-101, bead `lux-ghhf`).
- [architecture/connection-rung-design.md](./architecture/connection-rung-design.md)
  — the connection rung on every owned frame and the observed client and Hub
  hosts in the `i` popup and Details (DES-100, the DES-099 amendment, bead
  `lux-xrli`).
- [architecture/display-crash-quarantine.md](./architecture/display-crash-quarantine.md)
  — scene quarantine for the crash-respawn loop (DES-085, PR #354, bead
  `lux-88ka`). Companion model: `display_crash_loop.tex` below.
- [architecture/agent-menu-dispatch.md](./architecture/agent-menu-dispatch.md)
  — agent-menu frame targeting and delivery to the owning MCP session inbox
  (DES-098, bead `lux-m3xr`, PR #495).
- [architecture/binary-rename-migration.md](./architecture/binary-rename-migration.md)
  — historical record of the delivered stale binary-shim sweep
  (bead `lux-j169`, PR #383).
- [architecture/client-surface-parity-design.md](./architecture/client-surface-parity-design.md)
  — the shared noun-first command vocabulary across library, CLI, MCP and REST
  (DES-087, epic `lux-0shg`; lower/expire remain deferred).
- [architecture/display-presence-demand-driven.md](./architecture/display-presence-demand-driven.md)
  — hold content and retry the link without controlling the Display process
  (DES-093, bead `lux-81t3.1`).
- [architecture/hub-display-reconciliation-design.md](./architecture/hub-display-reconciliation-design.md)
  — manifest-on-identify reconciliation and single-owner preemption
  (DES-068, bead `lux-e9vy`; later scoped by Hub identity).
- [architecture/library-client-encapsulation.md](./architecture/library-client-encapsulation.md)
  — the public `LuxClient` facade and narrow applet operation protocols,
  retiring the public REST transport (bead `lux-duqj`).
- [architecture/scene-id-namespacing-design.md](./architecture/scene-id-namespacing-design.md)
  — connection-scoped scene/frame store keys (DES-086, PR #356, v0.25.0).
- [architecture/service-lifecycle-migration.md](./architecture/service-lifecycle-migration.md)
  — service-registration rename cleanup through the `LegacySweep` family
  (bead `lux-ehzy`).
- [design-des065-visibility.md](./design-des065-visibility.md)
  — historical delivered design for Display-owned closed-frame visibility and
  Hub-owned content (DES-065 R8, DES-088, bead `lux-mxvy.8`).
- [architecture/lease-reap-cascade.md](./architecture/lease-reap-cascade.md)
  — the delivered four-step departure cascade under `StoreLock`, including
  reconnect/reap exclusion (bead `lux-vvmt`; round 3 of
  `connection_lease_reaping.tex`; its §10 records a residual).

## Element Migration (completed)

The migration of all 25 element kinds onto the Element-ABC / Hub-Display path
is **complete** (epic `lux-xs7r`, closed 2026-07-27; the legacy path is
deleted). These documents are the historical record:

- [architecture/migration/README.md](./architecture/migration/README.md) —
  the plan and its per-element design documents (progress, slider, table,
  composites, and the rest).
- [architecture/element-migration-audit.md](./architecture/element-migration-audit.md)
  — the per-element map the migration worked from.
- [architecture/skill-tool-reusability-audit.md](./architecture/skill-tool-reusability-audit.md)
  — the audit behind DES-040's tools-vs-skills split.

Additional historical records not individually linked by the migration index:

- [ABC baseline debt audit](./architecture/migration/abc-baseline-debt-audit.md)
  — baseline cleanup inventory.
- [Foundation audit](./architecture/migration/foundation-audit.md)
  — the first four Element-ABC exemplars.
- [Foundation review R1](./architecture/migration/foundation-review-r1.md)
  and [R2](./architecture/migration/foundation-review-r2.md)
  — exemplar hardening reviews.
- [Hub write path](./architecture/migration/hub-write-path-design.md)
  — Hub-authoritative write-path design.
- [Factory decomposition](./architecture/migration/element-factory-decomposition-design.md)
  — the ABC-kind registry design.
- [Renderer decomposition](./architecture/migration/element-renderer-decomposition-design.md)
  — extraction of per-kind renderers.
- [Continuous-edit extraction](./architecture/migration/continuous-edit-extraction-design.md)
  — the shared `ContinuousEditArbiter` design (`lux-ld6y`).
- [Color picker](./architecture/migration/color-picker-element-design.md)
  — element migration and continuous-edit extraction.
- [Combo and radio](./architecture/migration/combo-radio-design.md)
  — selection-widget migration.
- [Composite kinds and Hub authority](./architecture/migration/composite-kinds-hub-design.md)
  — composite migration design and correction.
- [Group](./architecture/migration/group-element-design.md)
  — the first container migration.
- [Input number](./architecture/migration/input-number-element-design.md)
  — numeric-input migration.
- [Selectable](./architecture/migration/selectable-element-design.md)
  — selectable-row migration.
- [Simple composites](./architecture/migration/simple-composites-design.md)
  — `tab_bar` and `collapsing_header` migration.
- [Slider](./architecture/migration/slider-element-design.md)
  — slider migration.
- [Table](./architecture/migration/table-design.md)
  — composed basic data-grid migration (B6).

## Current Architecture

- [architecture/system.tex](./architecture/system.tex) →
  [architecture/system.pdf](./architecture/system.pdf)

This is the current/intermediate system view, not the rewrite target.

## Formal Specs

Z specifications, each ProB-model-checked and committed as a regression
artifact — re-run `fuzz` and the model-check whenever the modeled code
changes. A coverage audit beside a spec maps its test partitions to the tests
that cover them.

Current and authoritative:

| Model | Coverage audit | What it proves |
|---|---|---|
| [frame-visibility-lifecycle.tex](./frame-visibility-lifecycle.tex) | [frame_visibility_lifecycle_coverage.md](./frame_visibility_lifecycle_coverage.md) | Frame lifecycle (DES-065 R8, DES-088, DES-103): two visibilities, content pushes never write visibility, focus or tab, × needs an end handler. Verified by `make check-models` (`scripts/verify_frame_visibility_model.sh`), which also runs the fidelity variants. Coverage file lists test partitions, not current coverage |
| [listen_lifecycle.tex](./listen_lifecycle.tex) → [pdf](./listen_lifecycle.pdf) | [listen_lifecycle_coverage.md](./listen_lifecycle_coverage.md) | Delivered WebSocket listen-leg ownership and callback-registration atomicity across same-identity reconnects; distinct from the Hub-to-Display listener model below |
| [listener_lifecycle.tex](./listener_lifecycle.tex) | [listener_lifecycle_coverage.md](./listener_lifecycle_coverage.md) | Implemented per-dial socket, reader-slot and reply-sink ownership, stale-reader isolation, reply matching and retirement (DES-090/093/101/102). Fidelity controls: [ack key only](./listener_lifecycle_ack_key_only_buggy.tex), [current](./listener_lifecycle_current_buggy.tex), [gate only](./listener_lifecycle_gate_only_buggy.tex), [inline skip](./listener_lifecycle_inline_skip_buggy.tex), [lock expiry](./listener_lifecycle_lock_expiry_buggy.tex), [lose](./listener_lifecycle_lose_buggy.tex), [nowait](./listener_lifecycle_nowait_buggy.tex), [perlink lock](./listener_lifecycle_perlink_lock_buggy.tex), [pong unkeyed](./listener_lifecycle_pong_unkeyed_buggy.tex), [production](./listener_lifecycle_production_buggy.tex), [query plain](./listener_lifecycle_query_plain_buggy.tex), [reader restart](./listener_lifecycle_reader_restart_buggy.tex), [registry drop](./listener_lifecycle_registry_drop_buggy.tex), [repeat](./listener_lifecycle_repeat_buggy.tex), [retire split](./listener_lifecycle_retire_split_buggy.tex), [route skip](./listener_lifecycle_route_skip_buggy.tex), [stale reply](./listener_lifecycle_stale_reply_buggy.tex), [write fail keep](./listener_lifecycle_write_fail_keep_buggy.tex) |
| [listener_locks.tex](./listener_locks.tex) | [shared audit](./listener_lifecycle_coverage.md) | Deadlock-freedom and acquisition order for request, reader-slot, generation, socket and queue locks; [inverted-order control](./listener_locks_inverted_buggy.tex) |
| [scene_id_namespacing.tex](./scene_id_namespacing.tex) → [pdf](./scene_id_namespacing.pdf) | — | Delivered connection-scoped store-key collision exclusion, idempotency and malformed-id rejection (DES-086); [unscoped-key control](./scene_id_namespacing_buggy.tex) |
| [hub_display_reconciliation.tex](./hub_display_reconciliation.tex) | [hub_display_reconciliation_coverage.md](./hub_display_reconciliation_coverage.md) | Manifest reconciliation and original single-owner preemption (DES-068, `lux-e9vy`); the name-keyed HI4 clause is superseded by `crosshost_hubid_preemption.tex`. [No-preemption control](./hub_display_reconciliation_no_preemption_buggy.tex) |
| [display_lifecycle.tex](./display_lifecycle.tex) → [pdf](./display_lifecycle.pdf) | [display_lifecycle_coverage.md](./display_lifecycle_coverage.md) | Display-singleton spawn/reap/bind lifecycle (DES-037/038): singleton-serving, never-unlink-live, no-two-winners, deadlock-freedom |
| [hub_replicator.tex](./hub_replicator.tex) → [pdf](./hub_replicator.pdf) | [hub_replicator_coverage.md](./hub_replicator_coverage.md) | Hub→Display replication: coalescing, torn-read exclusion, send-failure recovery, menu re-mark (I6). The menu leg predates the menu epic's callback rework — reconciliation tracked as `lux-ptji` |
| [frame_expiry.tex](./frame_expiry.tex) | [frame_expiry_coverage.md](./frame_expiry_coverage.md) | Frame TTL expiry: a frame with a future deadline is always shown; every removal path disarms |
| [board_ordering.tex](./board_ordering.tex) | [board_ordering_coverage.md](./board_ordering_coverage.md) | The beads applet's board ordering: the slot never goes backwards, nor does the display, and the display never shows a board the slot refused. Three fidelity controls reproduce the defects the design closes — the code as it stood ([current](./board_ordering_current_buggy.tex)) and the two half-fixes ([counter](./board_ordering_gate_only_buggy.tex), [re-read](./board_ordering_reread_only_buggy.tex)) |
| [header_toggle_reconciliation.tex](./header_toggle_reconciliation.tex) | — | The collapsing header's open state across the click-to-re-push window: one click moves the rendered state once and fires once, the optimistic value never outlives its window, and the Hub wins once it has spoken. Three fidelity controls reproduce the shipped double-step ([unconditional write](./header_toggle_reconciliation_unconditional_buggy.tex)) and the two ways a careless fix goes wrong ([stale pending](./header_toggle_reconciliation_stale_pending_buggy.tex), [firing against the Hub value](./header_toggle_reconciliation_refire_buggy.tex)) |
| [patch_application.tex](./patch_application.tex) → [pdf](./patch_application.pdf) | — | Patch crash-freedom: no agent patch can terminate the display; rejected patches are atomic |
| [patch_atomicity.tex](./patch_atomicity.tex) → [pdf](./patch_atomicity.pdf) | — | Table-patch rollback atomicity (B6): a failed patch leaves no partial state |
| [tab_bar_selection.tex](./tab_bar_selection.tex) → [pdf](./tab_bar_selection.pdf) | — | Tab-bar selection state machine |
| [commit_on_idle_reconciliation.tex](./commit_on_idle_reconciliation.tex) → [pdf](./commit_on_idle_reconciliation.pdf) | — | Continuous-edit commit-on-idle reconciliation for non-atomic inputs |
| [display_linkage.tex](./display_linkage.tex) | [display_linkage_coverage.md](./display_linkage_coverage.md) | Demand-driven display presence (`lux-81t3.1`): the Hub never spawns the display, only dials/holds/retries; `DisplayLinkage`'s four-way classification, the disconnected retry's own 2s→120s curve structurally disjoint from the wedge backoff, the interruptible reconnect wait's lock-freedom (I8), and process-control absence (I5, the grep-provable "Hub never spawns" check) |
| [reconciliation_hub_reject.tex](./reconciliation_hub_reject.tex) → [pdf](./reconciliation_hub_reject.pdf) | — | Hub rejection of a reconciliation commit: the display converges to the Hub's value |
| [display_crash_loop.tex](./display_crash_loop.tex) | — | Crash-respawn quarantine (shipped, DES-085, `lux-88ka`); the `_buggy` variants ([1](./display_crash_loop_buggy.tex), [2](./display_crash_loop_earlyexit_buggy.tex)) are fidelity controls that reproduce the defect the design closes |
| [connection_lease_reaping.tex](./connection_lease_reaping.tex) | [connection_lease_reaping_coverage.md](./connection_lease_reaping_coverage.md) | Hub client-registry lease reaping (`lux-d84d`), refined to the code's three separate departure paths plus a background backstop — a non-destructive `Read`, a single `Depart` coordinator (graceful disconnect and SDK idle-reap), a `Claim` (write) that renews its own caller before sweeping anyone else, and `TimedReap` (a periodic sweep guarded only on a lapsed lease, no read/write/disconnect signal required): a transport-gone connection is *unconditionally* eventually reaped, even on an otherwise idle Hub (I1), leaving the registry and releasing ownership are the same event however triggered (I5), a live writer is never reaped by its own or another's write (I6), and a live reconnect under the same identity is never shadowed by a departed predecessor's ownership (I3). Implemented, including round 3\'s store-locked departure cascade (bead `lux-vvmt`). Three fidelity controls, one per ownership-integrity hole a four-way review found in the round-1 implementation: [destructive read](./connection_lease_reaping_destructive_read_buggy.tex) (a read sweeps a lapsed connection without releasing it), [no release on departure](./connection_lease_reaping_no_release_buggy.tex) (`HubDisplay.drop_connection` deregisters without releasing), [self-reap on write](./connection_lease_reaping_self_reap_buggy.tex) (`HubDisplay.apply` sweeps its own caller because nothing renews it first); additional fidelity controls: [cascade incomplete](./connection_lease_reaping_cascade_incomplete_buggy.tex), [reconnect race](./connection_lease_reaping_reconnect_race_buggy.tex) |
| [crosshost_connection_lifecycle.tex](./crosshost_connection_lifecycle.tex) | [crosshost_transport_coverage.md](./crosshost_transport_coverage.md) | Cross-host transport (DES-090), W12 Invariant 1 "no content before verification" (`lux-833p`): the two-gate connection lifecycle (accept into the pending set → TLS handshake, Gate 1 → SAN/`hub_id` cross-check, Gate 2 → content). No `SceneMessage` is processed until a connection is both handshaken (I1) and identified (I2); content therefore lands only past both gates. Two fidelity controls, one per gate: [no handshake gate](./crosshost_connection_lifecycle_no_handshake_gate_buggy.tex) (accept makes a socket readable before its handshake — reproduces the handshake-before-accept defect, I1 violated) and [no identify gate](./crosshost_connection_lifecycle_no_identify_gate_buggy.tex) (content accepted from any readable fd — the W1 gap, I2 violated); each isolates the other gate |
| [crosshost_hubid_preemption.tex](./crosshost_hubid_preemption.tex) | [crosshost_transport_coverage.md](./crosshost_transport_coverage.md) | Cross-host transport (DES-090), W12 Invariant 2 "at most one live connection per `HubId`" (`lux-833p`): DES-068's single-owner preemption re-keyed onto `HubId` (W11), generalized from one same-host Hub to N concurrently-reconnecting Hubs. `hubOf` stays injective on the live set across every interleaving; different-`HubId` connections coexist even when they share a name. One fidelity control: [name-keyed](./crosshost_hubid_preemption_name_keyed_buggy.tex) (the pre-W11 key) reproduces both the double-owner defect (two live connections own one `HubId`) and the wrong-eviction defect (a same-name arrival evicts a live, unrelated Hub). Supersedes the name-keyed HI4 clause of `hub_display_reconciliation.tex` |
| [menu_lifecycle.tex](./menu_lifecycle.tex) | [menu_lifecycle_coverage.md](./menu_lifecycle_coverage.md) | Agent-menu ownership, inbox delivery, and session-departure lifecycle (DES-098, `lux-m3xr`, PR #495): M1 "no false-positive delivery" (an `offer` that races a `drop_session` never reports `delivered` for a click no `recv()` will drain — the orphan-put defect) and MO "menu-ownership integrity" (no session owns a bar in the registry once it has left it, however it departed — the `connection_lease_reaping` I5/I7 shape applied to a fourth cascade leg), plus deadlock-freedom over the one-way lock order D3's fix requires. Three fidelity controls, one per defect the DES-098 review found: [D1](./menu_lifecycle_d1_buggy.tex) (offer's get-then-put non-atomic with departure), [D2](./menu_lifecycle_d2_buggy.tex) (the menu prune wired only to the graceful leg, not the lease-lapse cascade), [D3](./menu_lifecycle_d3_buggy.tex) (`set_menu` admit/store TOCTOU stores a bar for an already-departed owner) |
| [menu_lifecycle_delivery.tex](./menu_lifecycle_delivery.tex) | [menu_lifecycle_coverage.md](./menu_lifecycle_coverage.md) | Refines `menu_lifecycle.tex` along the one axis its delivery abstraction collapses — the fate of an enqueued-but-undrained menu event across a departure (round-6 challenge to M1, PR #495). Gives the enqueued event a token (`pending`), a drain (`recv`), and a two-phase departure whose registry-discard and inbox-teardown are separate steps, then proves M1b "no live-recipient loss": a discard only ever befalls a connection already gone from the registry, so the offer-THEN-drop-discards ordering (distinct from D1's drop-between-get-and-put) is not a false delivery. One fidelity control: [reorder](./menu_lifecycle_delivery_reorder_buggy.tex) |
| [menu_lifecycle_bounded_inbox.tex](./menu_lifecycle_bounded_inbox.tex) | [menu_lifecycle_bounded_inbox_coverage.md](./menu_lifecycle_bounded_inbox_coverage.md) | The per-connection Agent-Subscribe inbox bound (`lux-wk3p`): a `threading.Condition` over a `deque` serializes `put`/`get`/`drain`/`depth` so the bound is exact and drops are minimal. B1 "no `depth > cap` overshoot" and B2 "no double/spurious drop" (a `get` cannot slip between `put`'s full-check and its drop — the tear a plain `Lock` with an unguarded `get` leaves open), plus deadlock-freedom: the dequeue is serialized yet `Condition.wait_for` releases the lock while blocking, so a waiting `get` contributes no lock edge and the one-way `regLock → boxLock` nesting stays acyclic. Two fidelity controls: [no-lock](./menu_lifecycle_bounded_inbox_nolock_buggy.tex) (reproduces overshoot + double-drop) and [deadlock](./menu_lifecycle_bounded_inbox_deadlock_buggy.tex) (the reverse `boxLock → regLock` edge closes the cycle) |
| [writer_publish_generation.tex](./writer_publish_generation.tex) | — | Session-writer publish atomicity (`lux-wk3p` review), in two parts over one joint state. Part One, invariant WG — no cross-generation put WITHIN one firing of `_writer`: neither an orphan-put into a queue detached by a concurrent `drop_session` (silent loss) nor a departed session's message delivered into a same-`connection_id` reconnect's fresh inbox (cross-session leak); the fix mirrors `offer`'s D1 atomicity — `_writer`'s lookup-or-create and put under one `_inboxes_lock` hold. Fidelity control: [split](./writer_publish_generation_split_buggy.tex) (the release-then-put window at the real code's lock boundary) reproduces both the orphan-loss and cross-generation witnesses. Part Two, invariant WG2 — no cross-generation delivery via `Hub.publish`'s own snapshot-then-invoke window (a Copilot re-review finding on the round-2 atomicity fix, `c2f1c289`): a subscriber snapshot can capture a departed session's writer closure and invoke it, unbounded in delay, after a same-identity reconnect — WG2 is the generation-currency check, **shipped** in `c7454787` (`WriterRegistry.is_current` / `Hub.writer_is_current`, checked under the same `_inboxes_lock` hold as the put; regression: `tests/wire/model/test_inbox.py::test_stale_writer_after_reconnect_does_not_deliver_into_the_new_session`), that rejects such a stale invocation instead of delivering it into the reconnected session's live inbox. Fidelity control: [snapshot](./writer_publish_generation_snapshot_buggy.tex) — like the split control, this is now a regression control for a shipped fix: it models `_writer` as it stood after the round-2 atomicity fix (`c2f1c289`) but before the WG2 currency check, and reproduces the cross-generation delivery that fix does not reach |
| [frame_info_popup.tex](./frame_info_popup.tex) | [frame_info_popup_coverage.md](./frame_info_popup_coverage.md) | The frame-info glyph and its popup: a press, hold, drag and release on a frame's title-bar glyph against the one info popup, with ImGui's own dismissals (a press outside the popup shuts it at the end of that frame, so the code learns a frame late) and frames that appear, vanish and fold between press and release. I1 a click on a closed popup opens it (replacing another frame's), I2 a click on an open popup ends with it closed, I3 a press that strayed past the drag threshold never toggles, I4 a release acts only on the press it came from (no press record survives a release), I5 the popup is open only for a frame that exists, plus deadlock-freedom. Five fidelity controls, one per defect: [popup opened on the press](./frame_info_popup_press_opens_buggy.tex), [drag judged by the current offset](./frame_info_popup_current_offset_buggy.tex), [toggle decided on the release](./frame_info_popup_release_toggle_buggy.tex), [press record kept after a non-click release](./frame_info_popup_stale_press_buggy.tex), and [popup outliving its frame](./frame_info_popup_frame_gone_buggy.tex). The coverage audit also records which code mutations each test kills, and the one test that fails to guard the defect it was written for |
| [menu_presence.tex](./menu_presence.tex) | [menu_presence_coverage.md](./menu_presence_coverage.md) | Which sessions earn a Clients-menu entry, and what every change to that set owes the Hub (`lux-ghhf`, the recurrence of one defect class across four review rounds): P1 with no mark pending no live earning session is missing from the Display and nothing unregistered is shown, P2 every earning session has exactly one bound menu sink, none more, a departed one none, and P3 a live session's frame shows a stale label only while its own scenes carry a pending mark. A session earns presence as an agent or by holding a callback; the callback route is modelled (`RegisterCallback`, `Detach`), which is what the earlier revision elided and what hid INV-1. Presence is lease-filtered (DES-058, DES-064): a lapse is time, so a lapsed entry may linger only until the sweep or the next push, but a renewal that revives a lapsed session is a presence transition that marks, binds the one shared sink, and marks the session's scenes so a renumbered survivor's label is repaired (INV-2). Every presence transition is one `ClientLifecycle` step (`arrive`, `identify`, `attach`, `renew`, `register_callback`, `detach`, `depart`, `depart_lapsed`, with `PresenceWrites.attach` beneath it) under the store lock; the registry reports the change and never calls out of its own lock. Companion [menu_presence_locks.tex](./menu_presence_locks.tex) proves the lock order (store, then registry, callback steps included; readers registry-only) deadlock-free. Ten fidelity controls, one per defect: [D1/D2 identify or attach never marks](./menu_presence_d1_buggy.tex), [D3 the read loop revives a swept session](./menu_presence_d3_buggy.tex), [D4 renewing a lapsed agent never marks](./menu_presence_d4_buggy.tex), [D5 the before-snapshot outside the lock](./menu_presence_d5_buggy.tex), [D6 a sink bound per attach](./menu_presence_d6_buggy.tex), [INV-1 a callback registered under the registry lock only](./menu_presence_inv1_buggy.tex), [INV-1b a withdrawal mark gated on the lease](./menu_presence_inv1b_buggy.tex), [INV-2 a revival that marks the menus but not the scenes](./menu_presence_inv2_buggy.tex), [M1 a lease-gated withdrawal on re-identify as a non-agent](./menu_presence_redeclare_buggy.tex), and [the registry-owned hook, which deadlocks](./menu_presence_locks_inverted_buggy.tex) |
| [dial_settlement.tex](./dial_settlement.tex) | [dial_settlement_coverage.md](./dial_settlement_coverage.md) | How a dial is ended and settled (`lux-ghhf`, DES-102; the recurrence of one defect class across the final review rounds): settlement belongs to the holder of the reader slot, everyone else asks, and an asker refused behind a held slot waits a bounded time. S1a an ended or end-requested current dial is settled by a party already running, with no timer; S1b the same behind a holder that never makes progress, by the bound; S2 a dead display's end is captured only after a drain that began after it was recorded; S3 one capture per dial and S4 the first recorded cause wins (both structural); S5 a display already dead when the settler observed the socket is never recorded as a Hub end; plus deadlock-freedom. Four carve-outs are flagged, not hidden: `s2dec`, `s2blk` (the bound's undrained capture, display or unresponsive end), and `s5blk`, each an exception to A1 or A2 of the attribution model with its bound, and the gluing to `crash_attribution_inflight_ack_drain.tex` is an inclusion of charges. Twelve fidelity controls, one per defect: [start_fail](./dial_settlement_start_fail_buggy.tex) (`start_on` on an ended dial keeps the slot), [stop_skip_drain](./dial_settlement_stop_skip_drain_buggy.tex) (the listener's exit reads the end twice), [inline_strand](./dial_settlement_inline_strand_buggy.tex) (a refused settle leaves no debt), [split_settle](./dial_settlement_split_settle_buggy.tex) (the post-drain record is not first-wins), [atomic_refuse](./dial_settlement_atomic_refuse_buggy.tex) (refusal and debt are two steps), [atomic_release](./dial_settlement_atomic_release_buggy.tex) (release and debt-read are two steps), [defer_only](./dial_settlement_defer_only_buggy.tex) (a Hub request with no bound), [timer_hub_only](./dial_settlement_timer_hub_only_buggy.tex) (only a Hub request arms the bound), [s3_unguarded](./dial_settlement_s3_unguarded_buggy.tex) (a capture without the current guard), [s4_overwrite](./dial_settlement_s4_overwrite_buggy.tex) (a recorder that overwrites), [hub_record](./dial_settlement_hub_record_buggy.tex) (the Hub end records `hub` at once), and [hub_peek](./dial_settlement_hub_peek_buggy.tex) (a peek at the socket, an ack ahead of the FIN hides the end of file); additional fidelity controls: [bound records asker](./dial_settlement_bound_records_asker_buggy.tex), [drain gives up](./dial_settlement_drain_gives_up_buggy.tex), [drain no late](./dial_settlement_drain_no_late_buggy.tex), [stop no request](./dial_settlement_stop_no_request_buggy.tex), [unbounded write](./dial_settlement_unbounded_write_buggy.tex), [whole write deadline](./dial_settlement_whole_write_deadline_buggy.tex), [writer owe refused](./dial_settlement_writer_owe_refused_buggy.tex), [writer records display](./dial_settlement_writer_records_display_buggy.tex), [writer split record](./dial_settlement_writer_split_record_buggy.tex) |
| [crash_attribution.tex](./crash_attribution.tex) | [crash_attribution_coverage.md](./crash_attribution_coverage.md) | Which scenes the Hub charges when the display dies (DES-102, rulings T10 to T14): T10 a death is charged from the dead dial's own ack ledger, once, whoever discovers it, and a Hub-ended dial charges nothing; T11 the display installs on receipt but sends its ack only after the next completed buffer swap, so an ack means a frame survived the scene; T12 a Hub-ended dial's non-empty ledger joins a carried suspect set that a display-ended death charges and any ack read on a later dial clears; T13 a third retire cause, unresponsive, queued as a display death and carried as a Hub end; T14 the read is split into `Recv` and `Deliver`, and a display-ended or unresponsive capture waits until no ack is in the socket or in the reader's buffer. A1 every observed poison death charges the poison scene (A1w: and some scene is charged for it), A2 no scene is charged unless it was in that death (own ledger and carried set), A3 a Hub-ended dial charges nothing, A4 a dial's death is charged at most once, plus deadlock-freedom and charge liveness. Eight fidelity controls, each with the one phrase that names its defect: [the ack sent at receipt, the code before T11 (A1, A1w)](./crash_attribution_ack_on_receipt_buggy.tex), [T11 without T12, nothing carried (A1, A1w)](./crash_attribution_no_carry_buggy.tex), [only the unresponsive door's carry removed (A1w)](./crash_attribution_unresponsive_no_carry_buggy.tex), [capture without the reader-buffer guard, an acked scene charged (A2)](./crash_attribution_inflight_ack_buggy.tex), [charging only on the replicator's own redial (A1)](./crash_attribution_redial_only_buggy.tex), [blame carried to the next scene sent, a substitution (A1, A1w, A2)](./crash_attribution_idle_stop_buggy.tex), [a Hub-ended dial charged (A3)](./crash_attribution_hub_end_charged_buggy.tex), and [a dial charged twice (A4)](./crash_attribution_double_charge_buggy.tex); a ninth file, [the drain as part of the capture](./crash_attribution_inflight_ack_drain.tex), is a design variant that holds A1 to A4 and shows the two formulations agree |

Legacy (model the pre-Hub/Display single-process design):

- [architecture/display-server.tex](./architecture/display-server.tex) →
  [pdf](./architecture/display-server.pdf)
- [architecture/workspace-model.tex](./architecture/workspace-model.tex) →
  [pdf](./architecture/workspace-model.pdf)

The legacy specs' refinement tests still hold the current display code to their
models, but they predate the Hub/Display split and are not the main narrative
architecture set.

## ImGui Reference

- [imgui/primitive-catalog.md](./imgui/primitive-catalog.md)

A comprehensive Dear ImGui / ImPlot widget and primitive reference. This is a
timeless API reference, independent of Lux's architecture, and is kept current.

## Archive

- [archive/addressing.md](./archive/addressing.md) — superseded DES-089 draft;
  folded into `system.tex` and the multi-Hub implementation plan.
- [archive/cross-host-transport.md](./archive/cross-host-transport.md) —
  superseded DES-090 draft; folded into the same architecture and work plan.
- [archive/README.md](./archive/README.md)
- [archive/claude-code-lux.tex](./archive/claude-code-lux.tex) →
  [pdf](./archive/claude-code-lux.pdf)
- [archive/coverage-audit.md](./archive/coverage-audit.md)

Superseded documents retained for history. Each carries an archived banner.
They do not describe the current system; see [`archive/README.md`](./archive/README.md)
for why each was archived. Older migration notes and spike proof points not in
the archive can be recovered from git history.

## Alternative Concepts

- [concepts/self-extending-display.md](./concepts/self-extending-display.md)
- [concepts/extension-architecture.tex](./concepts/extension-architecture.tex) →
  [pdf](./concepts/extension-architecture.pdf)
- [concepts/pharo-inspiration.md](./concepts/pharo-inspiration.md)
- [concepts/vox-rooms/](./concepts/vox-rooms/README.md) — Vox Rooms, a
  November 2026 product concept: a keyboard-first, voice-forward workspace for
  leading several coding agents across repos and machines. Holds a draft
  PR/FAQ, a clickable prototype, thirteen mockups and the design notes behind
  them. Brainstorm stage; likely to move to its own repository.

These are not approved plans, are not the canonical Lux architecture, and are
not under active development.

## Product Thesis

- [prfaq.tex](../prfaq.tex) → [prfaq.pdf](../prfaq.pdf)

The Working-Backwards PR/FAQ (at the repo root, not under `concepts/`). Unlike
the alternative concepts above, this is a living product-thesis document under
the org's release workflow — it is updated when a change shifts product
direction or validates a risk assumption, not an abandoned concept.
