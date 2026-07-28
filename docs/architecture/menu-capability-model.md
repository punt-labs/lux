# Menu Capability Model

**Status:** design proposal for the operator to ratify. Read
[target/target.md](target/target.md) first; on any conflict that document wins.

This document redesigns what a Lux menu item is, what happens when the user
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
different identities at once, and it cannot.

### The three identities a menu item conflates

**The plugin.** There is one Lux. "Beads Browser" is a capability of Lux. It is
durable — it exists whether or not any agent is running. When the user thinks
"I want the beads browser," they are naming a plugin capability, not a session.

**The session.** There are eight Claude Code instances connected right now. Each
one is a separate, short-lived MCP connection to the Hub. A session comes and
goes. Today, the code makes a session the *owner* of a menu item — the item is
registered by a session and dies with it. That ties a durable capability to an
ephemeral thing.

**The context.** This is the repository the user actually cares about, and it is
missing from the model entirely. When the operator asks "which repo should the
beads browser show?", they are asking for the context. The current model has no
place to put it, so the answer is silent and wrong.

The fix is to give each of these three its own home, instead of forcing one
menu item to be all three.

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
because at the screen there is no "who." The context has to be part of what the
user chose, on screen, before the click.

## The Model

A menu item is a **capability**: a durable, named action that belongs to a
plugin, runs a handler on the Hub, and — when it needs one — resolves a context
at the moment it is launched.

### What a capability is

A capability has:

- an **id** that is stable and plugin-scoped, for example `lux.beads`.
- a **label** the user reads, for example "Beads Browser."
- an **owner**: the plugin (luxd) for a built-in, or a session for an
  agent-provided one. The owner decides the capability's lifetime.
- a **context mode**: either `none` (the capability needs no repository) or
  `per_repo` (the capability acts on one repository and must be told which).
- a **handler** that runs on the Hub when the capability is launched. The
  handler either installs a Hub-hosted UI (the beads board is this) or publishes
  a business event for an agent to act on.

The capability is the plugin identity. Its owner and lifetime are separate from
it. Its context is a separate axis resolved at launch. Each of the three
conflated identities now has its own field.

### Context is the live set of connected repositories

The context the user cares about is a repository. The Hub already knows the
repositories in play: each session connects from a working directory, and Lux's
own design says a client "carries only its own identity and the working
directory it alone can originate, and pushes that into the engine"
([one-code-path.md](one-code-path.md)). The `display_mode` request already
carries `repo: str` — an absolute path to the caller's project — so sessions
already tell the Hub their repository.

The gap is that the Hub does not store it. The session registry tracks
connections but records no working directory (`HubClient` has no repo field).
So the first concrete change is: every session reports its repository when it
connects, and the Hub records it in the session registry. The set of live
contexts is then the set of distinct repositories across connected sessions.
When the lux session connects, "lux" is a live context; when it disconnects,
"lux" leaves. The capability stays; the contexts come and go with sessions.

## What Happens on Click

### The eight-sessions, which-repo scenario, walked

Here is the operator's exact situation, resolved step by step.

1. luxd starts. It registers one durable built-in capability: id `lux.beads`,
   label "Beads Browser," context mode `per_repo`, handler = install a beads
   board for a given repository. It is registered once, by the plugin, not per
   session.

2. Eight Claude Code instances connect, from eight repositories — lux, vox,
   quarry, and so on. Each reports its working directory. The Hub's live-context
   set is now those eight repositories.

3. The menu bar shows one "Beads Browser" entry. Because the capability is
   `per_repo` and there are live contexts, the entry expands to a submenu
   listing the live repositories: lux, quarry, vox, sorted. The user sees
   exactly which repositories they can open a board for. The capability appears
   once; the choice of repository is visible under it.

4. The user clicks "Beads Browser" then "vox."

5. The display sends a launch message back to luxd carrying the capability id
   `lux.beads` and the chosen context — vox's repository path. The context is in
   the message because the user chose it on screen, not inferred from a
   session.

6. luxd dispatches the launch. This is a new Hub-side path, separate from the
   scene-element dispatch that fails today. It looks the capability up in the
   capability registry by id, sees `per_repo`, and runs the handler with
   context = vox's repository.

7. The handler runs `bd` in vox's repository, composes the beads table, installs
   it into the Hub as a scene in a frame titled "Beads: vox," and marks it
   dirty. The replicator paints it. The board appears, showing vox's beads.

8. No session had to be listening. The handler ran entirely on the Hub. It
   worked even though the click could not be attributed to any one of the eight
   sessions — because the user supplied the context by choosing it.

The "which repo?" question is answered by making the repository a visible choice
the user makes, drawn from the live set the Hub already knows.

### A context-free capability

Some capabilities need no repository — a theme picker, "Clear All," the Windows
menu. Their context mode is `none`. Clicking runs the Hub-side handler with no
context. These are the built-in Lux, Windows, and Help items today, and they
keep working the same way.

