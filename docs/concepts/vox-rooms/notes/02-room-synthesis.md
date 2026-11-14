# Lux as a shared room: terminals, a blackboard and a mesh

Date: 2026-11-12. Status: exploratory synthesis, not a design. Nothing here is ratified.

**Builds on:** DES-004, DES-040, DES-046, DES-063, DES-064, DES-089, DES-090, DES-093, DES-094 and DES-102.

**Conflicts with:**

- The PR/FAQ "Won't Do" list: texture-buffer rendering modes and a hosted service.
- The v1 guiding constraint in `CLAUDE.md`.

These conflicts are called out in §8.

**Inputs:** the earlier review notes ([01-lux-review-notes.md](01-lux-review-notes.md), §5 graphics engines), plus reading on herdr, tmux control mode and Block's Buzz.

**Not seen:** Biff's own code and docs are not in this container. I rely on the PR/FAQ's description of Biff ("presence") and on your description (messaging between agents and humans across networks).

---

## 1. The thesis

Today Lux is a screen agents can draw on. The more compelling Lux is **a shared room that agents and humans both work in**. The room has four kinds of surface:

1. **Terminals.** This is where agents actually run today.
2. **Rich views.** Plots, graphs, diffs and images, which terminals cannot show.
3. **A transcript.** Who said what, in order.
4. **A blackboard.** Shared, structured state that many parties read and write.

The room spans the machines you own as a mesh of Hubs, and any Display can look into it.

Each of the three tools read up on covers part of this:

| | Terminals | Agent awareness | Rich views | Shared messaging | Multi-host | Machine-readable state |
|---|---|---|---|---|---|---|
| **tmux** | yes | no | no | no | via SSH | yes (control mode) |
| **herdr** | yes | yes, guessed from output | no | agent→agent prompts | yes (`--remote`) | socket API |
| **Buzz** | no | identity, not state | canvases | yes (channels) | one relay | signed event log |
| **Lux today** | no | Clients menu | **yes** | no | Display ← N Hubs | **yes** (introspection) |

Lux already holds the two hardest columns: native rich rendering, and a live state that agents can inspect and verify. The other columns are additions, not a rewrite.

## 2. Lux already has the shape of tmux

Lux's architecture already has tmux's shape:

| tmux | Lux |
|---|---|
| server holds sessions; clients come and go | `luxd` holds scenes; the Display comes and goes (DES-093: "the Hub holds content and never controls the Display") |
| windows / panes | frames / scenes, with a `split_pane` renderer already present |
| detach and reattach | close the Display; content waits at the Hub |
| control mode: `%`-events and `-F` formats | MCP / REST introspection and Agent Subscribe |
| one server per user | one Hub per machine, with N Hubs per Display (DES-089) |

So "Lux with a terminal" does not bolt a foreign model onto Lux. It adds one element kind, and one missing replication primitive (§3), to a structure that already behaves like a multiplexer.

## 3. The missing primitive: a log next to the snapshot

Lux replicates by **snapshot**: whole-UI resend on change, with no diff protocol "until a real performance problem appears". Terminals, transcripts and blackboard histories are that performance problem. Each one is an append-only stream:

- A terminal is a byte stream fed through a deterministic VT state machine.
- A transcript is a message stream.
- A blackboard's history is a stream of writes.

Resending a 10,000-line scrollback on every byte of output is not viable.

**Proposal:** a second replication primitive, the **log**.

- A log is append-only, has a sequence number per entry, and has one owner.
- A replica follows the tail and resumes from its last sequence number after a reconnect.
- Flow control works like tmux's `%pause` / `continue`. It applies the same bounded-reader problem Lux already solved for inboxes (`lux-wk3p`, `menu_lifecycle_bounded_inbox.tex`) to a second case.
- A log element's *view state* still replicates by snapshot. Only its *body* replicates by log.

**Why this fits the architecture:**

- It keeps "UI state crosses IPC, render calls do not". Log entries are state, not drawing commands.
- It keeps "the Hub wins": the owner sequences the log.
- It mirrors D21's "same element state on both tiers". Because a VT parser is deterministic, the owner and the Display can each run one over the same byte log and agree on the screen, the way both tiers hold the same element copy today.

