# Frame Lifecycle: Test Partitions

Companion to [`frame-visibility-lifecycle.tex`](frame-visibility-lifecycle.tex),
verified by `scripts/verify_frame_visibility_model.sh` (`make check-models`).
Derives the test partitions (Test Template Framework style) from the Z
operation schemas of the two-state model (DES-103 decision 6). Each partition
is a test the implementation owes; the table in section 2 maps them to the
operation that must exhibit them.

This file lists the partitions the model implies. It makes no claim about which
tests exist today: the implementation contract audits `tests/display/` against
it.

## Spec operation to code

| Spec operation | Code |
|---|---|
| `PushNewFrame` | `FrameBook.ensure` (frame absent) + `SceneReplica.upsert_scene_in_frame` (`is_new`) |
| `PushNewScene` | `FrameBook.ensure` (frame present) + `upsert_scene_in_frame` (`is_new`) |
| `PushRepeat` | `upsert_scene_in_frame` (`not is_new`) |
| `DisposeScene` | `SceneReplica.dismiss_framed_scene` (frame keeps other scenes) |
| `DisposeFrame` | `dismiss_framed_scene` then `SceneReplica.dispose_frame` |
| `RegisterEndHandler` | the client's end-handler registration for one frame |
| `OwnerEnd` | the owner disposing every scene of the frame after the Display's request |
| `Minimize` | `FrameBook.minimize`, the frame's – control |
| `SetDockState` | `FrameCommands.set_state` (`set_frame_state`, Collapse All, Expand All) |
| `Raise` | `FrameCommands.raise_it` + `FrameBook.request_focus`; dock pill, Windows menu, the frame's menu entry |
| `End` | the frame's × after the confirm, routed to the owner by remote dispatch (D21) |
| `SelectTab` | `render_loop._render_frame_tabs` selection write-back |
| `ConsumeFocus` | `FrameBook.consume_focus` |

## 1. Partitions

### Push\* — over the target frame's visibility and handler

The cross product of *is the scene new* by *what the user had made of the
frame*. Every cell has the same expected result on the visibility axis:
**nothing changes**. That uniformity is the R8 rule.

| # | Partition | Expected |
|---|---|---|
| N1 | new scene, no frame yet | frame created `ON_SCREEN`, no end handler; **no focus request**; no other frame disturbed |
| N2 | new scene, frame `ON_SCREEN` | scene joins; visibility, focus and active tab unchanged |
| N3 | new scene, frame `DOCKED` | stays `DOCKED`; no focus; no tab steal |
| N4 | new scene, frame has no active tab (its first scene) | takes the active tab, the one legitimate tab write from content |
| R1 | repeat push, frame `ON_SCREEN` | repaints; visibility, focus, active tab unchanged |
| R2 | repeat push, frame `DOCKED` | stays `DOCKED` |
| R3 | repeat push, user had selected another tab | selection stands |
| R4 | repeat push, frame has an end handler | handler and any request in flight unchanged |

### Minimize(f?)

| # | Partition | Expected |
|---|---|---|
| M1 | minimize an `ON_SCREEN` frame | `DOCKED`; frame, scenes, widget state, active tab, cascade index kept |
| M2 | minimize: focus request held by that frame | cleared |
| M3 | minimize a frame with no end handler | allowed: every frame has – |
| M4 | minimize a frame with a request in flight | allowed; the request stands |
| M5 | minimize: the owner | not told; no event, no Hub-side scene removal |

### SetDockState(f?, v?)

| # | Partition | Expected |
|---|---|---|
| S1 | dock a frame that is on screen | `DOCKED`; no focus taken |
| S2 | undock a docked frame | `ON_SCREEN`; no focus taken, only `raise_it` focuses |
| S3 | set the value the frame already has | no-op, not a refusal |
| S4 | a request naming neither key | no-op, not a refusal |
| S5 | a frame the display does not hold | `LookupError` |

There is no refused-frame partition: both values are set on any frame.

### Raise(f?)

| # | Partition | Expected |
|---|---|---|
| A1 | raise an `ON_SCREEN` frame behind others | focus requested |
| A2 | raise a `DOCKED` frame | `ON_SCREEN` and focus, one gesture |
| A3 | raise a frame the display does not hold | `raised: false`, not an error |
| A4 | raise, then a background push | stays on screen |
| A5 | dock pill click | same restore path |
| A6 | Windows menu entry | restores that one frame |
| A7 | the frame's menu entry | same restore path |
| A8 | Expand All | restores every docked frame |

### RegisterEndHandler(f?)

| # | Partition | Expected |
|---|---|---|
| H1 | register for a frame the display holds | × appears on that frame |
| H2 | register: visibility, focus, active tab | none written |
| H3 | register for a frame the display does not hold | refused |
| H4 | a frame never registered | no ×, only – |
| H5 | the frame is disposed, id pushed again | new frame, no handler |

### End(f?) — the ×

