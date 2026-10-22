# Connection-Rung Frame Titles — Design

**Bead:** `lux-xrli`. **Status:** design, awaiting operator ratification.
**ADR:** draft DES-100 at the end of this document.

## Problem

Two Claude sessions in one repo, on one Hub, produce frames whose titles
collide: both Details panes read `claude`, both Vox panels read `Vox`. The
Clients menu tells the sessions apart (`lux`, `lux (2)`) because the Hub
computes that label (DES-064/067) while it builds the menu. The Display
cannot, because a frame arrives as `(hub, frame_id, title)` and the
Hub-computed connection-scope label is never attached to it.

DES-089 already specifies the answer: `LuxAddress.title()` elides a rung
until it is ambiguous — `Vox` solo, `lux (2) :: Vox` under one ambiguous Hub,
`pembroke :: lux (2) :: Vox` under two. The Hub rung works today. The
connection rung does not: `AddressRendering.title_for` hard-codes
`connection_ambiguous=False`, and `AddressBook.connection_ambiguous(hub)`
counts Display-to-Hub *links* (one fd per Hub), not the Hub's *clients*. It
can never be true on a single Hub. The rung's input — a label — is missing
from the wire.

## ADRs consulted

- **DES-089** (Identity Is a Path). Three rungs; `LuxAddress`; `AddressBook`
  computes ambiguity on the Display, once per build; a rung is elided the
  moment it is unambiguous. Its 2026-09-05 correction rejected
  `hub_id: str | None` because every sender can populate it. This design
  applies the same test to the new field (Decision 1). Governing invariant:
  storage keys and ImGui ids derive from the full `LuxAddress`, never from a
  label.
- **DES-064** (Clients menu). Collision numbering, narrowed 2026-08-02: a
  number lasts only while another client needs telling apart, and a released
  base goes to the senior client still numbered against it. Labels therefore
  *move* on departure; the carried label must follow.
- **DES-067** (grouping by `(repo, session_pid)`). Two applets of one session
  share one submenu and one name (`MenuGroupKey`). The Display must not
  count them as two scopes.
- **DES-086** (`ConnectionScopedId`, Rung 2). `{connection_id}\x1f{local}`
  is the stable Rung-2 key and is already inside every composed `frame_id`.
- **DES-088** (visibility versus content). A content event never writes
  visibility. A label change rides a content resend, so it must not touch
  `Frame` placement, and ambiguity must not depend on visibility.
- **DES-099** and its 2026-10-22 ruling. A callback-less connection's
  Details entry is named by the plain program token; its window title is
  "the connection's DES-089 address title, built by the Display's
  `AddressBook`". This design is the missing half of that sentence.
- `docs/architecture/multi-hub-addressing-work.md` (W4 `AddressBook`,
  `lux-pgkp` visible scoped title) and `system.tex` §"Identity, Addressing,
  and Multi-Hub Topology" (`AddressBook` per-Hub live connection set,
  `HubScopedStore`).
- Code read: `display/replica/{lux_address,address_book,address_rendering}.py`,
  `protocol/messages/{scene,scene_codec}.py`,
  `domain/hub/{client_roster,named_sessions,menu_group_key,replicator,
  scene_snapshot,frame_owner_facts,dirty_signal}.py`,
  `operations/{canonical_frame_owner,frame_owner_facts}.py`,
  `display/replica/{owner_facts_cache,scene_replica,frame_book}.py`.

## Decision

1. **The Hub sends the label; the Display decides whether to show it.** A
   frame carries the DES-064/067 roster name of its canonical owner
   (`lux`, `lux (2)`). The Display's `AddressBook` computes ambiguity and
   `LuxAddress.title()` composes the string. Hub-side string building is
   rejected: it would duplicate `LuxAddress` and could not see the Hub rung.
2. **One new optional frame-spec field, `frame_scope_label`**, beside
   `frame_owner_facts`, resolved by the same canonical-owner rule and
   cached Display-side with the same departure guarantee.
3. **Ambiguity is a collision test within one Hub, over held frames.** The
   connection rung is shown for frame F exactly when F has a label and some
   other frame on the same Hub has the same base title and a different
   scope.
4. **Label moves are pushed, not polled.** A roster release that changes a
   survivor's label marks that survivor's scenes dirty, outside the registry
   lock. The ordinary replicator path resends them.
5. **Hidden ids do not change.** Only the visible title does; `##hidden_id`
   keeps window position and state across a label move.

## Wire change

`SceneMessage` gains one field in the frame spec (not the scene — a frame
has one title, so it has one scope):

```python
frame_scope_label: str | None = None
```

Codec: `_strip_none` omits it when absent. `decode` accepts a non-empty
`str`; anything else (non-string, empty) decodes to `None` and logs a
warning, exactly as `_parse_owner_facts` degrades. No version bump.

