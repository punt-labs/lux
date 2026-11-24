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

# shellcheck source=scripts/prob_model_check.sh
source "$ROOT/scripts/prob_model_check.sh"

DUPLICATE='card(ran(registration)) /= size(registration)'
UNKNOWN='not(ran(bindings) <: ran(registration))'
MUTABLE='previous=rgsealed & (action=rgregister or action=rgbind)'
INCOMPLETE='(action=rgstart or action=rgstop) & ran(bindings)/=ran(registration)'
START='action=rgstart & dispatch/=registration'
STOP='action=rgstop & dispatch/=rev(registration)'
SAFETY="($DUPLICATE) or ($UNKNOWN) or ($MUTABLE) or ($INCOMPLETE) or ($START) or ($STOP)"
check_model 3 "$MODEL" registry-safety 'not found' "$SAFETY"
check_model 3 "$MODEL" registry-deadlock 'not found'
check_model 3 "$LOG_DIR/UNIQUE.tex" duplicate-kind-fidelity found "$DUPLICATE"
check_model 3 "$LOG_DIR/REGISTERED.tex" unknown-binding-fidelity found "$UNKNOWN"
check_model 3 "$LOG_DIR/FROZEN.tex" frozen-wiring-fidelity found "$MUTABLE"
check_model 3 "$LOG_DIR/COMPLETE.tex" incomplete-start-fidelity found 'action=rgstart & ran(bindings)/=ran(registration)'
check_model 3 "$LOG_DIR/COMPLETE.tex" incomplete-stop-fidelity found 'action=rgstop & ran(bindings)/=ran(registration)'
check_model 3 "$LOG_DIR/STARTORDER.tex" start-order-fidelity found "$START"
check_model 3 "$LOG_DIR/STOPORDER.tex" stop-order-fidelity found "$STOP"
echo 'PASS: all peripheral registry model checks'
