# Client Surface Parity — One Engine, Four Doors, One Vocabulary

- **Status:** draft for DES-087. Bead `lux-0shg.1`, epic `lux-0shg`.
  The seven positions the epic body ratifies (bead
  `bd show lux-0shg`) are carried here verbatim; this design mission
  turns them into a vocabulary and a DRY pattern the implementation
  missions (`.2` through `.7`) can execute against.
- **Proposed ADR number:** DES-087 (next after DES-086, connection-scoped
  store keys, in-flight but not yet pasted into `DESIGN.md`; DES-068
  through DES-085 are shipped but likewise absent from the numbered
  headings — closing that gap is not this design's to do).
- **Author:** gvr, design mission `m-2026-08-18-002`.
- **Evaluator:** mdm (CLI lens — the CLI is the least-covered surface
  today and the one this vocabulary most reshapes).
- **Companion PR:** `punt-labs/punt-kit` — the standards ratifying this
  design at the org level. Both PRs merge before `lux-0shg.2` opens.

## Abstract

Lux has four client surfaces of one engine (`architecture.md`, the
projection model): a Python library, a Typer CLI, a FastMCP server, and
a FastAPI REST app. Today each surface exposes a different subset of the
engine's operations, under different names, with different conventions.
The CLI has admin verbs only. The MCP surface has 23 tools with a
verb-first, single-word shape (`show`, `identify`, `list_clients`) that
was fine when it was three tools and is a naming schism now that it is
23. The REST surface has grown by ad-hoc addition. The library surface
is two transport-flavoured objects (`LuxRestClient`, `LuxHubClient`)
that expose HTTP mechanics rather than engine nouns.

The proposal is one vocabulary, applied everywhere:

1. **Nouns first.** Every operation is `noun verb` (`scene show`,
   `session ls`, `topic publish`) on every surface. Single-verb only for
   the top-level singletons (`enable`, `disable`, `doctor`, `version`).
2. **One code path.** The `Operations` facade becomes internal; a new
   `src/punt_lux/commands/` package holds one `@final` callable class
   per operation (vox's shape, `../vox/src/punt_vox/commands/voice.py`
   is the reference), returning `CommandResult`. CLI, MCP, REST, and
   library each adapt to the same instance.
3. **Equivalence is the default.** Every engine operation appears on
   every client surface with the same name. An omission is a
   *considered exception* with a stated reason, not the default;
   assessment reads omissions, never inclusions
   (`memory:feedback_assess_omissions_not_argue_inclusions`).
4. **No superuser surface.** Every write scopes to the caller's
   `ConnectionId` (DES-086 Decision 5). Every content read scopes the
   same way. The CLI carries `--as/--kind/--name/--repo/--agent` as
   per-invocation identity, not privilege elevation.

The wire protocols do not change. The DES-086 identity model does not
change. What changes is the shape of the client surfaces above them:
one vocabulary, one command class per operation, four thin adapters.

## Motivation

Three problems compound.

**Naming schism.** The MCP surface began with three tools and grew to
23 without ever adopting a grouping convention. Its `show` names
`scene_show` in every real invocation the operator has ever written
down (`show a scene`, `show the table`, `show the dashboard`);
`identify` names `session_identify`; `list_clients` inverts noun and
verb the way no other tool does. The CLI surface has the opposite
problem: an admin sub-surface with `hub-install`, `hub-status`, etc.,
and no client sub-surface at all. The library surface hands consumers
`LuxHubClient` (a websocket) and `LuxRestClient` (an HTTP session), not
`scene.show` and `topic.publish`.

**Four copies of every operation.** Today an operation is a shape in
`Operations`, plus a REST handler, plus an MCP tool, plus (if it has
one) a CLI command, each with its own request-parsing, its own
error-envelope, and its own JSON-vs-text branching. Vox has already
shown, in `../vox/src/punt_vox/commands/voice.py`, that one `@final`
callable class returning `CommandResult` erases three of those copies:
the CLI wrapper interprets `text` and `exit_code`, the MCP tool wraps
`json_data`, the library caller inspects fields directly. Lux has
signed up for the same discipline in `python.md` §Rule 5 but has not
followed it.

**Missing pre-conditions for adjacent work.** The menubar epic
`lux-mxvy` R4 shells out to `lux hub-*` for luxd process control;
today's CLI has the admin commands, but the operator has ruled that a
menubar app talking `launchctl`/`systemd` directly duplicates the
engine authority (rejected). R4 depends on the CLI's `hub` group
existing under this epic's noun convention. Slippage on this epic
slips R4 onto its rejected alternative.

## The seven ratified positions

Restated from the epic body (`bd show lux-0shg`) so the design cycle
does not re-litigate them. Each is a *ratified* input to this design
mission, not an open question.

1. **Standard is equivalence.** Every engine operation exists on every
   surface with the same name. Every omission is a considered exception
   with a stated reason.

2. **DRY via Humble Object commands.** New `src/punt_lux/commands/`
   package. `@final` callable classes returning `CommandResult`. Vox
   `commands/voice.py` is the reference shape.

3. **No superuser surface.** DES-086 identity scoping is load-bearing:
   every write composes on caller's `ConnectionId`, every content read
   composes on caller's `ConnectionId` (Decision 5 narrowing, no
   `owner=` override). Preserved unchanged.

