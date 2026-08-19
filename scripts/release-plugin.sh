#!/usr/bin/env bash
set -euo pipefail

# Prepare plugin for release: swap name to prod, remove -dev commands.
# The tagged commit has only prod artifacts; the marketplace cache clones
# from it.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# The shippable plugin surface lives under plugin/, so the marketplace's
# git-subdir source can fetch it alone. COMMANDS_DIR is the plugin's own
# commands directory — the one session-start.sh deploys from, skipping
# *-dev.md — not .claude/commands, which lux has never had.
#
# Two spellings of each path, and they are not interchangeable: the _REL forms
# are pathspecs for `git -C "$REPO_ROOT"`, resolved against the worktree; the
# absolute forms are for python3 and find, which have no repo to resolve
# against and run from whatever directory the caller invoked this script in.
PLUGIN_JSON_REL="plugin/.claude-plugin/plugin.json"
PLUGIN_JSON="${REPO_ROOT}/${PLUGIN_JSON_REL}"
COMMANDS_DIR="${REPO_ROOT}/plugin/commands"

# Preflight: abort if repo has uncommitted changes
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -uno)" ]]; then
  echo "Error: repository has uncommitted changes. Commit or stash before running $(basename "$0")." >&2
  exit 1
fi

# Preflight: both halves of the surface this script edits must be where we
# think they are. A missing commands directory is a broken script, not an empty
# result — skipping it quietly is how the `.claude/commands` typo survived,
# with every run reporting "No -dev commands found" while tagging a release
# that still carried them. Checked here, before the name swap, so a failure
# leaves the worktree untouched rather than half-edited.
if [[ ! -f "$PLUGIN_JSON" ]]; then
  echo "Error: plugin.json not found: ${PLUGIN_JSON}" >&2
  exit 1
fi
if [[ ! -d "$COMMANDS_DIR" ]]; then
  echo "Error: commands directory not found: ${COMMANDS_DIR}" >&2
  echo "       Nothing would be stripped, and the release would ship dev commands." >&2
  exit 1
fi

# Swap plugin name from *-dev to prod
current_name="$(python3 -c "import json; print(json.load(open('${PLUGIN_JSON}'))['name'])")"
prod_name="${current_name%-dev}"

if [[ "$current_name" == "$prod_name" ]]; then
  echo "Plugin name is already '${prod_name}' (no -dev suffix)" >&2
  exit 1
fi

echo "Swapping plugin name: ${current_name} → ${prod_name}"
python3 -c "
import json, pathlib
p = pathlib.Path('${PLUGIN_JSON}')
d = json.loads(p.read_text())
d['name'] = '${prod_name}'
# Release uses installed CLI directly (not uv run)
for srv in d.get('mcpServers', {}).values():
    args = srv.get('args', [])
    if srv.get('command') == 'uv' and len(args) >= 2 and args[0] == 'run':
        srv['command'] = args[1]
        srv['args'] = args[2:]
p.write_text(json.dumps(d, indent=2) + '\n')
"

# Remove -dev commands. find needs the absolute directory, but the results are
# stripped back to repo-relative because they end up as `git rm` pathspecs.
# COMMANDS_DIR was verified in preflight, which is the only guard that can
# work: `find` runs in a process substitution, so its exit status is not this
# shell's and `set -e` would not see a failure here.
dev_files=()
while IFS= read -r -d '' f; do
  dev_files+=("${f#"${REPO_ROOT}/"}")
done < <(find "$COMMANDS_DIR" -name '*-dev.md' -print0)

if [[ ${#dev_files[@]} -eq 0 ]]; then
  echo "No -dev commands found — name swap only"
else
  for f in "${dev_files[@]}"; do
    echo "Removing: $(basename "$f")"
  done
  git -C "$REPO_ROOT" rm "${dev_files[@]}"
fi

git -C "$REPO_ROOT" add "$PLUGIN_JSON_REL"
git -C "$REPO_ROOT" commit --no-verify -m "chore: prepare plugin for release"
