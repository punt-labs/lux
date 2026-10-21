# Frame-Info Popup: Test-Partition Coverage Audit

Companion to `docs/frame_info_popup.tex`. Derives the test partitions from the
Z operation schemas and maps each against the tests that cover it, the same way
`docs/display_lifecycle_coverage.md` and `docs/frame_expiry_coverage.md` map their
specs to code. The bar is that every partition is covered by a test that would
fail if the behaviour changed, not merely that the model-check passed.

Three kinds of test appear below, and they are not equal:

- **real** — `tests/display/test_frame_info_popup_real_imgui.py`: the production
  `RenderLoop` painting into a real headless ImGui context, with mouse edges
  queued the way a backend queues them. ImGui's own dismissals are the genuine
  article. Only these can attest to anything the model assumes about ImGui.
- **double** — the real `FrameInfoButton` / `PopupController` / `FrameInfoPopup`
  driven through `tests.menu_doubles.FakeImGui`. The code under test is real;
  ImGui is a script. Where a test makes ImGui dismiss the popup it does so by
  calling `dismiss_popup` at a moment the test chooses, so it proves the
  *code's* reaction to a dismissal, never that ImGui dismisses.
- **unit** — a single class (`GlyphReading`, `FrameInfoGlyph`, `PopupSite`)
  against a double. These bound a layer; they say nothing about the interaction.

A partition is **covered** only if a real test, or a double test of a purely
code-side behaviour, would fail on the corresponding defect. A double test that
scripts the ImGui behaviour the partition is about is listed, but marked.

## Spec-operation → design-element mapping

The design is `docs/architecture/target/target.md` (the Display is a replica that
renders and captures input); the concrete methods live in
`src/punt_lux/display/menus/`.

| Spec operation | Design element |
|---|---|
| `FramePress` | `PopupController.observe` on a reading with `pressed`: stores `GlyphPress(frame, popup.is_open_for(frame))`; `FrameInfoGlyph.render` / `GlyphReading.read` make the reading |
| `FrameRelease` | `PopupController.observe` on a reading with `clicked` → `_click` (open / request close / ignore), then `end_frame(is_released=...)` which discards the press record |
| `FrameIdle` | a render pass with no mouse edge: `FrameInfoButton.render_popup` → `FrameInfoPopup.render` (closes when its frame is gone or `begin_popup` reports it shut) |
| `FrameChange` | the replica gaining, losing, minimizing or restoring a frame between two render passes |
| `DragOut`, `DragBack` | the pointer moving while the button is held; `GlyphReading._is_undragged` reads ImGui's `mouse_drag_max_distance_sqr` (the latch), not the current offset |
| `site` | `PopupSite._open` (`None` = closed) |
| `press` | `PopupController._press` |
| `shut` | ImGui's popup stack, which the code reads only through `begin_popup` |

## Operation partitions and their tests

`R` = `test_frame_info_popup_real_imgui.py`, `T` = `test_frame_info_toggle.py`,
`P` = `test_frame_info_popup.py`, `B` = `test_frame_info_button.py`,
`GR` = `test_glyph_reading.py`, `G` = `test_frame_info_glyph.py`,
`S` = `test_popup_site.py`.

### FramePress

