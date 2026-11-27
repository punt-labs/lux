#!/usr/bin/env bash
# Verify the client-calls relay model (DES-107): invariants C1 to C5, the lock
# order and deadlock freedom, and the fidelity counterexamples.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -n "${PROBCLI:-}" ]]; then
  command -v "$PROBCLI" >/dev/null || {
    echo "ERROR: PROBCLI is not executable: $PROBCLI" >&2
    exit 1
  }
elif PROBCLI="$(command -v probcli)"; then
  :
elif [[ -x "$HOME/Applications/ProB/probcli" ]]; then
  PROBCLI="$HOME/Applications/ProB/probcli"
else
  echo "ERROR: probcli not found; set PROBCLI, add it to PATH, or install ~/Applications/ProB/probcli." >&2
  exit 1
fi
FUZZ="${FUZZ:-fuzz}"
command -v "$FUZZ" >/dev/null
mkdir -p "$ROOT/.tmp"
LOG_DIR="$(mktemp -d "$ROOT/.tmp/client-calls-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"

C1='#r.(r:REQ & (nout(r)>1 or (r:pend & nout(r)/=0) or (r:dom(sentTo) & r/:pend & nout(r)/=1)))'
C2='#r.(r:dom(accFrom) & accFrom(r)/=sentTo(r))'
C3='#r.(r:dom(outc) & r:pend)'
C4A='#r.(r:pend & sentTo(r)/:live)'
C4B='#(r,c).((r|->c):served & r:dom(sentTo) & sentTo(r)/=c)'
R1='#k.(k:dom(reg) & reg(k)/:live)'
P1='#c.(c:CONN & card({r|r:pend & sentTo(r)=c})>maxPend)'

# Reachability goals: the checks above are not vacuous.
G_PEND='pend/={}'
G_REPLIED='#r.(r:dom(outc) & outc(r)=replied)'
G_REFUSED='#r.(r:dom(outc) & outc(r)=refused)'
G_TIMEDOUT='#r.(r:dom(outc) & outc(r)=timedout)'
G_LOST='#r.(r:dom(outc) & outc(r)=lost)'
G_CAP='#c.(c:CONN & card({r|r:pend & sentTo(r)=c})=maxPend)'

# C5: whenever a call is pending the deadline is enabled.
PP='#r.(r:pend)'
C5='AG({'"$PP"'} => EF(e(Timeout)))'

# The lock model's flags.
L_ORDER='orderBroken=fset'
L_WAIT='waitHeld=fset'
L_WAKE='wakeHeld=fset'

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

trace_len() {
  sed -n 's/^\*\*\* TRACE (length=\([0-9]*\)).*/\1/p' "$1"
}

# check_model MODEL LABEL EXPECTED [GOAL]: the state models, carriers of 2.
check_model() {
  local model="$1" label="$2" expected="$3" goal="${4:-}" size="${5:-2}"
  local log="$LOG_DIR/${model%.tex}-$label.log"
  local args=("docs/$model" -model_check -p DEFAULT_SETSIZE "$size")
  if [[ -n "$goal" ]]; then
    args+=(-nodead -goal "$goal")
  fi
  "$PROBCLI" "${args[@]}" >"$log" 2>&1 || {
    if [[ "$expected" != found ]]; then fail "$model $label: ProB failed" "$log"; fi
  }
  if [[ "$expected" == found ]]; then
    if ! { grep -q '^Found GOAL in state id ' "$log" &&
      grep -q '^! Total Errors: 1, Warnings:0$' "$log" &&
      grep -q '^! goal_found$' "$log"; }; then
      fail "$model $label: expected goal not found, or other errors" "$log"
    fi
    echo "PASS: $model $label found (trace length $(trace_len "$log"), $(sed -n 's/^States analysed: //p' "$log") states)"
  else
    if ! { grep -q 'No counter example found. ALL states visited.' "$log" &&
      ! grep -q 'error occurred' "$log"; }; then
      fail "$model $label: unexpected counterexample or incomplete search" "$log"
    fi
    echo "PASS: $model $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
  fi
}

# check_ctl MODEL FORMULA EXPECTED: C5, the deadline property.
check_ctl() {
  local model="$1" formula="$2" expected="$3" label="${4:-C5}"
  local log="$LOG_DIR/${model%.tex}-$label.log"
  "$PROBCLI" "docs/$model" -p DEFAULT_SETSIZE 2 -ctlformula "$formula" >"$log" 2>&1 || true
  if [[ "$expected" == holds ]]; then
    grep -q '^CTL Formula TRUE' "$log" || fail "$model $label: expected the CTL formula to hold" "$log"
  else
    grep -q '^Formula FALSE' "$log" || fail "$model $label: expected a counterexample" "$log"
  fi
  echo "PASS: $model $label $expected"
}