4. **Per-invocation identity, not privilege.** The CLI's
   `--as/--kind/--name/--repo/--agent` flags let one CLI invocation be
   a different client for that call. It is BEING that client for the
   invocation; it is not becoming an admin. The DES-086 live demo
   needed multi-client scenarios and had to bypass the CLI via raw
   REST because these flags did not exist. Under this epic they do.

5. **Noun-first grouping.** Every operation is `noun verb`. The nouns
   are: `scene`, `frame`, `menu`, `session`, `topic`, `callback`,
   `display`, `event`, `error`, `hub`, plus top-level singletons
   (`enable`, `disable`, `install`, `uninstall`, `mcp`, `doctor`,
   `version`). Renames are a rename train — no shim, no alias, no
   deprecation window; the ecosystem updates in one release.

6. **Rename train, no shims.** The MCP rename set (26 renames + 3
   fuse-renames + 2 net-new tools, enumerated in §The MCP rename
   train) lands atomically. Agent prompts in
   `.punt-labs/ethos/agents/*.md`, slash-command definitions, and
   cross-repo consumers (vox's applet, z-spec's lux renderer) update
   in lockstep with the merge.

7. **Grey-area rulings.** Three cases that could be read admin-wide or
   caller-scoped are ratified here as caller-scoped by default:
   `event ls`, `error ls`, and `display screenshot` (per-frame with
   `--frame`); `session ls` stays visible to all as peer-discovery
   metadata. Details in §Grey-area rulings below.

## Vocabulary

The full noun/verb mapping. One row per engine operation; four columns
for the four client surfaces plus the slash-command form. This is what
`.4` (CLI), `.5` (MCP rename train), `.6` (slash coverage), and `.7`
(library reorg) implement against.

### Scene

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Install / replace a scene | `lux scene show <spec>` | `scene_show` (was `show`) | `PUT /scenes/{id}` | `client.scene.show(spec)` | `/lux:scene.show` |
| Patch elements in place | `lux scene update <id> <patches>` | `scene_update` (was `update`) | `PATCH /scenes/{id}` | `client.scene.update(id, patches)` | `/lux:scene.update` |
| Remove a scene | `lux scene clear <id>` | `scene_clear` (was `clear_scene`) | `DELETE /scenes/{id}` | `client.scene.clear(id)` | `/lux:scene.clear` |
| Remove all caller's scenes | `lux scene clear-all` | `scene_clear_all` (was `clear`) | `DELETE /scenes` | `client.scene.clear_all()` | `/lux:scene.clear-all` |
| Inspect a scene (introspection) | `lux scene inspect <id>` | `scene_inspect` (was `inspect_scene`) | `GET /scenes/{id}` | `client.scene.inspect(id)` | `/lux:scene.inspect` |
| List scenes (caller-scoped) | `lux scene ls` | `scene_ls` (was `list_scenes`) | `GET /scenes` | `client.scene.ls()` | `/lux:scene.ls` |
| Render a table (composite convenience) | `lux scene table <spec>` | `scene_table` (was `show_table`) | `PUT /scenes/{id}/table` | `client.scene.table(spec)` | `/lux:scene.table` |
| Render a dashboard (composite) | `lux scene dashboard <spec>` | `scene_dashboard` (was `show_dashboard`) | `PUT /scenes/{id}/dashboard` | `client.scene.dashboard(spec)` | `/lux:scene.dashboard` |

### Frame

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Raise a frame to the top | `lux frame raise <id>` | `frame_raise` (was `set_frame_state` w/ `state=raised`) | `POST /frames/{id}/raise` | `client.frame.raise_(id)` | `/lux:frame.raise` |
| Lower a frame below its peers | `lux frame lower <id>` | `frame_lower` (was `set_frame_state` w/ `state=lowered`) | `POST /frames/{id}/lower` | `client.frame.lower(id)` | `/lux:frame.lower` |
| Close a frame | `lux frame close <id>` | `frame_close` (was `set_frame_state` w/ `state=closed`) | `POST /frames/{id}/close` | `client.frame.close(id)` | `/lux:frame.close` |
| Expire a frame (schedule TTL) | `lux frame expire <id> [--in S]` | `frame_expire` (was `set_frame_state` w/ `state=expired`) | `POST /frames/{id}/expire` | `client.frame.expire(id, in_=None)` | `/lux:frame.expire` |

The `set-state` discriminator setter — `frame_set_state(id, state)`
where `state` is one of four literals — collapses four verbs into one
tool with a `Literal[...]` parameter. Four explicit verbs read
cleaner on every surface: an agent raises a frame the same way a user
raises a window; the CLI reads `lux frame raise <id>` rather than the
Java-style `lux frame set-state <id> raised`. This is also the shape
that plays best with the DES-058/DES-067 handler dispatch — one
callable per verb, no `if state == ...` ladder inside the tool. See
§Rationale below for the alternative rejected.

