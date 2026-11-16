# ADR-0006: A `terminal` element names a session; the Display pumps sessions each frame

- **Status:** Accepted for the spike. To be superseded by a separate `luxd-pty`
  daemon (step 4).
- **Date:** 2026-11-15
- **Evidence:** `spikes/terminal/STEP3.md`;
  `src/punt_lux/protocol/elements/terminal.py`,
  `src/punt_lux/display/terminal/sessions.py`, `display/render_loop.py`

## Context

A terminal has to appear in Lux the way other content does: an agent or app
sends a scene, and the Hub stores it and replicates it to the Display. But a
terminal differs from other elements in three ways:

- it produces a steady stream of bytes
- it needs every keystroke with no added delay
- its program must keep running whether or not the element is on screen

Lux's rules apply too:

- One thread runs the Display, polling its sockets once per frame (DES-002).
- The Hub never controls the Display process (DES-093).
- The Display holds a copy of each scene; it doesn't own state.

## Decision

- **The element only places the terminal.** It carries `id`, `session` (which
  defaults to the `id`), `command` (default: the user's login shell) and
  `height` (0 fills the frame). It is registered like other leaf elements
  (codec, ABC registry, ImGui renderer). The Hub knows nothing about terminals.
- **Bytes don't go through the Hub.** Output and keystrokes go directly between
  the Display and the program, so typing has no extra hops.
- **For the spike, sessions live in the Display process**
  (`TerminalSessions`, keyed by name):
  - The first time an element names a session, the session starts.
  - Re-rendering the element, or showing it in another frame, reuses it.
- **One pump per frame:** before painting, the render loop calls
  `TerminalSessions.pump_all()`. It reads each PTY without blocking, up to
  256 KB per frame, so a flood can't stall a frame.
- **Stay awake while output flows:** hello_imgui only counts input as activity.
  While a terminal produces output, and for 0.25 s after, the loop turns idling
  off. Without this, a busy terminal in an untouched window updated at about
  27 fps; with it, about 9 ms per frame.
- **Exiting ends the terminal:** when the program exits, the session stays and
  the terminal shows `[process exited]`. It is not restarted. This was found
  live: the first version respawned the shell on the next frame.
- **Closing never hangs:** SIGHUP, a short wait, then SIGKILL, never a blocking
  `waitpid`. Found live: an interactive shell that ignored SIGHUP hung the
  Display on exit.

## Consequences

- It works inside the real Lux display. Two terminals ran at once, each with
  its own shell; dock and undock work. With `top` running: about 52 fps at 14%
  of one core, on an overloaded machine.
- Lux binds no global keys of its own (only Enter in text inputs and Escape in
  modals), so the terminal gets every key while it has focus.
- **The spike's main limitation:** sessions die whenever the Display restarts
  (crash, upgrade, `lux display stop`). That conflicts with the target design,
  where Lux holds content while no Display is connected (DES-093).
- **Planned fix (step 4): a `luxd-pty` daemon.**
  - It owns the PTYs and a Ghostty terminal for each.
  - When a Display attaches, it sends a full terminal snapshot, then live
    bytes. Keystrokes travel back the same way.
  - Its copy of the screen also lets agents read what a terminal shows without
    a Display.
- **Ownership is undecided.** Who may start a session, and what happens when
  the scene that named it is removed, have no policy yet.

## Alternatives considered

- **Bytes through the Hub, as content updates:** adds hops and latency to every
  keystroke, and floods the Hub's replication path. Rejected.
- **Start the session in the Hub process:** DES-093 permits it, but a Hub
  restart would kill shells. The Vox Rooms notes prefer a separate daemon.
- **A reader thread per PTY (as imgui_terminal does):** conflicts with DES-002
  and needs locking around the terminal. Rejected.
