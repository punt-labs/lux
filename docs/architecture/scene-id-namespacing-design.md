# Connection-Scoped Store Keys — Scenes and Frames Cannot Alias Across Connections

- **Status:** ratified for DES-086. The operator ruled on all five decisions
  below on 2026-08-16: Decision 1 EXTRACT, Decision 2 UNCONDITIONALLY (NOW),
  Decision 3 ACCEPT AS DOCUMENTED (no follow-on bead), Decision 4 Z-SPEC
  REQUIRED (operator override of both gvr's and djb's "not required"
  recommendation), Decision 5 COMPOSE ON CALLER'S CONNECTION ONLY (no
  `owner=` override — narrower than gvr's recommendation (a) below;
  `inspect_scene` has no admin path). Implementation mission
  `m-2026-08-16-007`, worker `rmh`.
- **Proposed ADR number:** DES-086 (next after DES-085, the crash-respawn
  quarantine design, PR #354 — DESIGN.md's own numbered headings currently end
  at DES-067; DES-068 and DES-085 are shipped but not yet pasted into
  DESIGN.md as ADR entries. That gap is not this design's to close.)
- **Author:** gvr, design mission `m-2026-08-16-006`.
- **Evaluator:** djb (security lens).

## Abstract

`HubDisplay` stores every scene and frame under the exact string a client
submitted. Nothing about that string is namespaced to who submitted it. A
second client — another agent, another applet, the same tool running in a
second session — that happens to choose the same string does not get an
error; it gets the first client's scene, wholesale, silently. This is the bug
vox hit running in two Claude Code sessions at once: both push a
`"music-player"` scene, and the second one evicts the first's widget from the
shared display.

This document proposes that the Hub never use a client-submitted string as a
store key directly. Every scene id and frame id becomes, at the Hub boundary,
the composition of the writing connection's own id and the caller's local
label: `ConnectionScopedId.compose(connection_id, local_id)`. A provider still
writes `scene_id="music-player"` — the same call, the same one-line
ergonomics — and the Hub does the composing, transparently, on every call.
Two connections choosing the identical local label can no longer collide,
because they cannot construct the identical composed key: composition is a
pure function of `(connection_id, local_id)`, and no client controls another
client's `connection_id`.

The wire protocol between agent and Hub is unchanged: `show`, `update`, and
`clear` keep their existing `scene_id: str` parameter and existing semantics.
The Hub↔Display protocol is unchanged: `SceneMessage.id` and
`ScenePresentation.frame_id` are already opaque strings from the Display's
point of view, and now simply carry a structured value instead of a raw one.
Vox needs no code change.

## The security invariant

> No client, by accident or by malice, can install, replace, or remove a
> scene or frame under a store key another identifying connection has already
> claimed for itself — because the store key is a value neither client
> controls the whole of. It is composed from the writing connection's own id,
> which the writer does not choose, and the writer's own local label, which
> the writer does choose but which contributes only its own half of the key.

This is deliberately stronger than "the Hub checks ownership before
overwriting." A check can have a bug, a missed call site, a race between the
check and the write. Making collision *unrepresentable* — the two inputs to
composition are never both under one client's control — removes the check
from the trusted computing base entirely. `oo.md`'s stance on illegal states
applies one layer up from a type: the illegal *state* here is "two
connections' scenes share a key," and this design makes that state
impossible to construct rather than making it detectable.

**This invariant is conditional on transport, and the condition matters.**
"Which the writer does not choose" is true without qualification for
`mcp-session`-kind connections — the transport itself assigns `ConnectionId`
from a per-session `ContextVar` (`tools/server.py:45`), outside anything the
caller declares. It is not true in the same unconditional sense for `cli`-
and `applet`-kind connections, whose `ConnectionId` is `connection_for`'s
deterministic hash of fields the caller *does* declare over REST
(`connection_identity.py:39`). A process willing to declare the same fields
a target connection would declare gets that target's exact `ConnectionId`,
honestly, through the same `identify()` call every legitimate client uses.
This is not a defect in `ConnectionScopedId` — the class still composes
correctly from whatever `ConnectionId` it is given — it is a scope boundary
on what "the writer does not choose" can promise for those two transports.
See the `connection_for` residual and Decision 3 below for the full
accounting; djb's security review (round 2) confirmed this reading against
the code.

## The ergonomic invariant

> A provider (agent, applet, CLI) chooses a short, human-readable id local to
> itself — `"music-player"`, `"board"`, `"dialog"` — on every `show`,
> `update`, or `clear` call, exactly as it does today. The Hub composes the
> connection-scoped store key on every one of those calls, using identity
> information the connection already carries. The provider never sees,
> constructs, parses, or reasons about the composed form, and never has to
> think about whether `"music-player"` is taken.

Every existing caller of `show`/`update`/`clear` already satisfies this
invariant's precondition — they already pass a short, self-chosen
`scene_id`. Nothing about the call changes. What changes is invisible to the
caller: the string that ends up in `HubDisplay`'s internal maps is not the
string the caller sent.

## Current mechanics (what actually happens today, traced 2026-08-16)

1. **The client-submitted `scene_id` becomes the literal store key.**
   `RenderRequest.scene_id: str` (`operations/models/render.py:54`) flows
   through `SceneSubmission.of` (`operations/scene_submission.py:41`)
   unchanged into `SceneId(scene_id)`, and `SceneInstaller.install`
   (`operations/scene_installer.py:49`) passes that `SceneId` straight to
   `HubDisplay.show_scene` (`domain/hub/hub_display.py:385`). Nothing between
   the wire and the store touches the string.

2. **`replace_scene` evicts unconditionally, by whoever's roots are already
   there — not by whether the caller may claim the id.**
   `HubDisplay.replace_scene` (`hub_display.py:354`) opens with
   `self._eviction.drop_scene_roots(scene_id)`, dropping every existing root
   *whatever its owner*, then installs the new caller's roots under the new
   caller's `Owner`. There is no "does anyone else already hold this
   `scene_id`" check anywhere in this path. The per-element ownership guard —
   `OwnerTracker.require_ownership`, keyed by `(scene_id, element_id)`
   (`domain/hub/owner_tracker.py:58`) — only ever fires on `SetProperty` and
   `RemoveElement` against an element that is *already installed*. It has
   nothing to say about who may install the *first* root under a given
   `scene_id`, because by the time it could check, `drop_scene_roots` has
   already cleared the previous owner's roots out of the index.

3. **`frame_id` has the identical shape, with no ownership check at any
   granularity.** `FrameSpec.frame_id: str | None = None` defaults to the
   scene id when the caller names none (`RenderRequest.presentation`,
   `operations/models/render.py:107`).
   `ScenePresentationRegistry`/`FrameLifecycle` (referenced from
   `hub_display.py:44-58`) key by `frame_id` with no owner field in
   `ScenePresentation` at all — I grepped `frame_lifecycle.py` and
   `scene_presentation.py` for `owner`/`Owner` and found zero hits outside
   two docstrings that say a scene's roots are torn down "whatever its
   owner." Frame collision is not merely under-enforced; there is no
   enforcement mechanism to have missed.

4. **The menu-callback system already closed the identical class of bug, by
   the identical mechanism I am proposing.** `SessionCallback.id`
   (`domain/hub/session_callback.py:45`) is a caller-chosen label, exactly
   like a `scene_id`. But a callback's raw `id` is never a Hub-wide dict key
   — it lives in `Mapping[str, SessionCallback]` scoped *inside* one
   session's own `ListenerSlot` (`domain/hub/listener_slot.py:39`), so two
   sessions' callback ids cannot collide by construction: they are different
   dicts. And where a callback *does* need one wire-unique id — the menu
   leaf a click fires on — `CallbackInvocation.menu_id`
   (`session_callback.py:92`) composes exactly the shape this document
   proposes: `f"{connection_id}{_ID_SEPARATOR}{callback_id}"`, with
   `_ID_SEPARATOR = "\x1f"` (the ASCII unit separator) and a field validator
   on `SessionCallback.id` that rejects any caller-submitted id containing
   that separator, so the join always round-trips
   (`session_callback.py:48-60`). This shipped with DES-058/DES-067's menu
   work. Scene and frame ids never got the equivalent treatment. This design
   gives them one, in the same shape, reusing the same separator.

5. **`ConnectionId` is already the Hub's authoritative "who is this" anchor,
   and it is derived two different ways depending on transport — both
   already collision-resistant for the reported bug's actual path.** An MCP
   tool call's `ConnectionId` comes from `_session_key`
   (`tools/server.py:45`), a `ContextVar` the streamable-HTTP transport sets
   per live session — genuinely unique per connection, independent of
   anything the agent declares via `identify()`. A REST push or a WebSocket
   listen leg (applets, and any CLI invocation that opens one) derives its
   `ConnectionId` via `connection_for` (`connection_identity.py:39`), a
   deterministic hash of the *declared* identity fields `(kind, name, repo,
   agent)` — built that way on purpose, so a client's REST leg and WebSocket
   leg resolve to the same connection. I traced whether this second
   derivation reintroduces a collision for the reported bug and found it
   does not: vox's own music-player push happens over the MCP-session
   transport (each Claude Code session's own live connection), which is the
   transport-session-key derivation, not the declared-fields hash. See the
   Threat Model and the "connection_for residual" decision below for where
   the declared-fields derivation *does* still carry a narrower, pre-existing
   gap this design does not close.

## Decision: Hub-side composition, anchored on `ConnectionId`

The mission's three candidate shapes:

- **(a) HUB-SIDE COMPOSITION** — the wire `scene_id` stays a short string;
  the Hub composes a stored key at write time; the raw wire id is never a
  store key.
- **(b) WIRE-LEVEL COMPOSITE** — the wire message itself carries a composite
  value the client can only construct from valid identity components.
- **(c) CALLER-PREFIX ENFORCEMENT** — the Hub rejects any `scene_id` that
  does not begin with the caller's own identity prefix; the caller composes,
  the Hub polices.

**I am choosing (a), and anchoring the composition specifically on
`ConnectionId` rather than re-deriving a fresh `(kind, name, repo,
session_pid)` tuple.**

(b) fails the ergonomic invariant outright — the operator's own framing is
"the provider should probably have simple id schemes and we should namespace
them automatically" — automatically is the load-bearing word. Under (b),
every client library (vox's, the CLI's, a future applet's) would need to
reproduce the Hub's exact composition logic client-side and keep it in sync
across repos. That is duplicated logic across trust and version boundaries,
which is worse than the bug it fixes.

(c) is a weaker version of the same mistake: the caller still does the
composing, the Hub just checks its work. This still requires every caller to
carry identity-formatting logic, and — the sharper problem — the check is a
place a bug can live. (a) removes the check because there is no longer
anything to check: the client-submitted string is never eligible to be a
whole store key on its own.

**Why anchor on `ConnectionId` rather than a fresh tuple.** The operator's
sketch composes from `(kind, name, repo, session_pid)` directly. I traced
what that tuple would actually buy over the `ConnectionId` the Hub already
derives from those same fields (`connection_for`, item 5 above) and found:
nothing, for the cases that matter, and one real gap that a fresh tuple would
not close either (see the `connection_for` residual below). `ConnectionId`
is already the value `Owner`, `OwnerTracker`, `ClientSession`,
`MenuGroupKey`, and DES-068's whole reconciliation model treat as "this
connection, distinctly, for as long as it is live." Re-deriving a parallel
tuple for scene/frame keys means two independent encodings of "who is this"
have to be kept in agreement forever. One encoding, reused, is the smaller
surface and the one `oo.md`'s composition-over-duplication stance would
choose.

### The class

```python
# domain/hub/id_separator.py — new, tiny, shared

"""The ASCII unit separator joining a connection id to a caller-local label.

Shared by every composite wire-adjacent id the Hub derives from a connection
plus a caller-chosen string — the menu-leaf id (CallbackInvocation) and the
connection-scoped scene/frame id (ConnectionScopedId) both import this one
constant, so "no agent-chosen id or hashed connection id contains it" is
proven once, in one place, not reasserted per class.
"""

ID_SEPARATOR: Final = "\x1f"
```

```python
# domain/hub/connection_scoped_id.py — new

"""ConnectionScopedId — a caller-chosen id, namespaced to who chose it.

The store key a scene or frame is installed under is never the raw string a
client submitted. It is this composite, so two connections can never alias
the same store key even when they submit the identical raw string — the
collision is unrepresentable, not merely rejected.

Mirrors CallbackInvocation's menu-leaf-id composition
(domain/hub/session_callback.py), which closed the identical class of
collision for menu callbacks under DES-058/DES-067. This class exists
because scene and frame ids never received the same treatment.
"""


@final
@dataclass(frozen=True, slots=True)
class ConnectionScopedId:
    connection_id: ConnectionId
    local_id: str

    def __post_init__(self) -> None:
        if not self.local_id.strip():
            msg = "local id must be a non-empty, non-blank id"
            raise ValueError(msg)
        if ID_SEPARATOR in self.local_id:
            msg = "local id must not contain the unit separator"
            raise ValueError(msg)

    def __str__(self) -> str:
        return f"{self.connection_id}{ID_SEPARATOR}{self.local_id}"

    @classmethod
    def compose(cls, connection_id: ConnectionId, local_id: str) -> str:
        """Return the namespaced store-key string for `local_id`."""
        return str(cls(connection_id, local_id))
```

A malformed `local_id` (blank, or carrying the separator — which a client
could never have produced honestly, since the separator is a control
character no UI ever asks a user to type) raises `ValueError` at composition
time, per PY-EH-8: this is a value-producing function, so a `local_id` it
cannot compose from is a boundary error, not a silent fallback.

**Where that `ValueError` is caught — corrected, per djb's round-2 review.**
Round 1 of this design cited `IdentityOperations.identify`
(`operations/identity.py:52`) as the existing catch site this would mirror.
djb read that site end to end and found it wraps a **pydantic**
`ValidationError` from `ClientIdentity.model_validate`, on the `identify`
path only — it has nothing to do with `render`/`show`/`update`/`clear`, and
no catch site for `ConnectionScopedId`'s plain-dataclass `ValueError` exists
anywhere on those paths today. Nor is the empty-`local_id` case theoretical:
`RenderRequest.scene_id: str` (`operations/models/render.py:54`) carries no
`Field(min_length=1)`, so `show(scene_id="")` reaches `__post_init__`'s
raise with nothing between it and the tool boundary.

The implementation adds an explicit catch at each of the three composition
call sites this design introduces: `SceneInstaller.install`,
`SceneOperations.update`, and `SceneClearer.clear`, each wrapping its
`.scoped(...)`/`ConnectionScopedId.compose` call with
`except ValueError as exc: return OpError(code="invalid_request",
reason=str(exc))` — the same shape `RenderRequest.parse` already uses for
its own pydantic `ValidationError` (`operations/models/render.py:66-69`).
This is a mechanical, three-site addition, not a design change: a
construction this design specifies as fail-*closed* must also fail
*clean* — into the same bounded `OpError` surface every other boundary
rejection in this codebase uses — rather than into whatever
FastMCP/FastAPI does with an uncaught exception reaching a request handler.
The implementation mission's success criteria must include a test that
calls `show(scene_id="")` and one with a `scene_id` carrying the unit
separator, asserting a clean `OpError` in both cases, never an exception
escaping the tool boundary.

### The one choke point

`SceneInstaller.install` (`operations/scene_installer.py`) is already,
by its own docstring, "the one install: every scene reaches `HubDisplay`
through here, whether a client submitted it over the wire or the Hub
constructed it itself." That is the correct place to compose, because it is
the only place the `owner: ConnectionId` a scene is being attributed to is
always available — including the Hub-internal path where luxd writes a
scene *for* a client that is not the one calling (the docstring's second
sentence). Composing here, once, covers `render`, `show_table`,
`show_dashboard`, `details_scene`, and any future convenience built on
`install`, with no second call site to keep in sync.

`SceneSubmission` gains one method:

```python
def scoped(self, owner: ConnectionId) -> Self:
    """Return this submission with its scene and frame ids namespaced to `owner`."""
    return replace(
        self,
        scene_id=SceneId(ConnectionScopedId.compose(owner, str(self.scene_id))),
        presentation=self.presentation.scoped(owner),
    )
```

`ScenePresentation` gains the matching `.scoped(owner)`, composing
`frame_id` the identical way. Because `FrameSpec.frame_id` already defaults
to the raw `scene_id` when the caller names none
(`RenderRequest.presentation`), composing each field independently from its
own raw value, with the same owner, naturally preserves that default: a
scene shown with no explicit `frame_id` still ends up with `frame_id ==
scene_id` after composition, because composing the identical raw string
with the identical owner twice yields the identical composed string. No
special case is needed for the default-frame path.

`SceneInstaller.install` calls `submission.scoped(owner)` once, before
`self._display.show_scene(...)`. This is PY-OO-5 in the direction the
mission's cited rules demand: the composition is a method on the class that
owns the data (`SceneSubmission`/`ScenePresentation`), not a free function in
`scene_installer.py` that reaches into their fields.

**`update` and `clear` compose the same way, at their own existing
boundary.** `SceneOperations.update` (`operations/scenes.py:143`) currently
does `sid = SceneId(scene_id)` directly on the caller-submitted string; this
becomes `sid = SceneId(ConnectionScopedId.compose(scope.connection_id,
scene_id))`. `SceneOperations.clear`'s optional `scene_id` filter
(`operations/scene_clearing.py:53`, compared against `elements_owned_by`'s
already-composed keys) needs the identical rewrite before it reaches
`SceneClearer.clear`. Both already scope by `scope.connection_id` (a caller
can only ever `update`/`clear` a scene it is the connection for); composing
with that same connection id at the string layer changes nothing about
*what* the caller may address, only what the address *is* internally. A
caller updating "its own `music-player`" continues to update its own
`music-player` — it is simply, transparently, no longer able to spell
"its own" in a way that happens to also spell someone else's.

**One other `SceneId(...)` construction exists outside this write-set —
verified as not a gap.** `domain/hub/element_invocation_resolver.py:65`
constructs a raw `SceneId` from `RemoteEventHandlerInvocation.scene_id`.
djb traced the full path: that field is a display-echo of a click, carrying
the store's own (already-composed, post-design) id verbatim —
`display_link.py:455-456` sends `id=scene_id` straight from what the
replicator read out of the store, with no re-derivation. The value arriving
at `element_invocation_resolver.py:65` is therefore already a fully
composed key; `SceneId(scene_id)` there is a correct opaque cast, not a
second raw-key write path that needs `.scoped()`. Named here so a future
reader does not re-open it.

## Threat model

Three adversaries, per the mission's framing, under the **same-user-localhost
trust model** this codebase already operates under: the Hub verifies
well-formedness of a declared identity, not the identity's truth
(`client_identity.py:1-14`). Composition does not change that trust model —
it changes what a client's honest-or-dishonest *string choice* can do to
another client's state.

**(1) A well-meaning provider that picks a colliding short id in good
faith.** This is the reported bug exactly — vox, in two sessions, both
choosing `"music-player"` with no coordination between them, because
coordination was never their job. **Fully defended.** Two distinct
`ConnectionId`s compose two distinct store keys from the identical
`local_id`; there is no code path by which they collapse.

**(2) A careless provider whose own id scheme collapses when two of its own
sessions run.** This is (1) restated one level down — "its own sessions"
means two *connections*, and the defense is identical: each connection's own
`show()` calls compose against that connection's own id. A single connection
calling `show(scene_id="music-player")` twice in a row still updates one
scene (that is `replace_scene`'s existing, correct, intended behavior,
unchanged) — this design does not turn legitimate re-shows into new scenes,
because both calls compose to the identical key.

**(3) A hostile applet, under the same-user-localhost trust model, trying to
hijack a scene another applet or agent owns.** **Defended against the
specific act of writing under another connection's key — not defended
against everything a hostile local process could do.** The trust model this
codebase already accepts (`client_identity.py`: "under the same-user-
localhost trust model the Hub records the declaration and verifies nothing;
identity here is for attribution, not access control") means a hostile
process on the same machine, as the same user, can already: open its own
honest connection and declare whatever `kind`/`name`/`repo`/`agent` it
likes (nothing stops a process from lying about its own identity — that is
attribution, not authentication); read another client's scenes via
introspection (`list_scenes`/`inspect_scene` are not access-controlled per
caller); consume Hub resources by opening many connections. None of that
changes with this design, and none of it is what the operator asked this
design to close. What this design closes is narrower and precise: **a
hostile process cannot make its own store-key collide with a target's store
key**, because it does not control the target's `ConnectionId` half of the
composition, only its own. It could try to guess or brute-force a target's
`ConnectionId` and construct a raw `local_id` string that happens to embed
the separator and a copy of that guessed id — but `ConnectionScopedId`'s
`local_id` validator rejects any input containing `ID_SEPARATOR`
(`\x1f`, a control character), so that construction is rejected at the
boundary before it ever reaches composition, exactly as
`SessionCallback._reject_separator` already does for callback ids.

**What this design explicitly does not defend against, named plainly:** a
same-user-localhost process forging its declared identity (out of scope —
that is the standing trust model, not this bug); a same-user-localhost
process reading another connection's scene content via introspection (out
of scope — introspection has no owner-scoping today and this design does
not add any); resource exhaustion by opening many connections (out of
scope — no rate limiting exists anywhere in this codebase today).

## Wire-protocol change: none, on the agent↔Hub leg or the Hub↔Display leg

**Agent↔Hub.** `show`, `update`, and `clear`'s MCP tool signatures
(`tools/write_tools.py`) are unchanged — same `scene_id: str` parameter,
same caller-visible contract. `identify`'s three-field declaration
(`kind`/`name`/`repo`/`agent`) is unchanged; this design adds no new field
to `ClientIdentity` and derives nothing new from `identify`. The only new
types are Hub-internal (`domain/hub/connection_scoped_id.py`,
`domain/hub/id_separator.py`) — never serialized to a client, never
deserialized from one.

**Hub↔Display.** `SceneMessage.id` and `ScenePresentation.frame_id`
(`protocol/messages/scene.py`) are already opaque `str` fields from the
Display's point of view — nothing in `display/replica/` inspects their
internal structure, only compares and stores them. This design changes what
*value* the Hub puts into those existing fields; it adds no field, no
message, no codec change. `HubManifestMessage.scene_ids`
(DES-068) will now carry composed strings instead of raw ones — DES-068's
own mechanism (purge-what-the-manifest-doesn't-name) is unaffected, because
it treats every scene id as an opaque comparison key already; see Impacts on
Other ADRs below.

**Introspection is the one place a wire-adjacent shape actually changes**,
additively. `SceneSummary` (`operations/models/query_scenes.py`) gains one
field:

```python
class SceneSummary(BaseModel):
    scene_id: str  # now the composed store key
    local_id: str  # NEW — the caller's own id, as it declared it
    element_count: int
    frame_id: str
    owners: list[SceneOwner]
    ...
```

`local_id` exists so an agent reading `list_scenes` never has to manually
strip its own `ConnectionId` prefix off `scene_id` to recognize "this is the
scene I called `music-player`." `owners[].identity` already carries the
structured `ClientIdentity` (kind/name/repo/agent) of whoever owns a scene's
roots (`operations/models/query_ownership.py:17`) — that already answers
"whose scene is this" in human terms; `local_id` answers "what did they call
it." Together they make the composed `scene_id` string legible without an
agent ever needing to parse `ConnectionScopedId`'s own separator convention.

**`inspect_scene` is not addressed by the `SceneSummary` field above, and
that is a real gap djb's round-2 review found.** `inspect_scene`
(`operations/queries.py:73`) does a separate, raw, uncomposed
`SceneId(scene_id)` lookup — not a `SceneSummary` read — against what
becomes, after this design ships, a composed store. This design's original
write-set never accounted for it. See Decision 5 below.

## The frame-id dimension

Namespaced identically to scene ids, by the same `.scoped(owner)` call,
described above. **This is a real, disclosed behavior change, not a null
change:** today, nothing prevents two different connections from
deliberately choosing the same `frame_id` to tab their scenes together (no
ownership check exists to have stopped them). After this design, two
different connections' default or explicit `frame_id`s can never collide,
namespaced, and so two different connections can no longer land in one
frame by choosing the same string.

I read `frame_lifecycle.py`, `scene_presentation.py`, `render.py`, and
`scene_installer.py` looking for a caller that *relies* on cross-connection
frame sharing as a feature and found none — every renderer I traced
(`show`, `show_table`, `show_dashboard`, `details_scene`) always composes
its own `frame_id` from its own scene's data, never from another
connection's. But I did not exhaustively trace the Clients-menu/menubar
rendering paths (`domain/hub/callback_menu.py`, `menu_group_key.py`) for a
deliberate multi-connection frame aggregation, and the mission's own
scoping excludes the menu system from a full audit here. See Decision 2
below.

## The menu-registration dimension: already closed, cited above

`SessionCallback.id` is already scoped inside one session's own
`ListenerSlot` (item 4 in Current Mechanics), and the wire-visible
menu-leaf id is already `CallbackInvocation`'s connection-plus-callback
composite, using the exact separator and rejection pattern this design
reuses. **No change needed here.** This design's `ConnectionScopedId` and
the existing `CallbackInvocation` are, after this design ships, two
instances of one idea rather than one instance and one open gap — worth
naming as a small, real follow-on cleanup, not required for this design to
ship: `ID_SEPARATOR` moving into its own module (above) means
`session_callback.py` can import it instead of defining its own private
copy, so the two composite-id classes provably use the same separator
rather than two separately-declared `"\x1f"` literals that could drift.

## The client-identity dimension

**Anonymous clients cannot write a scene at all, today, unchanged by this
design.** `Scope.connection_id` (`operations/scope.py`) is required by
every write operation's signature; there is no code path where `render`,
`update`, or `clear` runs without one. Whether that `ConnectionId` came from
a fully `identify()`-declared connection or one that never called
`identify` (Owner.identity is `None` in that case,
`domain/hub/owner.py:29`) does not matter to composition — `.scoped(owner)`
only needs the `ConnectionId`, which every connection has from the moment
it is registered (`HubDisplay.register_client`,
`hub_display.py:170`), independent of whether an identity was ever
declared. DES-057's "anonymous REST rejected" ruling is about identity
*attribution* — whether `Owner.identity` is populated for introspection —
not about whether a write can happen; this design does not touch that
boundary and does not need to.

**The MCP-session path is the one that matters for the reported bug, and it
is already safe without any change to `ClientIdentity`.** As traced in item
5 of Current Mechanics, an MCP tool call's `ConnectionId` comes from the
transport's own per-session key, not from anything the agent declares. Two
Claude Code sessions running vox, whatever they each pass to `identify` (or
whether they call it at all), get two distinct `ConnectionId`s from the
transport itself. This is why anchoring on `ConnectionId` rather than a
freshly re-derived `(kind, name, repo, session_pid)` tuple is not merely
simpler — it is *stricter* on the path that produced the bug, because it
inherits a distinctness guarantee `identify()`'s declared fields do not, on
their own, provide.

**The residual gap, named plainly: `connection_for`'s declared-fields hash
can still collapse two genuinely different connections onto one
`ConnectionId`, on the REST/WebSocket-paired leg only.**
`connection_for` (`connection_identity.py:39`) hashes `(kind, name, repo,
agent)` — no `session_pid` in it. For `applet` connections this is already
closed: `ClientIdentity._validate_applet_shape`
(`client_identity.py:126`) rejects any applet whose `name` does not embed a
session pid via `applet_name_format.format_name`, so two Claude Code
sessions running the same applet program always declare different `name`s
and hence different `ConnectionId`s. For `cli` connections it is *not*
closed: `CliIdentity.resolve` (`cli_identity.py:36`) sets `name = override
or repo.name` — two unrelated terminal invocations of bare `lux show
<id>`, in the same repo, with no `--as`/`LUX_CLIENT` override, declare
identical `(kind, name, repo, agent)` and therefore share one
`ConnectionId`. Under this design, they would therefore also share one
scoped namespace and *could* still collide on an identical `scene_id`.

I am naming this as a residual, not silently absorbing it into this
design's scope, for two reasons. First, it is not the cause of the reported
bug (vox's collision is the MCP-session path, already fixed). Second, I
believe — but cannot rule alone — that it is *by design*, not an oversight:
the CLI's own ergonomic contract is "run `lux show status` again to update
the same scene," which only works if repeated bare invocations from one
repo share an identity. Making bare CLI invocations distinct-by-default
would silently turn every "refresh my dashboard" re-run into a pile of new,
never-cleared scenes — the CLI already ships the escape hatch a caller who
*wants* its own namespace needs (`--as`/`LUX_CLIENT`), and I do not think
this design should overrule that existing, shipped ergonomic choice on its
own authority. See Decision 3 below.

**What accepting this residual actually costs, stated precisely — not
"two accidental invocations colliding by coincidence."** djb's round-2
review sharpened this beyond the framing above. `connection_for`'s hash
requires no guessing: a hostile same-user-localhost process that wants to
*become* a target `cli`-kind connection needs only call `identify()` (or
push over REST, which resolves identity implicitly) with the identical
`(kind="cli", name, repo, agent)` tuple `CliIdentity.resolve` would have
produced for the target — a tuple built entirely from public, declared
information (a repo's directory name and absolute path), not a secret. At
that point `ConnectionScopedId.compose` does exactly what it is specified
to do; the writer's own `ConnectionId` is, by the Hub's own rules, now the
same as the target's. This is not a new capability this design creates —
the identical `connection_for` collision already grants a hostile process
the target's exact `Owner` for `SetProperty`/`RemoveElement`
(`owner_tracker.py:58-68`), which is strictly worse (full element mutation,
not merely a scene-id collision) — but Decision 3's recommendation to
accept the residual should be read as accepting *that* capability's narrow
extension to scene ids, not as accepting a coincidence between well-meaning
scripts.

**Applet-kind narrows the same class without closing it.**
`APPLET_NAME_RE` (`client_identity.py:126-145`) forces an applet's declared
name to embed its own session pid, so two honest applet instances never
collide by accident. A hostile process can still read that pid from `ps` on
the same machine as the same user and declare it deliberately — a higher
bar than the CLI residual (requires observing the target's pid, not just
its repo path) but the same class of guarantee: same-user-localhost, not a
different security boundary.

## The vox migration path

**Transparent. Vox needs no code change, and no coordination.** Vox's
music-player push runs over the MCP-session transport, whose
`ConnectionId` already distinguishes the two colliding sessions from the
reported bug without vox declaring anything new. Vox continues to call
`show(scene_id="music-player", ...)` exactly as it does on v0.22.1 today;
the Hub composes a distinct store key per session underneath that call, and
two sessions' music-player widgets now coexist instead of overwriting each
other. There is no vox-repo bead this design needs to open, and no biff
message this design needs to send before shipping — only a live-verified
demo after shipping (see Test Surface) confirming vox, unmodified, on two
sessions, without collision.

## Introspection

Covered above under Wire-Protocol Change: `SceneSummary` gains `local_id:
str`. `FrameSummary` (`operations/models/query_scenes.py:32`) is left
alone — a frame's `frame_id: str` is already opaque there and frames do not
carry an `owners` field the way scenes do (frame ownership is not tracked
anywhere in the code today, and this design does not add tracking for it,
only namespacing — see Decision 2). No display-side surface (menu labels,
frame titles, tooltips) ever shows a raw `scene_id`/`frame_id` string today
— `menu_label` is deliberately derived from `ClientIdentity`, never from a
scene id — so no human-facing label needs any change.

## The z-spec question

**Not required**, and I want to state the reasoning plainly enough that
djb's security review can independently check it rather than take it on my
word, given this codebase's own history of missed interleavings on
DES-037/038.

CLAUDE.md's z-spec rule triggers on: concurrency/interleaving over shared
state; lock disciplines, especially new or altered ones; stateful protocols
with an order invariant ("operation A must complete before operation B");
or the second occurrence of the same class of defect. I checked each:

- **No new lock, no new lock order.** `ConnectionScopedId.compose` is a
  pure function — no store access, no lock acquisition. The write it feeds
  (`HubDisplay.show_scene`/`replace_scene`) already runs under the existing
  `StoreLock.write()` (`hub_display.py:159-166`), unchanged by this design.
- **No new interleaving.** DES-068's z-spec requirement existed because two
  *different Hub connections*, racing across a straggling in-flight message
  and a fresh manifest, could land in either order and one order was wrong
  (`hub-display-reconciliation-design.md`, "Why this is required," Ground
  1). This design introduces no analogous race: composition happens
  synchronously, inline, in the same request that already holds (or is
  about to take) the write lock, using data — the caller's own
  `ConnectionId` — that is already resolved before the request begins, not
  data that could still be in flight from a second connection.
  Two calls from the *same* connection racing each other for the same
  `local_id` compose to the *same* key, so they hit the existing
  single-writer serialization `StoreLock` already provides — not a new
  concurrency question, the same one every `show()` call already answers.
- **No recurrence.** This is the first time a scene/frame id collision has
  been named as a defect in this codebase. (The menu-callback system closed
  the analogous class before it ever became a bug — see item 4 in Current
  Mechanics — so there is no first occurrence to count there either.)

If djb's review finds an interleaving I have missed — most plausibly around
the `.scoped()` call composing against a `ConnectionId` that is itself
mid-transition (a reconnect, a preemption under DES-068) — that is exactly
the kind of finding that should escalate back and force a z-spec track
before implementation, per Decision 4 below.

## Test surface

- **Unit, over `ConnectionScopedId` directly:** two distinct
  `ConnectionId`s composing the identical `local_id` produce distinct
  strings; the same `ConnectionId` composing the same `local_id` twice
  produces the identical string (idempotent re-show); a `local_id`
  containing `ID_SEPARATOR` raises `ValueError`; a blank or
  whitespace-only `local_id` raises `ValueError`.
- **Unit, over `SceneSubmission.scoped`:** a submission with an explicit
  `frame_id` and one with the default-to-`scene_id` frame both compose
  correctly, and the default case still yields `frame_id == scene_id`
  post-composition.
- **Integration, two identified connections racing on a colliding simple
  id:** construct two `HubDisplay` writes from two distinct
  `ConnectionId`s, both `show(scene_id="music-player", ...)` — assert both
  scenes exist afterward (`list_scenes` shows two entries, each with
  `local_id="music-player"` and a distinct `owners[0].connection_id`), and
  assert neither call evicted the other's roots.
- **Regression, over `update`/`clear`:** a connection's `update` against
  its own `music-player` continues to patch the scene it created; a second
  connection's `update` against the identical raw `scene_id="music-player"`
  operates on *its own*, separate scene, never the first connection's.
- **The demo gate this design's implementation PR must clear (per
  `WORKFLOW.md`), stated in the mission's own words:** a live `show()` from
  vox on one Claude Code session, a live `show()` with the identical
  `scene_id` from a second session, and `list_scenes` proving both coexist
  — driven through vox's real, unmodified entry point, not a synthetic
  test double standing in for it.

## Impacts on other ADRs

- **DES-057 (Client Identity).** No change to `ClientIdentity`'s fields or
  validators. This design reads `ConnectionId`, which DES-057's identity
  layer already produces; it adds nothing to what DES-057 declares and
  changes no ruling DES-057 made.
- **DES-068 (Hub/Display Scene Reconciliation).** No change to the manifest
  mechanism, the single-owner-preemption invariant, or the z-spec model
  (`hub_display_reconciliation.tex`). `HubManifestMessage.scene_ids` carries
  composed strings after this design ships — the manifest already treats
  every entry as an opaque comparison key (`SceneReplica`'s stale-frames
  query compares string equality, never structure), so this is a value-shape
  observation, not a mechanism change, and needs no re-verification of
  DES-068's own invariants.
- **DES-085 (Crash-Respawn Quarantine).** No interaction. Quarantine keys
  by `scene_id` too (`QuarantineRegistry`, referenced from
  `hub_display.py:51,296-351`) and, like DES-068, treats it as an opaque
  key throughout — quarantining a composed scene id works identically to
  quarantining a raw one.
- **DES-058/DES-067 (Menu callbacks, applet grouping).** No change. Cited
  throughout this document as the precedent this design generalizes, not a
  system this design touches.

## Verification

- `make check-oo` must show improvement on every touched file, per the
  ratchet. `operations/scene_submission.py` and
  `operations/models/render.py` are small, clean modules already; the two
  new classes (`ConnectionScopedId`, and the `ID_SEPARATOR` extraction from
  `session_callback.py`) are themselves an OO-positive move — a composite-id
  concept promoted from one inline literal into a real, validated,
  `@final` value class, mirroring `CallbackInvocation`'s already-shipped
  shape rather than inventing a new one.
- The unit and integration tests above are the merge gate for the
  collision-impossibility claim — "two connections cannot construct the
  same store key," proven by construction and exercised directly, not
  "the test passed because nobody happened to choose the same string in
  this run."
- The demo gate (vox, two sessions, `list_scenes` showing both) is
  mandatory regardless of the unit/integration results, per `WORKFLOW.md`'s
  standing rule that a design's own reasoning does not substitute for
  driving the real entry point.

## Provenance

- Bead: `lux-ledm`.
- Design mission: `m-2026-08-16-006`.
- Files read to ground this design:
  `src/punt_lux/domain/hub/client_identity.py`,
  `src/punt_lux/domain/hub/client_session.py`,
  `src/punt_lux/domain/hub/hub_display.py`,
  `src/punt_lux/domain/hub/scene_writer.py`,
  `src/punt_lux/domain/hub/owner.py`,
  `src/punt_lux/domain/hub/owner_tracker.py`,
  `src/punt_lux/domain/hub/applet_name_format.py`,
  `src/punt_lux/domain/hub/menu_group_key.py`,
  `src/punt_lux/domain/hub/session_callback.py`,
  `src/punt_lux/domain/hub/callback_menu.py`,
  `src/punt_lux/domain/ids.py`,
  `src/punt_lux/connection_identity.py`,
  `src/punt_lux/cli_identity.py`,
  `src/punt_lux/applets/identity.py`,
  `src/punt_lux/tools/server.py`, `src/punt_lux/tools/tools.py`,
  `src/punt_lux/tools/write_tools.py`,
  `src/punt_lux/tools/subscribe_tools.py`,
  `src/punt_lux/operations/scenes.py`,
  `src/punt_lux/operations/scene_installer.py`,
  `src/punt_lux/operations/scene_clearing.py`,
  `src/punt_lux/operations/scene_submission.py`,
  `src/punt_lux/operations/identity.py`,
  `src/punt_lux/operations/models/render.py`,
  `src/punt_lux/operations/models/query_scenes.py`,
  `src/punt_lux/operations/models/query_ownership.py`,
  `src/punt_lux/protocol/messages/scene.py`,
  `src/punt_lux/protocol/messages/lifecycle.py`,
  `docs/architecture/target/target.md`,
  `docs/architecture/target/ui-model.md`,
  `docs/architecture/one-code-path.md`,
  `docs/architecture/hub-display-reconciliation-design.md`,
  `docs/README.md`, `DESIGN.md`.
- Related, read for context, not modified by this design: `lux-k3u6`
  (applet menu grouping, PR #350, the precedent cited throughout), `lux-e9vy`
  (DES-068), `lux-88ka` (DES-085).

---

## Proposed ADR text for `DESIGN.md`

The paragraphs above are the design record; the following is what I would
paste into `DESIGN.md` once this is ratified and implemented, matching the
existing DES-NNN format.

> ## DES-086: Connection-Scoped Store Keys — Scenes and Frames Cannot Alias Across Connections
>
> **Status:** proposed (design mission `m-2026-08-16-006`, bead `lux-ledm`)
>
> **Problem.** `HubDisplay` stores every scene and frame under the literal
> string a client submitted, with no ownership check on the first write to a
> given id. Two different connections choosing the identical `scene_id` do
> not error; the second silently evicts the first's roots and takes over as
> owner. `frame_id` has the identical shape, with no ownership tracking at
> any point. Vox running in two Claude Code sessions at once hit this
> directly: both sessions' music-player widgets push `scene_id="music-
> player"`, and the second overwrites the first on the shared display.
>
> **Decision.** No client-submitted `scene_id` or `frame_id` is ever used as
> a store key directly. The Hub composes a `ConnectionScopedId` —
> `f"{connection_id}\x1f{local_id}"` — from the writing connection's own
> `ConnectionId` and the caller's raw string, at the single choke point
> every scene install already passes through (`SceneInstaller.install`) and
> at the equivalent point for `update`/`clear`. Collision becomes
> unrepresentable rather than merely checked: two connections cannot
> construct the identical composed key, because neither controls the
> other's `ConnectionId` half. This generalizes the composite-id pattern
> `CallbackInvocation` already shipped for menu-callback ids (DES-058/
> DES-067) to scene and frame ids, which never received the equivalent
> treatment. The agent↔Hub and Hub↔Display wire protocols are unchanged;
> callers keep passing the same short, local `scene_id` they always have.
>
> **Alternatives rejected.** A wire-level composite id the client
> constructs itself (duplicates identity-formatting logic across every
> client repo, and contradicts the operator's explicit ergonomic
> requirement that namespacing happen automatically); caller-prefix
> enforcement, where the Hub checks rather than composes (still requires
> every caller to format a prefix, and leaves a checkable — hence
> bug-prone — gate where composition leaves none); re-deriving a fresh
> `(kind, name, repo, session_pid)` tuple instead of reusing `ConnectionId`
> (duplicates the identity encoding DES-057/DES-068 already maintain, and
> is no stronger — for the transport that produced the reported bug,
> `ConnectionId` already distinguishes two sessions via the MCP transport's
> own session key, independent of anything a caller declares).

---

## Decisions — operator-ratified 2026-08-16

The five decisions below were put to the operator after djb's round-2
security review. All five are ruled; none is open. The original
recommendation-and-trade-off text is kept for the record — it is what the
operator ruled on — with the ruling stated first for each.

**Decision 1 — RULING: EXTRACT.** The operator ratified gvr's recommendation
as written: promote `ID_SEPARATOR` out of `session_callback.py` into its own
shared module, touching a file DES-058/DES-067 already shipped. Original
framing: whether to promote `ID_SEPARATOR` out of `session_callback.py` into
its own shared module. I recommend the extraction — one constant, one
import-line change
in `session_callback.py`, and the two composite-id classes (`
CallbackInvocation`, the new `ConnectionScopedId`) provably share one
separator instead of two independently-declared literals that could drift
if either is ever changed alone. Alternative: leave `session_callback.py`
untouched and declare a second, independent `\x1f` literal in the new
module — a smaller diff, at the cost of the exact "two copies of one
invariant" duplication `oo.md` exists to argue against. Trade-off I cannot
resolve alone: this is a one-line touch to a file outside this design's
core write-set, and whether that's worth doing now versus flagging as a
follow-on is a scope call, not a design-correctness call — the collision
risk from two literal `\x1f`s is real but small (neither literal is likely
to change without someone noticing the other).

**Decision 2 — RULING: UNCONDITIONALLY (NOW).** The operator ratified
namespacing `frame_id` unconditionally, in this implementation, not as a
follow-on bead — closing the frame-level hijack surface at the same time as
the scene-level one rather than leaving a gap between them. Original
framing: whether cross-connection frame sharing is a feature this
design would silently remove, or a theoretical possibility nothing
currently exercises. I traced every scene-showing entry point I could
find (`show`, `show_table`, `show_dashboard`, `details_scene`) and found
none that deliberately shares a `frame_id` across two different
`ConnectionId`s — but I did not exhaustively audit the menu/menubar
rendering paths, which the mission scoped out of this design's read set. I
recommend namespacing `frame_id` unconditionally, as described above,
because the alternative — leaving frames unnamespaced while scenes are
namespaced — reopens exactly the hijack surface this design exists to
close, just one level up (a hostile connection could still evict another
connection's *frame*, even if it can no longer evict the *scene* inside
it). Alternative: namespace scenes now, leave frames as a follow-on bead
pending an explicit audit of the menu-rendering paths. Trade-off I cannot
resolve alone: I am confident nothing in the scene-rendering paths breaks,
but "nothing breaks in the menu paths" is a claim about code I did not read
end-to-end, and only the operator (or an implementation-phase audit) can
close that gap with certainty before this ships.

**Decision 3 — RULING: ACCEPT AS DOCUMENTED (no follow-on bead).** The
operator ratified accepting the `connection_for` CLI-identity residual
exactly as gvr documented it, with no bead opened to close it later —
the residual is a scope call about the CLI's existing, shipped
"re-run to update the same scene" contract, not a gap this design leaves
half-closed. Original framing: whether to leave the `connection_for`
CLI-identity residual — accurately stated, not "two bare `lux show <id>`
invocations colliding by coincidence" but "any same-user-localhost process
can deliberately become a target `cli`-kind connection's identity for the
price of one honest `identify()` call, and thereby collide that
connection's scene-id namespace with the target's" — as an accepted,
documented risk, or fold a fix into this design's implementation. I
recommend accepting it as documented —
the CLI's "re-run to update the same scene" ergonomic already depends on
repeated bare invocations sharing an identity, and the escape hatch
(`--as`/`LUX_CLIENT`) already exists for a caller that wants its own
namespace. Changing this would be a real, user-visible behavior change to
the CLI's existing contract, not a security fix this design's mandate
covers. djb's round-2 review confirmed independently that this residual
grants no *new* capability — the identical `connection_for` collision
already grants a hostile process the target's exact ownership for
`SetProperty`/`RemoveElement`, a strictly worse capability than a scene-id
collision, under the same standing same-user-localhost trust model — so
accepting the narrower residual here is consistent with a risk this
codebase already accepts elsewhere, not a new hole this design introduces.
Alternative: extend `connection_for`'s hashed fields (or
`CliIdentity`'s defaults) to distinguish concurrent bare invocations by
some invocation-local token, closing the residual at the cost of breaking
"run the same command twice to refresh the same display region" for every
existing CLI script that relies on it today. Trade-off I cannot resolve
alone: this is a product-ergonomics call about the CLI's existing,
shipped behavior, not a call this design's security mandate authorizes me
to make unilaterally.

**Decision 4 — RULING: Z-SPEC REQUIRED (operator override).** The operator
overruled both gvr's and djb's "not required" recommendation and required a
formal model. This is the merge gate for the implementation: model-check
the composition state machine (collision-impossibility across two distinct
`ConnectionId`s, idempotency for the same `ConnectionId` + `local_id`,
rejection of a `local_id` carrying the separator before composition), with
a fidelity control that reproduces the collision when composition is
omitted. Original framing: whether "not required" is the right z-spec
call, or whether this should get a formal model out of caution given the
project's history on DES-037/038. I have made and defended the "not
required" case above —
no new lock, no new interleaving, no recurrence — and I stand behind it.
But I am the design's author, not its security reviewer, and I want the
operator's ruling to rest on djb's independent check of that reasoning,
not on my confidence in it. Recommend: proceed without a z-spec track,
contingent on djb's review finding no interleaving I missed; if djb's
review does find one, treat that as an automatic escalation back to this
document rather than a implementation-time patch. Alternative: require a
z-spec track regardless, on the grounds that "identity and ownership,"
which this design touches, is exactly the class CLAUDE.md's rule names as
REQUIRED-independent-of-recurrence for lock disciplines and stateful
protocols — even though I argue this specific change introduces neither.
Trade-off I cannot resolve alone: the cost of a z-spec track the reasoning
above says is unnecessary, against the cost of shipping a security-framed
fix without one and being wrong.

**Decision 5 (new in round 2) — RULING: COMPOSE ON CALLER'S CONNECTION
ONLY (no `owner=` override).** The operator's exact words: "you can only
inspect what you put into the hub/display." `inspect_scene` composes its
`scene_id` argument against `scope.connection_id` by default, exactly as
`update`/`clear` do — and that is the *only* form. There is no `owner=`
parameter, no override, no cross-connection audit path. gvr's recommendation
below proposed a broader shape — an optional `owner=` parameter for a
caller to inspect another connection's scene — and the operator struck it:
a caller can only ever inspect scenes it owns, full stop. The narrower
ruling is also the more defensible one against djb's own threat model
above, which already names "a same-user-localhost process reading another
connection's scene content via introspection" as out of scope for this
design to newly enable — an `owner=` parameter would have been exactly
that: a new, explicit cross-connection read this design did not need to
add to close the reported bug.

Original framing djb's round-2 review raised: whether `inspect_scene`
composes the caller's own connection into its `scene_id` argument by
default, or requires the full composed key, now that raw and composed keys
diverge. djb's round-2 review found a gap this design's write-set never
accounted for: `inspect_scene` (`operations/queries.py:73`, exposed at
`GET /scenes/{scene_id}`) does a raw, uncomposed `SceneId(scene_id)` lookup
against what becomes, after this design ships, a composed store. Today an
agent can `show(scene_id="x")` then immediately `inspect_scene("x")` to
verify what it just installed — exactly the self-verification workflow
`target.md`'s Verification section describes. After this design, that same
call returns `not_found`, because the actual store key is
`"<connection_id>\x1fx"` and `inspect_scene` never composes against the
caller's own connection the way `update`/`clear` will.

gvr's original recommendation, superseded by the ruling above: **(a)**
`inspect_scene` composes its `scene_id` argument against the caller's own
connection by default, exactly as `update`/`clear` will, with a second,
optional `owner=` parameter accepting the already-composed string
`list_scenes` returns, for the cross-connection audit case. The operator
ratified only the first half of (a) — compose by default — and struck the
`owner=` half. Alternative gvr considered: **(b)**
`inspect_scene` stays a raw-composed-key lookup only, and this design says
plainly that self-verification now requires `list_scenes` first — a real,
disclosed regression instead of a silent one, cheaper to implement but a
worse day-to-day agent experience. gvr rejected a third option outright,
named by djb and worth stating so it is not re-proposed later: a permissive
dual-lookup (try the raw string, fall back to the composed form) that
reopens, on the read side, the exact ambiguity this design exists to close
on the write side — a `scene_id` that happens to look like another
connection's fully composed key could resolve to that connection's scene
under such a lookup. Superseded trade-off note: (a) is a small,
well-precedented addition consistent with the shape `update`/`clear`
already take, but it is still a change to `inspect_scene`'s signature that
this design's original write-set never scoped, and the operator should
rule on whether that scope extension ships in this design's implementation
or as an immediate follow-on PR.