### Menu

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| List menu entries | `lux menu ls` | `menu_ls` (was `list_menus`) | `GET /menus` | `client.menu.ls()` | `/lux:menu.ls` |
| Set the caller's menu entries | `lux menu set <entries>` | `menu_set` (was `set_menu`) | `PUT /menus` | `client.menu.set(entries)` | `/lux:menu.set` |
| Read one menu entry | `lux menu get <label>` | `menu_get` (new) | `GET /menus/{label}` | `client.menu.get(label)` | `/lux:menu.get` |

### Session

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| List active sessions (metadata) | `lux session ls` | `session_ls` (was `list_clients`) | `GET /sessions` | `client.session.ls()` | `/lux:session.ls` |
| Inspect one session's metadata | `lux session inspect <id>` | `session_inspect` (new; extraction of one row from `list_clients`) | `GET /sessions/{id}` | `client.session.inspect(id)` | `/lux:session.inspect` |
| Declare caller identity | `lux session identify --kind K --name N ...` | `session_identify` (was `identify`) | `POST /sessions/identify` | `client.session.identify(...)` | *(exception — see below)* |

### Topic (Hub-managed pub-sub — application-event channel)

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Publish an app event | `lux topic publish <topic> [payload]` | `topic_publish` (was `publish`) | `POST /topics/{topic}` | `client.topic.publish(topic, payload)` | `/lux:topic.publish` |
| Subscribe to a topic | `lux topic subscribe <topic>` | `topic_subscribe` (was `subscribe`) | `PUT /subscriptions/{topic}` | `client.topic.subscribe(topic)` | `/lux:topic.subscribe` |
| Unsubscribe | `lux topic unsubscribe <topic>` | `topic_unsubscribe` (was `unsubscribe`) | `DELETE /subscriptions/{topic}` | `client.topic.unsubscribe(topic)` | `/lux:topic.unsubscribe` |
| Non-blocking receive | `lux topic recv` | `topic_recv` (was `recv`) | `GET /messages` | `client.topic.recv()` | *(exception — see below)* |

### Callback (menu-callback registration)

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Register a callback id | `lux callback register <id> <label>` | `callback_register` (was `register_callback`) | `POST /callbacks` | `client.callback.register(id, label)` | *(exception — see below)* |
| Pending invocations for caller | `lux callback pending` | `callback_pending` (was `pending_callbacks`) | `GET /callbacks/pending` | `client.callback.pending()` | `/lux:callback.pending` |

### Display

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Read display info (size, theme, mode) | `lux display info` | `display_info` (was `get_display_info`) | `GET /display` | `client.display.info()` | `/lux:display.info` |
| Set/get theme | `lux display theme [<name>]` | `display_theme` (was `get_theme` / `set_theme` — fused) | `GET/PUT /display/theme` | `client.display.theme(name=None)` | `/lux:display.theme` |
| Set/get display mode | `lux display mode [<mode>] [--repo R]` | `display_mode` (was `display_mode` / `set_display_mode` — fused) | `GET/PUT /display/mode` | `client.display.mode(mode=None, repo=None)` | `/lux:display.mode` |
| Set/get window settings | `lux display window [<opts>]` | `display_window` (was `get_window_settings` / `set_window_settings` — fused) | `GET/PUT /display/window` | `client.display.window(opts=None)` | `/lux:display.window` |
| Capture a per-frame screenshot | `lux display screenshot --frame <id>` | `display_screenshot` (was `screenshot`) | `GET /frames/{id}/screenshot` | `client.display.screenshot(frame)` | `/lux:display.screenshot` |

### Event / Error (caller-scoped only)

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Recent events emitted by/for caller | `lux event ls [--count N]` | `event_ls` (was `list_recent_events`) | `GET /events` | `client.event.ls(count=50)` | `/lux:event.ls` |
| Recent errors for caller | `lux error ls [--count N]` | `error_ls` (was `list_errors`) | `GET /errors` | `client.error.ls(count=20)` | `/lux:error.ls` |

### Hub (admin — CLI-only, absent from MCP/REST/library)

| Op | CLI | MCP tool | REST | Library | Slash |
|---|---|---|---|---|---|
| Install luxd (LaunchAgent / systemd unit) | `lux hub install` | — | — | — | — |
| Uninstall luxd | `lux hub uninstall` | — | — | — | — |
| Start luxd | `lux hub start` | — | — | — | — |
| Stop luxd | `lux hub stop` | — | — | — | — |
| Restart (rebuild + kick) | `lux hub restart` | — | — | — | — |
| Status of the luxd process | `lux hub status` | — | — | — | — |

The `hub *` group is purely admin: every verb in it runs the process
supervisor and never leaves the CLI. `ping` — a client-legitimate
liveness probe every agent uses — is not in the `hub` group; it is a
top-level diagnostics verb alongside `doctor` and `version` (see
below).

### Top-level singletons (no noun grouping)

