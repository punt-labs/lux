# Menu Model

**Status:** settled by operator rulings on 2026-07-29. This document once
proposed an abstract "capability" layer over menu items; that model is
withdrawn. A menu item is now a session's callback, and nothing more. Read
[target/target.md](target/target.md) first; on any conflict that document wins.
The file keeps its old name for history; the model it records is the
session-and-callback model below.

**Presentation superseded by [DES-064](../../DESIGN.md) (2026-08-02).** What a
menu item *is* — a client's callback, delivered to the client that registered it
— is unchanged. How the menu is *presented* is not: the flat one-submenu-per-
client bar this document describes became one top-level `Clients` menu holding
one submenu per live client, named for humans and numbered on collision, each
carrying the Hub's own `Details` command. Read DES-064 for the presentation.

This document describes what a Lux menu item is, what happens when the user
clicks one, and how the menu knows which repository the user means. It is
interaction design first and plumbing second. The thing that is broken is the
user's mental model, not a single function.

## The Problem

The operator's words, verbatim:

> What doesn't work is launching anything via Menu. And there is confusion about
> one menu per client and one menu per plugin which is active across many
> clients. I have 8 claude code instances running right now, and I see Lux and
> Beads Browser once. Which repo should the beads browser show? Unclear. The
> model is messed up.

The model is messed up because one menu item is being asked to carry three
different things at once, and it cannot.

### The three things a menu item conflates

**The action.** "Beads Browser" names an action the user wants to run. That is
the part the user thinks about — the verb on the menu.

**The session.** There are eight Claude Code instances connected right now. Each
one is a separate connection to the Hub, and each comes and goes on its own
schedule. Today the code makes a session the owner of a menu item, but it does
not treat that ownership honestly: the item is registered by a session yet is
shown as if it belonged to Lux itself.

**The context.** This is the repository the user actually cares about, and it is
missing from the model entirely. When the operator asks "which repo should the
beads browser show?", they are asking for the context. The current model has no
place to put it, so the answer is silent and wrong.

The settled model stops forcing one item to be all three. A menu item becomes
exactly one thing — a session's callback. The session that owns the callback
carries its own identity and its own lease, and that identity supplies the
context the menu is missing today. The Model section below gives the full shape.

## Why Launching Fails Today

There are two menu-launch paths in the code right now. One works. One does not.
The difference is the whole diagnosis.

### The one path that works: the built-in Beads Browser

At startup, luxd opens its own single connection to the display. On that
connection it does two things (`domain/hub/clients.py`,
`ClientRegistry._setup_apps`):

1. It declares the menu item `{"id": "app-beads", "label": "Beads Browser"}`.
2. It registers a Hub-side callback: when an event `("app-beads", "menu")`
   arrives, run `_on_beads_browser`.

When the user clicks "Beads Browser," the display sends a message back to luxd's
own connection. luxd's listener finds the registered callback and runs it. The
callback loads beads and installs the board into the Hub, entirely Hub-side. The
replicator paints it. It works because the handler runs on the Hub, on luxd's
own connection, and needs no agent to be listening.

But notice the context bug. The callback loads beads from `Path.cwd()` — luxd's
own working directory (`apps/beads.py`, line 59). luxd was launched by launchd
from some fixed, arbitrary directory. It is not any of the eight repositories
the user is working in. So the one working launch shows the beads of the wrong
repository, every time. This is exactly the "which repo?" confusion.

### The path that does not work: agent-registered tool items

An agent calls `register_tool(label, tool_id)`. This stores a menu item in the
Hub menu registry, keyed by the calling session's connection id
(`operations/menus.py`, `register_menu_item`). The replicator pushes it to the
display, where it appears under Applications. So far so good — the item shows up.

Then the user clicks it. The display sends a menu message back to luxd carrying
the `tool_id` and `action="menu"`, but no scene id — a menu item is not part of
any rendered scene. luxd's listener looks for a callback registered for
`(tool_id, "menu")`. The agent never registered one, and there is no API for an
agent to register a Hub-side callback. So the click falls through to the
fallback handler, `_hub_interaction_dispatch`. That handler's first act is to
resolve an element out of a scene — but there is no scene id, so it logs
"hub dispatch missing scene_id" and returns. The click does nothing.

The `register_tool` docstring promises "clicks arrive via recv()." That wiring
was never built. Even if it had been, it would require the agent to be sitting
in a `recv` poll at the moment of the click, which none of the eight instances
is doing. So a durable-looking menu item is bound to a session that is not
listening, and the click is dropped.

