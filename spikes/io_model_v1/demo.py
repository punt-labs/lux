#!/usr/bin/env python3
"""Live demo of the io-model spike — watch all three roundtrips happen.

Spawns hub + display + agent as three separate OS processes, tags each
process's stdout with a colored tier prefix, multiplexes them onto the
demo terminal in real time, and walks through the three canonical
roundtrips with clear section markers.

Run from the spike directory:

    python demo.py                  # text surface (default — pretty terminal output)
    LUX_SURFACE=recording python demo.py   # recording surface (JSONL log)

Stops on Ctrl-C or after the demo completes (~12s).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


# ─────────────────────────── output multiplexing ──────────────────────────────


# ANSI 256-color escapes. Fall back to plain text if stdout isn't a TTY.
_IS_TTY = sys.stdout.isatty()

_RESET = "\x1b[0m" if _IS_TTY else ""
_BOLD = "\x1b[1m" if _IS_TTY else ""
_DIM = "\x1b[2m" if _IS_TTY else ""

_TIER_COLORS = {
    "HUB":  "\x1b[38;5;39m"  if _IS_TTY else "",   # cyan
    "DISP": "\x1b[38;5;208m" if _IS_TTY else "",   # orange
    "AGNT": "\x1b[38;5;120m" if _IS_TTY else "",   # green
    "DEMO": "\x1b[38;5;213m" if _IS_TTY else "",   # pink
}


_print_lock = threading.Lock()


def _tag(label: str) -> str:
    color = _TIER_COLORS.get(label, "")
    return f"{color}{_BOLD}[{label:>4}]{_RESET}"


def out(label: str, line: str) -> None:
    with _print_lock:
        print(f"{_tag(label)} {line}", flush=True)


def section(title: str) -> None:
    bar = "─" * (len(title) + 2)
    with _print_lock:
        print()
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}╭{bar}╮{_RESET}")
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}│ {title} │{_RESET}")
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}╰{bar}╯{_RESET}")
        print()


def banner(text: str) -> None:
    with _print_lock:
        print()
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}» {text}{_RESET}")
        print()


# ─────────────────────────── process spawning ─────────────────────────────────


def _stream_reader(label: str, stream) -> threading.Thread:
    """Tag every line from a subprocess stream with the tier prefix."""
    def loop() -> None:
        for raw in iter(stream.readline, ""):
            line = raw.rstrip()
            if not line:
                continue
            out(label, line)
        stream.close()

    t = threading.Thread(target=loop, name=f"reader-{label}", daemon=True)
    t.start()
    return t


def spawn(label: str, module: str, env: dict[str, str], *, stdin_pipe: bool = False) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        [sys.executable, "-m", f"lux_spike.{module}"],
        env=env,
        stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    _stream_reader(label, proc.stdout)
    return proc


# ─────────────────────────── demo orchestrator ────────────────────────────────


def simulate_user_click(display_proc: subprocess.Popen[str], elem_id: str) -> None:
    """Drive the real user-input path: write `click <id>` to the Display
    process's stdin. The Display's stdin reader thread will encode an
    InteractionMessage and ship it to the Hub over Unix socket — same code
    path a keyboard-typed `click btn1` from a human user would take."""
    assert display_proc.stdin is not None, "display must be spawned with stdin_pipe=True"
    out("DEMO", f"writing 'click {elem_id}' to DISPLAY process stdin (simulating a real user keystroke)")
    display_proc.stdin.write(f"click {elem_id}\n")
    display_proc.stdin.flush()


def main() -> int:
    surface = os.environ.get("LUX_SURFACE", "text")
    tmp = Path(tempfile.mkdtemp(prefix="lux-spike-demo-"))
    agent_sock = tmp / "agent.sock"
    display_sock = tmp / "display.sock"
    recording_path = tmp / "recording.jsonl"

    env = os.environ.copy()
    env["LUX_SPIKE_HUB_AGENT_SOCK"] = str(agent_sock)
    env["LUX_SPIKE_HUB_DISPLAY_SOCK"] = str(display_sock)
    env["LUX_SPIKE_RECORDING_PATH"] = str(recording_path)
    env["LUX_SURFACE"] = surface
    env["LUX_SPIKE_HUB_TICK_SECONDS"] = "1.5"
    env["LUX_SPIKE_DISPLAY_HZ"] = "2"
    # DISPLAY stdin stays enabled so R3 can drive the real user-input code path.
    env["LUX_SPIKE_AGENT_RUN_SECONDS"] = "20"
    src = Path(__file__).resolve().parent / "src"
    env["PYTHONPATH"] = f"{src}:{env.get('PYTHONPATH', '')}".rstrip(":")

    section(f"io-model spike — live demo (surface = {surface})")
    out("DEMO", f"tmpdir = {tmp}")
    out("DEMO", f"hub<->display sock = {display_sock}")
    out("DEMO", f"hub<->agent  sock = {agent_sock}")
    if surface == "recording":
        out("DEMO", f"recording log     = {recording_path}")

    banner("Step 1: spawn three OS processes — hub, display, agent")
    procs: list[subprocess.Popen[str]] = []
    try:
        hub = spawn("HUB", "hub", env)
        procs.append(hub)
        time.sleep(0.7)
        display = spawn("DISP", "display", env, stdin_pipe=True)
        procs.append(display)
        time.sleep(0.7)
        agent = spawn("AGNT", "agent", env)
        procs.append(agent)

        # ── ROUNDTRIP 1 ─────────────────────────────────────────────────────
        section("ROUNDTRIP 1 — outbound + observer push")
        out("DEMO", "Expected sequence:")
        out("DEMO", "  agent.show(Panel{Label, Button})")
        out("DEMO", "  → hub decodes + applies + encodes AddElement Update")
        out("DEMO", "  → ships via Unix socket to display process")
        out("DEMO", "  → display decodes + applies to its own Element tree")
        out("DEMO", "  → display render loop calls elem.render() each frame")
        out("DEMO", "  → hub publishes 'scene.applied' topic")
        out("DEMO", "  → agent (subscribed) receives push notification")
        time.sleep(4.0)

        # ── ROUNDTRIP 2 ─────────────────────────────────────────────────────
        section("ROUNDTRIP 2 — background-thread state update")
        out("DEMO", "Hub timer thread fires every 1.5s and mutates LabelElement.content")
        out("DEMO", "via SetProperty Update. Watch the Label content increment each tick.")
        time.sleep(5.0)

        # ── ROUNDTRIP 3 ─────────────────────────────────────────────────────
        section("ROUNDTRIP 3 — user click inbound (display → hub → agent)")
        out("DEMO", "Expected sequence:")
        out("DEMO", "  user types `click btn1` (simulated by writing to DISPLAY stdin)")
        out("DEMO", "  → DISPLAY stdin reader encodes InteractionMessage")
        out("DEMO", "  → DISPLAY ships InteractionMessage to HUB over Unix socket")
        out("DEMO", "  → HUB looks up ButtonElement, calls button.on_click()")
        out("DEMO", "  → on_click() emits ButtonClicked Event")
        out("DEMO", "  → HUB publishes 'interaction.btn1' to subscribers")
        out("DEMO", "  → AGENT (subscribed on startup) receives push notification")
        simulate_user_click(display, "btn1")
        # Give the three processes time to handle the click roundtrip.
        time.sleep(2.5)

        section("Demo complete — shutting down")
        time.sleep(0.5)

    except KeyboardInterrupt:
        section("Interrupted — shutting down")
    finally:
        for p in reversed(procs):
            try:
                p.terminate()
            except ProcessLookupError:
                pass
        for p in procs:
            try:
                p.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(timeout=2.0)
        if surface == "recording" and recording_path.exists():
            banner("Recording surface output (first 12 lines)")
            for i, line in enumerate(recording_path.read_text().splitlines()):
                if i >= 12:
                    break
                out("DEMO", line)
        shutil.rmtree(tmp, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
