# Step 4 design notes: `luxd-pty`, a daemon that owns the shells

Research and measurements before writing any code. Written 2026-11-17 on
`spike/terminal-ghostty`. Nothing here is built yet.

## The question

Today (ADR-0006) each terminal's PTY and Ghostty state live inside the Display
process. A Display restart, crash or upgrade kills every shell. The planned fix
is a separate daemon, `luxd-pty`, that owns the PTYs and a Ghostty terminal per
session. A Display attaches, gets the screen, then live bytes; keystrokes go
back the same way.

Three things had to be decided before building it:

1. How the Display and the daemon talk: what socket, what protocol.
2. Whether "a snapshot, then the bytes since" is enough for a reconnect.
3. What a reconnect costs.

And underneath all three: who may do what to a terminal. The spike has no
security model (limitation 1.3).

## What others do

### herdr-core (`hc`)

The closest thing to `luxd-pty` that exists: a Rust daemon that "runs programs
and coding agents in terminals that stay alive after you leave", built on
ghostty-vt, and "draws nothing". Apache 2.0.

- **Two processes, not one.** A *holder* owns every PTY, is every program's
  parent, and always reads output. It does no parsing and no policy, and keeps
  a ~1 MB tail per terminal. The *core* holds the Ghostty terminals, the API
  and the policy. A core crash or upgrade leaves programs running; the holder
  restarts the core, and the core rebuilds screens from the holder's tails.
- **Attach is a VT byte stream.** On attach the core sends a *first paint*:
  a soft reset, every mode forced off, then the scrollback and screen rendered
  back to VT bytes by Ghostty's formatter (`FORMAT_VT`), plus cursor, title and
  modes. After that, the program's raw output, minus the queries the core
  already answered. The viewer sends keys as raw bytes. The core never encodes
  keys.
- **Flow control and catching up.** Each stream starts with 256 KiB of credit;
  the viewer returns credit as it draws. A viewer more than 4 MiB behind gets a
  fresh repaint instead of the backlog.
- **Framing.** A connection starts as JSON-RPC 2.0, one message per line.
  `hello {framed: true}` switches to frames: `[channel u32][kind u8][len
  u32][payload]`. Channel 0 is JSON-RPC; each attach gets a channel. Frame
  kinds: DATA, CREDIT, CLOSE, RESIZE, FOCUS, FACTS, AUTOMATIC_INPUT.
- **API.** 36 methods in an OpenRPC schema generated from the Rust types, with
  a test that fails if a released method changes incompatibly. The ones that
  matter here: `terminal.run`, `list`, `get`, `attach`, `send`, `keys`,
  `read` (screen text without attaching), `wait` (until output or status
  changes), `interrupt`, `kill`, and `events.subscribe`.
- **Agent status is declared, not guessed.** A program reports working, done,
  blocked or error through OSC 7501. The core stores it and does not infer
  from screen text.
- **Security.** From `docs/security.md`: "Anyone who can connect to its API
  can run commands, read and change files, and control its terminals with
  that access." A Unix socket in a 0700 directory, no API password, no
  per-client permissions. Other programs running as the account are inside
  the trust boundary. Sessions (`HC_SESSION`) separate state but are "not
  security boundaries".

### tmux

- One server per user, one Unix socket in a 0700 directory (`/tmp/tmux-UID/`).
  The server refuses to start if the directory has looser permissions; a
  known weakness is that another user can pre-create the directory as a
  denial of service.
- Everything is one process: PTYs, screen state and clients. An upgrade
  requires killing the server (sessions die) unless the user resorts to
  `tmux-resurrect`-style reconstruction.
- **Control mode** (`tmux -CC`) is the attach protocol for GUIs: line-oriented,
  `%output %<pane> <escaped bytes>` for output, `send-keys` for input,
  `refresh-client -B` subscriptions for pane state, `%extended-output` with
  pause-after for flow control. Contour's `vthost` reimplements it exactly,
  which shows it is a usable boundary for a GUI.
