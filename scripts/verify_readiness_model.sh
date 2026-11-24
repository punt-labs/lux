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

# shellcheck source=scripts/prob_model_check.sh
source "$ROOT/scripts/prob_model_check.sh"

# A union of bad states is unreachable iff every constituent invariant holds.
SAFETY='(phase=rsready & age<3) or now>6 or (phase=rsready & process/=rpnew) or (phase=rsready & now>=6) or (phase=rsready & sentAt-observedSince<3) or (phase=rsready & sampledPid/=process) or (phase=rsready & candidate/=process)'
check_model 7 "$MODEL" I1-I7-safety 'not found' "$SAFETY"
check_model 7 "$MODEL" deadlock 'not found'
check_model 7 "$LOG_DIR/no-reset.tex" reconnect-fidelity found 'phase=rsready & age<3'
check_model 7 "$LOG_DIR/unbounded.tex" deadline-fidelity found 'now>6'
check_model 7 "$LOG_DIR/receipt-credit.tex" delivery-fidelity found 'phase=rsready & age<3'
check_model 7 "$LOG_DIR/short-window.tex" short-window-fidelity found 'phase=rsready & sentAt-observedSince<3 & age>=3'
check_model 7 "$LOG_DIR/stale-pid.tex" stale-pid-fidelity found 'phase=rsready & sampledPid=rpold'
check_model 7 "$LOG_DIR/second-pid.tex" second-pid-fidelity found 'phase=rsready & process=rpnext'
echo 'PASS: all readiness model checks'
