#!/usr/bin/env bash
# Check readiness safety, deadlock freedom, and all defect witnesses.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FUZZ="${FUZZ:-fuzz}"
PROBCLI="${PROBCLI:-probcli}"
command -v "$FUZZ" >/dev/null
command -v "$PROBCLI" >/dev/null
mkdir -p "$ROOT/.tmp"
LOG_DIR="$(mktemp -d "$ROOT/.tmp/readiness-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"
MODEL="$ROOT/docs/display_restart_readiness.tex"
sed 's/^  RESETDIAL = ztrue/  RESETDIAL = zfalse/' "$MODEL" > "$LOG_DIR/no-reset.tex"
sed 's/^  BOUNDWORK = ztrue/  BOUNDWORK = zfalse/' "$MODEL" > "$LOG_DIR/unbounded.tex"
sed 's/^  SAMPLEBOUND = ztrue/  SAMPLEBOUND = zfalse/' "$MODEL" > "$LOG_DIR/receipt-credit.tex"
sed 's/^  ACCEPTAFTER = 3/  ACCEPTAFTER = 2/' "$MODEL" > "$LOG_DIR/short-window.tex"

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

for model in "$MODEL" "$LOG_DIR/no-reset.tex" "$LOG_DIR/unbounded.tex" "$LOG_DIR/receipt-credit.tex" "$LOG_DIR/short-window.tex"; do
  label="$(basename "$model" .tex)"
  log="$LOG_DIR/$label-fuzz.log"
  "$FUZZ" -t "$model" > "$log" 2>&1 || fail "$label fuzz" "$log"
  echo "PASS: $label fuzz"
done

check() {
  local model="$1" label="$2" expected="$3" goal="${4:-}"
  local log="$LOG_DIR/$label.log"
  local args=("$model" -model_check -p DEFAULT_SETSIZE 2 -p MAXINT 7)
  args+=(-p TIME_OUT 60000)
  if [[ -n "$goal" ]]; then
    args+=(-nodead -goal "$goal")
  fi
  "$PROBCLI" "${args[@]}" > "$log" 2>&1 || fail "$label ProB" "$log"
  if [[ "$expected" == found ]]; then
    if ! { rg -q '^Found GOAL in state id ' "$log" &&
      rg -q '^! Total Errors: 1, Warnings:0$' "$log" &&
      rg -q '^! goal_found$' "$log"; }; then
      fail "$label expected defect witness" "$log"
    fi
  elif ! rg -q 'No counter example found. ALL states visited.' "$log"; then
    fail "$label incomplete or unsafe" "$log"
  fi
  echo "PASS: $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
}

# A union of bad states is unreachable iff every constituent invariant holds.
SAFETY='(phase=rsready & age<3) or now>6 or (phase=rsready & process/=rpnew) or (phase=rsready & now>=6) or (phase=rsready & sentAt-observedSince<3)'
check "$MODEL" I1-I5-safety 'not found' "$SAFETY"
check "$MODEL" deadlock 'not found'
check "$LOG_DIR/no-reset.tex" reconnect-fidelity found 'phase=rsready & age<3'
check "$LOG_DIR/unbounded.tex" deadline-fidelity found 'now>6'
check "$LOG_DIR/receipt-credit.tex" delivery-fidelity found 'phase=rsready & age<3'
check "$LOG_DIR/short-window.tex" short-window-fidelity found 'phase=rsready & sentAt-observedSince<3 & age>=3'
echo 'PASS: all readiness model checks'