- `server-access` gives per-user read/write grants, but the socket is still
  the real boundary.

### WezTerm

- A separate `wezterm-mux-server` owns panes; the GUI attaches over a Unix
  socket, SSH, or TLS (bootstrapped over SSH). The closest analogue to a
  Display that may be remote.
- Its protocol sends **render changes**, not bytes: per pane, the dirty lines,
  cursor, dimensions and title since the client's last known state, with an
  input serial so a client can tell which keystrokes a frame reflects. The
  client keeps a cached copy of the screen and asks for lines it is missing.
- It offers predictive local echo when the round trip is slow.

### What the Vox Rooms notes already decided

`docs/concepts/vox-rooms/notes/03-herdr-competitor-brainstorm.md`: tmux is no
longer the host; Lux owns `luxd-pty`; a Hub restart must not kill shells.
Keystrokes across hosts "amount to SSH" and are the highest-risk surface.

## Measurements

All on the spike's macOS machine, pyghostty 0.1.4, Python 3.14.

### Snapshot size and cost

A 200x60 terminal with 2,000 lines of coloured output in a 10,000-line
scrollback:

| Operation | Bytes | Time |
|---|---|---|
| VT repaint of the screen (Ghostty formatter, `FORMAT_VT`, all extras on) | 44,402 | 0.15 ms (median of 10; the first call was 22 ms, a one-off) |
| Worst case: every cell its own 24-bit colour | 276,266 | 0.38 ms |
| Binary snapshot, screen plus the whole scrollback (`ghostty_snapshot_encode`) | 109,287 | 0.18 ms |
| Replaying the VT repaint into a fresh terminal | | 0.37 ms |

So building a snapshot is well under a millisecond, and even the worst case
fits in a few socket frames.

**A trap found while measuring:** replaying the screen-only VT repaint into a
fresh terminal left every row off by one. The formatter emits the rows, and a
fresh terminal fed those rows scrolls once at the end (the last row's newline,
or a wrap). herdr avoids this with an explicit recipe: clear the screen, then
write the rows, with care at the last cell. The lesson is that **the VT
repaint needs a tested recipe, not just the formatter's output.** The binary
snapshot is simpler for a Display that also runs Ghostty: `ghostty_snapshot_*`
round-trips exactly, including a half-received escape sequence, which the VT
form cannot carry.

### Socket cost

A Unix stream socket, one process echoing to another:

| Payload | Round trip, median | p99 |
|---|---|---|
| 1 byte (a keystroke) | 6 µs | 12 µs |
| 4 KiB (an output frame) | 6 µs | 13 µs |

A keystroke's round trip through a daemon is three orders of magnitude under a
16 ms frame. The spike's in-process design was defended on latency; the
measurement says that argument does not hold against a local daemon.

The throughput run (128 MiB through the echo loop) did not finish inside the
60 s I gave the whole script, so I have no measured number; the two-thread
Python echo was the bottleneck, not the socket. Unix sockets are known to
carry several GB/s; the spike's current cap is 30-45 MB/s.

## Answers

### 1. Transport and protocol

**A Unix stream socket, owned by the daemon, in a 0700 directory under the
user's Lux state dir** (next to the Hub's socket; DES-002 already discovers
sockets this way). No TCP.

**Protocol: herdr's shape, not herdr's wire.** One connection, two layers:

- A control channel of JSON messages, one per line, for everything that is a
  request: create, list, attach, resize, send-keys, read-screen, kill, and an
  event subscription. Lux's protocol is already JSON; this keeps the Hub and
  `inspect_scene` able to speak it with no new codec.
- Per-attach binary frames `[channel u32][kind u8][len u32][payload]` for the
  byte stream, because output must not be base64'd or escaped per byte at
  tens of MB/s. tmux's `%output` escaping and herdr's JSON-only "plain mode"
  both exist for debuggability; the framed mode is what a GUI actually uses.