| Op | CLI | MCP | REST | Library | Slash |
|---|---|---|---|---|---|
| Ping the running luxd (diagnostics) | `lux ping [--wait S]` | `ping` (unchanged) | `GET /ping` | `client.ping(wait=None)` | `/lux:ping` |
| Health checks (diagnostics) | `lux doctor` | — | — | — | — |
| Print version (diagnostics) | `lux version` / `--version` | — | — | — | — |
| Enable lux in the current repo (admin) | `lux enable` | — | — | — | — |
| Disable (admin) | `lux disable` | — | — | — | — |
| Install machine-scoped (MCP registration) (admin) | `lux install` | — | — | — | — |
| Uninstall machine-scoped (admin) | `lux uninstall` | — | — | — | — |
| Start the MCP server (stdio) (admin) | `lux mcp` | — | — | — | — |

The top-level singletons split into two tiers. **Diagnostics**
(`ping`, `doctor`, `version`) are legitimate operations for any
caller; `ping` in particular is a health check every agent runs and
lives on every client surface accordingly. **Admin** (`enable`,
`disable`, `install`, `uninstall`, `mcp`) are CLI-only per
`punt-kit/standards/tool-enable-disable.md` and the admin/client
split below. `doctor` and `version` are CLI-only for a different
reason — they are operator-facing summaries whose output shape is
not useful to a programmatic caller — but the invariant is the
same: no agent-turn is a legitimate caller of an operator-facing
verb.

## The MCP rename train

Extracted from the tables above into one place so any deviation from
the prior-conversation agreement is leader-visible. Every rename is
old-name → new-name with no alias, per position 6.

The epic body named 23 renames from the prior conversation. Round-2
of this design mission added three (F3 split `set_frame_state` into
four renames; F2 moved `ping` out of the rename set since the tool
name is unchanged; F4 renamed a *new* tool that never existed on the
old surface). The atomic set the `.5` rename train lands is now:
**26 renames** in the numbered table below, **3 fuse-renames** for
the get/set display pairs (§Display, noted after the table), and
**2 net-new tools** (`menu_get`, `session_inspect`) that are
additions rather than renames.

| # | Old MCP tool | New MCP tool |
|---:|---|---|
| 1 | `show` | `scene_show` |
| 2 | `update` | `scene_update` |
| 3 | `clear_scene` | `scene_clear` |
| 4 | `clear` | `scene_clear_all` |
| 5 | `inspect_scene` | `scene_inspect` |
| 6 | `list_scenes` | `scene_ls` |
| 7 | `show_table` | `scene_table` |
| 8 | `show_dashboard` | `scene_dashboard` |
| 9a | `set_frame_state` (state=`raised`) | `frame_raise` |
| 9b | `set_frame_state` (state=`lowered`) | `frame_lower` |
| 9c | `set_frame_state` (state=`closed`) | `frame_close` |
| 9d | `set_frame_state` (state=`expired`) | `frame_expire` |
| 10 | `list_menus` | `menu_ls` |
| 11 | `set_menu` | `menu_set` |
| 12 | `list_clients` | `session_ls` |
| 13 | `identify` | `session_identify` |
| 14 | `publish` | `topic_publish` |
| 15 | `subscribe` | `topic_subscribe` |
| 16 | `unsubscribe` | `topic_unsubscribe` |
| 17 | `recv` | `topic_recv` |
| 18 | `register_callback` | `callback_register` |
| 19 | `pending_callbacks` | `callback_pending` |
| 20 | `get_display_info` | `display_info` |
| 21 | `screenshot` | `display_screenshot` |
| 22 | `list_recent_events` | `event_ls` |
| 23 | `list_errors` | `error_ls` |

`get_theme`/`set_theme`, `get_window_settings`/`set_window_settings`,
and `display_mode`/`set_display_mode` are noted separately: the pair
fuses into one `display_theme` / `display_window` / `display_mode`
tool per §Vocabulary (Display). These are three fuse-renames the
`.5` rename train also lands atomically alongside the 26 numbered
renames above.

## Admin / client split

Which surface an operation appears on is a function of who can
legitimately call it. Two tiers.

**Client tier** — the vocabulary tables above minus the `hub *`
admin rows and minus the top-level singletons. Every operation on
this tier appears on all four client surfaces (CLI, MCP, REST,
library) under the same name. This is the surface an *agent* uses; an
agent is a client of the engine like any other. The client tier is
also where DES-086 identity scoping applies — every write and every
content read is caller-scoped.

**Admin tier** — the `hub install|uninstall|start|stop|restart|status`
group and the top-level singletons `enable`, `disable`, `install`,
`uninstall`, `mcp`, `doctor`, `version`. These run process
supervision, install/uninstall machine-scoped registrations, and
manage per-repo enablement. The CLI is their *sole* client surface.
They are absent from MCP by construction: `python.md` and
`tool-enable-disable.md` both say `install`/`enable`/`doctor` are
admin verbs run by an operator or a hook, not by an agent-turn.
Exposing them on MCP would recreate the "superuser MCP surface"
DES-086 Decision 5 forbids.

