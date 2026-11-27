#!/usr/bin/env bash
# Verify the retry-token memory model: invariants, reachability, deadlock freedom and fidelity counterexamples.
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
LOG_DIR="$(mktemp -d "$ROOT/.tmp/new-tokens-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"


T1='#t.(t:TOK & nforks(t)>1)'
T2='#t.(t:dom(held) & t/:ran(recent))'
T3='#t.(t:ran(recent) & nforks(t)>0 & t/:dom(held))'
T4='#t.(t:dom(held) & nforks(t)=0)'
T5='card(dom(held))>2'

# Reachability: each is a state the intact model must reach, so the
# invariants above are not vacuous.
# A capacity eviction, and nothing else: a token with a live process that is not a
# survivor, whose fork count is back to zero, and which is not held. A restart
# kills every non-survivor and a launch counts a fork, so only the cap can leave
# a token in this state. A survivor-only token does not satisfy it.
RV_EVICT='#t.(t:TOK & lv(t)-surv(t)>0 & nforks(t)=0 & t/:dom(held))'
# The retry of an evicted token launches again: two live non-survivor processes
# of one token, one counted fork, and a held entry. T1 forbids this without an
# eviction in between.
RV_RETRY='#t.(lv(t)-surv(t)=2 & nforks(t)=1 & t:dom(held))'
RV_UNREC='#t.(t:dom(held) & t/:bound & nforks(t)=1)'
RV_EXITED='#t.(t:bound & t:dom(held) & lv(t)=0)'
RV_FULL='#(a,b).(a:dom(held) & b:dom(held) & a/=b)'
RV_SURV='#t.(surv(t)>0 & lv(t)=2)'
# The last restart ended a shell whose token once had a survivor: the token is in
# kas, nothing has been admitted since (recent is empty), and it has no live shell.
RV_KAS='#t.(t:kas & lv(t)=0 & recent=<>)'
# T7: after a restart, before any admission, no token in kas has a live shell.
T7='#t.(t:kas & lv(t)>0 & recent=<>)'

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

# ProB prints "! Total Errors: N, Warnings: M" (or "Warnings:M") when it reports
# errors, and spells the clean verdict "No counter example found" or
# "No counterexample found". A clean run prints no error line at all.
NO_CE='No counter ?-?example found'
errors_reported() {
  grep -Eq '^! Total Errors: *[1-9]' "$1"
}

check_model() {
  local model="$1" label="$2" expected="$3" goal="${4:-}" size="${5:-3}"
  local log="$LOG_DIR/${model%.tex}-$label.log"
  local args=("docs/$model" -model_check -p DEFAULT_SETSIZE "$size" -p SYMMETRY_MODE hash)
  if [[ -n "$goal" ]]; then
    args+=(-nodead -goal "$goal")
  fi
  local status=0
  "$PROBCLI" "${args[@]}" >"$log" 2>&1 || status=$?
  if [[ "$expected" == found ]]; then
    # A found goal is the one error ProB reports: exactly one, no warnings.
    if ! { grep -q '^Found GOAL in state id ' "$log" &&
      grep -Eq '^! Total Errors: *1, *Warnings: *0$' "$log" &&
      grep -q '^! goal_found$' "$log"; }; then
      fail "$model $label: expected goal not found, or other errors" "$log"
    fi
  else
    [[ "$status" -eq 0 ]] || fail "$model $label: ProB failed" "$log"
    if errors_reported "$log"; then
      fail "$model $label: ProB reported model-check errors" "$log"
    fi
    if ! { grep -Eq "$NO_CE"'\. ALL states visited\.' "$log" &&
      ! grep -q 'error occurred' "$log"; }; then
      fail "$model $label: unexpected counterexample or incomplete search" "$log"
    fi
  fi
  echo "PASS: $model $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
}

