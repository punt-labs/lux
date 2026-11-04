#!/usr/bin/env bash
# Verify `lux enable` (src/punt_lux/claude_permissions.py) allows a Skill(<name>) rule for
# every command in plugin/commands/*.md. Drift here causes unexplained
# permission prompts on first use. Fast (no network; standard shell utilities).
set -euo pipefail
shopt -s nullglob

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/src/punt_lux/claude_permissions.py"
COMMANDS_DIR="$ROOT/plugin/commands"

if [[ ! -f "$HOOK" ]]; then
  echo "error: $HOOK not found" >&2
  exit 2
fi
if [[ ! -d "$COMMANDS_DIR" ]]; then
  echo "error: $COMMANDS_DIR not found" >&2
  exit 2
fi

# Commands deployed to ~/.claude/commands (skip *-dev.md, matching the
# hook's deployment logic). Uses `while read` for Bash 3.2 compatibility
# (stock macOS) — mapfile is a Bash 4+ builtin.
COMMANDS=()
while IFS= read -r name; do
  COMMANDS+=("$name")
done < <(
  for f in "$COMMANDS_DIR"/*.md; do
    name="$(basename "$f" .md)"
    [[ "$name" == *-dev ]] && continue
    printf '%s\n' "$name"
  done | sort
)

if [[ ${#COMMANDS[@]} -eq 0 ]]; then
  echo "error: no *.md files found in $COMMANDS_DIR — expected at least one command" >&2
  exit 2
fi

# Skill() rules declared in LUX_RULES.
ALLOWED=()
while IFS= read -r allow; do
  ALLOWED+=("$allow")
done < <(grep -oE 'Skill\([a-z_.-]+\)' "$HOOK" | sed -E 's/Skill\(|\)//g' | sort -u)

missing=()
for cmd in "${COMMANDS[@]}"; do
  found=0
  for allow in "${ALLOWED[@]}"; do
    [[ "$cmd" == "$allow" ]] && { found=1; break; }
  done
  [[ $found -eq 0 ]] && missing+=("$cmd")
done

extra=()
for allow in "${ALLOWED[@]}"; do
  found=0
  for cmd in "${COMMANDS[@]}"; do
    [[ "$cmd" == "$allow" ]] && { found=1; break; }
  done
  [[ $found -eq 0 ]] && extra+=("$allow")
done

status=0
if [[ ${#missing[@]} -gt 0 ]]; then
  echo "error: plugin/commands/*.md has no matching Skill() permission in src/punt_lux/claude_permissions.py:" >&2
  for m in "${missing[@]}"; do echo "  - $m" >&2; done
  status=1
fi
if [[ ${#extra[@]} -gt 0 ]]; then
  echo "error: src/punt_lux/claude_permissions.py grants Skill() for commands that do not exist:" >&2
  for e in "${extra[@]}"; do echo "  - $e" >&2; done
  status=1
fi

if [[ $status -eq 0 ]]; then
  echo "skill-permissions: ${#COMMANDS[@]} commands, ${#ALLOWED[@]} Skill() rules — in sync"
fi
exit $status
