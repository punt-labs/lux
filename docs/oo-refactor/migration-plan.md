# Migration Plan — Domain Model Across All Tiers (Revised 2026-05-23, v2.1)

**Status:** ACTIVE
**Target:** `docs/architecture/domain-model.md` (domain north star), `docs/architecture/io-model.md` (I/O architecture), `docs/architecture/x11-model.md` (process topology).
**Method:** B-amended — thin vertical slice. See "Methods considered and rejected" below.
**Authority:** This is the executable plan. Mission YAMLs cite PRs from this document; specialist agents (`rmh`, `gvr`, `mdm`, `djb`, `adb`, `kpz`) execute PRs in the order below.

## Why this revision exists (v2)

The v1 revision (merged in PR #188) replaced the original PR 3–6 sequence with a PR 3–13 sequence that landed io-model infrastructure family-by-family, then bundled connection-layer cleanup + Encoder (PR 10), Observer (PR 11), and process split (PR 13) at the end.

Operator review identified the PR 3–13 sequence as a repeat of **Method A** (the horizontal-bands approach rejected during the original plan drafting). Method A was rejected because it builds infrastructure before end-to-end proof — and v1 quietly does the same. Specifically:

- The Encoder family (PR 10) is built without exercise until then.
- The process split (PR 13) is built without exercise until then.
- The Observer subsystem (PR 11) is built without exercise until then.
- The full Hub-render → Encode → RPC → Display-paint pipeline is not proven end-to-end until PR 13 — eight PRs after the first migration.

The v2 sequence (this document) replaces PRs 3–13 with a **thin vertical slice** sequence that proves the target architecture end-to-end starting at PR 3. Peer-reviewed by rej (refactoring), kwb (TDD/XP), and rop (Plan 9 simplicity) before adoption; convergent findings applied as-is, the two 2/1 splits resolved per operator.

## What v1 got right and v2 retains

- The Element ABC + template-method `render()` shape (DES-032, io-model.md). Unchanged.
- The Renderer / Decoder / Encoder families (DES-033, DES-034). Unchanged in shape; v2 ships them per-kind alongside each Element migration rather than bundling Encoder as a family PR.
- Observer pattern at MCP boundary (DES-036). Unchanged in shape; v2 ships it in PR 4 with `interaction.<id>` as the load-bearing first consumer rather than PR 11 with a manufactured consumer.
- The Bar invariants (below). Unchanged — rule 10 (tests-with-code per commit) remains the new rule introduced in v1.
- WidgetValueProvider deletion. Same scope; happens in PR 3 with Text's migration.

## v2.1 update (2026-05-23, post-spike)

v2.1 is a small refinement of v2 after the spike at `spikes/io_model_v1/` validated the architecture end-to-end:

- **PR 3 reframed as port-from-spike, not design-from-scratch.** The spike is a working reference implementation of the io-model for one element (Text) with three processes, two surfaces, four roundtrips. PR 3's contract is to lift those patterns into production code, not to re-derive them. Risk drops substantially.
- **DialogElement added to PR 4 scope.** The spike's R4 demonstrated `DialogElement` with bound-callback Composite pattern (`Button(on_click_callback=dialog.close)`). PR 4 lands it alongside Button + Observer, so agents get usable modal-dialog capability immediately rather than waiting until PR 8 (Layout).
- **Universal MCP-tool preservation acceptance.** Every PR (3–12) must keep the 29 existing MCP tools working. The agent-facing contract is invariant; internal call paths evolve.
- **Spike + ARCHITECTURE_NOTES.md A1–A5 are primary references.** Mission YAMLs cite the spike as source material; PR design missions reference specific spike modules rather than re-deriving shapes the spike already validated.

The PR sequence, slicing, and total count are unchanged from v2.

## What v2 changes

The thin-slice principle is applied at the **pipeline** level, not just the family level. PR 3 ships the entire outbound pipeline end-to-end for one element (Text). PR 4 closes the inbound roundtrip (Button + Observer). PR 5 proves the update path via an in-fabric applet. PRs 6–11 mechanically replicate (or design-bear) per family. PR 12 sweeps any orphaned carcasses.

| Question | v1 (merged) | v2 (this) |
|---|---|---|
| When does outbound pipeline work end-to-end? | PR 13 | PR 3 |
| When does inbound roundtrip work end-to-end? | PR 13 | PR 4 |
| When does Observer push to agents work? | PR 11 | PR 4 (real first consumer) |
| When does background-thread update work? | PR 13 | PR 5 |
| When does Encoder family ship? | PR 10 (consolidated, 24 kinds at once) | Per-kind alongside each Decoder (PR 3, PR 4, ...) |
| When does process split exist? | PR 13 | PR 3 (bare subprocess; supervision deferred to a later operational PR) |
| Total PR count | 11 (PRs 3–13) | 10 (PRs 3–12) |

## What's shipped

| PR  | Bead       | GitHub | Status   | Summary |
|-----|------------|--------|----------|---------|
| 0   | `lux-edvm` | #184   | ✅ MERGED | Characterization snapshots + `make snapshot-parity` gate |
| 1   | `lux-b14i` | #186   | ✅ MERGED | Domain layer + basics family migrated (with codec-on-class — to be refactored in PR 3) |
| 2   | `lux-i84j` | #187   | ✅ MERGED | Inputs family migrated (with codec-on-class — to be refactored in PR 5) |

PRs 1 and 2 are productive steps that DO NOT need to be reverted. They
establish the domain layer (`Display`, `Update`, `Event`, `ClientId`, etc.),
the per-class module structure, per-kind renderer classes for basics+inputs in
`display/renderers/`, the `DomainPump` wire-side routing, and the
`Display.interact` Interaction-routing pipeline. The io-model adoption builds
on this scaffolding; it does not throw it away. What changes is the OWNERSHIP
boundary — codec moves off the class, render moves onto the class, behavior
moves onto the class, factories get injected.

## The Bar — non-negotiable invariants

Rules 1–10 are unchanged from v1. Repeated here for self-containment. **Rule 10 (tests arrive with the code, per commit) was new in v1** — it was implicit in earlier missions but is now codified.

1. **The system stays running at every step.** No flag days. Each PR is
   independently shippable. Existing agents that call `show()` /
   `show_table()` / `show_dashboard()` continue to work without modification
   until the final cleanup PR.

2. **`make check` passes on every commit, not every PR.** The OO ratchet
   must improve or hold; the suppression ratchet must hold or decrease. A
   commit that fails `make check` is a broken commit.

3. **No suppressions to land a PR.** No `# noqa`, no `# type: ignore`, no
   `# pylint: disable`, no `--no-verify`, no editing `.oo-baseline.json` by
   hand. If a suppression is genuinely necessary (e.g., a third-party
   library with no stubs), it must be approved by the operator before the
   PR is opened.

4. **No backwards-compatibility shims that outlive their PR (PL-PP-1).**
   When the new path covers the old one, the old one is deleted in the
   same PR that completes the coverage — not "in a follow-up." Re-exports,
   tombstone comments, "deprecated" aliases are forbidden.

5. **No dead code waiting to be wired (PY-RF-2).** A new class with zero
   callers is a refactoring failure. Infrastructure PRs ship with the
   first consumer that proves the infrastructure works.

6. **Local verification per commit, ship per PR.** Within each PR:
   - `make check` runs after every commit.
   - `code-reviewer` and `silent-failure-hunter` agents run on the diff
     of each commit (or each logical step of commits).
   - `make snapshot-parity` (introduced in PR 0) runs as a CI gate from
     PR 1 onward.
   - Manual smoke test (`make install` + restart `luxd` + exercise the
     affected MCP tools) is run by the agent who owns the PR before the
     PR opens.

7. **The COO does not write code.** Every implementation PR is delegated
   through an ethos mission. Mission YAMLs cite the OO rules verbatim in
   the first 20 lines, with one BEFORE/AFTER example. Worker and evaluator
   are distinct handles per the lux/CLAUDE.md pairing table.

8. **PR granularity ≠ verification granularity.** The verification unit is
   the local step (one transformation, locally reviewed, locally tested).
   The shipping unit is rollback coherence. A PR contains as many verified
   local steps as fit one rollback-coherent unit of work.

9. **No time estimates.** Plans speak in PR count and dependency order.
   Cadence is whatever the work allows.

10. **Tests arrive with the code, per commit.** When a commit adds a new
    Element class, a new Renderer, a new Decoder, a behavior method, or any
    other user-visible production code, the same commit contains the test
    that exercises it. Tests in a separate commit, deferred to a follow-up
    commit, or "to be added in a later commit of this PR" are forbidden.
    Red-green-refactor at commit granularity is the discipline; same-commit
    code-and-test is how it is enforced. The only exception is pure
    documentation / baseline-alignment commits (chore commits with no
    production code change).

## Architecture references (new)

Mission YAMLs from PR 3 onward MUST cite these in the OO-rules block:

- `docs/architecture/io-model.md` — the I/O architecture target.
- `DESIGN.md` DES-031 — Domain Model Across All Tiers (grounding decision).
- `DESIGN.md` DES-032 — Element Owns Behavior, Not I/O (codec moves off the
  class; render moves onto the class via template method; behavior methods on
  Element subclasses; `renderer_factory` + `emit` injected at construction).
- `DESIGN.md` DES-033 — Renderer and Decoder Families with Asymmetric
  Cardinality (per-surface and per-format families, module-level registries,
  1 RendererFactory + N Decoders per Display).
- `DESIGN.md` DES-034 — IPC and Rendering Are Decoupled — Renderer vs Encoder
  Distinction (Encoder family is committed; IPC carries Updates and Events
  only, never render calls; renderer is display-tier; encoder is in every
  shipping tier; shipping strategy whole-tree-vs-diff is a downstream-surface
  property). Mission YAMLs from PR 3 onward MUST cite this — v2 ships
  per-kind Encoders alongside each Decoder rather than a consolidated family.
- `DESIGN.md` DES-035 — Handler Routing — Ownership, Client Kind, and Pattern
  Are Three Independent Axes (ownership = "hub" or connection_id; client kind
  = library / wire / LLM agent; handler pattern = deterministic /
  agent-escalation / hybrid; applet author writes tier-blind code). Mission
  YAMLs from PR 4 onward MUST cite this (PR 4 introduces behavior-on-Element
  with Observer routing; the Interaction-layer collapses in PR 7 after every
  input migrates).
- `DESIGN.md` DES-036 — Observer Pattern at the MCP Boundary (hub is Subject;
  MCP-connected agents are Observers; topic-based subscribe / publish /
  notify; PublishMessage wire kind for in-fabric publishers crossing Lux IPC).
  Mission YAMLs from PR 4 onward MUST cite this — Observer subsystem lands
  in PR 4 with `interaction.<id>` as the load-bearing first consumer.
- `DESIGN.md` DES-037 — Hub thread-safety architecture (single-writer queue
  vs explicit lock — decision committed in PR 5 before in-fabric API code).

## Pipeline (v2 — thin vertical slice)

Ten PRs total — flat sequential numbering. PRs 0–2 are shipped (above). PRs 3 through 12 are the remaining work, each a rollback-coherent unit. The three early-verification slices land in PRs 3–5; PRs 6–11 replicate (or design-bear) per family; PR 12 sweeps.

| PR | Scope | Proves end-to-end |
|----|-------|-------------------|
| 3  | Text outbound + Element ABC + Renderer + Decoder + Encoder + Connection + bare subprocess + DisplayClient | Outbound pipeline (Agent → ImGui paint) |
| 4  | Button + on_click + Observer subsystem + `interaction.<id>` first consumer + recv() polling shim | Inbound roundtrip (User click → Hub → Agent push) |
| 5  | In-fabric applet + background-thread update + Hub thread safety + SetProperty on TextElement | Update path (background mutation → Display re-paint) |
| 6  | Remaining 5 basics (Image, Separator, Progress, Spinner, Markdown) | Outbound replication for leaves |
| 7  | Remaining 8 inputs + Interaction-layer collapse (design-bearing) | Inbound replication + legacy interaction plumbing deleted |
| 8  | Layout family + ReparentElement + ReplaceElement + cycle detection (design-bearing) | Composite pattern through the pipeline |
| 9  | Graphics — Draw + sub-Composite draw commands | Sub-Composite within Element |
| 10 | Table family (design-bearing — depends on PR 8) | Stateful element with rich behavior |
| 11 | Plot family + perf budget tightening (design-bearing) | All 24 kinds on io-model; perf budget enforceable |
| 12 | Sweep (capped: delete recv() shim, ElementRenderer god class, SceneManager legacy methods, system.tex update) | Codebase is purely io-model |

**Encoder family:** per-kind alongside each Decoder (PR 3 ships JsonTextEncoder, PR 4 ships JsonButtonEncoder + JsonInteractionEncoder, PR 6 ships 5 basics encoders, etc.). NOT a consolidated family PR.

**Process split:** the connection abstraction + in-memory queue + bare Unix-socket subprocess ship in PR 3. Operational supervision (launchd/systemd, exponential backoff, scene re-push on respawn) is a separate later PR — operational scope, not load-bearing for the slice.

**Observer subsystem:** ships in PR 4 with `interaction.<id>` as the load-bearing first consumer. `recv()` retained for one PR cycle as a polling shim over the Observer registry; deleted in PR 12.

**Interaction-layer collapse:** lands in PR 7 (the PR that migrates the last input), not PR 4. Deleting `Display.interact` / `ButtonClicked` / `ButtonPressed` / `DomainPump.route_interaction` while inputs still depend on them would break the 8 unmigrated kinds — a Method B violation. Each deletion lands in the PR that removes its last caller.

**Universal acceptance — every PR (3 through 12):** the 29 MCP tools in `src/punt_lux/tools/tools.py` (the agent-facing contract) continue to accept their current arguments and produce equivalent display output throughout the migration. Internal call paths change as the Hub API evolves; tool signatures must not. New MCP tools (e.g. the Observer `subscribe`/`unsubscribe`/`publish` in PR 4) are additive. A PR that breaks an existing MCP tool's contract is not ready to merge.

**Spike as reference:** the spike at `spikes/io_model_v1/` (branch `spike/io-model-v1`) is the working reference for the io-model architecture. Mission YAMLs from PR 3 onward cite it as primary source material; PR design missions should reference specific spike modules (e.g. "lift from spike's `connection.py`") rather than re-derive shapes the spike already validated. ARCHITECTURE_NOTES.md A1–A5 on the spike branch records the structural conclusions that apply across all PRs.

### PR 3 — Text outbound end-to-end (v2.1: port from spike, do not re-derive)

| Field | Value |
|-------|-------|
| **Reference implementation** | The spike at `spikes/io_model_v1/` (branch `spike/io-model-v1`) is a working three-process realization of the io-model architecture for one element (Text) with two surfaces (text + recording) and four end-to-end roundtrips, validated against ARCHITECTURE_NOTES.md A1–A5. **PR 3's contract is to LIFT the spike's foundation into production code, not to re-derive it.** Specifically: port `element.py`, `protocols.py`, `codec.py`, `connection.py`, and `renderers/{null,text,recording}.py` patterns into the production `src/punt_lux/` layout, adapt for production constraints (real ImGui rendering instead of text surface, integration with the existing 29 MCP tools, conform to the existing socket conventions), and migrate `TextElement` as the first proving consumer. |
| **Goal** | Prove the outbound pipeline end-to-end for one element under the v2 thin-vertical-slice plan, with the spike as the reference. Land the Element ABC with template-method `render()` + `_children()` hook; `Renderer` / `Decoder` / `Encoder` / `Connection` Protocols + per-kind registries; per-kind `JsonTextDecoder` + `JsonTextEncoder`; `Connection` abstraction with two backends (in-memory queue for tests, bare Unix-socket subprocess for runtime); `DisplayClient` that consumes encoded payloads and issues real ImGui calls; `TextElement` migrated to ABC; `WidgetValueProvider` Protocol deleted. |
| **What lands** | (a) Element ABC + Renderer Protocol (lifted from spike's `element.py` + `protocols.py`). (b) Decoder + Encoder Protocols + registries (lifted from spike's `codec.py`). (c) Per-kind JsonTextDecoder + JsonTextEncoder. (d) Connection abstraction with in-memory queue backend (default `LUX_DISPLAY_IN_PROCESS=1`) and bare Unix-socket subprocess backend (lifted from spike's `connection.py`, adapted to lux's existing socket paths). (e) DisplayClient that consumes encoded payload and issues real ImGui calls (NEW — the spike used text + recording surfaces; production needs ImGuiTextRenderer). (f) TextElement on the ABC with `__new__`-pattern construction; PR-2 codec methods deleted. (g) WidgetValueProvider Protocol deleted with its sole call site in SceneManager. (h) NullRenderer + RecordingRenderer (lifted from spike). (i) ImGuiRendererFactory with surface-shared state only (extraction rule stated below). (j) Loose perf smoke at 50ms/frame for 10 Text elements. |
| **Out of scope** | Observer subsystem (PR 4). Other basics (PR 6). Inputs (PR 7). Operational supervision — launchd/systemd/exponential-backoff/scene-re-push (later PR). Scene-diff encoding (later PR — measure before optimizing). Per-connection wire-format negotiation beyond JSON (no second format yet). |
| **Internal commit sequence** | (i) NullRenderer + RecordingRenderer + tests (genuinely generic; lifted from spike). (ii) Element ABC + Renderer Protocol + Decoder Protocol + Encoder Protocol + registries + RED TextElement test (xfail strict until commit iii). (iii) TextElement on ABC + JsonTextDecoder + JsonTextEncoder + ImGuiRendererFactory + ImGuiTextRenderer — RED test goes GREEN. (iv) Connection abstraction + in-memory queue backend + integration test (single-process). (v) Subprocess backend + spawn + lifecycle test. (vi) DisplayClient + ImGui paint integration. (vii) WidgetValueProvider deletion. (viii) Old Text scaffolding deletion + loose perf smoke. Each commit passes `make check` + `make snapshot-parity` + local code-reviewer + silent-failure-hunter. |
| **CI test name** | `tests/integration/test_text_outbound_e2e.py` — spawns Display via either backend, sends Text scene, asserts paint output. `tests/perf/test_frame_budget.py` — loose 50ms budget for 10-element Text scene. |
| **MCP-tool preservation (required acceptance)** | All 29 MCP tools in `src/punt_lux/tools/tools.py` continue to accept their current arguments and produce equivalent display output. The agent-facing contract does not break. Internal call path may change (tools call the new Hub API instead of the PR-2 `DisplayClient.show`); tool signatures must not. |
| **Rollback story** | If reverted on main, PR-2 Text path is restored verbatim. Other 23 kinds remain on PR-2 throughout this PR — they are not touched. |
| **ImGuiRendererFactory extraction rule** | The factory holds only surface-shared context (widget_state, texture_cache, emit channel). Per-kind state lives on the per-kind renderer. New per-kind renderers (PRs 4–11) may not accumulate state on the factory. |
| **Worker / Evaluator** | `rmh` / `gvr`. `rej` consulted on template-method Composite realization + WidgetValueProvider deletion. `adb` consulted on Connection abstraction + subprocess spawn. |
| **Acceptance** | `make snapshot-parity` passes for Text wire bytes. `make check` clean. Text scene renders end-to-end through the Connection in both backends. Loose perf smoke passes. All 29 MCP tools continue to work. Grep verifies zero `to_dict`/`from_dict` on TextElement, zero references to `WidgetValueProvider`. |

### PR 4 — Button + Observer + inbound roundtrip + DialogElement (v2.1)

| Field | Value |
|-------|-------|
| **Reference implementation** | The spike's R3 (`spike/io-model-v1`, `spikes/io_model_v1/demo.py run_r3`) demonstrates the inbound roundtrip end-to-end. The spike's R4 demonstrates `DialogElement` with bound child callbacks (`Button(on_click_callback=dialog.close)`) — the Composite + OO behavior dispatch pattern that PR 4 lands in production. Port both. |
| **Goal** | Close the inbound roundtrip end-to-end for one behavior-bearing element AND introduce the first composite with self-dismiss behavior (Dialog). ButtonElement on the ABC with `on_click` emitting `ButtonClicked`. ImGui detects click → encode → RPC to Hub → `ButtonElement.on_click()` runs → Hub publishes `interaction.<id>` → subscribed agent receives push. DialogElement with `close()` behavior; child buttons in a dialog have `on_click_callback=dialog.close` bound at decode time by `JsonDialogDecoder`. Hub's emit handler dispatches by message type: Events → publish; Updates → accept + ship (per ARCHITECTURE_NOTES.md A2). |
| **What lands** | (a) ButtonElement on ABC + `on_click` behavior method + optional `_on_click_callback` field bound at construction (per spike's `elements.py`). (b) DialogElement on ABC (composite with `close()` behavior — emits `RemoveElement(self._id)` via `self._emit`). (c) JsonButtonDecoder + JsonButtonEncoder + JsonDialogDecoder + JsonDialogEncoder. JsonDialogDecoder constructs the Dialog first (empty children), then constructs each child Button with `on_click_callback=dialog.close` bound, then installs children — per spike's `codec.py`. (d) JsonInteractionEncoder + RemoveElement Update kind (per spike's `updates.py`). (e) Observer subsystem: subscription registry (`{topic: str → set[connection_id]}`, thread-safe, cascade on disconnect); MCP `subscribe`/`unsubscribe`/`publish` tools (FastMCP); hub-internal `hub.publish` / `hub.subscribe` API for hub-side callers (e.g. emit handler dispatching Events). **No `PublishMessage` wire kind** — generalized external-publisher pub/sub is deferred per ARCHITECTURE_NOTES.md A3. (f) Hub's emit handler dispatches Events → publish, Updates → accept + ship (per spike's `hub.py` `hub_emit`). (g) First Observer consumer: hub publishes `interaction.<element_id>` on each routed InteractionMessage. (h) `recv()` polling shim retained — reimplemented as polling adapter over Observer registry; deprecated; deletes in PR 12. (i) Interaction trace parity gate: records `(element_id, action, value)` triples and asserts equivalence vs PR-2 baseline for Button clicks. |
| **Out of scope** | Interaction-layer collapse — the 8 unmigrated inputs still use `Display.interact` / `ButtonPressed`. Collapse lands in PR 7. Other inputs (PR 7). Process supervision (later PR). |
| **Internal commit sequence** | (i) ButtonElement on ABC + on_click + JsonButtonDecoder + JsonButtonEncoder + headless behavior test (Button isolated; uses Recording renderer). (ii) Observer subscription registry + hub-internal `hub.publish`/`hub.subscribe` API + Hub emit-handler dispatch (Events→publish, Updates→accept+ship) + unit tests (RecordingObserver fixture). (iii) MCP subscribe/unsubscribe/publish tools + server-push notification path + integration test (agent receives `observed(topic, payload)` notifications). (iv) DialogElement + RemoveElement Update + JsonDialogDecoder (wires child button callbacks to dialog.close) + JsonDialogEncoder + headless dialog dismiss test (per spike R4). (v) Hub publishes `interaction.<id>` on routed InteractionMessage + recv() polling shim reimplementation over Observer + end-to-end test (click Button → on_click → publish → agent push). (vi) End-to-end DialogElement test: scene contains Dialog{Label, Button(Yes), Button(No)}; user clicks Yes; verify Dialog dismissed by HUB (RemoveElement applied to display_display) AND agent observer received the interaction push. (vii) Interaction trace parity gate added. Each commit passes `make check` + `make snapshot-parity` + local review. |
| **CI test name** | `tests/integration/test_button_inbound_e2e.py` — clicks Button on display, asserts on_click ran on Hub, asserts subscribed agent received `interaction.<id>` push. `tests/integration/test_dialog_self_dismiss.py` — spike R4 ported (click inside Dialog → Dialog dismisses via its own close() behavior). `tests/regression/test_interaction_trace_parity.py` — interaction trace parity gate. |
| **MCP-tool preservation (required acceptance)** | All 29 MCP tools continue to work. The new Observer MCP tools (subscribe/unsubscribe/publish) are additive. |
| **Rollback story** | If reverted, PR-2 Button + recv() polling restored; Observer subsystem and DialogElement removed; agents that subscribed lose their subscription gracefully on reconnect. The other 8 PR-2 inputs continue to work because the Interaction-layer is still in place. |
| **Worker / Evaluator** | `rmh` / `gvr`. `dna` (interaction design) consulted on Element behavior method shape + DialogElement contract. `mdm` consulted on MCP tool surface. `djb` consulted on Observer trust model. `rej` consulted on Composite + bound-callback pattern. |
| **Acceptance** | `make snapshot-parity` passes. End-to-end Button click → subscribed agent push works. Dialog self-dismiss works end-to-end (HUB removes Dialog from hub_display on any child button click; DISP mirrors). Interaction trace parity passes for Button. recv() polling shim works (existing agents unbroken). Grep verifies no `to_dict`/`from_dict` on ButtonElement or DialogElement. All 29 MCP tools continue to work. |

### PR 5 — Background-thread applet + in-fabric update path

| Field | Value |
|-------|-------|
| **Goal** | Prove the update-and-re-render path (not just initial render) via a separate-process Lux IPC applet that mutates Hub state from a background thread. |
| **What lands** | (a) `examples/counter_applet/` — Python applet, no MCP, connects to Hub via Lux IPC. (b) In-fabric `hub.apply(SetProperty(...))` API via Lux IPC (applet → hub). (c) Background thread inside applet increments a counter on a timer; each tick mutates the active `TextElement`'s content via `SetProperty`. (d) Hub thread-safety architecture committed in `DESIGN.md` (new ADR DES-037 — single-writer queue OR explicit lock; decision in writing before code). (e) Whole-tree re-encode on each Update (no scene-diff encoding — defer until measured). (f) `SetProperty` Update kind first consumer is the applet (per PY-RF-2). |
| **Out of scope** | Scene-diff encoding (defer until perf budget demands it — likely PR 11). `Progress` migration (PR 6 with other basics). `BatchUpdate` / `IncrementProperty` (YAGNI). |
| **Internal commit sequence** | (i) DES-037 ADR + Hub thread-safety implementation (queue or lock per ADR) + unit tests asserting thread safety on `hub.apply`. (ii) In-fabric `hub.apply(SetProperty(...))` API + Lux IPC wire support + unit test (in-process caller). (iii) Counter applet example + integration test asserting Display reflects increments across N ticks without race or dropped update. Each commit passes `make check` + local review. |
| **CI test name** | `tests/integration/test_infabric_applet.py` — spawns counter applet, observes Display reflects counter increments across 5 ticks. |
| **Rollback story** | If reverted, applet example removed, in-fabric API removed, thread-safety ADR reverted. PR-2 single-threaded MCP path continues to work. |
| **Worker / Evaluator** | `rmh` / `gvr`. `kpz` (perf) consulted on thread-safety architecture. `djb` consulted on in-fabric API trust boundary. |
| **Acceptance** | `make check` clean. Counter applet exercises the update path end-to-end with the existing TextElement as the visible target. Thread-safety test passes. DES-037 ADR committed. |

### PR 6 — Remaining 5 basics

| Field | Value |
|-------|-------|
| **Goal** | Mechanical replication of PR 3's Text pattern across the remaining 5 basics: Image, Separator, Progress, Spinner, Markdown. |
| **What lands** | 5 Element subclasses on the ABC; 5 JsonDecoders; 5 JsonEncoders (per-kind); 5 HubRenderer entries; 5 headless tests via Recording. Each kind ends-to-end in its own commit per Bar §5/§10. Old codec + ElementRenderer dispatch deleted per kind. |
| **Internal commit sequence** | (i) Image end-to-end. (ii) Separator end-to-end. (iii) Progress end-to-end. (iv) Spinner end-to-end. (v) Markdown end-to-end. Each commit passes `make check` + `make snapshot-parity` + local review. |
| **CI test name** | `tests/integration/test_basics_outbound_e2e.py` — one assertion per basics kind. |
| **Rollback story** | Per-kind: each basics can be reverted independently up to the PR boundary. |
| **Worker / Evaluator** | `rmh` / `gvr`. |
| **Acceptance** | `make snapshot-parity` for all 5 basics. ElementRenderer no longer dispatches any basics kind. |

### PR 7 — Remaining 8 inputs + Interaction-layer collapse (design-bearing)

| Field | Value |
|-------|-------|
| **Goal** | Migrate the remaining 8 inputs (Slider, Checkbox, Combo, InputText, InputNumber, Radio, ColorPicker, Selectable) to the ABC with per-kind behavior methods. After the last input migrates, delete the legacy Interaction-routing pipeline. **Design-bearing because the collapse is a one-time architectural change**, not mechanical replication. |
| **What lands** | (a) 8 input Element classes on the ABC with behavior methods (`on_value_change`, `on_toggle`, `on_select`, `on_change`). (b) 8 JsonDecoders + 8 JsonEncoders. (c) 8 HubRenderer entries that call behavior methods directly. (d) Interaction-layer deletion commit: `domain/interaction.py`, `domain/interaction_event.py`, `Display.interact()`, `DomainPump.route_interaction()`, `_is_button_click()`, `ButtonPressed` event member, `_emit_event → route_interaction` wire plumbing. (e) Affected tests updated in the deletion commit. |
| **Internal commit sequence** | (i)–(viii) Per-input end-to-end (Slider, Checkbox, Combo, InputText, InputNumber, Radio, ColorPicker, Selectable). (ix) **Interaction-layer deletion commit**: delete legacy pipeline; update all affected tests; single coherent commit. (x) Sweep ElementRenderer for remaining input dispatch entries. Each commit passes `make check` + `make snapshot-parity` + interaction-parity (PR 4) + local review. |
| **CI test name** | `tests/integration/test_inputs_inbound_e2e.py` (per-input). `tests/regression/test_interaction_layer_deleted.py` (grep + AST check confirming deleted symbols are gone). |
| **Rollback story** | Per-input up to the deletion commit. The deletion commit is the rollback boundary — reverting the PR restores `Display.interact` and the 8 PR-2 inputs in one go. |
| **Worker / Evaluator** | `rmh` / `gvr`. `dna` consulted on per-input behavior methods. |
| **Acceptance** | `make snapshot-parity`. All 8 inputs work via Observer push. Interaction-parity gate passes. Grep verifies zero refs to `ButtonClicked` / `ButtonPressed` / `Display.interact` / `DomainPump.route_interaction` / `_is_button_click`. |

### PR 8 — Layout family (design-bearing)

| Field | Value |
|-------|-------|
| **Goal** | Migrate the layout family (Group, Window, TabBar, CollapsingHeader, Tree, Modal — 6 composites) and introduce composite-invariant domain operations. **Design-bearing because it introduces new domain Updates**, not just new element kinds. |
| **Depends on** | PR 7 (Reparent test moves a ButtonElement between Groups). |
| **What lands** | (a) 6 layout Element classes on the ABC with `_children()` overrides and behavior methods (Window.on_close/on_minimize/on_maximize/on_move/on_resize, TabBar.on_tab_select, CollapsingHeader.on_toggle, Modal.on_close, Tree.on_node_expand/on_node_collapse/on_node_click). (b) 6 JsonDecoders + 6 JsonEncoders + 6 HubRenderer entries with `begin()`/`end()` composite bracketing. (c) `ReparentElement` + `ReplaceElement` Update kinds with Group as first consumer. (d) Cycle detection in `Display.apply` per PY-EH-1. `CycleError` event. (e) Old layout SceneManager + ElementRenderer code deleted per kind. |
| **Internal commit sequence** | (i) **Group + domain additions**: ReparentElement, ReplaceElement, CycleError + Group end-to-end + Reparent test + Cycle test — all one commit (PY-RF-2). (ii) TabBar end-to-end. (iii) CollapsingHeader end-to-end. (iv) Window end-to-end (most behavior). (v) Tree end-to-end. (vi) Modal end-to-end. (vii) Sweep remaining old layout paths. Each commit passes `make check` + `make snapshot-parity` + local review. |
| **CI test name** | `tests/integration/test_layout_e2e.py` — nested groups, tabbed scenes, collapsing, modals, reparent test, cycle-error test. |
| **Rollback story** | If reverted, `ReparentElement` / `ReplaceElement` / `CycleError` removed from domain unions; PR-2 layout paths restored. |
| **Worker / Evaluator** | `rmh` / `gvr`. `rej` consulted on Composite realization. |
| **Acceptance** | `make snapshot-parity` for layout. Reparent + Cycle tests pass. Recording renderer asserts the composite tree shape (begin/render/end sequence). |

### PR 9 — Graphics (Draw + sub-Composite draw commands)

| Field | Value |
|-------|-------|
| **Goal** | Migrate DrawElement + draw-command sub-Composite (Circle, Rect, Polyline, Triangle, BezierCubic, Line, TextGlyph). |
| **What lands** | (a) DrawElement on ABC. (b) Per-draw-command small renderers in `display/renderers/draw/`. (c) JsonDrawDecoder + JsonDrawEncoder (recursive draw-command codec). (d) ImGuiDrawRenderer refactored. (e) Recording renderer captures draw-command tuples. (f) Old SceneManager + ElementRenderer Draw paths deleted. |
| **Internal commit sequence** | (i) DrawElement on ABC + JsonDrawDecoder + JsonDrawEncoder + ImGuiDrawRenderer skeleton + Recording test for empty Draw. (ii)–(viii) Per-draw-command (Circle, Rect, Polyline, Triangle, BezierCubic, Line, TextGlyph), each a commit with renderer + test. (ix) Old Draw paths deletion. Each commit passes `make check` + `make snapshot-parity` + local review. |
| **CI test name** | `tests/integration/test_graphics_e2e.py`. |
| **Worker / Evaluator** | `rmh` / `gvr`. `kpz` (perf) consulted on draw-list interaction. |
| **Acceptance** | `make snapshot-parity` for Draw. Recording test per draw command. |

### PR 10 — Table family (design-bearing)

| Field | Value |
|-------|-------|
| **Goal** | Migrate TableElement with five behavior methods + detail-panel composition. **Design-bearing because Table's detail panel composes Layout Elements** (cross-family integration), not mechanical replication. |
| **Depends on** | PR 8 (detail panel composes Layout). |
| **What lands** | (a) TableElement on ABC with `on_row_select`, `on_filter_change`, `on_column_sort`, `on_detail_open`, `on_detail_close`. (b) JsonTableDecoder + JsonTableEncoder. (c) ImGuiTableRenderer refactored. (d) Recording captures table-render + per-row-render. (e) Old SceneManager Table branch + standalone table_renderer.py either folded or simplified. |
| **Internal commit sequence** | (i) TableElement on ABC + Decoder + Encoder + Renderer + basic Recording test. (ii) Filter behavior + test. (iii) Row-select. (iv) Column-sort. (v) Detail-panel (composes Layout). (vi) Old Table paths deletion. Each commit passes `make check` + `make snapshot-parity` + local review. |
| **CI test name** | `tests/integration/test_table_e2e.py`. |
| **Worker / Evaluator** | `rmh` / `gvr`. `edt` (information design) consulted on table behavior. |
| **Acceptance** | `make snapshot-parity` for Table. Five behavior methods testable. Detail panel renders nested Layout Elements correctly. |

### PR 11 — Plot family (design-bearing — perf budget enforcement)

| Field | Value |
|-------|-------|
| **Goal** | Migrate PlotElement with four behavior methods. **Design-bearing because perf-budget enforcement starts here** — the loose 50ms smoke from PR 3 tightens to a hard budget for a 1000-point single-series plot frame. If the budget is exceeded, the scene-diff encoding decision is forced (in this PR or a follow-up). |
| **What lands** | (a) PlotElement on ABC with `on_zoom`, `on_pan`, `on_axis_change`, `on_series_toggle`. (b) JsonPlotDecoder + JsonPlotEncoder. (c) ImGuiPlotRenderer refactored (uses imgui_bundle.implot). (d) Recording captures plot-render + per-series-render. (e) Tightened perf budget test. (f) If perf budget fails, scene-diff encoding shipped per measurement. (g) Old SceneManager Plot branch deleted. |
| **Internal commit sequence** | (i) PlotElement on ABC + Decoder + Encoder + Renderer + basic Recording test. (ii)–(v) Per-behavior (zoom, pan, axis-change, series-toggle). (vi) Tightened perf budget test. (vii) (Conditional) scene-diff encoding if perf fails. (viii) Old Plot paths deletion. Each commit passes `make check` + `make snapshot-parity` + local review + perf gate. |
| **CI test name** | `tests/integration/test_plot_e2e.py` + tightened `tests/perf/test_frame_budget.py`. |
| **Worker / Evaluator** | `rmh` / `gvr`. `kpz` (perf) consulted on per-series hot path; `edt` on axis behavior. |
| **Acceptance** | `make snapshot-parity` for Plot. All 24 element kinds on io-model. Perf budget for 1000-point single-series plot is met. |

### PR 12 — Sweep (capped)

| Field | Value |
|-------|-------|
| **Goal** | Delete orphaned carcasses from PRs 3–11. Update `system.tex` to describe the io-model shape verbatim. Final OO-ratchet bookkeeping. |
| **Cap** | If PR 12 grows beyond ~500 LoC + the system.tex rewrite, a prior PR cheated — investigate the source PR and fix it there; do not let PR 12 absorb the debt. |
| **What lands** | (a) Delete `recv()` polling shim (Observer push has been the default since PR 4; one-PR-cycle deprecation honored). (b) Delete the legacy `ElementRenderer` god class (no callers — every kind migrated). (c) Delete `SceneManager.handle_scene` / `apply_update` / `replace_scene` / `_scene_widget_state` / `_scenes` (no callers — Display owns scene state). (d) Delete `SceneMessage` whole-scene wire path if no consumers remain (verify by grep). (e) Update `docs/architecture/system.tex` to reflect io-model verbatim. (f) Final OO-ratchet bookkeeping; commit baseline updates. |
| **Internal commit sequence** | (i) Delete recv() polling shim. (ii) Delete ElementRenderer god class. (iii) Delete SceneManager legacy methods. (iv) Delete SceneMessage if orphaned. (v) Sweep tombstones / deprecation comments / re-exports. (vi) Single doc commit: system.tex update. Each code commit passes `make check` + `make snapshot-parity` + local review. |
| **Worker / Evaluator** | `rmh` / `gvr`. `djb` (security) audits removed code paths to confirm no input-validation logic is lost. |
| **Acceptance** | `make snapshot-parity` passes. Full MCP surface exercised. OO ratchet at target. Zero dead code remains. `docs/architecture/system.tex` reflects io-model verbatim. |

## Verification discipline

Unchanged from the original plan. Repeated here for self-containment.

Every PR follows this loop. The loop is the contract.

1. **Read this document, the relevant ADRs in `DESIGN.md`, and
   `domain-model.md` / `io-model.md` / `x11-model.md`.**
2. **Author a mission YAML** that cites the OO rules + DES-031/032/033 +
   io-model.md in the first 20 lines with one BEFORE/AFTER example. The
   YAML lives at `.tmp/missions/<pr-name>.yaml`.
3. **Dispatch with `ethos mission create --file <yaml>`** then
   **`Agent(subagent_type=<worker>, run_in_background=true)`** — both steps
   are required. Verify the worker is running via TaskList before
   considering the mission active.
4. **The worker commits incrementally.** Each commit:
   - Is one logical step.
   - Passes `make check`.
   - Is locally reviewed by `code-reviewer` and `silent-failure-hunter`
     agents before the next commit lands.
   - Is locally smoke-tested if it touches anything user-visible.
   - Does not accumulate more than 30 minutes of uncommitted changes.
5. **After all commits are in:** `make snapshot-parity` runs end-to-end.
   Manual smoke test of the affected MCP tools by the COO before push.
6. **PR opens.** Copilot review requested once. Polling loop monitors CI.
7. **Address every comment.** No suppressions. No "this is fine."
8. **Resolve threads, merge, delete branch, pull main.** Inner loop done.

## Test pyramid for the migration

| Tier | Where | What it covers |
|------|-------|----------------|
| **Characterization (PR 0)** | `tests/characterization/snapshots/` | Every MCP tool input → response captured on `main`. Replayed in CI on every PR. Catches output-level regressions. |
| **Domain unit (PR 1 onward)** | `tests/domain/` | `Display.apply(client, update)` returns the expected Event or Error. Ownership, cycle, type, duplicate-id invariants enforced. Single-runtime tests per `domain-model.md` §"Testability". |
| **Render unit (PR 3 onward)** — NEW | `tests/render/` | Per-element-kind render tests against `Surface.RECORDING`. Construct an Element, render it via the Recording renderer, assert on the captured calls. Closes the rendering-layer test gap that existed since the project began. |
| **Behavior unit (PR 5 onward)** — NEW | `tests/behavior/` | Element behavior methods (`on_click`, `on_value_change`, etc.) tested directly. Construct an Element, call its behavior method, assert on the emitted InteractionMessage shape. |
| **Family integration (PR 3 onward)** | `tests/integration/families/<family>/` | End-to-end exercise of one element family through the io-model pipeline (decoder → domain → renderer). |
| **Manual smoke (every PR)** | Run by the agent | `make install` + restart `luxd` + exercise the changed MCP tools in a real Claude Code session. Paste the actual output in the PR description. |

## Methods considered and rejected (path only)

The architectural target (DES-031, DES-032, DES-033, io-model.md, domain-model.md)
is **not under review**. Reviewers are scoped to migration **path** only.

For the record: three migration methods were evaluated by three architect
reviewers (`rej` Smalltalk/refactoring school, `kwb` TDD/XP school, `rop`
Plan 9 simplicity school) during the original plan drafting (2026-05-22).
Verdicts:

| Method | Description | Verdict | Reason |
|--------|-------------|---------|--------|
| **A — Horizontal Bands** | One architectural concept per PR across the whole codebase. ~7 PRs, each cross-cutting. | ITERATE (3/3) | The final "all kinds migrated and old paths deleted" PR in this method is a flag day. Empty infrastructure ships before any consumer. The shadow-Display tax has no production value. |
| **B — End-to-End Vertical Slices (amended)** | Infrastructure ships with its first production consumer (basics family) in one PR, then family-by-family migration with each PR deleting its own old path. | **SELECTED** | Each PR is a rollback-coherent unit. Infrastructure does not exist without a production caller (The Bar §5 / PY-RF-2). Two vocabularies never coexist for the same noun longer than one PR. Snapshot parity from PR 0 is the safety net. Adopted as the active plan; PR 3 of this revision continues the same method by pairing io-model infrastructure with basics refactor. |
| **C — Parallel Universe Cutover** | Build a complete second implementation under `domain/`. Cut over with a one-line-per-tool flip. Delete old code. 3 PRs. | REJECTED (3/3 REJECT) | The canonical big-bang rewrite pattern. PR 1 has no production consumer until the flip; the flip surfaces every assumption error simultaneously. |

The revised plan PRs 3+ continue Method B. The same vertical-slice discipline
applies: PR 3 ships io-model infrastructure with basics as its first consumer,
PR 4 brings the remaining basics onto the same shape; PR 5 brings inputs; and so on.

## Open work tracker

Track via `bd` in the `repo:lux` label. Bead state under v2.1:

| PR | Bead | Title |
|----|------|-------|
| 3  | `lux-c2c8` | port spike io-model foundation + Text outbound |
| 4  | `lux-wb55` | Button + Observer + inbound roundtrip + DialogElement |
| 5  | `lux-6ia8` | in-fabric applet + Hub thread safety + SetProperty path |
| 6  | `lux-uk5r` | remaining 5 basics on io-model |
| 7  | `lux-fban` | remaining 8 inputs + Interaction-layer collapse |
| 8  | `lux-jk8m` | Layout family migration (on io-model) |
| 9  | `lux-bina` | graphics (Draw + sub-composite draw commands) |
| 10 | `lux-rocc` | table family |
| 11 | `lux-qxmn` | plot family + perf budget enforcement |
| 12 | `lux-h1nh` | sweep (capped) |

Dependency chain: `lux-c2c8` → `lux-wb55` → `lux-6ia8` → `lux-uk5r` → `lux-fban` → `lux-jk8m` → `lux-bina` + `lux-rocc` → `lux-qxmn` → `lux-h1nh`. Each blocks the next; `bd ready` advances one PR at a time.

Do not work two PRs in parallel on the same working tree.

## References

- `docs/architecture/domain-model.md` — the algebra this plan realizes
- `docs/architecture/io-model.md` — the I/O architecture (Decoder / Element / Renderer)
- `docs/architecture/x11-model.md` — the topology PR 3 realizes (bare subprocess; operational supervision in a later PR)
- `docs/architecture/introspection-api.md` — already-implemented query pattern
- `docs/oo-refactor/resume.md` — current OO scores; updated after each PR
- `DESIGN.md` DES-030 — three-layer type model (wire / scene graph / snapshot)
- `DESIGN.md` DES-031 — Domain Model Across All Tiers
- `DESIGN.md` DES-032 — Element Owns Behavior, Not I/O
- `DESIGN.md` DES-033 — Renderer and Decoder Families with Asymmetric Cardinality
- `DESIGN.md` DES-034 — IPC and Rendering Are Decoupled — Renderer vs Encoder Distinction
- `DESIGN.md` DES-035 — Handler Routing — Ownership, Client Kind, and Pattern Are Three Independent Axes
- `DESIGN.md` DES-036 — Observer Pattern at the MCP Boundary
- `DESIGN.md` DES-037 — Hub thread-safety architecture (committed in PR 5)
- `punt-labs/.claude/rules/python-*.md` — the rules every mission YAML cites
