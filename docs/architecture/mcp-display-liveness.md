# MCP Tool ↔ Display Liveness/Timeout Boundary

No tool an agent calls should ever wait on the display window. When a tool
changes the screen, it updates the Hub's own copy of the interface and returns
right away. A background worker inside the Hub — the replicator — sends those
changes to the display, and it alone deals with a slow or dead display. Tools
that read information ask the Hub, and the Hub reads the display for them when
the answer lives there. The Hub is the only party that talks to the display; no
tool connects to it directly. So a stuck display can no longer freeze an agent.

## Trust boundary

The system has two places where one party trusts another, and only two:

- A client reaches the Hub through one of the Hub's surfaces — the MCP tools,
  the CLI, the library, or the REST API. MCP is the surface this document is
  written around, because that is where the 38-minute freeze happened, but the
  boundary is identical for all four. The Hub is the one engine; these are its
  client surfaces (see the Architecture standard).
- The Hub talks to the display over a socket.

Every client goes through the Hub. No client ever opens its own connection to
the display. This matters for security: there is no third path, straight from a
client to the display, that would have to be trusted and guarded on its own.
Clients that change the screen write to the Hub's store. Clients that read the
screen ask the Hub, and the Hub — not the client — is what reads the display.

## The incident

An MCP `clear` call once blocked the agent for about 38 minutes. Here is the
path through the code:

- `tools/tools.py:561 clear()` first clears the Hub's store
  (`HubSceneWriter(hub_display).clear(...)`). Then, on the same thread, it sends
  the clear to the display: `client_registry.get().clear()` →
  `display_client.py:600 clear()` → `_send` → `display_client.py:497
  sock.sendall(wire)`.
- That socket blocks and has no send timeout (`connect()`,
  `display_client.py:251`, sets none). The display had stopped reading, so the
  kernel's send buffer for the socket filled up and `sendall` waited forever.
  `_send` holds `self._lock` the whole time it is stuck
  (`display_client.py:496`). The listener thread needs that same lock for its
  `recv` (`display_client.py:410`), so it stalled too, and the whole client
  froze.
- After about 30 minutes, Claude Code's idle timeout for the server finally
  aborted the call. The timeout did not cause the hang. The hang came from
  sending to the display, synchronously, on the thread handling the agent's
  call.

The same weakness sits in `show`, `show_table`, and `show_dashboard`, which also
wait up to 5s for an ack (`_recv_ack`, `display_client.py:531`), and in
`update`, which resends the scene inline (`repush_scene`). The real cause is the
shape of the design: the agent's call reaches the display at all. It should
never do that.

## Requirements

- **R1 — Tools that change or interact with the screen talk to the Hub and
  return.** `show`, `show_table`, `show_dashboard`, `update`, `clear`, and the
  pub/sub tools `recv` and `publish` write to `HubDisplay`, the Hub's in-memory
  copy of the interface, and return at once. They never call `DisplayClient`,
  never resend a scene, never call `sendall`, and never wait for an ack.
- **R2 — The Hub sends updates to the display in the background.** A background
  worker copies the Hub's store to the display whenever a scene changes, resending
  the whole scene. By the time it sends anything, the tool call has already
  returned.
- **R3 — Everything to do with a slow or dead display lives in that worker.**
  The time-limited send, the check for a stuck display, and killing and
  restarting it all happen on the worker. The agent's tool call never waits for
  any of it.
- **R4 — `recv` takes whatever is waiting and returns.** It never blocks inside
  the tool. To wait for an event, the agent polls on its own schedule.
- **R5 — Reads go through the Hub, have a time limit, and change nothing.** A
  read calls a query on the Hub. If the answer is in the Hub's store, the Hub
  answers directly. If it lives in the display — the live widget state, or a
  screenshot — the Hub reads it over its one connection and passes it back. The
  tool never opens its own connection. Every read from the display has a time
  limit on both the send and the receive, and returns a clear timeout or
  `"not running"` rather than hanging.
- **R6 — The idle timeout for the server no longer matters for latency.**
  Because nothing on the agent's path waits on the display any more, this timeout
  almost never fires. We keep it only as a safety net: if a later change
  accidentally puts a blocking call back on that path, the timeout still cuts it
  off.