The `hub *` group is purely admin. `ping` — the one liveness probe
every agent legitimately uses — is a top-level diagnostics verb, not
a `hub` verb; grouping it under `hub` would put a client-legitimate
operation inside an admin group and confuse the mental model. It
appears on every client surface as `lux ping` / `ping` /
`GET /ping` / `client.ping(...)` / `/lux:ping` per §Top-level
singletons.

## Grey-area rulings

Three cases could plausibly be read admin-wide or caller-scoped. The
ratified rulings, with reasoning:

**`event ls` / `error ls` — caller-scoped.** An events log visible to
all clients would let one client observe another client's activity —
exactly the read model DES-086 Decision 5 rejected for scene content.
The operator ruled the same rule extends to derived observations
about scene activity: a caller can list its own events and errors,
never another's. If an admin-tier "all events" view is needed later
for luxd operator debugging, it goes through the luxd logs, not
through a client surface.

**`display screenshot` — per-frame with `--frame`.** A whole-display
screenshot exposes every session's rendered pixels to one caller,
which is the DES-086 read invariant violated at the pixel layer. The
operation instead takes a `--frame <id>` and captures only that
frame's rectangle; the caller can screenshot any frame it owns, and
frame ownership is composed on `ConnectionId` per DES-086. This
narrows the operation without removing it.

**`session ls` — visible to all as peer-discovery metadata.** Sessions
already advertise themselves to the display's Clients menu (DES-064,
DES-067) — the identity and connect-time metadata is not
confidential. Content stays scoped; metadata does not. `session ls`
returns identity + connect time + subscription count only; it never
returns another session's scenes, menus, or events.

## Library API shape

The library becomes a noun-grouped facade over the underlying
transport clients.

```python
# lux/__init__.py (public API)
from punt_lux import LuxClient

client = LuxClient.for_identity(kind="tool", name="my-tool")
client.scene.show(spec)
client.scene.ls()
client.session.identify(kind="app", name="beads-browser")
client.topic.publish("openTicket", {"id": 42})
result = client.topic.recv()
```

`LuxRestClient` and `LuxHubClient` do not disappear; they become the
transport adapters `LuxClient` composes. A power user reaching under
the facade can still hold them directly, but the surface every
consumer sees is the noun-grouped facade. This is the shape vox
already presents (`../vox/src/punt_vox/commands/__init__.py`
re-exports `voice`, `model`, `provider` as callable instances a
library caller awaits directly).

The `for_identity` classmethod is the one place identity is declared;
the composed clients inherit it. Anonymous library use is rejected
the same way DES-086 rejected anonymous REST — the identity is not
optional.

## Commands layer architecture

The DRY pivot the epic executes on. Vox's `commands/` is the load-
bearing reference; the shape is not lux's invention and is not open
for redesign in this mission.

**Package layout** — `src/punt_lux/commands/`, one module per
operation, one `@final` callable class per module, exported as a
module-level singleton the four adapters share.

```python
# src/punt_lux/commands/scene_show.py
from __future__ import annotations

from typing import Self, final

from punt_lux.commands._result import CommandResult, Ctx


@final
class SceneShowCommand:
    """Install or replace a scene owned by the caller."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def __call__(
        self, ctx: Ctx, scene_id: str, tree: dict[str, object]
    ) -> CommandResult:
        result = ctx.ops.scenes.install(
            connection_id=ctx.identity.connection_id,
            scene_id=scene_id,
            tree=tree,
        )
        if isinstance(result, OpError):
            return CommandResult(
                text=f"Error: {result.message}",
                json_data={"error": result.message, "kind": result.kind},
                error=True,
                exit_code=1,
            )
        return CommandResult(
            text=f"scene {scene_id} installed",
            json_data={"scene_id": scene_id},
        )


scene_show: SceneShowCommand = SceneShowCommand()
```

**Shared types** — `commands/_result.py` carries `CommandResult` and
`Ctx`, matching vox's shapes verbatim (dataclass, `frozen=True`,
`slots=True`, four fields: `text`, `json_data`, `error`, `exit_code`).
`Ctx` composes the collaborators every command needs — the
`Operations` facade (`ctx.ops`), the resolved caller identity
(`ctx.identity` — `ConnectionId` + kind/name/repo/agent from
DES-086), and any per-repo config the operation reads.

**Adapters** —

- **CLI (`__main__.py`)** — noun-grouped Typer sub-apps. Each command
  is `_run(commands.scene_show, ...)` where `_run` owns the async
  context, JSON/text branching, and `typer.Exit(exit_code)` mapping.
- **MCP (`tools/*.py`)** — `@mcp.tool()` wrappers that call the
  command instance and JSON-encode `result.json_data` (falling back
  to `result.text`).
- **REST (`rest/*.py`)** — FastAPI route handlers that call the
  command instance and return `JSONResponse(result.json_data)` on
  success, `JSONResponse(result.json_data, status_code=<mapped>)` on
  error via the existing `OpError`→HTTP table.