### An agent-subscribed capability

Some capabilities mean "the agent does the work," not "the Hub does the work."
An agent registers a capability whose handler publishes a business event — say
`openTicket` — instead of installing a UI. On click, the Hub publishes that
event to the owning session. This capability is inherently session-scoped: if
the agent is gone, there is no one to act on the event. So it is shown scoped to
its session and its context, and it disappears when the session leaves — the
menu is honest that this item is tied to a running agent.

The open question for this kind is *delivery*: how the published event reaches
the agent. That is the one genuine unknown, and it is called out below as a
spike rather than answered here.

## Registration and Ownership

Three parties register capabilities, and the owner sets the lifetime.

**The plugin (luxd) registers built-ins.** At startup, luxd registers its
durable capabilities — the beads browser today. These are owned by the plugin.
They never expire. They are the capabilities that must "appear once and always
work." The user sees them whether or not any agent is connected.

**An agent registers a session-scoped capability.** An agent may add a
capability that publishes a business event to itself. It is owned by that
session and removed when the session disconnects. It is shown as belonging to
that session's context.

**Nobody registers a context.** Contexts are not registered. They are the live
repositories of connected sessions, tracked by the Hub automatically. A context
appears when a session from that repository connects and leaves when the last
such session disconnects.

Unregistration follows ownership. A plugin built-in is never unregistered while
luxd runs. A session capability is dropped when the session disconnects, on the
same cleanup path that already drops a session's inbox and owned scenes.

## What the Menu Bar Shows

The menu should make the available actions and their contexts visible before the
click. That is the affordance the current design lacks.

- **Context-free capabilities** appear as single entries: Settings, Windows,
  Help, and any agent capability that needs no repository.

- **Per-repo capabilities** appear once, and expand to the live repositories
  they can act on. "Beads Browser" is one entry; under it are lux, quarry, vox.
  The user sees the repositories and picks one. The capability is singular; the
  context is a visible choice.

- **When there are no live contexts**, a per-repo capability still appears, but
  disabled, with a hint that it needs a connected repository. Showing it
  disabled keeps it discoverable and explains why it cannot be clicked, which is
  better than hiding it (the user would not know it exists) or leaving it
  clickable and dead (the failure we are removing).

- **Agent-subscribed capabilities** are shown grouped by the session and context
  that own them, so it is clear they belong to a running agent and will vanish
  when it leaves.

The exact shape of the per-repo grouping — capability-as-menu with repositories
inside, versus repository-as-menu with capabilities inside, versus flat
"Beads · vox" entries — is a real design choice and is raised as an open
question below.

## What Dies, and What This Is Not

**What dies:**

- Session-scoped `register_tool` as it exists today — a durable-looking item
  tied to an ephemeral session, whose click is dropped in the fallback handler.
  It is replaced by the two honest kinds: a plugin built-in, or a
  session-scoped agent capability with real delivery.

- The per-session, file-descriptor-keyed menu bookkeeping in the display
  (`menu_manager.py`: `_menu_registrations`, `_menu_owners`,
  `_sorted_app_clients`). After the Hub took over replication, the display sees
  only luxd's single connection, so grouping items "by client" on the display is
  fiction. Grouping by context belongs on the Hub, which knows the contexts.

- The built-in beads browser's use of `Path.cwd()` to guess a repository. The
  repository becomes an explicit context the user chooses, never luxd's own
  directory.

- The stale promise in the `register_tool` docstring that "clicks arrive via
  recv()."

**What this is not:**

- It is not a shim. There is no compatibility layer that keeps the old
  session-scoped item semantics alongside the new capability model. When the
  beads built-in and any agent tools move to the capability model, the old
  registry path is deleted in the same change that wires the new one, per the
  org's no-migration-code rule.

- It is not a new event bus. It spends the machinery the epic already built —
  Hub authority, the replicator, the operations facade, the Hub-side handler
  execution that the working beads path already proves. The only new mechanism
  is the Hub-side *menu* dispatch, which is needed because a menu launch is not
  a scene-element interaction and must not be routed through the element-resolve
  path that drops it.

## What Must Change in the Existing Machinery

The design reuses what exists and names each thing it must change.

- **The session registry records each session's repository.** Today `HubClient`
  has no working-directory field. It must gain one, populated from what the
  session reports on connect. `display_mode` already proves a session can report
  its repository, so this is a known mechanism, not a new capability.

- **The menu registry becomes a capability registry.** Today it holds a flat map
  of session-keyed items (`HubMenuRegistry`). It becomes a registry of
  capabilities with an id, a context mode, an owner, and a handler, plus the
  agent-defined menu bar it already holds.

- **Menu launches get their own Hub-side dispatch.** Today a menu click reuses
  `_hub_interaction_dispatch`, which needs a scene id and fails without one. A
  menu launch instead carries a capability id and a chosen context, and is
  resolved against the capability registry, never against the scene-element
  index. The D21 element path is untouched — it remains correct for in-scene
  widgets.

