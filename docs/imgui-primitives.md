# Dear ImGui: Comprehensive Widget & Primitive Reference

Research date: 2026-03-06
Sources: imgui.h (ocornut/imgui), implot.h (epezent/implot), imgui_bundle (pthom/imgui_bundle)

---

## Key URLs

| Resource | URL |
|----------|-----|
| Interactive Explorer (imgui-bundle) | https://traineq.org/imgui_bundle_explorer |
| ImPlot Online Demo | https://traineq.org/implot_demo/src/implot_demo.html |
| Pyodide Playground (run in browser) | https://traineq.org/imgui_bundle_online/projects/imgui_bundle_playground/ |
| imgui-bundle Docs | https://pthom.github.io/imgui_bundle/ |
| Dear ImGui GitHub | https://github.com/ocornut/imgui |
| imgui-bundle GitHub | https://github.com/pthom/imgui_bundle |

---

## Python vs C++ API (imgui-bundle)

The imgui-bundle README states: **"C++ and Python APIs with very similar structure."** The Python bindings are auto-generated from C++ headers and follow the same function names, argument order, and semantics. Key differences:

- Python uses `snake_case` (e.g., `imgui.begin_child()`) where C++ uses `PascalCase` (`ImGui::BeginChild()`)
- Enum values follow the same translation: `ImGuiWindowFlags_NoTitleBar` becomes `imgui.WindowFlags_.no_title_bar`
- Output parameters (pointers in C++) become return tuples in Python (e.g., `changed, value = imgui.slider_float(...)`)
- `ImVec2`/`ImVec4` map to tuples or dedicated types
- The Begin/End pattern is identical in both languages

---

## Part 1: Core Dear ImGui Widgets

### 1.1 Windows

| Function | Description |
|----------|-------------|
| `Begin` / `End` | Push/pop a window; all widgets go between these |
| `BeginChild` / `EndChild` | Self-contained scrolling/clipping child region |
| `SetNextWindowPos` | Set window position before `Begin()` |
| `SetNextWindowSize` | Set window size before `Begin()` |
| `SetNextWindowSizeConstraints` | Apply min/max size constraints |
| `SetNextWindowContentSize` | Set scrollable content area size |
| `SetNextWindowCollapsed` | Set collapsed state before `Begin()` |
| `SetNextWindowFocus` | Prioritize window focus |
| `SetNextWindowScroll` | Set scroll position before `Begin()` |
| `SetNextWindowBgAlpha` | Set background transparency |
| `IsWindowAppearing` | Check if window just appeared |
| `IsWindowCollapsed` | Check collapsed state |
| `IsWindowFocused` | Query focus with optional flags |
| `IsWindowHovered` | Check if hovered with optional flags |
| `GetWindowDrawList` | Get the ImDrawList for custom drawing |
| `GetWindowPos` / `GetWindowSize` | Query window geometry |

### 1.2 Text Display

| Function | Description |
|----------|-------------|
| `Text` | Formatted text output |
| `TextUnformatted` | Raw text without printf overhead (fastest) |
| `TextColored` | Text with custom RGBA color |
| `TextDisabled` | Grayed-out text |
| `TextWrapped` | Word-wrapped text |
| `LabelText` | Label with right-aligned value text |
| `BulletText` | Bullet point followed by text |
| `SeparatorText` | Horizontal rule with centered text label |

### 1.3 Buttons

| Function | Description |
|----------|-------------|
| `Button` | Standard clickable button |
| `SmallButton` | Compact button without frame padding |
| `InvisibleButton` | Hit-detection rectangle with no visuals |
| `ArrowButton` | Button displaying a directional arrow |
| `TextLink` | Hyperlink-style clickable text |
| `TextLinkOpenURL` | Hyperlink that opens a URL or file path |
| `ImageButton` | Clickable image/texture button |
| `ColorButton` | Small colored square button (used with color editors) |
| `RadioButton` | Single-selection radio button |
| `Checkbox` | Boolean toggle checkbox |
| `CheckboxFlags` | Checkbox that toggles a bit flag |

### 1.4 Combo Box (Dropdown)

| Function | Description |
|----------|-------------|
| `BeginCombo` / `EndCombo` | Begin/end a dropdown; items go between |
| `Combo` | Simple one-liner combo from string array or getter |