| # | Partition | Expected |
|---|---|---|
| E1 | × on an on-screen frame with a handler, confirm | request routed to the owner; frame, content, visibility unchanged |
| E2 | × on a frame with no handler | not shown; the operation is refused on every surface |
| E3 | × on a docked frame | not reachable: the frame is not painted |
| E4 | × cancelled at the confirm | no event |
| E5 | × twice before the owner answers | one request in effect; no second frame removal |
| E6 | owner never answers | frame stays; – and Raise work |
| E7 | terminal frame, confirm | the shell ends; the window goes as on `exit` |

### OwnerEnd(f?)

| # | Partition | Expected |
|---|---|---|
| O1 | owner ends after a request | every scene of the frame disposed; frame, handler and request released |
| O2 | owner ends a frame that holds several scenes | all scenes go at once |
| O3 | owner ends a frame nobody asked it to end | not an `OwnerEnd`: an unrequested removal is `DisposeScene` or `DisposeFrame` |
| O4 | owner ends one frame | visibility, focus and active tab of every other frame unchanged |
| O5 | owner ends a docked frame | frame goes; the pill goes with it |
| O6 | the id is pushed again | genuinely new frame |

### DisposeScene / DisposeFrame

| # | Partition | Expected |
|---|---|---|
| D1 | empty push, frame holds other scenes | scene forgotten; frame stays; active tab falls back to a survivor; handler stays |
| D2 | empty push, last scene | frame disposed; ids and handler released; next push is genuinely new |
| D3 | empty push naming an absent frame | no-op |
| D4 | manifest purge sweeping a ghost scene | disposed; no event to the former owner |
| D5 | Clear All | every frame disposed whatever its visibility |
| D6 | tab ✕ emptying the frame | frame disposed |
| D7 | dispose the last scene of a `DOCKED` frame | frame disposed too: the husk rule ignores visibility |
| D8 | dispose: widget state | discarded |
| D9 | dispose: stale element ids | notified |
| D10 | a scene id shared across frames, one dismissed | the other frame's copy survives |
| D11 | dispose a frame with a request in flight | request released with the frame |

### Renderer and menu projections

| # | Partition | Expected |
|---|---|---|
| V1 | `ON_SCREEN` frame | painted, with – always and × only with a handler |
| V2 | `DOCKED` frame | not painted; dock pill shown |
| V3 | Fit All tiling | tiles on-screen frames only |
| V4 | Windows menu | lists every frame; Collapse All and Expand All reflect the two states |
| V5 | dock bar | shown exactly when a frame is docked |
| V6 | introspection payload | reports each frame's visibility and whether it has an end handler |
| V7 | `active_scene_id` | skips frames that are not on screen |

### Focus

| # | Partition | Expected |
|---|---|---|
| F1 | `ConsumeFocus` is one-shot | focused on the render after the request, not again |
| F2 | focus request on a disposed or ended frame | cleared with the frame |
| F3 | no content event ever leaves a focus request | invariant 1 |

## 2. Invariants and the partitions that carry them

| Model invariant | Partitions |
|---|---|
| 1. `autoFocused = {}` | N1, N3, A4, F3, O4 |
| 2. `tabStolen = {}` | N2, N3, R3 |
| 3. a docked frame is not on screen unless a visibility event put it there | N3, R2, A4, O4, O5, S1, S2 |
| 4. `endPending ⊆ handler` | E1, E2, H1, H4 |
| 5. deadlock freedom | the model check; no test |

## 3. Fidelity variants

Each variant is the intact model with one operation changed, generated by the
script from the `.tex`. Each must reach the goal of the invariant it breaks;
the intact model must not.

| Variant | Change | Goal found | Invariant | Partitions |
|---|---|---|---|---|
| `push-arrival` | new-frame and new-scene pushes raise the frame, request focus, take the tab | `autoFocused /= {}` | 1 | N1, N3 |
| `push-arrival` | same | `tabStolen /= {}` | 2 | N2, N3 |
| `push-arrival` | same | `card({f\|f:FRAME & f:frames & f:userDocked & vis(f)=vOnScreen})>0` | 3 | N3, A4 |
| `end-no-handler` | `End` does not require a handler | `not(endPending <: handler)` | 4 | E2, H4 |
| `end-writes-visibility` | `OwnerEnd` puts every surviving frame on screen | the invariant 3 goal | 3 | O4, O5 |

Three replays, run as `probcli -t` traces, pin single operations:

| Replay | Result | Partition |
|---|---|---|
| `PushNewFrame; RegisterEndHandler; End; OwnerEnd` | replays | E1, O1 |
| `PushNewFrame; End` | fails at `End` | E2 |
| `PushNewFrame; RegisterEndHandler; OwnerEnd` | fails at `OwnerEnd` | O3 |

`ALL OPERATIONS COVERED` on the intact model rules out a vacuous pass: no
invariant is discharged by an operation that never fired.

`make prob`'s `--- cbc deadlock ---` step prints `*** DEADLOCK state found ***`
for this spec and for every other Z spec in the repo, from a state that violates
the spec's own state schema. It is a ProB Z-mode artifact, not a finding.