## Two tool categories

The rule for reaching the display is different for the two kinds of tools, and
the whole design turns on this split.

| Category | Tools | Boundary rule |
|----------|-------|---------------|
| **Changes or interacts with the screen** | `show`, `show_table`, `show_dashboard`, `update`, `clear`, `recv`, `publish`, `subscribe`, `unsubscribe` | Change the Hub's store and return right away. Never connect to the display and never wait on it. The Hub's background worker sends the change to the display and deals with a slow or dead one. |
| **Reads / debug** | `inspect_scene`, `list_scenes`, `list_recent_events`, `list_errors`, `screenshot`, `get_display_info`, `list_menus`, `list_clients`, `get_theme`, `get_window_settings`, `ping` | Ask the Hub for information. If the answer is in the Hub's store, the Hub gives it directly; if it lives in the display, the Hub reads it over its one connection. Every read has a time limit and changes nothing: it returns a clear timeout or `"not running"` rather than hanging, and the tool never connects to the display itself. |

Both kinds go through the Hub; the Hub is the only party that talks to the
display. A few tools sit in between — `set_theme`, `set_window_settings`,
`set_frame_state`, `set_menu`, and `register_tool`. They neither write to the
store nor simply read it; they tell the display to change how it draws. These go
through the Hub on the same time-limited round-trip. If the send hits its time
limit, they return `"timeout"` right away. They never kill the display; only the
worker does that.

## The design

### Mutation tools: mutate the store, signal dirty, return

Each of these tools keeps the part that updates the store and drops the part
that sends to the display:

| Tool | Keeps (in-process) | Removes (was on the tool thread) | Returns |
|------|--------------------|----------------------------------|---------|
| `show` / `show_table` / `show_dashboard` | `hub_display.replace_scene`, `record_frame` | `client.show(...)` + `_recv_ack` wait | `"shown:<scene_id>"` |
| `update` | `HubSceneWriter.apply` | `client_registry.repush_scene` | `"shown:<scene_id>"` or `"error: … <reason>"` |
| `clear` | `HubSceneWriter.clear` | `is_running()` probe + `client.clear()` | `"cleared"` |

Once it has updated the store, the tool tells the worker the scene changed —
marking it *dirty* — by calling `replicator.mark_dirty(scene_id, frame_id)`, or
`replicator.mark_cleared(connection_id)` for `clear`, and then returns. Both
calls just add an entry to a queue inside the Hub; neither does any I/O. The
string the tool returns means the Hub accepted the change and will send it, not
that the display has drawn it. To check what actually rendered, an agent reads
the live system through an introspection tool rather than trusting an ack. This
matches the replica model in `target.md`, where the Hub holds the real state and
the display is a copy.

`clear` no longer checks whether the display is up (`is_running()`) and no
longer sends to it on the tool thread. Emptying the Hub's store should not depend
on the display being alive. Keeping the display in step is now the worker's job,
not the tool's.

### The Hub replicator: one background worker

One background thread inside the Hub, called `HubReplicator`, does all the
sending to the display. It starts when luxd starts and stops when luxd stops. It
owns the single connection to the display, and it is the only thing that writes
to it.

**Telling the worker a scene changed.** The worker keeps a set of the scenes
that have changed since it last sent them, plus a flag that says the screen was
cleared. A `Condition` guards both:

```text
mark_dirty(scene):   with cond: dirty.add(scene); cond.notify()
mark_cleared():      with cond: cleared = True;   cond.notify()
```

**The worker loop.** The worker waits on the condition until something changes.
When it wakes, it waits a further 16 milliseconds — one frame at 60 frames per
second — so that a quick burst of `update()` calls can pile up. Combining several
rapid changes into one resend this way is called coalescing. It then takes the
whole set of changed scenes under the lock and sends each one outside the lock:

```text
with cond:
    while not dirty and not cleared: cond.wait()
    cond.wait(0.016)                 # coalesce a burst
    batch, was_cleared = drain(dirty), take(cleared)
if was_cleared: push_clear()         # blank FIRST — see below
for scene in batch:                  # snapshot LATEST state under the store lock
    with hub_display.read_lock():    # copy roots out, then push outside the lock
        roots = list(hub_display.scene_roots(scene))
        frame = hub_display.frame_id_for(scene)
    push(scene, roots, frame)
```

