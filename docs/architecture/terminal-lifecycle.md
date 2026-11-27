# Terminal session lifecycle, namespace and menu

Status: ratified, revised by DES-103; the daemon unit it describes is
implemented (PL-1217; epic PL-1213).
Formal model: [`docs/terminal_lifecycle.tex`](../terminal_lifecycle.tex), with
four fidelity variants beside it.

## Abstract

A terminal is a program held by `luxd-pty`, shown by a Hub scene, painted by a
Display replica. Today nothing connects the three lifetimes: after `exit` the
daemon's session is dead, the scene stays, and the Display's replica is cached
forever by name. This document makes the lifecycle one state machine with one
owner per transition, makes exit remove the session and its frame, makes
"attach" mean resume only, and shows that N terminals on M hosts need no new
menu and almost no new mechanism.

## Decisions consulted

| ADR | How this design uses it |
|---|---|
| DES-022 | Frames and the World menu are the user's workspace; terminals are frames. Unchanged. |
| DES-037 | Model style: z-spec, ProB, fidelity variant. Followed. |
| DES-056 | A frame dies with its scene. Exit removes the scene, so the frame goes. Relied on. |
| DES-058 | A menu item is a session's callback. Kept: the menu gets two static callbacks, nothing per-session. |
| DES-059 | One menu model, two projections. Unchanged; no second menu source. |
| DES-061 | Menu entries are push-reachable. The helper holds a listen leg; "New terminal" stays under 100 ms because creation is a local socket call. |
| DES-063 | Applet species. Amended: the terminal helper is a machine-global applet that owns many scenes, created and removed at runtime. |
| DES-064 | Clients menu. Amended: the helper's submenu is named for its host, not `luxd-pty`. |
| DES-067 | Not affected (helper is kind `app`, no session pid). |
| DES-086 | Scene and frame ids are connection-scoped, so two hosts' helpers cannot alias even with equal ids. |
| DES-088 | Frame close is a visibility the user owns. Relied on: hiding a terminal does not end it. |
| DES-099 | A repeat click must not no-op. "New terminal" always creates, so it carries no `frame_id`; each terminal has its own frame id. |
| DES-100 | Frame titles read `<roster name> :: <title>`. With the helper named for the host, a terminal reads `pembroke :: Terminal 3`. |
| DES-101 | Not affected. |
| DES-107 | The Hub relays terminal commands to the helper and returns the reply; section 1 states what the Hub holds. |

Supersedes commit `9fb923b7` (respawn on reattach): respawn in the attach path
is exactly the silent swap that invariant I2 forbids.

## 1. Who owns what

| Process | Owns |
|---|---|
| `luxd-pty` | Shells, session ids, labels, the state of each session, removal. |
| Terminal helper (child of `luxd-pty`, a Hub client) | The Hub scenes and frames for terminals; the menu entries; the manager scene. Never touches a PTY. |
| Hub | Stores the helper's scenes; delivers clicks; carries a terminal command from a caller to the helper and the helper's reply back (DES-107). Holds no terminal state: no session, id, label, launcher or list. |
| Display | One replica per terminal element. Never creates a session. |

The helper is a *client* of its daemon, over the same local socket the Display
uses, authenticated by same-user peer credentials.

The Hub's part in a command is a relay. The helper registers the service
`terminal` for its host. A caller's `new`, `ls`, `open`, `rename`, `kill` or
launcher request is checked against its typed shape, sent to the helper over
the helper's listen leg, and the helper's reply or refusal is returned. The
helper asks its daemon; the daemon decides, including whether
`allow_runtime_launchers` permits a launcher to be added. If the helper does
not answer, the caller gets `timeout`, `provider_lost` or
`provider_unavailable`, and no terminal state changes in the Hub, because it
holds none. The relay core knows only a service name, an operation name and an
opaque payload; the typed terminal request and reply shapes live in the
`commands/` front door that DES-087 requires on every surface.

## 2. Identity

A session has an **id** and an optional **label**.