### What the display cannot know

There is one more fact that decides the whole design. The display is one screen
with one mouse. When the user clicks a menu item, the display has no idea which
of the eight sessions the click "belongs to." There is no per-session identity
at the point of a click. This is why a single "Beads Browser" item is
fundamentally ambiguous: the context cannot be inferred from who clicked,
because at the screen there is no "who." The context has to be carried by the
menu entry itself, decided when the entry is built, not guessed at the click.

## The Model

A menu item is a **callback**: a named action a session registers so that
clicking it fires that action back to the session that owns it.

The menu shows every callback that will actually work — the callbacks of
sessions whose lease has not expired, and nothing else. There is no abstract
capability sitting above the callbacks. If a callback is on the menu, a live
session stands behind it, ready to run it.

### A menu item is a callback

A callback has:

- an **id** the owning session chose, unique within that session.
- a **label** the user reads, for example "Beads."
- an **owning session**: the one session the click is delivered to. The callback
  lives exactly as long as that session's lease.

There is no separate "plugin capability" and no "context mode." The owning
session supplies both: the session's identity is the context, and the session's
lease is the lifetime. Every menu item is the same kind of thing — a callback
routed to its session — so the two-path split that fails today collapses into
one path.

### Sessions carry a lease

Each session declares a lease when it registers, and the lease length matches
the session's cadence:

- a cron client that beats every ten minutes declares a lease of about twenty
  minutes, so that two missed beats mean it is gone.
- a long-lived daemon declares a short lease, on the order of thirty seconds,
  because it is always connected and a lapse means it truly died.
- luxd's own built-ins are an ordinary app session with an effectively permanent
  lease. The built-in beads board stops being a special case in the code; it is
  just a session whose lease never runs out.

Any authenticated contact renews the lease — a cron beat, an MCP call, a ping.
There is no separate renew verb; staying in touch is what keeps a session, and
its callbacks, alive. When the lease lapses, the session's callbacks leave the
menu.

The lease lives in the one session registry that the identity design owns. That
design's first PR merged the registry; the lease is the registry's next field,
implemented in the identity train and consumed here. The menu model does not
introduce a second registry — it reads the one that already exists.

### Rendering: session ▸ callback, uniformly

The menu nests one way and one way only: session first, callbacks as its leaves.
Every session becomes one submenu labeled from its identity, and that session's
callbacks are the entries under it. This holds no matter how many callbacks a
session has — a session with one callback is a submenu with a single leaf, a
session with several is a submenu with several leaves. There is no case logic and
no count threshold that switches the shape.

> **RULED (operator, 2026-07-29):** "Would only do it one way: Session-name ->
> callback-name. No case logic."

The uniform nesting was chosen deliberately over count-dependent flattening. An
earlier revision special-cased a one-callback session into a flat labeled entry
("Beads — vox") and only nested when a session had several callbacks. The
operator struck that: the menu never flattens by count. The
eight-sessions-one-callback case renders as eight single-leaf submenus, by
design — "vox ▸ Beads," "lux ▸ Beads," "quarry ▸ Beads," and so on — not as eight
flat entries. One shape, every time.

The pretty name for each session comes from its `ClientIdentity` in the
registry: a display name and the repository it connects from.

This is the direct answer to "I see Beads Browser once, which repo?" The
repository is named on the submenu, so the user reads which repo an action
belongs to before opening it. Two callbacks that belong to two different sessions
never share a menu entry — each session is its own submenu, so they cannot be
merged. That merge is exactly the confusion the operator reported, and uniform
per-session nesting forbids it structurally.

## What Happens on Click

### The eight-sessions, which-repo scenario, walked

Here is the operator's exact situation, resolved step by step.

1. luxd starts as a session with an effectively permanent lease. It registers
   its own built-in callbacks — Settings, Windows, Help. There is no special
   beads path any more.

2. Eight Claude Code instances connect, from eight repositories — lux, vox,
   quarry, and so on. Each authenticates, registers itself in the one session
   registry with a `ClientIdentity` (name and repository) and a lease matched to
   its cadence, and registers its own Beads callback.

3. The menu nests one submenu per live session, labeled from the session's
   identity, with that session's callbacks as its leaves. Each of these sessions
   has exactly one callback, so each renders as a single-leaf submenu: "lux ▸
   Beads," "vox ▸ Beads," "quarry ▸ Beads," and so on. Eight sessions with a Beads
   callback each means eight single-leaf submenus. Nothing is collapsed. The user
   reads the repository off the submenu.