The clear is sent before the batch, never after. A `clear` followed quickly by
a `show` lands in the same coalescing window, and if the worker painted the new
scene first and then sent the clear, the clear would blank the scene it just
painted — the display would sit empty while the Hub's store holds a live
scene. Blanking first and then repainting the batch always leaves the display
showing the store's latest state. Model-checking found the lost update in the
send-then-clear order and verified clear-first against it
(`docs/hub_replicator.tex`).

Coalescing takes no extra effort. Many changes to one scene mark it as changed
just once. When the worker is about to send, it reads that scene's current state
from the store. So the display always receives the newest version, never a
half-finished one from the middle of a burst.

**The store needs a lock, and this is not optional.** Today `HubDisplay` runs on
a single thread and assumes it always will. Its docstring says the invariants are
checked when a change is applied and trusted afterwards. `scene_roots`
(`hub_display.py:136`) reads a dictionary with no lock, and `replace_scene`
(`hub_display.py:187`) makes several `apply` calls that change that dictionary as
it goes. If the worker reads the store while a mutation thread is inside
`replace_scene`, the two race: Python raises `RuntimeError: dictionary changed
size during iteration`, or the worker reads a half-updated list of roots. So the
design adds a read/write lock to `HubDisplay`. Every path that changes the store
— `replace_scene`, `apply`, `HubSceneWriter` — takes the write lock. The worker
takes the read lock just long enough to copy a scene's roots out, then sends the
copy. This race already exists today, so the lock is not new debt:
`_hub_interaction_dispatch` already calls `repush_scene` → `scene_roots` on the
listener thread (`clients.py:164`, `:185`) while a mutation thread can be inside
`replace_scene`. The lock closes a hole that is already open; the worker is what
makes closing it necessary.

**Clicks on the display use the worker too.** When the user clicks something, the
handler runs on the Hub and often changes the store. Today
`_hub_interaction_dispatch` (`clients.py:102`) runs the handler and then resends
the scene itself, inline, on the listener thread. That is the same unsafe send as
before, just on a different thread. Instead, once the handler has changed the
store, it marks the scene dirty with `replicator.mark_dirty(scene)`. Every resend
— whether it came from an agent's tool or from a user's click — now goes through
the one worker.

**Giving the send a time limit.** The worker sends with `show_async` over a
socket that has `SO_SNDTIMEO` set in `connect()`. `SO_SNDTIMEO` is the socket
option that puts a time limit on a send. The following was measured on macOS with
Python 3.13:

- When the time limit is hit, the send raises `BlockingIOError`, not
  `TimeoutError`. Setting `SO_SNDTIMEO` with `setsockopt` leaves the socket in
  blocking mode as far as CPython is concerned — `gettimeout()` still returns
  `None` — so a full buffer comes back as `BlockingIOError` (errno `EWOULDBLOCK`
  is 35 on macOS, `EAGAIN` is 11 on Linux). Nothing in this path ever puts the
  socket into non-blocking mode, so this is the only thing that can raise
  `EWOULDBLOCK` here. That makes it safe to key on.
- The exact bytes you pack for the time limit, and the real limit they produce,
  depend on the platform. These numbers were measured, not assumed:

  | Pack (macOS, 3.13) | Result |
  |--------------------|--------|
  | `struct.pack("ll", 1, 0)` (16 bytes) | `BlockingIOError` at **2.00s** |
  | `struct.pack("ll", 2, 0)` (16 bytes) | at **4.00s** |
  | `struct.pack("li", 1, 0)` (12 bytes) | `OSError EINVAL` (rejected) |

  macOS accepts only the 16-byte form, and it applies double the value you ask
  for, every time. So `struct.pack("ll", 1, 0)` asks for one second and gives the
  two seconds we want. Linux takes the same bytes at face value. Because the
  number you pack does not map to the same real limit on both systems, the
  implementation must confirm the real limit with a test: fill a send buffer
  against a peer that never reads, and time how long the send takes to fail.

**Killing a stuck display and starting a new one.** When the send fails, the
worker catches `BlockingIOError` before the more general `OSError`, because
`BlockingIOError` is a kind of `OSError`:

