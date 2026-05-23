#!/usr/bin/env python3
"""Live demo of the io-model spike — three self-contained scenarios.

Each scenario spawns its own fresh trio of OS processes (hub, display,
agent), narrates a single end-to-end roundtrip from start to finish,
verifies every tier participated, and tears down cleanly. No state
leaks between scenarios.

Run from the spike directory:

    python demo.py                                # text surface
    LUX_SURFACE=recording python demo.py          # recording surface
    python demo.py r1                              # run only R1
    python demo.py r3                              # run only R3
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


# ─────────────────────────── output multiplexing ──────────────────────────────


_IS_TTY = sys.stdout.isatty()
_RESET = "\x1b[0m" if _IS_TTY else ""
_BOLD = "\x1b[1m" if _IS_TTY else ""

_TIER_COLORS = {
    "HUB":  "\x1b[38;5;39m"  if _IS_TTY else "",   # cyan
    "DISP": "\x1b[38;5;208m" if _IS_TTY else "",   # orange
    "AGNT": "\x1b[38;5;120m" if _IS_TTY else "",   # green
    "DEMO": "\x1b[38;5;213m" if _IS_TTY else "",   # pink
    "USER": "\x1b[38;5;226m" if _IS_TTY else "",   # yellow
}

_print_lock = threading.Lock()

# Captured output for after-the-fact verification — reset per scenario.
_observed_lines: list[str] = []
_observed_lock = threading.Lock()


def _tag(label: str) -> str:
    color = _TIER_COLORS.get(label, "")
    return f"{color}{_BOLD}[{label:>4}]{_RESET}"


def out(label: str, line: str) -> None:
    with _print_lock:
        print(f"{_tag(label)} {line}", flush=True)
    with _observed_lock:
        _observed_lines.append(f"[{label}] {line}")


def reset_observed() -> None:
    with _observed_lock:
        _observed_lines.clear()


def section(title: str) -> None:
    bar = "─" * (len(title) + 2)
    with _print_lock:
        print()
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}╭{bar}╮{_RESET}")
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}│ {title} │{_RESET}")
        print(f"{_TIER_COLORS['DEMO']}{_BOLD}╰{bar}╯{_RESET}")
        print()


def step(label: str, text: str) -> None:
    """Narration step — labeled to make the scenario script obvious."""
    out("DEMO", f"{_BOLD}{label}.{_RESET} {text}")


def wait_for_line(label: str, fragment: str, *, timeout: float = 5.0) -> bool:
    """Poll captured output for a line from `label` containing `fragment`.
    Returns True if found within timeout; False otherwise."""
    deadline = time.time() + timeout
    prefix = f"[{label}] "
    while time.time() < deadline:
        with _observed_lock:
            for line in _observed_lines:
                if line.startswith(prefix) and fragment in line:
                    return True
        time.sleep(0.05)
    return False


def require(label: str, fragment: str, *, timeout: float = 5.0) -> bool:
    """wait_for_line + print on failure. Returns whether the line was observed."""
    if wait_for_line(label, fragment, timeout=timeout):
        return True
    out("DEMO", f"✗ FAILED — never observed [{label}] line containing {fragment!r} within {timeout}s")
    return False


# ─────────────────────────── process spawning ─────────────────────────────────


def _stream_reader(label: str, stream) -> threading.Thread:
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


def _spawn(label: str, module: str, env: dict[str, str], *, stdin_pipe: bool = False) -> subprocess.Popen[str]:
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


def _terminate(*procs: subprocess.Popen) -> None:
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


# ─────────────────────────── scenario context ─────────────────────────────────


@dataclass
class Trio:
    hub: subprocess.Popen[str]
    display: subprocess.Popen[str]
    agent: subprocess.Popen[str]
    agent_sock: Path
    display_sock: Path
    recording_path: Path
    tmpdir: Path


@contextmanager
def trio(
    *,
    surface: str,
    timer_seconds: float = 1.5,
    timer_disabled: bool = False,
    display_hz: float = 2.0,
    spawn_agent: bool = True,
    agent_run_seconds: int = 30,
    agent_mode: str = "basic",
) -> Iterator[Trio]:
    """Spawn hub + display + (optionally) agent for one scenario. Tear down on exit.

    `agent_mode` selects the AGNT's behavior:
      - "basic"  — Panel{Label, Button}; no reactive behavior (R1/R2/R3).
      - "dialog" — Yes/No dialog; on click, send a NEW scene to replace it (R4).
    `timer_disabled` turns off HUB's background SetProperty timer (use for
    scenarios where the timer would compete with scenario-driven state changes
    — e.g. R4's dialog where the timer would otherwise overwrite the question
    label with 'ticks: N')."""
    tmp = Path(tempfile.mkdtemp(prefix="lux-spike-demo-"))
    agent_sock = tmp / "agent.sock"
    display_sock = tmp / "display.sock"
    recording_path = tmp / "recording.jsonl"

    env = os.environ.copy()
    env["LUX_SPIKE_HUB_AGENT_SOCK"] = str(agent_sock)
    env["LUX_SPIKE_HUB_DISPLAY_SOCK"] = str(display_sock)
    env["LUX_SPIKE_RECORDING_PATH"] = str(recording_path)
    env["LUX_SURFACE"] = surface
    env["LUX_SPIKE_HUB_TICK_SECONDS"] = str(timer_seconds)
    env["LUX_SPIKE_HUB_TIMER_DISABLED"] = "1" if timer_disabled else "0"
    env["LUX_SPIKE_DISPLAY_HZ"] = str(display_hz)
    env["LUX_SPIKE_AGENT_RUN_SECONDS"] = str(agent_run_seconds)
    env["LUX_SPIKE_AGENT_MODE"] = agent_mode
    src = Path(__file__).resolve().parent / "src"
    env["PYTHONPATH"] = f"{src}:{env.get('PYTHONPATH', '')}".rstrip(":")

    out("DEMO", f"tmpdir={tmp}  surface={surface}")

    hub = _spawn("HUB", "hub", env)
    time.sleep(0.6)
    display = _spawn("DISP", "display", env, stdin_pipe=True)
    time.sleep(0.6)
    agent = (
        _spawn("AGNT", "agent", env)
        if spawn_agent
        else subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0)"])  # placeholder
    )

    trio_handle = Trio(
        hub=hub,
        display=display,
        agent=agent,
        agent_sock=agent_sock,
        display_sock=display_sock,
        recording_path=recording_path,
        tmpdir=tmp,
    )
    try:
        yield trio_handle
    finally:
        _terminate(agent, display, hub)
        shutil.rmtree(tmp, ignore_errors=True)


def simulate_user_click(display_proc: subprocess.Popen[str], elem_id: str) -> None:
    """Drive the real user-input path: write `click <id>` to Display stdin.
    Display's stdin reader thread encodes an InteractionMessage and ships
    it to Hub — same code path a human typing the line would take."""
    assert display_proc.stdin is not None, "display must be spawned with stdin_pipe=True"
    out("USER", f"types: click {elem_id}")
    display_proc.stdin.write(f"click {elem_id}\n")
    display_proc.stdin.flush()


# ───────────────────────────── scenarios ──────────────────────────────────────


def run_r1(surface: str) -> bool:
    """ROUNDTRIP 1 — show command from Agent, acceptance + propagation by Hub,
    apply + render by Display, observer push back to Agent.

    Independent: spawns its own hub+display+agent."""
    reset_observed()
    section("ROUNDTRIP 1 — show + accept + apply + render + notify")
    step("intent", "AGNT subscribes to 'scene.accepted', then sends show(Panel{Label, Button}) to HUB.")
    step("intent", "HUB decodes + instantiates Hub-tier Elements (rf=Null), accepts on hub_display,")
    step("intent", "encodes + sends AddElement Update to DISP, and publishes 'scene.accepted'.")
    step("intent", "DISP receives + decodes + instantiates DISP-tier Elements (rf=Surface), applies")
    step("intent", "to display_display, and renders the scene each frame. AGNT is notified via push.")

    with trio(surface=surface) as t:
        ok = True
        ok &= require("HUB",  "AGNT connected",                              timeout=5.0); step("1", "AGNT connected to HUB")
        ok &= require("HUB",  "AGNT subscribed to 'scene.accepted'",         timeout=3.0); step("2", "AGNT subscribed to 'scene.accepted'")
        ok &= require("AGNT", "sent show('scene1') to HUB",                  timeout=3.0); step("3", "AGNT sent show() to HUB")
        ok &= require("HUB",  "accepted scene 'scene1'",                     timeout=3.0); step("4", "HUB decoded + instantiated Hub-tier Elements; accepted scene on hub_display")
        ok &= require("HUB",  "sent AddElement Update to DISP",              timeout=3.0); step("5", "HUB encoded + sent AddElement Update to DISP")
        ok &= require("DISP", "decoded + instantiated DISP-tier Element tree", timeout=3.0); step("6", "DISP decoded + instantiated DISP-tier Elements; applied AddElement to display_display")
        ok &= require("DISP", "Panel[p1]",                                   timeout=3.0); step("7", "DISP rendered Panel composite")
        ok &= require("DISP", "Label[lbl1]",                                 timeout=3.0); step("8", "DISP rendered Label leaf")
        ok &= require("DISP", "Button[btn1]",                                timeout=3.0); step("9", "DISP rendered Button leaf — scene visible")
        ok &= require("HUB",  "published 'scene.accepted'",                  timeout=3.0); step("10", "HUB published 'scene.accepted' to subscribers")
        ok &= require("AGNT", "notified — topic='scene.accepted'",           timeout=3.0); step("11", "AGNT notified — 'scene.accepted' handler ran")

        out("DEMO", "✓ R1 PASSED — full outbound + observer push roundtrip end-to-end" if ok else "✗ R1 FAILED")
        return ok


def run_r2(surface: str) -> bool:
    """ROUNDTRIP 2 — Hub background-thread accepts state changes; DISP mirrors.

    Independent: spawns its own hub+display+agent."""
    reset_observed()
    section("ROUNDTRIP 2 — background-thread accept + apply + render")
    step("intent", "HUB timer thread is an in-process source of authoritative state changes:")
    step("intent", "each tick it accepts a SetProperty Update on hub_display, then encodes + sends")
    step("intent", "to DISP. DISP applies the Update to display_display; the next frame renders the new content.")

    with trio(surface=surface) as t:
        ok = True
        ok &= require("AGNT", "sent show('scene1') to HUB",                  timeout=5.0); step("1", "AGNT sent initial scene")
        ok &= require("DISP", "Button[btn1]",                                timeout=5.0); step("2", "initial scene rendered on DISP")
        ok &= require("HUB",  "timer tick 1 → accepted SetProperty",         timeout=3.0); step("3", "HUB timer tick 1 → accepted SetProperty(content='ticks: 1')")
        ok &= require("DISP", "applied SetProperty",                         timeout=3.0); step("4", "DISP applied the Update to display_display")
        ok &= require("DISP", "ticks: 1",                                    timeout=3.0); step("5", "DISP rendered Label with new content")
        ok &= require("HUB",  "timer tick 2 → accepted SetProperty",         timeout=3.0); step("6", "HUB timer tick 2 → accepted another SetProperty")
        ok &= require("DISP", "ticks: 2",                                    timeout=3.0); step("7", "DISP rendered Label with tick 2 content")

        out("DEMO", "✓ R2 PASSED — HUB accept → encode → send → DISP apply → render" if ok else "✗ R2 FAILED")
        return ok


def run_r3(surface: str) -> bool:
    """ROUNDTRIP 3 — user input enters at DISP, propagates to HUB for behavior
    invocation, EmittedEvent published, subscribed Agent notified.

    Independent: spawns its own hub+display+agent."""
    reset_observed()
    section("ROUNDTRIP 3 — detect + send + resolve + invoke + emit + publish + notify")
    step("intent", "USER produces a keystroke on DISP — the only tier where user input enters the system.")
    step("intent", "DISP detects the click, encodes an InteractionMessage, and sends it to HUB.")
    step("intent", "HUB receives + decodes, resolves the Element by id on hub_display, invokes")
    step("intent", "ButtonElement.on_click() (which emits a ButtonClicked Event), and publishes")
    step("intent", "'interaction.btn1' to subscribers. AGNT (subscribed) is notified.")

    with trio(surface=surface) as t:
        ok = True

        # ───── setup ─────
        ok &= require("HUB",  "AGNT connected",                              timeout=5.0); step("1", "processes started; AGNT connected to HUB")
        ok &= require("HUB",  "AGNT subscribed to 'interaction.btn1'",       timeout=3.0); step("2", "AGNT subscribed to 'interaction.btn1'")
        ok &= require("AGNT", "sent show('scene1') to HUB",                  timeout=3.0); step("3", "AGNT sent scene to HUB")
        ok &= require("HUB",  "accepted scene 'scene1'",                     timeout=3.0); step("4", "HUB accepted scene on hub_display + sent AddElement Update to DISP")
        ok &= require("DISP", "decoded + instantiated DISP-tier Element tree", timeout=3.0); step("5", "DISP decoded + instantiated Elements + applied to display_display")
        ok &= require("DISP", "Panel[p1]",                                   timeout=3.0); step("6", "DISP rendered Panel composite")
        ok &= require("DISP", "Label[lbl1]",                                 timeout=3.0); step("7", "DISP rendered Label leaf")
        ok &= require("DISP", "Button[btn1]",                                timeout=3.0); step("8", "DISP rendered Button leaf — scene fully visible")

        # ───── steady-state delay ─────
        step("9", "delay (2.5s) — steady state, no user input yet")
        time.sleep(2.5)

        # ───── user input ─────
        step("10", "USER clicks the button (simulated keystroke to DISP stdin)")
        simulate_user_click(t.display, "btn1")

        # ───── inbound roundtrip ─────
        ok &= require("DISP", "detected click(btn1)",                        timeout=2.0); step("11", "DISP detected the click")
        ok &= require("DISP", "encoded + sent InteractionMessage to HUB",    timeout=2.0); step("12", "DISP encoded + sent InteractionMessage to HUB")
        ok &= require("HUB",  "received InteractionMessage from DISP",       timeout=2.0); step("13", "HUB received the InteractionMessage")
        ok &= require("HUB",  "resolved ButtonElement",                      timeout=2.0); step("14", "HUB resolved ButtonElement[btn1] on hub_display")
        ok &= require("HUB",  "invoked ButtonElement.on_click()",            timeout=2.0); step("15", "HUB invoked behavior method (which emitted ButtonClicked)")
        ok &= require("HUB",  "published 'interaction.btn1'",                timeout=2.0); step("16", "HUB published 'interaction.btn1' to subscribers")
        ok &= require("AGNT", "notified — topic='interaction.btn1'",         timeout=2.0); step("17", "AGNT notified — 'interaction.btn1' handler ran")

        out("DEMO", "✓ R3 PASSED — USER → DISP → HUB → AGNT full inbound roundtrip end-to-end" if ok else "✗ R3 FAILED")
        return ok


def run_r4(surface: str) -> bool:
    """ROUNDTRIP 4 — interactive dialog with OO behavior dispatch.

    The dialog is a DialogElement on the HUB. Its child buttons are
    wired at construction time so that on_click invokes
    `dialog.close()`. When the user clicks any button:

      A) Button behavior runs (on HUB):
         - ButtonElement.on_click() emits ButtonClicked (Event)
         - then invokes its bound callback → DialogElement.close()
         - which emits RemoveElement(dlg) (Update)
         The HUB's emit handler routes each: Event → publish topic;
         Update → accept on hub_display + ship to DISP. The dialog
         removes itself through its own API; no Hub-side flag, no
         special interaction-handler logic.

      B) AGNT observes the click via the published topic. The dialog
         is already gone by the time AGNT's handler runs. AGNT
         independently composes a follow-up scene and sends a new
         show() for it.
    """
    reset_observed()
    section("ROUNDTRIP 4 — dialog dismisses itself via behavior; AGNT (observer) supplies follow-up")
    step("intent", "AGNT shows a DialogElement (kind='dialog'). At decode-time, HUB wires each")
    step("intent", "child button's on_click callback to dialog.close.")
    step("intent", "USER clicks Yes →")
    step("intent", "  (A) Button.on_click emits ButtonClicked AND calls dialog.close().")
    step("intent", "      dialog.close emits RemoveElement(dlg). HUB accepts + ships.")
    step("intent", "  (B) AGNT observes the click → performs work → ships a new follow-up scene.")
    step("intent", "AGNT is purely an observer; the dialog dismissed itself.")

    with trio(surface=surface, agent_mode="dialog", timer_disabled=True) as t:
        ok = True

        # ───── setup: dialog scene live ─────
        ok &= require("HUB",  "AGNT connected",                              timeout=5.0); step("1", "processes started; AGNT (dialog mode) connected to HUB")
        ok &= require("HUB",  "AGNT subscribed to 'interaction.btn_yes'",    timeout=3.0); step("2", "AGNT subscribed to 'interaction.btn_yes' (observer)")
        ok &= require("AGNT", "sent show('dialog') to HUB",                  timeout=3.0); step("3", "AGNT sent dialog scene (kind='dialog')")
        ok &= require("HUB",  "accepted scene 'dialog'",                     timeout=3.0); step("4", "HUB decoded DialogElement; bound child buttons' on_click → dialog.close; accepted on hub_display")
        ok &= require("DISP", "decoded + instantiated DISP-tier Element tree", timeout=3.0); step("5", "DISP applied AddElement to display_display")
        ok &= require("DISP", "Dialog[dlg]",                                 timeout=3.0); step("6", "DISP rendered Dialog composite")
        ok &= require("DISP", "Label[dlg_q]",                                timeout=3.0); step("7", "DISP rendered Label (Save your work?)")
        ok &= require("DISP", "Button[btn_yes]",                             timeout=3.0); step("8", "DISP rendered Button (Yes)")
        ok &= require("DISP", "Button[btn_no]",                              timeout=3.0); step("9", "DISP rendered Button (No)")

        # ───── steady-state delay ─────
        step("10", "delay (2.0s) — dialog steady, awaiting user input")
        time.sleep(2.0)

        # ───── user clicks Yes ─────
        step("11", "USER clicks the Yes button (simulated keystroke to DISP stdin)")
        simulate_user_click(t.display, "btn_yes")

        # ───── click reaches HUB; button behavior runs; dialog closes itself ─────
        ok &= require("DISP", "detected click(btn_yes)",                     timeout=2.0); step("12", "DISP detected the click")
        ok &= require("HUB",  "received InteractionMessage from DISP",       timeout=2.0); step("13", "HUB received the InteractionMessage")
        ok &= require("HUB",  "resolved ButtonElement",                      timeout=2.0); step("14", "HUB resolved ButtonElement[btn_yes] on hub_display")
        ok &= require("HUB",  "invoked ButtonElement.on_click()",            timeout=2.0); step("15", "HUB invoked button behavior")
        ok &= require("HUB",  "published 'interaction.btn_yes'",             timeout=2.0); step("16", "Button emitted ButtonClicked → HUB published 'interaction.btn_yes'")
        ok &= require("HUB",  "behavior emitted RemoveElement",              timeout=2.0); step("17", "Button's bound callback called dialog.close() → emitted RemoveElement(dlg)")
        ok &= require("HUB",  "sent RemoveElement Update to DISP",           timeout=2.0); step("18", "HUB accepted RemoveElement on hub_display + sent to DISP")
        ok &= require("DISP", "applied RemoveElement('dlg')",                timeout=3.0); step("19", "DISP applied RemoveElement — display_display empty; render loop draws nothing")

        # ───── (B) AGNT — purely observing — composes the follow-up ─────
        ok &= require("AGNT", "notified — topic='interaction.btn_yes'",      timeout=3.0); step("20", "AGNT notified (observer) — click handler runs")
        ok &= require("AGNT", "observed btn_yes — performing computation",   timeout=2.0); step("21", "AGNT performs its work (simulated, ~0.3s)")
        ok &= require("AGNT", "composing new scene",                         timeout=3.0); step("22", "AGNT composes follow-up scene")
        ok &= require("AGNT", "sent show('result') to HUB",                  timeout=2.0); step("23", "AGNT sent show('result') to HUB")
        ok &= require("HUB",  "accepted scene 'result'",                     timeout=3.0); step("24", "HUB accepted result scene on hub_display")
        ok &= require("HUB",  "sent AddElement Update to DISP",              timeout=3.0); step("25", "HUB sent AddElement Update to DISP")
        ok &= require("DISP", "Label[result_status]",                        timeout=5.0); step("26", "DISP rendered Label (Saved.)")
        ok &= require("DISP", "Label[result_body]",                          timeout=3.0); step("27", "DISP rendered Label (Result: 42 …)")
        ok &= require("AGNT", "notified — topic='scene.accepted'",           timeout=3.0); step("28", "AGNT notified — HUB confirms the result scene was accepted")

        out("DEMO", "✓ R4 PASSED — DialogElement dismissed itself via its close() behavior; AGNT (observer) supplied the follow-up" if ok else "✗ R4 FAILED")
        return ok


# ───────────────────────────── main ───────────────────────────────────────────


_SCENARIOS = {
    "r1": run_r1,
    "r2": run_r2,
    "r3": run_r3,
    "r4": run_r4,
}


def main(argv: list[str]) -> int:
    surface = os.environ.get("LUX_SURFACE", "text")
    requested = [a.lower() for a in argv[1:]] or ["r1", "r2", "r3", "r4"]

    unknown = [r for r in requested if r not in _SCENARIOS]
    if unknown:
        print(f"unknown scenarios: {unknown!r}; valid: {list(_SCENARIOS)}", file=sys.stderr)
        return 2

    section(f"io-model spike — live demo (surface={surface}, scenarios={requested})")
    out("DEMO", "Each scenario spawns fresh hub+display+agent processes,")
    out("DEMO", "runs one roundtrip end-to-end, verifies, and tears down.")

    results: dict[str, bool] = {}
    for name in requested:
        results[name] = _SCENARIOS[name](surface)

    section("Summary")
    for name in requested:
        mark = "✓" if results[name] else "✗"
        out("DEMO", f"{mark} {name.upper()}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
