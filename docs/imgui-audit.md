# ImGui Demo Audit vs Lux Element Coverage

**Date**: 2026-03-20
**ImGui version**: 1.92.7 (imgui_demo.cpp)
**Lux version**: 0.5.x (23 element types, 69 imgui calls)

## Coverage Summary

| Category | ImGui Demo | Lux Supports | Coverage |
|----------|-----------|-------------|----------|
| Widget types (high-level) | 35+ | 23 | 66% |
| Unique imgui function calls | 150+ | 69 | ~46% |
| Input/manipulation widgets | 20+ | 4 | 20% |
| Menu & popups | 10+ | 2 | 20% |
| Layout & spacing | 15+ | 6 | 40% |
| Drawing & canvas | 20+ | 8 | 40% |
| Drag & drop | 5 | 0 | 0% |
| Multi-select | 5+ | 0 | 0% |
| Docking | 3 | 0 | 0% |

## What Lux Supports Today (23 elements)

| # | Element | ImGui Calls | Notes |
|---|---------|------------|-------|
| 1 | `text` | Text, TextWrapped, TextColored, TextDisabled | Styled variants: heading, caption, code |
| 2 | `button` | Button, SmallButton | With optional shortcut keys |
| 3 | `separator` | Separator, SeparatorText | Horizontal divider |
| 4 | `image` | Image | Texture from file path |
| 5 | `slider` | SliderInt, SliderFloat | Min/max/format |
| 6 | `checkbox` | Checkbox | Boolean toggle |
| 7 | `combo` | BeginCombo/EndCombo | Dropdown list |
| 8 | `input_text` | InputText, InputTextWithHint | With optional hint, read-only |
| 9 | `radio` | RadioButton | Radio button group |
| 10 | `color_picker` | ColorEdit3 | RGB picker |
| 11 | `draw` | DrawList (AddLine, AddRect, AddCircle, etc.) | Canvas with basic shapes |
| 12 | `group` | SameLine, Indent, Dummy | Rows, columns, flow, spread, paged layout |
| 13 | `tab_bar` | BeginTabBar/BeginTabItem | Tabbed container |
| 14 | `collapsing_header` | CollapsingHeader | Foldable section |
| 15 | `window` | Begin/End | Floating window with position/size |
| 16 | `selectable` | Selectable | Clickable list item |
| 17 | `tree` | TreeNode, TreeNodeEx | Hierarchical tree |
| 18 | `table` | BeginTable + full table API | Columns, rows, cell coloring, sortable |
| 19 | `plot` | ImPlot (external) | Line/bar/scatter charts |
| 20 | `progress` | ProgressBar | Including indeterminate |
| 21 | `spinner` | Custom draw | Animated loading indicator |
| 22 | `markdown` | Custom renderer | Rendered markdown text |
| 23 | `render_function` | N/A | Agent-submitted Python (AST-scanned) |

## Full Gap Analysis

### Tier 1: High Value, Low Complexity

These fill the most obvious holes for agent-driven UIs. Each maps cleanly to the JSON protocol.

| Priority | Widget | ImGui API | Why It Matters |
|----------|--------|-----------|---------------|
| **1** | **InputInt / InputFloat** | `InputInt`, `InputFloat`, `InputDouble` | Numeric input with validation. Currently agents must use `input_text` and parse strings. Type-safe numeric fields are the most requested missing input. |
| **2** | **ColorEdit4 / ColorPicker4** | `ColorEdit4`, `ColorPicker4` | Alpha channel support. Lux only has `ColorEdit3`. Any theming or visual design tool needs RGBA. |
| **3** | **Modal popup** | `BeginPopupModal`, `EndPopupModal`, `OpenPopup` | Confirmation dialogs ("Delete this?", "Are you sure?"). No current way to block interaction and force a choice. |
| **4** | **ArrowButton** | `ArrowButton` | Directional navigation (prev/next, expand/collapse). Trivial to add — one imgui call, reuses button event path. |
| **5** | **ListBox** | `BeginListBox`, `EndListBox` | Scrollable selection list. Selectables-in-a-child-window works but a dedicated element is cleaner for agents. |
| **6** | **InputTextMultiline** | `InputTextMultiline` | Multi-line text editing. Currently `input_text` is single-line only. Needed for any code/note editing surface. |
| **7** | **Disabled regions** | `BeginDisabled`, `EndDisabled` | Gray out sections conditionally. Useful for forms where some fields depend on others. Could be a flag on `group`. |

### Tier 2: Medium Value, Medium Complexity

These require modest protocol extensions but unlock new interaction patterns.