```python
try:
    push(...)
except BlockingIOError:              # send-timeout: peer accepts but won't drain
    DisplayPaths().reap(timeout=2.0) # SIGTERM→SIGKILL the wedged owner
    DisplayPaths().ensure()          # respawn a fresh Display process
    client.close()                   # drop the dead fd so the next get() rebinds
    remark_all_dirty()               # re-mark every live scene, re-push fresh state
except OSError:                      # ECONNRESET/EPIPE: peer already dead
    client.close()                   # same: force a fresh connection
    reconnect()                      # nothing to kill — the peer is gone
    remark_all_dirty()               # the display may come back empty, so
                                     # re-push every live scene from the store
```

Both failure paths end by re-marking every live scene. A dead peer usually
means the display process is gone, and whatever display the next send reaches
is empty. Re-marking costs at most one redundant resend of scenes the display
already had — resending a whole scene is idempotent — and it removes the case
where a scene that was already clean before the crash stays missing forever.

A stuck display still answers new connection attempts, so `is_running()`
(`paths.py:139`) reports it as alive (`_probe` returns `ACCEPTING`,
`paths.py:129`). Simply reconnecting would just connect back to the same stuck
process. That is why we kill it first. To find which process to kill, we ask the
socket who owns it — its peer credential (`paths.py:238`) — and kill that.
Killing the stuck process and starting a fresh one is what we mean by *reap and
respawn*.

`reap()` kills the process and `ensure()` starts a new one, but the worker's
`DisplayClient` is still holding the file descriptor of the old, dead socket.
`is_connected` (`display_client.py:216`) would return True, so
`client_registry.get()` would not reconnect, and the next send would go to the
dead socket — the worker would only recover on the cycle after that. Calling
`client.close()` right after `ensure()` throws away the dead descriptor, so the
next `get()` connects to the new display straight away, in the same cycle.

After a restart the new display is empty, so the worker has to resend every
scene. To do that it needs a list of all the scenes, which the store does not
offer today. The design adds `HubDisplay.scene_ids()`, which lists the scenes
that still have elements in them. The worker marks each one dirty, and they are
all resent from the Hub's current state.

When the send times out it may have written part of a message to the socket.
That half-written message is thrown away along with the old socket, so the new
connection starts clean and never has to recover a garbled stream. Because the
send gives up after about two seconds, it releases `_lock` then rather than
holding it forever. It does hold that lock for those two seconds, and the
listener thread needs the same lock for its `recv` (`display_client.py:496`,
`:408`), so the listener pauses for those two seconds too. The agent is not
affected: the tools that change the screen hold no lock on the display and never
touch this socket. That is the point that matters; the listener catches up as
soon as the send returns.

While the display is being killed and restarted, tools keep marking scenes dirty
as usual. Once the new display is up, the worker sends the latest state. None of
the tools wait for any of this.

**Only the worker writes to the display, apps included.** `_on_beads_browser`
starts `BeadsBrowser().render(client)` on a background thread
(`clients.py:240-252`, `apps/beads.py`), and that render writes to the display
directly. That makes it a second writer, which contradicts the rule that only the
worker writes to the display. So a Hub-side app should behave like any other
tool: it changes `HubDisplay` and calls `replicator.mark_dirty(scene)`, and the
worker does the actual send. Then there is one writer, one connection, and one
send with a time limit — no app has its own path to the display with an
unlimited send.

**What happens to pending changes at shutdown.** When luxd shuts down cleanly,
the worker makes one last attempt to send whatever scenes are still marked dirty,
using the same time-limited send, and then stops. If the display is already stuck
or gone, that send fails within about two seconds and shutdown continues.
Shutdown never waits on a dead display. Losing that last frame does not matter,
because the process is exiting anyway.

### `recv` drains, never blocks

`recv` loses its `timeout` parameter and takes whatever is waiting without
blocking:

```python
@mcp.tool()
def recv() -> str:
    message = next_event(_connection_id(), timeout=0.0)  # get_nowait
    return "none" if message is None else f"event:{message.topic}:{...}"
```

