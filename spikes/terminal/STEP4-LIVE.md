# Step 4: Display restart and crash checks

The isolated live checks use this branch, never the main Lux checkout.
The first checkpoint started the daemon explicitly. Later checks below cover
lazy startup, multiple-viewer-era protocol and actual rendered restart proof.

## Isolation

- HOME: a new `/tmp/lxgui-*` directory per run.
- Hub: loopback port 18531, verified free before starting.
- Display socket: the run directory's `display.sock`.
- PTY socket: the run directory's private `pty/p.sock`.
- `LUX_PTY_SOCKET` points the Display at that isolated daemon.
- All processes use the spike clone's virtual environment.
- No normal Lux service is stopped, restarted or reconfigured.

## Procedure

1. Start `python -m punt_lux.pty --socket <private path>`.
2. Start `luxd-hub --port 18531` and `luxd-display --socket <display path>`.
3. Submit a scene through `lux scene show` with a `terminal` element.
   The program prints a marker and waits for input.
4. Read the daemon's session list through a separately authenticated client.
5. Stop the Display, or SIGKILL it for the crash case.
6. Confirm the same program PID remains running while no Display is present.
7. Start a new Display on the same Display socket; leave the Hub and daemon
   running. The Hub re-replicates the scene.
8. Confirm the same program PID and output position. A second attach is
   refused as already occupied, proving the new Display owns the viewer
   binding rather than merely leaving the program running headless.
9. Stop all isolated processes and verify none remain.

## Observed results

| Case | Program before | While Display absent | After new Display | Viewer proof |
| --- | --- | --- | --- | --- |
| Normal close/restart | PID 22628, position 45, running | Same | Same | Already-attached rejection |
| SIGKILL/restart | PID 23785, position 45, running | Same | Same | Already-attached rejection |

No Display stderr errors were observed. All isolated processes were stopped.
These checks establish lifetime separation and actual-window attachment, not
pixel-perfect rendering or keyboard-latency/flood-performance measurements.

## Automated coverage

- `test_remote_replica.py`: partial snapshot assembly, no premature live bytes,
  no duplicate automatic replies, resize waits for the daemon, close never
  sends kill.
- `test_remote_live.py`: one production replica pool closes; another restores
  the same PID/screen. Exited programs remain exited on a new attachment.
- `test_server_live.py`: independent daemon/client lifecycle and negotiation.

## Stage-5 actual-window evidence

A fresh private HOME/socket instance started no PTY owner until a terminal was
shown. The Display then lazily launched daemon PID **66826**, which started
program PID **66887**. A finite paced burst completed at position **5,321,141**.
After Display SIGKILL and Hub scene replay into a new window, the same daemon,
program PID, output position and visible `BURST DONE` marker remained.

Three PID-selected screenshots are retained under `results/window-*.png`; OCR
verifies the cold and resumed markers. A preliminary restart capture was taken
before Hub replay and was blank. The check was corrected to wait for a connected
active Hub and verify pixels, rather than accepting PID persistence alone.

Twenty actual Hub-to-Display pings overlapped the burst. Median/p95 were
14.928/15.906 ms; the quiet idle window measured 59.021/62.573 ms. Output wakes
the render loop; this is control-path responsiveness, not keyboard-to-pixel or
FPS proof. See `STEP4-PERFORMANCE.md` for scope, raw reports and reproducibility.

Every isolated process was stopped and instance directory removed. Normal Lux
was untouched. The live helper is `check_daemon_window.py`, requiring the
reviewed macOS capture script from Lux main (read-only), ffmpeg and tesseract.

## Two simultaneous actual windows

`check_two_windows.py` starts two isolated Hubs/Displays with distinct private
HOME/Display sockets and one shared private PTY socket. It does not change Hub
topology or touch normal Lux. Both PID-selected screenshots are OCR-checked
for the same `SHARED PID` marker (whitespace normalization only).

- Daemon PID **7626**, program PID **7688**.
- Simultaneous Display PIDs **7542** and **7740** show that same program marker.
- Display 7542 is SIGKILLed. A new input through the control client produces
  `UPDATE:survivor` in Display 7740, proving continuing live updates, not a
  frozen screenshot of a program merely left running.
- Replacement Display **8054** rejoins through its original Hub and shows the
  same update. Program and daemon PIDs remain unchanged.
- Explicit kill and orderly teardown stop the owned program, daemon, Displays
  and Hubs; the private instance directory is removed. No test daemon remains.

Raw evidence is `results/two-windows.json` and `results/two-windows-*.png`.
Reproduce on macOS with the same reviewed capture prerequisites:

```sh
LUX_CAPTURE_SCRIPT=../lux/scripts/screenshot_macos.py \
  timeout 120 .venv/bin/python -m spikes.terminal.check_two_windows
```

## Remaining

Cold-start retry delay, flooded-input latency, full keyboard/pixel fidelity,
long-duration leak/soak and broader macOS suite verification remain open.
The branch is experimental and is not automatically merge-ready.
