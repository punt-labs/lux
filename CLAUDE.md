# Lux

Part of [Punt Labs](https://github.com/punt-labs). This repo must be checked out inside the `punt-labs/` workspace meta-repo so that org-wide configuration loads via Claude Code's ancestor directory walk:

- **`punt-labs/CLAUDE.md`** — org workflow, delegation model, beads issue tracking, tool configuration
- **`punt-labs/.claude/rules/python-*.md`** — 19 Python OO coding rules, scoped via `paths:` frontmatter (load on-demand when `.py` files are touched)
- **`punt-labs/.envrc`** — git identity, beads DB connection, API keys from platform keychain
- **`punt-kit/standards/`** — canonical reference docs

If cloned outside the workspace, these rules and configuration will not be present.

**OO Python standards adopted 2026-05-13.** The codebase does not yet fully comply. Every commit must improve OO scores (`make check-oo`), never regress. Do not match existing code patterns that violate the rules — write new code to the standard and improve touched files incrementally.

Lux is a **visual output surface for Claude Code**. Vox gives agents a voice; Lux gives agents a screen. An ImGui window renders JSON element trees sent by agents over Unix socket IPC.

- **Package**: `punt-lux`
- **CLI**: `lux`, `luxd`
- **MCP server**: via `mcp-proxy` → `luxd` WebSocket
- **Python**: 3.13+, managed with `uv`

## Mandatory Reading

Source-of-truth documents, `@`-imported so they stay in context. Read them before
writing code; on any conflict, [`target.md`](docs/architecture/target/target.md)
wins. The full linked index is in [Key Documents](#key-documents) below.

@docs/README.md
@docs/architecture/target/target.md

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
- The **current implementation** still contains older single-process and
  transitional paths.
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

The **JSON protocol** (the `protocol/` package — `elements/`, `messages/`) is the API surface. Agents describe what they want as a tree of typed elements — tables, text, plots, groups, buttons, sliders, etc. The **rendering layer** (the `display/` package — `server.py`, `element_renderer.py`, `table_renderer.py`, `menu_manager.py`, `texture_cache.py`, `idle_screen.py`) consumes the protocol and paints ImGui widgets. Changes to the protocol are contract changes — every consumer (agents, tests, the display) depends on them. Changes to rendering are implementation — they affect only the display process.

This separation means: protocol bugs break agents. Rendering bugs break the display. They overlap only when a new element kind is added (protocol + rendering in a single coordinated change).

### Three-tier distributed architecture

- **`lux-display`** — ImGui renderer. Receives element objects from the Hub, wraps handlers with `remote_dispatch`, renders every frame. Native dependencies (`imgui-bundle`, `numpy`, `Pillow`) live here behind the `[display]` optional extra.
- **`luxd`** — Session hub. Decodes wire elements, stores authoritative state in HubDisplay, pushes element copies to the display, receives and dispatches remote handler invocations from display clicks.
- **`mcp-proxy`** — Transport bridge. Claude Code stdio ↔ luxd WebSocket. See `../mcp-proxy/`.

This is the rewrite target, documented in
`docs/architecture/target/target.md`,
`docs/architecture/target/topology.md`, and
`docs/architecture/target/ui-model.md`. The current implementation still
contains older single-process structure and migration scaffolding.

The code-backed sliver that already demonstrates this target is narrower than
the full system: `HubDisplay`, Hub-scoped pub-sub, and the ABC button/dialog
path with remote handler wrapping and Hub-side re-dispatch.

### Key packages and modules

| Module | Responsibility |
|--------|---------------|
| `display/server.py` | ImGui render loop and coordinator — **~1,550 lines, still over the 300-line target; remaining debt from the original `display.py`** |
| `display/element_renderer.py` | Per-element-kind ImGui dispatch — **~760 lines, still over target** |
| `display/table_renderer.py` | Table widget with filters, search, row selection |
| `display/menu_manager.py` | Application menu bar |
| `display/texture_cache.py` | Image texture upload (unbounded dict — no eviction policy yet; see `system.tex` §7 "No texture eviction") |
| `display/idle_screen.py` | Idle splash when no scene is active |
| `protocol/elements/*.py` | JSON element types (25 kinds; io-model kinds `text`, `button`, `checkbox`, `dialog` in dedicated modules with separate codecs; legacy kinds in family modules: basics, inputs, layout, graphics, table, plot_element) |
| `protocol/messages/*.py` | Wire message types across modules: lifecycle, scene, menu, introspect, `observer` (Agent Subscribe), `remote_invocation` (D21 `RemoteEventHandlerInvocation`), registry |
| `protocol/elements/codec.py` | `ElementCodec` registry — per-kind dispatch table |
| `scene/manager.py` | `SceneManager` — scene state, frame composition |
| `tools/server.py` | FastMCP server — `show`, `update`, `clear`, `show_table`, `show_dashboard`, etc. |
| `tools/tools.py` | Individual MCP tool definitions |
| `display_client.py` | `DisplayClient` — Unix socket client for clients → display |
| `apps/beads.py` | `BeadsBrowser` — beads issue browser app |

25 element kinds covering ImGui's core primitives. Primary consumers: beads issue browser (`show_table()`), dashboards (`show_dashboard()`), custom rendering (`draw` element).

Start with `docs/architecture/target/target.md`. Use
`docs/architecture/target/ui-model.md` for the authoritative UI model and
`docs/architecture/target/topology.md` for the target process model.

### Vision

**v1 (current):** A display canvas for Claude Code agents — tables, data, dashboards — **plus agent↔user interaction**: the agent can ask the user a question and receive the response. That loop shipped with the Hub/Display io-model (Hub-side handler dispatch + `recv`/`publish`, the Dialog/Checkbox/Button path). The protocol is the API surface — agents describe JSON, Lux renders it.

**v2 (future):** **Full ImGui element coverage** — every ImGui widget available as a Lux element — evolving toward a Pharo-inspired live environment where MCP is the message bus and Lux is the Morphic rendering layer (agent introspects and reshapes UI at runtime; system browser, inspector, workspace).

**Guiding constraint:** v1 hones the data-display core and the ask-user/get-response interaction loop. Completeness of the ImGui element set is a **v2 goal** — new element-kind work is tracked with the `v2` bead label and does not block v1. Applications and applets (clock, calculator, dock, standalone viewers) are out of scope entirely.

## Logging

Two separate log files — luxd and the display are separate processes with separate log destinations:

| Process | Log file | Level |
|---------|----------|-------|
| luxd (Hub) | `~/.punt-labs/lux/logs/luxd-stderr.log` | Configured by launchd |
| lux-display | `/tmp/lux-jfreeman/display.sock.log` | INFO (set in `__main__.py`) |

When debugging display-side behavior (rendering, click dispatch, handler wrapping), read the display log. When debugging Hub-side behavior (MCP tools, HubDisplay, publish), read the luxd log.

DEBUG-level logs do not appear by default. To see them, change the level in `__main__.py:100` or add WARNING-level logs. Do not add ad-hoc debug prints — use the logger at the appropriate level.

## Code Quality

### OO Python is non-negotiable

Default Python — procedural functions operating on dataclasses, `| None` everywhere, `str` fields with comments listing valid values — fails this project's quality bar. The rules in `punt-labs/.claude/rules/python-*.md` exist precisely to fix that bias and they are NOT load-bearing unless the agent (or the mission author writing a YAML) explicitly cites them. The user has had to repeat OO 101 across multiple sessions while agents shipped procedural code. Stop.

**Five rules, cited verbatim in every mission YAML for protocol/data work:**

1. **Classes own data AND behavior** (PY-OO-5). A dataclass with module-level `_<kind>_to_dict(m)` / `_<kind>_from_dict(d)` functions IS procedural code in dataclass clothing. The functions become `to_dict(self)` instance methods and `from_dict(cls, d)` `@classmethod`s. If you find yourself writing a function that takes a dataclass parameter, reads multiple fields, and returns a derivation — that function belongs ON the class.

2. **Families share via Protocol, not base class.** Structural typing. `runtime_checkable` Protocol with `TYPE: ClassVar[str]`, `to_dict`, `from_dict`. Every wire class satisfies it implicitly. No abstract base. No `BaseElement`. Tests assert `isinstance(x, WireType)` for the family contract.

3. **Composition over inheritance** (PY-IC-1). Shared shapes — e.g., `[x, y]` point pairs across draw commands — become small typed value classes (`Point2`) composed into containing classes, not parent state. Helpers like `_strip_none` are module-level utility functions called from instance methods, not methods of a base class.

4. **No `str` with a comment listing valid values.** Replace with `Literal[...]`. `layout: str = "rows"  # "rows" | "columns" | "paged"` → `layout: Literal["rows", "columns", "paged"] = "rows"`. The comment was the type system giving up; Literal is the actual type. Every `str` field with a comment listing values is a violation. Audit and fix when touching the file.

5. **Reduce `| None` types.** Each Optional is a place the type system gave up. Per-field, ask: is this really "absent", or is it a discriminated state? `color: str | None = None` (meaning "renderer default") → `color: str = "#FFFFFF"`. `error: str | None = None` on a response → discriminated `OkResponse` vs `ErrorResponse`. `path | data` validated one-or-the-other → discriminated `PathImage` vs `DataImage`. Genuinely-optional attributes (e.g., `tooltip`) stay.

**Mission YAMLs for protocol/data work open with the rules in scope, citing IDs and showing one BEFORE/AFTER example.** Sub-agents inherit the training-data bias toward procedural Python unless the prompt is explicit; explicit means cite-and-show. Don't dispatch a sub-agent on protocol/data work without these in the YAML's first 20 lines.

### Module-size constraints

**`display/server.py` (~1,550 lines) and `display/element_renderer.py` (~760 lines) must be decomposed further** — both are over the 300-line target. Any PR that adds rendering logic to either without extracting existing code will be rejected. The original `display.py` was 4,208 lines; PR #158 split it into the `display/` package; `server.py` still carries the bulk of the original mass (and has grown), while `element_renderer.py` has been reduced but is still over target.

**Protocol codec functions** — every `protocol/elements/*.py` and `protocol/messages/*.py` module still uses module-level `_<kind>_to_dict` / `_<kind>_from_dict` functions instead of methods on the dataclasses. Phase A (PRs #169, #170, #172) split the file but DID NOT fix the procedural codec pattern — same OO debt now spread across 11 family modules instead of 2. The draw-command surface (PR #176) is the one corner that fixed it. When you touch any of those files, fix the codec while you're there; do not file a follow-up bead.

**MCP tool boilerplate** — 27 MCP tools across `tools/tools.py` (23) and `tools/subscribe_tools.py` (4) (registered via `tools/server.py` and exposed by `tools/connection.py`) with identical boilerplate. This signals a missing abstraction. Extract the pattern into a decorator or registry — see `docs/architecture/target/introspection-api.md` for the target verification/control surface.

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

**Org standards override review tools.** Copilot, Bugbot, and Cursor are advisory. When a review suggestion conflicts with rules in `punt-labs/.claude/rules/python-*.md`, the rules win. Read the rules before accepting a reviewer's suggestion. PY-CC-1 (`__new__` as constructor) is the most common conflict.

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

Lux's biggest testing gap is the rendering layer. `display/server.py` and `display/element_renderer.py` are large and have no automated visual regression tests — correctness is verified manually by looking at the display. This means:

- **Protocol tests are the primary safety net.** Every element kind must have tests that verify serialization roundtrips (build → serialize → deserialize → compare). Protocol changes without tests are unshippable.
- **Scene tests verify composition.** Multiple elements in a scene, tab switching, window management, detail panels — these must be tested at the scene level even though visual rendering is manual.
- **Further decomposing `display/server.py` and `display/element_renderer.py` is prerequisite for meaningful render tests.** Until each is split into testable units, the rendering layer remains undertested. Every change that includes extraction improves the testability of the codebase.

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

Identity: `agent: claude` per `.punt-labs/ethos.yaml`. All code delegation uses ethos missions. Every non-trivial delegation has two phases: (1) **design mission** — describes problem, constraints, and invariants but does NOT prescribe a write set; (2) **implementation mission** — uses the write set produced by the design phase. The design mission's output IS the write set — the specialist decides what to create, split, or extract.

The COO must not read implementation files before writing the design spec. "Add a handler to `display/server.py` at line 923" is a predetermined write set that prevents the specialist from making design decisions. "Add a query operation that returns display metadata — the codebase has a generic query infrastructure, the implementation must follow code quality standards" gives the specialist latitude to decompose and restructure. This is how the original `display.py` grew to 4,208 lines and `display/server.py` is still ~1,400 — write sets were predetermined to existing files instead of letting the specialist extract.

### Why these pairings

Lux spans two domains that require distinct expertise: (1) **visual/UX** — element design, layout, theming, composability — owned by `edt` (information design) and `dna` (interaction design), with `kpz` for GPU/performance; (2) **protocol/infrastructure** — JSON element types, Unix-socket IPC, scene management, MCP tool surface — owned by `rmh`/`gvr` for Python, `mdm` for CLI, `djb` for IPC trust boundary. The protocol is the contract between these domains — changes to it require a worker from one domain and an evaluator from the other.

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

Use `standard` pipeline (design → implement → test → review) for new elements, protocol changes, or any work touching the JSON wire format. Use `quick` (implement → review) only for documented bugfixes inside an existing element that don't change the protocol. Review-cycle fix rounds (Copilot/Bugbot findings) use bare `Agent()`, not missions. Treat the JSON protocol as the API surface — any change demands an evaluator distinct from the worker.

## Session Queue

When claiming a batch of beads to work through in a session, create corresponding `Task` entries via `TaskCreate` for the session subset. Beads are the durable cross-session source of truth; the task list is the session-visible workqueue you can monitor in real-time in the Claude Code UI.

Workflow:

1. Pick a realistic batch from `bd ready`.
2. `bd update <id> --claim` for each bead in the batch.
3. `TaskCreate` one entry per claimed bead with the bead ID in the title.
4. Work through them in order. `bd close <id>` when done; mark the Task complete immediately after.
5. Uncompleted tasks at session end carry over as open beads — no extra cleanup needed.

Do not use `TaskCreate` for work that spans multiple sessions. Beads are the record; tasks are the display.

## Development Loop

Two nested loops govern all code changes. See `punt-kit/standards/pr-review.md` for the authoritative reference.

### Inner loop — one mission

Execute after every agent delegation that produces sizeable code changes. Do not start the next mission until this loop is complete — starting without local review is a procedural violation.

1. **Read `Makefile` first** and identify the repo-defined gate chain before you start coding. In Lux, assume `make check` is mandatory unless the user explicitly scoped the work to docs-only changes.
2. **Delegate** to the right ethos specialist (see pairing table above). Do not use bare `Agent()` for implementation work.
3. **`make check`** — must pass before proceeding. Zero exceptions. This is the authoritative all-gates target for code changes.
4. **`make restart`** — builds, installs, and restarts BOTH luxd AND the display. This is the ONLY correct way to pick up code changes. `launchctl kickstart` restarts luxd but leaves the display running stale code — the display is a separate process (PID visible in `make restart` output). `lux ensure-hub --restart` also only restarts luxd. Never use either for code iteration; always `make restart`.
5. **`make test`** against the installed artifact — not from source. If no test covers the changed code, write one before marking this step complete.
6. **Exercise via introspection + operator confirmation** — write expected output BEFORE running. Drive the feature through its real entry point (MCP tool, CLI command, button click in the lux window). Capture what the running system did via the introspection APIs (`inspect_scene`, `list_scenes`, `list_recent_events`, `list_errors`, `screenshot`, `list_menus`, `list_clients`, `get_display_info`). Compare actual to expected. **Ask the operator to confirm.** Cover one invalid input, one missing-dependency case, one boundary condition. Synthetic tests that exercise a dispatcher in-process do not substitute for running the feature. **Exception: docs-only changes (CLAUDE.md, ADRs, READMEs) have no entry point to run; markdownlint pass + read-through is the verification.**
7. **Local review** — run the applicable agents, 2–6 by scope.

   | Agent | When |
   |---|---|
   | `pr-review-toolkit:code-reviewer` | Always |
   | `pr-review-toolkit:silent-failure-hunter` | Always |
   | `pr-review-toolkit:type-design-analyzer` | New type, dataclass, or Protocol introduced |
   | `pr-review-toolkit:comment-analyzer` | Significant documentation/comment changes |
   | `pr-review-toolkit:pr-test-analyzer` | Changes that add or restructure tests |
   | `pr-review-toolkit:code-simplifier` | After the others are clean — catches unused abstraction / dead code |

   Trivial fix (≤1 file, no new types): 2. Single-feature change: 3–4. Cross-cutting refactor: 5–6.
8. **Fix every finding.** To dismiss one: document (a) the exact finding, (b) the specific reason it does not apply, (c) the code reference. "Pre-existing", "by design", "intentional", and "expected" are not reasons.
9. **Re-run agents.** Exit the fix loop on the first round that produces no findings on any selected agent.
10. **Commit.**

### Outer loop — one PR (one rollback-coherent unit)

After all missions for the feature complete and each has passed its inner loop:

1. **`make check`** on the full accumulated diff.
2. **All applicable local review agents** on the complete diff (2–6 by scope — same table as Inner-loop step 6) — cross-mission issues only appear at this level.
3. **Fix all findings** using the same documentation standard.
4. **Human IDE review** of the full diff — the only human review in the process. Resolve all findings before proceeding.
5. **`make restart`** (builds, installs, restarts both luxd and display), then run the complete user-facing workflow end-to-end through its real entry point. Capture system state via the lux introspection APIs (`inspect_scene`, `list_recent_events`, `list_errors`, `screenshot`, etc.) and **ask the operator to confirm** the observed behavior matches the expected outcome written down before running. Verify the changed code was exercised — not just the surrounding scaffolding.
6. **Re-run agents** until clean.
7. **Open PR.** A PR opened before step 6 is clean is a procedural violation. The PR description includes the manual-verification playbook: commands run + introspection captures + operator-confirmation outcome.

### PR boundaries

Split by **rollback granularity**, not size. Ask: if this broke production, what reverts together? That is one PR. "The diff is large" and "separate concern" are prohibited split reasons. Independent rollback capability and sequential dependency are valid.

## Release

Use `/punt:auto release [version=X.Y.Z]`. Lux is a CLI + Plugin Hybrid — releases publish to both PyPI (`punt-lux`) and the marketplace. Dev plugin testing: `claude --plugin-dir .` loads `lux-dev` alongside prod.

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

**Element migration (active plan):**

- [`docs/architecture/migration/README.md`](docs/architecture/migration/README.md) — the migration approach ([DES-041](DESIGN.md)): **fork, don't mix** (parallel new path; duplicate rather than mix legacy + ABC in composites, new class gets the canonical name), ordered **by testability** (container + primitives first, complex widgets last), per-element verify-as-you-go. Tracked as beads epic `lux-xs7r`.
- [`docs/architecture/element-migration-audit.md`](docs/architecture/element-migration-audit.md) — per-element map of all 25 kinds (4 on the Element-ABC path, 21 legacy).
- [`docs/architecture/migration/progress-element-design.md`](docs/architecture/migration/progress-element-design.md) — the display-only-leaf worked example (`progress`). Under DES-041 `progress` is a primitive migrated after a container, not element #1; read it for the leaf pattern, not the sequencing.

**Decisions, specs, product:**

- [`DESIGN.md`](DESIGN.md) — ADR log (40 entries; DES-039 self-validating elements, DES-040 interaction model + tool/skill surface are the most recent). **Do not read start to finish** — grep for a specific `DES-NNN` when you need the rationale behind a settled decision. Append new ADRs at the end; do not reorganize existing ones.
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
