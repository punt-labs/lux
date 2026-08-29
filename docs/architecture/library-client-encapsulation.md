# Library Client Encapsulation: Retiring the Public REST Transport

**Status:** design, unimplemented. Bead `lux-duqj`, mission `m-2026-08-22-006`.
Implementation is a separate mission after operator ratification.

This document answers the design questions in bead `lux-duqj`. The framing is
**encapsulation, not deletion**: `LuxClient` (`src/punt_lux/client/facade.py:46`)
is the one public library class every consumer imports; its REST transport is
an implementation detail that must stop being importable, stop being handed out
by `AppletRunner`, and stop appearing in applet method signatures. Grounded
throughout in the current tree, not assumed — every claim below was verified by
reading the cited file:line.

## 1. The Three Leaks, Confirmed Against the Current Tree

The bead names three leaks. All three are confirmed:

1. **Importable.** `src/punt_lux/rest_client.py:66` declares `__all__ =
   ["LuxRestClient"]` and the class at line 70 is `@final class LuxRestClient`.
   `src/punt_lux/__init__.py` does not import it (confirmed: no `rest_client`
   reference in that file's 116 lines), so `from punt_lux import LuxRestClient`
   already fails — but `from punt_lux.rest_client import LuxRestClient` still
   succeeds, because the *module* is a plain top-level module with no
   leading-underscore anywhere in its path. Removing a name from `__all__`
   changes nothing about what `import` can reach; only a module's own path can
   do that.
2. **Handed out.** `src/punt_lux/applets/runner.py:84-91` — `ServiceRunner._rest(self)
   -> LuxRestClient` builds `LuxRestClient.for_identity(self._identity)` and
   returns it to `ServicedClick` (`applets/serviced_click.py:82`, `_connect:
   Callable[[], LuxRestClient]`). A second, structurally identical `_rest()`
   exists on `AppletLeg` at `applets/leg.py:172-179`. The bead's own text names
   "`AppletRunner._rest()`" informally; the actual classes are `ServiceRunner`
   and `AppletLeg` — both are cited here so the implementation mission does not
   miss the second one.
3. **Typed into every applet signature.** Confirmed by grep across
   `src/punt_lux/applets/`: `runner.py:84`, `applet_board.py:29,78`,
   `service.py:22,51,61` (the `AppletService` Protocol itself —
   `acknowledge`/`service` both take `client: LuxRestClient`),
   `beads_service.py:33,97,107`, `serviced_click.py:39,55,65,100,105`,
   `board_channel.py:24,35,38`, `board_work.py:19,28,34`, `board_load.py:31,54,92`,
   `leg.py:40,172,179`. Fourteen files carry the type name.

A fourth site the bead does not name but the grep-zero verification (§9) forces
into scope: **the CLI**. `src/punt_lux/cli/_shared.py:27,253-274` —
`connect_client()` builds and returns `LuxRestClient` directly, and every CLI
verb module (`cli/scene.py`, `cli/menu.py`, `cli/frame.py`, `cli/session.py`,
`cli/display.py`, `cli/event.py`, `cli/error.py`, `cli/callback.py`,
`cli/beads.py`) constructs `Ctx(ops=connect_client(...), identity=identity)`
against it — nine call sites in `cli/scene.py` alone. `cli/beads.py:86` also
calls `LuxRestClient.connect()` directly, a fifth pattern. None of these are in
the mission's file input list, but `grep -rn LuxRestClient src/` cannot return
zero while they stand, so §6 below designs their migration alongside the
applets'.

Two more references are prose-only, not imports, and need only a text edit:
`hub_client.py:8` (a docstring cross-reference) and
`operations/callbacks.py:48` (an error-message string literal).

## 2. What `LuxClient` Already Covers — No Gaps

Bead design question 4 asks whether `LuxClient` already has noun-grouped
accessors for every operation `LuxRestClient` / `SceneRestOps` / `DisplayRestOps`
expose. Checked method-by-method against `rest_client.py`'s full public surface
(lines 150-350) and `client/facade.py`'s eight accessors:

| `LuxRestClient` method | `LuxClient` accessor |
|---|---|
| `render`, `render_table`, `render_dashboard`, `update`, `clear`, `clear_scene`, `list_scenes`, `inspect_scene` | `client.scene.*` (`client/scene.py:56-100`) |
| `raise_frame`, `close_frame` | `client.frame.*` (`client/frame.py:38-44`) |
| `list_menus`, `set_menu` | `client.menu.*` (`client/menu.py:38-44`) |
| `list_clients`, `identify` | `client.session.*` (`client/session.py:41-49`) |
| `register_callback` | `client.callback.register` (`client/callback.py:44-46`) |
| `get_display_info`, `get_theme`/`set_theme`, `get_window_settings`/`set_window_settings`, `read_display_mode`/`write_display_mode`, `screenshot` | `client.display.*` (`client/display.py:85-129`) |
| `list_recent_events` | `client.event.ls` (`client/event.py:30-33`) |
| `list_errors` | `client.error.ls` (`client/error.py:30-33`) |
| `ping` | `client.ping` (`client/facade.py:146-149`, top-level) |
| `listener` | `client.listener` (`client/facade.py:151-161`, top-level) |

Every method is covered. **No gap.** `rest_client_scenes.py`'s `SceneRestOps`
and `rest_client_display.py`'s `DisplayRestOps` are not independently public
today — confirmed by grep: nothing outside `rest_client.py` imports either
name — so question 4's answer for them is "already absorbed": they are private
implementation-detail collaborators `LuxRestClient.__new__` composes
(`rest_client.py:93-94`), not a second public surface.

The one omission is `TopicOps` (`commands/_ports.py:180-199`: `publish`,
`subscribe`, `unsubscribe`, `receive`) — `LuxClient` has no `client.topic`
accessor and `LuxRestClient` never implemented `TopicOps` either (the pub-sub
commands `topic_publish`/`topic_recv`/`topic_subscribe`/`topic_unsubscribe`
exist in `commands/__init__.py:51-54,101-104` but are wired to MCP only, per
`client/facade.py`'s own docstring at lines 3-11: *"`topic` ... omitted this
cycle: neither has a REST route today"*). This gap **predates** this bead,
applies equally to the class before and after the rename, and is not something
encapsulating the transport creates or worsens — it stays out of scope here,
tracked wherever the REST topic routes land.

## 3. Private Module Layout

### 3.1 What moves, and where

The bead's own text distinguishes two families and only one of them is in
scope. **Out of scope, unchanged, verified by grep to have zero domain
vocabulary in their public surface:**

- `rest_transport.py` (`HttpTransport` Protocol, `HttpResponse`, `HubUnavailableError`)
  — the bead states this explicitly ("stays as-is ... legitimate primitive").
- `rest_http_call.py` (`HttpCall`) and `rest_reply.py` (`RestReply`) — generic
  request-building and reply-reading value types. Grep confirms their only
  importers are `rest_client.py`, `rest_client_scenes.py`, `rest_client_display.py`,
  and their own test files (`tests/test_rest_http_call.py`,
  `tests/test_rest_reply.py`). Neither type knows about scenes, menus, or any
  `punt_lux` domain noun — their public API is `verb`, `path`, `body`,
  `headers`, `status` — the same class of thing `HttpTransport` is, which the
  bead already carves out. Moving them would be scope creep with no
  encapsulation benefit: nothing outside the transport family reaches them
  today, and after the rename nothing will either.
- `rest_loopback.py` (`LoopbackTransport`, the concrete `HttpTransport` over the
  local port) — same reasoning: zero importers outside the transport family
  and its own `tests/test_rest_loopback.py`.

**In scope, renamed and moved** — the three modules that carry `punt_lux`
domain vocabulary (scene, menu, frame, theme, display-mode) and that the bead
names directly:

| Current | New |
|---|---|
| `src/punt_lux/rest_client.py` (`LuxRestClient`, 350 lines) | `src/punt_lux/client/_rest_transport.py` (`_RestTransport`) |
| `src/punt_lux/rest_client_scenes.py` (`SceneRestOps`, 136 lines) | `src/punt_lux/client/_rest_scenes.py` (`_SceneRestOps`) |
| `src/punt_lux/rest_client_display.py` (`DisplayRestOps`, 99 lines) | `src/punt_lux/client/_rest_display.py` (`_DisplayRestOps`) |

**Why `client/`, not a new `_client/` package.** The bead's text offers
`src/punt_lux/_client/_rest_transport.py` as one option. This design rejects a
new top-level package: `client/` already exists, already holds
`facade.py` plus the eight accessor modules, and the accessors already import
`LuxRestClient` as their `ops` parameter type today (`client/scene.py`'s
`SceneAccessor.__new__` takes `ops: SceneOps` structurally satisfied by it,
`client/facade.py:31` imports it directly). The transport's natural home is
beside the facade that composes it — one package, one cohesive unit (PL-MD-2)
— not a second package that would exist solely to hold three files, immediately
imported by the first package on every use. **Naming convention: leading
underscore on the *filename*** (`_rest_transport.py`, not
`rest_transport_private.py` or a `_private/` subdirectory), matching the
existing convention already in this codebase for `commands/_ports.py`,
`commands/_result.py`, `commands/_faults.py`, `applets/board_ops.py`'s sibling
`_`-prefixed modules, and `client/facade.py:56-60`'s own private attributes.
Python enforces nothing about leading-underscore *modules* — the enforcement is
(a) no `__init__.py` ever imports the name into `__all__` (§3.2), and (b) the
structural test in §9.

### 3.2 `client/__init__.py` — unchanged in shape, changed in content

`client/__init__.py` currently exports all eight accessor classes plus
`LuxClient` (`__init__.py:26-36`). This design does not touch that list —
`_RestTransport`, `_SceneRestOps`, `_DisplayRestOps` are never added to it.
This is the whole mechanism: a name that never appears in any `__all__` and
whose module has no re-export path is unreachable except by an explicit
`from punt_lux.client._rest_transport import _RestTransport` — and a linter or
reviewer sees the leading underscore in that import and rejects it on sight, a
structural cue `LuxRestClient`'s plain module name (`rest_client.py`) never
carried.

**Note (out of scope, flagged for a separate bead):** `client/__init__.py`
exporting all eight accessor classes (`CallbackAccessor`, `DisplayAccessor`, …)
is itself a mild interface-width finding (PL-MD-3: 9 names, under the 20-name
ceiling, so not a hard failure, but arguably nothing outside `client/` should
construct an accessor directly — only `LuxClient`'s `cached_property`s do).
This design does not fold that into `lux-duqj`: the bead is scoped to the REST
transport, not the accessor layer, and the accessor classes carry zero
transport-identity information (unlike `LuxRestClient`, nothing about
`SceneAccessor` being importable lets a caller reach past `LuxClient`'s scope
or identity handling). Left as an observation for a future, separately-scoped
bead.

## 4. `LuxClient.sync` — the Sync/Async Resolution

### 4.1 The actual shape of "async" in this codebase, verified

Bead design question 2 assumes `LuxClient` is uniformly async. Reading the
accessor bodies shows something more specific: **every accessor method is
`async def`, but the body is `await asyncio.to_thread(ctx.ops.<method>, ...)`**
— confirmed in `commands/scene_show.py:34-38` (`SceneShowCommand.execute`) and
identically shaped in every other command module under `commands/`. The
*transport itself* (`LuxRestClient`, soon `_RestTransport`) has always been
fully synchronous — plain `urllib`-backed calls with no `async def` anywhere in
`rest_client.py`. The `async`-ness `LuxClient` adds exists **only** to let an
already-async caller (the CLI's `asyncio.run(coro)` in `cli/_shared.py:288`,
the MCP server's request handlers) issue a blocking HTTP call without stalling
their own event loop — it is a courtesy layered on top of synchronous work, not
a property of the transport.

This fact resolves the sync-vs-async question directly: a sync caller does not
need `asyncio.to_thread` + `asyncio.run` ceremony wrapped around a call that
was synchronous all along. It needs a typed reference to the same transport
instance, narrowed to only the methods it needs.

### 4.2 The three options, and the decision

**(a) Applets become async — rejected.** `applets/runner.py:1-16`'s own module
docstring states the invariant this would break: *"None of it may run on the
leg's loop, which is the one renewing the session's lease — a slow click
running there would lapse the very session whose menu item was clicked."*
`ServiceRunner.clicked()` (`runner.py:55-66`) and `.warmed()` (`runner.py:68-78`)
deliberately dispatch to `asyncio.to_thread` specifically so `AppletService.
acknowledge`/`.service` — which shell out to `bd` and push HTTP requests, both
blocking — never touch the leg's event loop. Making `AppletService.acknowledge`
`async def` and awaiting `LuxClient`'s async accessors from inside it would
require either (i) running it on the leg's own loop after all, which is exactly
the lease-lapsing hazard the module docstring names, or (ii) spinning up a
*second* event loop inside the worker thread to `await` calls whose underlying
work (§4.1) is synchronous regardless — more machinery for the same outcome.
Rejected: it inverts an existing, load-bearing design invariant to solve a
problem that does not exist at the transport layer.

**(c) Applet base class exposes `.run(coro)` — rejected.** There is no applet
base class to put it on. `applets/service.py:1-14`'s module docstring is
explicit: *"An applet satisfies this by having the methods, not by inheriting
anything: the leg holds whatever it was handed and calls it."* `AppletService`
is declared `@runtime_checkable class AppletService(Protocol)`
(`service.py:28`) — this is the family-by-protocol shape `oo.md` names
("Families share by protocol, not base class") and `punt-kit/standards/oo.md`
restates verbatim. Introducing a base class solely to carry a `.run()` bridge
method would (i) contradict this already-established, already-documented
no-inheritance contract for the one class in scope that would need it
(`BeadsService`, `applets/beads_service.py:49` — a `@final` class satisfying
`AppletService` structurally, with zero parent today), and (ii) still just be
`asyncio.run()` under a different name, providing no capability `.sync` (below)
does not already provide more directly. Rejected on both grounds.

**(b) `LuxClient` adds sync passthroughs — accepted.** Because the underlying
transport is already synchronous (§4.1), the "passthrough" is not a wrapper
that spawns an event loop per call — it is a typed accessor that hands back the
same transport instance the async accessors already share, narrowed to a
`Protocol` so the concrete class is never named outside `client/`.

```python
# src/punt_lux/client/facade.py — one new member on the existing class
@cached_property
def sync(self) -> SyncOps:
    """The synchronous ops surface this client's transport already satisfies.

    For callers that are architecturally synchronous and must not create or
    join an event loop -- an applet's worker thread, dispatched via
    ``asyncio.to_thread`` specifically so it never touches the loop renewing
    its own session's lease (see ``applets/runner.py``'s module docstring).
    Returns the SAME transport instance ``scene``/``frame``/``menu``/...
    compose -- no new object, no ``asyncio.run()`` per call, no thread hop.
    Its declared type is a Protocol, never ``_RestTransport`` by name, so a
    caller can hold and pass this value without importing anything private.
    """
    return self._transport
```

`self._transport` is already typed `_RestTransport` on `LuxClient`
(`facade.py:57`, renamed from today's `LuxRestClient`); the property's
*declared* return type is `SyncOps`, a `Protocol` (§4.3) — Python permits
returning a concrete private type from a method whose annotation names only a
public structural type, exactly as `commands/_ports.py`'s `SceneOps` Protocol
is already satisfied structurally by `LuxRestClient` with no inheritance
declared anywhere (`rest_client.py`'s class header is `class LuxRestClient:`,
no base). This is the *existing* pattern in this codebase, not a new one.

### 4.3 `SyncOps` — the composite Protocol

```python
# src/punt_lux/client/_sync_ops.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from punt_lux.commands._ports import (
    CallbackRegisterOps,
    DisplayInfoOps,
    DisplayModeOps,
    ErrorOps,
    EventOps,
    FrameOps,
    MenuOps,
    PingOps,
    SceneOps,
    ScreenshotOps,
    SessionOps,
    ThemeOps,
    WindowOps,
)

__all__ = ["SyncOps"]


@runtime_checkable
class SyncOps(
    PingOps,
    SceneOps,
    FrameOps,
    MenuOps,
    SessionOps,
    CallbackRegisterOps,
    EventOps,
    ErrorOps,
    DisplayInfoOps,
    ThemeOps,
    WindowOps,
    DisplayModeOps,
    ScreenshotOps,
    Protocol,
):
    """Every synchronous Hub operation ``LuxClient.sync`` exposes at once.

    A Protocol extending every per-family Ops Protocol in
    ``commands/_ports.py`` -- satisfied structurally by ``_RestTransport``
    (renamed from ``LuxRestClient``) purely because that class already has
    every one of these methods; extending this Protocol adds no new
    requirement on it. Its purpose is narrower than "expose the transport":
    it lets a caller's ``Ctx[SceneOps]`` (or ``Ctx[MenuOps]``, or a
    narrower composite like ``applets.board_ops.BoardOps``) accept
    ``client.sync`` without that caller ever importing ``_RestTransport``.
    """
```

`SyncOps` lives in `client/` (not `commands/_ports.py`) because it is not read
by any command — `_ports.py`'s own docstring scopes it to *"the ops surface the
[…] commands read"* — `SyncOps` is a client-side convenience type whose only
consumer is `LuxClient.sync`'s signature and, transitively, the CLI and
applets (§5, §6). This keeps `_ports.py` at its current 297 lines, under the
300-line module-size ceiling (PY-OO-2), with no risk from this bead.

Why a `Protocol` combining thirteen family Protocols and not `object` +
`cast()`: `cast()` at every call site defeats the type checker for the exact
surface this bead exists to make safe (mypy/pyright would no longer verify a
CLI verb file's `Ctx[SceneOps]` construction is well-typed). Why not export the
concrete `_RestTransport` type directly and skip the Protocol: that is
precisely the leak this bead closes — a private class escaping through a
"just this once, for typing" exception is still an escape.

**`SyncOps`'s thirteen-Protocol width is not new coupling — it names a surface
that already exists.** Read in isolation, a Protocol extending thirteen others
looks like an Interface Segregation Principle violation: no single caller needs
all thirteen families at once (§5.2's `BoardOps` needs two; `cli/callback.py`
needs one). But `SyncOps` does not *create* a class that must implement
thirteen families — `_RestTransport` (renamed from `LuxRestClient`) already
has every one of these methods today, verified in §2's table, and has had them
since before this bead. `SyncOps` is a *name* for a shape that was already
true of the concrete class; it adds no new method requirement to
`_RestTransport` and forces no consumer to depend on more than the narrower
Protocol it actually calls (`Ctx[SceneOps]`, `BoardOps`, or
`CallbackRegisterOps`, per §5.2 and §6.2 — each call site still narrows to
what it uses; only the *value* flowing through `LuxClient.sync` is typed as
the wide union at its one production point). If a future change ever needs
`_RestTransport` to shed a family — say, `ScreenshotOps` moves to a different
transport — that is the moment `SyncOps` stops being an accurate name for the
concrete class and must shrink to match; until then, the width documents the
existing shape rather than inventing a wider one for `LuxClient.sync` to
satisfy.

### 4.4 Thread Safety: `.sync` and the Async Accessors Share One `_RestTransport`

`.sync` returns the identical `self._transport` instance the async accessors
(`client.scene`, `client.frame`, …) already compose (§4.2's code: `SceneAccessor(
self._transport, …)`, `facade.py:102`). That means an applet's worker thread
calling `client.sync.render_table(request)` and, in a different process or a
concurrent CLI/MCP invocation holding the *same* `LuxClient` instance, an
`await client.scene.show(...)` running via `asyncio.to_thread` can both be
mid-flight against one `_RestTransport` object at once. This is a real
concurrent-access question, not a hypothetical — `asyncio.to_thread` already
runs `_RestTransport.render` on a thread-pool worker today, so the transport
has always had to tolerate concurrent calls from multiple threads; `.sync`
only adds a second *style* of caller (a dedicated, longer-lived worker thread
instead of a thread-pool one-shot), not a new class of hazard.

**Verified safe, by inspection of every piece of state a call touches:**

1. **`_RestTransport.__new__` state is set once and never mutated.**
   `rest_client.py:88-95` assigns `self._transport`, `self._identity`,
   `self._headers`, `self._scenes`, `self._display` exactly once in
   `__new__` and no method reassigns any of them afterward — confirmed by
   grep: the only `self._x =` assignments in the class body are inside
   `__new__`. `_headers: dict[str, str]` is built once via
   `ClientHeaders.to_wire(identity)` and read-only from every method that
   uses it (`self._headers` is passed as an argument to `HttpCall.write`/
   `.read`/`.post`/`.command`, never indexed-and-assigned). Two threads
   reading the same never-mutated dict concurrently is safe under the GIL
   and needs no lock.
2. **Every HTTP round trip opens its own connection.** `rest_loopback.py:34-54`
   — `LoopbackTransport.request()` constructs a fresh
   `http.client.HTTPConnection` inside the method body, uses it, and closes
   it in a `finally` block, every call. There is no persistent socket, no
   connection pool, and no `self._connection`-style shared handle on
   `LoopbackTransport` (its `__slots__` are `_port`, `_timeout` only,
   `rest_loopback.py:32`, both set once in `__new__` and never reassigned).
   Two threads calling `.request()` concurrently each get their own
   independent socket; there is nothing to race over.
3. **The port is re-read per `for_identity()` call, not cached on the
   transport.** `rest_client.py:119` — `HubPaths().read_port()` opens and
   reads a file fresh on every call; `HubPaths` itself
   (`hub_paths.py:19-59`) holds no mutable state either, only the `_dir`
   root path set once. Concurrent reads of the same port file are
   independent file-descriptor operations with no shared in-process state
   to corrupt.
4. **`HttpCall` (the one object built per request) is a frozen dataclass.**
   `rest_http_call.py:24-31` — `@dataclass(frozen=True, slots=True)`, every
   field set at construction, no method mutates it. A value object built
   fresh on each call, handed to `LoopbackTransport.request()`, and never
   retained — nothing for a second thread to observe mid-mutation.

No lock is required anywhere in this call graph because there is no shared
*mutable* state — only shared *read-only* state (the identity, the headers
dict, the port-file path) and per-call fresh objects (the connection, the
`HttpCall`). This is the same "no lock needed, no shared mutable state to
race over" shape `service-lifecycle-migration.md` §4.1 documents for
`PortGuard`/`LegacySweep`'s per-instance caches — cited here because it is
the same reasoning pattern this codebase already applies elsewhere, not
because the two subsystems share code.

**What this does NOT cover, named explicitly rather than left implicit:**
Two concurrent *writes racing to install the same scene id* is a Hub-side
ordering question (last-write-wins at `HubDisplay`, unrelated to this
bead), not a transport thread-safety question — the transport's only job is
"send this one request, return this one reply," and it does that
independently per call regardless of how many threads call it at once. If a
future change gives `_RestTransport` any per-instance mutable cache (a
connection pool, a memoized port, a retry counter), that change becomes the
point where a lock — or a documented single-writer discipline — must be
added; nothing in the current implementation needs one, and this design
introduces no new mutable state to the class.

## 5. Applet-to-Client Relationship

### 5.1 Who constructs `LuxClient`, and when

**One construction point per applet process**, at the same place
`ServiceRunner._rest()` and `AppletLeg._rest()` construct `LuxRestClient`
today — because the reason those two methods build *per-use* rather than
holding one instance across the applet's life still applies verbatim: both
docstrings state the port is re-read on each build because "a Hub that
restarted onto a new port is followed here exactly as the listen client
follows it, instead of pushing to a port nobody is on" (`runner.py:87-90`,
identical text `leg.py:174-178`). This behavior is preserved — the change is
only the return type, from `LuxRestClient` to the narrower ops Protocol the
call site actually needs:

```python
# src/punt_lux/applets/runner.py — ServiceRunner, was _rest() -> LuxRestClient
def _rest(self) -> BoardOps:
    return LuxClient.for_identity(self._identity).sync
```

```python
# src/punt_lux/applets/leg.py — AppletLeg, was _rest() -> LuxRestClient
def _rest(self) -> BoardOps:
    return LuxClient.for_identity(self._identity).sync
```

`BoardOps` (§5.2) is a narrower Protocol than `SyncOps` — applets need three
methods, not thirteen families' worth — but both are satisfied by the exact
same `client.sync` value, because `SyncOps` structurally extends `SceneOps`
and `FrameOps`, `BoardOps`'s two ingredients (§5.2). No second object is built;
`_rest()` still constructs exactly one `LuxClient` per call, exactly as it
constructs exactly one `LuxRestClient` per call today — the docstring's
"built per use rather than held" invariant is unchanged, only the type is
narrower.

### 5.2 `BoardOps` — the narrow Protocol applet internals hold

Applet-internal classes (`BoardChannel`, `ServicedClick`, `BoardLoad`,
`BoardWork`, `AppletService`) collectively call exactly three methods on the
object they are handed: `.raise_frame(frame_id)` (`board_channel.py:53`),
`.render(request)` and `.render_table(request)` (`board_channel.py:79-80`).
`SceneOps` already declares `render`/`render_table`
(`commands/_ports.py:63-72,83-88`) and `FrameOps` already declares
`raise_frame`/`close_frame` (`commands/_ports.py:110-116`) — no new
single-family Protocol is needed, only their combination, because no single
existing Protocol has both:

```python
# src/punt_lux/applets/board_ops.py
from __future__ import annotations

from typing import Protocol, runtime_checkable

from punt_lux.commands._ports import FrameOps, SceneOps

__all__ = ["BoardOps"]


@runtime_checkable
class BoardOps(SceneOps, FrameOps, Protocol):
    """The Hub-write surface a board push needs: raise a frame, install a scene.

    Composed here, in the applets package, rather than as a member of
    ``client._sync_ops.SyncOps`` -- the composite belongs beside its one
    consumer (PY-IC-9: types and Protocols in their own modules, close to
    where they are read), not inside the client package that produces
    values satisfying it. ``LuxClient.sync`` returns a ``SyncOps``, which
    structurally satisfies ``BoardOps`` for free (``SyncOps`` extends both
    ``SceneOps`` and ``FrameOps``); no adapter, no cast.
    """
```

**Why `BoardOps` and `SyncOps` are placed asymmetrically — one beside its
consumer, one beside its producer — stated explicitly rather than left for a
reader to reconstruct.** `BoardOps` lives in `applets/board_ops.py`, inside
the package that is its *only* consumer: `applets/service.py`,
`applets/serviced_click.py`, `applets/board_channel.py`,
`applets/board_work.py`, `applets/board_load.py`, `applets/applet_board.py`,
`applets/beads_service.py` — every one of the fourteen retyped sites in §1 is
inside `applets/`. PY-IC-9's placement rule ("types and Protocols in their own
module, close to where they are read") has one clear answer here because
there is one reader.

`SyncOps`, by contrast, has **no single consumer package** — it is read by
`client/facade.py` (as `LuxClient.sync`'s return-type annotation), by
`cli/_shared.py` and every `cli/*.py` verb module (§6.2), and by
`applets/runner.py`/`applets/leg.py` (§5.1, as the type `_rest()` narrows from
before handing the value down into `BoardOps`-typed applet internals).
Placing it inside any one of those consumer packages (`applets/`, say, since
it is a superset of what `BoardOps` needs) would make the other consumers
(`cli/`) import a type from a package they have no other relationship to —
`cli/_shared.py` importing from `punt_lux.applets` to type a CLI-only client
would itself be a layering smell (CLI has no business depending on the applet
package). `SyncOps` is placed beside its **producer** instead —
`client/_sync_ops.py`, in the same package as `client/facade.py`, whose
`LuxClient.sync` property is the one place that actually returns a value of
this type. Every consumer (`cli/`, `applets/`) imports `SyncOps` from
`client/`, the same package they already import `LuxClient` from, rather than
from one another. This is the same rule PY-IC-9 states (place the type near
where it is *read*), applied to the case where reads fan out across packages
with no shared parent other than the type's own producer: the producer is the
one place every reader already depends on, so it is the placement that adds
no new inter-consumer coupling.

Every applet-internal class that today spells `client: LuxRestClient` (the
fourteen sites in §1, item 3) is retyped to `client: BoardOps`:
`applets/service.py:22` (the `AppletService` Protocol's own `acknowledge`/
`service` signatures), `applets/serviced_click.py:39,55,65,100,105`,
`applets/board_channel.py:24,35,38`, `applets/board_work.py:19,28,34`,
`applets/board_load.py:31,54,92`, `applets/applet_board.py:29,78`,
`applets/beads_service.py:33,97,107`. Fourteen `LuxRestClient` references become
fourteen `BoardOps` references, each a plain type-name substitution — no
behavioral change, because `BoardOps`'s three methods are called with
identical signatures to today's `LuxRestClient` calls.

### 5.3 Rejected: AppletRunner constructs and injects the client

Considered having `ServiceRunner.__new__` build one `LuxClient` at applet
startup and pass it down through `AppletBoard`/`BoardLoad`/`BoardChannel` as a
constructor argument, rather than each `_rest()` call rebuilding on demand.
Rejected because it silently drops the reconnect behavior both existing
`_rest()` docstrings state as their reason for existing (§5.1) — a `LuxClient`
built once at startup holds a `_RestTransport` pointed at whatever port `luxd`
was on at that moment, and a `luxd` restart onto a new port would leave every
subsequent push targeting a stale, closed port with no code path that
re-resolves it. This is not a hypothetical: `HubPaths().read_port()`
(`rest_client.py:119`) is exactly the read that must happen fresh on every
`for_identity()` call to track a restarted Hub, and injecting a single
long-lived instance removes that freshness. Per-call construction (§5.1)
preserves the existing, deliberate behavior; injection would regress it while
looking like a pure refactor.

### 5.4 Rejected: applet subclass constructs its own client

Considered having `BeadsService` (or any future applet) build its own
`LuxClient` directly inside `acknowledge()`/`service()`, bypassing
`ServiceRunner`/`AppletLeg` entirely. Rejected because it duplicates the
identity-resolution responsibility `ServiceRunner`/`AppletLeg` already own
(`_identity: ClientIdentity`, set once from `AppletIdentity.for_session()` at
construction, `runner.py:42,47-53`) into every applet author's code, and
because `AppletService` is explicitly a thin Protocol with **no** construction
responsibility of its own (§4.2's citation of `service.py:1-14`) — its methods
receive collaborators, they do not build them. Keeping construction at the leg
level (`ServiceRunner`/`AppletLeg`) matches the existing division: the leg
owns connection lifecycle, the service owns what a click does with a
connection it is handed.

## 6. CLI Migration (Forced by the Grep-Zero Verification, Not Listed in the Mission's File Set)

### 6.1 Why the CLI cannot be left alone

`cli/_shared.py:253-274`'s `connect_client()` is not a mission input file, but
it is a `LuxRestClient` import site, and `grep -rn LuxRestClient src/` (§9) must
return zero for the bead to close. The CLI's own architecture (§1) is
structurally different from the applets': every CLI verb already runs inside
`asyncio.run(coro)` (`cli/_shared.py:277-288`, `run()`), calling `await
command(ctx, ...)` where `command` is a `commands/` singleton
(`SceneShowCommand.__call__`, `scene_show.py:40-44`) that both performs the
operation **and** formats it into a `CommandResult` (`render_outcome`,
`scene_show.py:46-67`) — `LuxClient`'s accessors (`SceneAccessor.show`) call
only the *operation* half (`.execute()`, not `.__call__()`, `scene_show.py:34-38`
vs `40-44`) and return the raw `SceneShown | OpError`, with no `CommandResult`
formatting. Routing the CLI through `LuxClient`'s accessors would require the
CLI to re-implement the `render_outcome` formatting itself at every verb site
— strictly more code than today, for no encapsulation gain the `.sync`
mechanism does not already provide.

### 6.2 The fix: `connect_client()` returns `LuxClient`, call sites read `.sync`

`connect_client()`'s entire purpose today is *"give me something satisfying
the ops Protocols"* (its return type, `LuxRestClient`, is never used for
anything but building a `Ctx[XxxOps]`). Since `LuxClient.sync` is exactly
"something satisfying the ops Protocols," the fix is a return-type change plus
a one-line change at every call site:

```python
# src/punt_lux/cli/_shared.py — connect_client, was -> LuxRestClient
def connect_client(
    *, identity: ClientIdentity | None = None, timeout: float = 2.0
) -> LuxClient:
    try:
        if identity is not None:
            return LuxClient.for_identity(identity, timeout=timeout)
        return LuxClient.connect(timeout=timeout)
    except HubUnavailableError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from None
```

```python
# src/punt_lux/cli/scene.py — every one of the nine call sites, mechanical
ctx: Ctx[SceneOps] = Ctx(ops=connect_client(identity=identity).sync, identity=identity)
run(scene_show(ctx, request, scope=scope_for(identity)), flags)
```

Same one-line pattern (`connect_client(...).sync` instead of
`connect_client(...)`) at every `Ctx[XxxOps]` construction across
`cli/menu.py`, `cli/frame.py`, `cli/session.py`, `cli/display.py`,
`cli/event.py`, `cli/error.py`. `cli/callback.py:60,63` (`_client: LuxRestClient`,
`__new__(cls, client: LuxRestClient)`) retypes to `CallbackRegisterOps`
(`commands/_ports.py:148-162`, the exact single-family Protocol its one method
needs — no reason to widen to `SyncOps` when the narrower Protocol already
exists and is already imported by that file's sibling command).
`cli/beads.py:29,66,86` (`LuxRestClient.connect()` used directly, plus a
`client: LuxRestClient` parameter on `_BeadsPusher`-equivalent) becomes
`LuxClient.connect().sync` at line 86 and `client: BoardOps` at line 66 —
`cli/beads.py` pushes the same table/scene requests `applets/beads_service.py`
does, so it is a second consumer of the exact `BoardOps` Protocol defined in
§5.2, not a reason to invent a third one.

### 6.3 Rejected: leave the CLI on a direct, unrenamed transport import

Considered treating the CLI as "inside the library's own implementation"
(same top-level package, `punt_lux.cli`) and letting it import
`client._rest_transport._RestTransport` directly, unchanged in spirit from
today's `LuxRestClient` import. Rejected: `cli/` is a presentation-layer
package under the four-layer model this codebase already documents
(`.claude/rules/python-module-design.md`'s `PL-MD-1`, layers 1-4, "Presentation
— CLI, MCP server, hooks, applets" is layer 4, outermost) — `client/` is not
"core" either, but it is the one package whose whole purpose is being the
public surface other layers consume. A presentation-layer package reaching
into a sibling presentation-adjacent package's private module is exactly the
kind of import the leading-underscore convention exists to make visually
wrong at review time, even though Python's import system does not block it.
Routing through `.sync` costs one attribute access per call site and keeps
every consumer — CLI, applets, any future external caller, tests — reaching
the transport through exactly one typed, public door.

## 7. What Rides Along With the Rename (Unavoidable at Implementation Time)

Two references outside the fourteen-plus-CLI sites are prose, not imports, and
are one-line docstring/message edits:

- `hub_client.py:8` — a Sphinx-style cross-reference
  (`:class:`~punt_lux.rest_client.LuxRestClient``) in `LuxHubClient`'s module
  docstring, explaining why both legs share one identity. Becomes
  `:class:`~punt_lux.client.facade.LuxClient``, since after this design the
  *client-facing* name to point a reader at is `LuxClient`, not the transport
  it composes — the docstring's point (both legs share one identity) is about
  the identity, not the transport class, so pointing at the public facade is
  more correct, not merely renamed.
- `operations/callbacks.py:48` — an error-message string literal:
  `"...or a client built with LuxRestClient.listener"`. Becomes `"...or a
  client built with LuxClient.listener"` (`LuxClient.listener`,
  `client/facade.py:151-161`, already exists and already delegates to
  `self._transport.listener(...)` — the message names the right public
  method today under the wrong class name).

`tests/test_rest_client.py` (`tests/test_rest_client.py`, 30+ tests per its
grep in the investigation above) is the direct test file for
`LuxRestClient`/`_RestTransport`. Per this repo's test-mirrors-source
convention (`tests/CLAUDE.md`, "Mirror source structure"), it moves to
`tests/client/test_rest_transport.py`, importing `_RestTransport` from its new
private path — legitimate, because a module's own test file is definitionally
"inside the implementation" the private-module convention exempts. Its
sibling `tests/rest/_fakes.py` (imported at `test_rest_client.py:30`,
`make_client`) is unaffected in location; only its target class's import path
changes.

## 8. What Stays Exactly As It Is

- `rest_transport.py`, `rest_http_call.py`, `rest_reply.py`, `rest_loopback.py`
  — §3.1, unchanged paths, unchanged names, unchanged public status.
  `HubUnavailableError` stays re-exported from `punt_lux/__init__.py:63,80` —
  it is the one exception type every consumer (CLI, applets, external callers)
  legitimately needs to catch, and the bead's own text names it a "legitimate
  primitive."
- `LuxHubClient` (`hub_client.py`) — the bead's stated non-scope, confirmed
  untouched except the one docstring cross-reference in §7.
- Every `LuxClient` accessor's existing async surface (`scene`, `frame`,
  `menu`, `session`, `callback`, `display`, `event`, `error`, `ping`,
  `listener`) — zero signature changes. `.sync` is additive.
- `commands/_ports.py`'s thirteen existing per-family Protocols — zero edits;
  `SyncOps` and `BoardOps` both import and extend them, adding no new method
  requirement to any of them.

## 9. Post-Implementation Verification

Exact commands, each expected to return zero lines:

```bash
grep -rn "LuxRestClient" src/ tests/ docs/
grep -rn "from punt_lux.rest_client import" src/ tests/
grep -rln "^class .*RestOps\|^class LuxRestClient" src/punt_lux/*.py   # no top-level survivor
test -f src/punt_lux/rest_client.py && echo "STILL PRESENT"            # file itself is gone
test -f src/punt_lux/rest_client_scenes.py && echo "STILL PRESENT"
test -f src/punt_lux/rest_client_display.py && echo "STILL PRESENT"
grep -rn "_RestTransport\|_SceneRestOps\|_DisplayRestOps" src/ tests/ \
  | grep -v "^src/punt_lux/client/" | grep -v "^tests/client/"          # zero: private names
  # never appear outside client/'s own implementation and its own test dir
```

`make check` (§9.2's structural test is part of the ordinary `make test` run,
not a separate gate) must pass with the OO ratchet showing an improvement on
every touched file — `rest_client.py`'s 350 lines splitting across
`_rest_transport.py`/`client/_sync_ops.py`/`applets/board_ops.py` is itself a
module-size improvement (PY-OO-2) on a file that was already at the edge of
the 300-line ceiling.

## 10. Test Fixture Design

### 10.1 Structural encapsulation test (new)

A dedicated test asserting the leak cannot reopen silently — this is the test
that answers "how does the design verify the encapsulation," not merely "how
does the design verify the operations still work":

```python
# tests/client/test_encapsulation.py
"""Structural guard: the REST transport must never be importable by name."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src" / "punt_lux"
_PRIVATE_NAMES = frozenset({"_RestTransport", "_SceneRestOps", "_DisplayRestOps"})
_PRIVATE_MODULE_STEMS = frozenset({"_rest_transport", "_rest_scenes", "_rest_display"})


def test_private_transport_module_not_importable_from_init() -> None:
    """No __init__.py anywhere in the package re-exports a private name."""
    for init_py in _SRC.rglob("__init__.py"):
        tree = ast.parse(init_py.read_text())
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert imported.isdisjoint(_PRIVATE_NAMES), (
            f"{init_py} imports a private transport name -- leak reopened"
        )


def test_no_module_outside_client_imports_the_private_transport() -> None:
    """Only client/'s own modules (and its own tests) may import the transport."""
    for py_file in _SRC.rglob("*.py"):
        if py_file.parent.name == "client":
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(
                    node.module.endswith(stem) for stem in _PRIVATE_MODULE_STEMS
                ), f"{py_file} imports the private transport module {node.module}"
```

This is a **structural** test — it walks the AST rather than grepping text, so
it survives reformatting and catches `import punt_lux.client._rest_transport
as rt`-style evasions a plain grep would miss. It belongs beside
`tests/client/test_facade.py` (already exists, §Investigation) as
`tests/client/test_encapsulation.py`.

### 10.2 `.sync` unit tests (new, mirrors `test_facade.py`'s existing shape)

`tests/client/test_facade.py:21-25`'s `_build_client()` already builds a
`LuxClient` over a `MagicMock()` transport, asserting each async accessor is
constructed and cached. Add the same shape for `.sync`:

```python
def test_sync_returns_the_same_transport_every_time() -> None:
    client = _build_client()
    assert client.sync is client.sync
    assert client.sync is client._transport  # not a new wrapper object
```

A `MagicMock()` satisfies `SyncOps` structurally by construction (any
attribute access succeeds), so this test proves caching and identity, not
behavior — behavior is covered by §10.3.

### 10.3 Applet fixture updates (existing files, type-only changes)

`tests/applets/board_doubles.py:216-298` already defines `RecordingClient`
and `UnraisableClient` as **hand-written stand-ins satisfying the ops
Protocol structurally** — confirmed: the file imports zero names from
`rest_client.py` (grep of its import block, lines 19-24), only
`punt_lux.operations` and `punt_lux.rest_transport.HubUnavailableError`. These
tests already exercise the target design's Protocol-based contract and
require **no behavioral change** — only their annotations (if any name
`LuxRestClient` explicitly rather than relying on structural duck-typing)
move to `BoardOps`. This is the strongest existing evidence the target design
is not aspirational: the test doubles for the applet layer were already
written against a Protocol, not a concrete class, before this bead existed.

### 10.4 CLI fixture updates (existing files, one call-site pattern)

`tests/cli/test_scene.py`, `test_display.py`, `test_frame.py`,
`test_callback.py`, `test_session_event_error.py` construct their own fake
transports today (per the same Protocol-first pattern `board_doubles.py`
uses) and monkeypatch `connect_client` — these tests change only insofar as
`connect_client`'s fake now returns a `LuxClient`-shaped stand-in exposing
`.sync`, not a bare transport-shaped one. No test asserts on `LuxRestClient`
by name (confirmed: `test_scene.py`, `test_display.py`, `test_frame.py` only
appear in the earlier grep for `LuxRestClient` because they import fixtures
from `board_doubles.py`/`rest/_fakes.py`, not because they reference the class
directly in test bodies).

## 11. End-to-End Verification Plan (Demo Gate)

Per `docs/WORKFLOW.md`'s demo-gate requirement, the implementation mission's
demo is not "the unit tests pass" — it is driving the real entry points:

1. **CLI**, against a running `luxd`: `lux scene show '{"elements": [...]}'`
   exercises `connect_client().sync` end to end over the real REST surface —
   expected output unchanged from today (`shown:<scene_id>`), because
   `.sync`'s methods are the literal same bound methods `LuxRestClient`
   exposed, only reached through a renamed, relocated class.
2. **Applet**, against a running `luxd` and a real repository with beads:
   `lux-beads --session-pid 0` (unattended mode, per `applets/beads.py:71-79`),
   click the Beads menu entry in the live display, confirm the board renders
   — exercises `ServiceRunner._rest()` → `LuxClient.for_identity(...).sync` →
   `BoardChannel.send()` → `_RestTransport.render_table()` end to end. This is
   the same click path `docs/board_ordering.tex` already formally verifies at
   the ordering level; this design changes none of that ordering, only the
   type flowing through it.
3. **Structural**, no `luxd` required: run §10.1's two AST-walking tests and
   §9's grep block; all must show zero.

## Related Documents

- `docs/architecture/binary-rename-migration.md` — the sibling rename-train
  design this document's citation style (grounded file:line claims, a
  rejected-alternatives section per decision, a verification section with
  exact commands) is modeled on.
- `docs/architecture/service-lifecycle-migration.md` — the original
  cure-verify-report shape both rename-train designs share; not directly
  reused here (no lifecycle/ordering hazard in this bead — a Python import
  path has no analogue to a launchd registration outliving its plist), cited
  only for the shared documentation discipline.
- `punt-kit/standards/architecture.md` — the Projection Model: "library,
  CLI, MCP server, REST API" as the four thin client surfaces of one engine;
  "client-specific state lives in the engine, keyed by client" and "the
  transport is an implementation detail" are the two invariants this whole
  bead exists to restore for the library surface specifically.
- `../vox/src/punt_vox/commands/` — the humble-object commands reference
  (`@final` callable class, `__new__` constructor, module-level singleton)
  this codebase's `commands/` package already follows; `SyncOps`/`BoardOps`
  are Protocols, not commands, but the composition discipline (one
  responsibility, no inherited base, structural satisfaction) is the same
  stance applied one layer up.
- Bead `lux-0shg` — client surface parity (vocabulary, noun-grouping) across
  CLI/MCP/REST/library. This design does not re-argue that epic's rulings;
  §2's "no gap" finding and §4.3/§5.2's Protocol names both use the
  noun-grouped vocabulary `lux-0shg` already established (`scene`, `frame`,
  `menu`, …) rather than inventing a parallel one.
- `src/punt_lux/rest_client.py`, `rest_client_scenes.py`,
  `rest_client_display.py`, `client/facade.py`, `client/*.py`,
  `commands/_ports.py`, `applets/runner.py`, `applets/leg.py`,
  `applets/service.py`, `applets/beads_service.py`, `applets/board_channel.py`,
  `applets/board_load.py`, `applets/board_work.py`, `applets/serviced_click.py`,
  `applets/applet_board.py`, `cli/_shared.py`, `cli/scene.py`, `cli/beads.py`,
  `cli/callback.py` — the current implementation this design extends or
  touches.