# check_locks MODEL LABEL EXPECTED THREADS [GOAL]: the lock model.  With no
# goal the search is the deadlock check; EXPECTED is "not found" or "deadlock".
check_locks() {
  local model="$1" label="$2" expected="$3" threads="$4" goal="${5:-}"
  local log="$LOG_DIR/${model%.tex}-$label.log"
  local args=("docs/$model" -model_check -p MAX_OPERATIONS 200 -card T "$threads")
  if [[ -n "$goal" ]]; then
    args+=(-nodead -bf -goal "$goal")
  else
    args+=(-coverage)
  fi
  "$PROBCLI" "${args[@]}" >"$log" 2>&1 || true
  case "$expected" in
    found)
      if ! { grep -q '^Found GOAL in state id ' "$log" && grep -q '^! goal_found$' "$log"; }; then
        fail "$model $label: expected goal not found" "$log"
      fi
      echo "PASS: $model $label found (trace length $(trace_len "$log"))"
      ;;
    deadlock)
      # ProB prints "deadlocked:N" in every run's summary, so the word alone
      # proves nothing; the witness is the error line and its marker.
      if ! { grep -q '^Found "deadlock" error in state id ' "$log" && grep -q '^! deadlock$' "$log"; }; then
        fail "$model $label: expected a deadlock" "$log"
      fi
      echo "PASS: $model $label deadlock (trace length $(trace_len "$log"))"
      ;;
    *)
      grep -q 'No counter example found. ALL states visited.' "$log" ||
        fail "$model $label: unexpected counterexample or incomplete search" "$log"
      if [[ -z "$goal" ]]; then
        grep -q 'deadlocked:0' "$log" || fail "$model $label: deadlocked states reported" "$log"
      fi
      echo "PASS: $model $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
      ;;
  esac
}

state_models=(
  client_calls.tex
  client_calls_replay_on_reconnect_buggy.tex
  client_calls_reply_any_session_buggy.tex
  client_calls_no_deadline_buggy.tex
  client_calls_session_end_keeps_pending_buggy.tex
)
lock_models=(
  client_calls_locks.tex
  client_calls_locks_inverted_buggy.tex
  client_calls_locks_wait_held_buggy.tex
  client_calls_locks_wake_held_buggy.tex
)
for model in "${state_models[@]}" "${lock_models[@]}"; do
  log="$LOG_DIR/${model%.tex}-fuzz.log"
  "$FUZZ" -t "docs/$model" >"$log" 2>&1 || fail "$model: fuzz failed" "$log"
  echo "PASS: $model fuzz"
done

# The intact model: every invariant holds, and each is reachable-sensitive.
check_model client_calls.tex C1 'not found' "$C1"
check_model client_calls.tex C2 'not found' "$C2"
check_model client_calls.tex C3 'not found' "$C3"
check_model client_calls.tex C4a 'not found' "$C4A"
check_model client_calls.tex C4b 'not found' "$C4B"
check_model client_calls.tex R1 'not found' "$R1"
check_model client_calls.tex P1 'not found' "$P1"
check_model client_calls.tex D-deadlock 'not found'
check_ctl client_calls.tex "$C5" holds
# Non-vacuity: pending calls, every outcome, the limit, a refused
# registration and a supersession are all reachable.
check_model client_calls.tex reach-pending found "$G_PEND"
check_model client_calls.tex reach-replied found "$G_REPLIED"
check_model client_calls.tex reach-refused found "$G_REFUSED"
check_model client_calls.tex reach-timedout found "$G_TIMEDOUT"
check_model client_calls.tex reach-lost found "$G_LOST"
check_model client_calls.tex reach-cap found "$G_CAP"
check_ctl client_calls.tex 'EF(e(RegisterRefused))' holds reach-refused-registration
check_ctl client_calls.tex 'EF(e(Supersede))' holds reach-supersede

# Fidelity: each variant fails exactly the invariant it names.
check_model client_calls_replay_on_reconnect_buggy.tex C4b found "$C4B"
check_model client_calls_replay_on_reconnect_buggy.tex C4a found "$C4A"
check_model client_calls_reply_any_session_buggy.tex C2 found "$C2"
check_ctl client_calls_no_deadline_buggy.tex "$C5" violated
check_model client_calls_session_end_keeps_pending_buggy.tex C4a found "$C4A"

# The variants break only what they name.
for model in client_calls_replay_on_reconnect_buggy.tex \
  client_calls_reply_any_session_buggy.tex \
  client_calls_no_deadline_buggy.tex \
  client_calls_session_end_keeps_pending_buggy.tex; do
  check_model "$model" C1 'not found' "$C1"
  check_model "$model" C3 'not found' "$C3"
  check_model "$model" R1 'not found' "$R1"
  check_model "$model" P1 'not found' "$P1"
done
check_model client_calls_replay_on_reconnect_buggy.tex C2 'not found' "$C2"
check_model client_calls_reply_any_session_buggy.tex C4a 'not found' "$C4A"
check_model client_calls_reply_any_session_buggy.tex C4b 'not found' "$C4B"
check_model client_calls_no_deadline_buggy.tex C2 'not found' "$C2"
check_model client_calls_no_deadline_buggy.tex C4a 'not found' "$C4A"
check_model client_calls_no_deadline_buggy.tex C4b 'not found' "$C4B"
check_model client_calls_session_end_keeps_pending_buggy.tex C2 'not found' "$C2"
check_model client_calls_session_end_keeps_pending_buggy.tex C4b 'not found' "$C4B"

# The lock order: store, registry, table.  Deadlock freedom at two and three
# threads, and the order and C6 flags never set.
check_locks client_calls_locks.tex deadlock-2 'not found' 2
check_locks client_calls_locks.tex deadlock-3 'not found' 3
check_locks client_calls_locks.tex order 'not found' 3 "$L_ORDER"
check_locks client_calls_locks.tex c6-wait 'not found' 3 "$L_WAIT"
check_locks client_calls_locks.tex c6-wake 'not found' 3 "$L_WAKE"
check_locks client_calls_locks_inverted_buggy.tex deadlock-2 deadlock 2
check_locks client_calls_locks_inverted_buggy.tex order found 3 "$L_ORDER"
check_locks client_calls_locks_wait_held_buggy.tex c6-wait found 3 "$L_WAIT"
check_locks client_calls_locks_wake_held_buggy.tex c6-wake found 3 "$L_WAKE"
echo "PASS: all client calls checks"
