# Brainstorm: competing with herdr, mockups, ImGui fidelity, language choice

> **Status: brainstorming, nothing decided.** Written 2026-11-12. Follows
> [02-room-synthesis.md](02-room-synthesis.md) and
> [01-lux-review-notes.md](01-lux-review-notes.md). Later thinking
> (rooms, the explicit and implicit hierarchy, the fact log, tools) is in
> [../prfaq.tex](../prfaq.tex).

## 1. The reframe: Lux competes with herdr

Lux would not integrate with herdr. It would compete with it, offering its own
terminals, persistent sessions and rich graphics.

**What changes from the room synthesis:**

- The `lux-herdr` applet is dropped.
- tmux is no longer the terminal host. Its control mode survives at most as a
  way to attach to existing tmux sessions.
- Lux owns its own process host, a separate daemon, `luxd-pty`. A Hub restart
  or upgrade must not kill shells, and herdr's and tmux's servers are both
  separate from their clients for the same reason.
- DES-093 forbids the Hub from controlling the **Display** process. It does not
  forbid the Hub from running terminal processes. A separate daemon is still
  the stronger design.

**Parity with herdr (the entry fee):**

| herdr has | Lux needs |
| --- | --- |
| Panes, tabs, workspaces, prefix keys, mouse | Frames and scenes cover layout; keyboard-driven pane control is new |
| Detach and reattach; sessions outlive the client | Mostly there already: luxd holds content when the Display closes (DES-093); needs `luxd-pty` for terminals |
| Layout restored and agents resumed after a restart | Persist layout and resume agents (for example `claude --resume`); herdr doesn't keep processes alive across a restart either |
| Working, blocked and idle state, plus jump-to-blocked | Hook-declared state, with output matching as a fallback, which is better than herdr's guessing |
| CLI and socket API (spawn a pane, send a prompt, wait until blocked) | New operations on the existing MCP, REST and CLI layer |
| Remote machines (`herdr --remote`) | A cross-host Display over mTLS (DES-090), plus the Hub mesh |
| A plugin marketplace | Applets (DES-063); the PR/FAQ rules out an extension store |

**Where Lux wins:**

- Live graphics beside and inside terminals.
- Agents can read what's on screen through introspection.
- The blackboard and transcript.
- A mesh of the user's own machines.
- GPU-native rendering.

**Threats:**

- herdr runs in any terminal, including over plain SSH. Lux needs a GUI; a
  text-mode Display would fix that.
- Momentum: herdr has about 50k GitHub stars. One source reports a desktop app
  announced on 2026-10-29.
- Terminal fidelity and speed: a native VT parser such as libghostty-vt is
  probably required.

**Revised phases:**

1. Log replication primitive.
2. Native terminal element plus `luxd-pty`.
3. Agent state, jump-to-blocked, and the agent API (parity with herdr).
4. Graphics beside and inside terminals.
5. Blackboard and transcript.
6. Mesh.

## 2. Mockups

The mockup sources are in [../mockups/](../mockups/). See
[../README.md](../README.md) for what each screen shows.

**Theme facts found in the source (hello_imgui and Dear ImGui, cloned):**

- Lux runs hello_imgui's default theme, `DarculaDarker` (`imgui_theme.h:71`).
  Lux never sets another at startup.
- That theme sets 3px rounding and a 1px border on input fields, buttons and
  tabs, and uses blue tabs.
- ImGui's default spacing: window padding 8×8, widget padding 4×3, item
  spacing 8×4, table cell padding 4×2.

## 3. How close can ImGui get to mockup C?

About 90% of C's look, at a fixed window size, with a custom theme, a font set
and a few hand-drawn details. This is a judgement, not a measurement.

**What a custom theme covers:**

- C's palette (dark background, blue for working, orange for blocked).
- 10px card corners with 1px borders.
- Pill buttons and chips, by setting a corner radius larger than the widget.
- C's padding and spacing.
- Per-widget colour overrides, such as the blue filled button and the orange
  blocked card.
- Several fonts and weights at any size, using `PushFont(font, size)`, new in
  ImGui 1.92.
- State dots, outlined tags, top-rounded card headers and a dot grid, drawn
  with a few draw-list calls each.

**Real gaps:**

1. **No wrapping layout.** C's cards reflow as the window narrows; ImGui would
   need layout code for that. Lux's `group` element has rows, columns and
   grid, but no wrap.
2. **No mixed-style wrapped paragraphs.** A paragraph mixing bold, grey and
   plain text can't wrap. imgui_md or a small rich-text helper would solve it.
3. **Typographic finish.** There's no letter-spacing. As far as I know there's
   also no kerning and only grayscale anti-aliasing, so text looks slightly
   softer than in a browser.

**What Lux itself would need:**

- **A Lux theme.** Today Lux offers only hello_imgui's named themes.
- **A font set.** `display/fonts.py` loads one font at one size.
- **Semantic presentation fields,** such as a frame marked as a card or a
  badge with `state: blocked`, with the theme picking the colours rather than
  agents styling pixels. Only `text` and `spinner` accept any styling today.