### 1.5 Drag Inputs

| Function | Description |
|----------|-------------|
| `DragFloat` | Mouse-drag float input with configurable speed |
| `DragFloat2` / `DragFloat3` / `DragFloat4` | Multi-component float drag |
| `DragFloatRange2` | Min/max float range via two drag handles |
| `DragInt` | Mouse-drag integer input |
| `DragInt2` / `DragInt3` / `DragInt4` | Multi-component integer drag |
| `DragIntRange2` | Min/max integer range |
| `DragScalar` / `DragScalarN` | Generic typed scalar drag (any numeric type) |

### 1.6 Slider Inputs

| Function | Description |
|----------|-------------|
| `SliderFloat` | Horizontal float slider with defined range |
| `SliderFloat2` / `SliderFloat3` / `SliderFloat4` | Multi-component float slider |
| `SliderAngle` | Angle slider displaying degrees |
| `SliderInt` | Horizontal integer slider |
| `SliderInt2` / `SliderInt3` / `SliderInt4` | Multi-component integer slider |
| `SliderScalar` / `SliderScalarN` | Generic typed scalar slider |
| `VSliderFloat` | Vertical float slider |
| `VSliderInt` | Vertical integer slider |
| `VSliderScalar` | Vertical generic scalar slider |

### 1.7 Text Inputs

| Function | Description |
|----------|-------------|
| `InputText` | Single-line text input with callbacks |
| `InputTextMultiline` | Multi-line text editor |
| `InputTextWithHint` | Text input with placeholder/hint text |
| `InputFloat` / `InputFloat2` / `InputFloat3` / `InputFloat4` | Float number input with +/- buttons |
| `InputInt` / `InputInt2` / `InputInt3` / `InputInt4` | Integer number input with +/- buttons |
| `InputDouble` | Double-precision float input |
| `InputScalar` / `InputScalarN` | Generic typed scalar input |

### 1.8 Color Editors & Pickers

| Function | Description |
|----------|-------------|
| `ColorEdit3` | RGB color editor (click to open picker) |
| `ColorEdit4` | RGBA color editor with alpha |
| `ColorPicker3` | Inline RGB color picker widget |
| `ColorPicker4` | Inline RGBA color picker with alpha bar |
| `ColorButton` | Clickable color swatch |
| `SetColorEditOptions` | Set default color edit flags globally |

### 1.9 Trees & Collapsing Headers

| Function | Description |
|----------|-------------|
| `TreeNode` | Collapsible tree node (auto-ID from label) |
| `TreeNodeEx` | Tree node with explicit flags (leaf, selected, etc.) |
| `TreePush` / `TreePop` | Manually indent/unindent tree level |
| `CollapsingHeader` | Collapsible section header (no tree indent) |
| `SetNextItemOpen` | Force next tree node open/closed |
| `GetTreeNodeToLabelSpacing` | Get horizontal offset to align with tree labels |

### 1.10 Selectables & List Boxes

| Function | Description |
|----------|-------------|
| `Selectable` | Clickable item that spans available width (highlight on select) |
| `BeginListBox` / `EndListBox` | Framed scrollable list container |
| `ListBox` | Simple one-liner list box from string array |
| `BeginMultiSelect` / `EndMultiSelect` | Multi-selection context (Shift+Click, Ctrl+Click) |
| `SetNextItemSelectionUserData` | Associate arbitrary data with selectable item |
| `IsItemToggledSelection` | Query if item selection was toggled |

### 1.11 Tables

| Function | Description |
|----------|-------------|
| `BeginTable` / `EndTable` | Create a table with columns, sorting, resizing |
| `TableNextRow` | Advance to the next row |
| `TableNextColumn` | Advance to the next column |
| `TableSetColumnIndex` | Jump to a specific column by index |
| `TableSetupColumn` | Define column name, flags, width |
| `TableSetupScrollFreeze` | Freeze rows/columns for sticky headers |
| `TableHeadersRow` | Output a row of column headers |
| `TableGetSortSpecs` | Get current sort specification (for sortable tables) |
| `TableGetColumnCount` | Get number of columns |
| `TableGetColumnIndex` | Get current column index |
| `TableGetRowIndex` | Get current row index |
| `TableGetColumnName` | Get column name by index |
| `TableGetColumnFlags` | Get column flags (visible, sorted, etc.) |
| `TableSetColumnEnabled` | Show/hide a column |
| `TableSetBgColor` | Set background color for row/column/cell |