### Optional, not required — and why this is not the `hub_id` mistake

DES-089 made `hub_id` required because every connecting `kind` could supply
it, so `None` meant nothing. The question to ask is the same: *what does an
absent value mean here?*

Here it has one honest meaning, shared with `frame_owner_facts`: "the Hub
has no name for this frame's owner right now" — the owner is unidentified
(only identified sessions are named, `named_sessions.py`), or departed
between snapshot and push. The Display keeps its last cached label and
renders no rung if it never had one. The sender genuinely cannot always
populate the field, so it is not a requiredness bug.

Rejected: a required `str` with `""` for "none". That is `Optional` with a
sentinel — the type admits a value the reader must remember to treat as
absent.

Old Hub with new Display, or the reverse: `frame_scope_label` absent decodes
to `None`, the title stays plain. The change is additive and not breaking.

### Rejected wire shapes

- **A scope key plus a label.** The stable key is already the leading
  segment of the composed `frame_id` (DES-086), and `hidden_id` already
  includes it. A second key on the wire is a second identity to drift. The
  Display never parses the frame id, and does not need to: grouping is by
  label (below).
- **The label on the scene rather than the frame.** A frame composes scenes
  from several connections. A per-scene label would let the title flip to
  whichever scene was sent last — the defect `CanonicalFrameOwner` exists to
  prevent for owner facts.
- **Hub pre-composes the full title.** See Decision 1.

## Hub change

Extend the existing owner resolution rather than add a parallel one.
`FrameOwnerFactsReader.facts_for_frame(frame_id)` becomes one call returning
one value, `FrameOwnership(facts, scope_label)`, both resolved from the
frame's canonical scene (`CanonicalFrameOwner._canonical_scene`) and its
first-appearance owner. Two separate port methods would resolve the
canonical scene twice and could answer from different owners if a scene
departed between the calls. `scope_label` is `NamedSessions.name_of(owner)`;
`None` when the owner holds no live session or no name. The existing
`SceneSnapshot.push` passes both onto `ScenePresentation.push` and
`DisplayLink.send_scene`, which fill `frame_owner_facts` and
`frame_scope_label`. The rename of the port is a rename train inside one
repo: no alias, every caller changes.

## Display change

- **`FrameScopeStore`** (new, beside `OwnerFactsStore`): `HubScopedKey ->`
  a departure-guarded cache. `adopt(key, incoming)` ignores `None`;
  `prune(key)` on frame disposal. `SceneReplica.handle_framed_scene` calls
  it where it calls `OwnerFactsStore.adopt`. The guarded-cache logic in
  `OwnerFactsCache` generalizes to a small `HeldValue[T]` shared by both —
  this is the medium-scale OO paydown the ratchet expects when touching the
  file.