- The id is daemon-assigned and opaque: `t<boot>.<n>`, `boot` a random value
  fixed at daemon start, `n` a counter. An id is never reused, not even after a
  daemon restart. It plays the role of `SHELL` in the model. The existing
  session-name regex already admits it.
- The label is what a person calls it: `work`, or `Terminal 3` by default.
  Labels are unique among live sessions on a host. This is the operator's
  "a name maps to at most one live shell per host", enforced where the shell
  lives.
- Every scene element, every `attach`, every replica is keyed by **id**.
  Resolving a label to an id happens once, in the helper or CLI, at the moment
  a person types it. After that a stale reference cannot name a different shell.

## 3. State machine

Session states in the daemon: `running` and `exited`, then removed. (The
existing `failed` and `closed` states are internal cleanup states and stay.)

| Transition | Trigger | Owner | Effect | Who learns, and how |
|---|---|---|---|---|
| new | `new` request (menu click, CLI, manager scene) | daemon | Spawn shell, assign id, register label. Fails if the label is live or the limit (16) is reached. | Watchers get `created`. The requester gets the id in the reply. |
| show | `created` event | helper | Install scene `terminal-<id>` in frame `terminal-<id>`. | Hub pushes the scene; Display builds a replica and attaches. |
| resume | Display (re)attaches by id | daemon | Attach a viewer to the running session; send snapshot. Refuses an unknown id. Never spawns. | Failure is non-retryable: the replica shows `unknown session` and stays until its scene goes. |
| exit | shell ends, or `kill` | daemon | State `exited`; every viewer gets `CLOSE{reason: exited}`; watchers get `ended`. | Replica goes `EXITED` (today's behavior); helper acts next row. |
| remove frame | `ended` event | helper | Clear scene `terminal-<id>`; DES-056 removes the frame. | Hub pushes the removal; Display drops the replica (section 5). |
| remove session | every viewer has been sent `CLOSE` (or has gone) | daemon | Delete from the session map; the label is free. Does not wait for the helper. | Nobody needs to learn: the id is dead. |
| hide | user clicks the frame close | Display | Visibility only (DES-088). The replica and the session stay. | None; the Windows menu lists the hidden frame. |
| reopen | Windows menu, or manager scene `Open` | Display / helper | `raise_frame`. | None. |
| viewer reconnect | socket drops and returns | Display | Replica goes `DISCONNECTED`, then re-attaches by id; if the session is gone, it fails as in resume. | Status line. |
| watch lost | helper's watch socket drops or overflows | helper | Re-dial; reconcile (below). | None. |
| daemon restart | supervisor | daemon, helper | Every shell the restart can end ends (SIGHUP, then SIGKILL to the shell's process group after a grace period); a shell that survives SIGKILL, such as a process in uninterruptible I/O, keeps running, and the daemon logs its pid and token and exits with a failure status (DES-107). New boot value. The helper restarts with the daemon. | Replicas go `DISCONNECTED`, then fail on re-attach (`unknown session`). Departure/lease expiry (30 s) releases old ownership but does not remove frames; old-instance removal is an implementation gap (section 7). |

**Reconcile (`HelperList`, then `HelperSync`).** On every connect of the watch
socket, and after every overflow, the helper sends `list` only after the daemon
acknowledges its `watch` subscription, not merely after the socket connects.
This subscription barrier prevents an exit between connect and subscribe from
being missed. It buffers events while acquiring and applying the list.
`HelperList` records a snapshot of the running sessions; creations and exits
can occur before `HelperSync` applies it. Application adds buffered creations
and removes buffered exits from that snapshot, releasing replicas whose scenes
are gone or changed. An exit wins over a creation for the same id. The list is
the authority at acquisition, not a live read at application; buffered events
bring it up to date. Watch loss invalidates a pending snapshot and requires
another reconcile. This is why a lost event cannot strand a frame.

**The watch.** A new control request `watch` turns a connection into an event
subscriber. The daemon queues `created` and `ended` events per watcher with a
bounded queue; overflow drops the watcher, which re-dials and reconciles. No
event carries content, only `{event, session, label}`.

### Invariants

Numbers match the model.

- **I1.** A scene is attachable (names a running shell), or its `ended` notice
  is in flight, or the helper is known out of sync.
- **I2.** A replica streams from the shell its element names. A resume never
  swaps in another.
- **I3.** At most one live shell per name, and per id.
- **I4 (transient).** After a daemon restart a replica may be `ready` for a
  vanished id until its stream drops. This is allowed. What is not allowed is an
  exit leaving it, which `remove session` prevents by sending `CLOSE` first.
- **I5.** No deadlock.
- **I6.** No cached replica of a dead shell shadows a scene that names a live one. Ids are never reused and a replica is released when its element goes (section 5).

## 4. Namespace and menu

### Hosts

Each `luxd-pty` generates a unique daemon instance id at startup and reports
it in hello/list responses. Its helper includes that instance id in its Hub
identity, alongside `kind=app` and `name=<host label>`, so distinct daemons get
distinct connection ids even when their host labels match. The label is
display-only: the Clients submenu name and frame-title prefix.

Increment 2 must add the instance id to `ClientIdentity`, carry it through
`ClientHeaders` serialization/parsing, and include it among the fields hashed
by `connection_for` (`connection_identity.py`); declaration alone is not enough.
Today that function hashes only `kind`, `name`, `repo` and `agent`.
The helper uses REST for menu registration and scene writes (`LuxClient`)
and the WebSocket `/ws` listen leg for callbacks, events and renewal
(`LuxHubClient`), not MCP. Both legs must carry the same instance field:
`RestCaller` and `HubListenTransport` already share `connection_for`.

```text
Clients
  pembroke            <- helper of the luxd-pty on pembroke
    New terminal
    Terminals
  local-mac           <- helper of the local luxd-pty
    New terminal
    Terminals
```

No new menu, no Hosts menu. DES-064's collision numbering can show
`pembroke` and `pembroke (2)` only once the instance-bearing identities
distinguish those connections; the shared label alone does not do that.
The host label defaults to the machine hostname and is
overridable (`LUX_PTY_HOST`). The frame title falls out of DES-100:
`pembroke :: Terminal 3`.

### Scenes and frames

| Thing | Value |
|---|---|
| scene id | `terminal-<id>` (stored as `<connection>\x1f<id>` per DES-086) |
| frame id | `terminal-<id>` |
| element | `terminal` with `session=<id>`, and from increment 3 `host=<daemon instance id>` |
| title | the session label |
| manager scene id | `terminals` (one per helper) |

One terminal, one scene, one frame. `New terminal` registers no `frame_id`
(DES-099): each click makes a fresh frame.

### The `Terminals` manager

A Hub-rendered table, one row per live session of that host: label, state,
`Open` (raises the frame), `Close` (kills the session). The buttons publish
topics (`terminal.open`, `terminal.close`, payload `{host, session}`, where
`host` is the daemon instance id) that the
helper subscribes to; the helper acts. This is the only place a user sees all
sessions, including any whose frame is hidden, and the only UI path to `kill`.
The table is rebuilt from the same list the helper reconciles from.

### Hosts across daemons (increment 3)

The element gains `host: str`, carrying the daemon instance id, never the host
label (`""` selects the configured local daemon instance). The Display holds
one `RemotePool` per instance, built from a Display-side map
`daemon instance id -> socket path`
(config file; the Hub never sends a path to the Display, since that would let
the Hub name an arbitrary socket for the Display to connect to). Replica key is
`(instance, session)`. A restart generates a new instance id; routing must
learn that id rather than treating an old instance as the new daemon.
Session ids are per-daemon and scenes are per-connection. These are design
contracts for the later units, not wire-type changes in this PR.

## 5. How the Display learns

Today it learns only the stream's `CLOSE`. Two additions:

1. The scene removal that follows `ended` is the signal. When a terminal
   element leaves the Display's scene replica, the replica calls
   `RemoteSessions.release(session)`, which closes and forgets the
   `RemoteSession`. The pool is no longer immortal: a replica lives exactly as
   long as an element names it.
2. `RemotePool.get` stops resurrecting a cached replica in a terminal phase
   (`FAILED`, `CLOSED`) for an element that is still present. It keeps the
   failure status on screen. Re-attaching is a new scene's job, never a retry
   loop's.

A hidden (closed-by-user) frame keeps its replica attached; a live session
keeps streaming and keeps its scrollback.

## 6. Daemon CLI against terminal CLI (PL-1219)

Mirror `lux hub` / `luxd-hub` and `lux display` / `luxd-display`:

- `lux pty install | uninstall | start | stop | restart | status | doctor` —
  the daemon, on this machine.
- `lux terminal new [--label L] [--host H] | ls | open <label-or-id> | kill <label-or-id>` —
  sessions.

`lux terminal enable | disable | restart | status` are removed, not aliased
(no shims on any surface). `install` replaces `enable` and `uninstall` replaces
`disable`. `status` splits: `lux pty status` reports the daemon;
`lux terminal ls` reports sessions.

## 7. Increment 1 write set (PL-1214)

The three code units are independent after the wire types land; run them in
parallel worktrees.

**Wire (first, small).** `wire/stream/new_request.py` holds `NewRequest`
(label, launcher, cols, rows). It names a launcher and carries no command line
(DES-103 decision 9); `wire/stream/launcher_name.py` validates the name.
`wire/stream/session_events.py` holds `WatchRequest` and `SessionEvent`
(frozen dataclasses, `to_dict` / `from_dict`). `wire/stream/control.py`
registers the codecs.
`AttachRequest` keeps its shape; its meaning becomes resume-only.

**Daemon unit.**

- `pty/core.py`: `acquire` is deleted. In its place `create(NewRequest)` and
  `attach(id)`. The respawn branch goes.
- New `pty/session_ids.py`: `SessionIds` (boot value plus counter, produces
  ids).
- New `pty/session_labels.py`: `SessionLabels` (uniqueness among live
  sessions).
- New `pty/session_watchers.py`: `SessionWatchers` (subscribed peers, bounded
  queues, overflow drops).
- New `pty/exited_sessions.py`: `ExitedSessions` (removes an exited session
  once every binding has been sent `CLOSE`).
- `pty/control_dispatch.py`: handles `new` and `watch`; attach no longer
  creates.
- `pty/stream_output.py`: calls `ExitedSessions` after a flush.
- `pty/session.py` and `pty/session_state.py`: carry `label`; `describe()`
  returns it.

**Helper unit.**

- New `pty/daemon_client.py`: `DaemonClient` (new, list, kill, watch over
  `TerminalConnection`).
- New `pty/session_watch.py`: `SessionWatch` (watch loop, reconnect, reconcile).
- New `pty/terminal_scenes.py`: `TerminalScenes` (builds the `RenderRequest`
  for one session, the scene id, frame id).
- New `pty/terminal_manager.py`: `TerminalManager` (the `Terminals` table and
  its button topics).
- `pty/menu_projection.py`: shrinks to registering `New terminal` and
  `Terminals`, and routing clicks; the hard-coded `luxd-pty-terminal` goes.
- `pty/menu_clients.py`: identity name becomes the host label (new
  `pty/host_label.py`, `HostLabel`).
- `pty/menu_listener.py`: wires the watch.

**Display unit.**

- `display/terminal/remote_pool.py`: `release(name)`; terminal-phase replicas
  are not resurrected.
- `display/terminal/remote_sessions.py`: facade for `release`.
- The scene replica's element-removal path (`display/replica/scene_replica.py`,
  `scene_index.py`, `frame_book.py` forget paths) calls the release for
  terminal elements. The implementer picks the one seam; it must cover scene
  clear, frame dispose and replace.

**Tests (written first; each fails on today's code).**

- `tests/pty/test_core_lifecycle.py`: new, resume, unknown id refused, exit
  removes after `CLOSE`, label unique, id never reused, limit.
- `tests/pty/test_session_watchers.py`: events, overflow drops the watcher.
- `tests/pty/test_session_watch_reconcile.py`: lost events then sync equals
  the daemon's list.
- `tests/pty/test_exit_removes_frame.py`: a real `luxd-pty` and a stub Hub;
  `exit` leaves no scene (this is the user's reported defect, end to end).
- `tests/display/terminal/test_remote_pool_release.py`: element removed means
  replica released; a hidden frame keeps its replica.
- Two regression tests replaying the model's fidelity traces (section 8).
- The existing respawn-on-reattach tests are replaced, not kept.

After a daemon restart, the new instance has a different helper connection id.
`HubSceneWriter.clear` only removes elements owned by the caller, so the new
helper's first reconcile cannot clear the old instance's frames. Today a
WebSocket disconnect detaches the listen leg but retains the session lease;
explicit departure or expiry of the helper's 30 s lease runs
`ClientLifecycle.depart`/`depart_lapsed` and releases ownership, registry,
callbacks and subscriptions. **That cleanup does not remove scenes or frames**:
`OwnerTracker.release_all` discards ownership records and leaves elements
installed (`hub/lifecycle.py`). Actual removal needs an explicit
element removal or unowned-claim reclaim; neither is performed by the new
helper's owner-scoped clear. Automatic removal of old-instance terminal
frames therefore remains an implementation gap, not a guarantee of lease
expiry or first reconcile. The later lifecycle unit must resolve it without
aliasing instance identities.

Increment 2 adds the daemon instance id (generated at daemon start and reported
in hello/list), includes it in the helper's Hub identity, and extends
`wire/model/client_identity.py`, `wire/model/identity_headers.py` (both directions), and
`connection_identity.py`'s hashed fields so REST and WebSocket listen resolve
the same instance-aware connection id. It adds the display-only host label
and tests: two otherwise identical, same-labelled declarations with different
instance ids yield distinct `connection_for` ids; the same instance round-trips
over REST and WebSocket to the same id, and separate connections receive
numbered Clients submenus. Increment 3 adds the
instance-valued `host` field to the element, the Display's instance-to-socket
map and per-instance pools, `(instance, session)` replica keys, and a
same-labelled second-daemon routing test. The host label never keys routing.

## 8. Formal model

[`docs/terminal_lifecycle.tex`](../terminal_lifecycle.tex). Reproduce every
result with `scripts/verify_terminal_model.sh` from the repo root (it runs fuzz
on all four files, then
`probcli FILE -model_check -nodead -p DEFAULT_SETSIZE 2 -goal '<predicate>'`;
a plain `-model_check` passes on the buggy variants too, because they violate
safety goals, not deadlock-freedom). `make check` runs the verifier through
`make check-models`, which also runs in CI (`.github/workflows/models.yml`).

The model has a `replica` map (the Display's cache, keyed by name and shell)
and a `used` set (names ever issued). `HelperEnded` and `HelperSync` release
every replica whose scene is gone or changed; `DropReplica` is the same
release on its own. `listed` holds the acquired snapshot and `sync=listing`
marks the interval before buffered-event replay. Individual helper event
handlers wait until replay completes; daemon operations remain enabled.
`watch` explicitly tracks `wnone`, `wpending` and `wacked`.
`HelperSubscribe` sends the request, `HelperWatchAck` acknowledges it, and
only `wacked` buffers daemon events and enables `HelperList`. Initialization,
watch loss and daemon restart require subscription and acknowledgment before
listing again. The model covers one daemon, not cross-host/instance routing.
`stalled` holds the names of sessions that have a viewer which has stopped
taking output. `ViewerStalls` adds a name. `DaemonRemove` refuses a stalled
name, because CLOSE follows a viewer's last byte and cannot be sent while the
viewer holds unsent output. `FinishDeadline` is the timeout transition: a
finished session with a stalled viewer has its unsent output abandoned
(`ViewerFlow.abandon_unsent`, called by `SessionRoster.sweep` once the 30 s
grace of `FinishDeadlines` is spent), CLOSE goes out and the name leaves
`stalled`. The timer is abstracted to the guard `dstate(n)=exited`. A daemon
restart clears `stalled`.
`ReplicaAttach` requires a running shell, and `ReplicaRefused` covers exited
shells as well as absent or mismatched ids. `HelperLoseEvents` cannot fire
when the watch is already lost and both event sets are empty.
The intact model has 10278 states at set size 2 and no deadlock.

Goals, each an unreachable bad state in the intact model:

- I1, visible implies attachable or being removed:
  `#n.(n:dom(scene) & sync=synced & not(n:dom(daemon) & daemon(n)=scene(n) & dstate(n)=running) & (n|->scene(n)) /: endedEv)`
- I2, resume never swaps:
  `#k.(k:dom(bound) & bound(k)/=prj2(NAME,SHELL)(k))`
- I3, one live shell per name (by construction; a sanity check):
  `#(a,b).(a:dom(daemon) & b:dom(daemon) & a/=b & daemon(a)=daemon(b))`
- I6, no stale replica shadows a live scene:
  `#n.(n:dom(scene) & n:dom(daemon) & daemon(n)=scene(n) & dstate(n)=running & #s.(s:SHELL & (n|->s):dom(replica) & s/=scene(n)))`
- I7, when synced with no pending events, every running session has a scene:
  `sync=synced & createdEv={} & endedEv={} & #n.(n:dom(daemon) & dstate(n)=running & not(n:dom(scene) & scene(n)=daemon(n)))`
- I8, every cached replica matches a current scene element:
  `#(n,s).(n:NAME & s:SHELL & (n|->s):dom(replica) & not(n:dom(scene) & scene(n)=s))`
- L1, no finished session outlives its deadline: whenever a finished session
  is held by a stalled viewer, `FinishDeadline` is enabled for it. A CTL
  property, not an unreachable state:
  `AG({#n.(n:dom(daemon) & dstate(n)=exited & n:stalled)} => EF(e(FinishDeadline)))`.
  The state it guards (`#n.(n:dom(daemon) & dstate(n)=exited & n:stalled)`) is
  reachable in the intact model, so the property is not vacuous; the deadline
  is the only transition that releases it.

I8 is a safety check because scene removal and replacement release replicas
atomically in this model. It catches an orphan without waiting for name reuse;
`DropReplica` does not make a stranded copy an acceptable transient.

| Variant | Removes | Goal reached |
|---|---|---|
| `terminal_lifecycle_cache_leak_buggy.tex` | Replica release, and the never-reuse guard | I6 (the operator's "exit, then nothing ever") and I8 |
| `terminal_lifecycle_exit_leak_buggy.tex` | Helper clears scene on `ended` | I1 |
| `terminal_lifecycle_swap_buggy.tex` | Resume checks the shell, and the never-reuse guard | I2 and I6 |
| `terminal_lifecycle_no_deadline_buggy.tex` | `FinishDeadline` (its guard is false) | L1 |

Results from the last run: intact model, I1/I2/I3/I6/I7/I8 not found over all 10278
states; L1 holds. Cache-leak I6 and I8 found; exit-leak I1 found; swap I2 and I6 found.
No-deadline L1 fails: `DaemonNew`, `ShellExit`, `ViewerStalls` reach an exited
session held by a stalled viewer with no transition that releases it, so a
stalled viewer pins the session and its slot forever.
I7 is also not found on all four fidelity variants. A local, uncommitted
mutation that omits `createdEv` from `HelperSync` reaches I7: acquire an empty
list, create a session, then apply the list without its buffered creation.
A second local mutation removing the acknowledgment guard from `HelperList`
also reaches I7: list before subscribing, create sessions without event
buffering, then apply the stale snapshot.
Deadlock check clean on all five files. State counts to the goal vary with
search order.

The latest cache-leak counterexample ends with an attached replica of `(n,s1)`:
`HelperLoseEvents`, `HelperSubscribe`, `HelperWatchAck`, `HelperList`,
`ShellExit(n)`, `ReplicaEnds(n,s1)`, `HelperSync` (scene cleared, replica
kept), then `HelperLoseEvents`, `HelperSubscribe`, `HelperWatchAck`,
`HelperList` (empty snapshot), `DaemonRemove(n)`, `DaemonNew(n,s2)`,
`HelperSync` (buffered creation installs the new scene, old replica kept).
The scene names a running shell and the
cached replica of the dead one is still keyed to the name, so the Display
shows the dead screen and never re-attaches. Today the name is the constant
`luxd-pty-terminal`, so every second terminal reproduces it without a restart.
The design closes it two ways, and the model needs both: ids are never reused
(the `used` guard), and a replica is released when its element leaves the
scene (section 5).

Limits: `DaemonRemove`'s guards (no `ready` replica, no stalled viewer)
abstract "`CLOSE` has been delivered to every viewer"; the daemon cannot see
replica phase, it sees its own bindings. The model has one stalled flag per
session, not one per viewer, and the 30 s grace is a guard, not a clock. The macOS child reap and the PTY itself are outside the
model. Re-run the checks when the lifecycle code changes.

### Releasing a replica on the shared connection

[`docs/terminal_release.tex`](../terminal_release.tex) models one luxd-pty
connection shared by many replicas, each on its own channel, with the daemon's
frames and attach replies in flight in one ordered stream. Its goals: R1, no
unreleased replica is ever dropped because of a frame for another channel
(`collateral/={}`); R2, no connection error at all (`health=failed`); and
deadlock freedom. The intact model (released-channel memory, cancelled-attach
memory, and a late attach reply that also marks its channel released) has 1194
states and reaches neither goal. Three buggy variants reach both: no
released-channel memory (`terminal_release_channel_buggy.tex`), no
cancelled-attach memory (`terminal_release_attach_buggy.tex`), and a late reply
that closes the channel but does not remember it as released
(`terminal_release_late_reply_buggy.tex`). The last is the first revision of
the fix: the daemon queues snapshot data behind the attach reply, so those
frames reach the Display after the late reply was consumed. Reproduce with
`scripts/verify_terminal_model.sh`.

[`docs/terminal_reopen.tex`](../terminal_reopen.tex) adds the attach request
queue, the daemon's one-viewer-per-session rule (`ViewerBindings.add`
rejects a second attach of a name on a peer, non-retryably) and the idle
pump, at set size 3. Goals: F, no replica ends stuck `failed` (a reopened
name rejected as a duplicate while a cancelled attach for it is unanswered);
O, no daemon viewer binding survives quiescence (last release with an
unsent attach); C, no collateral disconnect; D, deadlock freedom. The
design the model proves safe closes the connection when the last replica is
released, and holds a reopened name's attach back until the reply to its
cancelled attach is read. Each measure alone fails: closing the idle
connection alone reaches F, deferral alone reaches O, retrying the duplicate
rejection alone reaches O, and the committed code reaches both.

## 9. Working answers to the operator questions

The design proceeds on these working answers, with Jim's explicit
same-named-host decision recorded in item 2.

1. **Frame close box hides the terminal.** The session lives and the Windows
   menu reopens it (DES-088; tmux detach). The `Terminals` manager holds the
   only kill, so one stray click cannot end a long job.
2. **Hosts are Clients submenus named for the host**, not a new `Hosts` menu.
   A second menu source is the divergence DES-059 exists to prevent.
   Jim's decision: a unique daemon instance id distinguishes helper Hub
   identities and keys Display socket routing and replicas; host labels are
   display-only, including when two daemons share the same label.
3. **After a Hub restart every running session's frame reappears.** The user
   closes the ones they do not want. The alternative leaves a running shell
   with no window.

No question is asked about sequencing, CLI verb names, id format, wire shapes
or module layout; those are decided above.

## 10. ADR

DES-106 in `DESIGN.md` records the daemon side of sections 2, 3 and 5. DES-103
records the menu, naming, launcher and window decisions that revise sections 4
and 6.