### 1.12 Tabs

| Function | Description |
|----------|-------------|
| `BeginTabBar` / `EndTabBar` | Container for tab items |
| `BeginTabItem` / `EndTabItem` | Individual tab within a tab bar |
| `TabItemButton` | Tab that acts as a button (not selectable) |
| `SetTabItemClosed` | Notify tab bar of a closed tab |

### 1.13 Menus

| Function | Description |
|----------|-------------|
| `BeginMenuBar` / `EndMenuBar` | Menu bar inside a window (requires flag) |
| `BeginMainMenuBar` / `EndMainMenuBar` | Application-level top menu bar |
| `BeginMenu` / `EndMenu` | Submenu that opens on hover |
| `MenuItem` | Clickable menu entry (with optional shortcut text, checkmark) |

### 1.14 Tooltips

| Function | Description |
|----------|-------------|
| `BeginTooltip` / `EndTooltip` | Custom tooltip window (put any widgets inside) |
| `SetTooltip` | Simple text-only tooltip |
| `BeginItemTooltip` | Tooltip that auto-shows when previous item is hovered |
| `SetItemTooltip` | Simple text tooltip for the previous item |

### 1.15 Popups & Modals

| Function | Description |
|----------|-------------|
| `OpenPopup` | Open a popup by string ID |
| `OpenPopupOnItemClick` | Open popup on right-click of previous item |
| `BeginPopup` / `EndPopup` | Non-modal popup window |
| `BeginPopupModal` | Modal dialog (blocks interaction with rest of app) |
| `BeginPopupContextItem` | Right-click context menu for previous item |
| `BeginPopupContextWindow` | Right-click context menu for current window |
| `BeginPopupContextVoid` | Right-click context menu for empty space |
| `CloseCurrentPopup` | Close the innermost open popup |
| `IsPopupOpen` | Query whether a popup is open |

### 1.16 Images & Textures

| Function | Description |
|----------|-------------|
| `Image` | Display a texture/image at a given size |
| `ImageWithBg` | Image with configurable background color |
| `ImageButton` | Clickable image button |

### 1.17 Progress & Status

| Function | Description |
|----------|-------------|
| `ProgressBar` | Horizontal progress bar with optional overlay text |
| `Bullet` | Small bullet point marker |

### 1.18 Simple Data Plotting (built-in)

| Function | Description |
|----------|-------------|
| `PlotLines` | Simple line graph from array data |
| `PlotHistogram` | Simple bar histogram from array data |
| `Value` | Display a label:value pair (bool, int, float) |

### 1.19 Layout & Spacing

| Function | Description |
|----------|-------------|
| `Separator` | Horizontal or vertical divider line |
| `SameLine` | Place next widget on the same line |
| `NewLine` | Force a new line |
| `Spacing` | Add vertical whitespace |
| `Dummy` | Non-interactive rectangle placeholder |
| `Indent` / `Unindent` | Increase/decrease horizontal indentation |
| `BeginGroup` / `EndGroup` | Group widgets so they act as one item for layout |
| `AlignTextToFramePadding` | Vertically align text baseline to framed widgets |
| `PushItemWidth` / `PopItemWidth` | Set width for next widget(s) |
| `SetNextItemWidth` | Set width for the very next widget only |
| `CalcItemWidth` | Get the current widget width |
| `PushTextWrapPos` / `PopTextWrapPos` | Set text wrapping position |

### 1.20 Cursor & Positioning

| Function | Description |
|----------|-------------|
| `GetCursorScreenPos` | Get absolute screen position of cursor |
| `SetCursorScreenPos` | Set absolute screen position |
| `GetCursorPos` / `SetCursorPos` | Window-local cursor position |
| `GetCursorStartPos` | Initial cursor position in current window |
| `GetContentRegionAvail` | Available space from current cursor to edge |

### 1.21 Scrolling

