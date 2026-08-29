# DES-065 R8: Frame Visibility Is the Display's, Content Is the Hub's

**Bead:** `lux-mxvy.8` (R8 of epic `lux-mxvy`)
**Mission:** `m-2026-08-29-004` (design; worker `rmh`, evaluator `gvr`)
**Status:** design complete, model-checked, awaiting leader review
**Model:** [`frame-visibility-lifecycle.tex`](frame-visibility-lifecycle.tex),
fidelity control [`frame-visibility-lifecycle_buggy.tex`](frame-visibility-lifecycle_buggy.tex),
partition audit [`frame_visibility_lifecycle_coverage.md`](frame_visibility_lifecycle_coverage.md)

Design only. No source file is touched by this mission; the write-set for the
implementation mission is in §7.

---

## 1. The one rule

Two authorities write to a frame, and today they write to the same fields.

| Axis | Who owns it | What moves it | Where it lives |
|---|---|---|---|
| **Content** — does this scene id exist? | the client, via the Hub | `show()`, `update()`, an empty push, a manifest purge, a frame TTL | replicated: `FrameBook.scene_to_frame`, `Frame.scenes` |
| **Visibility** — where is this frame? | the user, at the Display | close button, collapse button, dock pill, `raise_frame`, Expand/Collapse/Fit All | Display-local: `Frame.minimized`, `Frame.active_tab`, `FrameBook._focus_frame_id`, `Frame.cascade_index` |

The rule this design establishes, and the whole of it:

> **A content event never writes visibility. A visibility event never writes
> content.**

Both shipped bugs are that rule broken, once in each direction.

**Bug A (vox-640w) — the user's gesture cannot reach the frame.**
`SceneReplica.close_frame` pops the frame out of `FrameBook` entirely, so
`FrameCommands.raise_it` finds nothing and answers `raised: false`. The one
mechanism that exists to restore a frame on a user gesture cannot act on a
frame the user closed. (The bead's stated root cause — that
`upsert_scene_in_frame` un-minimizes only when `is_new` — is the second half of
the same story: because a push is the only thing that can bring the frame back,
whether a push raises has become load-bearing. It should not be. Pushes should
never raise, and the gesture should always work.)

**Bug B (vox-7l2d) — a content event undoes the user's gesture.**
The same `close_frame` calls `FrameBook.forget_scene` for every scene the frame
held, returning those ids to *unseen*. The next background push therefore reads
as `is_new`, and the `is_new` branch clears `minimized` and requests focus. A
track change reopens a window the user shut.

They share one cause. `is_new` is a fact about **content** — "this scene id is
not in this frame" — wired to affordances that belong to **visibility**. Because
a close erases content, the user's decision is round-tripped through the content
axis and destroyed there.

---

## 2. The state model

### 2.1 Three states per scene id

The mission asks for three per-scene-id states. They are not three stores; they
are two facts read together.

| State | Content axis | Visibility axis | Meaning |
|---|---|---|---|
| **never-seen** | `scene_id ∉ scene_to_frame` | — | the next push is genuinely new |
| **known-and-framed** | `scene_id ∈ scene_to_frame` | its frame is `OPEN` or `MINIMIZED` | on screen, or docked |
| **known-but-unframed** | `scene_id ∈ scene_to_frame` | its frame is `CLOSED` | the user put it away; content still lives |

`is_new` is exactly *"not in the content axis"*, and after this change nothing on
the visibility axis can move a scene back into `never-seen`. That is the
criterion's *"'known' status survives a close"*, and it is achieved by deletion
rather than by addition: `close_frame` stops calling `forget_scene`.

### 2.2 Closed is a visibility value, not the absence of a frame

The decisive modelling choice. `Frame.minimized: bool` becomes a three-valued
`Frame.visibility`:

```text
OPEN       painted as an inner window
MINIMIZED  not painted; carries a dock pill
CLOSED     not painted; carries no pill; reachable only by a named user gesture
```

A closed frame stays in `FrameBook._frames` with its scenes, its widget state,
its active tab, and its cascade index. Nothing about it is destroyed; it is a
frame that is not being painted.