- **Library (`__init__.py` + `client.py`)** — the noun-grouped facade
  above; `client.scene.show(...)` awaits the same instance.

**Divergence from vox — one, stated.** Vox has a residual split
between `commands/voice.py` (used by the CLI and library) and
`server_switches.py`'s `VoiceTool` (used by the MCP surface). Lux
does *not* replicate that split. Every adapter, MCP included, calls
the single command instance. The split is a legacy vox has not yet
retired; lux adopts vox's shape without adopting vox's transitional
duplication. This is the one place this design deviates from the
reference, and it deviates in the direction the reference itself is
moving. Vox is welcome to converge on the same rule.

**No commands-vs-facade fork.** The existing `Operations` facade
becomes an *internal* collaborator every command holds via `Ctx`. It
does not disappear (its typed request/result models are the vocabulary
the commands compose against), but it stops being a client surface —
no adapter reaches past `commands/` into `operations/` directly. This
inverts today's structure, where `tools/tools.py`, `rest/*.py`, and
the CLI each import `Operations` and format the same shapes three
times.

## Slash-command coverage

Every operation on every client surface gets a slash-command
equivalent — with three considered exceptions. The slash surface is
the one lux has not yet aligned; today `.punt-labs/lux/commands/`
carries a curated four (`lux:beads`, `lux:dashboard`,
`lux:data-explorer`, `lux:beads`). Under this epic it grows to a
per-noun-verb catalog matching the MCP tool set, minus the
exceptions.

### Considered exceptions

Three operations have no slash equivalent, with stated reasons:

| Operation | Reason for exception |
|---|---|
| `topic recv` | Non-blocking receive is a background poll from a listening client, not an interactive turn (memory: `project_blocking_ux_not_blocking_impl`). A slash `/lux:topic.recv` would fire once with an empty result almost always; the caller wanting real-time delivery uses the library's `LuxHubClient` listener or MCP's `topic_recv` inside a poll loop. |
| `session identify` | Identity is declared once per session at start (DES-057). A slash form invites re-identification mid-session, which the identity model doesn't need and which confuses the DES-086 store-key composition. Sessions identify via the MCP tool at handshake or the CLI's `--as/*` flags per invocation. |
| `callback register` | Callback registration is a programmatic step of hosting a menu entry; a slash form has no meaningful ergonomics because the caller has to provide the callback id (opaque) and the label (only meaningful in the context of a running applet). Slash surface is for user-typed operations, not agent-programmatic ones. |

Every admin-tier operation (`hub install|uninstall|start|stop|
restart|status`, `enable`, `disable`, `install`, `uninstall`, `mcp`,
`doctor`, `version`) is also absent from the slash surface — admin
verbs run from a shell, not from a Claude Code prompt. This is the
same rule that puts them off MCP; slash inherits.

The slash surface receives 29 new command definitions under `.6` —
one per client-tier operation minus the three considered exceptions
above (`session identify`, `topic recv`, `callback register`). By
noun: Scene 8, Frame 4, Menu 3, Session 2 (of 3), Topic 3 (of 4),
Callback 1 (of 2), Display 5, Event 1, Error 1, plus top-level
`ping` 1.

### Skill vs slash

Today's four `.punt-labs/lux/commands/` entries include skills
(`lux:beads` — orchestrates several operations to render the beads
board) and thin slashes (`lux:dashboard` — a single `show_dashboard`
call). Under this epic, the *thin slashes* are auto-generated from
the vocabulary (one per client-tier operation); the *skills* stay
skill-shaped but move under noun groupings — `lux:beads` becomes a
skill that lives alongside `/lux:scene.*` rather than at the top
level, so a caller looking for "what can I do with a scene?"
discovers both the primitives and the skills in one place.

## Cross-repo notify plan

The MCP rename train (`.5`) breaks two known consumers.
Coordination is a leader-executed runbook, not code.

**Consumers to notify:**