| Function | Description |
|----------|-------------|
| `GetScrollX` / `GetScrollY` | Current scroll offset |
| `SetScrollX` / `SetScrollY` | Set scroll offset |
| `GetScrollMaxX` / `GetScrollMaxY` | Maximum scroll range |
| `SetScrollHereX` / `SetScrollHereY` | Scroll to make current cursor position visible |
| `SetScrollFromPosX` / `SetScrollFromPosY` | Scroll to a specific local position |

### 1.22 Clipping

| Function | Description |
|----------|-------------|
| `PushClipRect` / `PopClipRect` | Push/pop a clipping rectangle for hit-testing |

### 1.23 Drag & Drop

| Function | Description |
|----------|-------------|
| `BeginDragDropSource` / `EndDragDropSource` | Mark an item as draggable |
| `SetDragDropPayload` | Set the data payload for a drag operation |
| `BeginDragDropTarget` / `EndDragDropTarget` | Mark an area as a drop target |
| `AcceptDragDropPayload` | Accept a payload of a given type |
| `GetDragDropPayload` | Peek at the current payload from anywhere |

### 1.24 Disabling

| Function | Description |
|----------|-------------|
| `BeginDisabled` / `EndDisabled` | Gray out and disable all widgets in the block |

### 1.25 Focus & Navigation

| Function | Description |
|----------|-------------|
| `SetKeyboardFocusHere` | Focus keyboard on the next widget |
| `PushTabStop` / `PopTabStop` | Control whether widgets receive tab focus |

### 1.26 Item State Queries

| Function | Description |
|----------|-------------|
| `IsItemHovered` | Was the last item hovered? |
| `IsItemActive` | Is the last item being interacted with? |
| `IsItemFocused` | Is the last item focused? |
| `IsItemClicked` | Was the last item clicked? |
| `IsItemVisible` | Is the last item visible (not clipped)? |
| `IsItemEdited` | Did the last item's value change this frame? |
| `IsItemActivated` | Was the last item just activated? |
| `IsItemDeactivated` | Was the last item just deactivated? |
| `IsItemDeactivatedAfterEdit` | Deactivated after a value change? (useful for undo/redo) |
| `IsItemToggledOpen` | Was a tree node toggled open/closed? |
| `IsAnyItemHovered` / `IsAnyItemActive` / `IsAnyItemFocused` | Global item state |
| `GetItemID` | Get ID of last item |
| `GetItemRectMin` / `GetItemRectMax` / `GetItemRectSize` | Bounding rectangle of last item |

### 1.27 Viewports

| Function | Description |
|----------|-------------|
| `GetMainViewport` | Get the primary/default viewport |

### 1.28 Style & Fonts

| Function | Description |
|----------|-------------|
| `PushFont` / `PopFont` | Change active font |
| `PushStyleColor` / `PopStyleColor` | Override a color in the style |
| `PushStyleVar` / `PopStyleVar` | Override a numeric style variable |
| `PushItemFlag` / `PopItemFlag` | Set item flags (disabled, no nav, etc.) |
| `GetStyle` | Access the global ImGuiStyle struct |
| `StyleColorsDark` | Apply dark theme |
| `StyleColorsLight` | Apply light theme |
| `StyleColorsClassic` | Apply classic (old) theme |

### 1.29 ID Stack

| Function | Description |
|----------|-------------|
| `PushID` / `PopID` | Push/pop a string, int, or pointer onto the ID stack |
| `GetID` | Calculate a unique ID from a string/pointer |

### 1.30 Logging / Capture

| Function | Description |
|----------|-------------|
| `LogToTTY` | Start logging widget text to stdout |
| `LogToFile` | Start logging to a file |
| `LogToClipboard` | Start logging to OS clipboard |
| `LogFinish` | Stop logging |
| `LogText` | Write arbitrary text to the log |
| `LogButtons` | Display log destination buttons |

### 1.31 Demo & Debug

| Function | Description |
|----------|-------------|
| `ShowDemoWindow` | The comprehensive ImGui demo showcasing all widgets |
| `ShowMetricsWindow` | Internal metrics and state inspector |
| `ShowDebugLogWindow` | Debug event log |
| `ShowIDStackToolWindow` | ID stack debugging tool |
| `ShowAboutWindow` | Version and credits |
| `ShowStyleEditor` | Interactive style/theme editor |
| `ShowStyleSelector` | Dropdown to switch between built-in themes |
| `ShowFontSelector` | Dropdown to switch fonts |
| `ShowUserGuide` | Display usage instructions |

