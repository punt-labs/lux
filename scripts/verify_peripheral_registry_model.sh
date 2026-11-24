#!/usr/bin/env bash
# Check registry safety, deadlock freedom, and each policy-defect witness.
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
LOG_DIR="$(mktemp -d "$OUTPUT_DIR/peripheral-registry-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"
MODEL="$ROOT/docs/peripheral_registry_lifecycle.tex"
for switch in UNIQUE REGISTERED FROZEN COMPLETE STARTORDER STOPORDER; do
  sed "s/^  $switch = ztrue/  $switch = zfalse/" "$MODEL" > "$LOG_DIR/$switch.tex"
done

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

for model in "$MODEL" "$LOG_DIR"/*.tex; do
  label="$(basename "$model" .tex)"
  log="$LOG_DIR/$label-fuzz.log"
  "$FUZZ" -t "$model" > "$log" 2>&1 || fail "$label fuzz" "$log"
  echo "PASS: $label fuzz"
done

check() {
  local model="$1" label="$2" expected="$3" goal="${4:-}"
  local log="$LOG_DIR/$label.log"
  local args=("$model" -model_check -v -p DEFAULT_SETSIZE 2 -p MAXINT 3)
  args+=(-p TIME_OUT 60000)
  if [[ -n "$goal" ]]; then
    args+=(-nodead -goal "$goal")
  fi
  "$PROBCLI" "${args[@]}" > "$log" 2>&1 || fail "$label ProB" "$log"
  local errors
  errors="$(sed -nE \
    -e 's/.*[Tt]otal[[:space:]]+[Ee]rrors[[:space:]]*:[[:space:]]*([0-9]+)([[:space:]]*,.*|[[:space:]]*)$/\1/p' \
    -e 's/.*Finished[[:space:]]+model_check[[:space:]]*\(errors=([0-9]+),[[:space:]]*warnings=[0-9]+,[[:space:]]*expected_errors=[0-9]+\)[[:space:]]*$/\1/p' \
    "$log" | sort -u)"
  if [[ "$expected" == found ]]; then
    if ! { grep -Eq 'Found[[:space:]]+GOAL[[:space:]]+in[[:space:]]+state' "$log" &&
      [[ "$errors" == 1 ]] &&
      grep -Eq '![[:space:]]*goal_found' "$log"; }; then
      fail "$label expected defect witness" "$log"
    fi
  elif ! { [[ "$errors" == 0 ]] &&
    grep -Eq 'No counter[ -]?example found.*ALL states visited' "$log"; }; then
    fail "$label incomplete or unsafe" "$log"
  fi
  echo "PASS: $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
}

DUPLICATE='card(ran(registration)) /= size(registration)'
UNKNOWN='not(ran(bindings) <: ran(registration))'
MUTABLE='previous=rgsealed & (action=rgregister or action=rgbind)'
INCOMPLETE='(action=rgstart or action=rgstop) & ran(bindings)/=ran(registration)'
START='action=rgstart & dispatch/=registration'
STOP='action=rgstop & dispatch/=rev(registration)'
SAFETY="($DUPLICATE) or ($UNKNOWN) or ($MUTABLE) or ($INCOMPLETE) or ($START) or ($STOP)"
check "$MODEL" registry-safety 'not found' "$SAFETY"
check "$MODEL" registry-deadlock 'not found'
check "$LOG_DIR/UNIQUE.tex" duplicate-kind-fidelity found "$DUPLICATE"
check "$LOG_DIR/REGISTERED.tex" unknown-binding-fidelity found "$UNKNOWN"
check "$LOG_DIR/FROZEN.tex" frozen-wiring-fidelity found "$MUTABLE"
check "$LOG_DIR/COMPLETE.tex" incomplete-start-fidelity found 'action=rgstart & ran(bindings)/=ran(registration)'
check "$LOG_DIR/COMPLETE.tex" incomplete-stop-fidelity found 'action=rgstop & ran(bindings)/=ran(registration)'
check "$LOG_DIR/STARTORDER.tex" start-order-fidelity found "$START"
check "$LOG_DIR/STOPORDER.tex" stop-order-fidelity found "$STOP"
echo 'PASS: all peripheral registry model checks'
