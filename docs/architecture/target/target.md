# Lux Target Architecture

**Status:** canonical target for the rewrite.

This document describes the architecture Lux is moving toward. It is not a
claim that the current code already cleanly implements this model. For the
current architecture — what the shipped code does today, honestly framed as a
system mid-migration toward this target — see [system.tex](../system.tex).

If you read only one target-architecture document, read this one.

## Problem

Lux exists so many agents and apps can share one visual surface.

- Minimum scope: one user with many agent/app UIs aggregated by one Hub.
- Maximum scope: many users with many agent/app UIs aggregated by one Hub.

Lux also exists so agents can verify what actually happened by inspecting the
live system rather than asking the user to report what they saw.

## Core Model

Lux is a Hub/Display system with one authority.

1. Clients submit UI to the Hub.
2. The Hub decodes or constructs typed UI objects. Every element self-validates
   first; a tree with any invalid element is rejected back to the client and is
   never installed or rendered (see
   [element-contract.md](./element-contract.md)). Valid UI objects are
   installed in `HubDisplay`.
3. `HubDisplay` is the authoritative store for UI state, ownership, and
   handler dispatch.
4. The Display receives a full replica of the UI and uses it only for
   rendering and input capture.
5. When the user interacts with the Display, the interaction is routed back to
   the owning Hub and the real handler runs there.
6. After a change, the Hub re-sends the whole affected UI to the Display.
   Lux does not need a diff protocol until a real performance problem appears.

The Hub wins every disagreement. The Display is a replica, not a second
authority.

## Front Doors

MCP is one entry point into the Hub, not the architecture itself.

Lux should support multiple front doors:

- MCP agents calling tools such as `show()` and `show_table()`
- direct applications using a client API
- future transports that speak the same Hub-facing model

A headless Python app can keep its authoritative UI in the Hub. An agent can
also create ad hoc UI directly through the Hub. Both fit the same model.

The MCP surface stays small on purpose. `show()` is the one universal render
API — it takes an arbitrary element tree — and widget conveniences
(`show_table`, dashboards, ask-user flows) are composed from it as skills
rather than added as standing tools, so the tool contract every agent carries
does not grow per widget. The elements are limited; the ways they combine are
unlimited. See [DES-040](../../../DESIGN.md).

## Communication Model

Lux has two primary communication legs:

- **Agent/App ↔ Hub:** clients submit UI, call client-API or MCP operations,
  use app-level pub-sub, and use introspection/control surfaces.
- **Hub ↔ Display:** the Hub sends replicated UI state to the Display, and the
  Display sends user interactions back to the Hub.

The important boundary rule is:

- **UI state crosses IPC.**
- **Render calls do not.**

That means scene trees, updates, serialized Lux element objects, and remote
interaction messages may cross the boundary. ImGui calls, renderer invocations,
and pixel operations do not. The Display receives replicated UI state and then
renders locally.

