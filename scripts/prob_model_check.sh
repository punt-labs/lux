#!/usr/bin/env bash

check_model() {
  local maxint="$1" model="$2" label="$3" expected="$4" goal="${5:-}"
  local log="$LOG_DIR/$label.log"
  local args=("$model" -model_check -v -p DEFAULT_SETSIZE 2 -p MAXINT "$maxint")
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