---

## Part 2: ImDrawList Low-Level Drawing Primitives

These are available via `GetWindowDrawList()`, `GetForegroundDrawList()`, or `GetBackgroundDrawList()`. They render directly and are not widgets -- they are GPU-accelerated 2D drawing commands.

### 2.1 Shapes (Stroked)

| Function | Description |
|----------|-------------|
| `AddLine` | Line segment between two points |
| `AddRect` | Rectangle outline with optional rounding |
| `AddTriangle` | Triangle outline |
| `AddCircle` | Circle outline |
| `AddNgon` | Regular N-sided polygon outline |
| `AddEllipse` | Ellipse outline with optional rotation |
| `AddPolyline` | Connected line segments (open or closed) |
| `AddBezierCubic` | Cubic Bezier curve (4 control points) |
| `AddBezierQuadratic` | Quadratic Bezier curve (3 control points) |

### 2.2 Shapes (Filled)

| Function | Description |
|----------|-------------|
| `AddRectFilled` | Filled rectangle with optional rounding |
| `AddRectFilledMultiColor` | Gradient-filled rectangle (4 corner colors) |
| `AddTriangleFilled` | Filled triangle |
| `AddCircleFilled` | Filled circle |
| `AddNgonFilled` | Filled regular N-sided polygon |
| `AddEllipseFilled` | Filled ellipse with optional rotation |
| `AddConvexPolyFilled` | Filled convex polygon from point array |

### 2.3 Text & Images

| Function | Description |
|----------|-------------|
| `AddText` | Render text at a position (with optional font/size) |
| `AddImage` | Render a texture in an axis-aligned rectangle |
| `AddImageQuad` | Render a texture on an arbitrary quad |
| `AddImageRounded` | Render a texture with rounded corners |

### 2.4 Path API (build-then-stroke/fill)

| Function | Description |
|----------|-------------|
| `PathLineTo` | Add a point to the current path |
| `PathArcTo` | Add an arc segment to the path |
| `PathArcToFast` | Add arc using precomputed 12-step angles |
| `PathBezierCubicCurveTo` | Add cubic Bezier segment to path |
| `PathBezierQuadraticCurveTo` | Add quadratic Bezier segment to path |
| `PathRect` | Add a rectangle to the path |
| `PathStroke` | Stroke the current path and clear it |
| `PathFillConvex` | Fill the current path (must be convex) and clear it |
| `PathClear` | Discard the current path |

### 2.5 Low-Level Primitives

| Function | Description |
|----------|-------------|
| `PrimReserve` | Reserve vertex/index buffer space |
| `PrimRect` | Axis-aligned rectangle (2 triangles) |
| `PrimRectUV` | Textured rectangle |
| `PrimQuadUV` | Textured arbitrary quad |
| `PrimWriteVtx` / `PrimWriteIdx` | Write individual vertices and indices |
| `AddDrawCmd` | Force a new draw command (for render state changes) |
| `AddCallback` | Insert a user callback into the draw stream |
| `PushClipRect` / `PopClipRect` | GPU-level scissor clipping |
| `PushClipRectFullScreen` | Clip to entire screen |

---

## Part 3: ImPlot (2D Plotting Extension)

### 3.1 Plot Types

| Function | Description |
|----------|-------------|
| `PlotLine` | Line plot connecting data points |
| `PlotScatter` | Scatter plot (individual markers) |
| `PlotBubbles` | Bubble chart (scatter with variable size) |
| `PlotStairs` | Staircase/step plot |
| `PlotShaded` | Shaded/filled area between line and reference |
| `PlotBars` | Vertical or horizontal bar chart |
| `PlotBarGroups` | Grouped/stacked bar chart |
| `PlotErrorBars` | Error bars (symmetric or asymmetric) |
| `PlotStems` | Stem/lollipop plot |
| `PlotInfLines` | Infinite vertical or horizontal lines |
| `PlotPieChart` | Pie chart with labels and percentages |
| `PlotHeatmap` | 2D heatmap with color mapping |
| `PlotHistogram` | 1D histogram with configurable binning |
| `PlotHistogram2D` | 2D histogram (density plot) |
| `PlotDigital` | Digital/binary signal plot |
| `PlotImage` | Display an image/texture within plot coordinates |
| `PlotText` | Render text at plot coordinates |
| `PlotDummy` | Invisible item (reserves legend entry) |