Frame kinds to copy: DATA (both ways), CREDIT (viewer to daemon), CLOSE,
RESIZE. FOCUS is cheap and some programs want it. AUTOMATIC_INPUT, which marks
terminal-generated replies (DA, XTGETTCAP) so they do not count as the human
typing, is a real problem herdr hit and is worth having from the start.

**Not WezTerm's render-change protocol.** It is the right design for a slow
link, and the Display's cached grid would make `inspect_scene` trivially
cheap. But it means the daemon decides what changed, per client, per frame,
and the Display cannot run its own Ghostty. For a local socket at 6 µs per
round trip, a byte stream with a repaint-on-lag rule is simpler and keeps one
VT engine per side. If a remote Display ever matters (Vox Rooms over SSH), the
Hub-side replication (DES-090) is where WezTerm's idea belongs, not here.

### 2. Is "snapshot, then bytes" enough?

**Yes, with three rules, all of which herdr learned the hard way:**

1. **The snapshot must carry modes, not just cells.** Mouse tracking, bracketed
   paste, focus reporting, the kitty keyboard flags, the alternate screen and
   synchronized output all change how the Display must behave. A repaint that
   paints the right characters but leaves mouse mode off breaks vim's mouse.
   Ghostty's formatter with `modes`, `keyboard`, `kitty_keyboard` and
   `charsets` on, or the binary snapshot, carries them. The byte tail after the
   snapshot then applies cleanly because it starts from the same state.
2. **The cut between snapshot and tail must fall on a parser boundary.** If the
   daemon snapshots while the parser is inside an escape sequence, the tail
   starts mid-sequence and the Display's parser desynchronises. Either the
   daemon snapshots only at ground state (pyghostty has
   `vt_write_until_ground` for exactly this), or it uses the binary snapshot,
   which includes the partial sequence.
3. **A lagging viewer gets a fresh snapshot, not the backlog.** herdr's 4 MiB
   rule. Without it a Display that stalled (a modal, a long frame) replays
   megabytes to arrive at a screen the daemon could have sent in 44 KB.

Two choices follow:

- **Snapshot format.** Two options, both measured above:
  - *VT repaint* (herdr): any viewer that speaks VT can attach, including a
    plain `nc` for debugging or a future text-mode client. Needs the tested
    recipe (the off-by-one above).
  - *Binary Ghostty snapshot*: exact, includes a partial sequence, 0.18 ms
    with the whole scrollback. Ties both sides to the same Ghostty version;
    `restore` returns nothing on a mismatch, so the daemon would fall back to
    the VT form.
  - **Recommendation:** binary snapshot as the fast path when versions match,
    VT repaint as the fallback and the debugging path. Build the VT recipe
    first because it is needed anyway.