`next_event(timeout=0.0)` (`tools/inbox.py:64`) returns the next queued
`ObserverMessage`, or `None` if there is none, and it returns at once. The inbox
is a `SimpleQueue` held in memory, so this is just a memory read. An agent that
used to call `recv(timeout=N)` and wait now checks again on its own schedule.

### Introspection: Hub-mediated, bounded, read-only

Introspection is how an agent checks what the running system actually did. Each
of these tools calls a query on the Hub. The Hub decides where the answer is —
its own store, or the display — and when it is in the display, the Hub reads it
over its one connection and passes it back. The tool never connects to the
display itself.

- **Answers from the Hub's store, with no trip to the display.** `inspect_scene`
  and `list_scenes` come straight from `HubDisplay`.
- **Answers only the display has, which the Hub fetches over its one connection
  with a time limit.** `get_display_info` (backend, frame rate, process id,
  uptime), `list_recent_events`, `list_errors`, `list_clients`, `list_menus`,
  `get_theme`, `get_window_settings`, and `ping` all live in the display. The Hub
  reads them for the tool.
- **Both in one call.** A single Hub query may combine store data with a read
  from the display — for example, comparing the scene tree the Hub holds against
  the widget state the display is drawing — as long as each read from the display
  has a time limit.

`screenshot` is the clearest example of a read that has to reach the display: it
needs the actual pixels. The Hub reads them over its one connection and hands the
tool a PNG, with a time limit, changing nothing. It does not work today — it
returns an error instead of a PNG (bead `lux-olgj`). It is described here to show
the shape the category takes once it is fixed, not as something that works now.

The rule for every read is the same. Each read from the display uses the query
connection, with a time limit on both the receive (`_recv_timeout`) and the send
(`SO_SNDTIMEO`), and returns a plain `"timeout"` or `"not running"` instead of
hanging. A read never changes anything, and it never kills the display; that is
the worker's job alone.

There is exactly one connection between the Hub and the display. Both the
worker's sends and introspection's reads use it, taking turns on its `_lock`. So
a read may have to wait for one send already in progress — at most about two
seconds. That is fine: reads are not on the path an agent's screen changes take,
and they only read. The design does not add a second connection just for reads.

**What this changes from today.** Right now the `_query_tool` tools
(`tools/connection.py`) call `client_registry.get().query(...)` on the tool
thread. They do use the Hub's own `DisplayClient`, but they reach around the Hub
rather than going through a Hub query. The design turns introspection into a
proper Hub query. There is no way around the Hub and no second path to guard —
the same one connection, but owned and controlled by the Hub. This replaces the
current reach-around.

### The MCP idle backstop

No tool on the agent's path waits on display I/O any more, so the server's idle
timeout never cuts off real work. Keep it only as a safety net: if a later change
accidentally puts a blocking call back on that path, the timeout still stops it.
Around 30 seconds is plenty. It is no longer part of how we budget latency.

## Failure mode replayed

The 38-minute `clear`, against this design:

1. The agent calls `clear()`. The tool empties the Hub's store
   (`HubSceneWriter.clear`, in memory) and calls `replicator.mark_cleared()`. It
   returns `"cleared"` in microseconds. The agent is free again as soon as the
   Hub has the change.
2. The worker wakes, picks up the clear, and sends a `ClearMessage` with the
   time-limited send. The display is stuck, the buffer fills, and after about two
   seconds the send raises `BlockingIOError` — on the worker's thread, not the
   agent's.
3. The worker catches `BlockingIOError` before `OSError`. It kills the stuck
   display with `DisplayPaths.reap` (SIGTERM, then SIGKILL, found by peer
   credential), starts a new one with `ensure()`, and calls `client.close()` so
   the next `get()` connects to the new process. It then marks every scene dirty
   again with `remark_all_dirty()` (using `HubDisplay.scene_ids()`) and resends
   the current state — empty, since we just cleared — all in the same cycle.
4. What the agent saw: the store update, which takes microseconds. The 38-minute
   hang cannot happen by design, because no send to the display sits on the path
   the agent's call takes.

## Implementation notes / breaks to handle

