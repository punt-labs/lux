#!/usr/bin/env bash
# screenshot.sh — Capture the running lux-display window to a PNG.
#
# Mechanism (Ubuntu/Wayland-with-XWayland, DISPLAY=:0): lux-display is a
# GLFW/OpenGL3 app. GLFW renders it as an XWayland X11 top-level window
# titled "Lux", client instance/class ("Lux" "Lux") — distinct from the
# window manager's decoration frame, which is also titled "Lux" but carries
# the WM's own PID, not luxd-display's. We resolve the real client window by
# matching _NET_WM_PID to the running luxd-display process, so a same-titled
# decoration frame or an unrelated window never gets captured by accident.
#
# `import -window <id>` reads the window's composited pixmap directly (the
# X server's copy of the last-rendered frame), not a live re-render, so an
# occluding window on top of Lux does not blank the capture. The raise step
# below is a safety net for the rare case a compositor withholds the pixmap
# of a fully-obscured window, not a requirement for correctness.
#
# Usage: screenshot.sh [output-path]
#        screenshot.sh --out <output-path>
#
# Prereqs: imagemagick (import), x11-utils (xwininfo, xprop), xdotool,
#          systemd (systemd-inhibit)
set -euo pipefail

die() {
    echo "screenshot.sh: error: $*" >&2
    exit 1
}

require() {
    command -v "$1" >/dev/null 2>&1 || die "missing required tool '$1'"
}

require import
require xwininfo
require xprop
require xdotool
require systemd-inhibit

OUT="${OUT_DEFAULT:-.tmp/lux-screenshot.png}"
case "${1:-}" in
    --out)
        OUT="${2:?--out requires a path}"
        ;;
    "")
        ;;
    *)
        OUT="$1"
        ;;
esac

[[ -n "${DISPLAY:-}" ]] || die "DISPLAY is not set — no X server to capture from"

# The display process is the source of truth for which window is "ours".
# pgrep -x matches the exact binary name lux ships (see pyproject.toml
# [project.scripts]); it must be running before any window can exist.
DISPLAY_PID="$(pgrep -x luxd-display | head -n1 || true)"
[[ -n "$DISPLAY_PID" ]] || die "luxd-display is not running — start it first (e.g. 'lux display start' or 'make restart')"

find_lux_window() {
    local target_pid="$1"
    xwininfo -root -tree 2>/dev/null \
        | awk 'tolower($0) ~ /"lux"/ { print $1 }' \
        | while read -r win_id; do
            local pid
            pid="$(xprop -id "$win_id" _NET_WM_PID 2>/dev/null | awk -F' = ' '/_NET_WM_PID/ {print $2}')"
            if [[ "$pid" == "$target_pid" ]]; then
                echo "$win_id"
                return
            fi
        done
}

WIN_ID="$(find_lux_window "$DISPLAY_PID")"

# Fall back to any top-level window literally titled "Lux" if the PID match
# comes up empty (e.g. a WM that doesn't propagate _NET_WM_PID). This is a
# looser match — it can pick up a decoration frame instead of the real
# client window — so PID-match is always tried first.
if [[ -z "$WIN_ID" ]]; then
    WIN_ID="$(xwininfo -root -tree 2>/dev/null | awk 'tolower($0) ~ /"lux"/ { print $1; exit }')"
fi

[[ -n "$WIN_ID" ]] || die "no window titled 'Lux' found (is lux-display actually rendering a window on DISPLAY=$DISPLAY?)"

# Safety net: raise/activate in case the compositor won't hand back a
# pixmap for a fully-obscured window. import -window reads the composited
# pixmap regardless, so this is belt-and-suspenders, not load-bearing.
xdotool windowactivate --sync "$WIN_ID" >/dev/null 2>&1 || true
xdotool windowraise "$WIN_ID" >/dev/null 2>&1 || true

mkdir -p "$(dirname "$OUT")"
ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

# Wrap the capture so a locked/idle screen (which can blank the composited
# pixmap on some compositors) doesn't corrupt the shot.
systemd-inhibit --what=idle --why="lux screenshot capture" \
    import -window "$WIN_ID" "$ABS_OUT" \
    || die "import -window $WIN_ID failed — window may have closed mid-capture"

[[ -s "$ABS_OUT" ]] || die "capture produced an empty file at $ABS_OUT"

echo "$ABS_OUT"
