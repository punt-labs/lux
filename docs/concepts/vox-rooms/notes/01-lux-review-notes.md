# Lux review notes: design docs and Dear ImGui

Date: 2026-11-12
Repo state: `punt-labs/lux`, branch `claude/modest-pasteur-5n01gi`, at `63b7ce5` (same as `main`, #543)

Each item is marked with how well it is supported:

- **Verified:** read in the code or docs, or run.
- **Inferred:** follows from documented behaviour, but not reproduced.
- **Open:** a question that has not been checked.

---

## 1. Concerns

### 1.1 Labels containing `#` are cut short in element renderers (Inferred, likely bug)

Element renderers build ImGui IDs by joining the agent's label and the element id with `##`, without escaping the label:

| Site | Code |
|---|---|
| `display/renderers/checkbox_renderer.py:41` | `imgui.checkbox(f"{elem.label}##{elem.id}", ...)` |
| `display/renderers/selectable_renderer.py:41` | `imgui.selectable(f"{elem.label}##{elem.id}", ...)` |
| `display/renderers/input_text_renderer.py:59` | `label = f"{elem.label}##{elem.id}"` |
| `display/render_loop.py:666` | tab label `f"{label}##{scene_id}"` |
| `display/render_loop.py:689` | collapsing header `f"{label}##{scene_id}"` |

ImGui hides everything from the first `##` onward. If the label contains `###`, the ID is computed only from that point. Nothing in `protocol/` escapes `#` (a grep for `##`, `200B` and `zwsp` found nothing).

- **Effect:** a checkbox labelled `"Fix ##42"` would display `"Fix "`. IDs stay unique because the element id is still appended. The damage is lost visible text, not a click on the wrong widget.
- **Already solved for menus:** `display/menus/hidden_id.py` (`MenuHiddenId`) puts a zero-width space after every `#`. Its docstring cites the `lux-whb9` lesson: guard the whole constructed ID in one place. The element renderers do not use it.
- **Possible fix:** move `MenuHiddenId` out of `menus/` into a shared display-level type, and route every renderer that builds a label ID through it.
- **To confirm:** run `show()` with a checkbox labelled `"a ##b"`, then compare `screenshot` with `inspect_scene`.

### 1.2 Fallback ImGui IDs built from `id(elem)` (Verified: unreachable over the wire) → PL-565

- `display/renderers/imgui/plot.py:140`: `imgui.push_id(elem.id or f"anon-{id(elem)}")`
- `display/renderers/imgui/tree.py:41`: same pattern.

`id(elem)` is the Python object's address. The Display replaces its replica on every Hub resend, so the address changes every time. If this fallback is ever taken:

- ImGui state stored under the ID would reset on each resend. That includes plot zoom and pan, and tree open/closed state.
- A freed address can be reused by a different element, which risks an ID collision.

**Correction.** The wire path can't reach this fallback, so it is not a state-loss bug. `plot_codec.py:63` and `tree_codec.py:55` decode the id with `ctx.require_id(raw)`. `require_id` (`protocol/elements/element_wire.py:69`) rejects an empty id for every kind except `separator`. The fallback can run only for an element constructed directly in Python. Fix: delete it, or raise on an empty id.

### 1.9 The texture cache is described as unbounded, but it has an LRU cap (Verified) → PL-563 item 2

`CLAUDE.md:161` and `prfaq.tex` (lines 581–584 and 779) describe the texture cache as unbounded with no eviction policy. `texture_cache.py` already caps it with `TextureLru` (DES-071).

### 1.10 Checks that came back clean (Verified)

- **The 1.92 `SetCursorPos()` change:** the only cursor move in `display/` is `menus/corner_close_button.py:44`, and a `dummy()` follows it.
- **ImGui off the render thread:** the only thread in `display/` is the quit watchdog (`window_chrome.py:88`), which never calls ImGui.

### 1.3 Org standards are missing from this checkout (Verified)

`CLAUDE.md` `@`-imports `../punt-kit/standards/{architecture,oo,python}.md`. It also relies on the `punt-labs/` workspace meta-repo for `.claude/rules/python-*.md` (19 OO rules) and `.envrc`. Neither sibling exists in this container (`ls ..` shows only `lux`). Work done here sees only `docs/standards/python-oo.md`, not the org-level rules.

### 1.4 `element-contract.md` contradicts the rest of the docs (Verified)

`docs/architecture/target/element-contract.md`, §"Migration status", says 4 of 25 kinds (`text`, `button`, `checkbox`, `dialog`) are migrated and the rest are frozen wire dataclasses.

`CLAUDE.md` and `docs/README.md` say all 25 kinds migrated and the legacy path was deleted in B7 (epic `lux-xs7r`, closed 2026-07-27). The doc's header still reads "draft normative target… Review expected."

The section is stale. The "Gate" paragraph about migrating before adding new kinds is now satisfied and could say so.

### 1.5 `DESIGN.md` ADR order (Verified, low severity)

There are 89 `## DES-` headings, and they are not in numeric order:

- DES-088 sits between DES-067 and DES-071.
- DES-069, DES-070 and DES-071 appear as 071, 069, 070.
- DES-068 and DES-085 to DES-087 were backfilled at the end (#534).

`CLAUDE.md` says ADRs are appended in order. Grepping for `^## DES-` still works, but reading the file in sequence misleads.

### 1.6 Display code-size debt (Verified from docs)

`display/render_loop.py` (`RenderLoop`) is about 1,100 lines, against a 300-line target. `CLAUDE.md` calls it the main obstacle to automated render tests. Concern 1.1 lives partly in this file.

### 1.7 Two renderer directories (Verified, observation)

Per-kind adapters live in `display/renderers/imgui/`. Several of them (`selectable.py`, `input_text.py`) import and delegate to older classes in `display/renderers/*_renderer.py`. `CLAUDE.md` describes only `renderers/imgui/`. It is not clear whether the two-layer split is intended or left over from the migration. It also means a fix like 1.1 must land in the outer `*_renderer.py` files.

### 1.8 The ImGui reference doc lacks the conceptual rules (Verified)

`docs/imgui/primitive-catalog.md` (research date 2026-03-06) catalogues about 250 functions. It does not cover:

- the ID-stack rules, the cause of 1.1 and of `lux-whb9`
- the 1.92 font and texture changes
- the single-thread rule for an ImGui context
- the input-capture rules

Section 3 below could be added to it.

---

## 2. Architecture summary (from the target docs)

Sources: `docs/architecture/target/{target,topology,ui-model,element-contract,introspection-api}.md` and the opening sections of DES-089, DES-093, DES-101 and DES-102.

- **One authority.** Clients (MCP, REST, CLI, library) talk only to the Hub (`luxd`). Each element in a submitted tree validates itself, and every error is collected (DES-039). An invalid tree is rejected and never installed or rendered. A valid tree is installed into `HubDisplay`.
- **The Display is a replica.** It receives the whole UI and renders it locally. Its handlers are wrappers that send a `RemoteEventHandlerInvocation` to the Hub, where the real handler runs (D21). After a change the Hub resends the whole tree; there is no diff protocol.
- **Boundary rule.** UI state crosses IPC. Render calls (ImGui, pixels) never do.
- **Two event systems.** UI observer cascades stay inside the element tree. Hub-managed app pub-sub carries business events. Pub-sub is not used to replicate state.
- **View logic vs business logic.** A widget's own behaviour can be wired automatically. Business meaning must be wired by the agent. An interactive element with no business wiring should surface as a validation error (DES-040).
- **Visibility belongs to the Display (DES-088).** The client, through the Hub, owns whether a frame's content exists. The user owns where the frame is and whether it is open. A close never reaches the Hub.
- **Addressing and transport (DES-089, DES-090).** Identity is a path. One Display can show several Hubs, including Hubs on other hosts over mTLS.
- **The Hub never controls the Display process (DES-093).** It only connects to it, holds the connection and retries, with backoff from 2s up to 120s.
- **Recent concurrency work.**
  - DES-101: each client lifecycle step is one operation under the store lock.
  - DES-102: each Display dial is a generation, so a reply reaches only the dial that asked for it.
  - Both were model-checked with ProB before the code changed.
- **Formal methods.** About 20 Z specs. Each has deliberately buggy "fidelity control" variants that must reproduce the defect the fix closes.

---

## 3. Dear ImGui notes relevant to lux

Lux pins `imgui-bundle==1.92.900`. Its display runs through `immapp.run(runner_params, addons)` (`display/render_loop.py:303`), with hello_imgui handling the window, themes and screenshots.

### Immediate mode

- The whole UI is re-submitted every frame, and the application owns the data.
- ImGui keeps very little state of its own: open trees, focus, scroll position, in-progress text edits. All of it is stored under the widget's ID.
- **Consequence for lux:** nothing on the per-frame render path may log (enforced by `tests/test_per_frame_tracing.py`).

### The ID stack

- An interactive widget's ID is a hash of its label plus the parent scope (window, tree node, `PushID`). Plain `Text()` needs no ID.
- `label##hidden` shows only `label`, but `##hidden` contributes to the ID.
- `label###key`: the ID is computed only from `###key` onward, so the visible label can change while state is kept. Lux uses this for `"World###world_panel"`.
- Two widgets with the same ID in the same scope collide: interacting with one acts on the first.
- An empty label can collide with the window's own ID.
- Inside loops, use `PushID`/`PopID`. Tree nodes push an ID implicitly.
- For debugging, `ShowIDStackToolWindow()` shows the ID stack.
- **For lux:** an ID must come from a stable key (element id, scene id, frame id), never from a list position or object address. This is the same rule as DES-045 (stable sub-element IDs), applied to ImGui.

### Input

- Forward every input event to ImGui. The app should act on input only when `io.WantCaptureMouse` or `io.WantCaptureKeyboard` is false.
- Do not hit-test windows by hand.

### Threading

- One ImGui context must not be used from two threads at once.
- To render on another thread, stage the `ImDrawData` and texture requests first.

### What changed in 1.92

- **Fonts.** Glyphs are rasterized on demand at any size, so glyph ranges are obsolete.
  - `PushFont(font, size)` now requires a size: `0.0f` keeps the current size, and `PushFont(NULL)` was removed.
  - `io.FontGlobalScale` was replaced by `style.FontScaleMain`, alongside `FontSizeBase`, `FontScaleBase` and `FontScaleDpi`.
  - `SetWindowFontScale()` is obsolete.
  - `ImFont::FontSize` was removed; `ImFont::LegacySize` replaces it.
- **Textures.** `ImTextureRef` replaces `ImTextureID` in `Image`, `ImageWithBg`, `ImageButton` and `AddImage*`. Renderers now handle texture create, update and destroy themselves (`RendererHasTextures`). Lux already uses `ImTextureRef` (`display/renderers/image_renderer.py:37`).
- **Layout.** `SetCursorPos()` with no item after it no longer extends the parent; add a `Dummy()`. This may matter for `draw` and custom-layout renderers (Open).
- **New.** Tree connector lines (`ImGuiTreeNodeFlags_DrawLinesNone/Full/ToNodes`) and `ImGuiCol_InputTextCursor`.
- **Renames.** `PushTextureID`/`PopTextureID` became `PushTexture`/`PopTexture`. `ListClipper::ForceDisplayRangeByIndices` became `IncludeItemsByIndex`. `PushAllowKeyboardFocus` was removed; use `PushItemFlag(ImGuiItemFlags_NoTabStop, …)`.

### Sizing and DPI

- Express sizes relative to `GetFontSize()` or `GetFrameHeight()`, not in fixed pixels.
- Call `style.ScaleAllSizes(factor)` once; to change the factor, reset the style first.

---

## 4. Suggested next steps

Listed for consideration; none of these has been started.

1. Reproduce 1.1 through `show()` plus `screenshot`. If confirmed, file a bead and route every renderer that builds a label ID through one shared guarded-ID type.
2. Check whether the `id(elem)` fallback in 1.2 is reachable. Then delete it or replace it with a stable key.
3. Update `element-contract.md` §"Migration status" to match the completed migration.
4. Add the ID-stack and 1.92 notes from section 3 to `docs/imgui/primitive-catalog.md`.
5. Check whether `draw` or custom-layout renderers depend on the old `SetCursorPos()` boundary-extension behaviour.

---

## 5. Graphics engines Lux could integrate

Status: the libraries in 5.2 come from the imgui-bundle documentation and `DESIGN.md:137` ("21 extension libraries"). I have not installed `imgui-bundle==1.92.900` here to confirm each Python binding. Everything else in this section is analysis, not something I have verified.

### 5.1 What any addition has to fit

These constraints come from the target docs:

1. **The agent describes it as data.** Agents send JSON element trees. Running code in the display process is out of scope, so a declarative chart spec fits and a matplotlib script does not.
2. **Rendering happens only in the Display.** The Hub may compute layout or produce a static image. Render calls never cross IPC.
3. **Each capability is a deliberate new element kind.** It validates itself (DES-039) and is composed through `show()`, so the MCP tool surface does not grow (DES-040).
4. **Interactions return to the Hub as typed events,** such as node moved or link created, as `value_changed`. They never run behaviour inside the Display.
5. **Nothing blocks the frame.** One ImGui context per thread.
6. **Native dependencies go in the `[display]` extra.** New kinds carry the `v2` label (per `CLAUDE.md`).

### 5.2 Tier 1: already in the imgui-bundle wheel (no new dependencies)

Lux uses ImPlot today (`display/renderers/imgui/plot.py`).

| Library | What it adds | Why it matters |
|---|---|---|
| **imgui-node-editor** | Interactive node-and-link graphs | Graphs are the main data shape Lux cannot show today: dependency graphs (bead `blocks` edges), pipelines, z-spec state machines, call graphs. **Top pick.** |
| **ImPlot3D** | 3D line, scatter, surface and mesh plots | Extends `plot` into 3D using the same `Begin`/`Setup` calls Lux already uses. |
| **ImGuiColorTextEdit** | Syntax-highlighted code view with line numbers, error markers and find | Code and diffs are what agents produce most. A `markdown` code block has no gutter, no markers and no language-aware highlighting. |
| **ImmVision** | Image inspector with zoom, pan and pixel values | Makes `image` useful for screenshot review and image diffs. |
| **NanoVG** | Anti-aliased vector paths, gradients and better curves | A higher-quality backend for `draw` than `ImDrawList`. |
| **imgui_test_engine** | Scripted GUI tests: click, type, assert | Not graphics, but it targets `CLAUDE.md`'s stated biggest gap: no automated render tests. |

### 5.3 Tier 2: layout engines in the Hub (no Display dependencies)

These compute positions and emit element kinds Lux already has. Because nothing new runs in the Display, they also work unchanged across hosts (DES-090).

- **Graphviz or ELK auto-layout.** Today an agent must hand-place every node in `draw` or a node graph. Combined with the node editor, an agent could send nodes and edges and get back a laid-out, interactive graph.
- **Mermaid parsing.** Agents write Mermaid fluently. The Hub could parse it into nodes and edges to produce flowcharts and sequence diagrams.

### 5.4 Tier 3: offscreen engines rendered into a texture in the Display

The engine draws into a buffer in the Display, and ImGui shows the result with `image()`. This tier adds the most capability, but every interaction has to be translated back. Texture-upload cost is also bounded by the DES-071 LRU cap.

| Engine | Capability | Caveat |
|---|---|---|
| **Vega-Lite via `vl-convert`** | A large declarative chart grammar. It is already JSON, and agents know it well. | Static output unless clicks are mapped back. It overlaps `plot`, so it needs a rule for which to use when. |
| **VTK or PyVista** | Scientific 3D: volumes, meshes, point clouds | Heavy native dependency. Sharing a GL context with GLFW on the render thread is the hard part. |
| **pygfx (wgpu)** | A modern GPU scene graph | Mixing wgpu with Lux's OpenGL backend is untested. |
| **Skia** | Print-quality vector graphics and text | Overlaps NanoVG with a much larger dependency. |
| **HarfBuzz shaping** | Arabic, Hebrew, Indic scripts and emoji ZWJ sequences | As far as I know, Dear ImGui does no complex text shaping, so this is a correctness gap rather than a feature. |
| **LaTeX math** (matplotlib mathtext or MicroTeX) | Typeset equations | Markdown cannot show math today. |
| **PyAV / FFmpeg** | Video and animated frames | Decoding must stay off the render thread. |

### 5.5 What to avoid

- **Embedded web view (CEF or WebView).** It runs JavaScript inside the Display, which is in-display code execution and out of scope. It also bypasses the Hub's trust boundary.
- **Game engines (Godot, Unity).** They bring their own scene model and loop, which conflicts with the Display being a replica of the Hub.
- **Matplotlib running in the Display.** It needs agent-supplied code. If an agent wants matplotlib, it can render Hub-side and send an `image` element, which already works today.

### 5.6 Recommended order

1. **imgui-node-editor plus Hub-side Graphviz/ELK layout:** the largest new capability, with no new Display dependencies.
2. **ImGuiColorTextEdit:** code and diffs are what agents produce most.
3. **ImPlot3D:** a small extension of an existing kind.
4. **imgui_test_engine:** starts paying down the render-testing gap.

---

## Sources

- [Dear ImGui FAQ](https://github.com/ocornut/imgui/blob/master/docs/FAQ.md)
- [Dear ImGui v1.92.0 release notes](https://github.com/ocornut/imgui/releases/tag/v1.92.0)
- Repo: `CLAUDE.md`, `docs/README.md`, `docs/WORKFLOW.md`, `docs/architecture/target/*.md`, `DESIGN.md`, `docs/imgui/primitive-catalog.md`, and the source files cited above.
