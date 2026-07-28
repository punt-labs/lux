# Client Identity and Scene Ownership

**Status:** design proposal for the operator to ratify. Read
[target/target.md](target/target.md) first; on any conflict that document wins.

This document decides what a client of Lux is, how each client tells the Hub who
it is, and who owns a scene once it is installed. It is a contract change across
every front door — the MCP tools, the REST API, the command-line tool, and the
display socket. The thing that is broken is attribution: right now the Hub cannot
say which caller owns which scene, so the operator cannot either.

## The Problem, From the Live Hub

The operator inspected the running Hub and found two ownership shapes, both
useless for the question "who owns this?"

Every beads board created by `lux show beads` is owned by the literal string
`"rest"`. Five boards, five repositories, one owner string for all of them. The
boards are indistinguishable by owner.

An MCP-created dialog is owned by an opaque hex, `"2e3f1621"`. That hex names a
connection. It does not name a caller. Nothing about it says which agent, in
which repository, put the dialog up.

Both are symptoms of the same gap. A Lux client today carries a *connection*,
not an *identity*. The REST front door does not even carry a distinct connection
— every REST and command-line caller shares one reserved pseudo-connection named
`"rest"`, because REST had no identity to give and borrowed an immortal stand-in
so its scenes would not be swept away. That stand-in is the `"rest"` owner on
every board.

The operator's ruling: "All clients of the rest service and display need to have
an identity/owner." And the boundary on it: "I do not want to go overboard with
security on this; the first goal is to have clear, reliable scene ownership, not
hardened security; we can consider security as a second step."

So this design gives every client a real identity and makes that identity the
owner of what it installs. It does not authenticate anyone. The two goals are
kept apart on purpose, and the point where authentication would later attach is
named at the end.

## The Trust Model, Stated

Lux today runs for one user on one machine. luxd binds loopback and refuses a
non-loopback bind at startup ([one-code-path.md](one-code-path.md)). Every client
is the same person who started the Hub.

Under that model, an identity is a *declaration*, not a *credential*. A client
tells the Hub who it is, and the Hub records exactly what it was told. The Hub
verifies nothing, because there is no second party to defend against. Identity
here is for attribution — so the operator and the agents can see who owns what —
not for access control.

This is the whole security posture for step one, and it is deliberate. The step
where the Hub would start to *verify* a declared identity is named in the last
section. Nothing in this design builds it.

## What a Client Identity Is

A client identity is a small record the Hub stores for a caller. It has these
fields.

- **kind** — one of `mcp-session`, `cli`, or `app`. This is the discriminator,
  and it decides the identity's lifetime (see ownership below).
  - `mcp-session` is a Claude Code agent's live MCP connection to the Hub.
  - `cli` is a `lux` command invocation, such as `lux show beads`.
  - `app` is luxd itself, the plugin that owns the built-in capabilities.
- **name** — the human-readable label the Hub shows for this client, for example
  `claude` or `lux-cli`. This is what `list_clients` prints and what a scene's
  owner resolves to on screen.
- **repo** — the absolute path of the repository the caller is working in, or
  absent when the caller has no repository (a headless invocation). This is the
  field the menu design also needs; the two designs share it (see the alignment
  section).
- **agent** — an optional persona handle, such as `gvr` or `claude`, when the
  caller knows it. Under the same-user trust model this is self-declared and
  unverified, like every other field.

The identity is metadata bound to a connection, not a replacement for it. The
wire-level `ConnectionId` stays exactly what it is today — the key that scopes a
session's subscriptions, its inbox, and the cleanup that runs when the wire
drops. What changes is that the Hub now also holds an identity record for that
connection, and the identity — not the bare `ConnectionId` — is what a scene
records as its owner.

### Who declares it, and how each front door carries it

The client declares its own identity. The Hub records the declaration. This
follows the rule the architecture already states: a client "carries only its own
identity and the working directory it alone can originate, and pushes that into
the engine" ([one-code-path.md](one-code-path.md)).

- **The MCP session** connects to `/mcp?session_key=<value>` today, and that
  value becomes its `ConnectionId`. The session gains an identity by declaring
  its `kind`, `name`, `repo`, and `agent` when it connects — the same moment it
  already declares `session_key`. Exactly how it declares them is a genuine fork,
  raised as Open Question 1.

