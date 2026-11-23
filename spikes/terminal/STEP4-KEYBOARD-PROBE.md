# OS keyboard / 1,000-row table probe — incomplete

## What was observed

An isolated macOS Hub/Display lazily starts a terminal beside a six-column,
1,000-row table. The Hub's painted geometry reports both the terminal and the
table, with `row_count=1000`. The PID-selected setup screenshot/OCR contains
`KEYBOARD_READY` and `TABLE 1000 ROWS`. The program remains running.

Both screen capture and event-posting preflight checks return true. The probe
creates Quartz Unicode keyboard events and posts them only to the owned test
Display PID. It attempts child focus with PID-targeted mouse events, window
routing fields, a guarded process-scoped System Events click, and cursor
positioning. The cursor is restored during cleanup.

**The warm keyboard response never arrives.** The program's response log remains
without the expected marker, and the post-input screenshot still shows only
its ready state. Bounded waits fail and the helper tears down the owned Display,
Hub, daemon/program and private instance. No test daemon remains.

This does **not** distinguish a driver/focus problem from a product input issue.
It does not demonstrate that keyboard input works, and certainly does not yield
keyboard-to-pixel latency. The finite burst and quiet/busy key samples are not
reached. Permission preflight and successful event construction are not delivery
proof. No zero/placeholder latency values are published.

## Evidence and reproduction

- `results/keyboard-table-setup.png`: terminal and 1,000-row table rendered.
- `results/keyboard-table-input-unverified.png`: warm response not established.
- `results/keyboard-probe-status.json`: explicit incomplete outcome.
- `probe_keyboard_table.py`: exploratory diagnostic, **not a passing test** and
  not part of production dependencies or scoped pytest. It fails boundedly at
  the unverified input step in the recorded environment.

```sh
LUX_CAPTURE_SCRIPT=spikes/terminal/capture_macos.py \
  timeout 120 .venv/bin/python -m spikes.terminal.probe_keyboard_table
```

The reviewed capture helper is read-only from Lux main. Documentation lookup
used PyObjC `/ronaldoussoren/pyobjc` (Quartz event tests), plus installed bridge
metadata to check the Unicode-string call. No system-wide HID keyboard posting
fallback was used, and transport-written input was not relabeled as keyboard
input. Normal Lux services were not stopped or reconfigured.

## Acceptance implication

The previously reported replica round-trip and Hub/Display ping measurements
remain valid in their stated scopes. They do not fill this gap. A valid owned-
window input driver or an operator-assisted physical-key check is needed before
real keyboard/flood/table acceptance can be asserted. Calibrated first-pixel
measurement is a further, separate requirement.

Production code is unchanged in this checkpoint. Last functional verification
remains 835 focused tests, 18 integrations, all quality gates, 123 source
suppressions. This diagnostic is documented as incomplete rather than promoted
to a green test or used to relax acceptance criteria.