- **`AddressBook`** loses `connection_ambiguous(hub)` (a count of links;
  wrong rung's cardinality) and gains
  `connection_ambiguous(title, scope, peers)`, where `peers` are the
  `(title, scope)` pairs of the other frames on the same Hub. No shim.
  `note_connection`/`forget_connection` stay: they track Hub liveness and
  label retirement, which is their real job.
- **`AddressRendering.frame_title(frame)`** builds the address with the
  frame's scope label as the connection rung's label (key: the frame id's
  Rung-2 prefix is unchanged in `hidden_id`) and passes the computed
  `connection_ambiguous` to `LuxAddress.title`. `title_for` stops
  hard-coding `False`.
- **One seam for every frame title.** `render_loop.py:821` already routes
  through `frame_title`. `windows_menu.py:110`, `dock_pill.py:55,79,83`
  still read raw `frame.title` and so show neither the Hub rung nor the
  new one; they route through the same seam. `query_dispatcher.py:120` keeps
  the base title and adds `scope_label` so agents can introspect both.

### Exactly when the connection rung shows

For a frame F on Hub H with base title T and scope label S:

```python
shown = S is not None and any(
    g.title == T and g.scope != S for g in frames_of(H) if g is not F
)
```

Properties, each a test:

- **Solo is plain.** One session: no peers, `Vox`.
- **Same session, two applets, is plain.** Beads and Vox of one session
  share the label `lux` (DES-067), so equal scopes never collide. Distinct
  titles never collide either.
- **Two sessions, same repo:** `lux :: Vox` and `lux (2) :: Vox`. Both are
  prefixed; showing it on only one would make the unprefixed one read as the
  "default" and hide that there are two.
- **Different repos, different titles:** no prefix, no noise. Collision, not
  mere presence of a second session, is what DES-089 calls ambiguity here:
  the rung is shown when the *leaf* is not unique under the Hub.
- **Visibility is ignored.** Closed and docked frames still count (DES-088).
  Closing one of two `Vox` panels must not rename the other, and the closed
  one reappears with its old title on raise.
- **Disposal counts.** Clear All, or an emptied departed scene, removes a
  frame from the peer set, and the survivor's title de-prefixes.
- An unscoped peer (label `None`) counts as a distinct scope but has no
  label to show.

Grouping by *label* is sound because the roster guarantees live groups hold
distinct labels (that is what numbering is for). A moment of Display-side
staleness shows at worst a prefix one frame too long, never a wrong one,
and the next resend converges.

## Label churn

Labels move only through `ClientRoster.release` (a group's last member
departs, its base goes to the senior numbered survivor) and arrive through
`names_for` (a connection first identified). Both already happen under the
registry lock in `hub_clients.py`.

- `ClientRoster.release` returns the survivors whose held label changed
  (diff of `held()` before and after). `ClientRegistry.discard` and
  `reap_lapsed_locked` return that set to their caller.
- The caller — the departure cascade, which already calls `mark_menus` on
  these paths — then marks every live scene owned by those connections dirty
  (`HubDisplay.scene_owners` supplies the scenes) **after** the registry lock
  is released. Marking is queue-only, but taking the `DirtySignal` condition
  inside the registry lock would add a lock edge for nothing.
- Identification (`None` to named) marks the connection's own scenes dirty
  in the same way. This is the existing `lux-ghhf` identify path, which
  already re-pushes the menu.
- Only a real change marks anything. A departure that moves no label marks
  no scene; a plain `show()` resend carries the current label and the
  Display's cache treats an equal value as a no-op.

DES-088: a label rides the same full-scene resend as any content change. It
writes `FrameScopeStore` and nothing on `Frame` placement. A test pins that
a label-moving resend leaves a closed frame closed, extending
`test_a_replace_leaves_a_closed_frame_closed`.

## Multi-Hub composition

`LuxAddress.title()` already composes outermost first:
`hub :: connection :: leaf`. Hub ambiguity stays global (more than one Hub
live); connection ambiguity is per Hub, as above. Combinations:

| Hubs | Collision on a Hub | Title |
|------|--------------------|-------|
| 1 | no | `Vox` |
| 1 | yes | `lux (2) :: Vox` |
| 2 | no | `pembroke :: Vox` |
| 2 | yes | `pembroke :: lux (2) :: Vox` |

Two Hubs minting the same connection label never interact: the peer set is
per Hub (`HubScopedKey.hub`), so Hub A's `lux` cannot make Hub B's frame
ambiguous. The Hub rung's own `pembroke (2)` numbering is untouched.

Keys stay `LuxAddress`-derived. `hidden_id_for(hub, composed_key)` is not
touched; the window is still `title##hub_token␟frame_id`, so the governing
invariant holds and a label change never changes an ImGui id. The scope
store is a `HubScopedKey` map like `OwnerFactsStore`.

## Cross-repo impact

Hub-to-Display only. `SceneMessage` is built by `DisplayLink` inside luxd; a
search of `vox/src` and `z-spec/src` finds no `SceneMessage`. Both talk to
the Hub through REST/MCP/library and never to the Display. The field is
additive and optional, so no coordinated release is needed. The cross-repo
breaking-change protocol is not triggered.

## z-spec determination

**Not required.** Per the lux rule (concurrency, lock discipline, stateful
protocol, or a recurring defect class), none applies:

- No new lock and no new lock edge. The replicator worker resolves the label
  on its own thread by reading the registry through the same
  `named_sessions()` call `FrameOwnerFacts` already makes, holding no other
  lock (`SceneSnapshot.push` runs after the store read lock is released).
  The dirty-marking runs outside the registry lock for exactly this reason.
- No new interleaving class. The only race — a label read at push time
  versus a concurrent departure — converges by the argument that already
  governs menus: every label-moving change marks its owners dirty *after*
  committing, and the later push reads the registry fresh, so the newest
  state wins. `menu_lifecycle.tex` and `hub_replicator.tex` model the
  dirty-then-fresh-read discipline this reuses.
- No state machine: the Display side is a pure function of held frames.
- The recurrence signal has not fired: this is the first round on this
  defect.

A roundtrip-plus-convergence test is the right instrument.

## Write set

Create or modify (the implementation mission decides final names, but each
concern below must land):

- `protocol/messages/scene.py`, `scene_codec.py`: `frame_scope_label`.
- `domain/hub/frame_owner_facts.py` (port and Null Object),
  `scene_snapshot.py`, `scene_presentation.py`, `display_link.py`: carry
  `FrameOwnership`.
- `operations/canonical_frame_owner.py`, `operations/frame_owner_facts.py`:
  resolve the label from the canonical owner.
- `domain/hub/client_roster.py`, `hub_clients.py`, `departure_cascade.py`
  (or the sink that marks menus on departure), `operations/` identify path:
  moved-label set and dirty-marking outside the lock.
- `display/replica/owner_facts_cache.py` (generalize), new
  `frame_scope_store.py`, `scene_replica.py`, `address_book.py`,
  `address_rendering.py`, `display/menus/windows_menu.py`,
  `display/dock_pill.py`, `display/query_dispatcher.py`.
- `docs/architecture/system.tex` §Addressing (the "scope label does not
  reach the Display" note and the per-surface table), `DESIGN.md` (DES-100),
  `CHANGELOG.md`, `.oo-baseline.json` via `make update-oo`.

Concurrency warning for the leader: `hub_clients.py` and
`operations/menus.py` have uncommitted edits from the `lux-ghhf` worker.
Sequence this mission after that branch lands.

## Test plan

- **Wire roundtrip** (`tests/test_protocol.py`): present, absent, empty
  string, non-string; absent produces no key; old payload decodes to `None`.
- **AddressBook ambiguity** (pure unit, no ImGui): solo plain; same-session
  two applets plain; two same-repo sessions both prefixed; different repos
  with different titles plain; same title, different repos prefixed; closed
  and docked frames count; disposal de-prefixes; unscoped peer; two Hubs
  with equal labels do not cross-contaminate; hub plus connection rung
  composition (the four-row table above).
- **Label follows departure**: two sessions `lux`/`lux (2)`; the first
  departs; the survivor's scenes are marked dirty, the resend carries `lux`,
  and the title becomes plain `Vox`. A departure that moves no label marks
  nothing.
- **Identify**: scenes sent before identification (`None`) are resent with
  the label once identified.
- **Canonical owner**: a frame composed of scenes from two connections
  carries the oldest scene's owner's label on every scene send, and the
  facts and label always come from the same owner (the single-call port).
- **DES-088**: a label-moving resend leaves a closed frame closed and does
  not move `active_tab` or cascade slot.
- **Windows menu and dock pill** show the same title as the window.
- **Guard**: a grep-style test that no renderer reads `Frame.title` for
  display outside the one seam (like `test_per_frame_tracing.py`).
- **Demo** (`make restart`, expected result written first): open a second
  Claude session in the same repo; run a Vox panel and Details in both;
  `list_frames`/`inspect_scene` shows both `scope_label`s and `make
  screenshot` shows `lux :: Vox` and `lux (2) :: Vox` (Read the PNG). Close
  one session: within one replication cycle the survivor reads plain `Vox`
  and a window the user had closed stays closed. Invalid input: a payload
  with `frame_scope_label: 7` is logged and ignored. Boundary: the lone
  session never shows a rung.

## Draft DES-100

```markdown
## DES-100: The Connection Rung Reaches the Display as a Per-Frame Scope Label

**Status:** DRAFT — awaiting operator ratification. Bead `lux-xrli`.
Design: `docs/architecture/connection-rung-design.md`.

**Problem.** Two sessions in one repo on one Hub produce frames with
identical titles (`claude`, `Vox`). DES-089 specifies a connection rung
(`lux (2) :: Vox`) but the Display never received its label:
`AddressRendering.title_for` hard-coded `connection_ambiguous=False`, and
`AddressBook.connection_ambiguous` counted Display-to-Hub links, never a
Hub's clients.

**Decision.** `SceneMessage` carries `frame_scope_label: str | None`, the
DES-064/067 roster name of the frame's canonical owner, resolved with the
same canonical-owner rule as `frame_owner_facts` in one `FrameOwnership`
port call. The Display caches it with the same departure guarantee. The
Display's `AddressBook` decides ambiguity: the rung shows for a labeled
frame exactly when another frame on the same Hub has the same base title
and a different scope, regardless of visibility (DES-088). The label is
visible text only; `hidden_id` is unchanged. A roster release that moves a
survivor's label, and identification, mark that connection's scenes dirty
outside the registry lock; the normal replicator resend carries the new
label.

**Optional, not required.** Absence has one meaning shared with
`frame_owner_facts` — the Hub has no name for the owner now — so DES-089's
`hub_id` correction (every sender can populate it) does not apply.

**Alternatives rejected.** A scope key plus label (the key is already in the
composed frame id; a second key is a second identity). A per-scene label (a
frame's title would follow the last scene sent). A Hub-composed full title
(duplicates `LuxAddress`, cannot see the Hub rung). Required `str` with `""`
(Optional with a sentinel). Showing the rung whenever a second session
exists (noise in the common multi-repo case; DES-089's test is leaf
uniqueness). Polling the roster for label changes (the dirty signal already
carries every other content change). Marking dirty under the registry lock
(a lock edge for no benefit).

**Consequences.** Hub-to-Display only; vox and z-spec unaffected. Additive
wire field, no coordinated release. Not a z-spec candidate: no new lock, no
new interleaving, convergence by the existing dirty-then-fresh-read rule.
Supersedes the "scope label does not reach the Display" note in
`system.tex` §Addressing.
```