- **The REST and command-line caller** carries its identity in the request. The
  command-line tool resolves the identity from its context (its working
  directory and git repository) and sends it; a raw REST caller sends it in a
  header. The shared `"rest"` pseudo-connection is gone — each caller carries a
  real, named identity, and its `ConnectionId` is derived from that identity, not
  from a single reserved constant.

- **The app (luxd's built-ins)** declares its identity at startup, once, when it
  registers the capabilities it owns.

## Ownership: Who Owns a Scene, and For How Long

Ownership today conflates two things that must be pulled apart: *who* owns a
scene, and *how long* it lives. The Hub records a scene's owner as a
`ConnectionId` (`domain/hub/owner_tracker.py`), and a scene lives exactly as long
as that connection does. When the connection drops, the disconnect cascade sweeps
every scene it owned.

That single rule is wrong for two of the three kinds of client.

A `lux show beads` process connects to REST, installs one board, and exits
immediately. If the board's life were tied to that process's connection, the
board would vanish the instant the command returned. The only reason the board
survives today is the accident that it is owned by the immortal `"rest"`
pseudo-connection, which never disconnects. The board persists for the wrong
reason, and un-attributed.

So ownership splits along the identity's kind.

- **A scene owned by an `mcp-session` identity dies when that session
  disconnects.** This is the existing cascade, unchanged, and it is correct: an
  ad-hoc dialog an agent put up is the agent's ephemeral UI, and it should leave
  with the agent.

- **A scene owned by a `cli` identity is durable.** Its owner is the caller's
  repository context, not the short-lived command process. It persists after the
  command exits, and it is cleaned up the way durable UI already is — by an
  explicit `clear`, or by the frame-expiry timeout the Hub already runs
  (`domain/hub/frame_expiry.py`) — never by a disconnect. The command invocation
  that installed or last wrote it is recorded as metadata (the last writer), so
  the board shows both its durable owner (the repository) and who touched it last.

- **A scene owned by an `app` identity is durable for luxd's lifetime.** These
  are the built-ins; they persist until the Hub stops, matching the menu design's
  rule that a plugin built-in is never unregistered while luxd runs.

The rule in one sentence: a scene's lifetime follows its owner's kind, and only
`mcp-session`-owned scenes die with a wire.

The disconnect cascade changes accordingly. Today it drops every scene the
dropping `ConnectionId` owned. After this change it drops only the scenes owned
by a *session* identity whose connection dropped, and leaves durable (`cli`,
`app`) owners alone.

## The Fate of the Reserved "rest" Connection

`RESERVED_REST_CONNECTION = ConnectionId("rest")` and the `DEFAULT_SCOPE` built
from it (`session_key.py`, `rest/app.py`) exist for one reason: REST had no
identity, so it borrowed one immortal connection for all its callers, and the
Hub reserved that name so an MCP session could not collide with it and, on
disconnect, sweep away REST-created scenes.

Once every REST and command-line caller carries its own real identity, there is
no shared pseudo-connection to protect, and nothing to reserve. So both the
reserved constant and the reserved-key refusal in the MCP endpoint
(`mcp_endpoint.py`, the 403 on a colliding `session_key`) are deleted. There is
no longer a reserved name to collide with.

That raises the question the operator flagged: what happens to a caller that
declares no identity at all? The answer splits by what the caller is doing.

- A **read-only** call — a health probe, `list_scenes`, `ping` — tolerates a
  caller with no declared identity. These do not own anything, so an
  auto-derived or anonymous reader is fine. Nothing breaks.
- A **scene-owning write** — `render`, `update` — needs a real owner. The
  command-line tool always resolves one from its working directory before it
  calls, so in practice a write arrives with an identity. Whether a write that
  still carries *nothing* should be given an auto-derived identity or refused
  with a named error is a genuine fork, raised as Open Question 2.

## How Introspection Answers "Who Owns What"

The operator's question — "which sessions own which scenes" — has no true answer
today. After this change it does, because both `list_clients` and `list_scenes`
report the identity, not the bare connection.

Before, from the live Hub:

```text
list_scenes → scenes: [
  { scene_id: "beads-lux",  owner: "rest" },
  { scene_id: "beads-vox",  owner: "rest" },
  { scene_id: "beads-quarry", owner: "rest" },
  ...
]
list_clients → clients: [
  { connection_id: "2e3f1621", owned_scenes: ["dialog-1"] }
]
```

The owner is `"rest"` for every board, and the one MCP client is a hex.

After:

```text
list_scenes → scenes: [
  { scene_id: "beads-lux",
    owner: { kind: "cli", name: "lux-cli", repo: "/…/lux" },
    last_writer: "lux-cli" },
  { scene_id: "beads-vox",
    owner: { kind: "cli", name: "lux-cli", repo: "/…/vox" },
    last_writer: "lux-cli" },
  ...
]
list_clients → clients: [
  { identity: { kind: "mcp-session", name: "claude", repo: "/…/lux", agent: "claude" },
    connection_id: "2e3f1621",
    owned_scenes: ["dialog-1"] }
]
```

Each board names the repository that owns it and the kind of client that created
it. Each connected client names its identity and the scenes it owns. The
operator can now read ownership straight off the introspection output.

Concretely, `SceneSummary.owner` (`operations/models/query_scenes.py`) changes
from a bare owner string to the structured identity, and `HubClient`
(`operations/models/query_clients.py`) gains an `identity` field. These are the
read shapes; the owner mechanics above are what fill them.

## The Command-Line Identity Flow

The operator's sketch was a gh-like flow, "which perhaps could be simplified if
it is in a repo with an active session." Developing that sketch turns up a
simplification bigger than the operator suggested: Lux needs no enrollment step
at all.

gh enrolls because it needs a *credential* — a token it stores and later
presents. Lux, under the same-user-localhost trust model, needs only a *name*,
and a name can be derived from the working directory. There is no secret to
store, so there is no enrollment to do. The whole "auth flow" collapses to
resolving a name from context, with an override.

The command-line tool resolves its identity in this order.

1. **An explicit override.** A `--as <name>` flag or a `LUX_CLIENT` environment
   variable, when the caller wants to name itself. This is the escape hatch; it
   is rarely needed.

2. **Attach to a live repository context.** If the working directory is inside a
   repository that already has an active MCP session connected to the Hub, the
   command attaches to that repository's context — its board is owned by that
   repository, attributed to `lux-cli`. This is the operator's "simplified if in
   a repo with an active session" path: the context already exists in the Hub's
   registry, so the command joins it rather than inventing one.

3. **Derive from the repository.** With no active session for this repository,
   the command derives its identity from the git repository root — `name` from
   the repository's directory name, `repo` from the root path. This is
   deterministic and needs no stored state, because the working directory already
   determines the answer.

4. **Headless or non-repository.** In CI, or when the working directory is not a
   repository, the command derives a fallback identity — `name` of `lux-cli`,
   `repo` absent — and installs a context-free scene. The owner is still real and
   named; it is never the anonymous `"rest"`.

First run and every repeat run take the same path, because nothing is persisted:
the working directory yields the same identity each time. Persisting an identity
record would only start to matter when step-two security adds a token to present,
and that is out of scope here (raised as Open Question 3).

## Alignment With the Menu Capability Model

The [menu capability model](menu-capability-model.md) needs the Hub to know each
session's repository, so it can present the live set of repositories under a
per-repo menu item. Its PR-1 is titled "session context registry" and does
exactly one thing: record each connected session's repository in the Hub session
registry, and expose the set of live repositories.

That is a strict subset of the identity record this design defines. The `repo`
field is the same field. There must be **one** registry, and it holds the
identity record.

- **What is shared:** the Hub session registry (`domain/hub/hub_clients.py`, the
  `HubClientRegistry`) grows from holding a bare connect-time to holding the
  identity record, and `repo` is one field of it. Both designs populate it from
  the same act — the client declaring its identity when it connects.
- **What the menu design adds on top:** the live-context projection (the set of
  distinct connected repositories) and the capability model that reads it.
- **What this design adds on top:** the full identity record (kind, name,
  agent), the owner-is-an-identity model for scenes, the command-line identity
  flow, the deletion of the reserved `"rest"` connection, and the introspection
  shapes.

The concrete coordination: this design's registry record is the shared
foundation, and the menu design's PR-1 folds into this design's first PR (below)
rather than building a second registry. Whichever epic lands that PR first builds
the registry; the other reads it. The leader sequences the two epics; this
document only fixes that they share one registry and names it.

## Interactions To Note

Three open beads touch this contract. This design notes where each connects; it
does not solve them.

- **lux-e9vy (ghost replicas).** A reconnecting client can leave a duplicate
  replica behind because the Hub cannot recognize that the new connection is the
  same client. An identity gives the Hub the handle to recognize a returning
  client and reconcile its replicas per owner rather than duplicating them. The
  identity record is the prerequisite; the reconciliation is that bead's work.

- **lux-s4wg (the display socket accepts any client).** The display socket
  handshake already carries a client name (`ConnectMessage(name=…)`), which is
  the display-leg of identity. Today only luxd connects to that socket, so the
  identity there is latent. The same identity record should stamp that handshake
  if a non-luxd client ever connects. That is the display leg of this same
  contract, out of scope under the same-user trust model, named here so the two
  legs stay one contract.

- **lux-0shg (command-line parity).** The session-scoped operations — subscribe,
  unsubscribe, publish, receive, and a per-caller `clear` — were held off the
  REST front door in [one-code-path.md](one-code-path.md) precisely because every
  REST caller shared one anonymous scope, so a REST publish could never reach a
  subscriber. Giving each REST and command-line caller a real,
  `ConnectionId`-bearing identity removes that blocker. Those operations become
  expressible over REST once this contract lands; whether to expose them is that
  bead's decision.

## Settled Decisions

These follow from the diagnosis and the target architecture. They are recorded so
the design leaves them closed.

**An owner is an identity, not a bare connection.** A scene records the identity
that installed it — kind, name, repository, optional agent — not an opaque
`ConnectionId`. The connection stays the wire key for scope and cleanup; the
identity is the owner.

**A scene's lifetime follows its owner's kind.** An `mcp-session`-owned scene
dies when its session disconnects, by the existing cascade. A `cli`-owned scene
is durable, owned by its repository context, cleaned by explicit `clear` or the
existing frame-expiry timeout, and never by a disconnect. An `app`-owned scene
lives for luxd's lifetime. Only session-owned scenes die with a wire.

**The reserved "rest" connection dies.** It was a stand-in for identity-less
REST. Every caller now carries a real identity, so there is no shared
pseudo-connection to protect and no reserved name to collide with; the
reserved-key refusal in the MCP endpoint goes with it.

**There is one identity registry, shared with the menu design.** The `repo` field
is the same field both designs need; the menu design's live-context set is a
projection over this registry. No second registry is built.

**The command-line tool derives its name from context; it does not enroll.** The
same-user-localhost trust model authenticates nothing, so there is no credential
to store and no enrollment step. The working directory and git root yield the
name; a flag or environment variable overrides it.

**Same-user-localhost trust is the model.** The Hub records what a client
declares and verifies nothing. luxd is already loopback-only. Identity is
attribution, not access control.

## Open Questions for the Operator

These are genuine forks. Each carries a recommendation.

**1. How an MCP session declares its identity.** The choices are: (a) query
parameters alongside `session_key`, so the URL carries `?session_key=…&repo=…&agent=…`;
(b) an explicit `identify` operation the session calls first, carrying the whole
record; (c) piggyback on the first write that already carries a repo, as
`display_mode` does today. Recommendation: **(b) an `identify` first-call.** It is
the one place to declare kind, name, repo, and agent together; it is symmetric
with the REST header; and it does not overload the connection URL or scatter the
record across later calls. The menu design's "report the repo on connect" becomes
a part of this one call, not a separate mechanism. Choose (a) instead if the
record must never be more than a repo, in which case a query parameter is
simplest.

**2. What an anonymous write does — derive or refuse.** A scene-owning write
(`render`, `update`) that arrives with no resolvable identity. The choices are:
(a) auto-derive a fallback identity from whatever the request carries, such as
its working directory; (b) refuse with a named error that says a write needs an
identity. Recommendation: **derive where the request carries a working directory
— the command-line tool always does — and refuse only a write that carries
literally nothing.** This matches "clear ownership, not gatekeeping": nothing
legitimate reaches the refusal path, and a truly context-free write that wants to
own a scene is the one case worth stopping.

**3. Whether the command-line identity is derived every time or persisted.** The
choices are: (a) derive the identity from the working directory on every
invocation, storing nothing; (b) persist an identity record, like gh's
`hosts.yml`, for stability across invocations. Recommendation: **(a) derive every
time.** Lux stores no credential, and the working directory is deterministic, so
persistence buys nothing in step one. Persistence starts to matter only when
step-two security adds a token to store and present — which is exactly where a
persisted record would arrive, together with the thing worth persisting.

## Where Step-Two Security Attaches

This design is scoped to attribution and stops there. When Lux later serves more
than one user, or reaches beyond loopback, a declared identity stops being
trustworthy and must be backed by a credential the Hub verifies. The exact point
where that plugs in is nameable now, so the design leaves a clean place for it:

- The command-line identity file gains a token, stored the way gh stores its
  token, and the command presents it with each request. This is the enrollment
  step this design deliberately omits.
- The Hub verifies the presented token against the declared identity before
  recording ownership, instead of recording the declaration as-is. This is the
  one behavioral change: declaration becomes verified declaration.
- luxd's off-loopback bind, which it refuses today, is enabled together with that
  verification and an origin policy derived from the bind host, exactly as
  [one-code-path.md](one-code-path.md) already stages it.

None of that is built here. It is named so that step one does not accidentally
close the door on it. The identity record this design defines is the same record
step two would verify; step two adds verification, it does not redefine identity.

**A named spike, not run here:** whether the "attach to a live repository
context" path (command-line resolution step 2) can reliably detect an active
session for the working directory without racing session connect and disconnect.
If it cannot be made race-free cheaply, the fallback is derivation (step 3),
which is always available. The spike decides whether step 2 is worth its
complexity or whether the command-line tool should derive unconditionally. This
document names the spike; it does not run it.

## Proposed PR Decomposition

Each PR is one rollback-coherent unit.

**PR 1 — the identity record and the shared registry.** Introduce the
`ClientIdentity` record (kind, name, repo, optional agent) and make the Hub
session registry hold it, populated from what each client declares on connect.
This is the shared foundation the menu capability model's PR-1 folds into. It is
additive: nothing owns-by-identity yet, so it lands and is exercised on its own.

**PR 2 — owner is an identity, and lifetime follows kind.** Change the owner a
scene records from a `ConnectionId` to the identity, and change the disconnect
cascade to drop only session-owned scenes, leaving `cli` and `app` owners
durable. Delete `RESERVED_REST_CONNECTION`, its `DEFAULT_SCOPE`, and the
reserved-key refusal, and make every REST route resolve a real identity. The
introspection owner shape changes here because it must — `SceneSummary.owner`
becomes the structured identity in the same unit. This is the change that makes
ownership real.

**PR 3 — the command-line identity flow.** Make `LuxRestClient` and the `lux`
commands resolve an identity from context (working directory and git root, with a
`--as` / `LUX_CLIENT` override) and send it. After this, `lux show beads` boards
are owned by their repository and attributed to `lux-cli`, and the live probe the
operator ran returns the "after" shapes above. Depends on PR 2.

Ratification of this document is followed by a `DESIGN.md` ADR (the next number,
DES-056) recording the decision; the ADR lands with the first implementation PR,
not with this design doc.

## Related Documents

- [target/target.md](target/target.md) — the Hub-authoritative model this builds
  on.
- [one-code-path.md](one-code-path.md) — the operations facade, the session
  registry, the reserved-`"rest"` scope this design retires, and the
  loopback-only bind policy step-two security extends.
- [menu-capability-model.md](menu-capability-model.md) — the session-context
  registry this design's identity record subsumes, and the capability model that
  reads the shared `repo` field.
- [target/introspection-api.md](target/introspection-api.md) — the `list_clients`
  and `list_scenes` read surface whose owner shapes this design makes meaningful.