- **Return strings change from `ack:` to `shown:`.** `show`, `show_table`, and
  `show_dashboard` all wrap `show()`, and they, along with `update`, now return
  `"shown:<id>"`, because no ack is waited for. This changes every saved `ack:*`
  snapshot in the `show-*`, `show_table-*`, and `show_dashboard-*` families
  (checked by `make snapshot-parity`) and the `ack:` marker in `tests/CLAUDE.md`,
  so regenerate them. Do not keep `"ack:"`; nothing waits for an ack any more, so
  the word would be wrong. `update` (`tools/tools.py:418`) already returned an
  `"ack:"` it never waited for; rename it in the same change.
- **`clear` behaves differently.** It no longer checks `is_running()` and no
  longer sends to the display on the tool thread, and it always returns
  `"cleared"`. This changes `clear-not-running.json` and `clear-running.json`, so
  regenerate them.
- **Callers that pass `recv(timeout=)`.** `tests/test_tools.py:1970` and `:1976`
  call `recv(timeout=1.0)` and `recv(timeout=0.1)`. Update them when the
  parameter goes away.
- **The `lux show beads` CLI** (`show.py:41-51`) is a separate entry point that
  talks to the display itself and treats `ack is None` as the display being down.
  Since the send no longer waits for an ack, move its check to
  `DisplayPaths().is_running()` before it sends; the `SO_SNDTIMEO` limit also
  protects its send. It never kills the display — only the Hub's worker does that.
- **A probe test must pass before merge.** Write a test that fills a send buffer
  against a peer that never reads and times how long the `BlockingIOError` takes.
  It must confirm the real limit is at most about 2.5 seconds on the CI machine,
  because the number you pack does not mean the same thing on every platform.
- **Two new methods on `HubDisplay`.** One is a read/write lock: paths that
  change the store take the write lock, and the worker takes the read lock to
  copy `scene_roots` out. The other is `HubDisplay.scene_ids()`, which lists the
  live scenes so the worker can mark them all dirty after a restart. The migration
  has to add both.
- **The beads app moves to the worker.** `BeadsBrowser.render` (`apps/beads.py`,
  `clients.py:240-252`) changes from writing to the display through `client` to
  changing `HubDisplay` and calling `mark_dirty`, so that only the worker writes
  to the display.

## Concurrency verification (z-spec — required)

The worker adds real concurrency: a background thread, a changed-scene signal
touched by several threads, a read/write lock on the store, and killing and
restarting the display while other threads are changing the store. This is
exactly the kind of concurrent, lock-based code the project's z-spec guidance
requires us to model-check rather than only test. Before merge, model-check the
following:

- **The invariants hold and there is no deadlock**, across every interleaving of
  the worker, the mutation threads, and the kill-and-restart path. Show that the
  two locks — the store's read/write lock and the client's `_lock` — are always
  taken in the same order, so they can never form a cycle.
- **The model reproduces the real bug.** Remove the store lock from the model,
  and ProB should find the race: the worker reading the store while a mutation
  thread changes it, giving a changed-size error or a half-read list of roots.
  With the lock in place, ProB should find no such trace. A model that cannot show
  the bug it is meant to guard against is too vague to trust.

This verification is done. The spec is `docs/hub_replicator.tex`, checked
exhaustively with ProB — all invariants hold, no deadlock, and the
lock-removed variant reproduces the torn read. It also caught two defects in
an earlier draft of this design: the clear was ordered after the batch (a
`clear` → `show` burst lost the show), and the dead-peer path did not re-mark
scenes. Both fixes are folded in above. The derived test partitions are in
`docs/hub_replicator_coverage.md`; the implementation fills them. Re-run
`fuzz` and the model-check whenever the modeled behavior changes.

## Out of scope

- Making `clear` affect only the caller's scenes, for the many-user case. Today
  `clear` (`tools/tools.py:561`) clears everything on screen; scoping it is a
  separate change.
- Sending only the differences instead of the whole scene. We still resend the
  whole scene; the worker combines resends but does not make them smaller.
- Moving the `lux show` CLI, or other entry points that talk to the display
  directly, onto the Hub. They stay as they are; this design only puts a time
  limit on their send.
- `DisplayClient.poll_event` and the other blocking waits that in-process apps
  use. Those are not MCP tools, so they are outside this design.
- A watchdog inside the display for its own event loop. This design limits how
  long the Hub waits on a stuck display; making the display notice when it is
  stuck is a separate problem.