- **The launch message carries the chosen context.** The message the display
  sends on a menu click must include the context the user chose, not just the
  item id, because the context cannot be recovered on the Hub side otherwise.

## Settled Decisions

These follow from the diagnosis and the target architecture. They are recorded
so the design leaves them closed.

**A capability is durable and plugin-owned by default; a session capability is
the deliberate exception.** The default menu item is a plugin capability that
outlives every session, because that is what "one Lux, appears once, always
works" requires. A session-scoped capability exists only for the case where the
agent itself must do the work, and it is shown as session-bound so its
disappearance is not a surprise.

**Context is chosen on screen, never inferred from the click.** The display has
one screen and no per-session identity at a click, so a per-repo capability must
present its live contexts and let the user choose. Inferring a repository from
"who clicked" is impossible and is not attempted.

**The handler runs on the Hub.** Every capability's real work runs Hub-side, on
the proven path the built-in beads browser already uses. The Hub is the
authority for installed UI, so a launch that installs UI installs it on the Hub
and lets the replicator paint it.

**luxd stops guessing a repository from its own working directory.** luxd's cwd
is not a repository of interest. A per-repo capability with no live contexts is
shown disabled, not run against luxd's directory.

## Open Questions for the Operator

These are genuine forks. Each carries a recommendation.

**1. How to present a per-repo capability in the bar.** The choices are:
(a) the capability is a menu and the live repositories are its items — "Beads
Browser" opens to lux, quarry, vox; (b) each repository is a top-level menu and
capabilities live under it — "vox" opens to "Beads Browser"; (c) flat entries,
one per pair — "Beads · lux", "Beads · vox". Recommendation: **(a)**. In v1
there is essentially one per-repo capability, so grouping by capability keeps
the bar shallow, and the user's stated mental model is "I want the beads
browser," so the capability is the natural top-level name. Reconsider if v2
grows many per-repo capabilities, when grouping by repository may read better.

**2. Whether an agent-subscribed capability is in v1 at all.** The Hub-hosted
capability (beads) fully resolves the operator's stated pain. The
agent-subscribed capability (click publishes a business event to a listening
agent) is more of the model but depends on the delivery spike below.
Recommendation: **land the Hub-hosted capability model first and defer the
agent-subscribed kind** until the spike says whether reliable delivery is
achievable. This keeps v1 honest — we ship the launches that work, not a second
promise we cannot keep.

**3. What a per-repo capability does when exactly one context is live.** With one
connected repository, the submenu holds one item. The choices are: still require
the user to pick it, or launch directly on click since there is no ambiguity.
Recommendation: **still show the one item and require the pick**, so the behavior
is uniform and the user always sees which repository they are opening. A
click-through shortcut for the single-context case can be added later if the
extra click proves annoying.

## A Named Spike

**The agent-notification delivery spike.** For an agent-subscribed capability,
the click publishes a business event that must reach the owning session. Today
that would land in the session's inbox and wait for a `recv` poll that the agent
is not running. The streamable-HTTP transport the epic adopted carries
server-initiated messages on its stream, which is the push channel a menu launch
would need. The spike answers one question: can a menu-triggered business event
be pushed to a live session over that stream without the agent polling, and if
not, is `recv`-polling an acceptable fallback for v1? The outcome decides
Open Question 2. This document names the spike; it does not run it.

## Proposed PR Decomposition

Each PR is one rollback-coherent unit.

**PR 1 — session context registry.** Record each connected session's repository
in the Hub session registry, populated from what the session reports on connect.
Expose the live-context set. This is the enabler; nothing depends on it yet, so
it lands and is exercised on its own.

**PR 2 — the capability model and the beads built-in.** Turn the menu registry
into a capability registry. Register the beads browser as one durable, per-repo,
plugin-owned capability. Add the Hub-side menu-launch dispatch that resolves a
capability and a chosen context and runs its handler. Delete the built-in's
`Path.cwd()` guess and the dead agent-`register_tool` launch path. This is the
change that makes launching work.

**PR 3 — the menu bar shows contexts.** Render per-repo capabilities grouped by
live context (the shape ruled in Open Question 1), with the disabled state when
no context is live. Remove the file-descriptor-keyed `menu_registrations` and
`menu_owners` fiction from the display's menu manager. This is the visible
affordance change.

**PR 4 — agent-subscribed capabilities.** Gated on the delivery spike and Open
Question 2. Add the capability kind whose handler publishes a business event to
the owning session, shown scoped to that session, delivered by whatever the
spike settles on. Deferred until the spike returns.

## Related Documents

- [target/target.md](target/target.md) — the Hub-authoritative model this builds
  on.
- [target/ui-model.md](target/ui-model.md) — handlers on Hub-side objects,
  application pub-sub versus UI events.
- [one-code-path.md](one-code-path.md) — the operations facade, the session
  registry, and the client-reports-its-repository rule this design extends.
