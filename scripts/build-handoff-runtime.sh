#!/usr/bin/env bash
set -euo pipefail

if [[ $(uname -s)/$(uname -m) != Linux/x86_64 || $# != 1 || ! -d $1 ]]; then
    printf 'On Linux x86-64: %s OUTPUT_DIRECTORY\n' "$0" >&2
    exit 2
fi

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
output=$(cd -- "$1" && pwd -P)
work=$(mktemp -d "$output/.lux-runtime.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
runtime=$work/runtime
mkdir -p "$runtime/bin" "$runtime/cache/uv" "$runtime/licenses" "$work/home" "$work/tmp" "$work/z-spec"

uv_tool=$(command -v uv)
uv_version=$("$uv_tool" --version)
if [[ ! $uv_version =~ ^uv\ (0\.13\.[0-9]+)([[:space:]]|$) ]]; then
    printf 'Use a uv 0.13 release with the embedded uv_build backend; got %s.\n' "$uv_version" >&2
    exit 1
fi
uv_version=${BASH_REMATCH[1]}
install -m 0755 "$uv_tool" "$runtime/bin/uv"
node_tool=$(node -p 'process.execPath')
node_home=$(dirname -- "$(dirname -- "$node_tool")")
mkdir -p "$runtime/node/bin" "$runtime/node/lib/node_modules"
install -m 0755 "$node_tool" "$runtime/node/bin/node"
cp -RP -- "$node_home/lib/node_modules/npm" "$runtime/node/lib/node_modules/npm"
ln -s ../lib/node_modules/npm/bin/npm-cli.js "$runtime/node/bin/npm"
ln -s ../lib/node_modules/npm/bin/npx-cli.js "$runtime/node/bin/npx"
install -m 0644 "$node_home/LICENSE" "$runtime/licenses/node-LICENSE"

download() {
    curl --proto '=https' --proto-redir '=https' --fail --silent --show-error \
        --location --connect-timeout 20 --max-time 300 --output "$2" "$1"
}
for notice in LICENSE-APACHE LICENSE-MIT; do
    download "https://raw.githubusercontent.com/astral-sh/uv/$uv_version/$notice" "$runtime/licenses/uv-$notice"
done

python_tool=$(uv --no-config python find --managed-python --no-project --system 3.13)
python_home=$("$python_tool" -I -c 'import sys; print(sys.base_prefix)')
cp -RP -- "$python_home" "$runtime/python"
python_tool=$runtime/python/bin/python3
isolated=(env -i "HOME=$work/home" "TMPDIR=$work/tmp"
    "PATH=$runtime/bin:$runtime/node/bin:$runtime/python/bin:/usr/bin:/bin" LC_ALL=C TZ=UTC)
"${isolated[@]}" "UV_PYTHON=$python_tool" UV_PYTHON_DOWNLOADS=never \
    "UV_CACHE_DIR=$runtime/cache/uv" "UV_PROJECT_ENVIRONMENT=$work/venv" UV_LINK_MODE=copy \
    uv --directory "$repo" sync --locked --extra display --no-install-workspace >&2
"${isolated[@]}" "UV_PYTHON=$python_tool" UV_PYTHON_DOWNLOADS=never \
    "UV_CACHE_DIR=$runtime/cache/uv" "UV_PROJECT_ENVIRONMENT=$work/doclint-venv" UV_LINK_MODE=copy \
    uv --directory "$repo" sync --locked --only-group doclint --no-install-workspace >&2
"${isolated[@]}" npm_config_ignore_scripts=true npm_config_audit=false npm_config_fund=false \
    npm install --global --prefix "$runtime/node" markdownlint-cli2@0.24.2 pyright@1.1.414 >&2

models=$repo/.github/workflows/models.yml
prob_version=$(sed -n 's/^      PROB_VERSION: "\([^"]*\)"$/\1/p' "$models")
prob_sha=$(sed -n 's/^      PROB_SHA256_LINUX: "\([^"]*\)"$/\1/p' "$models")
z_spec_ref=$(sed -n '/repository: punt-labs\/z-spec/{n;s/^ *ref: //p;}' "$models")
if [[ ! $prob_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ || ! $prob_sha =~ ^[0-9a-f]{64}$ || ! $z_spec_ref =~ ^[0-9a-f]{40}$ ]]; then
    echo 'Cannot read the pinned ProB and z-spec versions from models.yml.' >&2
    exit 1
fi
download "https://codeload.github.com/punt-labs/z-spec/tar.gz/$z_spec_ref" "$work/z-spec.tar.gz"
tar -xzf "$work/z-spec.tar.gz" --strip-components=1 -C "$work/z-spec"
(cd "$work/z-spec" && "${isolated[@]}" bash install.sh --fuzz-only) >&2
install -m 0755 "$work/home/.local/bin/fuzz" "$runtime/bin/fuzz"
install -Dm 0644 "$work/home/.local/lib/fuzzlib" "$runtime/lib/fuzzlib"
fuzz_ref=$(sed -n 's/^FUZZ_REF="\([0-9a-f]*\)"$/\1/p' "$work/z-spec/install.sh")
download "https://raw.githubusercontent.com/Spivoxity/fuzz/$fuzz_ref/README.md" "$runtime/licenses/fuzz-README.md"

download "https://stups.hhu-hosting.de/downloads/prob/tcltk/releases/$prob_version/ProB.linux64.tar.gz" "$work/prob.tar.gz"
printf '%s  %s\n' "$prob_sha" "$work/prob.tar.gz" | sha256sum --check >&2
mkdir "$runtime/prob"
tar -xzf "$work/prob.tar.gz" --strip-components=1 -C "$runtime/prob"
test -x "$runtime/prob/probcli"

jre_asset=OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz
download "https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/$jre_asset" "$work/jre.tar.gz"
printf '%s  %s\n' aeab55d064a1a27a3744b0880b9b414077b4ed2b1790817eea3df60aec946431 "$work/jre.tar.gz" | sha256sum --check >&2
mkdir "$runtime/java"
tar -xzf "$work/jre.tar.gz" --strip-components=1 -C "$runtime/java"
test -x "$runtime/java/bin/java"

LC_ALL=C tar --sort=name --format=gnu --mtime=@0 --numeric-owner --owner=0 --group=0 \
    --hard-dereference -C "$runtime" -cf - bin cache java lib licenses node prob python \
    | gzip -n > "$work/runtime.tar.gz"
sha=$(sha256sum < "$work/runtime.tar.gz")
archive=$output/${sha%% *}.tar.gz
mv -- "$work/runtime.tar.gz" "$archive"
printf '%s\n' "$archive"