| Repo | What it consumes | Migration cost |
|---|---|---|
| `../vox` | Vox's music-player applet calls `pending_callbacks` and `set_menu` from the `lux-vox-music` applet (v0.22.1). | Rename to `callback_pending` and `menu_set`. Two lines. |
| `../z-spec` | The z-spec repo imports `punt_lux.client.LuxClient` (per project memory: broken since lux #135). This epic's library reorg finalizes `LuxClient` as the public entry point; z-spec already needs a cross-repo fix, and this epic makes the correct target concrete. | Adopt the noun-grouped `client.scene.*` calls; retire the ad-hoc `LuxClient` shape z-spec was pinned to. |

**Runbook the leader executes before `.5` merges:**

1. Biff `@vox` (session name from `/who`) with the rename table and
   the ETA of `.5`.
2. Biff `@z-spec` with the library API shape from §Library API and
   the ETA of `.7`.
3. Wait for `ack` from both. Silence is not consent — hold `.5` until
   both agents reply.
4. On `.5` merge: send a follow-up biff with the merged version and
   the `pip install` line.
5. Verify: vox's music-player renders on a fresh install of the new
   lux; z-spec's `lux render` command exercises the new library
   entry point. Both are demo-gate items for `.5` (vox) and `.7`
   (z-spec).

Biff — not GitHub issues — is the channel per
`memory:feedback_biff_is_the_only_cross_repo_channel`. Offline
recipients get a bead in their repo (`cd ../vox && bd create ...`).

## Security invariants — the DES-086 stance is preserved

Two invariants carry from DES-086 into this epic unchanged. The
vocabulary reorganizes the client surfaces above them; the invariants
under the surface are non-negotiable.

**Write scope.** Every write operation on every client surface
(`scene show`, `scene update`, `scene clear`, `scene clear-all`,
`frame raise`, `frame lower`, `frame close`, `frame expire`,
`menu set`, `topic publish`, `topic subscribe`, `topic unsubscribe`,
`callback register`, `display theme` set, `display mode` set,
`display window` set) composes its store key on the caller's own
`ConnectionId`. No operation on any surface accepts an `owner=`
override. This is the DES-086 Decision 5 narrowing.

**Content-read scope.** Every operation that returns another client's
content (`scene inspect`, `scene ls`, `event ls`, `error ls`,
`display screenshot`, `topic recv`, `callback pending`) composes on
the caller's own `ConnectionId` and returns only what the caller
owns. Metadata-only operations (`session ls`, `session inspect`,
`display info`, `menu ls`, `menu get`) return peer-discovery data
that is not confidential and stay visible to all callers.

**`--as/--kind/--name/--repo/--agent` is per-invocation identity,
not privilege elevation.** The CLI accepts these flags on any
client-tier command so a test or an operator can drive the engine as
a *different client* for that call. The flag composes a fresh
`ConnectionId` from the declared kind/name/repo/agent and runs the
operation against it. The caller does not gain any operation the
declared identity would not have; the caller *becomes* that identity
for one invocation. This is how the DES-086 live demo would have
exercised multi-client scenarios if the flag had existed then — it
had to bypass the CLI via raw REST because the flag did not exist.
The `.4` implementation restores that capability.

Absence of any admin-tier operation on any surface other than the
CLI is itself a security invariant: no superuser MCP surface, ever.

## Impacts on other ADRs

- **DES-057 (Client Identity — Declared Kind/Name, Leases, One
  Identity for Both Legs).** Reinforced. The `session identify`
  vocabulary and the CLI's `--as/*` flags are the surfaces this ADR
  contracts against. No semantic change to the identity model.
- **DES-063 (Lux Applets — Session-Bound Programs).** Reinforced.
  Applets consume the new `callback register` / `menu set` vocabulary
  under noun-first names; the applet framework itself does not
  change.
- **DES-086 (Connection-Scoped Store Keys).** Preserved verbatim. The
  four-surface parity does not weaken or bypass composition. Every
  write on every surface passes through `SceneInstaller.install`
  (or its `menu`/`frame` equivalents), which is where composition
  lives; the vocabulary reorganizes the callers, not the composer.
- **DES-058 / DES-067 (Menu callbacks, `(repo, session)` grouping).**
  Preserved. The `callback register` and `menu set/get/ls` verbs are
  the surfaces the menu model already runs over; renaming does not
  change the model.
- **DES-055 (One Code Path — Typed Hub Operations, REST Front Door,
  Thin Adapters).** Extended. DES-055 established `Operations` as the
  single engine facade and made REST, MCP, and CLI thin adapters over
  it. This epic *removes* the CLI/MCP/REST adapters as the shared
  layer and inserts `commands/` between `Operations` and the four
  adapters. `Operations` remains — it becomes an internal
  collaborator every command holds via `Ctx`, not a client surface.
  The direction of DES-055 (one code path) is preserved; the code
  path becomes one command instance per operation instead of one
  facade shape.

## Verification

Two demos gate the design's implementation missions.

**`.4` demo (CLI parity).** Run `lux scene show` end-to-end with
`--as kind=tool,name=demo-1`; verify a scene appears in the display.
Run `lux scene ls` with the same `--as`; verify the scene is listed
against `demo-1`. Run `lux scene ls` with `--as kind=tool,name=demo-
2`; verify the same scene is *not* listed (DES-086 caller-scope).
Machine evidence: `lux --json scene inspect <id>` from each identity
returns the right subset. Operator confirms the rendered pixels.

**`.5` demo (MCP rename train).** Fresh install of the new lux
plugin; MCP tool list shows every renamed tool from §The MCP rename
train under its new name and no old names present; vox's music-player
renders correctly against the new tool names (coordinated via the
cross-repo notify runbook above).

## Provenance

The seven ratified positions are the epic body's, decided in the
prior session between the operator and the leader. This design
mission's job was to name the operations, map them to surfaces, and
choose the shape of the commands layer. Vox's `commands/voice.py` is
the reference shape; the departure from vox on the MCP adapter (one
command instance instead of two) was the one non-trivial local
design choice and is stated openly in §Commands layer.

## Proposed ADR text for `DESIGN.md`

The paragraphs above are the design record; the following is what I
would paste into `lux/DESIGN.md` once this is ratified and
implemented, matching the existing DES-NNN format.

> ## DES-087: Client Surface Parity — One Vocabulary Across CLI, MCP, REST, and Library
>
> **Status:** proposed (design mission `m-2026-08-18-002`, bead
> `lux-0shg.1`, epic `lux-0shg`).
>
> **Problem.** Lux has four client surfaces of one engine and four
> different vocabularies for the same operations. The MCP surface
> carries 23 tools with verb-first, single-word names (`show`,
> `identify`, `list_clients`) that were fine at three tools and are
> a naming schism at 23. The CLI has admin verbs only — no client-
> tier presence. The library surface hands consumers transport
> objects (`LuxRestClient`, `LuxHubClient`) rather than engine
> nouns. Every operation is written four times — once as an
> `Operations` request shape, once as a REST handler, once as an MCP
> tool, once as a CLI command (if it has one). The menubar app
> epic (`lux-mxvy` R4) depends on the CLI's `hub *` group existing
> under a noun convention that today's CLI does not have.
>
> **Decision.** One vocabulary applied to all four client surfaces,
> under noun-first grouping. Ten nouns (`scene`, `frame`, `menu`,
> `session`, `topic`, `callback`, `display`, `event`, `error`,
> `hub`) plus a small set of top-level singletons split into a
> diagnostics tier (`ping`, `doctor`, `version`) and an admin tier
> (`enable`, `disable`, `install`, `uninstall`, `mcp`). Every engine
> operation appears on every client surface under the same name;
> each omission is a considered exception with a stated reason.
> The DRY pivot is a new `src/punt_lux/commands/` package holding
> one `@final` callable class per operation returning
> `CommandResult`, with `Ctx` for collaborators (vox's
> `commands/voice.py` is the reference shape). The existing
> `Operations` facade becomes an internal collaborator composed into
> `Ctx`; no adapter reaches past `commands/`. The MCP rename train
> (26 renames + 3 fuse-renames + 2 net-new tools, no aliases, no
> deprecation window) lands atomically with agent-prompt updates
> and cross-repo consumer
> updates (vox's music-player applet, z-spec's lux renderer). The
> CLI's `--as/--kind/--name/--repo/--agent` flags declare per-
> invocation identity — the caller BEING that identity for the
> call, not becoming an admin — restoring the multi-client-scenario
> capability the DES-086 live demo had to bypass the CLI to
> exercise.
>
> **Alternatives rejected.** *Per-surface epics* — separate epics
> for CLI parity, MCP renames, and library reorg — rejected because
> the four surfaces share one vocabulary; splitting the vocabulary
> across three epics guarantees drift between them and produces
> three review cycles for one decision. *Commands layer as
> conditional (python.md §Rule 5 today)* — rejected because with
> four adapters over 30 operations the "conditional" case is every
> case; keeping the layer optional keeps the four-copy drift the
> epic exists to end. *Verb-first grouping* (`show scene`,
> `list scenes`) — rejected because the noun is the stable axis
> (scenes exist; the verbs vary and grow); grouping by noun places
> related operations together in help output, in library
> discovery, and in the MCP tool list. *Aliases during the rename
> train* — rejected because two names for one operation is exactly
> the drift the epic ends; the coordination cost of a rename train
> is paid once, the cost of aliases is paid forever. *A superuser
> MCP surface for `hub *` admin operations* — rejected per DES-086
> Decision 5; MCP is a client surface, not an admin one.
>
> **Impacts on other ADRs.** DES-055 (one code path) extended: the
> `commands/` layer inserts between `Operations` and the four
> adapters; `Operations` remains but stops being a client surface.
> DES-057 (client identity), DES-063 (applets), DES-058 (menu-as-
> callbacks), DES-067 (menu grouping), and DES-086 (connection-
> scoped store keys) are all preserved verbatim — this epic
> reorganizes the vocabulary above them, not the invariants
> underneath.

## Decisions requiring operator ratification

The seven positions in the epic body are ratified. The three
grey-area rulings are ratified per §Grey-area rulings. The MCP
rename map is prior-conversation agreement (26 renames + 3
fuse-renames + 2 net-new tools per §The MCP rename train, after
round-2 amendments F1–F4 from the mdm evaluator review). Local
Decisions A (fuse get/set into one tool per concern) and B
(introduce `menu_get`) are ratified as-is (mdm concurred in
round 2).

No open decisions remain for operator ratification. Round-2
amendments F1–F4 (from `/Users/jfreeman/Coding/punt-labs/lux/.tmp/
missions/results/m-2026-08-18-002-mdm-eval.md`) are folded in:

- **F1** — `lux scene clear-all` is its own CLI verb, restoring
  parity with MCP's two-tool split.
- **F2** — `ping` is a top-level diagnostics verb, not a `hub *`
  member.
- **F3** — `set_frame_state` splits into four verbs (`frame raise`,
  `frame lower`, `frame close`, `frame expire`).
- **F4** — `session show` renamed to `session inspect`, removing
  the read/write overload on `show`.
