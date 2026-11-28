#!/usr/bin/env bash

lux_repo_enabled() {
  local root state
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || return 1
  state="$root/.punt-labs"
  [[ ! -e "$state/lux/opt-out" && ! -e "$state/local/lux/disabled" ]] || return 1
  [[ -e "$state/lux/enabled" || -e "$state/local/lux/enabled" ]] || return 1
  command -v lux >/dev/null 2>&1 || command -v lux-beads >/dev/null 2>&1
}
