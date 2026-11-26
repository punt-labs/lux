#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -s)/$(uname -m) != Linux/x86_64 || $# != 1 || ! -f $1 || -L $1 ]]; then
    printf 'On Linux x86-64: %s HANDOFF_RUNTIME_ARCHIVE\n' "$0" >&2
    exit 2
fi
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
sha=$(python3 -I - "$repo/.punt-labs/ethos/checks/snapshots/python-oo.yaml" <<'PY'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as sidecar:
        pin = json.load(sidecar)["checks"]["gate"]["runtime"]["platforms"]["linux-amd64"]["sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError
except (KeyError, OSError, TypeError, ValueError):
    sys.exit("Invalid Lux snapshot sidecar: expected a JSON-formatted SHA-256 pin.")
print(pin)
PY
)

umask 077
store=$HOME/.punt-labs/ethos/runtimes
mkdir -p -- "$store"
if [[ ! -O $store || -L $store ]]; then
    echo 'The Ethos runtime store must be owned by the current user and not a symlink.' >&2
    exit 1
fi
chmod 700 -- "$store"
archive=$store/$sha.tar.gz
if [[ -f $archive && ! -L $archive ]] && printf '%s  %s\n' "$sha" "$archive" | sha256sum --check --status; then
    printf '%s\n' "$archive"
    exit 0
fi

candidate=$(mktemp "$store/.lux-runtime.XXXXXX")
trap 'rm -f -- "$candidate"' EXIT
cp -- "$1" "$candidate"
if ! printf '%s  %s\n' "$sha" "$candidate" | sha256sum --check --status; then
    printf 'Lux handoff runtime checksum mismatch (expected %s).\n' "$sha" >&2
    exit 1
fi
mv -T -- "$candidate" "$archive"
printf '%s\n' "$archive"