| Partition | Meaning | Covering test | Kind |
|---|---|---|---|
| PR1 | press on a glyph, popup closed | `R::test_a_real_click_leaves_the_popup_open[1,2,3,8]`; `T::test_a_press_and_release_on_the_glyph_across_frames_opens_the_popup` | real; double |
| PR2 | press on a glyph, popup open for it, press outside the popup (ImGui shuts it at the end of the frame) | `R::test_a_second_click_closes_a_popup_that_does_not_cover_the_glyph`; `R::test_a_second_click_released_on_the_frame_after_the_press_closes_the_popup`; `R::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup`; the premise itself: `R::test_imgui_shuts_the_popup_at_the_end_of_the_press_frame_not_during_it` | real |
| PR2d | the same, the code-side reaction only | `T::test_a_second_click_released_the_frame_after_the_press_closes_the_popup`; `T::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup` | double (scripts the dismissal) |
| PR3 | press on a glyph, popup open for it, press lands on the popup (it covers the glyph) | `R::test_a_second_click_on_the_glyph_closes_the_popup` (the popup is anchored at the glyph, so it covers it: `R::test_the_popup_sits_above_the_frame_that_spawned_it`); `P::TestGlyphToggle::test_clicking_the_glyph_again_dismisses_the_open_popup` | real; double |
| PR4 | press on a glyph, popup open for *another* frame, press outside it | `R::test_a_click_on_another_frames_glyph_moves_the_popup_to_it`; `T::test_a_click_on_another_frames_glyph_moves_the_popup_to_it` | real; double |
| PR5 | press on a glyph, popup open for another frame, the press lands on that popup | `T::test_a_click_on_a_glyph_under_the_open_popup_moves_the_popup_to_its_frame` | double (no dismissal scripted) |
| PR6 | press on no glyph, popup closed (including a near miss beside a glyph) | `R::test_a_release_on_the_glyph_whose_press_began_beside_it_does_not_open`; `T::test_a_release_on_the_glyph_whose_press_began_off_it_does_nothing` | real; double |
| PR7 | press on no glyph, popup open (outside the popup) | the dismissal itself is ImGui's, covered by the PR2 real tests; the code's reaction to a shut popup: `P::TestDismissal::test_an_outside_click_shuts_the_popup` | real (mechanism); double (reaction) |
| PR8 | press on the popup's own body, not a glyph | **not covered** — see Gap 2 | — |
| PR9 | Escape in the same frame | not applicable — see Gap 4 | — |

### FrameRelease

| Partition | Meaning | Covering test | Kind |
|---|---|---|---|
| RL1 | click, record says closed → open | PR1 tests; `B::test_clicking_the_button_opens_the_popup_at_the_anchor`; `P::TestGlyphToggle::test_clicking_the_glyph_opens_the_popup` | real; double |
| RL2 | click, record says closed, popup open for another frame → replaced | the PR4 and PR5 tests; popup layer alone: `P::TestOneAtATime` | real; double |
| RL3 | click, record says open, popup still open on the code's side → close | `R::test_a_second_click_on_the_glyph_closes_the_popup`; `R::test_a_second_click_released_on_the_frame_after_the_press_closes_the_popup`; `T::test_a_second_click_released_the_frame_after_the_press_closes_the_popup`; `P::TestGlyphToggle::test_the_glyph_reopens_the_popup_after_a_toggle_close` | real; double |
| RL4 | click, record says open, the code has seen ImGui shut it → nothing to close, **not** a reopen | `R::test_a_second_click_closes_a_popup_that_does_not_cover_the_glyph`; `R::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup`; `T::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup` | real; double |
| RL5 | release over a glyph, the press strayed (including away and back) → no action | `R::test_dragging_away_and_back_before_releasing_does_not_open_the_popup`; `R::test_dragging_away_and_back_over_an_open_popup_neither_closes_nor_reopens_it`; reading level: `GR::test_a_drag_keeps_the_press_but_not_the_click`, `G::test_a_release_that_dragged_reports_nothing`, `B::test_a_drag_that_ends_on_the_button_does_not_open_the_popup` | real; unit |
| RL6 | release over a glyph, the record names another frame → no action | `T::test_a_press_on_one_frames_glyph_released_on_anothers_does_nothing` | double |
| RL7 | release over a glyph, no record (press began off any glyph) → no action | `T::test_a_release_on_the_glyph_whose_press_began_off_it_does_nothing`; `R::test_a_release_on_the_glyph_whose_press_began_beside_it_does_not_open`; recovery: `T::test_a_proper_click_opens_the_popup_after_an_ignored_release`, `R::test_a_proper_click_opens_the_popup_after_a_near_miss` | double; real |
| RL8 | release over no glyph with a record held → the record is cleared | `T::test_a_drag_released_off_the_glyph_leaves_no_press_behind` | double |
| RL9 | release while the pressed frame is not drawn → the record is cleared | `T::test_a_release_after_the_pressed_frame_vanished_leaves_no_press_behind` | double |
| RL10 | the record survives the idle frames it is held across | `T::test_a_press_in_flight_survives_the_frames_it_is_held_across` | double |
| RL11 | the pressed frame vanishes and returns before the release → the click still acts | `T::test_a_press_survives_its_frame_vanishing_and_returning_before_the_release` | double |
| RL12 | Escape in the release frame | not applicable — see Gap 4 | — |