Three things fall out of this that no other arrangement gives for free:

1. **`raise_frame` works on a closed frame with no change to its logic.** The
   frame is still in the book to be found. `raise_it` sets the visibility to
   `OPEN` and requests focus, exactly as it does today for a minimized frame.
   This is §6.
2. **There is one store, not two.** The alternative — a graveyard of closed
   scenes beside the live frames — needs a resurrection path, a second place for
   the purge sweep to look, and a second place for introspection to read. Every
   one of those is a place for the two copies to disagree.
3. **`known-but-unframed` needs no representation of its own.** It is
   `known-and-framed` where the frame's visibility happens to be `CLOSED`. The
   mission's third state is a reading of the two axes, not a third store.

### 2.3 The husk rule survives

`SceneReplica.handle_framed_scene` documents that "the frame and its content
appear and disappear together, never as a husk". That still holds, and it holds
for closed frames too: when the last scene of a frame is *disposed* (empty push,
manifest purge, TTL), the frame goes with it **whatever its visibility**. A
closed frame whose content is gone is disposed, its id released, and the next
arrival under that id is a genuinely new frame. This is the model's
`DisposeFrame`, and it is what keeps a closed frame from being an unbounded leak
(see §8.2).

### 2.4 Close and dispose are two operations wearing one name

Today one method, `SceneReplica.close_frame`, serves six call sites with two
incompatible meanings. Exactly one of them means "visibility":

| Call site | Meaning |
|---|---|
| `render_loop._render_frames` — the user clicked a frame's ✕ | **visibility**: put this away |
| `render_loop._clear_all` — the World menu's Clear All | **dispose**: throw it out |
| `render_loop._render_frame_tabs` — a tab ✕ emptied the frame | **dispose**: the scene was dismissed |
| `handle_framed_scene` — an empty push emptied the frame | **dispose**: the client says it is gone |
| `upsert_scene_in_frame` — a scene moved out of its old frame | **dispose**: the old frame is a husk |
| `hub_reconciliation` — a manifest purge emptied the frame | **dispose**: the Hub disowned it |

They must become two named operations. `close` sets the visibility and touches
nothing else. `dispose` is today's behaviour in full — pop the frame, forget
every scene, discard widget state, return the stale element ids. Only the first
call site gets `close`; the other five get `dispose`, which is what they already
mean.

The implementation must also honour these, which follow from the split:

- **Closing must not discard widget state.** Scroll position, selection, and
  in-progress text survive a minimize today; they must survive a close for the
  same reason.
- **Closing must not notify the Hub of stale element ids.** The elements still
  exist; nothing was replaced. `_notify_stale` belongs to dispose only.
- **Closing should still drain the Display's own queued interactions for that
  frame's elements.** A button in a window the user just shut must not fire
  afterwards. That drain is Display-local (`_drain_stale_events` informs no one)
  and so is a visibility-side action, not a content one. Mechanism is the
  implementer's call.
- **`set_frame_state` must not reach a closed frame, in either direction.**
  *(Added after implementation round 1; see §10.)* `FrameCommands.set_state` is
  on the whole client surface — MCP, REST, CLI, via
  `operations/display_control.py` — and it toggles a dock state. A closed frame
  is not in that state's domain: undocking one puts back a window the user shut
  with no gesture behind it, and docking one gives it a pill they never asked
  for. Both break §6's rule that a closed frame is reachable **only** by a named
  user gesture, which is `raise_frame` and nothing else. The command refuses
  loudly rather than no-opping, because a caller cannot see a frame's visibility
  from the request it is making and silence would let it believe it had acted.

---

## 3. Is a genuinely-new scene allowed to surface? (criterion 2)

This is the criterion that asks whether the Display-owned auto-surface policy
defaults to "never", or whether a Display-local preference is genuinely wanted.
**It resolves from the existing documents, and no operator ruling is needed** —
because the question contains an equivocation on the word "appear".

Three different things have been called visibility in this epic:

| | What it is | R8's rule |
|---|---|---|
| **window** | the OS window `luxd-display` owns | never opened by an agent action (R1) |
| **frame** | an inner window on the workspace canvas | this design |
| **focus** | z-order + OS focus, the one-shot `request_focus` | never taken by an agent action |