### 3.2 Plot Containers

| Function | Description |
|----------|-------------|
| `BeginPlot` / `EndPlot` | Create a single plot area |
| `BeginSubplots` / `EndSubplots` | Grid of linked subplots |
| `BeginAlignedPlots` / `EndAlignedPlots` | Align axes across multiple plots |

### 3.3 Axis Setup

| Function | Description |
|----------|-------------|
| `SetupAxis` | Configure a single axis (label, flags) |
| `SetupAxisLimits` | Set axis range |
| `SetupAxisLinks` | Link axis range to external variables |
| `SetupAxisFormat` | Custom axis tick label format |
| `SetupAxisTicks` | Custom tick positions and labels |
| `SetupAxisScale` | Set axis scale (linear, log, symmetric log, custom) |
| `SetupAxisLimitsConstraints` | Constrain how far user can pan |
| `SetupAxisZoomConstraints` | Constrain how far user can zoom |
| `SetupAxes` | Configure X and Y axes in one call |
| `SetupAxesLimits` | Set both axes' ranges in one call |
| `SetupLegend` | Configure legend position and behavior |
| `SetupMouseText` | Configure mouse position readout |
| `SetupFinish` | Finalize setup (called automatically if omitted) |

### 3.4 Interactive Tools

| Function | Description |
|----------|-------------|
| `DragPoint` | Draggable point within plot |
| `DragLineX` | Draggable vertical line |
| `DragLineY` | Draggable horizontal line |
| `DragRect` | Draggable rectangle region |
| `Annotation` | Text annotation at plot coordinates |
| `TagX` | Axis tag on X axis |
| `TagY` | Axis tag on Y axis |

### 3.5 Plot Queries & State

| Function | Description |
|----------|-------------|
| `IsPlotHovered` | Is the current plot hovered? |
| `IsPlotSelected` | Is a region currently selected? |
| `IsAxisHovered` | Is a specific axis hovered? |
| `IsSubplotsHovered` | Is the subplot grid hovered? |
| `IsLegendEntryHovered` | Is a specific legend entry hovered? |
| `GetPlotMousePos` | Mouse position in plot coordinates |
| `GetPlotLimits` | Current visible range |
| `GetPlotPos` / `GetPlotSize` | Plot area in screen pixels |
| `PixelsToPlot` / `PlotToPixels` | Coordinate conversion |
| `CancelPlotSelection` | Programmatically cancel a box selection |
| `HideNextItem` | Hide the next plot item |
| `GetLastItemColor` | Get the color assigned to the last plotted item |
| `GetPlotDrawList` | Access ImDrawList for custom drawing in plot space |
| `PushPlotClipRect` / `PopPlotClipRect` | Clip to the plot area |

### 3.6 Colormaps

| Function | Description |
|----------|-------------|
| `AddColormap` | Register a custom colormap |
| `PushColormap` / `PopColormap` | Set active colormap |
| `GetColormapSize` | Number of colors in active colormap |
| `GetColormapColor` | Get color at index |
| `SampleColormap` | Interpolate colormap at position t in [0,1] |
| `ColormapScale` | Render a vertical colormap scale bar |
| `ColormapSlider` | Slider that samples from active colormap |
| `ColormapButton` | Button showing the active colormap |
| `ColormapIcon` | Small icon showing a colormap |
| `BustColorCache` | Clear cached auto-assigned colors |

### 3.7 Plot Styling

| Function | Description |
|----------|-------------|
| `GetStyle` | Access ImPlotStyle for customization |
| `PushStyleColor` / `PopStyleColor` | Override plot colors |
| `PushStyleVar` / `PopStyleVar` | Override plot style variables |
| `ShowStyleSelector` | Dropdown for built-in plot styles |
| `ShowColormapSelector` | Dropdown for built-in colormaps |
| `ShowStyleEditor` | Full interactive plot style editor |

### 3.8 Plot Drag & Drop