### FrameIdle, FrameChange, DragOut, DragBack

| Partition | Meaning | Covering test | Kind |
|---|---|---|---|
| ID1 | popup closed, nothing happens | `P::TestOpening::test_a_closed_popup_renders_nothing` | double |
| ID2 | ImGui has shut the popup → the code closes its state | PR2 real tests; `P::TestDismissal` (three tests) | real; double |
| ID3 | the popup's frame is gone → closed, logged once | `P::TestAutoClose::test_the_popup_closes_when_its_frame_is_gone`, `test_a_vanished_frame_is_logged_once_with_hub_and_frame`; `P::TestHubScoping::test_a_frame_that_exists_only_under_another_hub_is_treated_as_gone` | double (the replica is a function; nothing stubbed that the partition is about) |
| ID4 | the popup's frame still exists (folded or not) → stays | `P::TestAutoClose::test_the_popup_stays_open_while_its_frame_still_exists`; `P::TestHubScoping::test_a_frame_that_exists_under_its_own_hub_stays_open` | double |
| ID5 | a held title-bar press moves a window while a popup stands | **not covered, not coverable headlessly** — see Gap 3 | — |
| FC1 | a frame appears, vanishes, folds or unfolds between press and release | RL9, RL11; the glyph of a folded frame is not drawn: `B::test_the_button_is_not_drawn_on_a_collapsed_frame` | double |
| DG1 | the pointer leaves the threshold | the RL5 real tests | real |
| DG2 | the pointer returns; the latch stays | `R::test_dragging_away_and_back_before_releasing_does_not_open_the_popup` | real |

## The invariants, and what kills a violation

The check that a test suite has teeth is the same as the check that the model
does: remove the guard and see whether something fails. Each defect of the
specification's Section "Fidelity" was reproduced against the *code* by editing
the one guard out and running `tests/display/test_frame_info_*.py`,
`test_glyph_reading.py` and `test_popup_site.py`. Each edit was made in the working
tree, run, and reverted; none was committed.

| Mutation of the code (spec defect) | Invariant | Killed by | Killed by a real test? |
|---|---|---|---|
| (a) open on the press, no action on the release | I1, I2 | `R::test_a_second_click_on_the_glyph_closes_the_popup`, both `R` drag tests, five `T` tests, `P::TestGlyphToggle` (two), `B::test_a_drag_that_ends_on_the_button_does_not_open_the_popup` | yes, **but not by the test written to guard it** — see Gap 1 |
| (b) drag judged by the current offset, not the farthest travelled | I3 | `R::test_dragging_away_and_back_before_releasing_does_not_open_the_popup`, `R::test_dragging_away_and_back_over_an_open_popup_neither_closes_nor_reopens_it` (every double test also fails, with `AttributeError`, because the doubles supply no drag delta — those failures prove nothing) | yes, and only real tests can |
| (c) the toggle decided on the release from the current popup | I2 | `R::test_a_second_click_closes_a_popup_that_does_not_cover_the_glyph`, `R::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup`, `T::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup` | yes |
| (d) a release that is not a click leaves the record | I4 | `T::test_a_drag_released_off_the_glyph_leaves_no_press_behind`, `T::test_a_release_after_the_pressed_frame_vanished_leaves_no_press_behind` | no (double only) |
| (d′) a release clears the record only if a glyph saw it, not if the mouse did | I4 | `T::test_a_release_after_the_pressed_frame_vanished_leaves_no_press_behind` | no (double only) |
| (e) the popup survives its frame | I5 | `P::TestAutoClose` (two), `P::TestHubScoping` (one) | no (double only) |
| (f) a click acts for a record naming another frame | I4 | `T::test_a_press_on_one_frames_glyph_released_on_anothers_does_nothing` | no (double only) |
| (g) an unconditional close, with no check that the popup is still open | I2 | the three tests that kill (c) | yes |
| (h) a click cannot replace a popup open for another frame | I1 | `T::test_a_click_on_another_frames_glyph_moves_the_popup_to_it` | no (the real counterpart passes under the mutation only because the replaced popup was shut by ImGui first; see below) |

