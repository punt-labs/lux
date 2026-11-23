#!/usr/bin/env bash
# Check readiness safety, deadlock freedom, and all defect witnesses.
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
mkdir -p "$ROOT/.tmp"
LOG_DIR="$(mktemp -d "$ROOT/.tmp/readiness-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"
MODEL="$ROOT/docs/display_restart_readiness.tex"
sed 's/^  RESETDIAL = ztrue/  RESETDIAL = zfalse/' "$MODEL" > "$LOG_DIR/no-reset.tex"
sed 's/^  BOUNDWORK = ztrue/  BOUNDWORK = zfalse/' "$MODEL" > "$LOG_DIR/unbounded.tex"
sed 's/^  SAMPLEBOUND = ztrue/  SAMPLEBOUND = zfalse/' "$MODEL" > "$LOG_DIR/receipt-credit.tex"
sed 's/^  ACCEPTAFTER = 3/  ACCEPTAFTER = 2/' "$MODEL" > "$LOG_DIR/short-window.tex"
sed 's/^  MATCHHUBPID = ztrue/  MATCHHUBPID = zfalse/' "$MODEL" > "$LOG_DIR/stale-pid.tex"
sed 's/^  KEEPLOCALPID = ztrue/  KEEPLOCALPID = zfalse/' "$MODEL" > "$LOG_DIR/second-pid.tex"

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

for model in "$MODEL" "$LOG_DIR/no-reset.tex" "$LOG_DIR/unbounded.tex" "$LOG_DIR/receipt-credit.tex" "$LOG_DIR/short-window.tex" "$LOG_DIR/stale-pid.tex" "$LOG_DIR/second-pid.tex"; do
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
  local errors
  errors="$(sed -nE 's/.*[Tt]otal[[:space:]]+[Ee]rrors[[:space:]]*:[[:space:]]*([0-9]+).*/\1/p' "$log" | tail -n 1)"
  if [[ "$expected" == found ]]; then
    if ! { grep -Eq 'Found[[:space:]]+GOAL[[:space:]]+in[[:space:]]+state' "$log" &&
      [[ "$errors" == 1 ]] &&
      grep -Eq '![[:space:]]*goal_found' "$log"; }; then
      fail "$label expected defect witness" "$log"
    fi
  elif ! { [[ "$errors" == 0 || -z "$errors" ]] &&
    grep -Eq 'No counter[ -]?example found.*ALL states visited' "$log"; }; then
    fail "$label incomplete or unsafe" "$log"
  fi
  echo "PASS: $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
}

# A union of bad states is unreachable iff every constituent invariant holds.
SAFETY='(phase=rsready & age<3) or now>6 or (phase=rsready & process/=rpnew) or (phase=rsready & now>=6) or (phase=rsready & sentAt-observedSince<3) or (phase=rsready & sampledPid/=process) or (phase=rsready & candidate/=process)'
check "$MODEL" I1-I7-safety 'not found' "$SAFETY"
check "$MODEL" deadlock 'not found'
check "$LOG_DIR/no-reset.tex" reconnect-fidelity found 'phase=rsready & age<3'
check "$LOG_DIR/unbounded.tex" deadline-fidelity found 'now>6'
check "$LOG_DIR/receipt-credit.tex" delivery-fidelity found 'phase=rsready & age<3'
check "$LOG_DIR/short-window.tex" short-window-fidelity found 'phase=rsready & sentAt-observedSince<3 & age>=3'
check "$LOG_DIR/stale-pid.tex" stale-pid-fidelity found 'phase=rsready & sampledPid=rpold'
check "$LOG_DIR/second-pid.tex" second-pid-fidelity found 'phase=rsready & process=rpnext'
echo 'PASS: all readiness model checks'