Every one of R8's acceptance tests is about the **window** and about **focus**:
*"window stays hidden"*, *"window does not raise; no focus steal"*, *"the scene
updates in place; no raise"*. None of them says a new frame may not exist on the
canvas — and none could, because R8's own final test is *"user opens window via
menubar: the scene is visible"*, which requires that arriving scenes did get
frames while the window was hidden.

So the policy is:

> **A frame is born `OPEN`. It never takes focus, never opens the window, and
> never disturbs any other frame's visibility.**

That satisfies R8's literal test cases, and it satisfies the operator's *"the
only time a frame should magically appear is if the frame is new"* — appearing
on a canvas the user has to choose to look at is not a raise.

It also satisfies the stricter `workspace-model.tex` reading that DES-060 left
open. That model says `AddSceneToFrame` keeps `frameVis` and only an explicit
`RestoreFrame` restores. It constrains *existing* frames, and this design obeys
it absolutely: no content event writes the visibility of a frame that already
has one. For a frame that does not exist yet there is no `frameVis` to keep, and
`CreateFrame` in that same model already assigns `fvNormal`. The model and this
design agree.

**Why this is Display-owned and not Hub-forced.** The Hub sends a scene. It does
not send "this is new, raise it" — there is no such flag on the wire, and this
design adds none. The Display derives newness from its own replica and decides
what a frame containing that scene looks like when it first exists. Today that
decision is an unnamed side effect buried in `upsert_scene_in_frame`'s `is_new`
branch, which is why it also reaches out and modifies *other* state. Under this
design it is a single assignment at the one place a frame is constructed
(`FrameBook.ensure`), with nothing else attached to it.

**Recommendation: no preference knob.** One default, no configuration, no
per-client override. A "create new frames minimized" preference has no
requester, would need a surface to set it on, and would give the user a way to
make arriving content invisible with no affordance saying where it went. If a
user wants a frame put away they can close it, and now that decision sticks.

---

## 4. What the model says

`docs/frame-visibility-lifecycle.tex` formalises §1 and §2 as ten flat state
components: three for the content axis (`frames`, `content`, `sceneFrame`),
three for the visibility axis (`vis`, `activeTab`, `focus`), and four ghosts
recording what the *user* did (`userClosed`, `closedScenes`, and
`autoFocused`/`tabStolen` for the violations). Eleven operation schemas cover
every transition: three content pushes, two disposals, five user gestures, and
`SetDockState` — the client-surface dock toggle, added in round 2 (§10).

Five invariants, none placed in the state schema (a predicate there is enforced
as a guard on every successor and would silently mask the defect):

1. `autoFocused = ∅` — no content event ever requests focus.
2. `tabStolen = ∅` — no content event ever moves the active tab.
3. `userClosed ⊆ frames` — **bug A**: a closed frame is still there to raise.
4. `{f ∈ frames | f ∈ userClosed ∧ vis f = vOpen} = ∅` — **bug B**: only a raise
   reopens a closed frame.
5. `∀ s ∈ closedScenes ∩ content • vis (sceneFrame s) ≠ vOpen` — **bug B in the
   shape the user meets it**: not merely that a frame id came back, but that the
   very scene they shut is in front of them again.
6. **Deadlock freedom** — no reachable state leaves every operation disabled.
   A property of the transition relation rather than a state predicate, so it is
   discharged by the model check itself rather than by a goal.

`fuzz -t` exits 0 on both documents. ProB 1.15.1 explores the intact model's
whole reachable state space — **95 states, 845 transitions, ALL OPERATIONS
COVERED**, no deadlock — and finds no counter-example to any of the five goals.
Also clean at `DEFAULT_SETSIZE 3` (2593 states, 34939 transitions); size 4 does
not finish usefully and is not needed, since every operation is covered at 2 and
none of the properties is cardinality-dependent.

### 4.1 Findings the formalisation surfaced

Four, each of which changes the implementation:

