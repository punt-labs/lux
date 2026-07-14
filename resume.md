# Lux Migration — Resume Point (2026-07-06)

Paused mid-migration. `main` is clean and synced (`49e04a2`). Everything below
merged this session.

## Where the migration stands

Migrating from the legacy single-process display to the distributed
**Element-ABC / Hub-Display** architecture. Strategy: **DES-041 fork, don't mix**
— build the ABC path in parallel; order by testability (container + primitives
first, complex widgets last); one kind at a time.

**6 of 25 element kinds are on the ABC path**, and the foundation under them is
complete:

- **Migrated kinds:** `text`, `button`, `checkbox`, `dialog` (io-model leaves),
  `group` (first container, rows/columns), `progress` (first display-only
  primitive).
- **Render engine (DES-042, #239):** `Element.render()` is the real paint path
  (Template-Method skeleton + per-kind ImGui adapters). `render_path=="abc"`
  now means the element *paints* via the new path.
- **Patch crash-freedom (DES-043, #241):** the patch-application state machine
  is ProB-model-checked (`docs/patch_application.tex`) — no agent patch can
  terminate the display; per-patch rejection + boundary backstop; regression
  artifact committed.
- **E2E business-event-loop harness (DES-044, #243):** `tests/e2e/` — a
  standing gate proving the full interaction→dispatch→publish→react→re-push loop
  across the real boundary, in-process over `InMemoryConnection` (the shared
  `Connection` interface), zero `src/` changes. 17 scenarios (button, checkbox,
  dialog, payload, five deny-paths, replay, isolation). `djb`-confirmed faithful.

The other 19 kinds are still legacy. Authoritative live status:
`docs/architecture/migration/README.md` §"Where we are".

## This session's merged PRs

PRs #238 docs reconciliation (DES-041), #239 render engine, #240 group
container, #241 progress + crash-freedom, #242 migration checkpoint
(DES-042/043 + status), #243 e2e harness, #244 DES-044 ADR.

## Next threads (on operator's word)

1. **Remaining B1 display-only leaves** — `image`, `separator`, `spinner`,
   `markdown` (bead `lux-mphn`, partially done: progress landed). Same proven
   leaf path (one ABC class, `validate()`, an ImGui adapter). **Each now lands
   with a `Scenario` in the e2e harness** — "migrated" means its loop is green,
   not just that it paints.
2. **B3 simple composites** — `tab_bar`, `collapsing_header` (bead `lux-4n5n`;
   `group` landed).
3. **CI fast-follow** — `lux-lodl` (`adb`): wire the `@pytest.mark.integration`
   tier into CI so the harness runs on every PR (currently CI-capable but
   excluded by `-m 'not integration'`). Prereq `lux-gqai` (stabilize flaky
   real-subprocess tests, e.g. `test_paths::TestReap`).
4. **Deferred decisions (beads):** `lux-5zhw` framing-switch (DisplayClient onto
   the shared `Connection` interface); `lux-x8rb` interaction dedup/anti-replay;
   DES-028 pixel/screenshot fidelity.

## How to continue (per-element migration loop)

1. `bd update <id> --status=in_progress`; `/plan`; branch `feat/<kind>-migration`.
2. Design mission (no predetermined write set) → leader review → **escalate
   substantive issues to operator BEFORE implementation dispatch** → implement
   mission (worker `rmh`/`gvr`, cite the OO rules in the first 20 lines).
3. Add the kind's ABC class + `validate()` + ImGui adapter + a harness
   `Scenario`. Run Level 1-6 (`tests/CLAUDE.md`): roundtrip, wire, Hub/Display
   crossing, D21 interaction, introspection, manual visual.
4. `make check` + `make snapshot-parity` byte-identical + `make restart`, then
   demo live for operator confirmation (they are the verifier).
5. Local review: 2-6 agents by scope. Fix every finding, re-run until clean.
6. PR. **Merge gate:** a big code PR needs a FRESH Copilot review of the fix
   commit (Copilot reviews once on open here and can't be re-requested via API —
   need the `request_copilot_review` MCP tool); a docs/trivial PR is fine with
   Copilot-once + findings-resolved + Bugbot-re-passed on the latest commit.
   Bugbot passing is NOT Copilot done.

## Key process lessons

- Formalize (z-spec) on the 2nd repeat of a defect class, not the 4th.
- Bring the operator demos (they are the verifier) + genuine design judgment;
  decide tactical/sequencing yourself.
- `make check` ≠ feature works; the demo / the harness is the verification.
- Merge gate scales with PR risk (see step 6).

## Key docs

`docs/architecture/target/target.md` (canonical target) ·
`docs/architecture/migration/README.md` (live status) ·
`docs/architecture/e2e-harness-design.md` (harness design of record) ·
DESIGN.md DES-041/042/043/044 · `tests/CLAUDE.md` (the Round-trip Level 1-6
migration gate) · `docs/standards/python-oo.md` (OO standard + ratchet).

## OO ratchet (still active, applies to every touched file)

`make check` runs `check-oo` against `.oo-baseline.json`. Touch a god module →
decompose it (don't rebaseline growth). `server.py` (~1,386) and
`element_renderer.py` still over the 300-line target. After improvements:
`make update-oo`, stage `.oo-baseline.json` + `.oo-audit.jsonl` with the commit.
