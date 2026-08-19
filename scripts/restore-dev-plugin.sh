#!/usr/bin/env bash
set -euo pipefail

# Restore dev plugin state on main after a release tag.
#
# Usage:
#   scripts/restore-dev-plugin.sh [release-prep-commit]
#
# If no argument is given, auto-detects the last "prepare plugin for release"
# commit and restores from its parent.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Repo-relative, because every use below is a pathspec for a `git -C
# "$REPO_ROOT"` invocation, and a pathspec is resolved against the worktree.
# The plugin/commands/ pathspecs further down are already spelled this way.
PLUGIN_JSON="plugin/.claude-plugin/plugin.json"

# Preflight: abort if repo has uncommitted changes
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -uno)" ]]; then
  echo "Error: repository has uncommitted changes. Commit or stash before running $(basename "$0")." >&2
  exit 1
fi

# Determine the release-prep commit to restore from
RELEASE_PREP_COMMIT="${1:-}"
if [[ -z "$RELEASE_PREP_COMMIT" ]]; then
  RELEASE_PREP_COMMIT="$(git -C "$REPO_ROOT" log -n 1 --grep='prepare plugin for release' --pretty=format:%H || true)"
  if [[ -z "$RELEASE_PREP_COMMIT" ]]; then
    echo "Error: could not find a 'prepare plugin for release' commit. Pass a commit or tag as the first argument." >&2
    exit 1
  fi
fi

echo "Restoring dev state from parent of ${RELEASE_PREP_COMMIT:0:12}"
git -C "$REPO_ROOT" checkout "${RELEASE_PREP_COMMIT}^" -- "$PLUGIN_JSON"

# Restore dev commands if the parent commit had a plugin/commands/ directory.
# This must name the same directory release-plugin.sh strips *-dev.md from.
#
# No -d: `ls-tree -d <commit> -- <dir>/` prints NOTHING. A trailing-slash
# pathspec makes ls-tree recurse into the directory and report its blobs, and
# -d then filters those blobs out, so the guard was silently always false and
# dev commands were never restored. Listing the blobs is the actual test of
# "did this commit have that directory".
#
# The `git add` belongs INSIDE this guard, not after it. Run unconditionally
# with `2>/dev/null || true` it swallowed two different failures: a restore
# that produced nothing to stage, and a genuine `git add` error. Staging only
# what this branch just checked out means a failure here aborts the script
# under `set -e` instead of committing a half-restored state.
if git -C "$REPO_ROOT" ls-tree "${RELEASE_PREP_COMMIT}^" -- plugin/commands/ | grep -q .; then
  git -C "$REPO_ROOT" checkout "${RELEASE_PREP_COMMIT}^" -- plugin/commands/
  git -C "$REPO_ROOT" add plugin/commands/
fi

git -C "$REPO_ROOT" add "$PLUGIN_JSON"
git -C "$REPO_ROOT" commit --no-verify -m "chore: restore dev plugin state [skip ci]"