**F1 — the two halves of the fix must ship together, or the product gets
worse.** This is the finding that justifies the modelling. Retiring the
`is_new` side effect (criterion 3) while leaving `close_frame` destructive
produces a state — invariant 3 violated, `userClosed ⊄ frames` — where the user
has closed a frame, `raise_frame` cannot find it, and the accidental recreation
that used to bring it back has been removed. **Today, bug B *is* the only reopen
path for a closed frame.** Take it away on its own and closing becomes a
one-way door. The implementation mission must not be split along that seam, and
its tests must assert the composite: close, then raise, then confirm the frame
is on screen.

**F2 — the active tab is in the same category as visibility, and R8 retires it
too.** DES-060 gated three affordances to new scenes: un-minimize, focus, and
active-tab. R8's language retires the first two by name. The third is the same
kind of thing — a user-owned selection — and a second scene arriving in a frame
the user is reading pulls the selection off whatever they were looking at.
Invariant 2 covers it. **Rule: a new scene takes the active tab only when the
frame has no active tab** (i.e. it is the frame's first scene). Otherwise it
joins the tab strip and the selection stays put. `dismiss_framed_scene`'s
existing fallback — repoint the tab when the *active* scene is disposed — is a
repair, not a steal, and is unaffected.

**F3 — a closed frame needs a deliberate reopen affordance, and this is
in-scope.** Once the accidental path is gone (F1), a frame is reopenable only by
a named gesture. `raise_frame` covers every client that owns a menu entry —
voxd's Music, `lux-beads`' Beads. **A plain agent `show()` scene owns no menu
entry, and after this change nothing can reopen its frame.** That is a
regression the moment the fix lands, so the fix must carry its own remedy: the
Windows menu gains the list of closed frames, one entry per frame, each
restoring one — and `Expand All` restores docked and closed frames alike, since
its whole meaning is "everything back on screen". The dock bar deliberately does
*not* show closed frames: the pill is the minimize affordance, and keeping
closed out of it is what makes closed a stronger statement than minimized.

**F4 — the Hub must stop deleting scenes when the user closes a frame, and the
`frame_close` wire event should go with it.** This one is invisible from
`scene_replica.py` alone and would have survived a Display-only fix. Today
`render_loop._close_frame` sends a `RemoteEventHandlerInvocation(action=
"frame_close")` to the owning fds; `HubInteractionDispatch._close_frame` answers
it by calling `hub_display.frames.remove_frame(frame_id)` and marking every
scene dirty, and the replicator then pushes those scenes back **empty**. An
empty push is the dispose path. So even a Display that kept its closed frame
perfectly would have it disposed one round trip later, by the Hub, on the user's
own close.

Closing is a Display-owned visibility decision, and under this design it has
nothing to tell the Hub. The `frame_close` branch in `HubInteractionDispatch`,
and the send in `render_loop._close_frame`, are both retired. `notify=False`
and its regression guard go with them, because the user-close and purge paths
are now different methods rather than one method with a flag.
`FrameLifecycle.remove_frame` stays — the TTL sweep still uses it.

---

## 5. Fidelity (criterion 4, mandatory)

`docs/frame-visibility-lifecycle_buggy.tex` is the same model with today's code
restored in exactly three schemas — `Close` disposes the frame and forgets its
scenes; `PushNewFrame` and `PushNewScene` carry the `is_new` side effect. Every
other schema is identical. It is fuzz-clean, and its state space is 1030 states
/ 10309 transitions, also with every operation covered.

Every goal is **found** in the control and **not found** in the intact spec, on
the same carriers and the same initial state:

| Goal (negated invariant) | Intact | Control |
|---|---|---|
| `autoFocused /= {}` | not found | **found** |
| `tabStolen /= {}` | not found | **found** |
| `userClosed /\ frames /= userClosed` | not found | **found** |
| `card({f\|f:FRAME & f:frames & f:userClosed & vis(f)=vOpen})>0` | not found | **found** |
| `#s.(s:closedScenes & vis(sceneFrame(s))=vOpen)` | not found | **found** |

**The individual witness traces are not cited, because they are not stable.**
ProB's search order varies between runs — the same goal returned a 3-step
witness on one invocation and a 6-step one on the next. The verdict and the
state-space size are stable; the witness is not. So the fidelity evidence is
given instead as two deterministic `probcli -t` trace replays, each of which
names exactly one operation that is enabled in one design and not the other:

| Replay | Control | Intact spec |
|---|---|---|
| `PushNewFrame; Close; PushNewFrame` (same frame id, same scene id) | replays | **fails at step 3** |
| `PushNewFrame; Close; Raise` | **fails at step 3** | replays |

That pair is the whole design in two lines. **Bug B**: after a close, pushing
the same scene into the same frame is not even a legal `PushNewFrame` any more —
its guard `s ∉ content` fails, because the close no longer forgot the scene, so
the push is a `PushRepeat` and the frame stays closed. **Bug A**: after a close,
`Raise` is enabled here and is not enabled in the control, where the close
removed the frame — which in the running system is `raise_frame` answering
`raised: false` to an applet's menu click.

### Two things the ProB run changed

**Invariant 5 was added because invariant 4 was weaker than the claim.** The
first four invariants are about frame *identity* — "a frame the user closed is
open". The symptom vox reports is stronger: *the very scene they shut* is in
front of them again on a track change. The model as first written could not
witness that, and a `-goal` naming a specific element (`FRAME2 : frames`) is
rejected by probcli with a `type_expression_error` — it prints those names in
its own traces but will not accept them in a goal, and the model-check then
reports "no counter example" **vacuously**. Rather than leave an unwitnessed
claim in this document, the model gained the `closedScenes` ghost (the scene ids
that were in a frame when it was closed, cleared on raise or dispose) and
invariant 5 over it. It holds on the intact spec and is violated by the control.

**`ALL OPERATIONS COVERED` is the guard against a vacuous pass.** ProB reports
it for both documents, so no invariant is discharged by an operation that never
fired.

### `make prob` reports a spurious deadlock — on this spec and every other one in the repo

`make prob` runs a constraint-based deadlock check (`-cbc_deadlock`) alongside
the model check, and that step prints `*** DEADLOCK state found ***` for this
document. **It is noise, and it is not this model's.** The state it reports is
not a state of the specification at all:

```text
vis = {(FRAME1|->vOpen), (FRAME1|->vMinimized)},  frames = {}
```

`vis` maps one frame to two values, so it is not a function, let alone the
partial function `Sys` declares — and `dom vis = {FRAME1}` while `frames = {}`,
violating `Sys`'s own `dom vis = frames`. In ProB's Z mode `-cbc_deadlock` does
not constrain its solutions to the state schema. The two-line proof: give it a
counter declared `n : ℕ` and bounded `n ≤ 2`, whose only real deadlock is at
`n = 2`, and it reports the deadlocking state as **`n = -2`**, having enumerated
`n` over `INTEGER`.

Ruling out the two candidate explanations, in order:

- **Not a reachable deadlock.** `-model_check` without `-nodead` explores the
  reachable state space with deadlock detection on and reports none, at
  `DEFAULT_SETSIZE` 2 and 3. That detection is live, not vacuous: run against
  the `n ≤ 2` control it reports `Found "deadlock" error in state id 2`.
- **Not a small-carrier artifact.** It persists unchanged at `DEFAULT_SETSIZE`
  2, 3, 4 and 6. Growing the carrier does not remove it.
- **Not specific to this model.** `display_lifecycle.tex`,
  `architecture/workspace-model.tex`, `hub_replicator.tex` and
  `listen_lifecycle.tex` all report it too — including `display_lifecycle.tex`,
  whose own Verification section discharges deadlock freedom with `-model_check`
  and is right to do so.

**Recommendation (needs the leader — `Makefile` is outside this write-set).**
The `--- cbc deadlock ---` step of `make prob` prints a red
`*** DEADLOCK state found ***` for every Z spec in the repository and has never
meant anything. It cost one review cycle on this mission alone. Either drop the
step, or keep it and have it print the caveat beside the result. Leaving a check
in place that always fails trains everyone to ignore it, which is worse than not
having it.

---

## 6. `raise_frame` is unaffected, and works for minimized and closed (criterion 7)

Confirmed, and this is the load-bearing confirmation in the whole design.

`FrameCommands.raise_it` is DES-063's explicit user-gesture path: an applet's
menu-entry click calls `raise_frame`, and its docstring already states the
principle this design generalises — *"the one focus change a client may ask for,
and only because the user asked… Nothing here takes focus on its own
initiative."* Nothing in R8 touches it. `raise_frame` is the **only** operation
in the model that both opens a frame and takes focus, and it is enabled from
every visibility state.

| Frame state at click | Today | After |
|---|---|---|
| `OPEN` behind others | found; focus requested | unchanged |
| `MINIMIZED` | found; `minimized=False` + focus | unchanged, spelled `restore()` |
| `CLOSED` | **not found** (popped) → `raised: false` → applet pushes → the frame reappears **only because `is_new` fires the side effect R8 retires** | found; visibility → `OPEN` + focus |

The middle column is F1 in one line: the closed-frame case works today *by
accident*, and the accident is exactly what criterion 3 removes. The
`display_control.raise_frame` contract is unchanged — a frame the Display does
not hold still answers `raised: false` rather than erroring, so an applet with
nothing up still learns to push one — but after this change a closed frame *is*
held, so the answer becomes `raised: true` and the applet's raise-first pattern
(`BoardChannel.raised` → skip the blanking push) behaves correctly for the first
time.

Vox's own menu-click fix (vox-640w, tracked in the vox repo) is to call
`raise_frame` on click instead of relying on a push to raise. That fix depends
on this one: without the closed frame being retained, `raise_frame` has nothing
to act on. **Both repos' fixes must be verified together**, and the vox agent
should be told when this lands.

---

## 7. Write-set for the implementation mission

Per the design-mission rule, this is the write-set, not a diff. Each entry names
the concern; the specialist decides the shape, and may create, split, or extract
modules not listed here.

### Display — the visibility type and the state it lives in

- `src/punt_lux/display/replica/frame.py` — `minimized: bool` becomes a
  three-valued visibility with predicates (`is_on_screen`, `is_docked`,
  `is_closed`) and mutators (`minimize()`, `close()`, `restore()`). The boolean
  and its setter are deleted, not aliased.
- `src/punt_lux/display/replica/frame_book.py` — queries the renderer asks
  instead of testing a flag (`on_screen()`, `docked()`, `closed()`); `close` as
  a visibility write; `ensure`'s new-frame policy (§3) as one named assignment.
- `src/punt_lux/display/replica/scene_replica.py` — split `close_frame` into
  `close` (visibility only) and `dispose_frame` (today's behaviour); strip
  `frame.minimized = False` and `request_focus` from
  `upsert_scene_in_frame`'s `is_new` branch; apply F2's active-tab rule.
- The visibility type may want its own module. The specialist's call.

### Display — the callers

- `src/punt_lux/display/frame_commands.py` — `raise_it` restores from any
  visibility (§6); `set_state` refuses a closed frame in both directions, so the
  dock toggle cannot become a second, gesture-less way back (§2.4, §10).
- `src/punt_lux/display/render_loop.py` — paint only on-screen frames; route the
  ✕ to `close` and Clear All / purge to `dispose_frame`; Fit All tiles on-screen
  frames; retire the `frame_close` send and the `notify` flag.
- `src/punt_lux/display/dock_bar.py`, `src/punt_lux/display/menus/projections.py`
  — ask the book for docked frames rather than testing `frame.minimized`.
- `src/punt_lux/display/menus/own_menus.py` — Windows menu: the closed-frames
  list, and `Expand All` covering closed (F3).
- `src/punt_lux/display/hub_reconciliation.py` — the purge routes to
  `dispose_frame`.

### Hub

- `src/punt_lux/domain/hub/hub_interaction_dispatch.py` — retire the
  `frame_close` branch (F4). `FrameLifecycle.remove_frame` stays for the TTL
  sweep.

### Introspection

`frame_count`'s docstring already says "open frames" and
will become false; `active_scene_id` must skip frames that are not on screen;
the `introspect` / `list_scenes` payloads should carry each frame's visibility,
because that is how the implementation mission's own verification step observes
the fix. Module ownership is the specialist's call.

### Tests

`tests/display/replica/test_scene_replica.py`,
`tests/display/replica/test_frame_book.py`, `tests/display/test_frame_commands.py`,
`tests/display/test_render_loop.py`, `tests/display/test_hub_reconciliation.py`,
`tests/domain/test_hub_interaction_dispatch.py`, `tests/test_display_partition.py`.
The tests must assert the modelled properties by name. The full partition
table, with every existing test marked COVERED, REPLACE, RETARGET or GAP, is
[`frame_visibility_lifecycle_coverage.md`](frame_visibility_lifecycle_coverage.md);
the summary is:

- *content never raises* — push (new and repeat) against `OPEN`, `MINIMIZED` and
  `CLOSED`; visibility and focus unchanged in all six.
- *known survives close* — close, then push the same scene id; it is a repeat,
  not an arrival.
- *the tab is not stolen* — a second scene arrives in a frame; the selection
  does not move.
- *close then raise* — **F1's composite**, the one that fails if either half
  ships alone.
- *dispose still forgets* — empty push and manifest purge return the id to
  never-seen, including on a closed frame.
- *closed husk* — a closed frame's last scene disposed disposes the frame.
- *widget state survives a close* and *queued interactions do not fire after a
  close*.

### Docs

- `DESIGN.md` — a new ADR recording this decision, superseding DES-025 and
  DES-060 as R8 already declares, and amending DES-063 with the
  raise-works-on-closed guarantee.
- `docs/architecture/workspace-model.tex` — `FrameVis` gains `fvClosed`;
  `CloseFrame` becomes a visibility transition rather than a removal; the
  removal becomes a separate dispose. This model is cited by DES-060 and will
  otherwise contradict the shipped code.
- `docs/architecture/target/target.md` — the Display-local/replicated split
  (§1's table). The document already says `SceneReplica` holds "exactly what the
  Hub's last resend put there, nothing more"; visibility is the counterexample
  and belongs beside the `WidgetStateStore` paragraph, which makes the same
  distinction for a different reason.
- `CHANGELOG.md`.

### Not in the write-set

No migration path, no compatibility shim, no dual
code path, no `minimized` alias, no feature flag, no "closed frames are
disposed after N minutes" grace period. The boolean is replaced and its callers
change with it, in one commit series.

---

## 8. Consequences, stated rather than discovered later

**8.1 Closing no longer tells the client anything.** Today `frame_close`
reaches the Hub. After F4 it reaches no one. Nothing consumes it apart from the
scene deletion being removed, so nothing regresses — but an applet that would
like to pause expensive work while its window is shut has no signal. If that is
ever wanted it is a new Hub→client notification, designed on its own merits, not
a reason to keep a deletion.

**8.2 A closed frame's scenes stay in the Hub's store.** Today the close deletes
them. After this change they live until the client disposes them, the client
disconnects (manifest purge), or the frame TTL passes. Bounded by client
lifetime, and the price of "closed is visibility, not deletion".

**8.3 Closed does not survive a Display restart.** A restarted Display rebuilds
its replica from the Hub's manifest and creates every frame fresh — `OPEN`, per
§3. Deliberate: `CLOSED` is Display-local session state like focus and cascade
position, neither of which survives either, and persisting it would mean
replicating a Display-owned value back to the Hub, which is the exact coupling
this design severs. R1's hidden-by-default window is the backstop that keeps a
restart from being a face-full of windows.

**8.4 The tab ✕ has the same defect, and is deliberately left alone.** Closing a
*tab* calls `dismiss_framed_scene`, which calls `forget_scene` — so the scene id
returns to never-seen and the next background push re-adds the tab, which is bug
B one level down. It is the same rule broken the same way, and it is genuinely
out of this change's reach: fixing it needs a *per-scene* visibility state, since
a dismissed tab is one scene put away inside a frame that stays on screen, and
this design's visibility is per-frame. **File it as a bead** rather than growing
this write-set — scope discovered outside the unit goes back to the backlog, and
a half-done per-scene visibility would be worse than the honest per-frame one.

**8.5 `lux frame close` on the client surface.** The parity design
(`docs/architecture/client-surface-parity-design.md`) plans a `frame_close`
client operation. It is not implemented, so nothing changes today — but when it
is, it is a **dispose** (a client saying its content is gone), not a
**close** (the user putting a window away). Same word, two operations; the
parity work should pick a different name for one of them.

---

## 9. Open items for the leader

1. **ProB — RESOLVED.** ProB 1.15.1 was installed and both documents were
   model-checked. The intact spec: 95 states, 845 transitions, all operations
   covered, no deadlock, no counter-example to any of the five goals; also clean
   at `DEFAULT_SETSIZE 3`. The control: 1030 states, every goal found. The run
   strengthened the model — see §5.
2. **Write-set (§7 vs the contract).** The mission's `write_set` names one file;
   this design also required `frame-visibility-lifecycle.tex` (criterion 4) and
   its fidelity control. Already raised with the leader; noted here for the
   record.
3. **F3's reopen affordance.** It is a small piece of new UI in a bug-fix
   change. Recommendation: keep it in, because without it the fix makes the
   close button a one-way door for every client that owns no menu entry.
4. **Cross-repo.** vox-640w's fix depends on this one landing. The vox agent
   should be told before this merges, per the cross-repo breaking-change
   protocol.
5. **New bead for the tab ✕ (§8.4).** Same defect one level down; needs
   per-scene visibility, which this write-set does not have. Recommendation:
   file it, do not grow this change.
6. **`make prob`'s cbc-deadlock step is broken repo-wide (§5).** It prints
   `*** DEADLOCK state found ***` for every Z spec in the repository, from a
   state that violates the spec's own state schema. Not this model's defect and
   not a carrier-size artifact — see the analysis in §5. `Makefile` is outside
   this write-set, so this needs the leader: drop the step or annotate it.
   Recommendation: drop it. A check that always fails trains everyone to ignore
   it.

Criterion 2 is **not** on this list: it resolves from R8's own acceptance tests
and `workspace-model.tex` without an operator ruling. §3 gives the reasoning.

---

## 10. Round-2 amendment: `set_frame_state` was a second door onto a closed frame

**Status:** found by `silent-failure-hunter` during leader review of the
implementation, ruled and fixed 2026-08-29.

**What was missed.** This document reasoned about the six call sites of
`close_frame` and about `raise_frame`, and concluded that a closed frame is
reachable only by a named user gesture (§6, F3). It never mentioned
`FrameCommands.set_state` — the `set_frame_state` operation, carried by the
whole client surface. That operation calls `restore()` on whatever frame it is
given, so after this design retained the closed frame, any client holding a
frame id could silently reopen a window the user had just shut.

**Why it is the same bug in a new place.** Bug B was a *content* event undoing
the user's decision. This is a *client command* doing it — different path, same
rule broken, and the same shape: no gesture, no focus, nothing to tell the user
where the window came from. Docking a closed frame is the mirror image and was
equally open: it would have given the frame a pill in the bar the user never
asked for.

**Why the old code did not have it.** Closing used to pop the frame out of the
book, so `set_state` on a closed frame raised `LookupError` — the door was shut
*by accident*, exactly as `raise_frame` was broken by accident (F1's shape,
one operation over). Retaining the frame is what opened it. This is a defect the
fix created, and it belongs in the same change.

**Why the model did not catch it.** The specification had no `SetDockState`
operation. A model cannot constrain an operation it does not carry, and
invariant 4 — "only a raise reopens a closed frame" — was true of every
transition the model knew about. The lesson is narrow and worth keeping: the
operation inventory is part of the model's fidelity, not scaffolding around it.
`frame-visibility-lifecycle.tex` now carries `SetDockState` with the guard, the
control carries it without, and the guard is evidenced by a deterministic replay
that fails at exactly that operation.

**Decision.** `set_state` refuses a closed frame in both directions, raising
rather than no-opping. A caller cannot see visibility from its own request, so a
quiet "nothing changed" would let it believe it had collapsed something —
and unexplained silence on this axis is what the whole design exists to remove.
The refusal names `raise_frame` as the operation that does apply. Undocking and
docking a frame that is *up* are untouched.