| Priority | Widget | ImGui API | Why It Matters |
|----------|--------|-----------|---------------|
| **8** | **DragInt / DragFloat** | `DragInt`, `DragFloat`, `DragIntRange2`, `DragFloatRange2` | Click-drag to adjust, Ctrl+Click to type. More intuitive than sliders for unbounded values. Range variant enables min/max pair editing. |
| **9** | **Vertical slider** | `VSliderInt`, `VSliderFloat` | Mixing boards, equalizers, level controls. Lux only has horizontal sliders. |
| **10** | **Context menu** | `BeginPopupContextItem`, `BeginPopupContextWindow` | Right-click menus on items or background. Standard UI pattern missing entirely. |
| **11** | **Main menu bar** | `BeginMainMenuBar`, `EndMainMenuBar` | App-level menu bar. Lux has per-window menus but no top-level bar. |
| **12** | **Multi-component inputs** | `InputFloat2/3/4`, `SliderFloat2/3/4` | Vector editing (positions, colors, sizes). Currently requires 3-4 separate sliders in a group. |
| **13** | **BulletText** | `BulletText`, `Bullet` | Bulleted lists. Currently requires text with manual "* " prefix. Trivial but polishes output. |
| **14** | **TextLink** | `TextLinkOpenURL` | Clickable hyperlinks. Currently no way to render a URL as a link. |

### Tier 3: High Value, High Complexity

These require significant protocol work or stateful interaction models.

| Priority | Widget | ImGui API | Why It Matters |
|----------|--------|-----------|---------------|
| **15** | **Drag & drop** | `BeginDragDropSource/Target`, `SetDragDropPayload`, `AcceptDragDropPayload` | Reordering lists, moving items between containers, spatial arrangement. Requires multi-frame state tracking and payload serialization. |
| **16** | **Multi-select** | `BeginMultiSelect`, `EndMultiSelect`, `ImGuiMultiSelectIO` | Select multiple items in trees/lists for bulk operations. Complex selection state (range, toggle, all/none). |
| **17** | **Docking** | `DockSpace`, `DockSpaceOverViewport`, `SetNextWindowDockID` | User-rearrangeable window layout. The Pharo/Smalltalk vision needs this — windows that dock, split, and tab together. |
| **18** | **Scroll control** | `SetScrollX/Y`, `GetScrollX/Y`, `SetScrollFromPos` | Programmatic scrolling. Agent can't currently scroll a child window to a specific item. |
| **19** | **Font stack** | `PushFont`, `PopFont` | Multiple font sizes/weights in one view. Currently Lux loads one font. Needed for proper typography hierarchy. |

### Tier 4: Nice to Have / Debug

Low priority for agent use cases, but useful for the Pharo-like inspector vision.

| Widget | ImGui API | Notes |
|--------|-----------|-------|
| Metrics window | `ShowMetricsWindow` | Debug: render stats, draw call count |
| ID stack tool | `ShowIDStackToolWindow` | Debug: ID conflict diagnosis |
| Style editor | `ShowStyleEditor` | Live theme tweaking |
| PlotLines/PlotHistogram (native) | `PlotLines`, `PlotHistogram` | ImGui's built-in are weak; ImPlot (already in Lux) is better |
| SliderAngle | `SliderAngle` | Niche: angle input with degree display |
| Columns (legacy) | `Columns`, `NextColumn` | Deprecated; tables supersede |

## Recommended Implementation Order

### Phase A — Complete the input story (Tier 1, items 1-7)

These are the lowest-hanging fruit. Each is a single new element type with a straightforward render path and event model matching existing patterns. After this phase, Lux covers all common form widgets.

Estimated: 7 element types, ~200 lines of display.py + protocol.py each.

### Phase B — Richer interaction (Tier 2, items 8-14)

These expand what agents can build from "forms and dashboards" to "interactive tools." DragFloat and context menus are the highest-value items here.

Estimated: 7 element types, moderate protocol additions for drag values and popup state.

### Phase C — Spatial interaction (Tier 3, items 15-19)

These are the building blocks for the Pharo vision. Docking and drag-drop require rethinking how the protocol handles multi-frame interactions. Font stack requires asset management.

Estimated: architecture work, likely 0.6.x or 0.7.x scope.

## Design Considerations

### Protocol compatibility

Every new element must be fully describable as JSON. The test: can an agent build a valid element dict without understanding ImGui internals?

- **Good**: `{"type": "input_float", "id": "x", "value": 3.14, "min": 0, "max": 10}`
- **Bad**: requiring the agent to manage ImGui state flags or frame-to-frame continuity

### Event model

New interactive elements need to fit the existing event polling model (`recv()` returns events). Modal popups need a "popup closed with result X" event. Drag-drop needs "drag started," "drag hovering over target," "dropped on target" events.

### The disabled flag

Rather than a standalone `BeginDisabled` element, add an optional `disabled: bool` field to all interactive elements and to `group`. This composes better in the JSON protocol — no need to track Begin/End pairing.

### Multi-component inputs

Rather than separate `input_float2`, `input_float3`, `input_float4` types, consider a single `input_vector` element with a `components: int` field. Reduces type proliferation.

### Docking (Pharo path)

Docking is the single most impactful feature for the Smalltalk vision. It turns Lux from "agent shows you things" into "agent and user co-arrange a workspace." This deserves its own design doc before implementation.
