# Lux

Part of [Punt Labs](https://github.com/punt-labs). This repo must be checked out inside the `punt-labs/` workspace meta-repo so that org-wide configuration loads via Claude Code's ancestor directory walk:

- **`punt-labs/CLAUDE.md`** — org workflow, delegation model, Linear issue tracking, tool configuration
- **`.claude/rules/python-*.md`** (repo-local) — the canonical Python OO coding rules, scoped via `paths:` frontmatter (load on-demand when `.py` files are touched)
- **`punt-labs/.envrc`** — git identity, API keys from platform keychain
- **`punt-kit/standards/`** — canonical reference docs

If cloned outside the workspace, these rules and configuration will not be present.

**OO Python standards adopted 2026-05-13.** The codebase does not yet fully comply. Every commit must improve OO scores (`make check-oo`), never regress. Do not match existing code patterns that violate the rules — write new code to the standard and improve touched files incrementally.

Lux is a **visual output surface for Claude Code**. Vox gives agents a voice; Lux gives agents a screen. Clients submit UI to the Hub over MCP or REST; the Hub replicates element trees to the ImGui Display over Unix socket IPC.

- **Package**: `punt-lux`
- **Executables**: `lux` (CLI), `luxd-hub` (Hub daemon), `luxd-display` (Display renderer), `lux-beads` (beads applet)
- **MCP server**: `luxd` serves streamable HTTP at `/mcp`; the plugin connects directly (no per-session process)
- **Python**: 3.13+, managed with `uv`

## Mandatory Reading

The authoritative process document, [`docs/WORKFLOW.md`](docs/WORKFLOW.md), is
`@`-imported so it stays in context every session — it is the one source of
truth for the three development loops and has no per-turn backstop. On any
design conflict, [`target.md`](docs/architecture/target/target.md) wins. The
full linked index is in [Key Documents](#key-documents) below.

@docs/WORKFLOW.md

Three more source-of-truth documents are **non-autoloaded references** — linked,
not `@`-imported, because each is reachable on demand and consulting it every
session is pure context cost:

- [`docs/README.md`](docs/README.md) — the docs map and conflict triage. Read it
  when the documentation feels contradictory or you need the right doc for a
  question; it is an index, not a per-turn rule.
- [`target.md`](docs/architecture/target/target.md) — the canonical design
  target for the rewrite, authoritative on any design conflict. Read it before
  any architecture decision or design proposal (and see the `DESIGN.md` ADR-log
  consult rule in `docs/WORKFLOW.md`).

These org-wide standards from the `punt-kit` sibling repo are the merged source
of truth for how Punt Labs tools are built. They are **non-autoloaded
references** — linked, not `@`-imported — because each is already carried
per-turn by the `.claude/rules/python-*.md` files (`paths: ["**/*.py"]`) that
auto-load the moment an agent touches a `.py` file. The full standards are one
link away; consult them when a per-turn rule does not settle the question:

- [`python.md`](../punt-kit/standards/python.md) — the Python standard,
  including the mandatory OO ratchet lux runs. Carried per-turn by the 23
  `.claude/rules/python-*.md` rules.
- [`oo.md`](../punt-kit/standards/oo.md) — the object-oriented stance lux's
  Python answers to. Carried per-turn by `python-oo-adoption.md`,
  `python-oo-design-requirements.md`, `python-cohesion.md`,
  `python-coupling.md`, `python-encapsulation.md`, and
  `python-design-patterns.md`.
- [`architecture.md`](../punt-kit/standards/architecture.md) — the
  engine-and-clients model lux **is**: the Hub is the engine, the Display a
  decomposition of that one engine, and the MCP tools, CLI, library, and REST
  its thin client surfaces. Carried per-turn by `python-package-architecture.md`.

<!-- docs/README.md, target.md, python.md, oo.md, and architecture.md are
non-autoloaded references (linked above), not @-imports: the three punt-kit
standards are enforced per-turn by .claude/rules/python-*.md (paths: **/*.py),
and docs/README.md + target.md are on-demand design references. Only
docs/WORKFLOW.md stays @-imported (no per-turn backstop). This keeps a clean
session's instruction load under the harness 150k-char limit. -->
<!-- @docs/README.md -->
<!-- @docs/architecture/target/target.md -->
<!-- @../punt-kit/standards/architecture.md -->
<!-- @../punt-kit/standards/oo.md -->
<!-- @../punt-kit/standards/python.md -->

## Read This First

**This codebase is being rewritten toward a new architecture.** The repo
contains a mix of:

- current implementation
- migration scaffolding
- target-state architecture docs
- historical and alternative concept docs

Do not infer the intended architecture from whichever file you opened first.

- **Canonical design target:** `docs/architecture/target/target.md`
- **Docs map / conflict triage:** `docs/README.md`
- **Coding standard:** `docs/standards/python-oo.md`
- **Current/intermediate architecture:** `docs/architecture/system.tex`
- **Rule for conflicts:** if a document disagrees with
  `docs/architecture/target/target.md`, treat that target doc as the source of
  truth for design intent.

For implementation work, distinguish carefully between:

- **current behavior** — what the code and tests do today
- **target architecture** — what the rewrite is converging toward

Do not re-entrench legacy structure just because it is present in the tree.
When making design decisions, align new work with
`docs/architecture/target/target.md`. When writing Python, follow
`docs/standards/python-oo.md`.

## Architecture

### Rewrite status

The repository is mid-migration from an older display-server-centered design to
the newer Hub/Display architecture. Some modules already reflect the new model;
others are transitional or legacy. Agents must keep that distinction explicit.

- The **target architecture** is documented in `docs/architecture/target/`.
- The **current implementation** runs the Hub/Display split with all 25 wire
  element kinds on the Element-ABC path; some target capabilities remain
  transitional or unwired.
- The purpose of new work is generally to move the codebase toward the target,
  not to treat every current implementation detail as architecturally blessed.

### Target rendering model

The paragraphs below describe the architecture the rewrite is converging on.
They are not a claim that every module already implements this cleanly today.

Lux has multiple front doors into the Hub, especially MCP tools and direct
client APIs. Clients submit UI to the Hub, the Hub installs authoritative UI
objects into `HubDisplay`, and the Hub executes the real handlers. The Hub may
host long-lived headless app UIs as well as ad hoc agent-produced UIs.

App-level business logic flows through the Hub-managed publish/subscribe
channel, which is separate from the UI observer mechanism. A Hub-side handler
or a timer may publish app-defined topics such as `openTicket`,
`closeTicket`, or `markTicketInProgress`.

The Display receives a full copy of the UI it is rendering. It wraps handlers
for remote dispatch so interactions route back to the owning Hub instead of
executing locally. The default replication model is whole-UI resend on change:
if a rendered UI changes, the Hub can resend the whole affected UI and the
Display replaces its copy.

UI state crosses the Hub/Display boundary; render calls do not. Scene trees,
updates, serialized Lux element objects, and remote interaction messages may
cross the wire. ImGui calls and other renderer operations stay local to the
Display.

### Two-tier handler dispatch (D21)

The Hub says: "I am sending you a copy of a UI. If anyone interacts with it, I
will do the work." The Display says: "I will render that copy and forward
interactions back to the Hub." When the Hub sends a new scene, the Display
forgets the old one completely and repeats the cycle.

One event type (`ButtonClicked`), same element state on both tiers:

- **Hub:** `elem.fire(ButtonClicked)` → real handler runs (call_model → DialogModel, publish → Hub.publish)
- **Display:** `elem.fire(ButtonClicked)` → wrapped handler sends `RemoteEventHandlerInvocation` to Hub → Hub resolves element → fires real handler on its copy

The Hub and Display are separate processes, potentially on separate machines.
The MCP tool or client API talks to the Hub, not to the Display. The Hub
manages Display communication.

When a handler mutates Hub-side state (e.g., dialog dismissed via `mark_removed`), the Hub re-pushes the full scene tree to the Display. ImGui handles the diff — it renders whatever the current scene tree is.

### Key architectural boundary: protocol vs. rendering

Shared domain values, elements, messages, and framing now live in
`punt_lux.wire.model`. Hub state and replication now live in `punt_lux.hub`;
the old `punt_lux.domain` package is removed. PTY execution now lives in
`punt_lux.pty`; its shared stream contracts live in `punt_lux.wire.stream`.
Shared patch requests and their validation errors belong in
`wire.model.patch_batch` and `wire.model.write_errors`, not Hub. The model
facade's `Element` is the wire union; `ElementProtocol` is
the structural interface from `wire.model.element`. `ConnectionId` and
`ProgrammerError` live in kernel; protocol-aware display socket/process
lifecycle belongs to `service.display_paths`. No old-path alias modules exist.
Ready version `0.3` requires both pickle namespaces; older Displays must be
restarted with `make restart` or `lux service restart` before accepting scenes.

The **JSON protocol** (the `wire/model/` package — `elements/`, `messages/`) is the API surface. Agents describe what they want as a tree of typed elements — tables, text, plots, groups, buttons, sliders, etc. The **rendering layer** (the `display/` package — `render_loop.py`, the per-kind adapters in `display/renderers/imgui/`, `replica/menu_replica.py`, `texture_cache.py`, `idle_screen.py`) consumes the protocol and paints ImGui widgets. Changes to the protocol are contract changes — every consumer (agents, tests, the display) depends on them. Changes to rendering are implementation — they affect only the display process.

This separation means: protocol bugs break agents. Rendering bugs break the display. They overlap only when a new element kind is added (protocol + rendering in a single coordinated change).

### Three-tier distributed architecture

- **`luxd-display`** — ImGui renderer. Receives element objects from the Hub, wraps handlers with `remote_dispatch`, renders every frame. Native dependencies (`imgui-bundle`, `numpy`, `Pillow`) live here behind the `[display]` optional extra.
- **`luxd-hub`** — Session hub. Fronts everything through the typed `Operations` facade (`operations/`); stores authoritative scenes in `HubDisplay`, menus in `HubMenuRegistry`, and sessions in `HubClientRegistry`; serves MCP (streamable HTTP) and REST (FastAPI, same port) as thin adapter surfaces; pushes replicas to the display via the HubReplicator; receives and dispatches remote handler invocations from display clicks. The CLI is a third thin client over REST (`LuxClient`). The plugin's MCP config connects directly to `http://127.0.0.1:8430/mcp` — no per-session process in the tool path.
- **Lux applets** — standalone programs on the library client (REST + the WebSocket listen leg) that own menu entries and service clicks (DES-063). Species: machine-global daemon (vox's music player, in the vox repo), session-bound applet (`lux-beads`, spawned by the plugin's session-start hook, parent-pid watch, dies with the session), on-demand renderer (z-spec). Bundled applets live in `applets/`; each Punt Labs tool ships its own applet in its own repo.

This is the rewrite target, documented in
`docs/architecture/target/target.md`,
`docs/architecture/target/topology.md`, and
`docs/architecture/target/ui-model.md`. The shipped core follows this
Hub/Display split; the target also describes capabilities beyond the
current entry-point wiring.

The shipped core includes `HubDisplay`, Hub-scoped pub-sub, and all 25 wire
element kinds on the ABC path with remote handler wrapping and Hub-side
re-dispatch.

### Key packages and modules

| Module | Responsibility |
|--------|---------------|
| `service/` | Shared install and daemon lifecycle: supervisor backends, migration sweeps, service managers, project config, permissions, hook decisions and diagnostics |
| `kernel/` | All shared implementation primitives now live inside the package: timing, tracing, bounded I/O, process/connection identity, credentials and code runtime; no root-module aliases |
| `kernel/display_defaults.py` | Shared display round-trip timeout, independent of Hub implementation |
| `hub/luxd.py`, `hub/mcp_*.py`, `hub/ws_*.py`, `hub/hub_{composition,lifespan}.py` | Hub gateway, transports, sessions and lifetime composition, moved physically into the Hub package |
| `display/luxd_display.py`, `display/__main__.py` | Display renderer entry point and module executable; `service/display_foreground.py` owns foreground launch without a CLI-to-Display import |
| `cli/hook_cli.py` | Headless hook CLI, no longer a root single-file module |
| `service/terminal_service.py`, `service/terminal_enablement.py` | Terminal supervisor registration and opt-in lifecycle, independent of PTY execution |
| `commands/` | Separate shared execution/formatting layer allowed to import only kernel and wire; both Hub and CLI may import it |
| `kernel/hub_paths.py`, `kernel/hub_defaults.py` | Process-independent Hub metadata paths, liveness checks and default port, shared by lifecycle and transport clients |
| `display/render_loop.py` | `RenderLoop` — ImGui render loop and coordinator — **778 lines, still over the 300-line target; remaining debt from the original `display.py`** |
| `display/renderers/imgui/` | Per-element-kind ImGui adapters (one module per kind; every leaf inherits `LeafRenderer`) |
| `display/replica/` | The Display's replica of what the Hub sent: `SceneReplica` (scene state, frame composition), `FrameBook`, `WidgetStateStore`, `MenuReplica` (the replicated menu state both menu surfaces render) |
| `display/texture_cache.py` | Image texture upload with bounded LRU eviction (`TextureLru`) and a coupled data-key memo |
| `display/idle_screen.py` | Idle splash when no scene is active |
| `wire/model/elements/*.py` | JSON element types (25 kinds, all on the Element-ABC path — one module per kind with a sibling codec; the legacy family modules were deleted in B7) |
| `wire/model/messages/*.py` | Wire message types across modules: lifecycle, scene, menu, introspect, `observer` (Agent Subscribe), `remote_invocation` (D21 `RemoteEventHandlerInvocation`), registry |
| `operations/` | Hub-owned `Operations` facade, `HubPorts`, and concern classes; public request/result values live in `wire/operations/` |
| `wire/operations/`, `wire/ops/` | Public operation requests/results and per-family operation Protocols, shared by SDK and commands without loading the Hub |
| `service/service_spec.py` | Public `ServiceSpec`, exported from `punt_lux.service`, configures reusable launchd/systemd backends; Lux's Hub/Display specs are unchanged |
| `rest/` | Typed FastAPI surface on luxd (`RestSurface`, six concern routers, one `OpError`→HTTP table) |
| `client/facade.py` | `LuxClient` — public library facade; its private REST transport serves the CLI and library |
| `client/` | Runtime-isolated SDK: WebSocket/HTTP transports and direct async operation-port accessors; no commands or Hub imports |
| `wire/model/identity_headers.py`, `wire/model/header_value.py` | Shared identity-header contract and header encoding, used by both SDK and Hub adapters |
| `wire/model/client_identity.py`, `wire/model/applet_name_format.py` | Shared client identity declaration and applet-name contract, independent of Hub behavior |
| `tools/server.py` | FastMCP instance and per-session identity binding; transport lifecycle lives in `hub/mcp_transport.py` and `hub/mcp_session.py` |
| `tools/{read,write,composite,display_write,subscribe}_tools.py` | MCP tool definitions — zero-logic adapters over the `Operations` facade, split by concern |
| `hub/display_link.py` | `DisplayLink` — the Hub's (luxd's) sole Unix-socket client to the display; constructed only in `hub/clients.py`, guard-enforced |
| `applets/` | Lux applets (DES-063): `AppletLeg` (listener + register-on-connect + click servicing), `SessionWatch` (parent-pid lifetime), `beads/` (`lux-beads` — the first bundled applet: `applet.py`, its service, the `bd` runner and board) |
| `beads/browser.py` | `BeadsBrowser` — loads and orders beads issues; `beads/beads_board.py` builds requests and `wire/model/compositions/table_composition.py` builds the Hub-side table UI |

25 wire element kinds covering ImGui's core primitives. Primary consumers: beads issue browser (`client.scene.table()`), dashboards (`client.scene.dashboard()`), custom rendering (`draw` element). `SplitPaneElement` is a `GroupElement` refinement with the same JSON kind, not a 26th wire kind.

Start with `docs/architecture/target/target.md`. Use
`docs/architecture/target/ui-model.md` for the authoritative UI model and
`docs/architecture/target/topology.md` for the target process model.

### Vision

**v1 (current):** A display canvas for Claude Code agents — tables, data, dashboards — **plus agent↔user interaction**: the agent can ask the user a question and receive the response. That loop shipped with the Hub/Display io-model (Hub-side handler dispatch + `recv`/`publish`, the Dialog/Checkbox/Button path). The protocol is the API surface — agents describe JSON, Lux renders it.

**v2 (future):** **Full ImGui element coverage** — every ImGui widget available as a Lux element — evolving toward a Pharo-inspired live environment where MCP is the message bus and Lux is the Morphic rendering layer (agent introspects and reshapes UI at runtime; system browser, inspector, workspace).

**Guiding constraint:** v1 hones the data-display core and the ask-user/get-response interaction loop. Completeness of the ImGui element set is a **v2 goal** — new element-kind work is tracked with the `v2` Linear label and does not block v1. **Lux applets are in scope** (operator ruling 2026-08-01, DES-063): external programs on the library client owning menu entries — bundled ones in `applets/` for software that is not Punt Labs-built (beads; top/clock/irc-class candidates), tool-shipped ones in each tool's own repo (vox's music player). What stays out of scope: applications running inside the display process, and in-display code execution.

## Logging

The CLI, Hub (including HTTP MCP), Display, terminal daemon, Python hook
dispatcher, and detached helpers all share the private, rotating
`~/.punt-labs/lux/logs/lux.log` sink. Filter by logger name to distinguish
subsystems. Use the entry-point adapter in `logging_config.py`; libraries
declare module loggers and do not configure sinks. The default durable
level is INFO; set `LUX_LOG_LEVEL=DEBUG` in a process's environment for
more detail. Keep diagnostics free of credentials, content and private
identifiers; final-record redaction is defense in depth.

Hub operation and Display first-paint durations are separate typed usage telemetry in
`~/.punt-labs/lux/telemetry.db`, not diagnostic log records.
`LUX_TELEMETRY=off` or `PUNT_TELEMETRY=off` disables capture.

Do not add ad-hoc debug prints — use the logger at the appropriate level. **Nothing on the per-frame render path may log.** ImGui repaints every element every frame, so one line there is sixty lines per element per second; the `@trace` decorator belongs on event-driven paths (a click, a decode, a send), never on a renderer's `render`. `tests/test_per_frame_tracing.py` enforces this.

## Code Quality

### OO Python is non-negotiable

Default Python — procedural functions operating on dataclasses, `| None` everywhere, `str` fields with comments listing valid values — fails this project's quality bar. The rules in `.claude/rules/python-*.md` exist precisely to fix that bias and they are NOT load-bearing unless the agent (or the mission author writing a YAML) explicitly cites them. The user has had to repeat OO 101 across multiple sessions while agents shipped procedural code. Stop.

**Five rules, cited verbatim in every mission YAML for wire/model/data work:**

1. **Classes own data AND behavior** (PY-OO-5). A dataclass with module-level `_<kind>_to_dict(m)` / `_<kind>_from_dict(d)` functions IS procedural code in dataclass clothing. The functions become `to_dict(self)` instance methods and `from_dict(cls, d)` `@classmethod`s. If you find yourself writing a function that takes a dataclass parameter, reads multiple fields, and returns a derivation — that function belongs ON the class.

2. **Families share via Protocol, not base class.** Structural typing. `runtime_checkable` Protocol with `TYPE: ClassVar[str]`, `to_dict`, `from_dict`. Every wire class satisfies it implicitly. No abstract base. No `BaseElement`. Tests assert `isinstance(x, WireType)` for the family contract.

3. **Composition over inheritance** (PY-IC-1). Shared shapes — e.g., `[x, y]` point pairs across draw commands — become small typed value classes (`Point2`) composed into containing classes, not parent state. Helpers like `_strip_none` are module-level utility functions called from instance methods, not methods of a base class.

4. **No `str` with a comment listing valid values.** Replace with `Literal[...]`. `layout: str = "rows"  # "rows" | "columns" | "grid"` → `layout: Literal["rows", "columns", "grid"] = "rows"`. The comment was the type system giving up; Literal is the actual type. Every `str` field with a comment listing values is a violation. Audit and fix when touching the file.

5. **Reduce `| None` types.** Each Optional is a place the type system gave up. Per-field, ask: is this really "absent", or is it a discriminated state? `color: str | None = None` (meaning "renderer default") → `color: str = "#FFFFFF"`. `error: str | None = None` on a response → discriminated `OkResponse` vs `ErrorResponse`. `path | data` validated one-or-the-other → discriminated `PathImage` vs `DataImage`. Genuinely-optional attributes (e.g., `tooltip`) stay.

**Mission YAMLs for wire/model/data work open with the rules in scope, citing IDs and showing one BEFORE/AFTER example.** Sub-agents inherit the training-data bias toward procedural Python unless the prompt is explicit; explicit means cite-and-show. Don't dispatch a sub-agent on wire/model/data work without these in the YAML's first 20 lines.

### Module-size constraints

**`display/render_loop.py` (778 lines, `RenderLoop`, formerly `display/server.py`/`DisplayServer`) must be decomposed further** — it is over the 300-line target. Any PR that adds rendering logic to it without extracting existing code will be rejected. The original `display.py` was 4,208 lines; PR #158 split it into the `display/` package; `render_loop.py` still carries the bulk of the original mass. (`element_renderer.py` and the other legacy renderers were deleted with the legacy render path in B7.)

**Protocol codec debt — resolved by the element migration.** Every element kind now has a class-based codec beside its element module (`JsonXEncoder`/`JsonXDecoder`); the legacy family modules with module-level `_<kind>_to_dict` functions were deleted in B7. The remaining procedural corners live in `wire/model/messages/*.py` — fix a message codec onto its class when you touch the file.

**MCP tool boilerplate — resolved.** Every tool under `tools/` (`read_tools.py`, `write_tools.py`, `composite_tools.py`, `display_write_tools.py`, `subscribe_tools.py`) is a grep-provable parse-call-format adapter over the `Operations` facade, and the REST routes are the same adapters over HTTP. New capabilities are added as operations; the surfaces inherit them.

**Ratchet tooling:** `uv sync` installs the dev-only PyPI package
`punt-oo-ratchet==0.6.0`. The `oo-ratchet oo`, `oo-ratchet coupling`, and
`oo-ratchet suppressions` commands power the Makefile gates; do not embed
copies under `tools/`. Existing root baselines and audit logs stay committed.

**OO ratchet:** `make check-oo` (part of `make check`) compares current OO scores against `.oo-baseline.json`. It passes only if no metric regressed on touched files and at least one metric improved. It fails if any metric got worse or nothing improved.

**Why the ratchet exists — and how to work with it, not against it.** The ratchet is a tech-debt paydown mechanism: like paying down a loan, you retire OO debt a bit at a time, on every change, *including in parts of the code unrelated to the feature you came to write*. This is deliberate, and it is counterintuitive because it means **taking on additional scope on purpose**. When you touch a module, the expectation is a real, medium-scale OO improvement to it — extract a class, move behavior onto the data, replace a `str`-with-comment with a `Literal`, kill an Optional — not the smallest possible edit that clears the "at least one metric improved" bar. **Squeezing one trivial change in under the limit and moving on is a failure of the mechanism, even when the check goes green.** A lot of time gets wasted fighting the ratchet over tiny deltas and near-misses; that time should instead go straight into a substantive improvement to the module you are already sitting in. Bigger, deliberate improvements clear the ratchet trivially and pay the debt down far faster than a stream of minimal ones. When in doubt: improve more, not less. Make the medium-scale improvement at every opportunity.

**PRs do not need to be "pure," and purity is never a reason to hold back an improvement.** These PRs are agent-reviewed and squash-merged — the whole branch collapses to one commit on `main`, so the "normal fencing" (one-concern-per-PR, keep-the-diff-minimal, split-out-the-unrelated-bit) does not apply. Do not spend time policing scope: a docs tweak, an OO/complexity paydown, or an adjacent bug fix riding along with a feature PR is welcome, not a violation. **The operator explicitly rejects rules that make it harder to improve code.** If you are in a file and can make it better, do it — never revert or defer a genuine improvement to keep a PR "clean," and never open a separate PR solely for purity. The one real constraint is mechanical, not stylistic: when multiple agents share one worktree, don't let them edit the same uncommitted lines simultaneously — sequence them so no one's work is clobbered. That is about not losing work, not about scope.

Workflow:

1. Write code that improves OO quality on the files you touch.
2. `make check` runs `check-oo --check` automatically. If it fails, fix the regression.
3. After all checks pass, run `make update-oo` to write the new baseline.
4. Stage `.oo-baseline.json` and `.oo-audit.jsonl` with your commit — they are committed files.

Bootstrap (first time only): run `make update-oo` to create the initial baseline. After that, the ratchet is active.

**Do not negotiate with the ratchet.** Do not edit `.oo-baseline.json` by hand. Do not suppress `check-oo`. Do not argue a regression is "acceptable." If the ratchet fails, improve the code until it passes. The ratchet is the quality standard's enforcement — working around it defeats the purpose.

**Org standards override review tools.** Qodo, Bugbot, and Copilot are advisory. When a review suggestion conflicts with rules in `.claude/rules/python-*.md`, the rules win. Read the rules before accepting a reviewer's suggestion. PY-CC-1 (`__new__` as constructor) is the most common conflict.

**Verify outputs, not just metrics.** After writing a file, open it and read the content. `make check` passing does not mean the feature works — it means the code compiles and tests pass. Those are necessary but not sufficient.

- **Read `Makefile` before code changes.** Do this early in every coding session in Lux. Do not guess what the repo’s gates are, do not assume another repo’s workflow applies here, and do not substitute ad-hoc `pytest`, `ruff`, or `mypy` commands for the repo-defined workflow until you have read the Make targets.
- **Run the full quality gate on every code change.** In Lux that means `make check`. Focused commands are fine while iterating, but you are not done, and you must not report a code change as complete, until `make check` passes. If `make check` fails anywhere, fix the failure or explicitly report the remaining blocker.

- `make check-oo` — OO ratchet against baseline.
- `make update-oo` — update baseline and append to audit log after improvements.
- `make report` — full diagnostics including per-file OO breakdown.
- `make metrics` — ABC complexity analysis.
- `make coverage` — test coverage HTML report.

**Makefile note:** `make check` uses `uv run --extra display` for all targets. pyright runs via `npx pyright` (not `uv run pyright`) because the display extras pull native dependencies that confuse uv's pyright wrapper.

## Testing

### Pyramid

| Layer | Make target | Runs in CI | What it covers |
|-------|-------------|------------|----------------|
| Unit | `make test` | yes | Protocol types, serialization, scene management, element builders, client |
| Visual | manual | no | ImGui rendering correctness (requires display server running) |

### What good testing means in this project

Lux's biggest testing gap is the rendering layer. `display/render_loop.py` is large and has no automated visual regression tests — correctness is verified manually by looking at the display. This means:

- **Protocol tests are the primary safety net.** Every element kind must have tests that verify serialization roundtrips (build → serialize → deserialize → compare). Protocol changes without tests are unshippable.
- **Scene tests verify composition.** Multiple elements in a scene, tab switching, window management, detail panels — these must be tested at the scene level even though visual rendering is manual.
- **Further decomposing `display/render_loop.py` is prerequisite for meaningful render tests.** Until it is split into testable units, the rendering layer remains undertested. Every change that includes extraction improves the testability of the codebase.

### Key relationships

- **Vox** (`../vox/`) — audio counterpart; follows the same plugin/release patterns
- **claude-plugins** (`../claude-plugins/`) — marketplace catalog entry

## Formal Verification (z-spec)

Some defects are not fixable by writing another test. When a change involves
**concurrency, a lock discipline, a stateful protocol, or a safety-critical
state machine**, model-checking finds in one pass what empirical testing chases
across many rounds. The display singleton lifecycle proved it: 13 review rounds
on lux-w8t5 plus 3 on lux-h29e, each surfacing another interleaving — then one
ProB model-check verified all five invariants and deadlock-freedom exhaustively,
and the coverage audit exposed that "passing" tests were exercising a
monkeypatched premise, not the real mechanism.

**z-spec is REQUIRED — not optional — for a change in any of these classes:**

- **Concurrency / interleaving.** Multiple processes or threads contending for a
  shared resource (sockets, files, locks): spawn/reap/cleanup lifecycles, the
  Hub/Display dispatch path, connection registries. If two agents can interleave
  on shared state, model-check the interleaving.
- **Lock disciplines.** Any change that introduces or alters a lock, especially
  more than one. Deadlock-freedom must be **proven**, not assumed — encode the
  acquisition order and run the ProB deadlock check.
- **Stateful protocols / lifecycle state machines.** Anything with a safety
  invariant of the form "at most one X", "never X while Y", "operations must
  follow order Z", or a defined set of states and transitions.
- **The recurrence signal (the hard rule).** The MOMENT the *same class* of
  defect surfaces across **two or more** fix/review rounds — stop. Do not open a
  third empirical round. Formalize the state machine and model-check it.
  Recurrence means the problem is a state-space problem, and the state space is
  finite and checkable.

**The workflow (the z-spec plugin skills):**

1. `z-spec:code2model` — model the stateful entity as a Z spec (flat state
   schema, operations, invariants; bounded carrier, single `Init` for ProB).
2. `z-spec:check` — `fuzz` type-check; must be clean.
3. `z-spec:test` / probcli `-model_check` — model-check **every** invariant AND
   the deadlock check over a bounded carrier (setsize 2–3 usually exhibits the
   races). **This is the merge gate** for the change — "provably no interleaving
   violates it", not "the flaky test passed 50 times".
4. **Fidelity check (mandatory).** The model must reproduce the *known* defect
   when the fix is removed (drop the lock → ProB returns the exact bad
   interleaving). A model that cannot reproduce the bug it guards against is too
   abstract to trust — refine it until it can, then show the fixed design has no
   such trace.
5. `z-spec:partition` + `z-spec:audit` — derive the test partitions from the
   spec and audit which our tests actually cover. Fill every gap. A passing test
   that stubs the mechanism is a gap, not coverage.
6. Commit the spec (`docs/<name>.tex`) as a **regression artifact**; re-run
   `fuzz` + the model-check whenever the modeled code changes.

Purely sequential logic, single-element rendering, a data-format tweak do **not**
need z-spec — a roundtrip or scene test suffices. z-spec is for the
interleaving/state-machine class, where testing samples and model-checking
proves. Reference model: `docs/display_lifecycle.tex` +
`docs/display_lifecycle_coverage.md`. Toolchain: `/z-spec:setup` installs fuzz +
probcli.

## Ethos & Delegation

Identity: `agent: claude` per `.punt-labs/ethos/ethos.yaml`. The registry at `.punt-labs/ethos/` is **vendored** (not a submodule) and holds only lux's roster — 12 identities on the `lux` team (`teams/lux.yaml`), not the org's full engineering roster. Upstream changes to `punt-labs/team` don't propagate; a real org-standard change worth pulling in gets deliberately synced by copying the specific files. Persona tuning for lux (e.g. rmh's tool list) lives here and never leaks to other repos.

All code delegation uses ethos missions. Every non-trivial delegation has two phases: (1) **design mission** — describes problem, constraints, and invariants but does NOT prescribe a write set; (2) **implementation mission** — uses the write set produced by the design phase. The design mission's output IS the write set — the specialist decides what to create, split, or extract.

The COO must not read implementation files before writing the design spec. "Add a handler to `display/render_loop.py` at line 923" is a predetermined write set that prevents the specialist from making design decisions. "Add a query operation that returns display metadata — the codebase has a generic query infrastructure, the implementation must follow code quality standards" gives the specialist latitude to decompose and restructure. This is how the original `display.py` grew to 4,208 lines and `display/render_loop.py` is still ~1,100 — write sets were predetermined to existing files instead of letting the specialist extract.

### Why these pairings

Lux spans two domains that require distinct expertise: (1) **visual/UX** — element design, layout, theming, composability — owned by `edt` (information design) and `dna` (interaction design), with `kpz` for GPU/performance; (2) **wire/model/infrastructure** — JSON element types, Unix-socket IPC, scene management, MCP tool surface — owned by `rmh`/`gvr` for Python, `mdm` for CLI, `djb` for IPC trust boundary. The protocol is the contract between these domains — changes to it require a worker from one domain and an evaluator from the other.

| Task type | Worker | Evaluator |
|-----------|--------|-----------|
| New element kind / protocol extension | `edt` (Tufte) | `dna` (Norman) |
| Visual / layout / theming change | `dna` | `edt` |
| Python implementation (rendering, IPC, scenes) | `rmh` (Hettinger) | `gvr` (van Rossum) |
| Protocol amendment (JSON patch, Unix-socket schema) | `gvr` | `rmh` |
| CLI surface (`lux …` commands, plugin shell) | `mdm` (McIlroy) | `rop` (Pike) |
| MCP tool surface (`show`, `update`, `clear`, etc.) | `mdm` | `rmh` |
| GPU / perf-sensitive rendering paths | `kpz` (Karpathy) | `rmh` |
| Security review (socket auth, IPC trust boundary) | `djb` (Bernstein) | `rmh` |
| Release / packaging / hybrid plugin pipeline | `adb` (Lovelace) | `mdm` |
| Frame-rate / latency budget verification | `kpz` | `edt` |

### Pipeline selection

Use `standard` pipeline (design → implement → test → review) for new elements, protocol changes, or any work touching the JSON wire format. Use `quick` (implement → review) only for documented bugfixes inside an existing element that don't change the protocol. Review-cycle fix rounds (Qodo/Bugbot findings) use bare `Agent()`, not missions. Treat the JSON protocol as the API surface — any change demands an evaluator distinct from the worker.

## Issue Tracking

Linear is the sole tracker of record for lux: the Punt Labs team, issues
labelled `repo:lux`, listed in the shared `lux` view. `.punt-labs/punt/CLAUDE.md`
(imported below) carries the full rules for reading and writing issues.

Create, claim (In Progress), finish (Done) and cancel issues in Linear, with
the `repo:lux` label plus a type label (`Bug`, `Feature`, `Improvement`,
`Epic`). Epics are Linear projects.

## Session Queue

When working a batch of issues in a session, create corresponding `Task`
entries via `TaskCreate` for the session subset. Linear is the durable
cross-session tracker of record; the task list is the session-visible workqueue
you can monitor in real-time in the Claude Code UI.

Workflow:

1. Pick a realistic batch of open, unblocked `repo:lux` issues in Linear.
2. Set each issue in the batch to In Progress in Linear.
3. `TaskCreate` one entry per claimed issue with the issue ID in the title.
4. Work through them in order. Mark the issue Done in Linear when done, and
   mark the Task complete immediately after.
5. Uncompleted tasks at session end carry over as open Linear issues — no extra
   cleanup needed.

Do not use `TaskCreate` for work that spans multiple sessions. Linear is the
record; tasks are the display.

## Development Loop

The loops are specified once, in [`docs/WORKFLOW.md`](docs/WORKFLOW.md) —
imported above, so always in context. It is the single source of truth for the
three levels (backlog, PR, mission), the review-agent selection, the demo
gate, and the merge gate. Do not restate loop rules here.

PR review follows punt-kit/standards/pr-review.md: local review (qodo review + silent-failure-hunter + code-reviewer) before the PR, then Qodo and Bugbot once at open, at most two rounds, Copilot only on request.

Two lux-specific operational facts the loops rely on:

- **`make restart` is the only correct way to pick up code changes** — it
  rebuilds, installs, and restarts the Hub, Display, and running terminal
  daemon. Restarting `luxd-pty` ends the terminal sessions it owns.
  Use `make reload` for Hub-only changes.
- **Docs-only changes have no entry point to run**; markdownlint plus a
  read-through is their verification at the demo gate. Markdown under
  `plugin/` is behavior, not docs, and is demoed (`demo_exempt` in
  `docs/WORKFLOW.md`).

## Release

Use `/punt:auto release [version=X.Y.Z]`. Lux is a CLI + Plugin Hybrid — releases publish to both PyPI (`punt-lux`) and the marketplace. Dev plugin testing: `claude --plugin-dir plugin` loads `lux-dev` alongside prod — the argument is the plugin root, which is `plugin/`, not the repo root.

**Workspace version step:** in release Phase 2, immediately after the root version bump and before the lock refresh, run `make sync-workspace-version`. It mirrors the root version into `punt-lux-client`, `punt-service` and the root's exact dependency pins; include all three manifests and `uv.lock` in the release commit. Build with `uv build --all-packages`. `tests/test_workspace.py` rejects drift. See `docs/workspace.md`.

**The shippable plugin surface lives in `plugin/`.** `plugin/.claude-plugin/`, `plugin/commands/`, `plugin/hooks/`, and `plugin/skills/` are the only directories a marketplace install fetches: the catalog entry uses Claude Code's `git-subdir` source (`"path": "plugin"`), which is a blobless partial clone plus a cone sparse-checkout. Nothing outside `plugin/` may be referenced from inside it, and `${CLAUDE_PLUGIN_ROOT}` resolves to `plugin/`. The wheel is unaffected — `uv_build` ships `src/punt_lux` only, so the plugin surface has never been packaged.

Release scripts: `scripts/release-plugin.sh` (swap `lux-dev` → `lux`), `scripts/restore-dev-plugin.sh` (restore dev state after tag).

**Gotcha from v0.5.0:** `.gitignore` must cover all transient files (`.coverage`, `*.ini`, `demos/`, `__pycache__/`, LaTeX artifacts) — `punt release` checks for a clean working tree.

## Key Documents

**Read before writing code** (the first two are `@`-imported in [Mandatory Reading](#mandatory-reading)):

- [`docs/architecture/target/target.md`](docs/architecture/target/target.md) — **start here**; canonical design target for the rewrite. On any conflict, this wins.
- [`docs/README.md`](docs/README.md) — docs map and conflict triage; says what is current vs legacy vs concept.
- [`docs/standards/python-oo.md`](docs/standards/python-oo.md) — mandatory OO implementation standard and ratchet policy.

**Target architecture:**

- [`docs/architecture/target/topology.md`](docs/architecture/target/topology.md) — process topology target.
- [`docs/architecture/target/ui-model.md`](docs/architecture/target/ui-model.md) — authoritative UI model target.
- [`docs/architecture/target/element-contract.md`](docs/architecture/target/element-contract.md) — the Element-ABC contract every migrated kind satisfies.
- [`docs/architecture/target/introspection-api.md`](docs/architecture/target/introspection-api.md) — introspection and control surface.

**Element migration (completed 2026-07-27, epic `lux-xs7r`):**

All 25 element kinds are on the Element-ABC / Hub-Display path; the legacy path is deleted. The design docs below stay as historical record:

- [`docs/architecture/migration/README.md`](docs/architecture/migration/README.md) — the migration approach ([DES-041](DESIGN.md)): **fork, don't mix**, ordered by testability, per-element verify-as-you-go.
- [`docs/architecture/element-migration-audit.md`](docs/architecture/element-migration-audit.md) — per-element map of all 25 kinds (all now migrated).
- [`docs/architecture/migration/progress-element-design.md`](docs/architecture/migration/progress-element-design.md) — the display-only-leaf worked example for `progress`; read it for the leaf pattern.

**Decisions, specs, product:**

- [`DESIGN.md`](DESIGN.md) — ADR log (80+ entries, appended in order). **Consult it before proposing any design** — a design mission, a design review, or a naming/UX/architecture suggestion made directly to the operator. The ADR headings are the index: `grep '^## DES-' DESIGN.md`, pick every heading that touches the topic, read those entries in full, and cite the ones you built on (or supersede) in the proposal. A proposal that cites no ADR on a topic the log covers has skipped this step. Do not read the file start to finish; do not re-litigate a settled decision without new evidence. Append new ADRs at the end; do not reorganize existing ones.
- [`docs/display_lifecycle.tex`](docs/display_lifecycle.tex) → [`docs/display_lifecycle.pdf`](docs/display_lifecycle.pdf) — the ProB-verified display-singleton lifecycle spec (DES-037/038); partition [coverage](docs/display_lifecycle_coverage.md). Keep the PDF in sync with the `.tex` (rebuild + commit together).
- [`prfaq.tex`](prfaq.tex) → [`prfaq.pdf`](prfaq.pdf) — the Working Backwards PR/FAQ (product direction, hypothesis stage). Update when the change shifts product direction.
- [`CHANGELOG.md`](CHANGELOG.md) — release history; add entries under `## [Unreleased]`.
- [`README.md`](README.md) — user-facing overview; update when user-facing behavior changes.

**Current/intermediate — NOT the target:**

- [`docs/architecture/system.tex`](docs/architecture/system.tex) → [`docs/architecture/system.pdf`](docs/architecture/system.pdf) — the current/intermediate architecture, not the rewrite target. Aligns to `target.md` on any conflict.

Do **not** use [`docs/concepts/*`](docs/concepts/) to guide implementation. Those
are alternative concepts, not approved plans, and not under active development.

<!-- quarry:begin -->
## Quarry

Local semantic search is available via quarry. Use it to search indexed
documents by meaning, ingest new content, and recall knowledge across sessions.

- Before using WebSearch or WebFetch for research, run `/find` with the query
  first. Quarry indexes this codebase, design docs, prior session transcripts,
  and web pages from previous research. If quarry returns relevant results,
  use them — do not re-research what has already been found.
- Use grep for symbol lookups and value lookups; use quarry for "why", "how",
  and "what did we decide about X" questions.
- **Slash commands**: `/find`, `/ingest`, `/remember`, `/explain`, `/source`,
  `/quarry`
- **Research agent**: `researcher` — combines quarry local search with web
  research. Use for deep investigation across local docs and the web.
- **Auto-behaviors**: working directory is auto-indexed at session start;
  URLs fetched via WebFetch are auto-ingested; transcripts are captured before
  context compaction.
- **Search tip**: natural language queries work best ("What were Q3 margins?"
  outperforms "Q3 margins").
<!-- quarry:end -->
@.punt-labs/vox/CLAUDE.md
@.punt-labs/ethos/CLAUDE.md
@.punt-labs/punt/CLAUDE.md
@.punt-labs/biff/CLAUDE.md