4. The user clicks "vox ▸ Beads."

5. The display sends the click to the Hub. The Hub fires a `CallbackInvocation`
   carrying `{session_id, callback_id}` — the vox session and its beads
   callback. The Hub knows the exact session because the menu entry named it. It
   is never inferred from "who clicked," which the display cannot know.

6. The invocation is delivered to the vox session and the vox agent runs the
   callback in its own repository. It runs `bd` in vox's directory and calls
   `show_table` to install the board. The board shows vox's beads, from vox's
   own working directory, with no `Path.cwd()` guessing anywhere.

The "which repo?" question is answered before the click, by nesting each
callback under the session that owns it, labeled from the identity the registry
already holds.

### Pickup is routed by how the session connects

The click always fires the same `CallbackInvocation {session_id, callback_id}`
at the Hub. How that invocation reaches the owning session depends on how that
session connects.

- **Persistent socket** — a daemon that holds a live connection, such as voxd's
  music player. The Hub pushes the invocation straight down the live connection.

- **MCP streamable-HTTP** — a Claude Code session on the streamable-HTTP
  transport. The invocation goes to that session's server stream or to a session
  inbox. Which of the two is the delivery spike's one open choice, named below;
  the routing itself is settled.

- **Periodic or cron client** — a client that connects in bursts over raw HTTP
  or through the `LuxClient` Python library, not continuously. The invocation is
  held in a queue and delivered on the session's next beat, as long as that beat
  arrives inside the lease. Past the lease it is dropped, with a visible notice
  rather than a silent loss.

This is the display's `PendingInteractions` discipline generalized to the Hub:
hold the interaction, deliver in order, bound it by the lease, and compensate
visibly when it cannot be delivered. The display already runs this pattern for
interactions it cannot deliver instantly; the Hub-side pickup is the same pattern
applied to callbacks.

### Withdrawal on expiry, and the click-versus-expiry race

When a session's lease expires, the Hub withdraws that session's menu
registrations and re-pushes the menu. The entries for a dead session leave the
bar, so the menu keeps showing only callbacks that will work.

There is a narrow race: the user can click an entry in the instant between the
lease expiring and the withdrawal re-push landing on the display. The operator
ruled for reasonable handling here, not a heavy locking mechanism. When the Hub
receives a click for a session whose lease has expired, it delivers a named
"provider is gone" notice — the entry belonged to a session that has since left.
It does not attempt to hold a lock across the display and the Hub to make the
race impossible; a clear notice on the rare lost click is the settled trade.

## The Flow, End to End

```text
Session
  declares ClientIdentity(name, repo) + lease, registers callbacks
        |
        |  register {session_id, ClientIdentity, lease, callbacks}
        |  (any authenticated contact renews the lease)
        v
Session registry  (owned by the identity design; lease is a field)
        |
        |  live sessions = those whose lease has not expired
        v
Menu build
  one submenu per live session, labeled from ClientIdentity,
  its callbacks as leaves; session -> callback, uniformly, no case logic;
  two sessions are never merged into one entry
        |
        |  menu replica, re-pushed on any change
        |  (including withdrawal when a lease expires)
        v
Display renders the menu; user clicks "vox -> Beads"
        |
        |  click
        v
Hub fires CallbackInvocation {session_id, callback_id}
        |
        |  routed by how the owning session connects
        v
Pickup
  persistent socket    -> push down the live connection
  MCP streamable-HTTP  -> server stream or session inbox   (spike names which)
  periodic / cron      -> held in queue, delivered next beat within the lease,
                          dropped with a visible notice past it
  lease already expired -> named "provider is gone" notice
```

## Registration and Ownership

A session registers its own callbacks, and the session's lease sets their
lifetime. There is only one kind of owner now: a session.

**luxd registers its built-ins as a session.** At startup luxd registers its own
callbacks — Settings, Windows, Help — as a session with an effectively permanent
lease. These are the items that must "appear once and always work," and they do,
because luxd's lease never lapses. luxd is not a privileged special case in the
code; it is a session like any other, with a very long lease.

**Each agent session registers its own callbacks.** A Claude Code session
registers the callbacks it wants on the menu, such as its Beads callback. They
are owned by that session, shown under that session's identity, and delivered to
that session on click. They leave the menu when the session's lease expires.