- **Scrollback.** The screen repaint is 44 KB; the full scrollback snapshot is
  109 KB here and grows with history. Send the screen plus a bounded history
  (herdr's `history` parameter, default a few hundred lines) and let the
  Display fetch more on scroll.

### 3. What a reconnect costs

From the measurements, for a 200x60 terminal with 2,000 lines of history:

| Stage | Cost |
|---|---|
| Daemon builds the snapshot | 0.2-0.4 ms |
| Socket transfer, 44-110 KB | well under 1 ms locally |
| Display rebuilds its Ghostty state | 0.4 ms (VT replay) or less (binary restore) |
| First paint through the existing painter | one frame |

**Total: one or two frames, well under 50 ms,** per terminal. A Display
restart with ten terminals open is still under a second including process
start. The spike's current "restart kills the shell" costs the user the whole
session, so there is no comparison.

What is *not* free: the daemon must keep a Ghostty terminal per session fed at
full speed whether or not a Display is attached, because the screen has to be
correct at the moment of attach. That is CPU the Display pays today; it moves,
it does not disappear. herdr's holder/core split also means output is parsed
once in the core and again in each viewer. Lux would do the same: once in the
daemon (for snapshots and `inspect_scene`), once in the Display (to draw).

## The security model

This is the part the spike left blank, and it is the part that decides the
protocol's shape.

### What the daemon is

A process that starts programs as the user and lets clients type into them.
There is no way to dress that up: **access to the daemon's socket is a shell
as the user.** herdr says so in its first paragraph, and tmux's `server-access`
exists because its authors reached the same conclusion. The daemon cannot be a
sandbox for agents; macOS and Linux offer nothing in-process that would make
it one (DES-004 reached this for Python code, and it is equally true for a
child process).

So the model has two layers, and they must not be confused:

**Layer 1: who can reach the socket.** The operating system's job. A 0700
directory under the user's state dir, the socket created with umask 077, and
the daemon refusing to start if the directory's owner or mode is wrong (tmux's
check). On Linux, `SO_PEERCRED` confirms the peer's uid on every connection;
on macOS, `LOCAL_PEERCRED` does the same. Anything else running as the user is
inside the boundary, as it is for SSH agents, keychains and tmux. A remote
Display never talks to this socket; it talks to the Hub, and the Hub's mTLS
(DES-090) is the remote boundary.

**Layer 2: which client may do what to which terminal.** This is Lux policy,
and it is where Lux can be better than herdr, because Lux already knows who
its clients are: every Hub client has an identity and a lease (DES-094). The
daemon should know the same thing. Every request names a *principal*: the
Display acting for the human, or an agent's client identity. Then:

| Action | Human at the Display | Agent (Hub client) |
|---|---|---|
| Create a session running the login shell | yes | yes, with a consent gate |
| Create a session running an arbitrary `command` | yes | **consent gate**, like DES-004's code-running modal: show the command, Allow or Deny, remembered per command per session |
| Attach and view a terminal | yes | read-only view of terminals it created; others need consent |
| Type into a terminal | yes | into terminals it created; into a human's terminal only with consent, shown live ("agent X is typing") |
| Read the screen as text (`inspect_scene`) | yes | its own terminals; others need consent, because screens hold secrets |
| Kill a session | yes | its own |

The consent prompts belong in the Display (the only place the human is), as
DES-004 did. The daemon enforces the decision; it does not ask. When no
Display is attached, an agent request that needs consent **waits or fails**,
it does not default to yes. herdr avoids all of this by trusting every
client; Lux should not, because its stated goal (Vox Rooms) is agents
starting and driving terminals, which is exactly the case where "anyone on
the socket is you" is too coarse.

### Things that follow

- **Ownership (limitation 1.2).** A session has a creating principal and a
  lifetime policy: *attached* (ends when the last viewer detaches, the tmux
  default), *kept* (lives until killed; herdr's `--keep`), or *leased* (ends
  when its agent's Hub lease lapses, as applets do under DES-094). The element
  in a scene is a *view* of a session, not its owner; clearing the scene does
  not kill the shell. That matches DES-093's "the Hub holds content".
- **Secrets in the environment (limitation 1.11).** A shell started by the
  daemon in a directory with `.envrc` gets direnv's exports, including API
  keys. For human-started shells that is the same as kitty. For agent-started
  sessions the consent prompt should say the working directory, and a later
  version could start agent sessions with a reduced environment.
- **The daemon's own environment.** It will often start from launchd or
  systemd with almost nothing set. The spike already builds the user's
  environment from the user database (ADR-0006); herdr-core has a whole
  `platform/` directory for this (`macos_launchd`, `linux_login`,
  `macos_session`) and documents the restart-with-saved-environment
  problem at length. Budget for it.
- **Logs and persisted screens are secrets.** herdr's `security.md` says
  "treat the whole directory as private: terminal output and saved screens may
  contain secrets." The same applies to any scrollback `luxd-pty` writes to
  disk for restarts. Mode 0700, and documented.
- **What the daemon does not do.** It does not persist shells across a
  machine restart (nobody does; herdr restores layout and resumes supported
  agents, "the original processes do not survive"). It does not run as root.
  It is not reachable over the network.

### The holder/core split

herdr's two-process design means a daemon *upgrade* keeps the shells too, not
just a Display restart. For Lux that is the difference between "upgrading Lux
kills your shells" and not. The holder is small (spawn, read, write, resize,
reap, keep a tail) and changes rarely; the Ghostty-using core changes often.
Recommendation: **design the daemon with that seam from the start**, even if
step 4 ships them as one process. The seam is cheap to keep and expensive to
add later.