| Function | Description |
|----------|-------------|
| `BeginDragDropTargetPlot` | Accept drops on the plot area |
| `BeginDragDropTargetAxis` | Accept drops on a specific axis |
| `BeginDragDropTargetLegend` | Accept drops on the legend |
| `BeginDragDropSourcePlot` | Drag from the plot area |
| `BeginDragDropSourceAxis` | Drag from an axis |
| `BeginDragDropSourceItem` | Drag from a specific plot item |

16 built-in colormaps: Deep, Dark, Pastel, Paired, Viridis, Plasma, Hot, Cool, Pink, Jet, Twilight, RdBu, BrBG, PiYG, Spectral, Greys.

---

## Part 4: imgui-bundle Extensions

### 4.1 Bundled Libraries

| Library | Directory | Description |
|---------|-----------|-------------|
| **Dear ImGui** | `imgui` | Core immediate-mode GUI (all widgets above) |
| **Hello ImGui** | `hello_imgui` | App runner: window creation, backends, docking, asset management |
| **ImmApp** | `immapp` | Simplified app runner with easy add-on activation |
| **ImPlot** | `implot` | 2D plotting (all plot types above) |
| **ImPlot3D** | `implot3d` | 3D plotting extension (experimental) |
| **ImmVision** | `immvision` | Image inspection/viewing (zoom, pixel values, overlays) |
| **imgui-node-editor** | `imgui-node-editor` | Visual node graph editor with links and flow |
| **ImGuizmo** | `ImGuizmo` | 3D gizmos: translate/rotate/scale manipulators, view cube |
| **ImFileDialog** | `ImFileDialog` | Native-style file open/save dialogs |
| **portable-file-dialogs** | `portable_file_dialogs` | OS-native file dialogs (no custom rendering) |
| **imgui-knobs** | `imgui-knobs` | Rotary knob widgets (multiple visual styles) |
| **imspinner** | `imspinner` | Animated spinner/loading indicators (many styles) |
| **imgui_toggle** | `imgui_toggle` | iOS-style toggle switches |
| **imgui-command-palette** | `imgui-command-palette` | VS Code-style command palette (Ctrl+Shift+P) |
| **imgui_md** | `imgui_md` | Markdown renderer (headings, bold, italic, code, links, images) |
| **ImGuiColorTextEdit** | `ImGuiColorTextEdit` | Syntax-highlighted code editor widget |
| **imgui_tex_inspect** | `imgui_tex_inspect` | Texture/image inspection tool |
| **ImCoolBar** | `ImCoolBar` | macOS Dock-style icon bar with magnification |
| **ImAnim** | `ImAnim` | Animation utilities for ImGui |
| **nanovg** | `nanovg` | Vector graphics rendering (NanoVG integration) |
| **imgui_test_engine** | `imgui_test_engine` | Automated GUI testing framework |

### 4.2 ImPlot3D Plot Types

| Plot Type | Description |
|-----------|-------------|
| `PlotLine` | 3D line plot |
| `PlotScatter` | 3D scatter plot |
| `PlotSurface` | 3D surface plot |
| `PlotMesh` | 3D mesh rendering |
| `PlotTriangle` | Individual 3D triangles |
| `PlotQuad` | Individual 3D quads |
| `PlotText` | 3D text labels |

### 4.3 ImGuizmo Components

| Component | Description |
|-----------|-------------|
| `Manipulate` | 3D translate/rotate/scale gizmo for 4x4 matrices |
| `ViewManipulate` | View orientation cube (click to snap to axis views) |
| `DrawCubes` | Debug cube rendering |
| `DrawGrid` | 3D grid rendering |
| `DecomposeMatrixToComponents` | Extract position/rotation/scale from matrix |
| `RecomposeMatrixFromComponents` | Build matrix from position/rotation/scale |
| **ImSequencer** | Timeline/sequencer editor for frame-based events |
| **ImCurveEdit** | Curve/keyframe editor |
| **ImGradient** | Gradient editor widget |
| **ImZoomSlider** | Zoom slider for timeline/sequencer |

### 4.4 imgui-node-editor

