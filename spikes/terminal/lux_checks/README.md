# Checks against the packaged terminal (`src/punt_lux/display/terminal/`)

Run from the repo root with `uv run --extra display python spikes/terminal/lux_checks/<script>`,
always under `timeout` (each finishes in seconds).

| Script | What it checks |
| --- | --- |
| `check_pkg.py` | The packaged `RenderState`/`RowBuilder` paints the same grid as the spike's per-cell reference, on every recording |
| `live_test_pkg.py` | Real bash on a PTY, driven through `TerminalView`'s input path: typing, Enter, Ctrl-C, arrows, paste, wrap, resize, exit (7 checks) |
| `frame_bench.py "<scenario>"` | End-to-end frame cost and throughput: `pump_all` + paint, scenarios `"1 flood"`, `"2 floods"`, `"1 flood + 3 idle"`, `"4 idle"` |
| `pump_bench.py <label>` | `PtyProcess.pump` alone: flood MB/s and idle cost |
| `tab_lux_layout.py` | Tab reaches the program inside a Lux-like frame (parent window + tab bar) |
| `zsh_tab.py` | `cd ~/` + Tab completes in a login zsh |

`lux-spike-env.sh` and the `*.json` scenes start a second, isolated Lux (own
`HOME`, socket and hub port 8531) and place terminals in it; see STEP3.md.
