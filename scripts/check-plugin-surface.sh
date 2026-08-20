#!/usr/bin/env bash
# Verify the shippable plugin surface does not reach outside itself.
#
# A marketplace install fetches ONLY the surface directory (Claude Code's
# git-subdir source is a blobless clone plus `sparse-checkout set --cone
# plugin`), so any path that resolves outside it — or to a file that simply is
# not there — is a SILENT break: the hook or command runs, finds nothing, and
# the feature is quietly absent on every installed copy while working perfectly
# in the source tree. This gate is the reason that cannot happen twice.
#
# Usage: check-plugin-surface.sh [surface-dir]   (default: <repo>/plugin)
#
# The checks live in tools/plugin_surface.py so they are a real, lintable module
# rather than logic embedded in a shell string; this wrapper is the stable CLI
# the Makefile and CI call, and the shape the sibling repos share.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/tools/plugin_surface.py" "$@"
