# Step 4: Display restart and crash checks

The isolated live checks use this branch, never the main Lux checkout.
The daemon is started explicitly; automatic startup is not implemented yet.

## Isolation

- HOME: a new `/tmp/lxgui-*` directory per run.
- Hub: loopback port 18531, verified free before starting.
- Display socket: the run directory's `display.sock`.
- PTY socket: the run directory's private `pty/p.sock`.
- `LUX_PTY_SOCKET` points the Display at that isolated daemon.
- All processes use the spike clone's virtual environment.
- No normal Lux service is stopped, restarted or reconfigured.

## Procedure

1. Start `python -m punt_lux.ptyd --socket <private path>`.
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

## Remaining

Credit accounting, lag repaint, several viewers of one session, automatic
startup, reconnect/flood timing and broader suite verification remain open.
The branch is still experimental and is not automatically merge-ready.