As Lux grows into a platform, more processes join these two legs: resource
daemons such as luxd-pty, more peripherals, and peered Hubs. They follow the
same rule and reach each other through a Hub. See
[Platform Packages](#platform-packages).

## Roles

```text
Agent or app
  - MCP client
  - client API user
  - future front door
          |
          v
Hub
  - owns HubDisplay
  - aggregates many app/agent UIs
  - executes real handlers
  - runs lightweight built-in UI behavior
  - publishes app-level events
  - exposes introspection APIs
          |
          | full UI replica
          v
Display
  - stores a full copy of the UI
  - renders that copy
  - wraps handlers for remote dispatch
  - forwards interactions to the owning Hub
```

## The Hub

The Hub is authoritative.

It hosts UIs, but it does not automatically imply built-in apps or built-in
screens. Apps and agents supply UI. The Hub stores, executes, and coordinates
that UI in a lightweight way.

That lightweight behavior includes things like:

- handler execution
- ownership checks
- observer-driven UI updates inside the composite hierarchy
- simple built-in UI behavior where it belongs in the UI model

## The Display

The Display keeps a full copy of the UI tree for whatever it is rendering.

Handlers on the Display copy are wrapped so they do not execute real behavior
locally. When invoked, they call back to the Hub that sent the UI. The Display
only needs to know which Hub owns that UI and how to communicate with it over
an already-established connection.

`SceneReplica` is the concrete class holding that copy — framed scenes via a
composed `FrameBook`, tree navigation via a composed `SceneTreeWalk`, and the
one responsibility that belongs to neither: when the Hub resends a scene,
diffing which element ids no longer survive and notifying the render loop so
queued or held interactions for elements that are gone get dropped instead of
firing on nothing. Its scene and frame data satisfy the Replication Policy
below by construction — exactly what the Hub's last resend put there, nothing
more.

`SceneReplica` also composes a `WidgetStateStore`, which is a different kind
of state entirely: selection, scroll position, and in-progress text the
Display accumulates locally across ImGui frames, opened and discarded with
its scene rather than carried in any Hub resend. It lives beside the
replicated scene data because both are scoped to the same scene's lifetime,
not because the Hub sent it.

A frame's **visibility** is the second and sharper counterexample to
"nothing more than the Hub's last resend put there" — sharper because it is
the one Display-local value a Hub resend could plausibly be expected to
overwrite, and must not. Two authorities write to a frame, and they own
different axes of it (DES-088):

| Axis | Owned by | Moved by | Held in |
|---|---|---|---|
| **Content** — does this scene id exist? | the client, via the Hub | `show()`, `update()`, an empty push, a manifest purge, a frame TTL | replicated: `FrameBook.scene_to_frame`, `Frame.scenes` |
| **Visibility** — where is this frame? | the user, at the Display | the close and collapse buttons, a dock pill, `raise_frame`, Expand/Collapse/Fit All | Display-local: `Frame.visibility`, `Frame.active_tab`, `FocusRequest`, `Frame.cascade_index` |

The rule that separates them is that a content event never writes visibility
and a visibility event never writes content. It is why a frame the user
closed keeps its scenes rather than being removed, why `close` and
`dispose_frame` are two methods rather than one with a flag, and why closing
a frame tells the Hub nothing at all. Visibility is never replicated back, so
it does not survive a Display restart — deliberately, like focus and cascade
position, because persisting it would mean sending a Display-owned value to
the Hub and re-deriving it from a resend, which is the coupling the rule
exists to sever.

## Event Models

Lux has two different event mechanisms and they must not be conflated.

- **UI event/observer mechanics:** local to the UI object hierarchy. These are
  things like handler invocation and observer cascades inside the composite
  tree.
- **Application pub-sub:** Hub-managed publish/subscribe for application-level
  events and topics. This is separate from the UI observer mechanism.

Application pub-sub is what enables business logic at the app level. A Hub-side
event handler may both perform local UI behavior and publish an application
event such as `openTicket`, `closeTicket`, or `markTicketInProgress`. That same
pub-sub channel may also be used by non-UI sources such as timers or other app
logic. The published topics are defined by the app or agent, not by Lux.
Pub-sub is not the canonical UI-state replication path; it is the business
event channel that reacts to state changes or other app activity.

## Replication Policy

The default replication rule is simple:

- if one relevant piece of UI state changes for a rendered UI, the Hub may
  resend the whole UI for that app/scene/display
- the Display replaces its previous copy with the new one
- ImGui re-renders the current copy every frame

This is simpler, easier to inspect, and easier to reason about than a
distributed incremental diff protocol.

## Platform Packages

Lux is becoming a family of processes that share one set of packages, not one
process. This section records the package names and layer rules agreed before
any more code moves. They are targets: today the code still ships as one
distribution, and `make check-layers` ratchets where it breaks these rules.

### Process roles

| Role | Responsibility | Examples |
|---|---|---|
| Hub | Authority: UI state, routing, handlers, app pub-sub, front doors | luxd; a user may run several, anywhere |
| Peripheral | Device-local replica: renders state, returns input | the Display; an audio peripheral later |
| Resource daemon | Owns durable resources independently of clients and peripherals | luxd-pty (persistent shells); may run anywhere |
| Spoke | Publishes UI or state and receives events through a Hub | MCP agents, the `lux` CLI, applets such as lux-beads, external projects |
| Hub peering | Shares state between Hubs | reserved; see [Mesh](#mesh-reserved) |

Processes share contracts and the public client SDK, never each other's
internals. No daemon imports another daemon.

### Packages

Every package lives under the one `punt_lux` namespace.

| Package | Namespace | Holds |
|---|---|---|
| lux-kernel | `punt_lux.kernel` | Primitives with no Lux dependencies: paths, logging and usage adapters, peer credentials, bounded socket writers and queues |
| lux-wire | `punt_lux.wire` | Pure contracts: the UI model (elements, kinds, handlers), Hub-to-Display replica messages and codec, public request and result types, terminal stream frames; `facts/` and `mesh/` reserved |
| lux-trust | `punt_lux.trust` | CA, enrollment, peer identity |
| lux-service | `punt_lux.service` | Daemon lifecycle shared by every daemon: install, backends, sweeps, doctor, endpoints and process ownership |
| lux-client | `punt_lux.client` | The spoke SDK: REST and listen legs, applet helpers, the Hub-carried terminal stream transport |
| lux-terminal | `punt_lux.terminal` | Headless VT behind libghostty and the shared output and snapshot policy; no daemon code |
| lux-commands | `punt_lux.commands` | Shared command execution and output formatting over kernel and wire contracts; no Hub or client implementation imports |
| lux-hub | `punt_lux.hub` | The Hub: authoritative store, handlers, links, operations and front doors; `mesh/` reserved |
| lux-display | `punt_lux.display` | The Display peripheral: window, replica, menus, ImGui renderers, terminal view |
| lux-pty | `punt_lux.pty` | luxd-pty: sessions, processes, viewers, stream server |
| lux-cli | `punt_lux.cli` | The `lux` command, built on the client SDK and service lifecycle |
| applets | `punt_lux.applets` | Bundled spokes such as lux-beads, built on the client SDK |
| punt-lux | — | Meta-distribution: the default single-machine install under the existing PyPI name |

### Layer rules

The first package move installs lifecycle code under `punt_lux.service`, with
the service managers exported from its `__init__.py`. Private implementation
modules retain their leading underscores. `HubPaths` and the default Hub port
live in `punt_lux.kernel`, independent of either the Hub or client SDK.
Project display-mode file I/O belongs to `service.display_mode_store`; the
Typer-facing enable/disable orchestration belongs to `cli.display_enablement`.

Step 3 merges shared domain and protocol definitions into `punt_lux.wire.model`;
the Hub and `protocol.pty` were retained for later migrations. The merged
facade exports the wire `Element` union and the structural `ElementProtocol`.
`LeaseTerm` is a shared wire value, while `ConnectionId` and `ProgrammerError`
belong to kernel. Display socket/process lifecycle, including protocol-aware
readiness probing, belongs to `service.display_paths`, not kernel. Package moves
must remove actual forbidden edges as well as update names in the shrinking
ratchet baseline; the legacy package initializers do not alias moved models.

Step 4 promotes the Hub to `punt_lux.hub` and removes the empty
`punt_lux.domain` package, without import aliases. Shared patch parsing and
validation errors move into `wire.model.patch_batch` and
`wire.model.write_errors`, removing the shared request model's Hub dependencies.
The Display's unpickler also remaps old `domain.hub` paths: published element
handlers carry `HubPublishSink` across the Hub→Display pickle boundary.
Ready version `0.3` refuses Displays still using the old Hub namespace before
scenes are sent, with an actionable Display restart error.
`protocol.pty` remains at this step until its step-7 migration.

Step 5 consolidates the SDK under `punt_lux.client`: WebSocket access, the HTTP
transport contract and values, identity headers, and CLI identity resolution.
`client/rest_transport.py` owns the public transport contract;
`client/_rest_transport.py` remains the distinct private implementation, without
new facade re-exports. Shared `ClientIdentity` and applet-name formatting belong
to `wire.model`, so clients, applets and request models do not depend on Hub
behavior. Applets import operation values from `operations.models`, classified
as wire, rather than the Hub-owned operations facade.
The client facade's dependencies on `punt_lux.commands` remain baseline debt
pending a design decision.
The moved identity values do not occur in Hub-to-Display element pickles, so
Ready remains `0.3` and the existing pickle remapping is unchanged.

Step 6 folds the old `punt_lux.apps` package into `punt_lux.beads`,
which now holds the whole Beads applet: the `lux-beads` program
(`beads/applet.py`), its service and source, the `bd` runner, and the
board that turns a load into a render request. The board builds those requests
from `operations.models`, removing the last direct static applets-to-Hub edge.
This does not yet isolate runtime imports: Python executes `operations/__init__.py`
before loading `operations.models`, and that initializer eagerly loads the
Hub-owned operations facade; the public root package imports operations too.
Removing that transitive Hub load remains debt of
the operations package, not part of this move. Generic
applet machinery (leg, claim, watch, board cache and slots) stays in
`punt_lux.applets`. No alias module remains at `punt_lux.apps`.

Step 7 moves the PTY owner from `punt_lux.ptyd` to `punt_lux.pty`, including
`process_group.py`, and moves its stream contracts from `protocol.pty` to
`wire.stream`. The `luxd-pty` executable and wire formats are unchanged; no
old-path aliases remain. Tests mirror `pty/` and `wire/stream/`.
`pty.menu_projection` imports `OpError` and `RenderRequest` from
`operations.models`, removing the direct static PTY-to-Hub edge. The operations
initializer and public root still eagerly load Hub code, as described in step 6;
runtime import isolation remains operations-package debt.

The pickle decoder maps old `protocol.pty` globals to `wire.stream` without
making the old package importable. Ready remains `0.3`: terminal scene pickles
contain model elements with primitive placement fields, not stream contracts or
PTY execution objects. PTY control and stream frames use JSON/binary codecs,
not pickle; no PTY execution pickle-name remapping is needed.

Step 8 prepares extraction of `lux-service` and `lux-client`: public operation
requests and results move from `operations.models` to `wire.operations`, and
the per-family operation Protocols and command context move from `commands`
to `wire.ops`. Client accessors call their operation ports directly through
`asyncio.to_thread`; commands retain their MCP/CLI execution and formatting.
Client identity headers and their encoded values now live in `wire.model`.
Pure menu/callback values, connection-scoped IDs, frame ownership facts and
scene presentations also live there; the mutable presentation registry remains
Hub-owned. No old-path alias or compatibility facade is retained.

The operations initializer exports only `Operations` and `HubPorts`. The root
package no longer re-exports the Hub's `ping` command. Fresh-interpreter tests
prove that importing `punt_lux`, `punt_lux.client` or `punt_lux.service` loads
no Hub, commands, operations facade, Display or PTY modules. Client static
layer violations are zero. `service.service_spec.ServiceSpec`, exported by
`punt_lux.service`, is public; both existing supervisor backends can install
a non-Lux daemon without changing `HUB_SPEC` or `DISPLAY_SPEC`.

Ready remains `0.3`. Operation requests/results are REST/MCP JSON, menus are
wire dictionaries, and presentation/ownership values become primitive scene
fields. None of the moved classes is captured by the shipped element/handler
pickles; `HubPublishSink` still reduces to its unchanged class and `ConnectionId`.
Every element kind and a Hub-bound publish handler have regression coverage
for the absence of moved globals. No new Display-unpickler remap is necessary.

Step 9a prepares package-directory ownership for a uv workspace: all 34
remaining top-level implementation modules move into their existing kernel,
Hub, Display or CLI layer, preserving filenames without collisions. Only
`__init__.py` and `__main__.py` remain at the root; `commands`, `operations`,
`tools` and `rest` retain their paths. The tracked `protocol/__init__.py`
remains an empty namespace, not an alias. Old implementation imports fail in
fresh interpreters; entry points, tests and callers use the package-owned paths.

`kernel.display_defaults.DEFAULT_RECV_TIMEOUT` is the shared display-leg
budget, independent of the Hub. Terminal supervisor registration and opt-in
enablement move from `pty.service` and `pty.enablement` into
`service.terminal_service` and `service.terminal_enablement`. Foreground display
lifecycle belongs to `service.display_foreground`: `lux display serve` checks
the display extra and execs `python -P -m punt_lux.display` in the same environment,
retaining its PID, terminal and exit status without importing the renderer
into the CLI. The renderer entry point lives in `display.luxd_display`.

Commands are now a separate layer, allowed to import only kernel and wire.
Both Hub and CLI may use commands; command execution and MCP/CLI output remain
unchanged. The runtime dependency baseline is empty. No moved implementation
class occurs in shipped Hub-to-Display element/handler pickles or the Ready
handshake, whose fields are wire values and primitives. Ready remains `0.3`;
no additional pickle-name remap is needed.

A package may import only from itself and the packages listed for it.
`tools/layer_contract.py` holds the same table and `make check-layers`
reports every runtime import edge that breaks it. The checked-in
`.layer-baseline.json` allows the known migration violations; new edges fail
`make check-layers` (also run by `make check` and CI). Stale entries fail too:
after removing violations, run `make update-layers` and commit the shrinking
baseline. The update target refuses to add new violations to an existing baseline.
The check also rejects baseline additions relative to `BASE_REF` (by default,
the merge base with `origin/main`, when available), so adding an import and its
baseline entry together cannot bypass the gate. A base without the baseline file
skips only this growth comparison, allowing the initial baseline to land. CI uses
the PR merge base or the pre-push commit on main, with full git history.

| Package | May import |
|---|---|
| kernel | nothing else in Lux |
| wire, trust | kernel |
| service, client | kernel, wire, trust |
| commands | kernel, wire |
| terminal | kernel, wire |
| hub | kernel, wire, trust, service, commands |
| display | kernel, wire, trust, service, terminal |
| pty | kernel, wire, trust, service, client, terminal |
| applets | kernel, wire, trust, service, client |
| cli | kernel, wire, trust, service, client, applets, commands |

Display and pty may both use terminal's headless VT, but never each other.

### Terminal streams go through the Hub

Terminal output, snapshots, input and resize travel Display → Hub → luxd-pty
and back, like any other UI state and interaction. Today the Display opens a
direct local socket to luxd-pty instead. That direct link is the latency
baseline the Hub path is measured against, not the target.

### Mesh (reserved)

Hubs will sometimes share state, for example a blackboard. Only the package
slots are reserved; there is no protocol or conflict-handling design yet.

- `wire/facts`: a log of tuples with a current-state query on top.
- `wire/mesh` and `hub/mesh`: Hub peering messages and the Hub side of peering.

### Packaging and other repositories

- Lux keeps the `uv_build` backend and ships one distribution for now. The
  packages above become separate distributions in a uv workspace later.
- vox stays in its own repository and consumes the shared Lux packages
  (wire, service, client) instead of carrying its own copies.

## Current Demonstrated Slice

Only a small slice of this target is demonstrated cleanly in the code today.

The real sliver is:

- Hub-side `HubDisplay` authority
- connection-scoped Hub pub-sub
- ABC-backed Lux elements on the button/dialog path
- Display-side handler wrapping for remote dispatch
- Hub-side re-dispatch of the real handler after a display click

That sliver is enough to validate the architectural direction. It is not yet
evidence that the entire current codebase cleanly implements the full target.

## Verification

The architecture includes introspection so agents can verify real outcomes.

An agent should be able to:

- verify its own UI *before* render — self-validation returns any malformed
  element to the agent instead of rendering it (see
  [introspection-api.md](./introspection-api.md))
- render UI through its real entry point
- trigger real interactions
- inspect live Hub/Display state
- compare the observed result with expected behavior

## Related Target Docs

- [README.md](./README.md)
- [topology.md](./topology.md)
- [ui-model.md](./ui-model.md)
- [element-contract.md](./element-contract.md)
- [introspection-api.md](./introspection-api.md)
- [../system.tex](../system.tex) §"Identity, Addressing, and Multi-Hub
  Topology" and §"Cross-Host Transport and Trust" — identity ladder,
  multi-Hub aggregation, and cross-host transport/trust (DES-089, DES-090)
