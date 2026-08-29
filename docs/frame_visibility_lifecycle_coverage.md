# Frame Visibility Lifecycle: Test-Partition Coverage Audit

Companion to [`frame-visibility-lifecycle.tex`](frame-visibility-lifecycle.tex)
and its fidelity control
[`frame-visibility-lifecycle_buggy.tex`](frame-visibility-lifecycle_buggy.tex).
Derives the test partitions (Test Template Framework style) from the Z operation
schemas, then maps them against the tests in `tests/display/replica/` and
`tests/display/`. The bar is that the spec's partitions are covered by a test,
not merely that the model type-checks.

**This audit is written at design time**, so most rows are GAPs by
construction — the code the spec describes does not exist yet. That is the
point: the GAP column is the implementation mission's test plan, and every row
marked REPLACE names a test that today asserts a behaviour DES-065 R8 retires.

Spec-operation → code mapping (target state, not current):

| Spec operation | Code |
|---|---|
| `PushNewFrame` | `FrameBook.ensure` (frame absent) + `SceneReplica.upsert_scene_in_frame` (`is_new`) |
| `PushNewScene` | `FrameBook.ensure` (frame present) + `upsert_scene_in_frame` (`is_new`) |
| `PushRepeat` | `upsert_scene_in_frame` (`not is_new`) → `_replace_scene_state` |
| `DisposeScene` | `SceneReplica.dismiss_framed_scene` (frame keeps other scenes) |
| `DisposeFrame` | `dismiss_framed_scene` → `SceneReplica.dispose_frame` (the split's content half) |
| `Minimize` | `FrameBook.minimize`, `render_loop._render_frames` `"minimized"` result |
| `Close` | `SceneReplica.close` (the split's visibility half), `render_loop._render_frames` `"closed"` result |
| `Raise` | `FrameCommands.raise_it` → `Frame.restore()` + `FrameBook.request_focus`; also `DockPill`, `Expand All`, the Windows menu's closed list |
| `SelectTab` | `render_loop._render_frame_tabs` selection write-back |
| `ConsumeFocus` | `FrameBook.consume_focus` |

Two operations have no code today and are the change: `Close` as a visibility
write, and `Raise` from a closed frame.

## 1. Partitions

### PushNewFrame / PushNewScene / PushRepeat — over the target frame's visibility

The cross product of *is the scene new* × *what the user had made of the frame*.
Every cell has the same expected result on the visibility axis: **nothing
changes**. That uniformity is the R8 rule, and it is why the table is worth
writing out rather than sampling.

| # | Partition | Expected |
|---|---|---|
| N1 | new scene, no frame yet | frame created `OPEN`; **no focus request**; no other frame disturbed |
| N2 | new scene, frame `OPEN` | scene joins; visibility, focus and active tab unchanged |
| N3 | new scene, frame `MINIMIZED` | stays `MINIMIZED`; no focus; no tab steal |
| N4 | new scene, frame `CLOSED` | stays `CLOSED`; no focus; no tab steal |
| N5 | new scene, frame has no active tab (its first scene) | takes the active tab — the one legitimate tab write from content |
| R1 | repeat push, frame `OPEN` | repaints; visibility, focus, active tab unchanged |
| R2 | repeat push, frame `MINIMIZED` | stays `MINIMIZED` |
| R3 | repeat push, frame `CLOSED` | stays `CLOSED` — **bug B's partition** |
| R4 | repeat push, user had selected another tab | selection stands |
| R5 | repeat push after a close, same scene id | reads as a **repeat**, not an arrival — `known` survived the close |
| R6 | repeat push relocating a scene to another frame | old frame disposed if emptied; neither frame's visibility written |

### Close(f?) — the visibility half of the split

| # | Partition | Expected |
|---|---|---|
| X1 | close an `OPEN` frame | visibility `CLOSED`; frame still in the book |
| X2 | close a `MINIMIZED` frame | visibility `CLOSED`; no dock pill afterwards |
| X3 | close: scene ids | still in `scene_to_frame` — **not** forgotten |
| X4 | close: widget state | preserved (scroll, selection, in-progress text) |
| X5 | close: stale-id notification | **none** — no element was replaced |
| X6 | close: queued interactions for the frame's elements | drained; a shut window's button does not fire later |
| X7 | close: focus request held by that frame | cleared |
| X8 | close: the Hub | **not told** — no `frame_close` event, no Hub-side scene removal |
| X9 | close a frame that is not up | no-op, not an error |

### DisposeScene / DisposeFrame — the content half of the split

| # | Partition | Expected |
|---|---|---|
| D1 | empty push, frame holds other scenes | scene forgotten; frame stays; active tab falls back to a survivor |
| D2 | empty push, last scene | frame disposed; ids released; next push is genuinely new |
| D3 | empty push naming an absent frame | no-op |
| D4 | manifest purge sweeping a ghost scene | disposed; no `frame_close` event to the former owner |
| D5 | Clear All | every frame disposed whatever its visibility |
| D6 | tab ✕ emptying the frame | frame disposed |
| D7 | **dispose the last scene of a `CLOSED` frame** | **frame disposed too — the husk rule ignores visibility** |
| D8 | dispose: widget state | discarded (unlike close — X4) |
| D9 | dispose: stale element ids | notified (unlike close — X5) |
| D10 | a scene id shared across frames, one dismissed | the other frame's copy survives |

### Raise(f?) — the user gesture, DES-063's raise-first path

| # | Partition | Expected |
|---|---|---|
| A1 | raise an `OPEN` frame behind others | focus requested |
| A2 | raise a `MINIMIZED` frame | `OPEN` + focus, one gesture |
| A3 | **raise a `CLOSED` frame** | **`OPEN` + focus — bug A's partition** |
| A4 | raise a frame the display does not hold | `raised: false`, not an error; the applet learns to push |
| A5 | **close, then raise** | on screen — **the composite that fails if either half of the fix ships alone** |
| A6 | raise, then a background push | stays open; the push does not undo the raise |
| A7 | dock pill click on a minimized frame | same restore path |
| A8 | Expand All | restores docked **and** closed frames |
| A9 | Windows menu's closed-frame entry | restores that one frame |

### Renderer and menu projections — over the three-valued visibility

| # | Partition | Expected |
|---|---|---|
| V1 | `OPEN` frame | painted |
| V2 | `MINIMIZED` frame | not painted; dock pill shown |
| V3 | `CLOSED` frame | not painted; **no dock pill** |
| V4 | Fit All tiling | tiles on-screen frames only |
| V5 | Windows menu enablement | Collapse All / Expand All / the closed list reflect the three states |
| V6 | dock bar suppression when nothing is docked | a workspace of only closed frames shows no bar |
| V7 | introspection payload | reports each frame's visibility, so the fix is observable through the real entry point |
| V8 | `active_scene_id` | skips frames that are not on screen |

### Focus

| # | Partition | Expected |
|---|---|---|
| F1 | `ConsumeFocus` is one-shot | focused on the render after the request, not again |
| F2 | focus request on a disposed frame | cleared with the frame |
| F3 | **no content event ever leaves a focus request** | the whole of invariant 1 |

## 2. Coverage table

Status key: **COVERED** — an existing test already asserts this partition and
stays valid. **REPLACE** — an existing test asserts the behaviour R8 retires and
must be inverted. **RETARGET** — an existing test is valid but names
`close_frame` and must follow the operation to `dispose_frame`. **GAP** — no
test exists; the implementation mission writes it.

| Partition | Covering test | Status |
|---|---|---|
| N1 | `test_scene_replica.py::test_frame_created_with_scene` (structure only) | GAP — the focus assertion is missing |
| N2 | `test_scene_replica.py::test_second_scene_joins_frame` (structure only) | GAP — visibility/focus/tab assertions missing |
| N3 | `test_scene_replica.py::test_a_new_scene_still_raises_its_frame_and_takes_focus` | **REPLACE** — asserts the retired behaviour by name |
| N4 | — | GAP |
| N5 | `test_scene_replica.py::test_frame_created_with_scene` | COVERED |
| R1 | `test_scene_replica.py::test_replacement_overwrites_scene` | COVERED |
| R2 | `test_scene_replica.py::test_a_replace_leaves_a_minimized_frame_minimized` | COVERED |
| R3 | — | **GAP — bug B** |
| R4 | `test_scene_replica.py::test_a_replace_leaves_the_tab_the_user_picked` | COVERED |
| R5 | — | **GAP — bug B's mechanism, the highest-value single test** |
| R6 | `test_scene_replica.py::test_scene_moves_between_frames` | GAP — visibility assertion missing |
| X1–X2 | — | GAP |
| X3 | — | **GAP — "known survives close"** |
| X4 | — | GAP (the mirror of `test_widget_state_is_discarded_only_for_the_purged_scene`) |
| X5 | — | GAP |
| X6 | — | GAP |
| X7 | `test_scene_replica.py::test_focus_frame_cleared`, `test_frame_book.py::test_pop_returns_frame_and_clears_focus_when_it_held_it` | RETARGET |
| X8 | `tests/domain/test_hub_interaction_dispatch.py::test_hub_interaction_dispatch_frame_close_removes_the_frames_scenes` | **REPLACE** — asserts the Hub-side deletion F4 retires |
| X9 | `test_scene_replica.py::test_close_nonexistent_frame` | RETARGET |
| D1 | `test_scene_replica.py::test_cleanup_and_next_tab_selection` | COVERED |
| D2 | `test_scene_replica.py::test_dismiss_last_scene_empties_the_frame`, `test_empty_framed_scene_closes_its_only_frame` | RETARGET |
| D3 | `test_scene_replica.py::test_empty_framed_scene_for_an_absent_frame_is_a_noop` | COVERED |
| D4 | `tests/display/test_render_loop.py::test_a_manifest_driven_purge_sends_no_frame_close_event` | RETARGET — the `notify` flag goes away with F4; the property (no event to the former owner) survives trivially |
| D4b | `tests/display/test_render_loop.py::test_a_user_initiated_close_still_notifies_the_owner` | **REPLACE** — asserts the `frame_close` send F4 retires |
| D5 | `test_scene_replica.py::test_everything_empty`, `test_clear_all_idempotent` | RETARGET |
| D6 | `tests/test_display_partition.py` (tab-close path) | RETARGET |
| D7 | — | **GAP — the husk rule against a closed frame** |
| D8 | `test_scene_replica.py::test_frame_and_scene_state_cleaned` | RETARGET |
| D9 | `test_scene_replica.py::test_replace_preserves_survivor_state_discards_stale` | COVERED |
| D10 | `test_scene_replica.py::test_shared_id_across_frames_survives_one_dismissal` | COVERED |
| A1–A2 | `tests/display/test_frame_commands.py::test_raising_a_frame_restores_it_and_asks_for_focus` | COVERED |
| A3 | — | **GAP — bug A** |
| A4 | `test_frame_commands.py::test_raising_a_frame_that_is_not_up_is_an_answer_not_an_error` | COVERED |
| A5 | — | **GAP — the composite; see §4.1 F1 of the design note** |
| A6 | — | GAP |
| A7 | `tests/test_dock_bar.py` | COVERED |
| A8–A9 | — | GAP (new behaviour, F3) |
| V1–V2 | `tests/test_dock_bar.py`, `tests/test_display_partition.py` | COVERED |
| V3 | — | GAP |
| V4 | `tests/test_display_partition.py` (fit-all) | GAP — must exclude closed |
| V5 | `tests/display/test_menu_inventory.py` | GAP — the closed list is new |
| V6 | `tests/test_dock_bar.py`, `tests/test_menu_projections.py` | COVERED |
| V7 | `tests/display/test_scene_inspection.py` | GAP — visibility is not in the payload today |
| V8 | — | GAP |
| F1 | `tests/display/replica/test_frame_book.py::test_consume_is_one_shot` | COVERED |
| F2 | `test_scene_replica.py::test_focus_frame_cleared` | RETARGET |
| F3 | `test_scene_replica.py::test_a_replace_leaves_the_foreground_frame_focused` | partial — covers repeat only; **GAP** for the new-scene cases (N1–N4) |

## 3. The two tests that must not be forgotten

Everything above is bookkeeping except these.

**R5 / X3 — a push after a close reads as a repeat.** This is bug B's mechanism
rather than its symptom, and it is the one assertion that cannot be satisfied by
accident. Push a scene, close its frame, push the same scene id again, and
assert the frame is still `CLOSED`. If `close` still calls `forget_scene`, the
second push is an arrival and the test fails.

**A5 — close, then raise.** The design note's finding F1: today's only reopen
path for a closed frame *is* bug B, so retiring the `is_new` side effect without
retaining the closed frame makes the close button a one-way door. Neither half
of the fix can be verified alone; this test is the one that fails if either
ships without the other.

## 4. Fidelity control

The buggy variant reaches five states the specification cannot. Each maps to a
partition above, and to a test that must go from failing to passing:

| Goal (negated invariant) | Partition | Defect |
|---|---|---|
| `autoFocused /= {}` | N1, N3, F3 | the DES-025 / DES-060 focus steal |
| `tabStolen /= {}` | N2, N3 | the active-tab steal (F2 of the design note) |
| `userClosed /\ frames /= userClosed` | A3, A5 | **bug A** — the closed frame cannot be raised |
| `card({f\|f:FRAME & f:frames & f:userClosed & vis(f)=vOpen})>0` | R3, R5 | **bug B** — the closed frame reopens on a push |
| `#s.(s:closedScenes & vis(sceneFrame(s))=vOpen)` | R5 | **bug B, same scene id** — the scene the user shut is back in front of them |

**Both legs have been run.** `fuzz -t` exits 0 on both documents. ProB 1.15.1
(SICStus 4.8.0) explores the intact spec's whole reachable state space — 95
states, 845 transitions, `ALL OPERATIONS COVERED`, no deadlock — and finds no
counter-example to any of the five goals. The control reaches all five, over
1030 states. `ALL OPERATIONS COVERED` on both is what rules out a vacuous pass:
no invariant is discharged by an operation that never fired.

The two partitions that carry the change (§3) map to two deterministic
`probcli -t` trace replays rather than to search-order witnesses, which are not
stable between runs:

| Replay | Control | Intact spec | Partition |
|---|---|---|---|
| `PushNewFrame; Close; PushNewFrame` (same frame and scene id) | replays | fails at step 3 | **R5 / X3** |
| `PushNewFrame; Close; Raise` | fails at step 3 | replays | **A3 / A5** |

Each names one operation that is enabled in one design and not the other, which
is exactly what the corresponding test must assert.

Two things the run surfaced. R5 needed the `closedScenes` ghost in the model:
a ProB goal may not name an element of a given set (`FRAME2 : frames` raises
`type_expression_error` and makes the check pass *vacuously*), so "the same
scene came back" could not be stated as a cleverer goal over the original state.
And the witness traces varied in length across repeated runs of one goal, which
is why the replays above — not the witnesses — are the citable artifact.