This primitive is the load-bearing decision under everything that follows. It is a stateful protocol (sequencing, resume, flow control, reconnect), so the z-spec rule in `CLAUDE.md` makes a model-check mandatory before any code.

## 4. The terminal element

### 4.1 Where each part lives

| Part | Tier | Why |
|---|---|---|
| The PTY and its process | **A terminal-host applet** (a DES-063 species), or tmux itself | No code runs in the Display (PR/FAQ). The Display may be remote or killed. DES-093 says the Hub controls no processes. |
| The VT parser that decides the screen | **Owner side** (applet or Hub), *and* a replica in the Display | Owner-side parsing lets `inspect_scene` return the terminal's text, so an agent can verify what is on screen without a screenshot. That is the target's verification goal, which herdr and tmux lack. |
| The cell-grid painter | Display | An ImGui draw list over a monospace font atlas. The dynamic fonts in 1.92 help. |
| Keystrokes | Display → Hub → owner | Remote dispatch as typed events, as D21 already does. Locally this adds a few milliseconds per key; across hosts it is noticeable, as noted in §6. |

### 4.2 Phase 1: let tmux be the terminal host

Do not build a PTY host at first. A `lux-tmux` applet speaks tmux control mode:

- `%output` feeds the byte log.
- `refresh-client -B` subscriptions feed pane titles and activity.
- `send-keys -H` carries input back.

Lux renders existing tmux sessions and inherits tmux's persistence for free. A pure terminal emulator is years of work (herdr leans on Ghostty's `ghostty-vt`). Options for the parser: `pyte` (pure Python, slower), libvterm bindings, or libghostty-vt bindings. Measure each against the frame budget (`kpz`).

### 4.3 The herdr part: agent state you declare, not guess

herdr tells working, blocked and idle apart by matching process names and output patterns. Lux can do better:

- The Lux plugin already runs a session-start hook.
- Claude Code hooks (PreToolUse, Stop, the permission prompt) can **declare** state to the Hub.
- Pattern matching becomes the fallback for agents with no hooks, consistent with DES-094: liveness is a heuristic, never a trust boundary.

The Clients menu (DES-064) becomes herdr's sidebar: each agent, its state, and "jump to the pane that needs you".

### 4.4 Where the graphics engines come in

The terminal is the one surface agents already live in. Lux's advantage is that the terminal sits beside, and inside, rich views:

- **Beside: a companion pane.** An agent in a terminal pane calls `show()`. Its plot, diff (ImGuiColorTextEdit), node graph (imgui-node-editor) or image (ImmVision) lands in the adjacent pane of the same frame. The terminal and the views are siblings under one owner.
- **Inside: inline elements in the scrollback.** Terminals already have inline-graphics conventions: the kitty graphics protocol, sixel and OSC 8 hyperlinks. Lux could accept an OSC escape that names a Lux scene. `lux show plot.json` from a shell would then drop a live, interactive widget into the scrollback, not a picture. tmux and herdr cannot do this.
- **Hub-side layout engines** (Graphviz or ELK, §5.3 of the notes) turn an agent's process tree, `bd` dependencies or a mesh topology into a laid-out node graph next to the terminals.

## 5. The transcript and the blackboard

These are two different things, and Buzz merges them. Lux should keep them apart.

### 5.1 The transcript (time-ordered)

- **What it is:** who said what, in order. Channels, threads and DMs, as in Buzz.
- **Primitive:** a log (§3) with signed entries.
- **Boundary with Biff:** Biff already owns messaging and presence between agents and humans across networks. Lux should not rebuild it. Biff stays the transport, delivery and identity layer for messages. Lux supplies a **transcript element** that renders a Biff channel richly: inline Lux elements in messages, code blocks with a gutter, agent state badges, and jump-to-terminal. This is the PR/FAQ's "companion-tool surfacing" item ("render biff presence panels") taken all the way.
- **Open question:** I have not seen Biff's code. If Biff has no durable ordered log per channel, the log primitive could live in Lux and Biff could carry it. That boundary is the operator's decision.

### 5.2 The blackboard (spatial and structured)

The blackboard is the classic AI blackboard architecture (Hearsay-II): independent specialists read and write one shared, structured workspace, and a controller notices what changed. Lux is unusually well placed to offer it, because it already has the core parts:

- **Hub-authoritative shared state:** `HubDisplay`.
- **Change notification:** Agent Subscribe, the observer path, and pub-sub.
- **Typed, self-validating content:** the element vocabulary with `validate()`.
- **Verifiable reads:** introspection.

**What is new:**

- **Regions with owners.** Each agent owns a region, such as a table, a graph or a status block. Writes to a region come only from its owner. Everyone can read the whole board.
- **Multi-writer scenes.** Today one connection owns one scene (DES-086 keys the store by connection). A blackboard is one scene with many owners, which needs a scene-composition rule that DES-086 does not have.
- **A history log** (§3), so the board can be replayed and audited. Like Buzz's single log, this records who changed what and when.

A blackboard is strictly more than Buzz's canvases. Agents write typed, validated state that other agents can query, not free-form documents. That is the version of "agents talking to each other" that only Lux can offer: they coordinate through shared structured state, not only through prose.

## 6. From hub-and-display to a mesh

### 6.1 Where it is today

- A Display aggregates 1..N Hubs (DES-089).
- Each cross-host link uses mTLS against a pluggable trust anchor (DES-090).
- A click routes to the Hub that owns the element.
- Hubs do not talk to each other.

### 6.2 The step to a mesh

**Keep "one authority", but per object instead of per system.** That is already the de facto rule, since a click goes to the owning Hub. The mesh makes it explicit:

- **Every object has a home Hub.** That covers scenes, logs, blackboards and terminals. The home Hub sequences and decides.
- **Hubs replicate to each other.** Hub B can subscribe to Hub A's logs and scenes, so a Display attached only to B still sees A's terminal and the shared blackboard.
- **Routing is location-transparent.** An interaction on any Display travels Display → its Hub → the home Hub. DES-089's addressing (the Hub-of-origin rung) already names every object globally, so the mesh needs routing, not new names.
- **Logs merge cheaply. Mutable state does not.** Append-only signed logs from different authors can be unioned and ordered. Mutable blackboard regions keep a single home, which avoids CRDTs until there is a reason to need them.

**Compared with Buzz:** Buzz has one relay per workspace. ForkLog's critique is that this makes it less decentralised than it claims. A Lux mesh has many homes, each authoritative only for what it owns. That fits "user-owned machines, no hosted service" better than a central relay.

### 6.3 Identity and trust

- Buzz gives every agent its own keypair, and press coverage says a second signature binds the agent to its human owner.
- Lux has the parts for the same: per-host mTLS identity (DES-090), the client-identity ladder (DES-057, DES-089), and ethos identities for agents.
- The missing piece is **per-agent signing of log entries**, so a transcript or blackboard entry can be attributed and verified across the mesh. Keystrokes into a terminal across hosts amount to SSH. That is the highest-risk surface in this whole picture and needs `djb` review before anything ships.

## 7. What the compelling Lux looks like

> **Lux is the room where your agents work, on every machine you own.**
> Every agent's terminal, live, side by side, with the ones waiting for you flagged.
> Next to each terminal, the plots, diffs and graphs it produces, as live widgets, not screenshots.
> A transcript where humans and agents talk (carried by Biff).
> A blackboard where agents coordinate through shared structured state.
> Every pixel is also readable by agents, so they verify what happened instead of asking you.

**What stays Lux-specific:**

- Rich native views next to terminals.
- Hub-authoritative state that agents can introspect.
- A typed, validated shared blackboard.
- A user-owned mesh with per-object authority.

tmux, herdr and Buzz each have one or two of these, not all four.

## 8. Conflicts with what is already settled

| Conflict | Where | Nature |
|---|---|---|
| **v1 guiding constraint:** "data-display core and ask-user loop". Applications inside the display are out. | `CLAUDE.md` Vision; PR/FAQ | Terminals, the blackboard and the mesh are a **strategic pivot**. Per `WORKFLOW.md`, that is the operator's ruling, not sequencing. |
| **"Won't do: multiple rendering modes, no texture-buffer"** | PR/FAQ `feat:no-modes` | Offscreen engines (VTK, Vega-Lite) render to textures. The terminal element does not; it is a native draw-list painter. |
| **"Won't do: hosted service API"** | PR/FAQ `feat:no-http` | A mesh of user-owned Hubs is consistent with this. A Buzz-style hosted relay would not be. |
| **Whole-UI resend, no diff protocol** | `target.md` Replication Policy | The log primitive (§3) is a deliberate second replication mode. It needs its own ADR. |
| **One connection owns a scene** | DES-086 | A multi-writer blackboard needs a composition rule. |
| **The Hub controls no processes** | DES-093 | PTYs therefore live in an applet or in tmux, never in the Hub or the Display. |
| **Lux vs Biff responsibilities** | PR/FAQ "companion-tool surfacing" | The transcript boundary needs a ruling with Biff's code in view. |

