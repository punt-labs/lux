#!/usr/bin/env bash
# Verify terminal lifecycle safety, deadlock freedom and fidelity counterexamples.
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
LOG_DIR="$(mktemp -d "$ROOT/.tmp/terminal-model.XXXXXX")"
echo "Verification logs: $LOG_DIR"

I1='#n.(n:dom(scene) & sync=synced & not(n:dom(daemon) & daemon(n)=scene(n) & dstate(n)=running) & (n|->scene(n)) /: endedEv)'
I2='#k.(k:dom(bound) & bound(k)/=prj2(NAME,SHELL)(k))'
I3='#(a,b).(a:dom(daemon) & b:dom(daemon) & a/=b & daemon(a)=daemon(b))'
I6='#n.(n:dom(scene) & n:dom(daemon) & daemon(n)=scene(n) & dstate(n)=running & #s.(s:SHELL & (n|->s):dom(replica) & s/=scene(n)))'
I7='sync=synced & createdEv={} & endedEv={} & #n.(n:dom(daemon) & dstate(n)=running & not(n:dom(scene) & scene(n)=daemon(n)))'
I8='#(n,s).(n:NAME & s:SHELL & (n|->s):dom(replica) & not(n:dom(scene) & scene(n)=s))'

fail() {
  echo "FAIL: $1" >&2
  cat "$2" >&2
  exit 1
}

check_model() {
  local model="$1" label="$2" expected="$3" goal="${4:-}"
  local log="$LOG_DIR/${model%.tex}-$label.log"
  local args=("docs/$model" -model_check -p DEFAULT_SETSIZE 2)
  if [[ -n "$goal" ]]; then
    args+=(-nodead -goal "$goal")
  fi
  "$PROBCLI" "${args[@]}" >"$log" 2>&1 || fail "$model $label: ProB failed" "$log"
  if [[ "$expected" == found ]]; then
    if ! { grep -q '^Found GOAL in state id ' "$log" &&
      grep -q '^! Total Errors: 1, Warnings:0$' "$log" &&
      grep -q '^! goal_found$' "$log"; }; then
      fail "$model $label: expected goal not found, or other errors" "$log"
    fi
  else
    if ! { grep -q 'No counter example found. ALL states visited.' "$log" &&
      ! grep -q 'error occurred' "$log"; }; then
      fail "$model $label: unexpected counterexample or incomplete search" "$log"
    fi
  fi
  echo "PASS: $model $label $expected ($(sed -n 's/^States analysed: //p' "$log") states)"
}

models=(
  terminal_lifecycle.tex
  terminal_lifecycle_cache_leak_buggy.tex
  terminal_lifecycle_exit_leak_buggy.tex
  terminal_lifecycle_swap_buggy.tex
)
for model in "${models[@]}"; do
  log="$LOG_DIR/${model%.tex}-fuzz.log"
  "$FUZZ" -t "docs/$model" >"$log" 2>&1 || fail "$model: fuzz failed" "$log"
  echo "PASS: $model fuzz"
done

check_model terminal_lifecycle.tex I1 'not found' "$I1"
check_model terminal_lifecycle.tex I2 'not found' "$I2"
check_model terminal_lifecycle.tex I3 'not found' "$I3"
check_model terminal_lifecycle.tex I6 'not found' "$I6"
check_model terminal_lifecycle.tex I7 'not found' "$I7"
check_model terminal_lifecycle.tex I8 'not found' "$I8"
check_model terminal_lifecycle_cache_leak_buggy.tex I6 found "$I6"
check_model terminal_lifecycle_cache_leak_buggy.tex I8 found "$I8"
check_model terminal_lifecycle_exit_leak_buggy.tex I1 found "$I1"
check_model terminal_lifecycle_swap_buggy.tex I2 found "$I2"
check_model terminal_lifecycle_swap_buggy.tex I6 found "$I6"

for model in "${models[@]}"; do
  if [[ "$model" != terminal_lifecycle.tex ]]; then
    check_model "$model" I7 'not found' "$I7"
  fi
  check_model "$model" I5-deadlock 'not found'
done
echo "PASS: all terminal lifecycle checks"