**Nobody registers a context.** The context is the session's own repository,
carried in its `ClientIdentity` and set when the session registers. A repository
appears on the menu because a session from that repository is connected, and it
leaves when that session's lease lapses.

Unregistration follows the lease. A session's callbacks are withdrawn when its
lease expires, on the same registry path that tracks the session. luxd's
callbacks are never withdrawn while luxd runs, because its lease never expires.

## What the Menu Bar Shows

The menu shows the live callbacks, nested session ▸ callback uniformly as above,
so the user sees which action belongs to which repository before clicking.

- **Built-in callbacks** — Settings, Windows, Help — appear as luxd's own
  session submenu. They are always present because luxd's lease never lapses.

- **Every session appears as one submenu** labeled from its `ClientIdentity`,
  with its callbacks as the leaves under it. "vox ▸ Beads" and "lux ▸ Beads" are
  separate submenus; they are never merged. The submenu carries the repository,
  so the user never has to ask which repo an entry means.

- **The shape does not change with the count.** A session with one callback is a
  single-leaf submenu; a session with several is a submenu with several leaves.
  There is no flat-entry special case for a lone callback — the operator ruled
  for one shape, no case logic.

- **A session that leaves takes its entries with it.** When a lease expires, the
  menu re-pushes without that session's callbacks. The user is never left with a
  clickable entry whose session is gone — except in the narrow race above, which
  is answered with the "provider is gone" notice.

There is no disabled-but-visible state and no "capability with no live context,"
because there is no capability that outlives its session. If no session offers a
callback, the callback is simply not on the menu.

## What Dies

**Session-scoped `register_tool` as it exists today** — a durable-looking item
whose click is dropped in the fallback handler. It is replaced by callback
registration whose click is delivered to the owning session over the pickup path
above.

**The per-session, file-descriptor-keyed menu bookkeeping in the display**
(`menu_manager.py`: `_menu_registrations`, `_menu_owners`,
`_sorted_app_clients`). After the Hub took over replication, the display sees
only luxd's single connection, so grouping items "by client" on the display is
fiction. Grouping by session belongs on the Hub, which owns the session registry
and its identities.

**The built-in beads browser's use of `Path.cwd()` to guess a repository.** The
repository is the owning session's own repository, carried in its identity and
run in that session on pickup. luxd never guesses a repository from its own
working directory.

**The stale promise in the `register_tool` docstring that "clicks arrive via
recv()."** Clicks arrive as a `CallbackInvocation` delivered by the pickup path,
not by an agent sitting in a `recv` poll.

This is not a shim. When the beads built-in and the agent tools move to the
callback model, the old registry path is deleted in the same change that wires
the new one, per the org's no-migration-code rule. It is not a new event bus
either: it spends the machinery the epic already built — Hub authority, the
replicator, the operations facade, the session registry the identity design
owns, and the display's `PendingInteractions` discipline. The one new mechanism
is the Hub-side callback dispatch, needed because a menu launch is not a
scene-element interaction and must not be routed through the element-resolve path
that drops it.

## What Must Change in the Existing Machinery

- **The session registry gains a lease and an identity per session.** The
  identity design owns the registry; its first PR merged the registry, and the
  lease is its next field. The menu model consumes both — the lease decides which
  callbacks are live, and the `ClientIdentity` labels them.

- **The menu registry holds callbacks keyed by session.** Today it holds a flat
  map of session-keyed items (`HubMenuRegistry`). It becomes a registry of
  callbacks, each with an id, a label, and an owning session, built into the
  session-then-callback menu.

- **Menu launches get their own Hub-side dispatch.** Today a menu click reuses
  `_hub_interaction_dispatch`, which needs a scene id and fails without one. A
  menu launch instead carries `{session_id, callback_id}` and is delivered to the
  owning session by the pickup path, never resolved against the scene-element
  index. The D21 element path is untouched — it remains correct for in-scene
  widgets.

- **Pickup delivery is added Hub-side.** The Hub gains the three delivery routes
  above — push down a persistent socket, stream or inbox for MCP streamable-HTTP,
  and a lease-bounded hold-and-deliver queue for periodic clients — generalizing
  the display's `PendingInteractions` discipline.

## Settled Decisions

These are the operator's rulings of 2026-07-29. They close the three questions
this document once left open and record the model's fixed points.

**A menu item is a callback; the menu shows only callbacks that will work.**
There is no abstract capability layer. If a callback is on the menu, a session
with a live lease stands behind it.