| Feature | Description |
|---------|-------------|
| `BeginNode` / `EndNode` | Define a visual node |
| `BeginPin` / `EndPin` | Define an input/output pin on a node |
| `Link` | Create a visual link between pins |
| `BeginCreate` / `EndCreate` | Detect when user creates a new link |
| `BeginDelete` / `EndDelete` | Detect when user deletes a link/node |
| `QueryNewLink` | Query the link being created |
| `AcceptNewItem` / `RejectNewItem` | Accept or reject a new link |
| `Suspend` / `Resume` | Temporarily exit node editor for popups |
| `NavigateToContent` | Zoom to fit all content |
| `NavigateToSelection` | Zoom to fit selected nodes |
| Flow animations | Visual flow indication along links |
| Grouping | Group nodes together |

### 4.5 imgui-knobs

| Style | Description |
|-------|-------------|
| `Knob` | Rotary knob widget with configurable style |
| Styles: Tick, Dot, Wiper, WiperOnly, WiperDot, Stepped, Space | Different visual appearances |

### 4.6 imspinner

Over 30 spinner styles including: circle, arc, ball, dots, pulse, bounce, fading, bars, clock, solar, and more. Used as loading/activity indicators.

### 4.7 imgui_toggle

| Widget | Description |
|--------|-------------|
| `Toggle` | iOS/Android-style toggle switch |
| Configurable: colors, animation speed, size, labels | Full customization |

### 4.8 ImCoolBar

| Widget | Description |
|--------|-------------|
| `BeginCoolBar` / `EndCoolBar` | macOS Dock-style bar container |
| `CoolBarItem` | Individual item that magnifies on hover |

### 4.9 imgui_md (Markdown)

Renders Markdown directly in ImGui: headings (h1-h6), bold, italic, strikethrough, inline code, code blocks, links (clickable), images (inline), bullet lists, numbered lists, horizontal rules, and tables.

### 4.10 ImGuiColorTextEdit

| Feature | Description |
|---------|-------------|
| Syntax highlighting | C, C++, Lua, GLSL, Python, and custom languages |
| Line numbers | Gutter with line numbers |
| Breakpoint markers | Clickable breakpoint indicators |
| Error markers | Inline error display |
| Find/replace | Text search within editor |
| Undo/redo | Full undo history |
| Selection | Multi-cursor and selection support |

### 4.11 imgui-command-palette

| Feature | Description |
|---------|-------------|
| `CommandPaletteWindow` | VS Code-style fuzzy search command palette |
| Register commands with callbacks | Dynamic command registration |
| Fuzzy matching | Type to filter commands |
| Keyboard navigation | Full keyboard support |

---

## Part 5: ImGui Demo Window Sections

The `ShowDemoWindow()` function demonstrates all core widgets organized as:

1. **Help** -- About, user guide
2. **Configuration** -- Style, backend flags, IO
3. **Window options** -- Flags for no titlebar, no scrollbar, no menu, etc.
4. **Widgets**
   - Basic (buttons, checkboxes, radio, combo, sliders, drags, inputs, color edits, tooltips)
   - Multi-component (float2/3/4, int2/3/4)
   - Trees
   - Collapsing headers
   - Bullets
   - Text (wrapped, colored, disabled, UTF-8)
   - Images
   - Selectables (single, multiple, grid)
   - Text filters
   - Combos (all variants)
   - List boxes
   - Plotting (lines, histogram)
   - Progress bars
   - Color widgets (all modes: RGB, HSV, hex, wheel, bar)
   - Drag and drop
   - Querying item status
   - Disabling
5. **Layout**
   - Child windows
   - Groups
   - Text wrapping
   - Horizontal scrolling
   - Clipping
6. **Popups & Modal Windows**
   - Popups, context menus, modals
7. **Tables**
   - Basic, resizable, reorderable, sortable
   - Horizontal scrolling, row selection, custom headers
   - Padding, sizing policies, background colors
   - Tree view in tables, advanced layouts
8. **Inputs & Focus**
   - Tabbing, focus, keyboard/gamepad navigation
9. **Multi-select**
10. **Columns** (legacy API, prefer Tables)
11. **Filtering**
12. **Tab bars** (reorderable, auto-fit, manual)

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Core ImGui widget functions | ~150+ |
| ImDrawList drawing primitives | ~30 |
| ImPlot plot types | 18 |
| ImPlot API functions | ~80+ |
| imgui-bundle extension libraries | 21 |
| Total distinct widget/primitive types | ~250+ |
