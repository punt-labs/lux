# Client Identity and Scene Ownership

**Status:** ratified with amendments (operator, 2026-07-28 — see
[Ratification](#ratification)). Read [target/target.md](target/target.md)
first; on any conflict that document wins.

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
`"rest"` (`RESERVED_REST_CONNECTION` in `session_key.py`), because REST had no
identity to give and borrowed one shared stand-in.

Note what the problem is *not*. The boards do not persist because they are owned
by `"rest"`. They persist because every scene is durable — a scene survives its
creating connection, ratified in PR #275 (see the lifetime section). The `"rest"`
owner is not keeping the boards alive; it is only making them indistinguishable.
The problem is attribution, cleanly separated from lifetime.

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

- **kind** — one of `mcp-session`, `cli`, or `app`. This is the discriminator.
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
connection, and the identity — not the bare `ConnectionId` — is what an installed
root records as its owner.

### Who declares it, and how each front door carries it

The client declares its own identity. The Hub records the declaration. This
follows the rule the architecture already states: a client "carries only its own
identity and the working directory it alone can originate, and pushes that into
the engine" ([one-code-path.md](one-code-path.md)).

- **The MCP session** connects to `/mcp?session_key=<value>` today, and that
  value becomes its `ConnectionId`. The session gains an identity by declaring
  its `kind`, `name`, `repo`, and `agent` when it connects — the same moment it
  already declares `session_key`. Exactly how it declares them is a genuine fork,
  raised as Open Question 2.

- **The REST and command-line caller** carries its identity in the request. The
  command-line tool resolves the identity from its context (its working
  directory and git repository) and sends it; a raw REST caller sends it in a
  header. The shared `"rest"` pseudo-connection is gone — each caller carries a
  real, named identity, and its `ConnectionId` is derived from that identity, not
  from a single reserved constant.

- **The app (luxd's built-ins)** declares its identity at startup, once, when it
  registers the capabilities it owns.

## Ownership Is Per-Root, and a Scene Can Have Several Owners

Ownership in Lux is recorded per installed root, not per scene. The `OwnerTracker`
keys `(scene_id, element_id) → ConnectionId` (`domain/hub/owner_tracker.py`), so
one scene can hold roots installed by different connections, and each root has its
own owner. The introspection model already reflects this: `SceneSummary.owners`
is a list — "every distinct connection owning a root in the scene"
(`operations/models/query_scenes.py`).

This design changes the *value* recorded as an owner, not the granularity. The
per-root owner becomes the identity record instead of a bare `ConnectionId`. A
scene's `owners` list therefore becomes a list of distinct identities — the
repositories and agents that own the roots in that scene.

The mixed case is real and must be answered. A `lux show beads` board is a
`cli`-owned root; an agent may then install its own dialog root into a scene
presented in the same frame, a `mcp-session`-owned root. Under per-root
ownership these coexist: the scene reports two owners, and each root keeps its own
owner for as long as it lives. There is no single scene owner to be in conflict,
because ownership was never per-scene. Whatever cleanup rule applies, it applies
to a root, not to the whole scene — a point that matters for the lifetime fork
below, because dropping a session drops that session's *roots*, and a scene
empties only when its last root is gone.

## Scene Lifetime Is Already Settled — and This Design Must Not Quietly Change It

Here is the fact that reshapes the rest of this design. Today every scene is
durable. When an MCP session disconnects, the cascade forgets the connection as a
Hub client, tears down its subscription scope and its writer binding, and
releases its inbox — and it deliberately leaves the scenes standing
(`domain/hub/lifecycle.py`, `HubDisplay.drop_connection` in `hub_display.py`).
The roots stay installed and stay owned by the departed connection id until a
later explicit removal: the user closing the frame, an agent clearing, or a frame
TTL expiring.

This is not incidental. It is PR #275, the scene-frame lifecycle, ratified by the
operator. Its taxonomy: a **frame** is the user's unit — the user closes it, or a
TTL set on it expires — and a **scene** is the agent's unit, which survives the
agent's session. A session's UI outliving the session is the point, so an agent
can put up UI, drop its connection, reconnect, and find its UI still there.

An earlier draft of this design said `mcp-session`-owned scenes "die on
disconnect" and called that the existing behavior. That was wrong on both counts.
It is not the existing behavior — the existing behavior is that they survive — and
adopting it would reverse a ratified operator decision while claiming to preserve
it. That reversal is now surfaced as an explicit fork for the operator (Open
Question 1), not smuggled in as a settled default.

The consequence for the rest of the design: **identity is attribution, and by
itself it changes no lifetime.** An owner's identity records *who* owns a root;
it does not decide *how long* the root lives. The lifetime model is PR #275's, and
it stands unless the operator rules on the fork to change it.

## The Fate of the Reserved "rest" Connection

`RESERVED_REST_CONNECTION = ConnectionId("rest")` and the `DEFAULT_SCOPE` built
from it (`session_key.py`, `rest/app.py`) exist for one reason: REST had no
identity, so it borrowed one connection for all its callers, and the Hub reserved
that name so an MCP session could not claim it and interfere with REST-created
state.

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
  with a named error is a genuine fork, raised as Open Question 3.

## How Introspection Answers "Who Owns What"

The operator's question — "which sessions own which scenes" — has no true answer
today. After this change it does, because both `list_clients` and `list_scenes`
report the identity, not the bare connection. The `owners` list stays plural, as
it already is; each entry becomes a structured identity.

Before, from the live Hub:

```text
list_scenes → scenes: [
  { scene_id: "beads-lux",  owners: ["rest"] },
  { scene_id: "beads-vox",  owners: ["rest"] },
  { scene_id: "beads-quarry", owners: ["rest"] },
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
    owners: [ { kind: "cli", name: "lux-cli", repo: "/…/lux" } ] },
  { scene_id: "beads-vox",
    owners: [ { kind: "cli", name: "lux-cli", repo: "/…/vox" } ] },
  { scene_id: "review-panel",
    owners: [ { kind: "cli", name: "lux-cli", repo: "/…/lux" },
              { kind: "mcp-session", name: "claude", repo: "/…/lux", agent: "claude" } ] },
  ...
]
list_clients → clients: [
  { identity: { kind: "mcp-session", name: "claude", repo: "/…/lux", agent: "claude" },
    connection_id: "2e3f1621",
    owned_scenes: ["review-panel"] }
]
```

Each board names the repository that owns its root and the kind of client that
created it. The `review-panel` scene shows the mixed case: a `cli` root and an
`mcp-session` root, two owners, side by side. Each connected client names its
identity and the scenes it holds a root in. The operator can now read ownership
straight off the introspection output.

Concretely, each entry in `SceneSummary.owners`
(`operations/models/query_scenes.py`) changes from an owner string to the
structured identity, and `HubClient` (`operations/models/query_clients.py`) gains
an `identity` field. These are the read shapes; the per-root owner value above is
what fills them.

## The Command-Line Identity Flow

The operator's sketch was a gh-like flow, "which perhaps could be simplified if
it is in a repo with an active session." Developing that sketch turns up a
simplification bigger than the operator suggested: Lux needs no enrollment step at
all, and the "attach to an active session" step is not needed either.

gh enrolls because it needs a *credential* — a token it stores and later presents.
Lux, under the same-user-localhost trust model, needs only a *name*, and a name
can be derived from the working directory. There is no secret to store, so there
is no enrollment to do.

And deriving from the working directory already produces the outcome the
"attach to an active session" step was reaching for. If a repository has an active
MCP session, that session reported the same repository the command-line tool would
derive, so both resolve to the *same repository context*. Attaching would add only
the session's agent name — but a `lux` invocation is a `cli`, not the agent, and
attributing a command-line board to the agent would be wrong. So deriving is not
merely equivalent to attaching; it is more correct, and it has no session to race.
The operator's "simplified if in a repo with an active session" intent is
satisfied — a command in such a repo Just Works — by derivation, without the
attach step.

The command-line tool resolves its identity in this order.

1. **An explicit override.** A `--as <name>` flag or a `LUX_CLIENT` environment
   variable, when the caller wants to name itself. This is the escape hatch; it is
   rarely needed.

2. **Derive from the repository.** The command derives its identity from the git
   repository root — `name` from the repository's directory name, `repo` from the
   root path. This is deterministic and needs no stored state and no session
   lookup, because the working directory already determines the answer.

3. **Headless or non-repository.** In CI, or when the working directory is not a
   repository, the command derives a fallback identity — `name` of `lux-cli`,
   `repo` absent — and installs a context-free scene. The owner is still real and
   named; it is never the anonymous `"rest"`.

First run and every repeat run take the same path, because nothing is persisted:
the working directory yields the same identity each time. Persisting an identity
record would only start to matter when step-two security adds a token to present,
and that is out of scope here (raised as Open Question 4).

Dropping the attach step retires the spike an earlier draft named — whether
attaching to a live session could be made race-free. There is no race to worry
about, because every resolution path above is a deterministic read of the working
directory. No spike is needed for step one; the resolution is total and local.

## Alignment With the Menu Capability Model

The [menu capability model](menu-capability-model.md) needs the Hub to know each
session's repository, so it can present the live set of repositories under a
per-repo menu item. Its PR-1 is titled "session context registry" and does exactly
one thing: record each connected session's repository in the Hub session registry,
and expose the set of live repositories.

That is a strict subset of the identity record this design defines. The `repo`
field is the same field. There must be **one** registry, and it holds the identity
record.

- **What is shared:** the Hub session registry (`domain/hub/hub_clients.py`, the
  `HubClientRegistry`) grows from holding a bare connect-time to holding the
  identity record, and `repo` is one field of it. Both designs populate it from
  the same act — the client declaring its identity when it connects.
- **What the menu design adds on top:** the live-context projection (the set of
  distinct connected repositories) and the capability model that reads it.
- **What this design adds on top:** the full identity record (kind, name, agent),
  the identity-as-owner model for roots, the command-line identity flow, the
  deletion of the reserved `"rest"` connection, and the introspection shapes.

The concrete coordination: this design's registry record is the shared foundation,
and the menu design's PR-1 folds into this design's first PR (below) rather than
building a second registry. Whichever epic lands that PR first builds the
registry; the other reads it. The leader sequences the two epics; this document
only fixes that they share one registry and names it.

## The Cleanup Story for Durable Scenes

If a `cli`-owned board is durable, and the command that made it has exited, what
eventually removes it? The answer is the same as for every scene today, because
this design does not change scene lifetime — it changes attribution.

A durable scene is removed by exactly the three paths PR #275 established, and no
others.

- The **user closes its frame**. Frames are the user's removal unit; closing a
  frame removes the scenes it presented.
- An **agent or command clears** it explicitly.
- A **frame TTL expires**, if one was set when the frame was created. The TTL is
  opt-in per frame (`domain/hub/frame_expiry.py`), not a background collector that
  reaps orphans. A frame with no TTL is not swept.

There is deliberately no automatic orphan collector for durable scenes. That is
the PR #275 model, not an omission: the user owns removal through the frame, and a
board that the user has not closed and did not TTL is a board the user still
wants. An agent or command that wants its board to clean itself up sets a frame
TTL when it creates it. If unbounded accumulation of never-closed, never-TTL'd
boards ever becomes a real problem, that is a lifetime question for the frame
model to answer, not something client identity introduces or should solve.

## Interactions To Note

Three open beads touch this contract. This design notes where each connects; it
does not solve them.

- **lux-e9vy (ghost replicas).** A reconnecting client can leave a duplicate
  replica behind because the Hub cannot recognize that the new connection is the
  same client. An identity gives the Hub the handle to recognize a returning
  client and reconcile its replicas per owner rather than duplicating them. The
  identity record is the prerequisite; the reconciliation is that bead's work.

- **lux-s4wg (the display socket accepts any client).** The display socket
  handshake already carries a client name (`ConnectMessage(name=…)`), which is the
  display leg of identity. Today only luxd connects to that socket, so the
  identity there is latent. The same identity record should stamp that handshake
  if a non-luxd client ever connects. That is the display leg of this same
  contract, out of scope under the same-user trust model, named here so the two
  legs stay one contract.

- **lux-0shg (command-line parity).** The session-scoped operations — subscribe,
  unsubscribe, publish, receive, and a per-caller `clear` — were held off the REST
  front door in [one-code-path.md](one-code-path.md) precisely because every REST
  caller shared one anonymous scope, so a REST publish could never reach a
  subscriber. Giving each REST and command-line caller a real,
  `ConnectionId`-bearing identity removes that blocker. Those operations become
  expressible over REST once this contract lands; whether to expose them is that
  bead's decision.

## Settled Decisions

These follow from the diagnosis and the target architecture. They are recorded so
the design leaves them closed.

**An owner is an identity, not a bare connection.** A root records the identity
that installed it — kind, name, repository, optional agent — not an opaque
`ConnectionId`. The connection stays the wire key for scope and cleanup; the
identity is the owner.

**Ownership is per-root, and a scene can have several owners.** This is the
existing granularity (`OwnerTracker` keys `(scene_id, element_id)`, `SceneSummary`
already reports `owners` plural), kept unchanged. This design changes the owner
*value* to the identity, not the per-root granularity. A scene holding a `cli`
root and an `mcp-session` root reports both owners.

**Identity is attribution and does not, by itself, change scene lifetime.** The
lifetime model is PR #275's — scenes are durable and survive their session; frames
are the user's removal unit. Recording who owns a root does not decide how long
the root lives. Whether to *add* a lifetime rule that ties a session's roots to
its connection is the fork in Open Question 1, not a default this design assumes.

**The reserved "rest" connection dies.** It was a stand-in for identity-less REST.
Every caller now carries a real identity, so there is no shared pseudo-connection
to protect and no reserved name to collide with; the reserved-key refusal in the
MCP endpoint goes with it.

**There is one identity registry, shared with the menu design.** The `repo` field
is the same field both designs need; the menu design's live-context set is a
projection over this registry. No second registry is built.

**The command-line tool derives its name from context; it does not enroll and does
not attach to a session.** The same-user-localhost trust model authenticates
nothing, so there is no credential to store and no enrollment step. The working
directory and git root yield the name deterministically; a flag or environment
variable overrides it. A repository with an active session resolves to the same
repository context by derivation, so no attach step is needed.

**Same-user-localhost trust is the model.** The Hub records what a client declares
and verifies nothing. luxd is already loopback-only. Identity is attribution, not
access control.

## Ratification

The operator ruled on the open questions on 2026-07-28:

1. **Session-scene lifetime: durable.** An MCP session's scenes survive its
   disconnect, exactly as PR #275 established. Identity changes attribution
   only, never lifetime.
2. **The `identify` first-call: approved, extended with a challenge.** A
   session declares its identity with an `identify` call. In addition — the
   operator's amendment — an operation that requires identity, invoked by a
   caller that has not identified, must return a structured
   "identification required" error, the analogue of a 401/403 challenge in
   web authentication. Callers learn to identify from the response; nothing
   proceeds silently unidentified.
3. **Anonymous REST: rejected.** The operator does not accept identity-less
   REST requests as a valid end state — "I don't see this as valid." The
   shutdown may take a few steps: a transition window in which unidentified
   writes still work (with the challenge response signalling the coming
   requirement) is acceptable, but the end state is that every REST request
   carries an identity. The CLI deriving its identity from the git root and
   sending it remains the mechanism — what dies is the Hub accepting requests
   that carry nothing.

The implementation missions build to these rulings; the design's
derive-where-cwd-present recommendation for anonymous writes is superseded by
ruling 3.

## Open Questions for the Operator (ruled — see Ratification)

These are genuine forks. Each carries a recommendation.

**1. Whether a session's roots should die when its connection drops.** Today they
do not — PR #275 made every scene durable, so an agent's UI survives its session.
This design's identity model makes it *possible* to reintroduce
ephemeral-on-disconnect for `mcp-session`-owned roots (drop those roots in the
disconnect cascade, leaving `cli` and `app` roots standing), because per-root
ownership means the cascade can drop one session's roots without touching a
shared scene. The choice is:

- (a) **Ephemeral session UI** — an `mcp-session` root is dropped when its
  connection drops. An agent's ad-hoc dialog leaves with the agent. This reverses
  PR #275 for session-owned roots.
- (b) **Durable as today** — every root survives its session, and removal stays
  the user's frame close, an explicit clear, or a frame TTL, regardless of owner
  kind.

Recommendation: **(b) durable as today.** PR #275's taxonomy is deliberate and
ratified: a scene is the agent's unit and survives the agent, while the user
controls removal through the frame. An agent that wants its dialog to clean itself
up already has the opt-in tool — a frame TTL — which is more precise than
disconnect-coupling, because it does not lose UI on a transient reconnect. Choosing
(a) would make an agent's UI vanish every time its MCP connection blips, which is
the fragility PR #275 removed. Identity should stay attribution; lifetime should
stay PR #275's. Choose (a) only if the operator now wants agent UI to be genuinely
session-scoped, in which case this is the place to say so — but it is a reversal,
and it is called out as one.

**2. How an MCP session declares its identity.** The choices are: (a) query
parameters alongside `session_key`, so the URL carries
`?session_key=…&repo=…&agent=…`; (b) an explicit `identify` operation the session
calls first, carrying the whole record; (c) piggyback on the first write that
already carries a repo, as `display_mode` does today. Recommendation: **(b) an
`identify` first-call.** It is the one place to declare kind, name, repo, and
agent together; it is symmetric with the REST header; and it does not overload the
connection URL or scatter the record across later calls. The menu design's "report
the repo on connect" becomes a part of this one call, not a separate mechanism.
Choose (a) instead if the record must never be more than a repo, in which case a
query parameter is simplest.

**3. What an anonymous write does — derive or refuse.** A scene-owning write
(`render`, `update`) that arrives with no resolvable identity. The choices are:
(a) auto-derive a fallback identity from whatever the request carries, such as its
working directory; (b) refuse with a named error that says a write needs an
identity. Recommendation: **derive where the request carries a working directory —
the command-line tool always does — and refuse only a write that carries literally
nothing.** This matches "clear ownership, not gatekeeping": nothing legitimate
reaches the refusal path, and a truly context-free write that wants to own a scene
is the one case worth stopping.

**4. Whether the command-line identity is derived every time or persisted.** The
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
where that plugs in is nameable now, so the design leaves a clean place for it.

- The command-line identity file gains a token, stored the way gh stores its
  token, and the command presents it with each request. This is the enrollment
  step this design deliberately omits.
- The Hub verifies the presented token against the declared identity before
  recording ownership, instead of recording the declaration as-is. This is the one
  behavioral change: declaration becomes verified declaration.
- luxd's off-loopback bind, which it refuses today, is enabled together with that
  verification and an origin policy derived from the bind host, exactly as
  [one-code-path.md](one-code-path.md) already stages it.

None of that is built here. It is named so that step one does not accidentally
close the door on it. The identity record this design defines is the same record
step two would verify; step two adds verification, it does not redefine identity.

## Proposed PR Decomposition

Each PR is one rollback-coherent unit.

**PR 1 — the identity record and the shared registry.** Introduce the
`ClientIdentity` record (kind, name, repo, optional agent) and make the Hub
session registry hold it, populated from what each client declares on connect.
This is the shared foundation the menu capability model's PR-1 folds into. It is
additive: nothing owns-by-identity yet, so it lands and is exercised on its own.

**PR 2 — the identity becomes the per-root owner, and REST resolves it
per-request.** Change the owner value recorded per root from a `ConnectionId` to
the identity, and change each entry in `SceneSummary.owners` and the new
`HubClient.identity` to the structured shape. Delete `RESERVED_REST_CONNECTION`,
its `DEFAULT_SCOPE`, and the reserved-key refusal. That last part is the bulk of
the PR, not a rename. The REST layer does not resolve a caller's identity
per request today — `RestSurface` and its routers take one `scope` at construction
(`rest/app.py`, `DEFAULT_SCOPE`), so a per-request identity inverts that wiring.
Each route must read the caller's identity from the request (a header, via a
dependency or middleware) and pass it into the operation, rather than share one
construction-time scope. Size the PR for that inversion. The disconnect cascade is
unchanged in this PR, because recommendation (b) keeps scenes durable; if the
operator rules (a) on Open Question 1, dropping a session's roots is an added,
separately-committed change within this unit.

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
  registry, the reserved-`"rest"` scope this design retires, and the loopback-only
  bind policy step-two security extends.
- [menu-capability-model.md](menu-capability-model.md) — the session-context
  registry this design's identity record subsumes, and the capability model that
  reads the shared `repo` field.
- [target/introspection-api.md](target/introspection-api.md) — the `list_clients`
  and `list_scenes` read surface whose owner shapes this design makes meaningful.
- PR #275 (the scene-frame lifecycle) — the ratified rule that scenes are durable
  and frames are the user's removal unit, which this design's lifetime section
  must not silently change.
