# Changelog

## [Unreleased]

### Fixed

- **`install.sh` called the retired `lux hub-install` verb (`lux-2msd`).**
  The rename train in `lux-0shg.4` retired flat `hub-install` in favour of
  noun-grouped `lux hub install`, but `install.sh` at the repo root was
  missed and every fresh installer on v0.27.0 hit `Error: No such command
  'hub-install'`. The luxd LaunchAgent was silently never registered — the
  plugin then couldn't reach a hub, but the script printed "lux is ready!"
  anyway. `install.sh` now calls `lux hub install`, and the failure branch
  is `fail` rather than `warn` so a registration miss aborts loudly instead
  of shipping a broken end-state.
- **Display never showed a window on macOS (#362, `lux-5uc7`).** The Hub
  spawned the display with `start_new_session=True`, which stripped the
  child from the macOS GUI-session bootstrap; the socket handshake
  completed and nothing appeared. The Hub-side spawn no longer creates a
  new session, and the display now installs as its own launchd/systemd
  service under `lux display install` so the OS supervises it directly
  (parallel to `lux hub *`). `lux display serve` in the foreground stays
  attached to its terminal.

### Added

- **`lux display install|uninstall|start|stop|restart|status`** — six
  admin verbs on the display noun group, symmetric to `lux hub *` (from
  `lux-0shg.4`). `restart` mirrors `HubRestart`: SIGTERM the recorded
  display pid, wait for the supervisor to respawn under a new pid, then
  report the new one. `start` reports the running display and skips the
  supervisor call when the socket is already alive, matching `lux hub
  start`'s already-running fast path. `install` registers a per-user LaunchAgent
  (`com.punt-labs.luxd-display`) or systemd user unit (`luxd-display`)
  that runs at login and restarts on crash; the remaining verbs toggle
  and inspect that service. The `install.sh` bootstrap runs `lux
  display install` after `lux hub install` so `curl … | sh` produces a
  working window with no extra step.
- **macOS Dock icon.** The display now applies
  `NSApplicationActivationPolicyRegular` at startup: the window gets a
  Dock icon and is listed in Cmd-Tab (standard macOS app behaviour).
  When the menubar-app epic (`lux-mxvy.3`) ships this flips back to
  `Accessory` and the menubar controls visibility instead — a foreseen
  breaking change tracked with the epic.

### Changed

- **Menu bar reordered so Clients sits second-from-left.** The bar composed
  as `Lux Windows Help [agent bars] Clients`; users scanning left-to-right
  passed the two chrome menus (used least often) before reaching the client
  roster (used most). It now composes as `Lux Clients [agent bars] Windows
  Help`. `OwnMenus.sections()` split into `lux_section()` +
  `chrome_sections()`; `MenuReplica.menu_model()` interleaves Lux → callback
  menus (Clients) → agent menus → chrome.
- **Process names.** The hub identifies as `luxd-hub` and the display as
  `luxd-display` in `ps`, `top`, and Activity Monitor. launchd labels
  and systemd unit names match (`com.punt-labs.luxd-hub`,
  `com.punt-labs.luxd-display`; `luxd-hub.service`,
  `luxd-display.service`). This covers R5 of `lux-mxvy`. `lux hub
  install` unloads and removes any orphan `com.punt-labs.lux.plist` from
  a prior version so the two labels cannot race to bind port 8430 at the
  next login.

## [0.27.0] - 2026-08-21

### Added

- **Slash-command coverage for every non-exempt MCP tool (`lux-0shg.6`).**
  21 new slash definitions under `plugin/commands/` — one per client-tier
  MCP tool — round out the four-surface parity. Filenames are flat and
  dot-separated (`plugin/commands/scene.show.md` → `/lux:scene.show`);
  no cached plugin uses nested command directories, and the design doc
  names commands with dots explicitly, so a dotted filename is the
  slash routing convention adopted here. New commands, by noun:

  - **scene** (7): `/lux:scene.show`, `/lux:scene.update`,
    `/lux:scene.clear`, `/lux:scene.clear-all`, `/lux:scene.ls`,
    `/lux:scene.inspect`, `/lux:scene.table`. The dashboard slot is
    covered by the composed `scene.dashboard` SKILL (see below), not a
    thin slash — the two would register the same `/lux:scene.dashboard`
    name and shadow each other.
  - **frame** (2): `/lux:frame.raise`, `/lux:frame.close`
  - **menu** (2): `/lux:menu.ls`, `/lux:menu.set`
  - **session** (1): `/lux:session.ls`
  - **topic** (3): `/lux:topic.subscribe`, `/lux:topic.unsubscribe`,
    `/lux:topic.publish`
  - **display** (2): `/lux:display.info`, `/lux:display.screenshot`
  - **event** (1): `/lux:event.ls`
  - **error** (1): `/lux:error.ls`
  - **callback** (1): `/lux:callback.pending`
  - **top-level** (1): `/lux:ping`

  Slash file names follow the CLI verb spelling: `scene.clear-all`
  matches `lux scene clear-all` (hyphen), even though the MCP tool
  keeps the underscored `scene_clear_all` (transport convention).

  The existing `/lux y|n` enable/disable command (`plugin/commands/lux.md`)
  is unchanged — it stays at the top level as the per-repo integration
  switch.

  **Not shipped as slash (by design).** Seven MCP tools have no slash
  equivalent, each for a stated reason:

  - `topic_recv` — non-blocking receive; a slash `/lux:topic.recv`
    would fire once with an empty result almost always. Callers wanting
    real-time delivery use the library's `LuxHubClient` listener or an
    MCP poll loop.
  - `session_identify` — identity is declared once per session at
    handshake (DES-057); a slash form invites re-identification
    mid-session, which the identity model does not need.
  - `callback_register` — callback registration is a programmatic
    step of hosting a menu entry; a slash form has no meaningful
    ergonomics (the caller has to provide an opaque callback id).
  - `display_theme_get`, `display_theme_set`, `display_window_get`,
    `display_window_set` — deferred to the display fuse follow-on
    (`lux-5pwu`); once fused, one slash `/lux:display.theme`
    covers get+set (and likewise `/lux:display.window`). Shipping
    four thin slashes now would have to be retired within the same
    epic.

- **Skills reorganized under the scene noun group.** The three existing
  skills move from `plugin/skills/{beads,dashboard,data-explorer}/` to
  `plugin/skills/scene.{beads,dashboard,data-explorer}/`. Their
  `name:` frontmatter is now `scene.beads`, `scene.dashboard`,
  `scene.data-explorer`, so an agent looking for "what can I do with a
  scene?" discovers the thin slashes and the composed skills in one
  place. The session-start hook's `Skill()` allowlist and the
  `scripts/check-skill-permissions.sh` gate are updated to match.
  The `scene.dashboard` SKILL owns the `/lux:scene.dashboard` slash
  outright — the thin scene.dashboard command file was not shipped,
  so the two never collide.

- **`LuxClient` — the public library facade with noun-grouped accessors
  (`lux-0shg.7`).** A downstream Python consumer now holds a single
  `LuxClient` and reaches the Hub through nine noun-grouped accessors —
  `client.scene.*`, `client.frame.*`, `client.menu.*`, `client.session.*`,
  `client.callback.*`, `client.display.*`, `client.event.*`,
  `client.error.*` — plus `client.ping(...)` and `client.listener(...)` at
  the top level. Every accessor method is async and returns the typed
  operation result, dispatched through the shared command singletons in
  `punt_lux.commands` so the library caller runs the same code path as the
  CLI, MCP, and REST adapters. IDE completion on `client.scene.` shows the
  same verbs `lux scene <verb>` (CLI), `scene_<verb>` (MCP), and `/scenes`
  (REST) speak.

### Changed (BREAKING)

- **Library public API swap: `LuxRestClient` / `LuxHubClient` retired from
  `punt_lux.__all__` in favour of `LuxClient` (`lux-0shg.7`).** The
  transport classes remain importable from their submodule paths
  (`from punt_lux.rest_client import LuxRestClient`,
  `from punt_lux.hub_client import LuxHubClient`) for internal callers and
  power users who need to hold a transport directly. They are no longer
  part of the primary consumer surface. Migration table lives in
  [`docs/library.md`](docs/library.md#migrating-from-luxrestclient--luxhubclient);
  a typical port is `client.render(req)` → `await client.scene.show(req)`.
  Cross-repo consumers (vox, z-spec) update in lockstep — beads `vox-oyfs`
  and `z-spec-t7w` track their migration.

- **MCP tool rename train — 22 renames + 1 new tool + frame_split.** Every
  MCP-visible tool now uses the noun_verb form of the design vocabulary.
  There are **no aliases** (PL-PP-1) — any agent invoking an old name after
  this release will error with an unknown-tool response. The full rename map:

  | Old MCP tool | New MCP tool |
  |---|---|
  | `show` | `scene_show` |
  | `update` | `scene_update` |
  | `clear` | `scene_clear_all` |
  | `clear_scene` | `scene_clear` |
  | `inspect_scene` | `scene_inspect` |
  | `list_scenes` | `scene_ls` |
  | `show_table` | `scene_table` |
  | `show_dashboard` | `scene_dashboard` |
  | `set_frame_state` | (split — see below) |
  | `list_menus` | `menu_ls` |
  | `set_menu` | `menu_set` |
  | `list_clients` | `session_ls` |
  | `identify` | `session_identify` |
  | `publish` | `topic_publish` |
  | `subscribe` | `topic_subscribe` |
  | `unsubscribe` | `topic_unsubscribe` |
  | `recv` | `topic_recv` |
  | `register_callback` | `callback_register` |
  | `get_display_info` | `display_info` |
  | `screenshot` | `display_screenshot` |
  | `list_recent_events` | `event_ls` |
  | `list_errors` | `error_ls` |
  | `get_theme` | `display_theme_get` |
  | `set_theme` | `display_theme_set` |
  | `get_window_settings` | `display_window_get` |
  | `set_window_settings` | `display_window_set` |
  | `display_mode` (get variant) | `display_mode_get` |
  | `set_display_mode` | `display_mode_set` |
  | (new) | `callback_pending` |

  The six display get/set renames above were missed in the initial
  `.5` rename train because the display fuse deferral swept them under
  it; they land here as a mechanical follow-on. No behavior changes —
  Python function names, request/response types, and wire semantics are
  unchanged; only the MCP tool identifier moves to the noun_verb form.

- **Frame split — `set_frame_state` splits into two new verbs, not four,
  and the split is not a rename.** The old `set_frame_state(minimized=...)`
  toggled the visibility of a still-alive frame. The two new verbs are a
  different operation on a different lifecycle stage:
  - `frame_raise` — unminimize a live frame and bring it to the front
    (z-order-to-front for a frame the display already holds); a frame the
    display does not hold returns `raised=false` rather than erroring.
  - `frame_close` — tear down the frame's scenes on the Hub. This ends
    the frame's life, it does not toggle its visibility.

  The old operation's minimize aspect is deferred with `frame_lower` per
  the capability-gap section below. The design's four-verb split
  (`raise|lower|close|expire`) needs display-protocol capabilities that do
  not yet exist: z-order lowering (for `lower`) and
  `FrameExpiry.set_deadline` exposed publicly (for scheduled `expire`).

  The old `set_frame_state` MCP tool, `lux frame set-state` CLI verb,
  PATCH `/display/frames/{id}` REST route, and `Operations.set_frame_state`
  facade method are all removed with no alias.

### Not shipped (by design, capability gap)

- **`frame_lower`** — needs a genuine z-order concept in the display
  protocol (only minimize exists today, which is not z-order lowering).
  Follow-on bead.
- **`frame_expire --in <seconds>`** — needs `FrameExpiry.set_deadline`
  exposed through `FrameLifecycle`, currently private to the presentation
  re-show path in `domain/hub/`. Follow-on bead.

### Not shipped (by design, mechanical)

- **Display fuse (`display_theme` / `display_window` / `display_mode` as
  fused get/set tools replacing the six current `get_*`/`set_*` MCP tools).**
  Ratified in the design, but shipping the retirement of the six old
  commands and wiring three fused replacements is a coordinated multi-file
  Protocol refactor. OO ratchet enforcement of per-file per-metric baseline
  prevents such multi-file Protocol refactors mid-edit (the `PostToolUse`
  hook fires `make check` on every `.py` write and blocks any intermediate
  state where a single file has regressed, even briefly, against the
  committed baseline). Will land as follow-on bead once tooling accommodates
  the pattern. The six current tools (`get_theme`/`set_theme`,
  `get_window_settings`/`set_window_settings`, `display_mode`/`set_display_mode`)
  ship unchanged under their current names.
- **`menu_get` MCP tool + `GET /menus/{label}` REST route + `lux menu get`
  CLI verb.** Ratified in the design as a net-new tool; the underlying
  `Operations.get_menu` facade method and `MenuOperations.get_menu`
  implementation shipped in an earlier commit of this bead. The adapter
  wiring (command class + Protocol update + stub update + three adapter
  wirings) is the same multi-file Protocol refactor blocked by the ratchet
  mechanics above. Will land as follow-on bead.
- **`session_inspect` MCP tool + `GET /sessions/{id}` REST route + `lux
  session inspect <id>` CLI verb.** Ratified in the design as a net-new
  tool (extraction of one row from `session_ls`); needs a new
  `Operations.session_inspect(id)` facade method plus the same adapter-
  wiring refactor blocked above. Will land as follow-on bead.

- **The CLI is now noun-grouped, matching the vocabulary the MCP tools and
  REST routes use.** Every flat verb from before this release is retired,
  with no alias (PL-PP-1) — a script or muscle-memory invocation of any of
  these must be updated:

  | Old (retired) | New |
  |---|---|
  | `lux hub-install` | `lux hub install` |
  | `lux hub-uninstall` | `lux hub uninstall` |
  | `lux ensure-hub` | `lux hub start` |
  | `lux hub-status` | `lux hub status` |
  | `lux display` (start the render-loop server) | `lux display serve` |
  | `lux show beads` | `lux beads` |

  `lux hub stop` is new (previously there was no way to stop luxd without
  uninstalling the service).

- **New noun groups**, each wrapping the `commands/` singletons from the
  Humble Object commands layer through a real per-invocation identity:
  `lux scene {show,update,clear,clear-all,inspect,ls,table,dashboard}`,
  `lux frame {raise,close}`, `lux menu {ls,set}`, `lux session {ls,inspect,identify}`,
  `lux display {info,theme,mode,window,screenshot,serve}` (theme/mode/window
  are fused: no argument reads, an argument or option writes), `lux event ls`,
  `lux error ls`, `lux callback register`. Every write accepts
  `--as/--kind/--name/--repo/--agent` (per-invocation identity — the caller
  *being* a different client for one call, not privilege elevation); every
  command accepts `--json/--verbose/--quiet`. Identity flags apply to write
  verbs only — read verbs (`scene ls`, `session ls`, `display info`, ...) use
  the ambient CLI identity from `CliIdentity.resolve` and take no identity
  flags of their own, since a read has no owner to declare.

- **`lux ping`, `lux version`, `lux enable`, `lux disable` gained real
  `--json`/`--quiet` support.** `lux status`/`lux doctor` accept the flags for
  surface consistency (`--quiet` suppresses their existing text output;
  `--json` is not wired to a payload for these two yet — their output is a
  multi-line diagnostic render, not a single value).

- **`LuxRestClient` grew ~20 methods** to satisfy the `commands/` ops
  Protocols the CLI needs (`scene_update`, `scene_clear`, `scene_clear_all`,
  `scene_ls`, `scene_inspect`, `scene_dashboard`, `list_clients`,
  `set_frame_state`, `list_menus`, `set_menu`, the display info/theme/window/
  mode family, `list_recent_events`, `list_errors`, `screenshot`). Split into
  three composed classes (`SceneRestOps`, `DisplayRestOps`, plus
  `LuxRestClient` itself) to stay under the 300-line module-size target.

- **`lux hub stop` implemented**: `LaunchdBackend.stop()` /
  `SystemdBackend.stop()` stop the running luxd process while leaving its
  service registration in place (distinct from `uninstall`, which removes the
  registration too).

- **`CallbackOps` split into `CallbackRegisterOps`/`CallbackPendingOps`**
  (`commands/_ports.py`): the two operations it bundled have different
  reachable transports — `register_callback` has a REST route a REST-backed
  client can implement, `pending_callbacks` does not and never will (see
  below) — so no REST-only client could ever satisfy the combined Protocol.

### Not shipped (by design, not oversight)

- **`lux topic *` (`publish`/`subscribe`/`unsubscribe`/`recv`) and
  `lux callback pending` have no CLI verb.** Both would need a REST route,
  and `tests/rest/test_app.py`'s `_MCP_ONLY` exemption set forbids one by
  ratified design: delivery for these operations runs over the Hub↔Display
  listen leg's push/drain, which a stateless CLI/REST request cannot bind to.
  A route that returns 200 but can never actually deliver is worse than no
  route.
- **`lux mcp` (a stdio MCP server) is intentionally not shipped.** The
  streamable HTTP endpoint at `http://127.0.0.1:8430/mcp` is the
  authoritative MCP transport (the one-code-path epic `lux-7gcz` removed the
  stdio/mcp-proxy path); the Claude Code plugin connects to it directly, with
  no per-session process in the tool path.

- CLI parity guard (`tests/cli/test_parity.py`): every non-admin
  `commands/` singleton must have a reachable Typer entry, or a stated
  exemption. Mirrors the REST route-parity guard
  (`tests/rest/test_app.py`).

## [0.26.0] - 2026-08-19

### Changed

- **The shippable plugin surface moved to `plugin/`, so a marketplace install
  fetches only the plugin.** `.claude-plugin/`, `commands/`, `hooks/`, and
  `skills/` now live under a single `plugin/` directory, which lets the
  marketplace entry use Claude Code's `git-subdir` source (`"source":
  "git-subdir"`, `"path": "plugin"`). That source is a blobless partial clone
  plus a `sparse-checkout set --cone`, so an install stops fetching whole
  directories: `src/`, `tests/`, `docs/`, `tools/`, `scripts/`, `.github/`,
  `.beads/`, this repo's `.claude/` dev config, and the vendored
  `.punt-labs/ethos` persona registry are all absent. Measured against this
  branch on GitHub: 34 files / 1.7 MB of working tree (3.8 MB including
  `.git`) versus 1,177 files / 15 MB (21 MB including `.git`) for an
  equivalent shallow full clone — a 35x file-count and 8.8x working-tree
  reduction. Note that cone mode always materializes the files sitting in the
  *repo root*, so roughly 1.6 MB of root-level documents still travel with an
  install (`.oo-audit.jsonl` 501 KB, `DESIGN.md` 299 KB, `uv.lock` 265 KB,
  `.oo-baseline.json` 186 KB, `CHANGELOG.md` 113 KB); `plugin/` itself is only
  84 KB. Shrinking that remainder means moving root documents into a
  subdirectory, which this change does not attempt.
- Nothing in the surface reaches outside itself at runtime — the MCP server is
  luxd's HTTP endpoint, not a file in the plugin — and both
  `${CLAUDE_PLUGIN_ROOT}/hooks/*.sh` in `hooks.json` and `session-start.sh`'s
  own `dirname "$0"/..` walk stay correct because the whole surface moved
  together. The wheel is unaffected: `uv_build` ships `src/punt_lux` only, so
  the plugin surface was never packaged. **One consequence for anyone working
  in this repo:** dev-plugin loading is now `claude --plugin-dir plugin`, not
  `--plugin-dir .` — the argument is the plugin root, and pointed at the repo
  root it would resolve a `hooks/` that no longer exists there. No user-visible
  behavior change; existing installs are unaffected until the marketplace entry
  is repointed.

### Added

- **`make check` now enforces that the plugin surface stands alone.**
  `scripts/check-plugin-surface.sh` (over `tools/plugin_surface.py`) verifies
  every path the surface uses to address itself, and it also runs in the lint
  workflow — as does `check-skill-permissions.sh`, which was previously in
  `make lint` only and so never ran in CI. The invariant that nothing under
  `plugin/` reaches outside it was documented and true but structurally
  unenforced: every other gate runs against the full source tree, where the
  target of an escaping path is present, so a `../../src/...` reference or a
  `source "$REPO_ROOT/..."` would pass CI and break every sparse-checkout
  install. Four checks: each `${CLAUDE_PLUGIN_ROOT}`/`$PLUGIN_ROOT` reference
  must resolve inside the surface, exist, and — for a shell script, identified
  by its shebang as well as its suffix — be executable;
  no symlink may resolve out or onto nothing; no `source`d file may land outside;
  and the surface may not name the repository root. **Containment is asserted on
  the resolved path, and existence only afterward** — a textual `../` scan and an
  `exists()` check both pass a symlink pointing out of the surface, because its
  text is clean and its target is right there in the source tree, while the
  install gets a dangling link. That ordering governs every check that resolves a
  path, symlinks included: a link contained by the surface but pointing at
  nothing ships broken just as surely. The gate also fails closed if `hooks.json`
  stops carrying a placeholder, since that would mean the extraction pattern
  rotted rather than the surface getting clean. Every file the surface ships is
  read, with binary content skipped by inspecting the bytes rather than the
  suffix: a suffix allowlist has a blind spot shaped exactly like the files it
  omits, and since a hook needs no `.sh` name to be a hook, an extensionless
  script was a place an escaping reference could live while the gate still
  reported the surface clean — and the same reasoning governs the executable-bit
  check, which asks what a file *is* rather than what it is called, so a hook at
  mode 0644 cannot ship merely by having no suffix. The `source` scan reads from
  that same universe minus documentation: a sourced fragment carries no shebang
  and needs no exec bit, so gating the scan on shell classification left its
  plain-relative `source "../../lib/x"` checked by nothing — no placeholder, no
  repo-root variable, no symlink. Markdown stays out because a `source` line in a
  command file is an example, not wiring. Twenty-one tests in
  `tests/test_plugin_surface.py`
  drive it as a subprocess, including negative controls for each rejected shape
  and a control that documented prose is never mistaken for a dependency;
  a guard that never fires is indistinguishable from no guard.

### Fixed

- **`scripts/restore-dev-plugin.sh`'s directory guard could invert its own
  answer under `pipefail`.** It piped `git ls-tree` into `grep -q .`; `grep -q`
  exits on the first match, so once the listing exceeds the 64 KB pipe buffer
  `git` takes SIGPIPE and returns 141, `pipefail` promotes that to the
  pipeline's status, and the `if` reads a populated directory as empty —
  skipping the restore. Demonstrated at 141 against a listing large enough to
  fill the buffer. The listing is now captured into a variable and tested with
  `[[ -n ]]`: one exit status, no race.
- **`scripts/release-plugin.sh` stripped release-only commands from a
  directory that has never existed.** Its `COMMANDS_DIR` pointed at
  `.claude/commands`, which is absent from every commit in this repo's history,
  so the `*-dev.md` removal step was a permanent no-op that reported "No -dev
  commands found — name swap only" whether or not dev commands were present.
  The plugin's own `commands/` — the directory `session-start.sh` deploys from,
  skipping `*-dev.md` — is the one that was meant; both it and the matching
  restore path in `scripts/restore-dev-plugin.sh` now name `plugin/commands`.
- **`scripts/restore-dev-plugin.sh` never restored dev commands, because its
  guard could not be true.** It tested `git ls-tree -d <commit> -- <dir>/`,
  but a trailing-slash pathspec makes `ls-tree` recurse into the directory and
  report the blobs it contains, and `-d` then filters every one of those blobs
  out — so the command printed nothing whatever the commit held, `grep -q .`
  failed, and the restore step was skipped every time. Confirmed against the
  pre-move layout too: `ls-tree -d <commit> -- commands/` was equally empty.
  With the two bugs together the dev-command round trip was inert in both
  directions. The guard drops `-d`; a round trip against a scratch clone now
  strips a seeded `foo-dev.md` on release-prep and restores it afterward, and
  the `-d` variant still reports zero entries where the fixed one reports two.
- **Three suppressed failures in the release and session-start scripts.** Each
  turned a broken state into a quiet wrong answer.
  `restore-dev-plugin.sh` staged the commands directory unconditionally with
  `git add ... 2>/dev/null || true`, which swallowed both "nothing was
  restored" and a genuine `git add` error, so a half-restored state could be
  committed; the `git add` now sits inside the guard that does the checkout, so
  `set -e` aborts on failure. `release-plugin.sh` treated a missing commands
  directory as an empty result — the mechanism that let the `.claude/commands`
  typo survive, every run reporting "No -dev commands found" while tagging a
  release that still carried them; it is now a preflight that refuses, placed
  before the name swap so a failure leaves the worktree untouched, and it is
  the only guard that can work because `find` runs in a process substitution
  whose exit status `set -e` never sees. `session-start.sh` probed
  `plugin.json` with `grep ... 2>/dev/null` and let `DEV_MODE` default to
  false, so a wrong `PLUGIN_ROOT` silently took the *prod* branch and wrote the
  prod MCP tool glob into the user's `settings.json` while a dev plugin was
  loaded; a missing `plugin.json` now fails loudly, which is safe because the
  hook is registered `async`.

## [0.25.0] - 2026-08-17

### Security

- **Scenes and frames cannot alias across connections (DES-086, `lux-ledm`).**
  `HubDisplay` stored every scene and frame under the literal string a client
  submitted, so two connections choosing the same `scene_id` did not error;
  the second silently evicted the first's roots. Two Claude Code sessions
  running vox both pushed `scene_id="music-player"` and the second
  overwrote the first on the shared display. The Hub now composes a
  `ConnectionScopedId` — `f"{connection_id}\x1f{local_id}"` — from the
  writing connection's own `ConnectionId` and the caller's raw string, at
  every scene write and read. Collision becomes unrepresentable, not
  merely checked: two connections cannot construct the identical composed
  key because neither controls the other's `ConnectionId` half. `frame_id`
  is namespaced the same way. The agent↔Hub and Hub↔Display wire protocols
  are unchanged — callers keep passing the same short local `scene_id`;
  vox needs no code change. Model-checked with a fidelity control at
  `docs/scene_id_namespacing.tex` and `_buggy.tex`; the buggy variant
  reproduces the pre-fix collision in 7 states.

### Added

- **`SceneSummary.local_id`.** `list_scenes` now surfaces both the composed
  store key (`scene_id`) and the caller's raw label (`local_id`) so an
  agent can recognize the scene it called `music-player` without parsing
  the composed form.

## [0.24.0] - 2026-08-14

### Fixed

- **Two applets in one session no longer collapse onto one Hub connection.**
  `AppletIdentity.for_session(session_pid)` derived identity from `(repo,
  session_pid)` alone, so lux-beads and a tool's own applet — vox-panel is
  the first case in the wild — both produced the same identity, landed on
  the same Hub connection, and the later `register_callback` clobbered the
  earlier one. The signature is now `AppletIdentity.for_session(program,
  session_pid)`; the caller names its own program (`"lux-beads"`,
  `"vox-panel"`), which becomes a fourth distinctness token in the wire
  `name`. `menu_label` is untouched — the OS menu still reads the repo name,
  the composite is a wire-level distinctness token, not something to read
  aloud. Callers of `AppletIdentity.for_session` must update to the new
  signature; there is no shim.

### Removed

- **The `signal-beads.sh` PostToolUse hook.** It fired `lux hook post-bash`
  on every `Bash` tool call to grep for a `bd` subcommand and push an
  unprompted `lux show beads` refresh — a stand-in from before the beads
  menu had its own applet. The session-owned Beads menu entry (DES-058,
  `lux-beads`) now owns that refresh instead: clicking the entry re-fetches
  and re-pushes the board, so an already-open board goes stale after a `bd`
  command until the next click rather than updating automatically. Removed
  the hook, its `hooks.json` wiring, `handle_post_bash`/`read_hook_input`/
  `_BD_CMD_RE` from `hooks.py`, and the `lux hook post-bash` CLI dispatcher.

## [0.23.1] - 2026-08-08

### Changed

- **`scene/` is gone; its state lives under `display/replica/`.** The package
  wore a domain-noun name for state that only ever existed on the Display
  tier — `SceneManager` is now `SceneReplica`, `MenuManager` is `MenuReplica`,
  both in `display/replica/` beside `Frame`, `FrameBook`, `WidgetState`, and
  the new `WidgetStateStore`. `scene/rgba_buffer.py` moved to
  `display/renderers/rgba_buffer.py` beside its text and float siblings.
- **`display/server.py` is `display/render_loop.py`; `DisplayServer` is
  `RenderLoop`.** A class in `display/` no longer needs `Display` in its name
  to say what tier it is on. Move and rename only — the module's own
  1,082-line decomposition is still owed, separately.
- **`display_client.py` is `domain/hub/display_link.py`; `DisplayClient` is
  `DisplayLink`.** It is the Hub's socket client of the display, not
  Display-tier code, despite the old name and location — moving it closes the
  one Display→Hub import in the tree. The unrelated agent-side wire-decode
  factory the same file held moved to `protocol/agent_factory.py`.
- **`QueryDispatcher` is `QueryRouter`; `SocketServer` is `SocketListener`.**
  Both now live under `display/` with their callers. No bare `*Dispatcher` or
  `*Server` names a job.

Every module above is a pure move and rename with no behavior change; the
full design and rationale is
`docs/architecture/scene-display-packaging-design.md`. Any code importing the
old paths or class names directly (outside this package) needs updating.

### Fixed

- **A click on an already-dismissed dialog's descendant could still fire.**
  `HubInteractionDispatch` resolved a clicked element by id without checking
  whether it, or an ancestor, had been marked removed — a dialog dismissed out
  from under a race, or a click delivered after dismissal, could still run a
  confirm/delete handler on the Hub's authoritative copy. A new `DismissalWalk`
  drops the click instead, restoring behavior the earlier `Display.interact()`
  had and the D21 migration lost.

### Security

- **`cryptography` 49.0.0 → 50.0.0.** Fixes a PKCS#7 EnvelopedData decryption
  Bleichenbacher oracle, vulnerable range `>=44.0.0, <50.0.0`
  ([Dependabot alert #52](https://github.com/punt-labs/lux/security/dependabot/52)),
  reached in production via `fastmcp` → `authlib` → `cryptography`.

### Removed

- **`punt_lux.domain.display.Display`.** The display-tier scene mirror had no
  production caller left once `DomainPump` went, and it carried a second
  implementation of ownership, dismissed-ancestor, and click validation beside
  the Hub's. `HubDisplay` is the one store and `HubInteractionDispatch` the one
  dispatch surface; the tests that drove the mirror now drive them.

## [0.23.0] - 2026-08-03

### Added

- **Every client's submenu carries a `Details` command.** It shows that
  connection's state as a frame of its own: what kind of client it is, the name
  it declared, its repository, how long it has been connected, its lease, the
  topics it subscribed to, and the scenes it owns. The wire identity the labels
  no longer carry lives here, where state belongs. The Hub answers this command
  itself — it reports its own record of the connection and runs nothing outside
  luxd — and it reports the same facts `list_clients` returns, so the menu and
  the introspection read can never describe a client differently.
- **`list_clients` reports each client's lease.** The `lease` field carries the
  effective term — the one its kind holds when it declared none — not just what
  the client asked for. It is one of two states, `{"kind": "expiring",
  "seconds": N}` or `{"kind": "permanent"}`, rather than a number with a magic
  value in it: luxd's own built-ins never lapse, and written as a float that
  reads as `Infinity`, which no JSON can carry.
- **Applets — small session-bound programs that own a menu entry.** An applet
  runs for the life of one Claude Code session, in that session's repository
  and shell, holding its own connection to luxd. It exists because luxd cannot
  do this work itself: launchd starts luxd with no `PATH`, no repository, and
  no repository credentials, while the session has all three. Applets are for
  software Punt Labs did not build; `lux-beads` is the first.
- **A session gets one applet, however many times its hook fires.** `/resume`
  and `/clear` both fire SessionStart again against the same process, and
  every firing used to start another `lux-beads` under the same session
  identity — one identity is one Hub connection, so each new applet took the
  session's callbacks from the one before it and the menu entry flapped
  between them. An applet now claims its session before it serves it, under a
  lock on `$TMPDIR/lux-beads-<session pid>.pid`: the holder serves, and a
  second one says the session is already served and exits without connecting
  to anything. The lock arbitrates rather than the pid written inside it,
  because the kernel drops a lock when its holder dies — no stale claim to
  recognise, no recycled pid to mistake for a live applet, and two applets
  starting at the same instant cannot both find the session free. The
  session-start hook checks for a running applet before it spawns one, so the
  ordinary re-fire costs no process at all.
- **The Beads menu entry is automatic.** The plugin's session-start hook
  launches `lux-beads`, which registers the entry on connect and refreshes the
  board when it is clicked. Neither the hook nor the `/lux:beads` skill asks
  the agent to register a callback or poll for clicks any more. Measured on
  the author's machine: 0.43–0.56s from spawn to the entry being visible in
  the menu.
- **A click says where its time went.** The applet reports one line per click,
  timing each stage separately and ending with the whole wait — for example
  `click beads: answered 97 ms, fetched 2340 ms, built 12 ms, pushed 45 ms,
  total 2494 ms`. A board that was slow to arrive now names which stage was
  slow — the `bd` query, the board build, or the push to luxd — instead of
  leaving them to be told apart by guesswork, and a user who reports it can
  paste one line that carries the whole story. A click that failed reports the
  stages it reached, which is how far it got. The applet logs at INFO, so the
  line is written for every click, into the log the session-start hook gives it
  — `$TMPDIR/lux-beads-<session pid>.log`. A click that broke the 100 ms answer
  budget goes out at WARNING instead, so it is read even where the floor has
  been raised above INFO.
- **The read from `bd` is broken down, on lux's side of the boundary.** Reading
  the issues is four things, and only one of them is `bd`'s: lux starts a
  process, waits on it, reads what comes back, and turns it into rows. Each is
  now measured separately and reported with the stage that did it — a real
  click reads `fetched 4899 ms (spawn 4, bd 4894, parse 0, 66 kB, 50 rows)`, so
  the 4894 ms is `bd`'s and everything lux does around it is 5 ms. `bd`'s own
  wall time stays one figure, because what happens inside it is not lux's to
  instrument, and the counts are there because a four-second wait for fifty rows
  and a four-second wait for fifty thousand are different problems. The reload
  behind a standing board carries the same breakdown. This changed how lux runs
  `bd`: `Popen` instead of `subprocess.run`, so the spawn and the wait are two
  numbers rather than one, with the same 60-second bound now applied to the wait
  and an overrunning `bd` killed and reaped rather than left behind.
- **A click shows the board the applet already has.** Reading the issues is a
  query to a hosted database and it is the whole wait — one measured click spent
  4873 ms of its 4915 ms there. So the click stops waiting on it: the applet
  loads a board as soon as its entry is registered, and holds the board from
  every click after that, so a click answers with real issues and reloads behind
  them instead of opening "Loading issues…" and waiting. That board goes up on
  every click, whatever the frame raise answered: a frame coming forward says a
  board is up, not which board, so a refresh whose push never landed cannot
  leave a stale board in front of a user while the applet holds newer issues.
  The fresh board replaces the standing one in place and never takes focus. A load that fails
  leaves that board standing and says why in the log, so a `bd` that has stopped
  answering costs a log line rather than the board. When the warm-up and a click
  overlap — the case the warm-up exists for — the board kept is the one whose
  load *began* last, because a query's snapshot is fixed when it starts: a slow
  warm-up that returns after a click read fresher issues cannot put the staler
  ones back on screen. A session with no board yet
  opens the placeholder and waits, exactly as before. The click's line says
  which it was: `click beads: answered 28 ms (cached board), refreshed 4310 ms,
  total 4341 ms` — one figure for the reload, because the user was reading their
  issues throughout it and waiting on no stage of it.
- **A click is answered while the click before it is still loading.** Servicing
  ran on the connection's receive path, which reads the next frame only when the
  handler for this one returns — so a second click could not be raised or
  acknowledged until the first click's reload had finished, which is a menu
  entry that does nothing for the length of a `bd` query. A click is now started
  and the frame behind it read at once, so every click gets its own answer
  inside the budget. The work behind them is one piece of work: a click arriving
  while a query is running answers from the board the applet holds and stands
  down rather than starting a second `bd`, and the running query's board goes
  into the frame it just raised, so it serves both. Drumming on the entry costs
  one answer per click and no extra queries. The click that stood down says so
  rather than reporting figures for a query it never ran — `click beads:
  answered 24 ms (cached board), stood down 0 ms (a load was already running),
  total 25 ms`.
- **An applet leaves when its session does.** It is handed the session's
  process id at spawn and checks every five seconds whether that process still
  exists, exiting when it does not — so an applet cannot outlive its session
  even when the session is killed rather than closed, which is exactly when a
  shutdown hook would not fire. Measured: 4.4–6.4s from the session ending to
  the applet exiting. The Hub's lease sweeps the menu entry underneath this
  regardless.
- **Every process on the click path now times its own work.** The applet
  already reported its stages; the two processes between it and the glass said
  nothing. luxd logs one line per mutating operation — `op render
  scene=beads-lux 14 ms` — covering the scene installs, the frame raise, the
  menu push, and the clears, and the display logs the other half from the
  message arriving to the buffer swap that first painted it: `paint
  scene=beads-lux 41 ms`. A frame raise is logged where it actually takes
  effect (`raise frame=beads-lux applied`), which is the visible half of a
  click. No process vouches for another's clock: each figure is measured by
  the process that did the work, so a slow click is attributed rather than
  argued about. Read-only queries are not timed — they change nothing a user
  sees, and a line each would bury the mutations. Both lines are at INFO,
  which is at or above each process's default floor.

### Changed

- **The menu bar has one `Clients` menu — the live roster of what is connected
  to the display.** Every client that registers a command now appears under it
  as its own submenu, whatever kind of client it is: voxd's music player, a
  session's Beads applet, an on-demand tool. Before, each one took a top-level
  submenu of its own, and with several live the bar filled with near-identical
  entries labeled `lux · lux · #4b97` — the label crammed kind, repository, and
  process id together because a flat bar had nowhere else to carry the
  difference. Now the hierarchy carries it and the labels stop trying to.
- **Clients are named the way a person names them.** A client is called after
  the repository it works in — `lux`, `quarry` — or after itself when it works
  in none, as a machine-wide daemon like `voxd` does. Two clients that read the
  same way are numbered: `lux`, `lux (2)`. A number lasts only while there is
  another client to be told apart from: when one leaves, the name it frees goes
  back to a client still numbered against it, so nobody is left wearing `(2)`
  alone. Nothing else moves a name — while two clients of one name are both
  connected neither label changes and the two never swap, so a menu entry never
  renames itself under the pointer.
- **Command names are plain again.** A leaf under a client reads `Beads` or
  `Music`, with nothing appended, because the client it belongs to is the menu
  above it.
- **A menu callback may only be registered by a connection that can be pushed
  to.** `register_callback` is refused — over MCP, REST, and the client library
  alike — unless the calling connection holds luxd's listen leg, with a named
  reason saying what to hold and how. A caller that could never be told its
  menu item was clicked must not own one, and no interval a client would
  actually poll at can meet what a menu implies.
- **One beads board per repository.** `lux show beads`, the post-`bd` refresh,
  and a session's menu entry now all refresh the same `beads-<project>` scene,
  so they land in the tab already on screen instead of opening a second
  identical one.

### Removed

- **The per-session stdio MCP proxy (`lux mcp-serve`).** The plugin connects
  straight to luxd's HTTP endpoint again, as it did in 0.21.0. The proxy was
  reintroduced to give a session a connection its menu clicks could be pushed
  down; applets provide that without putting a hop in front of every one of a
  session's MCP calls.
- **`pending_callbacks`, the polling pickup leg** — the MCP tool and the
  `GET /menus/callbacks/pending` route. With push the only delivery, it could
  no longer return anything: a registered session is pushed its clicks, and a
  session that cannot be pushed to now owns no callback to have clicks for.
  Apps receive clicks through `LuxRestClient.listener(...)`, registering from
  its `on_connect` hook.

### Fixed

- **A malformed menu costs its own menu and nothing else.** The display now
  checks a replicated menu where it arrives from the Hub rather than trusting
  the payload downstream: a menu whose `items` is not a list, whose label is
  missing, or whose entry carries neither an id nor the `---` separator is
  refused there and logged by field name (`callback_menus.0.items: expected a
  list, got 7`). Before, such a payload raised while the model was composed —
  blanking the *whole* menu bar for the frame — and raised again inside
  `list_menus`, so the introspection query answered nothing at all instead of
  answering about the menus that were fine. The display now accepts exactly
  what the Hub accepts from an agent, so neither tier quietly repairs the
  other's payload.
- **The display's `list_menus` query reports where each line sits.** Every menu
  line now carries the menus above it (`["Clients", "lux"]`) instead of one
  label, so two clients that both offer `Beads` can be told apart in the
  display-side read, and the Hub's menu and the display's can be compared line
  for line. The field replaces the old single `menu` name.
- **A published event now carries what happened.** An element that declares
  `"publish": ["my.topic"]` fired its topic on every interaction and sent an
  empty payload with it, so a subscriber learned that *something* happened on a
  topic and nothing else — which row was clicked, what a slider was set to, and
  which element it was all went to the sink and were dropped one call before it.
  The publish now carries the event's own data: its kind, the scene and element
  it landed on, and its fields — a table selection's `row_ids` and `anchor`, an
  input's `value`, a tab bar's `tab_id`, a header's `open`. The event renders
  that mapping itself, so a new interactive kind publishes correctly without the
  decorator learning anything about it. The shape is documented in
  [the library guide](docs/library.md#what-a-published-event-carries).
  A subscriber that read nothing from the payload before is unaffected; one that
  wants the clicked row reads `anchor`, which the unordered selection set cannot
  name. A button's `publish` *mapping* form (`{"topic": ..., "payload": ...}`) is
  unchanged — that payload is the app's own message, sent verbatim.

- **One click on a collapsing header moves it once.** The renderer wrote the
  Hub's value into ImGui's own stored header state every frame, so a click
  opened the section, the next frame snapped it shut (the Hub had not heard
  yet), and the confirming re-push opened it again — three rendered states
  for one click. The header now holds the click's own transition until the
  Hub answers, fires once per click rather than once per frame, and a
  rejected toggle converges back to the Hub's value. The reconciliation is
  specified in Z (`docs/header_toggle_reconciliation.tex`) with three
  fidelity controls that reproduce the shipped defect and both careless
  half-fixes. An interaction evicted from the pending buffer — aged or
  overflowed, so no Hub answer will ever come — now gives up the state it
  latched: the header's optimistic open, a pending tab switch, and a
  committed-but-unanswered input value all revert to the Hub's authority
  instead of standing forever, and a stored flag slot is read as a flag or
  not at all (a stray non-bool value can no longer hold a header open or arm
  a refocus).
- **One identity is one connection even when the client does not encode its
  headers.** Identity crosses as `X-Lux-Client-*` header values, and the two
  transports disagree about everything but ASCII: the WebSocket client sends
  UTF-8 bytes where the HTTP client sends latin-1, and luxd decodes both as
  latin-1. A client that sends its name raw — every released `punt-lux`, and any
  client that does not use `ClientHeaders` — therefore gave luxd two different
  names for one identity as soon as that name held a non-ASCII character. The
  name is what the connection id hashes, so the client's listen leg bound one
  connection and its REST calls another: `register_callback` was refused for
  holding no listen leg, permanently, and neither log said why. luxd now
  recovers such a value on the read — bytes it decoded as latin-1 that spell
  valid UTF-8 are re-read as UTF-8 — so both legs resolve to one connection
  whichever way the client encoded them. Percent-encoding on the way out
  (shipped earlier in this release) only ever governed the clients we ship;
  this is the half that covers the ones we do not.
- **The display log is readable again.** Every renderer's `render`, and the
  paint loop that called them, carried a call-tracing decorator that logged one
  DEBUG line per element per frame. Against a live window that is sixty lines
  per element per second: a log sampled while this was running held 31,464 DEBUG
  lines, of which 31,254 — 99.3% — were the trace, and the 197 lines that said
  something were buried among them. The trace is removed from the per-frame path
  and kept on the event-driven paths, where one line still means one thing
  happened.
- **`make restart` no longer puts the display at DEBUG nobody asked for.** It
  exported `LUX_LOG_LEVEL=DEBUG` as a default onto the display it spawns, which
  overrode the display's own INFO floor on every restart. The variable is now
  passed through rather than defaulted: an operator who exports it still reaches
  both processes, and an operator who has asked for nothing gets luxd at DEBUG
  for its timings and the display at INFO. An empty `LUX_LOG_LEVEL` is read as
  unset rather than as a mistyped level, so clearing the variable no longer
  warns on every start.
- **A transient socket hiccup no longer makes a live display unreapable.**
  Reading the socket owner's peer credential failed the whole read on one
  refused connect, so `reap` could report that a display which was plainly
  running could not be resolved and refuse to act. The read now retries across
  a bounded window, matching how the liveness probe already treats an ambiguous
  connect.
- **One identity, one connection id.** A declaration read from request headers
  omits an absent field while one dumped from a `ClientIdentity` carries an
  explicit `None`; the two hashed to different connections. An app deriving its
  own connection id from the identity it holds now gets the connection its own
  socket will bind.
- **Identity crosses both transports intact.** Identity header values are
  percent-encoded on the wire, so the WebSocket leg (UTF-8) and the HTTP leg
  (latin-1) read the same bytes as the same identity. Before, a repository
  path with a non-ASCII character split one session into two connections and
  its menu entry silently never appeared. Plain-ASCII values cross unchanged.
- **Menu entries survive a reconnect and leave with their owner.** A
  session's entries are withdrawn the moment its listening connection ends —
  no more ghost entries whose clicks report success into a queue nobody
  drains — while a transient drop heals automatically: the connect hook
  re-registers on every handshake. A superseded or lease-swept connection's
  teardown removes only what it owns, so it can never strip its successor's
  entries, writer, or subscriptions. The succession rules are
  ProB-model-checked (`docs/listen_lifecycle.tex`).
- **A click on a menu entry launches instead of waiting on a database.** The
  first thing a Beads click did was run `bd`, so nothing at all happened until
  the query returned — and the board was usually already on screen, so the
  common case was waiting on a database to be shown what was already there. A
  click now raises the board's frame first, which is the whole answer in that
  case; a click with no board up opens one with a "Loading issues…" placeholder;
  and `bd` runs behind whichever happened. Measured on the author's machine:
  median ~55 ms from click to visible response, with the one breach in each run
  being the first click — the cold path, which has no frame to raise and pays a
  second round trip to open one. The per-click line carries this number and
  every stage behind it, and the applet writes it at INFO for every click; over
  budget, it goes out at WARNING instead.
- **A frame can be raised.** `POST /display/frames/{id}/raise` (and
  `LuxRestClient.raise_frame`) brings a frame to the front, restoring it first
  if it was minimized. A frame the display does not hold answers `raised: false`
  rather than failing, so a caller learns to push one. This is the only focus
  change a client may ask for, and only on the user's behalf: a menu click
  naming a frame is the user reaching for it.
- **The bar never shows an entry whose callback has gone.** A reconnect that
  beats its predecessor's teardown clears the predecessor's entries as it takes
  the connection, and the bar is now re-pushed at that moment. Before, the
  clearing was silent and nothing was guaranteed to correct it: the arriving
  session may register nothing of its own, and clicking a cleared entry found
  the fault rather than repairing it.
- **A dropped click says so.** A session's pending-click buffer is bounded, and
  reaching that bound discards the oldest click — one that was already reported
  as routed. luxd now logs which connection and which callback lost it, instead
  of discarding it silently.
- **A failed click no longer costs the session its menu entry.** A click
  whose board build fails renders the error in the window; a click that
  cannot reach the Hub (a `make restart` mid-click, a slow push) logs
  visibly and leaves the listening connection intact. A slow `bd` no longer
  starves the lease keepalive, so servicing a click can no longer expire the
  session doing the servicing.
- **`lux doctor` no longer hangs** when `claude plugin list` does not
  answer: the probe is bounded at 10 seconds and reports "did not answer"
  distinctly from "not installed".
- **The World menu and the menu bar are one menu.** Both now render from a
  single menu model as two projections — identical entries (agent bars and
  the session-registered callbacks alike) with identical click routing from
  either surface. Dynamically registered entries such as a session's Beads
  or voxd's Music appear in the World menu, which previously showed only
  hard-coded sections. Both surfaces also fail identically: one guarded
  render path keeps the ImGui window stack balanced even when a menu
  action's event emission fails mid-click.
- **Scene updates no longer steal focus.** Re-pushing an existing scene — a
  beads refresh, a now-playing update — repaints it in place: a minimized
  frame stays minimized, the focused frame keeps focus, and the selected tab
  stays selected. Only a genuinely new scene raises its frame and takes
  focus. The user controls what is front-most; updates do not.

## [0.22.1] - 2026-07-29

### Removed

- **The built-in luxd-side Beads Browser.** luxd no longer registers a
  permanent-lease "Lux — Beads Browser" session and no longer runs `bd`
  in-process. luxd's launchd environment has no `PATH`, no repository
  credentials, and no repository working directory, so a click on the built-in
  produced `bd unavailable — No such file or directory: 'bd'`. Beads now
  belongs to the session that has a repo shell: each lux-enabled session
  registers its own Beads menu callback and services a click by running `bd`
  from its own working directory. `BuiltinBeadsCallbacks`, its startup
  registration, `BeadsBrowser.render()`, and the `BeadsBoardInstaller` are gone;
  the `bd` load-and-shape payload machinery the CLI's `lux show beads` uses is
  unchanged.

### Added

- **`register_callback` MCP tool.** A session registers its own menu callback
  over MCP (the same operation the `POST /menus/callbacks` REST route exposes),
  guarded by the same identity challenge as a scene write. This lets a
  lux-enabled Claude Code session put its own repo-labeled Beads entry in the
  menu and service the click from its shell.

## [0.22.0] - 2026-07-29

### Removed

- **The `register_tool` menu path.** The `register_tool` MCP tool, the
  `POST /menus/items` REST route, and the display's per-connection
  registered-items machinery are gone — a menu item is a session callback
  now (`register_callback`), withdrawn with its session's lease. Agent menu
  bars via `set_menu` are unaffected.
- **The legacy render path is gone** — the element migration's final step.
  Every element kind renders through the Element-ABC / Hub-Display
  architecture; the legacy dataclass classes, their codec registry, and the
  four legacy display renderers (about 4,900 net lines) are deleted, with a
  structural test guarding against reintroduction. **The `paged` group layout
  is removed from the wire contract** (operator-ruled): an agent sending
  `layout="paged"` or the `pages`/`page_source` fields gets a named rejection
  explaining the removal. Native scrolling covers the use case; pagination
  can return later as a purpose-built feature. The display also now survives
  a version-skewed peer: an undecodable pickled element is rejected by name
  instead of killing the display process, and container decode errors name
  the parent container holding the bad child.

### Added

- **The menu bar shows live sessions.** The display renders the Hub's
  session-then-callback tree — one submenu per live session ("name — repo"),
  its callbacks as entries — updated whenever a session registers, withdraws,
  or lapses. A click travels from the pixels through the Hub to the owning
  session's delivery leg, end to end. Agent-defined menu bars (`set_menu`)
  are unchanged, and the built-in beads browser is now itself a
  permanent-lease callback session invoking through the same path.
- **Buttons can publish.** An in-scene button may declare
  `publish: {topic, payload}`; a click fires Hub-side and publishes the
  payload to the topic on Hub pub-sub, reaching WebSocket and MCP
  subscribers. Composes with regular click handlers; a blank topic rejects
  the element tree before render.
- **Menu items are session callbacks now.** An identified session registers a
  named callback (`POST /menus/callbacks`, guarded by the same identity
  challenge as a scene write); the menu shows one submenu per live session that
  registered one, labeled from the session's identity and the repository it
  connects from, with its callbacks as the leaves — the uniform
  session-then-callback shape, whatever the count, and two sessions are never
  merged. A callback lives on its session, so it leaves the menu the moment the
  session's lease lapses. A click routes to the owning session's bounded hold;
  the delivery legs that drain it, and the display rendering, arrive in the
  following slices. See `docs/architecture/menu-capability-model.md`.
- **Menu clicks are delivered to their owning session.** A click's held
  invocation reaches the session three ways, chosen by how the session connects,
  never by a client-kind branch: an MCP session polls the `pending_callbacks`
  tool, a periodic/cron client polls `GET /menus/callbacks/pending` (both drain
  the caller's own hold), and a persistent daemon is **pushed** the click the
  instant it lands, over a new WebSocket listen leg at `/ws`. The persistent leg
  works click-to-handler end to end.
- **`LuxHubClient` — the persistent hub client.** `from punt_lux import
  LuxHubClient` (or `rest_client.listener(...)`, sharing one identity) holds a
  live WebSocket to `luxd`, subscribes to pub-sub topics, and dispatches both
  those events and the menu callbacks routed to its session to app handlers in a
  blocking receive loop that renews the lease on contact and reconnects on a
  dropped connection. The Hub buffers clicks missed during a gap and drains them
  on reconnect. The wire frames are typed (pydantic, discriminated by `kind`).
- **Sessions declare their own lease.** `ClientIdentity.lease_ttl` (5 s–1 h,
  rejected outside the bounds, carried on both REST and WebSocket identify) —
  a daemon declaring 30 s vanishes from the menu on the lease timer if it
  dies; sessions that declare nothing keep their kind defaults, so luxd's
  built-ins stay permanent. Daemons identify explicitly via
  `LuxRestClient.for_identity(ClientIdentity(...))`; `connect()` remains the
  CLI's context-deriving path, and `ClientIdentity` is now a public export.
- **`LuxRestClient` is the public Python library API.** `from punt_lux import
  LuxRestClient` — typed requests and results, no display extras required, and
  client identity built in. Python programs use the library; shell scripts and
  cron jobs may still call the REST routes directly.
- **The CLI identifies itself on every run.** Identity derives from the git
  root (override with `LUX_CLIENT`, headless fallback otherwise), so scenes
  installed from a repo are owned by that repo — `lux show beads` boards now
  attribute truthfully.
- **Client sessions carry TTL leases.** Any authenticated contact renews;
  expired sessions are swept opportunistically, so identified REST callers no
  longer accumulate forever. Per-kind defaults: MCP sessions 30 min, CLI runs
  90 s, apps permanent.
- **Anonymous REST writes are rejected.** An identity-less scene-owning write
  now returns 401 with the identification-required challenge (reads stay
  open), completing the phased shutdown of anonymous ownership.
- **Scene owners are real identities now.** Ownership records carry the
  declared identity (kind, name, repo) snapshotted at install — attribution
  survives the owning connection's departure — and `list_scenes` reports
  structured owners. The anonymous shared `rest` pseudo-session is gone:
  every REST request resolves its own identity, two anonymous callers never
  share a connection, and an identity-less write still works but carries an
  identification-required signal (the first step of phasing anonymous REST
  out). Reads stay silent.
- **Clients can identify themselves.** A new `identify` MCP call lets a
  session declare who it is — kind (`mcp-session`, `cli`, or `app`), name,
  repository, and optionally an agent handle — and `list_clients` shows the
  declared identity beside each connection. This is the first slice of the
  client-identity model: an "identification required" error shape now exists
  (HTTP 401 on REST) for operations that will demand identity in the next
  slice. Identity is attribution only — nothing about scene lifetimes
  changes.

- **The table's grid/detail split is draggable.** Every `show_table` view with
  a detail pane now renders the grid and the detail as two panes separated by
  a horizontal divider you can drag to reallocate their heights. The dragged
  ratio is display-local view state — it survives scene re-pushes (the beads
  poller included) and clears when the scene is removed. The initial split
  still comes from the Hub-side default, biased toward the detail.

- **The table migrated to the Element-ABC path — all 25 kinds now on the new
  architecture.** The core `table` is a basic data grid: columns, rows, a
  `key_column` attribute (index or column name) giving every row a stable id,
  and a `selection_mode` of `none`, `single`, or `multi`. Row selection is
  Hub-authoritative and survives sorting, filtering, and row reordering
  because it names key values, never positions. Multi-select uses ImGui's
  native API (ctrl/shift/box gestures); column sort now actually works (the
  legacy flag drew arrows that did nothing); the built-in 10-row pager is
  replaced by native scrolling. Filter bars, search boxes, and detail panels
  are no longer table features — they are compositions of existing elements
  wired through Hub-side handlers, with `FilteredTableModel` holding the full
  row set and full selection so filtering never forgets a hidden selection.
  `show_table` gained `key_column` and `table_id` parameters and builds the
  composed experience server-side; the beads browser and data-explorer are
  rebuilt on the same composition. Columns auto-size proportionally to their
  content when no explicit widths are given, and the grid reserves scroll
  space so a detail panel stays visible below it. REST gained
  `PUT /scenes/{id}/table` and `/dashboard` routes that construct the
  composition server-side — pushing a composed table as plain JSON through
  the generic render route cannot carry the Hub-side filter and detail
  handlers, so table/dashboard callers must use the dedicated routes.
- **Tree, plot, and draw migrated to the Element-ABC path.**
  The three kinds now self-validate at the Hub: a malformed plot series
  (non-string label, non-numeric coordinate), a wrong-schema draw command, or
  a label-less tree node is rejected back to the agent with an error naming
  the offending index and field — payload classes that previously crashed the
  display or rendered silently wrong. Tooltips are functional on all three
  kinds. Tree node expansion stays display-local view state. The legacy tree
  node-click event was removed with the migration; it had no consumers.
- **Geometry introspection.** `inspect_scene` (MCP and REST) accepts
  `want_geometry`; the reply carries each painted element's on-screen
  rectangle plus z-order — a paint-sequence number per element and a window
  stacking index — read from the display's last completed frame. An element
  that didn't paint (collapsed, clipped, closed) is absent from the map.
  Geometry stays display-local state; the query only reads it. Capture costs
  about 40 µs per frame for a 50-element scene. Agents can now verify size,
  position, overlap, and stacking without a human looking at the screen.
- **Inline image data renders.** An `image` element with base64 `data` now
  decodes and paints (content-hash cached), where it previously fell through
  to its alt text. A malformed payload degrades to alt text with one warning
  in the display log — never a crash, never once-per-frame log spam (missing
  image files also now log once instead of every frame).
- **Optional frame TTL.** A frame can carry `ttl_seconds` at show time (MCP
  `show` and REST `PUT /scenes/{id}` via `frame.ttl_seconds`); the Hub retires
  the frame when the TTL elapses, removing its scenes from both the Hub store
  and the display. No TTL means the frame is permanent until dismissed. TTLs
  exist at the frame level only.

### Changed

- **Every agent scene renders in a frame.** A `show()` (MCP, REST, or CLI)
  that names no frame gets one synthesized — `frame_id` is the scene id, the
  title comes from the request — so all agent content is closable, can carry
  a TTL, and is removed cleanly; frameless rendering is reserved for the
  display itself (the background and idle screen). The unframed render path
  is deleted. Frame options (`frame_size`, flags, layout, `ttl_seconds`) now
  take effect whether or not a `frame_id` is named.
- **Element migration batch B4: `window` and `modal` are on the Element-ABC
  path** (21 of 25 kinds migrated). A modal is now dismissal-convergent:
  the close button and Escape route through the Hub, a dismissed modal is
  removed (a re-push cannot resurrect it), and if the dismissal cannot reach
  the Hub the popup visibly reopens rather than silently diverging. Clicking
  outside a modal deliberately does not dismiss it — a modal blocks. A window
  element keeps its view state (drag/resize) local to the display and
  deliberately has no close affordance — dismissal belongs to frames.
  Renaming an open modal or window no longer dismisses it or resets its
  position.
- **Interaction events are element-owned.** Each interactive element declares
  its wire kind, payload validation, and event construction on its own
  `RemoteDispatchSpec`; the central event-building ladder is deleted. A
  remote invocation naming the wrong kind — or no kind at all — gets a named
  denial instead of being guessed at, and a new interactive kind registers in
  exactly one place.
- **Element migration batch B1: `image`, `separator`, `spinner`, and
  `markdown` are on the Element-ABC path** (19 of 25 kinds migrated; the
  legacy code for each is deleted). User-visible effects: `tooltip` now works
  on all four kinds (the legacy path silently dropped it); an `image` is
  either a path image or a data image, validated one-or-the-other with named
  errors; a `spinner` rejects a zero or negative `radius` instead of
  invisibly painting nothing.
- **An element with an empty `id` is rejected at decode with a named error**
  (separators excepted — they are anonymous by design). Previously an empty
  id could crash the display window mid-install.
- **Scenes survive their session.** A disconnected or idle-reaped MCP session
  no longer takes its rendered frames with it — subscriptions, inbox, and menu
  items are still cleaned up, but what's on screen stays until the user closes
  the frame, the agent clears or empties the scene, or a frame TTL expires.
- **An empty-element push now removes the scene** (and closes its frame)
  instead of storing an empty husk. A zero-row table is still content — only a
  push with no elements at all is a removal.

### Fixed

- **Clearing is scene-scoped and honest.** A new `clear_scene` MCP tool and
  `DELETE /scenes/{scene_id}` REST route clear one scene; `clear()` empties
  only the caller's scenes. Clearing one scene no longer blanks every board on
  the display, a cleared scene blanks into its own frame (custom frame
  bindings preserved), and a clear that removes nothing says so — an unknown
  scene returns not-found and an unowned scene a rejection, never a false
  "cleared". The dead global-clear wire machinery is deleted.
- **Markdown arrows render.** The markdown renderer now uses a packaged,
  subsetted DejaVu Sans quad (~648 KB) instead of imgui_md's bundled Roboto
  subset, which lacks the arrow glyphs entirely — so U+2192 and kin render in
  markdown text and tables instead of tofu. Markdown body text changes
  typeface to DejaVu. If the packaged fonts are missing the display warns and
  falls back to the default font rather than failing.
- **Display clicks survive a Hub connection drop.** The display no longer
  severs its one client on a transient would-block send (a slow-but-alive peer
  defers; only a dead peer disconnects), interactions are held in a short
  bounded buffer across a dropout and delivered in order on reconnect, and
  luxd runs a keepalive that detects a dead display connection within seconds
  instead of waiting for the next scene push. Previously one full socket
  buffer during a busy frame silently killed row selection and every other
  interaction for minutes. The buffer bound is derived from the keepalive
  constants so a tuning change cannot silently break the coverage; an
  interaction that still ages out is compensated (a modal reopens, an
  optimistic row selection clears) so the two tiers never silently diverge.
- **The beads board's search, filters, and detail pane work again.** `lux show
  beads` (and the Hub-menu beads item) built the table chrome client-side and
  pushed it through the generic render route, whose wire decode cannot carry
  Hub-constructed handlers — so search, status/type filters, and the detail
  pane were dead while sort and selection worked. The CLI now sends the board
  as data over `PUT /scenes/{id}/table` and the Hub composes the chrome with
  live handlers. The detail pane also got a cleanup: a fields table (ID,
  status, priority, type, owner, dates), a rule, then the description as
  paragraphs — and the generic `show_table` detail card now renders one field
  per line instead of collapsing them inline. A board render rejected by the
  Hub now shows a visible error scene instead of silently doing nothing.
- **Multi-client event broadcast no longer stops at the first successful
  send** — every connected display client receives the event.
- **A `window` element rejects non-finite placement** (infinite or NaN
  position/size) at validation instead of passing it to the renderer.
- **Closing a frame in the window now removes its scenes from the Hub.**
  Previously the click closed the frame locally and the Hub kept the scene —
  the tiers silently diverged and empty "husk" frames accumulated across
  sessions.
- **The `screenshot` tool reports capture as unsupported** (with the DES-028
  reference) instead of leaking an internal display error, and its docstrings
  no longer promise a PNG path.

## [0.21.0] - 2026-07-22

### Added

- **Direct HTTP MCP connection to luxd, no mcp-proxy in the path.** With luxd on
  streamable HTTP, Claude Code can connect natively at
  `http://127.0.0.1:8430/mcp` through its HTTP MCP configuration. A copy-paste
  config is in `.claude-plugin/mcp-http.example.json`, and
  `scripts/direct_connection_probe.py` drives a real session end to end
  (initialize, list tools, call a tool) as runnable proof. See DES-055.

### Changed

- **luxd's MCP leg moved from WebSocket to streamable HTTP.** luxd now serves
  MCP over the mcp SDK's streamable-HTTP transport, mounted beside the REST
  routes on the same FastAPI app and loopback port at `/mcp`. Every MCP session
  capability is preserved — per-session identity (including the reserved-REST
  refusal, now a 403), the register/cleanup lifecycle (menu drop plus the
  disconnect cascade of scenes, subscriptions, writer, and inbox), pub-sub
  `recv` delivery, and the byte-identical tool surface (the characterization
  corpus stays green without regeneration). The loopback trust policy migrates
  onto the SDK transport's Host (421) and Origin (403) validation. luxd now
  refuses a non-loopback `--host` at startup with one clear line rather than
  binding a wider interface than its guards trust. See DES-055.

- **The plugin connects to luxd directly over HTTP.** `.claude-plugin/plugin.json`'s
  `mcpServers.lux` block is now `{"type": "http", "url": "http://127.0.0.1:8430/mcp"}`
  — the `mcp-proxy` stdio bridge and its `lux serve` fallback are gone. The
  installer pins `luxd` to `--port 8430` in the launchd plist, so the static URL
  is correct for installed systems; on a non-default port, read it from the port
  file (`~/.punt-labs/lux/hub.port`). This completes the WebSocket-to-HTTP swap
  on the install path: a plugin shipped before this could not reach the
  WebSocket-less luxd. See DES-055.

- **The command-line tool is the third thin client of the engine.**
  `lux show beads` and `lux ping` now reach luxd over its typed REST API through
  a small `LuxRestClient`, instead of opening the display's Unix socket. The CLI
  no longer constructs a `DisplayClient`, so the display socket has become
  Hub-internal plumbing with exactly one client — luxd. A guard test names the
  allowed set (the client module and luxd's connection registry) and fails on
  any new direct consumer. `lux show beads` builds the same beads scene as
  before and `PUT`s it to `/scenes/{id}`; `lux ping` calls `GET /display/ping`.
  When luxd is not running, both fail with one actionable line
  (`luxd is not running. Run 'lux hub-install' to register the service.`) and a
  non-zero exit, rather than a traceback. See DES-055.

### Removed

- **The deprecated WebSocket MCP transport.** luxd's `/mcp` WebSocket route, its
  `mcp.server.websocket.websocket_server` import, and the two `reportDeprecated`
  suppressions that import required are gone — no dual transport. With the WS
  server dependency removed, the `mcp<2` cap lifts to `<3` (the `>=1.28.1`
  security floor stays; FastMCP governs the effective upper bound).
- **`--socket` on `lux show beads` and `lux ping`.** The CLI addresses luxd by
  its port (read from the hub port file), not the display socket path, so the
  `--socket`/`-s` option on these two commands is gone; `lux ping` keeps
  `--timeout`. `punt_lux.DisplayClient` and the `LuxClient` alias are no longer
  exported from the package root — the display client is Hub-internal.
- **`mcp-proxy` leaves lux's path entirely.** With the plugin on direct HTTP,
  the `lux serve` (stdio MCP) and `lux setup-proxy` commands and the
  `punt_lux.remote` module (the `mcp-proxy` TOML config writer) are removed, and
  `install.sh` no longer installs or configures `mcp-proxy` — the installer's
  job is luxd, the marketplace, and the plugin. A Hub-bypassing in-process stdio
  server contradicts the single-engine model; luxd is the one front door.

### Fixed

- **A vanished MCP client no longer strands its session.** luxd hands the SDK
  session manager a `session_idle_timeout` (1800s), so a client that dies
  without a clean disconnect is reaped and its Hub-side state (scenes, menus,
  subscriptions, inbox) released, instead of living until restart.
- **Session teardown is isolated.** Each cleanup leg (menu drop, disconnect
  cascade) runs independently and logs any failure against the session key, so
  one failing leg cannot starve the other or surface as an unattributed SDK
  "session crashed".
- **The live session count reflects instances, not unique keys.** Two sessions
  admitted under the same key count as two, and the first to disconnect leaves
  the peer counted (previously a same-key disconnect could drop a still-live
  peer from the count).
- **Shutdown drains sessions before stopping the writer.** The caller lifespan
  (the display replicator) is the outer scope, so each session's cleanup cascade
  runs while the replicator carrying its display effects is still alive.

## [0.20.0] - 2026-07-22

### Added

- **Typed REST surface on luxd** — a second thin client of the operations
  facade, mounted beside the WebSocket MCP leg on luxd's one FastAPI app. Every
  routable capability gets a typed route (`PUT /scenes/{id}`,
  `PATCH /scenes/{id}`, `DELETE /scenes`, `GET /scenes`, `GET /scenes/{id}`,
  `GET /clients`, and the `/menus`, `/display`, `/display-mode`, `/events`, and
  `/errors` routes). Each route binds a request model, calls one operation, and
  maps the discriminated result to HTTP through one shared table —
  `invalid_request` → 422, `not_found` → 404, `rejected` → 409, `fault` → 502,
  `display_unavailable` → 503, `timeout` → 504 — so a route body is
  parse-call-format only and a new operation inherits the mapping. The request
  and response models are the operations layer's own; nothing is duplicated.
  `/health` becomes a typed route returning `HubHealth`, a plain liveness probe
  (process up + session count, not hub/replicator health). A route-parity guard
  test fails if a facade operation gains no route, so REST cannot silently fall
  behind the engine. Session-scoped pub-sub (publish/subscribe/receive) and the
  tree-composing conveniences stay MCP-only, where their callers are: a
  connection-less REST publish in one fixed scope can never deliver, so it is
  not exposed until the REST-session decision lands. See DES-055.
- **`fault` operation error / HTTP 502** — a new `OpError` code for an
  engine-side failure on a *valid* request, distinct from a caller error
  (`rejected`/`invalid_request`) and a down display (`display_unavailable`). Any
  malformed display reply the model cannot narrow — a screenshot with no path, a
  ping with no round-trip time, a frame ack for the wrong or a missing frame, or
  any theme/window/info/events/errors reply that fails validation — now reports
  `fault`, not `rejected`. A config-file read or write that raises `OSError`
  (the display-mode file is a directory, its parent is a file) is also a `fault`
  rather than an uncaught crash: the config file is a backing resource, caught at
  the `DisplayModeStore` boundary. `rejected` stays reserved for the engine
  refusing a caller's write. REST maps `fault` to 502.
- **Self-validating elements** — elements now check their own inputs. `show`
  decodes the element tree, then a hierarchy walk calls each element's
  `validate()` and collects *every* error across the tree (no fail-fast),
  recursing into every container (`group`, `window`, `modal`, `tab_bar`,
  `collapsing_header`, `tree`). An invalid tree is rejected before render and
  the full error set is returned to the agent so it can self-correct; a valid
  tree renders unchanged. Validation is component-appropriate and lives on the
  element: `TableElement.validate()` checks each row's cell count against the
  column count and that cells are renderable scalars — reporting, not crashing,
  when `columns`/`rows` arrive malformed; `TreeElement.validate()` checks its
  node structure instead of silently dropping malformed nodes. Contract:
  `SelfValidating` / `HasChildElements` protocols, a `ValidationError` value
  object, and a `ValidationReport` aggregate; the Element ABC supplies an
  empty-leaf default so every kind participates. A structural guard test fails
  if a new container kind is added without exposing its children, so nested
  elements can never silently skip validation. See DES-039.
- **Render engine — `Element.render()` is the paint path** — a fixed
  Template-Method skeleton (`_begin` / `_paint_self` / `_render_children` /
  `_end`) on the Element ABC, with per-kind ImGui adapters resolved through the
  factory, replaces the hardcoded leaf-vs-composite branch. Migrated kinds now
  *paint* through `render()` — not merely flip type/routing — so
  `render_path == "abc"` means the element renders via the new path. See
  DES-042.
- **`group` container on the ABC path (rows / columns)** — the first container.
  A `group` decodes to the ABC `GroupElement` only when its whole subtree is
  migrated-ABC (the all-ABC gate); otherwise the renamed `LegacyGroupElement`.
  A legacy container forces its nested groups legacy, so an ABC container is
  never nested in a legacy one — the `[unsupported element]` regression is
  structurally impossible (DES-041). Columns render via imgui stack layout.
- **`progress` display-only leaf on the ABC path** — the first display-only
  primitive; a single ABC `ProgressElement` with a `[0,1]`+NaN `validate()`
  (the fraction is validated pre-render instead of clamped by ImGui), enforced
  on both the `show` and the `update`/patch write paths.
- **`collapsing_header` interactive container on the ABC path** — the first
  interactive container: a `GroupElement`-shaped box composed with a single
  Hub-authoritative `open` flag (the checkbox interaction pattern). A user
  toggle fires `header_toggled`, which routes to the Hub (D21), the Hub mirrors
  the new `open` and re-pushes; an agent drives the same field by patching
  `open` and the ImGui adapter honours it every frame via `set_next_item_open`.
  A Hub-driven change never re-fires (echo-suppression), so no fire→Hub→re-push
  loop can run. The single `open` field replaces the legacy `default_open` on
  the ABC path. Decodes to the ABC `CollapsingHeaderElement` only when its whole
  subtree is migrated-ABC; otherwise the renamed `LegacyCollapsingHeaderElement`
  (a legacy container forces it legacy). `resolved_props()` reports the
  authoritative `open` view-state. The all-ABC gate is now the shared
  `ContainerAbcGate`, reused by `group` and `collapsing_header`. See DES-045.
- **`tab_bar` interactive tabbed container on the ABC path** — a container
  composed with a Hub-authoritative active-tab selection. Every tab carries a
  stable `tab_id` — the agent-supplied id when present, else a content slug of
  the tab's label (deduplicated with a numeric suffix only when a label repeats)
  assigned by `TabIdSynthesizer` — and the selection names that id, never a
  positional index (DES-045); reconciliation on a structural change is a
  membership check — an added tab leaves the selection unchanged, a removed
  active tab resets to the first live tab, a relabel is stable. The
  reconciliation invariant is enforced on every mutation, so an `active_tab`
  patch naming a stale tab resets rather than installing a dangling selection.
  A user tab click fires `tab_changed` → Hub → re-push; an agent drives the same
  field by patching `active_tab`, and the ImGui adapter honours it, distinguishing
  a Hub write from a user gesture via per-scene `WidgetState` so a Hub-driven
  change never re-fires (echo-suppression). On the first frame the declared
  `active_tab` is force-selected, so a non-first initial tab is never clobbered
  by ImGui's tab-0 default. The tab strip is painted through a small
  `TabContainerRenderer` sub-protocol and a `_render_children` override; every
  tab's children cross the wire (only the active tab is drawn). A present-but-not-
  a-list `tabs`/`children` is rejected rather than silently emptied. Decodes to
  the ABC `TabBarElement` only when the whole subtree is migrated-ABC, else the
  renamed `LegacyTabBarElement`; `resolved_props()` reports `active_tab` and the
  tabs. See DES-045.
- **`slider` interactive numeric input on the ABC path** — the second non-atomic
  mutable control (after `input_text`). A single ABC `SliderElement` (float
  `value`/`min`/`max`, a printf `format`, an `integer` variant flag) carrying a
  commit-on-idle drag reconciliation: while idle the thumb tracks the Hub value,
  while dragging the local buffer wins so a Hub re-push landing mid-drag cannot
  clobber the value under the thumb, and exactly one `ValueChanged` fires on
  release (never per drag frame). Through the echo-latency window the just-
  committed value is honoured optimistically, so a re-grab builds on it. The
  discipline is the *same* verified state machine `input_text` uses
  (`docs/commit_on_idle_reconciliation.tex`) — the model is type-agnostic, so the
  shared `ContinuousEditArbiter[T]` drives it for the float carrier via a
  `FloatValueAccessor` (the `ValueAccessor[T]` seam) unchanged; exact float `==`
  is the correct reconciliation predicate (values are
  copied not recomputed, JSON round-trips doubles exactly). `validate()` rejects
  an inverted range, an out-of-range value, a non-finite `value`/`min`/`max`
  (`NaN`/`±inf` — the soundness precondition for value-equality reconciliation),
  and a malformed `format`; because `min`/`max` are patchable the range invariant
  is re-checked at the element boundary (a combined patch is judged on its final
  state, so a value arriving before its widening `max` is accepted). Decodes to
  the ABC path when its subtree is all-ABC; `resolved_props()` reports
  `value`/`min`/`max`/`format`/`integer`/`tooltip`.
- **`color_picker` interactive color input on the ABC path** — the third
  non-atomic mutable control (after `input_text` and `slider`). A single ABC
  `ColorPickerElement` (hex-string `value`, orthogonal `alpha`/`picker` flags)
  carrying a commit-on-idle drag reconciliation over an **RGBA-tuple carrier**:
  while idle the picker tracks the Hub color, while dragging a sub-control the
  local buffer wins so a Hub re-push landing mid-drag cannot clobber the color
  under the cursor, and exactly one `ValueChanged` fires on release. The
  color_edit/color_picker sub-controls each fire an independent deactivate, so a
  gesture across the SV square and hue bar commits the whole color once per
  sub-control release — never a partial channel. The discipline is the *same*
  verified state machine `input_text`/`slider` use
  (`docs/commit_on_idle_reconciliation.tex`) — the model is type-agnostic, so the
  shared `ContinuousEditArbiter[T]` drives it for the RGBA-tuple carrier via a
  `ColorValueAccessor` (the `ValueAccessor[T]` seam) unchanged. All three
  non-atomic controls (`input_text`, `slider`, `color_picker`) now fold onto that
  one generic arbiter plus three trivial `@final` accessors, replacing the
  bespoke per-element arbiters. Tuple `==` is elementwise, so the optimistic-echo
  window closes
  atomically only when every channel echoes back; the renderer commits the
  *quantized* (8-bit round-tripped) tuple so the committed value bit-equals the
  echo (no full-precision→8-bit color pop). `validate()` rejects a malformed hex
  (the reconciliation-soundness precondition — a well-formed hex parses to finite
  channels, so no `NaN` is reachable and no `math.isfinite` loop is needed);
  length is not checked against `alpha` (a 6-digit value under RGBA pads to
  opaque, an 8-digit value under RGB drops its alpha). A new frozen `RgbaColor`
  value object owns the hex↔tuple↔hex conversion. Decodes to the ABC path when
  its subtree is all-ABC; `resolved_props()` reports
  `value`/`alpha`/`picker`/`tooltip`.
- **`input_number` interactive numeric input on the ABC path** — the fourth
  non-atomic mutable control (after `input_text`, `slider`, `color_picker`). A
  single ABC `InputNumberElement` (float `value`, a printf `format`, an `integer`
  variant flag, and genuinely-optional `min`/`max`/`step` where `None` means
  unbounded / no stepper) carrying a commit-on-idle typing reconciliation: while
  idle the field tracks the Hub value, while typing the local buffer wins so a Hub
  re-push landing mid-edit cannot clobber the value under the cursor, and exactly
  one `ValueChanged` fires on commit (blur / Enter / a stepper release) — never
  per keystroke. The discipline is the *same* verified state machine the other
  three controls use (`docs/commit_on_idle_reconciliation.tex`) — the model is
  type-agnostic, so the shared `ContinuousEditArbiter[T]` drives the float carrier
  via the existing `FloatValueAccessor` (the `ValueAccessor[T]` seam) **unchanged**;
  the `integer` variant is a coercion at the `input_int` widget seam (`int` payload,
  `float` carrier), `float(int)` round-tripping exactly. `validate()` rejects an
  inverted range, an out-of-range value, a non-finite `value`/`min`/`max`/`step`
  (`NaN`/`±inf` — the value-equality soundness precondition), a non-integral
  `value`/bound/step under the integer variant, a negative `step`, and a malformed
  `format`; because the bounds are patchable the invariant is re-checked at the
  element boundary (skipping any absent bound), so a combined patch is judged on
  its final state. The range/finiteness/format predicate is extracted into a
  composed `NumericInputChecks` value object so the element module stays within the
  size budget. Decodes to the ABC path when its subtree is all-ABC;
  `resolved_props()` reports `value`/`min`/`max`/`step`/`format`/`integer`/`tooltip`.
- **Number-input tooltips are now shown** — a `tooltip` on a numeric input was
  previously dropped on the wire (the legacy codec never emitted or read it); it
  is now carried and rendered, matching `input_text`/`slider`/`color_picker`/`checkbox`.
- **Color-picker tooltips are now shown** — a `tooltip` on a color picker was
  previously dropped on the wire (the legacy codec never emitted or read it); it
  is now carried and rendered, matching `input_text`/`slider`/`checkbox`.
- **Slider tooltips are now shown** — a `tooltip` on a slider was previously
  dropped on the wire (the legacy codec never emitted or read it); it is now
  carried and rendered, matching `input_text` and `checkbox`.
- **Hub-authoritative writes (`update` / `clear`)** — the MCP `update`
  (field-patch, remove) and `clear` tools now mutate the authoritative
  `HubDisplay` store and re-push the affected UI, instead of patching the Display
  directly, so the Hub wins every disagreement. One model-agnostic write contract
  at a single seam: an Element-ABC element is patched in place (`apply_patch`,
  preserving handlers/observers); a legacy element is realized by
  `dataclasses.replace()` (sharing untouched fields by reference) — no legacy
  class is modified, so the seam is *deleted*, not unwound, when a kind migrates.
  A batch is all-or-nothing; the authoritative mutation runs once (only the
  idempotent re-push is retryable); every write is ownership-checked and validated
  with the same walk `show` uses. `id` and `kind` are immutable; a structural
  field (`children`/`pages`/`tabs`, which carries child elements) or a legacy
  element nested below a legacy composite is rejected fail-loud and directed to
  `show` (the always-correct whole-tree resend) — no bridging. See DES-047.
- **Tree-level element-id uniqueness** — the Hub rejects a submitted tree that
  reuses a named element id (two elements sharing an id, or an id used as both a
  root and a nested child) before install, returning the same `DuplicateIdError`
  the Display already raises; anonymous (empty-id) elements such as separators
  may repeat. Closes a path where a duplicate id desynced the Hub's root tracking.

### Removed

- **The Display-side incremental patch path.** The `UpdateMessage` wire type and
  the `Patch` protocol export are dropped from the public API (`punt_lux.__all__`
  / `protocol`), and the `patch` element kind, `patch_applier`, and `widget_sync`
  are deleted. `update` / `clear` now route through the Hub-authoritative write
  path (DES-047) with a whole-UI re-push — the target's whole-UI-resend
  replication model — so the Display no longer applies field-level patches
  locally, and bad-patch crash-freedom moves Hub-side (reject-before-install).

### Fixed

- **`get_display_info` no longer rejects its own valid payload (DES-055, PR B).**
  The tool's MCP output schema is now derived from the `DisplayInfo` result model
  rather than hand-maintained, so a schema built from the model cannot reject a
  payload the model accepts — the drift that made the tool refuse a live display's
  metadata is gone.
- **Plot series without labels no longer flicker or fight for one legend slot.**
  Two series that share a label — including the label-less default "data" —
  used to collide on a single ImPlot item. Each series and each plot is now
  scoped on the ImGui id stack, so labels and titles render verbatim (a label
  ending in "#" is no longer truncated) while every item still gets a distinct
  id. A non-str wire label is rejected rather than rendered as garbage.
- **MCP tools no longer block on the display; the 38-minute hang class is closed
  by construction.** Every mutation tool (`show`, `show_table`, `show_dashboard`,
  `update`, `clear`) now writes only to the Hub's authoritative store and returns
  at once — `show*`/`update` return `"shown:<scene_id>"`, `clear` returns
  `"cleared"`. A single background `HubReplicator` is the sole writer to the
  display: it coalesces changes, sends them with a time-limited socket
  (`SO_SNDTIMEO`), and alone reaps and respawns a wedged display or reconnects a
  dead one. Because no send sits on the agent's path, a stuck display can never
  again freeze an agent (previously a `clear` to a wedged display blocked ~38
  minutes). `recv` loses its `timeout` and drains the inbox without blocking;
  the `set_*` tools do a time-limited round-trip and return `"timeout"` rather
  than hanging or killing the display; the `lux show beads` CLI checks
  `DisplayPaths().is_running()` before it sends. The concurrency discipline is
  ProB-verified (`docs/hub_replicator.tex`).
- **lux MCP tool calls now fail fast on an unresponsive display** — the
  `mcpServers.lux` entry in `plugin.json` gains a per-server `timeout` of 5s.
  Without it, calls inherited the ~30-minute default MCP idle timeout, so a
  single hung call (e.g. `clear` against a stalled Display or `mcp-proxy`→`luxd`
  WebSocket) blocked the agent for tens of minutes. lux renders are tens of
  milliseconds; anything past ~5s means the surface is broken, so the call
  aborts there rather than waiting on a dead display.

- **Color-picker channel bars now scale with their value in both modes** — every
  RGB(A) channel fill is painted proportional to its 0..255 value (0%..100%)
  instead of ImGui's fixed 3px color marker, which drew an identical sliver for
  `R=216` and `R=37`. Both the inline `color_edit` variant and the full `picker`
  variant route their channels through a shared `ColorChannelStrip` that
  replicates ImGui's grouped layout while painting its own scaled fill; the full
  picker keeps the SV square, hue bar, and hex readout via a `FullColorPicker`
  widget (with a fixed 240px item width constraining the previously oversized
  square). Every sub-control stays inside one `begin_group`/`end_group`, so the
  single `is_item_active` / `is_item_deactivated_after_edit` read still aggregates
  over the whole control and the `ContinuousEditArbiter` commit-on-release seam is
  untouched — exactly one `ValueChanged` fires per gesture. The full picker's
  right-click context menu is disabled.
- **Interaction re-push no longer duplicates a container's children** — the Hub's
  `scene_roots` returned every indexed element (roots *plus* every descendant), so
  a re-push after an interaction hoisted each container child to a top-level root
  and rendered it twice. Roots are now tracked separately from children, so a
  re-push carries exactly the original root set.
- **Transient display state survives a narrow re-push** — a whole-root re-push
  from an `update` no longer clears a surviving element's display-local widget
  state (table selection, scroll, in-progress text). Only a removed element's
  keys are discarded — including a removed dialog's open/dismiss latches, so a
  re-added same-id dialog reopens instead of reading a stale "dismissed" latch.
- **No stacked display windows from a direct `lux display` or a concurrent
  spawn** — the display server now self-arbitrates at bind. `SocketServer.setup()`
  probes for a live display and exits cleanly if one is already serving,
  serializes its cleanup→bind→listen critical section under a dedicated bind-lock
  (distinct from the spawn lock, with a fixed spawn→bind acquisition order so the
  two can't deadlock), and treats a lost `bind()` race (`EEXIST`/`EADDRINUSE`) as
  "another instance won → exit 0" — the losing process exits before opening a
  window. The `listen()` backlog was raised (5→128) so a briefly-stalled display
  (not draining accepts) isn't misread as dead by a probe getting `ECONNREFUSED`
  on a full queue. (lux-h29e)
- **No agent patch can crash the display** — a bad `update()` patch (out-of-range
  / NaN / wrong-type value, an unknown field, a remove of a missing id) is now
  rejected **Hub-side, before install** (validate-before-install on the
  authoritative store; DES-047), so it never reaches the Display at all. This
  supersedes the earlier display-side per-patch catch (DES-043): the incremental
  patch-application path it guarded (`patch_applier`, and its ProB model) is
  removed in favour of the Hub-authoritative write path plus whole-UI re-push
  (see Removed).

### Changed

- **Operations layer — the single home of front-of-house logic (DES-055, PR A).**
  `render`, `update`, `clear`, the four pub-sub operations (`subscribe`,
  `unsubscribe`, `publish`, `receive`), and the two display-mode operations moved
  out of the MCP tool bodies into a new `operations/` package of typed concern
  classes. Each operation takes a Pydantic request and returns a discriminated
  result — its own success type or a shared `OpError` — instead of a magic
  string. The `show`, `show_table`, `show_dashboard`, `update`, `clear`,
  `display_mode`, `set_display_mode`, `subscribe`, `unsubscribe`, `publish`, and
  `recv` MCP tools became thin adapters that parse arguments, call one operation,
  and format the result. This is an internal restructure: the tools' string
  contract is unchanged and pinned byte-identical by the characterization corpus,
  so agents see no behavior difference.
- **Query, menu, and display-control surface on the one code path (DES-055, PR
  B).** The read and control tools moved into the operations layer, removing the
  tool→display reach-around. `inspect_scene`, `list_scenes`, and `list_clients`
  now read Hub-authoritative state (`HubDisplay` and the Hub session registry)
  instead of asking the display replica; menus become Hub-owned — `set_menu` and
  `register_tool` write a Hub menu registry and the background replicator pushes
  the bar to the display (the sole writer, no reach-around), and `list_menus` is
  a Hub read; the remaining display facts (`list_recent_events`, `list_errors`,
  `get_display_info`, `get_theme`, `set_theme`, `get_window_settings`,
  `set_window_settings`, `set_frame_state`, `screenshot`, `ping`) reach the
  display through one bounded Hub connection that returns an `OpError` instead of
  hanging or raising. The structured-output tools (`get_display_info`,
  `get_theme`, `get_window_settings`, `list_scenes`, `inspect_scene`,
  `list_clients`, `list_menus`, `list_recent_events`, `list_errors`) now return
  typed result models with the MCP output schema derived from the model; the
  string-return tools keep their exact status lines, pinned byte-identical by the
  characterization corpus. `list_clients` now answers with the Hub sessions and
  their scopes — the meaningful client list now that the display has one socket
  client (luxd).
- **Hub-side session logic relocated out of `tools/`.** The connection-scoped
  element decode (`hub_factory`) and the per-session inbox queues (`inbox`) moved
  into `domain/hub`, where the rest of the Hub session machinery lives.
- **`ValueChanged.value` widened to `bool | int | float | str`** (from
  `bool | str`) so a slider commit can carry its `float` (or `int` for the
  integer variant) alongside a checkbox `bool` and an input_text `str`. The
  Hub-side interaction-dispatch guard admits the same scalar set; the firing
  element re-validates the value's shape for its kind. `RemoteDispatchGroup`'s
  wire stamping already carried an opaque `value`, so no transport code changed.
- **CI runs the integration tier as a standing gate** — `.github/workflows/test.yml`
  now has an `integration` job running `make test-integration` (`pytest -m
  integration`, including the `tests/e2e/` business-event-loop harness, DES-044)
  on every PR and push to main, on the same `ubuntu-latest` runner the `test` job
  uses. It is wired as a **blocking** CI job (no `continue-on-error`), so a
  failure fails the check run; to enforce it as a required merge gate,
  `integration` must be added to main's branch-protection required status
  checks. Together these mean the e2e harness — the standing gate
  against the illusion of progress — can no longer rot into a
  manually-run-only suite. A
  separate `slow` job runs `make test-slow` (the `@pytest.mark.slow` timing class)
  with `continue-on-error: true`, so the frame-budget and probe-responsiveness
  smokes run for visibility/anti-rot but a rare timing hiccup on a loaded runner
  **never blocks a merge** — preserving the lux-gqai quarantine of wall-clock
  assertions out of the gating path. The `pyproject.toml` `addopts` default filter
  is unchanged; each job overrides the marker via its Make target.
- **Timing-sensitive tests isolated behind `make test-slow`** — the frame-budget
  smoke now carries `@pytest.mark.slow`, so the default serial gate (`make test`,
  `make check`) no longer runs it; `make test-slow` runs it alone. Its budget is
  loosened to 20 ms — ~70x above the ~0.28 ms measured cost — because an absolute
  wall-clock bound on a pure-CPU loop tracks machine load, not code. That
  headroom catches only a catastrophic blow-up (an infinite loop, accidental
  per-element I/O, O(n^2) work over the 600 render calls); it is deliberately not
  a 10x regression guard, since a 10x slowdown to 2.8 ms/frame still passes. The
  socket-probe test now asserts the probe returns `ACCEPTING` in the default gate
  (behavior, not wall-clock), with the timing guard preserved as a separate
  `@pytest.mark.slow` test that bounds `_probe` at 0.5 s — between the ~0.2 s
  handshake window and the ~1.0 s connect timeout — so a regression that blocks
  the whole connect timeout on a silent-but-live owner is still caught, just out
  of the serial gate. The `test_query` harness now joins its server thread before
  closing the socket and releases the timeout hold via an event — eliminating the
  recurring `Bad file descriptor` teardown warning and the fixed 3 s sleep. See
  `tests/CLAUDE.md`.
- **Beads board selects by stored status, not dependency-readiness** — the
  board's default query is now `bd list --json --status open,in_progress`
  instead of `bd ready --json`. Selecting by stored status shows every `open`
  issue plus whatever is `in_progress`, replacing `bd ready`'s
  dependency-readiness filter. Claimed beads no longer vanish the moment their
  status flips to `in_progress`, and open-but-dependency-blocked issues that
  `bd ready` hid are now visible too. The `--all` view is unchanged.
- **Element-ABC renderer-factory DI made real and honest** — the Display now
  rebinds its real `ImGuiRendererFactory` onto every received ABC element (a new
  `Element.bind_renderer_factory`), so `Element.render()`'s dependency is
  production-wired rather than the fail-loud sentinel it silently carried. The
  renderer-factory docstrings were corrected to describe what the code actually
  does (they had claimed a decode-time factory threading that never happened),
  and the interactive remote-dispatch wrap was made Open-Closed via a per-element
  `RemoteDispatchSpec` hook (removing an `isinstance` switch and a domain→protocol
  layering inversion). Internal only — wire output byte-identical. Prerequisite
  for the render-path unification.
- **Table and layout element codecs moved onto their dataclasses** — the
  module-level `_<kind>_to_dict`/`_from_dict` functions became `to_dict`/
  `from_dict` methods (PY-OO-5), and the container-recursion dispatcher was
  extracted to `container_dispatch.py`. Wire output is byte-identical (132
  characterization snapshots unchanged).
- **`hub_*` path helpers promoted to a `HubPaths` class** (`hub_paths.py`),
  mirroring `DisplayPaths` — extracted from `paths.py`, no behavior change.
  (lux-bsrs)
- **Display lifecycle formally specified and model-checked** — `docs/display_lifecycle.tex`
  is a Z specification of the spawn/reap/bind concurrency, `fuzz`-clean and
  ProB-verified for singleton-serving, never-unlink-live, no-two-winners,
  lost-racer-clean-exit, and deadlock-freedom. A regression artifact for future
  lifecycle changes.

### Security

- **Upgraded the `mcp` SDK dependency (previously transitive, now pinned
  directly as `mcp>=1.28.1,<2`)**, closing three HIGH advisories: WebSocket
  Host/Origin validation, HTTP session principal verification, and cross-client
  task access. The version is capped below 2.0 because that release removes the
  WebSocket server transport that luxd uses for the luxd-to-mcp-proxy leg.
- **Bumped the `Pillow` floor in the `[display]` extra from `>=11.0.0` to
  `>=12.3.0`** (`uv.lock` currently resolves to 12.3.0; the requirement stays
  a floor, not a pin), closing 13 Dependabot advisories — 10 HIGH
  and 3 medium. These cover heap out-of-bounds writes in `ImageCmsTransform`,
  `Image.paste`, and `RankFilter`; decompression-bomb bypasses in the BDF, PCF,
  FontFile, and GdImageFile font-loading paths; a PdfParser bomb DoS; a
  JPEG2000 scratch-buffer DoS; an mmap out-of-bounds read in the McIdas reader;
  a TGA RLE heap serialization flaw; WindowsViewer command injection; and an EPS
  infinite loop. 12.3.0 is the first release that patches every one.

## [0.19.1] - 2026-07-04

### Changed

- **Starlette upgraded to 1.x** — `luxd` now requires `starlette>=1.3.1,<2`
  (was `>=0.46.0`), a major-version upgrade. The hub's WebSocket/HTTP app and
  the MCP transport run on Starlette 1.x; the MCP stack (mcp/fastmcp) imposes
  no upper bound, so it resolves cleanly. Verified: 1347 tests pass and luxd
  serves the MCP round-trip on 127.0.0.1:8430 under 1.3.1. Fresh `lux install`
  now resolves the patched 1.x rather than 0.x.
- **rich upgraded 13 → 15** (`rich>=15,<16`) — lux has no direct rich usage
  (only via typer's CLI output); `make check` and the CLI verified on 15.0.0.
- **imgui-bundle upgraded 1.92.600 → 1.92.801** — the display renderer.
  Verified live: the display spawns and renders (OpenGL3, ~47 fps, zero
  errors). This build ships `imspinner` and `imgui_md`, so the two
  previously-skipped renderer import tests now run and pass (1347 → 1349).

### Fixed

- **Display windows no longer accumulate; `make restart` reaps reliably** — the
  display singleton guard now reads liveness from the Unix socket (a tri-state
  connect/handshake probe) instead of a PID file, and resolves the running
  display's owner via the OS peer credential (macOS `LOCAL_PEERPID` / Linux
  `SO_PEERCRED`) so it is reaped regardless of how it was started. A stale or
  missing PID file can no longer orphan a live display or spawn a duplicate
  window. Spawn, reap, and cleanup are serialized under a single per-socket
  lock, and `make restart` now ensures exactly one live display (and fails
  loudly if one cannot start, instead of silently backgrounding a dead process).
  (lux-w8t5)

### Security

- **Cleared 17 Dependabot advisories.** Required `starlette>=1.3.1` (5 alerts:
  SSRF/NTLM via UNC paths, form-limit bypass, arbitrary HTTP-method dispatch,
  path concatenation, Host-header poisoning) and bumped the vulnerable
  transitive deps `pyjwt`→2.13.0, `python-multipart`→0.0.32, `cryptography`→49,
  `pydantic-settings`→2.14.2, `idna`→3.18 (12 alerts). Real exposure was low —
  luxd is localhost-only with CSWSH — but the dependency tree is now clean.
- **Least-privilege CI permissions** — the `test`, `lint`, and `docs` workflows
  now declare `permissions: contents: read` instead of inheriting the broad
  default `GITHUB_TOKEN` (clears 3 code-scanning alerts).

## [0.19.0] - 2026-07-03

This release is mid-migration, not a finished state. The Hub/Display io-model
and the OO decomposition are both **in progress**: only Text, Checkbox, and
Dialog elements are on the new Element ABC path, and `display/server.py` and
`display/element_renderer.py` remain over the module-size target. Entries below
describe what shipped, framed as increments.

### Changed

- **BREAKING — `set_display_mode` and `display_mode` MCP tools now require a
  `repo` argument** (absolute path of the caller's project). Config is
  read/written at `<repo>/.punt-labs/lux.md`. Previously the path resolved
  against the server process's cwd, which under launchd (cwd `/`) wrote to a
  read-only `/.punt-labs` and raised `[Errno 30]`. Callers must now pass their
  workspace path explicitly. (lux-r929)
- **Internal decomposition (ongoing, not complete)** — the original
  `display.py` (4,208 lines) was split into `display/`, `scene/`, `tools/`, and
  `protocol/` packages; `protocol.py`, `messages.py`, and `elements.py` became
  sub-packages; `MessageRegistry` and `ElementCodec` registries replaced
  if/elif dispatch. `display/server.py` (~1,400 lines) and
  `display/element_renderer.py` (~1,100 lines) are still above the 300-line
  target — further extraction remains.
- **Protocol dataclasses are `frozen=True, slots=True`**; draw-command `*Cmd`
  classes renamed to nouns (they are records, not commands).
- **Architecture spec refreshed** — `docs/architecture/system.tex` brought
  current: 24 element kinds, 24 MCP tools, frame architecture, introspection
  protocol. README MCP tool table expanded from 11 to the full 24-tool surface;
  `display_mode` documented as read-only alongside `set_display_mode`.

### Added

- **Initial Hub/Display io-model architecture** — Element ABC with two-tier
  handler dispatch, `HubDisplay` authoritative state, and a Hub-scoped Agent
  Subscribe publish/subscribe channel separate from the UI observer mechanism.
  Text, Checkbox, and Dialog elements are migrated to the ABC; remaining element
  kinds still use the legacy path. (lux-wb55, and the PR 0–4 migration chain)
- **Interactive checkbox** — fires a `ValueChanged` event through remote
  dispatch, routing the interaction back to the owning Hub. New `ValueChanged`
  event type; `RemoteDispatchGroup` widened from `ButtonClicked` to any `Event`.
- **Dialog modal clicks** — dialog buttons dispatch through the D21
  `remote_dispatch` path to the Hub's authoritative copy.
- **Typed draw-command decoder** — removes silent `.get()` defaults from the
  draw-command wire path. (lux-4n1b)
- **Concept papers from PR #109** — self-extending display vision
  (`concept-self-extending-display.md`), extension architecture
  (`concept-extension-architecture.tex`), and Working Backwards PR/FAQ
  (`concept-prfaq.tex`). Concept-stage exploration, not versioned roadmap.
- **Sub-agent write permissions** — `.claude/settings.json` allows Edit/Write
  for `src/`, `tests/`, `docs/`, `tools/`, `.tmp/` so background sub-agents can
  modify code without interactive approval.

### Fixed

- **luxd reads no display config at startup** — removed the MCP session
  lifespan's display-config gate and its eager-connect retry machinery. Under
  launchd the daemon runs with cwd `/`, so the gate's no-argument
  `ConfigManager()` resolved to a nonexistent `/.punt-labs/lux.md`: the read
  never matched the caller's project and the eager connect never fired. The
  gate was also redundant — `set_display_mode(y)` eager-connects on explicit
  enable and every tool call connects lazily. This eliminates both the
  read-only `/.punt-labs` failure class and the silently-disabled eager
  connect; luxd now holds no display-config state.
- **D21 remote dispatch: grouped handler wrapping** — `RemoteDispatchGroup`
  replaces per-handler wrapping so one button click yields one
  `RemoteEventHandlerInvocation` instead of N. Hub replays the full handler
  chain once on its authoritative copy.
- **D21 remote dispatch: owner resolution** — `_hub_interaction_dispatch` now
  resolves the real element owner from `HubDisplay.owner_of()` instead of
  hardcoded `"display-fallback"` sentinel.
- **D21 remote dispatch: race condition guard** — `owner_of` call moved inside
  the existing try/except block so a concurrent `drop_connection` cannot crash
  the dispatch handler.
- **D21 remote dispatch: PY-TS-10 compliance** — replaced `getattr` duck-typing
  in `_logical_handler_count` and `_is_remote_dispatch_group` with `isinstance`
  checks against `RemoteDispatchGroup`.
- **Display-tier publish safety** — `RaisingPublishSink` replaces
  `NoOpAgentSideSink` on the Display so misrouted publishes fail loud instead
  of silently dropping.
- **Hub scene replacement** — `HubDisplay.replace_scene` consolidates the
  remove-old + install-new loop from `tools.py` into the domain layer where
  ownership, root observers, and child indexes are rebuilt through `apply()`.
- **Coherent log-level control** — `LUX_LOG_LEVEL` now configures both the
  luxd hub and the display process; an invalid value warns instead of silently
  falling back.
- **launchd-aware `make restart`** — restarts both luxd (via launchd) and the
  separate display process, so code changes are actually picked up.
- **Beads auto-render hook** — uses `bd ready`, surfaces `bd` failures instead
  of swallowing them, and applies a 60s timeout.
- **Display restart on upgrade** — `lux install`/upgrade restarts the display
  so it does not keep running stale code.

### Removed

- **Dock-hiding behavior on macOS (macOS only)** — removed the
  `NSApplicationActivationPolicyAccessory` call in
  `DisplayServer._on_post_init`. The `lux-display` process now appears as a
  normal Dock app per GLFW's default activation policy, restoring standard
  macOS app presence and making operational debugging easier. Pairs with the
  v0.7.0 "Dock hiding" Added entry. No effect on Linux.

## [0.18.0] - 2026-05-12

### Changed

- **Canonical file and class renames** — `server.py` → `tools.py`,
  `client.py` → `display_client.py`, `LuxClient` → `DisplayClient`.
  Aligns module names with the distributed architecture proposal where
  `tools.py` holds MCP tool definitions and `display_client.py` is the
  client library for connecting to `lux-display`. `LuxClient` is
  available as a backward-compatible alias.

### Added

- **`luxd` session hub daemon** — WebSocket server (Starlette + uvicorn) that
  multiplexes MCP sessions onto a single display connection. Phase 1 of the
  distributed architecture: `/mcp` endpoint for mcp-proxy, `/health` for
  monitoring, CSWSH protection, session tracking. Managed by launchd (macOS)
  or systemd (Linux) with `KeepAlive=true`.

- **Hub CLI commands** — `lux hub-install`, `lux hub-uninstall`,
  `lux ensure-hub` (with `--restart`), `lux hub-status`, `lux setup-proxy`.

- **Session multiplexing in MCP tools** — `_session_key` ContextVar for
  per-session state isolation. Per-session menu registration tracking with
  cleanup on WebSocket disconnect. `run_mcp_session()` entry point for hub.

- **mcp-proxy config management** — `remote.py` reads/writes
  `~/.punt-labs/mcp-proxy/lux.toml` with atomic writes and 0600 permissions.

- **Generic query infrastructure** — `QueryRequest`/`QueryResponse` protocol
  types with generic dispatcher in the display server. Adding a new
  introspection operation now requires only a handler function and an MCP
  tool — no protocol changes. Existing `inspect_scene`, `list_scenes`,
  `screenshot` registered as query handlers alongside their dedicated paths.

- **mcp-proxy plugin fallback** — `plugin.json` tries mcp-proxy → luxd when
  `lux.toml` is configured, falls back to direct `lux serve`. `install.sh`
  adds mcp-proxy install, luxd service registration, and proxy config steps.

- **`inspect_scene` MCP tool** — query the display server for a scene's element
  tree as JSON. Enables agent self-debugging: see exactly what elements are
  rendered for a given scene_id without human intervention. Inspired by
  Postern's dashboard introspection pattern.

## [0.17.1] - 2026-05-11

## [0.17.0] - 2026-05-11

### Added

- **`make install` target** — builds wheel and installs locally with `[display]`
  extras, preventing the silent loss of display dependencies that occurs when
  running `uv tool install` on a bare wheel without extras.

- **`show_table` `frame_id`/`frame_title` parameters** — convenience wrapper
  now forwards frame parameters to `show()`, enabling tab-isolated tables
  (e.g., per-project beads boards) without falling back to raw `show()` calls.

### Changed

- **Beads browser fetches live data from DoltDB** — `load_beads()` now calls
  `bd list --json` via subprocess instead of reading the stale `.beads/issues.jsonl`
  file. The `/lux:beads` skill uses the Bash tool with `bd list --json` instead
  of the Read tool with JSONL files.

### Removed

- **Clock and Calculator applets** — removed along with the `render_function`
  element kind and consent dialog. Code-on-demand was a proof of concept; the
  core product is ImGui via JSON, not agent-submitted Python.
- **`show_diagram` MCP tool** — removed the 450-line auto-layout engine. ImGui
  has no native diagram support; this fought the framework. The `draw` element
  remains for custom 2D rendering.
- **`consent.py` and AST safety scanner** — only used by `render_function`.

### Fixed

- **Applications menu appears at display startup** — Beads Browser is registered
  by the display server at init,
  not by the MCP client on first tool call. The menu is visible immediately.

- **`/lux:beads` skill frame isolation** — skill now passes `frame_id` and
  `frame_title` to `show_table` so the beads board renders in its own frame
  instead of replacing the main scene.

## [0.16.1] - 2026-04-09

## [0.16.0] - 2026-04-09

### Added

- **Programmer Calculator applet** — multi-base integer calculator with bit grid,
  bitwise operations (AND/OR/XOR/NOT/shift), and computation history. Available
  via Applications > Calculator.
- **Analog Clock applet** — smooth-sweeping analog clock face with hour, minute,
  and second hands rendered via ImGui draw list. Transparent, borderless floating
  window. Available via Applications > Clock.
- **Frame flags `no_title_bar`, `no_background`, `no_scrollbar`** — new ImGui
  window flags for `frame_flags` on `show()`. Enable borderless/transparent frames.
- **`TextElement.color` field** — hex color string (e.g. `"#FF3333"`) for text
  elements, applied across all text styles.
- **TreeElement `flat` flag** — `flat=True` renders tree nodes without child
  indentation. Branch nodes use `NoTreePushOnOpen` for arrow+label toggle,
  leaf children render as flush-left selectable items. Useful for inline
  disclosure patterns where hierarchical indentation wastes horizontal space.
- **`InputNumberElement`** — numeric input field with optional step buttons,
  min/max clamping, and integer mode. Wraps `imgui.input_int`/`input_float`.
- **`ModalElement`** — modal popup dialog that blocks background interaction.
  Container element with children; emits `"closed"` event on user dismissal.
- **`ButtonElement` arrow/small variants** — `arrow` field renders directional
  arrow buttons (left/right/up/down); `small` field renders compact buttons.
- **`ColorPickerElement` alpha/picker modes** — `alpha=True` enables RGBA
  editing via `ColorEdit4`; `picker=True` renders full color picker widget.
- **Beads board sortable columns** — table now includes `sortable` flag.
- **`make depot` target** — builds the wheel and copies it to the local depot
  (`../.depot`) for cross-project dev iteration. Sibling projects that list
  the depot in `uv.toml` pick up the local wheel instead of the stale PyPI
  version.

### Fixed

- **PostToolUse hook stdin on Linux** — `signal-beads.sh` used `< /dev/stdin`
  which fails on Linux where `/bin/sh` is dash. The redirect opens
  `/proc/self/fd/0` as a separate file descriptor, losing pipe data. Removed
  the explicit redirect; stdin inherits naturally per hook standards § 3.
- **Debug scene dump flushing** — `Dump Scene JSON` menu item used `print()`
  without `flush=True`. With stdout redirected to a file (via `ensure_display`
  Popen), full buffering prevented the dump from reaching disk until process
  exit. Added `flush=True`.
- **Orphan scenes on disconnect** — scenes from a disconnecting client now
  persist instead of being dismissed. If another client shares the frame,
  ownership transfers; otherwise scenes are marked as orphans and the frame
  stays open until the user closes it or a new client adopts it. Fixes
  fire-and-forget CLI usage (`lux show beads`) where the beads frame would
  flash and disappear.
- **Eager connect retry with backoff** — MCP server lifespan retries the
  initial display connection up to 3 times (2s, 5s, 10s) instead of giving
  up silently on the first failure.
- **Development Status classifier** — reverted to `3 - Alpha` in `pyproject.toml`
  to match the project's actual stage.
- **TextElement tooltip hover** — tooltips on unstyled text elements now use
  `selectable()` for reliable hover detection. Styled text (heading, caption, code)
  uses the standard generic tooltip handler.

### Security

- **`cryptography` → 46.0.6, `pygments` → 2.20.0** — CVE-2026-34073,
  CVE-2026-4539.
- **`fastmcp` → 3.2.0** — CVE-2026-32871, CVE-2026-27124.
- **`PyJWT` ≥ 2.12.0** — high-severity vulnerability where the library
  accepted unknown `crit` header extensions.

## [0.15.1] - 2026-03-16

### Changed

- **Shared frame ownership** — frames now accept scenes from multiple clients.
  `owner_fd` replaced with `owner_fds: set[int]`. When a client disconnects,
  only its scenes are removed from the frame; other clients' scenes persist.
  Frames close when no scenes remain, regardless of connected owners.

## [0.15.0] - 2026-03-15

### Added

- **Frame stack layout** — new `frame_layout="stack"` option for multi-scene
  frames. Scenes render as vertically stacked collapsing headers (all visible,
  individually collapsible) instead of the default tab bar. Set via
  `frame_layout` parameter on `show()` / MCP `show` tool.

### Fixed

- **Updates no longer steal window focus** — `UpdateMessage` previously called
  `_focus_owning_frame`, raising the target frame to the front on every patch.
  With multiple frames receiving concurrent updates, this caused z-order
  fighting. Only `show` (scene creation) now raises frames.

## [0.14.2] - 2026-03-14

### Fixed

- **Markdown font size matches ImGui default** — `MarkdownElement` body text
  was noticeably larger because imgui_md loads its own Roboto fonts at 16px
  while Lux uses system fonts. Set `regular_size=13.0` via
  `with_markdown_options` (not `with_markdown=True`, which triggers a
  static guard that silently drops custom options). See DES-026.
- **Markdown text wrapping** — long lines now wrap at the parent container
  boundary via `push_text_wrap_pos(0.0)` instead of overflowing to the
  window edge.

### Changed

- **Base font size** — primary font increased from 15px to 16px for better
  readability at default scale.

## [0.14.1] - 2026-03-14

### Fixed

- **Eager connect now auto-spawns display server** — the `is_display_running()`
  guard prevented the MCP server from starting the display on session start,
  defeating the purpose of eager connect. Removed the guard and moved
  `_get_client()` to a background thread via `asyncio.to_thread()` so
  auto-spawn doesn't block the async event loop.
- **Thread safety for `_get_client()`** — added `threading.RLock` to prevent
  race conditions between the lifespan thread and MCP tool threads that
  could create duplicate `LuxClient` instances with leaked sockets.
- **Eager connect error visibility** — failures now log at `warning` level
  instead of `debug`, so users who set `display=y` can see why the display
  didn't start. Separated config-read errors from connect errors with
  distinct log messages.

## [0.14.0] - 2026-03-14

### Added

- **`lux ping` CLI command** — round-trip ping to the display server with
  configurable timeout (default 2s). Exits 0 on pong, 1 on timeout or no
  server. Does not auto-spawn the display server.
- **Eager connect on display=y** — the MCP server connects to the display
  server and registers applications immediately on startup when display
  mode is enabled, and again when `display_mode` is set to `y`. No more
  waiting for the first tool call.

### Fixed

- **Dock bar pill clicks broken by dock space** — `dock_space_over_viewport`
  covers the entire viewport, making the `is_window_hovered(any_window)`
  guard always true and blocking all pill clicks. Replaced with explicit
  per-frame hover tracking so pills only reject clicks when a visible
  frame window overlaps the dock bar.

## [0.13.0] - 2026-03-13

### Added

- **Beads Browser application** — the Applications menu now shows "Beads
  Browser" instead of "Hello World". Clicking it opens the beads issue
  board in a frame, same as the `/lux:beads` skill. The hook-based
  auto-refresh after `bd` commands continues to work alongside the menu
  entry.

### Changed

- **Extractable beads module** — `load_beads` and `build_beads_payload`
  moved from `show.py` to `apps/beads.py`, a self-contained module with
  no Lux display internals. Designed for future extraction into the beads
  repo as an optional dependency.

### Removed

- **Hello World demo app** — replaced by the Beads Browser application.

## [0.12.0] - 2026-03-13

### Added

- **Paged group Prev/Next buttons** — paged groups now render built-in
  `<< Prev` and `Next >>` buttons flanking the combo, wired directly to
  widget_state with no round-trip required.
- **ImGui docking** — frames can be drag-merged into tabbed dock nodes
  via `dock_space_over_viewport` and `DockingEnable` config flag.

### Fixed

- **imgui_bundle 1.92.600 compatibility** — replaced removed
  `style.colors[col.value]` API with `style.color_(col)`, fixing a
  crash in dock bar rendering.
- **imgui_bundle 1.92.600 docking regression** — docking was silently
  disabled in the new version; now explicitly enabled via config flag
  and viewport dock space.
- **Dock bar pill clicks** — replaced unreliable `invisible_button`
  inside an unfocused overlay window with raw mouse hit-testing, fixing
  click-to-restore on minimized frame pills.
- **Collapse vs dock conflict** — collapse-to-minimize no longer fires
  during ImGui docking transitions (`is_window_docked` guard).

### Changed

- **imgui-bundle pinned** — locked to `==1.92.600` to prevent future
  API breakage.

## [0.11.0] - 2026-03-13

### Added

- **Push-based event handling** — `LuxClient` gains a background listener
  thread with callback registry for autonomous UI event dispatch.
  `on_event(element_id, action, callback)` registers handlers keyed by
  `(element_id, action)` tuples (following standard UI framework
  conventions). Fire-and-forget methods (`show_async`, `update_async`,
  `clear_async`) are safe to call from callbacks. The listener
  auto-restarts on reconnect when callbacks are registered. Existing
  pull-based `recv()` continues to work — unmatched events and acks
  route to their respective queues.
- **Frame minimize/restore** — the collapse triangle (▼) in frame title
  bars now minimizes to a bottom dock bar instead of collapsing in-place.
  Clickable pills in the dock bar restore frames, matching Pharo
  Smalltalk's taskbar pattern.
- **Dock bar** — a persistent bar at the bottom of the display shows all
  minimized frames as pills. Click to restore and focus. The bar only
  appears when frames are minimized.
- **Expand All / Collapse All** — Windows menu shows "Expand All" when
  frames are minimized and "Collapse All" when visible, for bulk
  minimize/restore.
- **Detached World menu** — World menu is now a floating panel triggered
  by clicking the background, matching Pharo Smalltalk's World menu
  pattern. Mirrors the full menu bar (Lux, Debug, Windows, Help) plus
  agent-registered items. Appears at click coordinates, supports
  pin/unpin, and auto-closes on item click when unpinned.
- **Debug menu** — new menu with "Dump Scene JSON" for inspecting
  current display state (frames, scenes, clients).
- **Help menu** — displays current Lux version.
- **Paged group layout** — `GroupElement` gains `layout="paged"` with
  `pages` and `page_source` fields. A combo's selected index controls
  which page of children is visible, all client-side with no MCP
  round-trips.
- **Windows menu: Collapse All, Expand All, Fit All** — Collapse
  minimizes all frames to dock, Expand restores them, Fit All tiles
  frames in a non-overlapping grid layout. Items are grayed out when
  not applicable.

### Changed

- **Menu bar reorganization** — menu bar is now Lux | Applications | Debug |
  Windows | Help. Theme, Always on Top, Borderless, and Opacity moved under
  Lux > Settings. Opacity changed from slider to preset submenu
  (25%, 50%, 75%, 100%). "Window" renamed to "Windows".

### Fixed

- **Markdown initialization** — use `addons.with_markdown=True` instead
  of manual `initialize_markdown()` to prevent "Markdown was not
  initialized" warning spam.

## [0.10.0] - 2026-03-12

### Added

- **Frame auto-focus** — frames automatically focus (brought to front)
  when they receive a scene update. Minimized frames are restored.
- **Table `row_select` event** — clicking a table row emits a
  `row_select` InteractionMessage with row index and data, routable
  through `recv()`. Rows are selectable when `copy_id` flag is set,
  even without a detail panel.
- **`frame_size` and `frame_flags` on `show()`** — frames accept an
  initial size hint `[width, height]` and ImGui window flags
  (`no_resize`, `no_collapse`, `auto_resize`). Size applies on first
  use only; users can still resize afterwards unless `no_resize` is set.
- **Lightweight install** — heavy display deps (imgui-bundle, numpy,
  Pillow, PyOpenGL) moved to `[display]` extra. `pip install punt-lux`
  now pulls only lightweight deps (~2 MB); consumers that only need
  `LuxClient` no longer pay for the 66 MB display stack. End users
  install with `pip install 'punt-lux[display]'`.

### Changed

- **Public API** — `CodeExecutor` and `RenderContext` removed from
  `punt_lux` top-level exports. These are display-internal and remain
  importable from `punt_lux.runtime` directly.
- **Beads sort order** — in-progress issues float to the top of the
  beads board regardless of priority.
- **SessionStart hook** — made async; display mode discovery deferred
  to first MCP tool call.

### Fixed

- **Stale beads board on empty results** — when all issues are closed
  or no active issues exist, the beads frame now shows "No active
  issues." instead of leaving stale data from the previous refresh.

## [0.9.0] - 2026-03-11

### Added

- **ConnectMessage client identity** — clients identify themselves by name
  during handshake. Protocol validates non-empty names. Display server
  tracks client names for menu namespacing and logging.
- **Frames with orphan model** — scenes can target named frames (ImGui
  child windows). Frames persist after their owner disconnects and can be
  adopted by new clients sending to the same `frame_id`. Per-project beads
  boards each get their own frame (`beads-lux`, `beads-vox`, etc.).
- **World menu with per-client namespaces** — hierarchical menu replaces
  the flat Tools menu. Each connected client gets its own submenu
  (named from ConnectMessage). Menu items are sorted alphabetically
  within each client submenu. Environment items (Minimize All, Close All)
  appear below client submenus.
- **RegisterMenuMessage protocol type** — MCP servers can register menu
  items via the `register_menu` wire message. Items are per-client,
  merged alphabetically, and auto-cleaned on disconnect. Item ID
  uniqueness is enforced across clients.
- **Routed menu event delivery** — World menu item clicks are sent only to
  the owning client, not broadcast. Non-menu and environment events
  continue to broadcast.
- **`register_tool` MCP tool** — register a menu item in the World menu.
  Clicks are routed only to the registering server via `recv()`. Items
  auto-replay on reconnect.
- **`LuxClient.register_menu_item()`** — client library method for World
  menu registration. Accumulates items and replays on reconnect.

### Changed

- **Per-project beads frames** — each project's beads board opens in its
  own frame (`Beads: lux`, `Beads: vox`, etc.) so multiple projects
  can coexist without overwriting each other.
- **Window size** — default window increased from 800x600 to 1200x800.
  Frames fill 75% of the content region on first use.
- **PostToolUse beads hook** — fires on any `bd` subcommand, not just
  mutations. `bd ready`, `bd list`, `bd show`, etc. now refresh the board.
- **Resizable table columns** — beads board tables now have `resizable`
  flag enabled; users can drag column borders to resize.

### Fixed

- **Narrow table columns collapsing** — short-content columns like "P"
  (priority) collapsed to near-zero width when stretched beside long
  columns. Column weight floor raised from 1.0 to 4.0.

## [0.8.0] - 2026-03-10

### Added

- **SMP font coverage** — merge STIX Two Math (macOS) and Noto Sans Math
  (Linux) for Mathematical Alphanumeric Symbols block (U+1D400–1D7FF).
  Fixes diamond replacement glyphs for Z notation double-struck letters
  like 𝔽 (U+1D53D). See DES-020.
- **`make font-test`** — visual font coverage test that starts a dev display
  server for manual verification of SMP/BMP double-struck characters.
- **`lux show beads`** — CLI command that displays the beads issue board in
  the Lux window without requiring an LLM to generate the table mapping.
  Reads `.beads/issues.jsonl`, filters to active issues, and sends directly
  to the display server. Supports `--all` to include closed issues.
- **`copy_id` table flag** — when set, selecting a table row copies the first
  column value to the system clipboard. Enabled by default in `lux show beads`.
- **PostToolUse beads hook** — automatically refreshes the Lux beads board
  after `bd create`, `close`, `update`, `dep`, or `sync` commands.

## [0.7.2] - 2026-03-10

### Fixed

- **Draw element crash on RGBA list colors** — `_parse_hex_color` called
  `.lstrip()` on list inputs, raising `AttributeError` which escaped the
  draw command exception handler and killed the display server. Now accepts
  both hex strings and RGBA lists/tuples as documented in the MCP tool schema.

## [0.7.1] - 2026-03-10

### Fixed

- **Session start hook hang** — removed unnecessary stdin parsing from
  `cc_session_start`. The handler never used the data, so all 17 lines
  of non-blocking stdin reading were wasted work. See DES-027.

## [0.7.0] - 2026-03-09

### Added

- **Persistent dismissable tabs** — each `show()` call opens a new tab; multiple scenes coexist and users can dismiss them individually via close button. Same `scene_id` replaces content in-place (no new tab). Single-scene usage renders without tab bar chrome.
- **Flame idle screen** — animated candle flame with radial light rays replaces "waiting for scene..." text; theme-aware (adapts to light and dark backgrounds)
- **Clear All** menu item under Window — clears all tabs and resets to idle screen
- **Dock hiding** (macOS) — display server hides from Dock via `NSApplicationActivationPolicyAccessory`; process name shows as "Lux" in `ps` via `setproctitle`
- Optional `display` extras: `setproctitle`, `pyobjc-framework-Cocoa` (macOS only)

### Changed

- Default font scale increased from 1.0× to 1.1×
- Window title simplified from "Lux Display" to "Lux"

### Fixed

- **`/lux:beads` skill** — use `show_table` MCP tool instead of bypassing protocol with raw Python script via Bash

## [0.6.0] - 2026-03-09

### Added

- **`/lux y` and `/lux n` display mode toggle** — advisory L3 state signal for consumer plugins; persists to `.lux/config.md`
- **`display_mode` MCP tool** — get or set display mode (`y`/`n`) for LLM callers
- **`lux enable` / `lux disable` CLI commands** — terminal-facing display mode toggle
- **`lux hook session-start` CLI dispatcher** — SessionStart hook delegates to Python handler
- **`show_diagram()` MCP tool** — auto-laid-out architecture diagrams with layers, nodes, edges, and color-coded boxes via draw canvas
- **`/lux:diagram` skill** — guides agents through building layered box-and-arrow diagrams
- **Font size controls** — Increase Font / Decrease Font in Lux menu (0.5×–3.0× range)

### Changed

- Diagram layout: wider spacing, centred rows, edge port spreading, horizontal same-layer routing, angle-aligned arrowheads, edge label backgrounds

### Fixed

- Validate unique node IDs in diagram layout (raise `ValueError` on duplicates)
- Dynamic layer label column width based on longest label text
- Flip arrowhead direction for upward edges in diagrams
- Safe minimum canvas dimensions when all diagram layers are empty
- Skip empty-layer labels when computing label column width

## [0.5.2] - 2026-03-08

### Added

- **`show_table()` MCP tool** — filterable data tables with search, combo filters, and detail panel
- **`show_dashboard()` MCP tool** — metric cards, charts, and status tables in a single call
- **`set_theme()` MCP tool** — switch display theme (dark, light, classic, cherry)
- **`/lux:beads` skill** — rewritten as single-command recipe for beads issue board
- **`/lux:data-explorer` skill** — interactive filterable table with detail panel
- **`/lux:dashboard` skill** — metrics, charts, and status overview
- README screenshots: beads board, data explorer, dashboard

### Fixed

- Beads skill sort order: two-pass stable sort (updated_at desc, then priority asc)
- PyPI classifiers: added Python 3.14, fixed development status

## [0.5.1] - 2026-03-08

### Added

- **`install.sh`** — curl | sh installation script
- **`lux doctor`** — check for Unicode and symbol fonts
- **`lux install` / `lux uninstall`** — CLI commands per standard

### Changed

- Added acknowledgements for Dear ImGui, imgui-bundle, and FastMCP to README

## [0.5.0] - 2026-03-08

### Added

- **Display server** — ImGui-based visual output surface with non-blocking socket IPC
- **MCP server** — FastMCP tools (`show`, `update`, `clear`, `ping`, `recv`, `set_menu`)
  for AI agents to display text, tables, images, buttons, and interactive controls
- **Protocol** — framed JSON message protocol with element types: text, separator, image,
  button, table, markdown, group, collapsing_header, tab_bar, render_function
- **Interactive controls** — slider, checkbox, combo, input_text, radio, color_picker
  with event routing back to agents via `recv()`
- **Render functions** — `render_function` element kind for agent-submitted Python code
  with AST safety scanning, consent dialog, and sandboxed execution
- **Window chrome** — Always on Top, Borderless toggle, Opacity slider via Window menu
- **Auto-reconnect** — MCP tools automatically reconnect on broken pipe when display
  server restarts
- **Client library** — `LuxClient` context manager for Python callers
- **CLI** — `lux display` to launch the display server, `lux serve` for MCP server

### Fixed

- Table columns use `WidthStretch` with `text_wrapped` for proper text wrapping
- Default status bar (Enable idling / FPS counter) hidden
- Reset Size menu item uses `change_window_size()` for runtime resize
- Markdown initialization warnings resolved by calling `initialize_markdown()` in post-init
- `ClearMessage` properly clears render function state