**Sessions carry a lease matched to their cadence, and any authenticated contact
renews it.** luxd's built-ins are an ordinary session with a permanent lease, so
the built-in beads board is no longer a special case. There is no separate renew
verb.

**Rendering is session ▸ callback, uniformly — no case logic.** Every session is
one submenu labeled from its `ClientIdentity`, with its callbacks as the leaves
under it, whatever the count. The operator ruled: "Would only do it one way:
Session-name -> callback-name. No case logic." A count-dependent variant that
flattened a lone callback into a labeled entry was considered and overruled. Two
sessions' callbacks are never merged; each session is its own submenu, so eight
one-callback sessions are eight single-leaf submenus — never one entry to
disambiguate.

**A lease expiring withdraws the session's menu registrations, with a re-push.**
The click-versus-expiry race is handled reasonably, not with heavy locking: a
click for an expired session gets a named "provider is gone" notice. The operator
ruled explicitly against building the most robust race mechanism.

**Pickup is routed by connection kind** — persistent socket push, MCP
streamable-HTTP stream or inbox, or a lease-bounded queue for periodic clients —
generalizing the display's `PendingInteractions` discipline Hub-side.

### The prior open questions, now ruled

**Prior question 1 — how to present a per-repo capability in the bar.** Ruled
moot. There is no per-repo capability and no submenu of repositories. Presentation
is session-then-callback, one entry per session's callback, labeled from the
session's identity.

**Prior question 2 — whether an agent-subscribed capability is in v1.** Ruled
moot. Every menu item is a callback delivered to its session, so the Hub-hosted
versus agent-subscribed split is gone. luxd's built-ins are just a session.
Delivery is routed by connection kind; the one remaining choice is the
MCP-stream-versus-inbox detail, which the delivery spike names.

**Prior question 3 — what a per-repo capability does with exactly one live
context.** Ruled moot. There is no submenu of contexts to collapse; each session's
callback is already its own top-level entry.

## A Named Spike

**The MCP-stream delivery spike.** For a session on the MCP streamable-HTTP
transport, the `CallbackInvocation` reaches the session either on its server
stream or through a session inbox. The spike answers the one open question: can a
menu-triggered invocation be pushed to a live Claude Code session over its
streamable-HTTP stream without the agent polling, and if not, is a session inbox
drained on the next call the right fallback for v1? The routing decision — that
MCP sessions are served this way at all — is settled; the spike only names which
of the two mechanisms carries it. This document names the spike; it does not run
it.

## Proposed PR Decomposition

Each PR is one rollback-coherent unit. The session-lease field is not a menu PR —
it belongs to the identity train, and the menu PRs consume it.

**Identity train (prerequisite, not a menu PR) — the session lease.** The lease
becomes the session registry's next field, implemented in the identity design's
train alongside `ClientIdentity`. The menu work depends on it and does not
duplicate it.

**PR 1 — the callback model and Hub-side callback dispatch.** Turn the menu
registry into a registry of session-owned callbacks. Register luxd's built-ins as
a permanent-lease session and each agent session's callbacks as its own. Add the
Hub-side dispatch that fires `CallbackInvocation {session_id, callback_id}`.
Delete the built-in's `Path.cwd()` guess and the dead agent-`register_tool`
launch path. This is the change that makes launching work.

**PR 2 — pickup delivery by connection kind.** Add the three delivery routes —
persistent-socket push, MCP stream or inbox, and the lease-bounded queue for
periodic clients — generalizing the display's `PendingInteractions` discipline
Hub-side. The MCP-stream detail follows the delivery spike.

**PR 3 — the menu bar shows sessions and withdraws on expiry.** Render callbacks
by the uniform rule — every session one submenu labeled from `ClientIdentity`,
its callbacks as leaves, whatever the count — and withdraw a session's entries
with a menu re-push when its lease expires, including the "provider is gone"
notice on the expiry race. Remove
the file-descriptor-keyed `menu_registrations` and `menu_owners` fiction from the
display's menu manager. This is the visible affordance change.

## Related Documents

- [target/target.md](target/target.md) — the Hub-authoritative model this builds
  on.
- [target/ui-model.md](target/ui-model.md) — handlers on Hub-side objects,
  application pub-sub versus UI events.
- [one-code-path.md](one-code-path.md) — the operations facade, the session
  registry, and the client-reports-its-repository rule this design extends.