## 9. Risks

1. **Scope.** Terminal emulation, messaging and a mesh are each a product. Phase as in §10 and stop at whichever phase earns adoption.
2. **Display debt.** `render_loop.py` is about 780 lines against a 300-line target, and render paths are largely untested. A terminal painter added on top makes this worse unless the decomposition and `imgui_test_engine` come first.
3. **Frame budget.** A busy terminal pushing megabytes per second through Python-side VT parsing may miss 60 fps. This needs measuring (`kpz`), and may push the parser into native code.
4. **Cross-host input latency and security.** A remote terminal is remote code execution by design. It needs mTLS, per-identity permissions and an audit trail before it ships.
5. **Formal-methods load.** The log protocol, mesh routing, and blackboard ownership on reconnect are all in the mandatory z-spec class.

## 10. A phasing that delivers value at each step

| Phase | Delivers | New primitive | Gate |
|---|---|---|---|
| 0 | `lux-herdr` and `lux-tmux` applets that show **read-only** agent-state boards and session lists. No terminal rendering. | none (applets, DES-063) | demo |
| 1 | **Log primitive** plus a **transcript element** rendering a Biff channel | log replication | z-spec of sequencing, resume and flow control; ADR |
| 2 | **Terminal element** backed by tmux control mode, with declared agent state via hooks and a jump-to-blocked-agent action | VT replica on both tiers | frame-budget receipts (DES-070 style); `djb` review of input routing |
| 3 | **Companion panes and inline elements** (OSC escape → Lux scene) next to terminals, with the node editor and code view kinds | 2–3 v2 element kinds | per-kind `validate()` |
| 4 | **Blackboard**: multi-owner scene, owned regions, history log | multi-writer composition | z-spec of ownership across reconnects; ADR amending DES-086 |
| 5 | **Mesh**: Hub-to-Hub replication of logs and scenes, routing to the home Hub, per-agent signed entries | Hub↔Hub leg | z-spec of routing and replication; ADR extending DES-089 and DES-090 |

Phase 0 is cheap and tests demand: does anyone want herdr's or tmux's state in Lux? Phase 1 is the real commitment, because every later phase depends on the log.

## 11. Decisions this would need from the operator

1. Is the room thesis a pivot Lux takes, or a v2 horizon? This changes `CLAUDE.md`'s Vision and the PR/FAQ.
2. Where is the line between Lux and Biff for messages and transcripts?
3. Does the log primitive become a second replication mode, amending `target.md`?
4. Do terminals render existing tmux sessions (phase 2 as written), or does Lux eventually host its own PTYs through an applet?
5. Should a mesh object's home be fixed at creation, or able to migrate?

---

## Sources

- [herdr on GitHub](https://github.com/herdrdev/herdr)
- [AI Weekly: herdr agent-state awareness](https://aiweekly.co/alerts/herdr-adds-agent-state-awareness-to-terminal-multiplexing)
- [tmux wiki: Control Mode](https://github.com/tmux/tmux/wiki/Control-Mode)
- [Buzz on GitHub](https://github.com/block/buzz)
- [ForkLog: Block launches Buzz](https://forklog.com/en/block-launches-buzz-an-open-source-platform-for-teams-and-ai-agents/)
- [Shopifreaks: Buzz agent identities](https://www.shopifreaks.com/block-releases-buzz-an-open-source-workspace-where-ai-agents-hold-their-own-cryptographic-identities-and-work-with-humans/)
- Repo: `DESIGN.md` (the ADRs cited above), the repo-root `prfaq.tex` (lines 600–615 and 775–815), `docs/architecture/target/*.md`, `CLAUDE.md`.