# Tokens are interchangeable (no operation orders them), so ProB's hash symmetry
# reduction over the deferred set TOK is sound and cuts the intact model from
# 38908 to 6524 states.
# An operation is enabled in some reachable state, optionally together with a state predicate.
check_enabled() {
  local model="$1" label="$2" formula="$3"
  local log="$LOG_DIR/${model%.tex}-$label.log"
  "$PROBCLI" "docs/$model" -p DEFAULT_SETSIZE 3 -p SYMMETRY_MODE hash -ctlformula "$formula" >"$log" 2>&1 || true
  grep -q '^CTL Formula TRUE' "$log" || fail "$model $label: operation never enabled" "$log"
  echo "PASS: $model $label reachable"
}

variants=(
  request_counted_eviction
  entry_after_spawn
  entry_kept_after_failed_fork
  evicted_not_restored
  label_guard
)
models=(new_tokens.tex)
for v in "${variants[@]}"; do
  models+=("new_tokens_${v}_buggy.tex")
done
for model in "${models[@]}"; do
  log="$LOG_DIR/${model%.tex}-fuzz.log"
  "$FUZZ" -t "docs/$model" >"$log" 2>&1 || fail "$model: fuzz failed" "$log"
  echo "PASS: $model fuzz"
done

# The fidelity variants first: each must reach the violation it is named for.
check_model new_tokens_request_counted_eviction_buggy.tex T3 found "$T3"
check_model new_tokens_request_counted_eviction_buggy.tex T1 found "$T1"
check_model new_tokens_entry_after_spawn_buggy.tex T3 found "$T3"
check_model new_tokens_entry_after_spawn_buggy.tex T1 found "$T1"
check_model new_tokens_entry_kept_after_failed_fork_buggy.tex T4 found "$T4"
check_model new_tokens_entry_kept_after_failed_fork_buggy.tex T2 found "$T2"
check_model new_tokens_evicted_not_restored_buggy.tex T3 found "$T3"
check_model new_tokens_evicted_not_restored_buggy.tex T1 found "$T1"
check_model new_tokens_label_guard_buggy.tex T1 found "$T1"

# The intact model: every invariant holds over all states.
check_model new_tokens.tex T1 'not found' "$T1"
check_model new_tokens.tex T2 'not found' "$T2"
check_model new_tokens.tex T3 'not found' "$T3"
check_model new_tokens.tex T4 'not found' "$T4"
check_model new_tokens.tex T5 'not found' "$T5"
check_model new_tokens.tex T7 'not found' "$T7"
check_model new_tokens.tex deadlock 'not found'

# Reachability in the intact model.
check_model new_tokens.tex R-evicted-live found "$RV_EVICT"
check_model new_tokens.tex R-unrecorded found "$RV_UNREC"
check_model new_tokens.tex R-exited-held found "$RV_EXITED"
check_model new_tokens.tex R-memory-full found "$RV_FULL"
check_model new_tokens.tex R-survivor-retry found "$RV_SURV"
check_enabled new_tokens.tex R-repeat-bound 'EF(e(RepeatBound))'
check_enabled new_tokens.tex R-repeat-unrecorded 'EF(e(RepeatUnrecorded))'
check_enabled new_tokens.tex R-refuse-label 'EF(e(RefuseLabel))'
check_enabled new_tokens.tex R-refuse-config 'EF(e(RefuseConfig))'
check_enabled new_tokens.tex R-fork-fails 'EF(e(LaunchForkFails))'
check_enabled new_tokens.tex R-fork-fails-full 'EF({'"$RV_FULL"'} & e(LaunchForkFails))'
check_model new_tokens.tex R-retry-after-eviction found "$RV_RETRY"
check_model new_tokens.tex R-survivor-gone-restart found "$RV_KAS"
check_enabled new_tokens.tex R-exit-survivor 'EF(e(ExitSurvivor))'
check_enabled new_tokens.tex R-restart-survivor 'EF(e(RestartSurvivor))'
check_enabled new_tokens.tex R-restart-clean 'EF({'"$RV_UNREC"'} & e(RestartClean))'
echo "PASS: all new-token model checks"