## 4. Language: is Python the problem?

For the Hub and the Display, the concern is justified. For clients it matters
much less, because they talk to the Hub over a protocol and can be written in
any language.

**Where Python already hurts Lux, from the repo:**

- **Render speed:**
  - nothing on the per-frame render path may log;
  - DES-069 memoizes the table's hot path;
  - DES-070 makes a performance test a permanent guardrail;
  - `render_loop.py` is about 1,100 lines.
- **Races in the Hub:** most recent decision records (DES-085, DES-101,
  DES-102) and about 20 formal models fix Hub races. Rust prevents data races
  at compile time, not deadlocks or protocol-logic races, so the Z specs would
  still be needed.
- **Typing by tooling:** pyright, mypy and the OO ratchet enforce by policy
  what a compiler checks.
- **Packaging:** Python 3.13, uv and native extras inside a long-running GUI
  daemon.

**Size of a rewrite:**

- Source: about 80,000 lines of Python in 830 files (about 44,500 lines of
  code once docstrings, comments and blanks are removed): `domain/` 21k,
  `protocol/` 18k, `display/` 16k, `operations/` 5.6k.
- Tests: about 137,000 lines.
- Language-neutral assets that carry over: the JSON protocol, about 121 specs
  (`.tex` files), the decision log and the end-to-end scenarios.

**Inspiration:**

| Source | Lesson for Lux |
| --- | --- |
| X11 | Lux is X11 one level up: clients send a widget tree and the server draws it. That keeps it network-transparent and inspectable, which is Lux's edge. |
| Wayland | Take its corrective lessons: clients isolated from each other, the compositor alone owns focus and input, a small core protocol with versioned extensions. |
| Hyprland (Omarchy) | Keyboard-first tiling; one command socket plus one event socket; live-reloaded config; opinionated defaults. It's C++, so C++ is viable for a Display. |
| herdr | A Rust server holds sessions and any client reattaches, including over SSH. |
| WezTerm | The closest existing design: a separate mux server owns the panes, and the GPU interface attaches locally, over SSH or over TLS. Study it before designing. |
| Plan 9 rio and acme | Expose live state as files (9P or FUSE). |

**Shape:**

- **Hub in Rust:** tokio, axum, `rmcp` (the official Rust MCP SDK), rustls,
  and serde types generated from one protocol schema.
- **`luxd-pty` in Rust, first:** a new component, so nothing gets rewritten.
  Building blocks: `portable-pty` and `vte` or `alacritty_terminal`.
- **Display, decided by a spike between:**
  - C++ with Dear ImGui directly: keeps every engine, fastest, and links
    libghostty-vt;
  - Rust with egui: one language with the Hub and runs in a browser, but the
    ImGui ecosystem has to be rebuilt.
- **A text-mode client** (for example ratatui) to close the gap with herdr
  over SSH.
- **Clients in any language:** MCP and REST don't care. Keep the Python client
  library and add TypeScript, both generated from the protocol schema.

**How to migrate:**

1. Define the protocol in a schema, and turn the end-to-end harness into a
   conformance suite any Hub must pass.
2. Write `luxd-pty` in Rust.
3. Build a Rust Hub behind the same protocol and switch only when it passes
   the suite.
4. Run the Display spike, measuring frame time on a 1,000-row table, terminal
   throughput, and how well each matches ImPlot3D and the node editor.

**Main risk:** a rewrite of this size stalls feature work. Steps 1 and 2 pay
off either way.

## 5. More speculative ideas

- **Run the Hub inside the compositor:** a Hyprland plugin or a small Wayland
  compositor. Agents could inspect and arrange real application windows as
  well as Lux scenes.
- **Write the Display in Zig on libghostty:** a best-in-class terminal on day
  one, with Lux elements as overlays.
- **Make the protocol the product:** anyone can write a Display (GPU,
  text-only, browser, phone). Lux ships the reference Hub and two Displays.
- **Run Displays as WebAssembly in the Hub:** a headless Display, so an agent
  can render a scene and check its pixels with no window open.
- **The blackboard as a CRDT document:** drop the home-Hub rule and merge
  local edits, with Automerge as the model. This trades authority for offline
  work.
- **Agents as tiling-window-manager rules:** for example, "when an agent is
  blocked, float its pane to the centre and dim the rest", written as
  Hyprland-style config.

## Sources

- [herdr on GitHub](https://github.com/herdrdev/herdr)
- [tmux wiki: Control Mode](https://github.com/tmux/tmux/wiki/Control-Mode)
- [Buzz on GitHub](https://github.com/block/buzz)
- [Dear ImGui](https://github.com/ocornut/imgui)
- [hello_imgui](https://github.com/pthom/hello_imgui)
- Repo: `DESIGN.md`, `prfaq.tex`, `docs/assets/*.png`,
  `src/punt_lux/display/fonts.py`.
