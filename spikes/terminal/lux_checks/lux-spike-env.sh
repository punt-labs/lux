# Isolated second Lux for the terminal spike: own HOME (hub state, port file, logs),
# own display socket, own hub port. The running Lux (pid 45336) is untouched.
export SPIKE_REPO=~/Coding/punt-labs/lux-terminal-spike
export HOME_REAL="$HOME"
export LUX_SOCKET=/tmp/lux-spike-run/display.sock
export SPIKE_HUB_PORT=8531
spike() { ( cd "$SPIKE_REPO" && HOME=/tmp/lux-spike-home LUX_SOCKET=$LUX_SOCKET \
    UV_CACHE_DIR="$HOME_REAL/.cache/uv" "$SPIKE_REPO/.venv/bin/$@" ); }
