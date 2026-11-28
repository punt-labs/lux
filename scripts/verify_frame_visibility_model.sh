#!/usr/bin/env bash
# Check the frame lifecycle model: fuzz, invariants, deadlock freedom, the
# fidelity variants, and the End/OwnerEnd trace replays.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FUZZ="${FUZZ:-fuzz}"
PROBCLI="${PROBCLI:-$HOME/Applications/ProB/probcli}"
for binary in "$FUZZ" "$PROBCLI"; do
  if ! command -v "$binary" >/dev/null 2>&1; then
    echo "ERROR: required verification binary not found: $binary (set FUZZ or PROBCLI)" >&2
    exit 1
  fi
done
OUTPUT_DIR="${MODEL_OUTPUT_DIR:-$ROOT/.tmp}"
mkdir -p "$OUTPUT_DIR"
LOG_DIR="$(mktemp -d "$OUTPUT_DIR/frame-visibility-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"
MODEL="$ROOT/docs/frame-visibility-lifecycle.tex"

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

# mutate SCHEMA OLD NEW: print the model with every line of SCHEMA equal to OLD
# replaced by NEW. Exact line match; the awk reads both strings from the
# environment so backslashes survive. A mutation that changes nothing is an
# error, so a variant cannot silently become a copy of the intact model.
mutate() {
  local schema="$1" old="$2" new="$3" out
  out="$(OLD="$old" NEW="$new" SCHEMA="$schema" awk '
    BEGIN { old = ENVIRON["OLD"]; new = ENVIRON["NEW"]; start = "\\begin{schema}{" ENVIRON["SCHEMA"] "}" }
    $0 == start { inside = 1 }
    inside && $0 == old { print new; changed++; next }
    inside && $0 == "\\end{schema}" { inside = 0 }
    { print }
    END { if (!changed) exit 3 }
  ' "$CURRENT")" || {
    echo "FAIL: mutation of $schema matched no line: $old" >&2
    exit 1
  }
  CURRENT="$LOG_DIR/.step.tex"
  printf '%s\n' "$out" > "$CURRENT"
}

# variant NAME: finish the mutation chain begun with CURRENT=$MODEL.
variant() {
  cp "$CURRENT" "$LOG_DIR/$1.tex"
}

CURRENT="$MODEL"
mutate PushNewFrame "  focus' = focus \\\\" "  focus' = \\{ f? \\} \\\\"
mutate PushNewFrame "  autoFocused' = autoFocused \\\\" "  autoFocused' = autoFocused \\cup \\{ f? \\} \\\\"
mutate PushNewScene "  vis' = vis \\\\" "  vis' = vis \\oplus \\{ f? \\mapsto vOnScreen \\} \\\\"
mutate PushNewScene "  activeTab' = activeTab \\\\" "  activeTab' = activeTab \\oplus \\{ f? \\mapsto s? \\} \\\\"
mutate PushNewScene "  focus' = focus \\\\" "  focus' = \\{ f? \\} \\\\"
mutate PushNewScene "  autoFocused' = autoFocused \\\\" "  autoFocused' = autoFocused \\cup \\{ f? \\} \\\\"
mutate PushNewScene "  tabStolen' = tabStolen" "  tabStolen' = tabStolen \\cup \\{ f? \\}"
variant push-arrival

CURRENT="$MODEL"
mutate End "  f? \\in handler \\\\" "  f? \\in frames \\\\"
variant end-no-handler

CURRENT="$MODEL"
mutate OwnerEnd "  vis' = \\{ f? \\} \\ndres vis \\\\" \
  "  vis' = (\\{ f? \\} \\ndres vis) \\oplus ((frames \\setminus \\{ f? \\}) \\cross \\{ vOnScreen \\}) \\\\"
variant end-writes-visibility

for model in "$MODEL" "$LOG_DIR"/*.tex; do
  label="$(basename "$model" .tex)"
  log="$LOG_DIR/$label-fuzz.log"
  "$FUZZ" -t "$model" > "$log" 2>&1 || fail "$label fuzz" "$log"
  echo "PASS: $label fuzz"
done

# shellcheck source=scripts/prob_model_check.sh
source "$ROOT/scripts/prob_model_check.sh"

AUTOFOCUS='autoFocused /= {}'
TABSTEAL='tabStolen /= {}'
UNDOCKED='card({f|f:FRAME & f:frames & f:userDocked & vis(f)=vOnScreen})>0'
NOHANDLER='not(endPending <: handler)'
check_model 3 "$MODEL" content-never-focuses 'not found' "$AUTOFOCUS"
check_model 3 "$MODEL" content-never-steals-tab 'not found' "$TABSTEAL"
check_model 3 "$MODEL" content-never-undocks 'not found' "$UNDOCKED"
check_model 3 "$MODEL" end-needs-handler 'not found' "$NOHANDLER"
check_model 3 "$MODEL" lifecycle-deadlock 'not found'
check_model 3 "$LOG_DIR/push-arrival.tex" push-arrival-focus-fidelity found "$AUTOFOCUS"
check_model 3 "$LOG_DIR/push-arrival.tex" push-arrival-tab-fidelity found "$TABSTEAL"
check_model 3 "$LOG_DIR/push-arrival.tex" push-arrival-undock-fidelity found "$UNDOCKED"
check_model 3 "$LOG_DIR/end-no-handler.tex" end-no-handler-fidelity found "$NOHANDLER"
check_model 3 "$LOG_DIR/end-writes-visibility.tex" end-writes-visibility-fidelity found "$UNDOCKED"

# replay NAME EXPECTED STEP...: run the steps as a probcli trace. probcli exits 0
# for a failed replay, so the verdict is read from its output.
replay() {
  local name="$1" expected="$2"
  shift 2
  local dir="$LOG_DIR/replay-$name"
  mkdir -p "$dir"
  cp "$MODEL" "$dir/m.tex"
  {
    echo "machine('m')."
    echo "'\$initialise_machine'."
    local step
    for step in "$@"; do echo "$step"; done
  } > "$dir/m.trace"
  "$PROBCLI" "$dir/m.tex" -t -p DEFAULT_SETSIZE 2 > "$dir/replay.log" 2>&1 || fail "replay $name ProB" "$dir/replay.log"
  if [[ "$expected" == replays ]]; then
    grep -q 'Trace checking successful' "$dir/replay.log" || fail "replay $name should replay" "$dir/replay.log"
  else
    grep -q "trace_checking_fails" "$dir/replay.log" || fail "replay $name should fail" "$dir/replay.log"
    grep -q "OPERATION:$expected," "$dir/replay.log" || fail "replay $name should fail at $expected" "$dir/replay.log"
  fi
  echo "PASS: replay $name $expected"
}

NEW="'PushNewFrame'(fd(1,'FRAME'),fd(1,'SCENE'))."
HANDLER="'RegisterEndHandler'(fd(1,'FRAME'))."
END="'End'(fd(1,'FRAME'))."
OWNER="'OwnerEnd'(fd(1,'FRAME'))."
replay end-then-owner-ends replays "$NEW" "$HANDLER" "$END" "$OWNER"
replay end-without-handler End "$NEW" "$END"
replay owner-end-without-request OwnerEnd "$NEW" "$HANDLER" "$OWNER"
echo 'PASS: all frame visibility model checks'