The last row deserves a word. `R::test_a_click_on_another_frames_glyph_moves_the_popup_to_it`
survives mutation (h) in the real harness: the press on the other frame's glyph is
outside the popup, ImGui shuts it, and the popup is closed by the time the release
arrives, so even a controller that refused to *replace* a popup would open the new
one. The test is real evidence that the two-frame arrangement works end to end; it
is not what guards the replace rule. The double test does.

## Model-check result

Every state of the bounded model is visited (`docs/frame_info_popup.tex`,
Section "Verification"):

| carrier | states | transitions | I1 | I2 | I3 | I4 | I5 | deadlock |
|---|---|---|---|---|---|---|---|---|
| 2 frames | 594 | 6172 | holds | holds | holds | holds | holds | none |
| 3 frames | 3105 | 40582 | holds | holds | holds | holds | holds | none |

The code at the branch head satisfies all five invariants over the model. No
counter-example was found, so there is no trace to report against the code.

## Gaps

1. **The test written to guard the "open on the press" defect does not guard it.**
   `R::test_a_real_click_leaves_the_popup_open` passes against a controller that
   opens the popup on the press and does nothing on the release. In the headless
   harness a popup opened at the root scope on the press frame is not shut by
   ImGui, even while the pointer is dragged (the model's assumption A2 records
   this). The mechanism the test's own docstring names — a title-bar press
   refocusing its frame and closing popups stacked over it — is therefore not
   what the test exercises today. The defect is still caught, by other tests
   (table row (a)), but by accident. Either the mechanism holds only in the
   application's ImGui configuration, in which case the test needs that
   configuration, or it no longer holds at all and the docstring and
   `GlyphReading`'s module docstring state something that is not so. Resolving
   it needs a decision about the rationale, not a test; it is reported rather
   than fixed.
2. **PR8: a press on the popup's own body is untested.** The controller records
   nothing for it (it is not a glyph), so the risk is ImGui's, not the code's. A
   real test would press inside the open popup, release, and assert it is still
   open. Not added: it exercises ImGui's behaviour only.
3. **ID5 / assumption A2 cannot be exercised headlessly.** There is no test that
   a held title-bar press shuts a standing popup, because the harness does not
   reproduce it. The intact controller never has a popup standing during a
   title-bar press, so no invariant depends on it (the model with the rule
   deleted visits the same 594 states).
4. **Escape does not dismiss the popup in this application's configuration**
   (probed headlessly: no keyboard navigation is enabled). Partitions PR9 and RL12
   are therefore unreachable today. The model keeps Escape as an input anyway
   (a superset), and the code's reaction to *any* dismissal is covered by ID2.
   If keyboard navigation is ever enabled, add a real Escape test then.
5. **Overlapping glyphs are not modelled.** The glyph hit-test is raw geometry, so
   two frames whose glyphs overlap would both read a press at one point. The
   controller keeps one press record, so the later glyph wins; no test covers it,
   and neither does the model.
6. **Late-arriving owner facts** change only the popup's rows and are covered by
   `T::test_facts_arriving_after_opening_replace_the_unknown_row` and its
   neighbours; they are outside the model's state because they cannot affect
   which frame the popup is open for.

## Tests added by this audit

Pure tests; no source file changed.

- `R::test_imgui_shuts_the_popup_at_the_end_of_the_press_frame_not_during_it` —
  pins the premise (A1) the model's `shut` rests on.
- `R::test_a_second_click_released_on_the_frame_after_the_press_closes_the_popup`
  and `R::test_a_second_click_released_after_a_held_frame_does_not_reopen_the_popup`
  — the two sides of the one-frame-late dismissal, with real ImGui.
- `R::test_a_click_on_another_frames_glyph_moves_the_popup_to_it` — replacement
  with two real frames.
- `R::test_dragging_away_and_back_over_an_open_popup_neither_closes_nor_reopens_it`
  — Invariant 3 on an *open* popup, which no test covered.
- `T::` the quick close, the close after a held frame, replacement (outside and
  under the popup), and a press surviving its frame vanishing and returning.

Re-run `fuzz` and the model-check whenever `popup_controller.py`,
`glyph_reading.py`, `frame_info_popup.py`, `popup_site.py` or the order of
`_render_frames` and `render_popup` in `render_loop.py` changes.