## What step 4 should build, in order

1. **The VT repaint recipe, with a test**: snapshot a terminal in known states
   (plain text, alternate screen with vim, mouse mode on, mid-escape) into a
   fresh Ghostty and compare cell grids. This is the correctness core and
   needs no daemon.
2. **A `luxd-pty` process with the socket, the two-layer protocol, one
   session, one viewer.** Measure end-to-end keystroke latency and `yes`
   throughput against the spike's 30-45 MB/s. Success: typing feels the same
   and throughput at least doubles.
3. **Reconnect:** kill the Display, start it again, compare screens. Measure
   the time. Then: two Displays attached to one session.
4. **Principals and the consent gate** for agent-created sessions, wired to
   the Hub's client identity. This is where the design meets Lux's existing
   model and will raise questions the first three steps do not.
5. **The holder seam**, if time allows: the PTY owner as a child process the
   core can be restarted without.

Language: the Vox Rooms notes propose Rust for `luxd-pty`. The spike's Python
pump reached 30-45 MB/s *inside the render loop with a 6 ms budget*; a
dedicated Python process reading PTYs with no frame budget would do better,
and pyghostty already exists. Rust buys the holder's "always reads, never
blocks" guarantee more easily and is what herdr proved. Steps 1-3 would show
whether Python is enough; I would not decide the language before step 2's
numbers.

## Open questions for Jim

1. **Consent for agent-started commands:** per command, per agent, or a
   standing allow-list in config? DES-004 chose per source change. A terminal
   is more dangerous than a render function and more frequent.
2. **Does an agent get to type into a human's shell at all?** herdr says yes
   (that is its whole model). The table above says only with live consent. It
   changes what `biff_talk`-style collaboration looks like.
3. **One daemon per user, or one per Hub?** Per user matches tmux and herdr
   and lets two Hubs show the same shell. Per Hub is simpler to reason about
   with leases. The Vox Rooms mesh (every object has a home Hub) suggests per
   Hub, with the Hub as the principal broker.
4. **Should the Hub be allowed to talk to `luxd-pty` directly** (to serve
   `inspect_scene` without a Display), or does everything go through the
   Display? DES-093 says the Hub holds content and never controls the Display;
   it says nothing against the Hub reading a terminal's screen.

## Sources

- herdr-core: `github.com/herdrdev/herdr-core` (README, `docs/security.md`,
  `schema/README.md`, `crates/herdr-core/src/holder.rs`, `viewers.rs`,
  `crates/ghostty-vt/src/lib.rs::paint`). Read 2026-11-17.
- tmux: `control.c`, the `server-access` manual, issues #3216 and #2765 on
  socket directory permissions; Contour's `vthost` control-mode notes.
- WezTerm: `docs/multiplexing.md`, `codec/src/lib.rs`,
  `wezterm-mux-server-impl/src/sessionhandler.rs`.
- Lux: DES-002, DES-004, DES-090, DES-093, DES-094;
  `docs/concepts/vox-rooms/notes/02-room-synthesis.md` §4 and
  `03-herdr-competitor-brainstorm.md`.
- Measurements: pyghostty 0.1.4 formatter and snapshot API; Unix socket echo
  in Python on this machine.
