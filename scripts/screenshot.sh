#!/usr/bin/env bash
# screenshot.sh — Capture the running lux-display window to a PNG.
#
# Mechanism (Ubuntu/Wayland-with-XWayland, DISPLAY=:0): lux-display is a
# GLFW/OpenGL3 app. GLFW renders it as an XWayland X11 top-level window
# titled "Lux", client instance/class ("Lux" "Lux") — distinct from the
# window manager's decoration frame, which is also titled "Lux" but carries
# the WM's own PID, not luxd-display's. We resolve the real client window by
# matching _NET_WM_PID to the running luxd-display process. Unlike a title
# match, PID match cannot be fooled by a same-titled decoration frame or an
# unrelated window — this is a verification tool, so there is no fallback
# that trades correctness for convenience: if the client window can't be
# resolved, we die rather than risk capturing (and validating) the wrong
# window.
#
# `import -window <id>` reads the window's composited pixmap directly (the
# X server's copy of the last-rendered frame), not a live re-render, so an
# occluding window on top of Lux does not blank the capture. The raise step
# below is a safety net for the rare case a compositor withholds the pixmap
# of a fully-obscured window, not a requirement for correctness. Because
# that pixmap can still be black on a *locked* session (systemd-inhibit only
# blocks a new idle transition — it does not un-blank a session already
# locked when this script runs), the post-capture stddev check is what
# actually makes the evidence trustworthy, not the inhibit.
#
# Usage: screenshot.sh [output-path]
#        screenshot.sh --out <output-path>
# Default output path is $SCREENSHOT_OUT if set, else .tmp/lux-screenshot.png.
#
# Prereqs: imagemagick (import, convert), x11-utils (xwininfo, xprop),
#          xdotool, systemd (systemd-inhibit)
set -euo pipefail

# Below this stddev, the capture is treated as a uniform (black/blank)
# buffer rather than real rendered content.
BLACK_STDDEV_THRESHOLD="0.005"

die() {
    echo "screenshot.sh: error: $*" >&2
    exit 1
}

require() {
    command -v "$1" >/dev/null 2>&1 || die "missing required tool '$1'"
}

require import
require convert
require xwininfo
require xprop
require xdotool
require systemd-inhibit

OUT="${SCREENSHOT_OUT:-.tmp/lux-screenshot.png}"
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

mkdir -p "$(dirname "$OUT")"
ABS_OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

# Never leave a prior run's image at the stable output path: every exit
# from here on must be either a fresh, verified capture or no file at all.
rm -f "$ABS_OUT"

# Fail loud, immediately, if the X server itself is unreachable — under
# `set -euo pipefail` a failing xwininfo inside the pipeline below would
# otherwise abort mid-pipe without ever reaching a die() call. The tree is
# queried once here and reused by find_lux_window below, rather than
# queried twice, so the window list can't shift between the reachability
# check and the search.
window_tree() {
    xwininfo -root -tree 2>/dev/null \
        || die "cannot reach the X server on DISPLAY=$DISPLAY (XWayland running?)"
}

WINDOW_TREE="$(window_tree)"

# The display process is the source of truth for which window is "ours".
# pgrep -x matches the exact binary name lux ships (see pyproject.toml
# [project.scripts]); it must be running before any window can exist.
DISPLAY_PID="$(pgrep -x luxd-display | head -n1 || true)"
[[ -n "$DISPLAY_PID" ]] || die "luxd-display is not running — start it first (e.g. 'lux display start' or 'make restart')"

find_lux_window() {
    local target_pid="$1"
    local win_id pid
    while read -r win_id; do
        [[ -n "$win_id" ]] || continue
        pid="$(xprop -id "$win_id" _NET_WM_PID 2>/dev/null | awk -F' = ' '/_NET_WM_PID/ {print $2}')"
        if [[ "$pid" == "$target_pid" ]]; then
            echo "$win_id"
            return 0
        fi
    done < <(printf '%s\n' "$WINDOW_TREE" | awk 'tolower($0) ~ /"lux"/ { print $1 }')
    return 1
}

# `|| true` matters under `set -e`: find_lux_window returns 1 when no
# match is found, and without it the script would exit right here on the
# not-found case instead of reaching the die() below with a clear message.
WIN_ID="$(find_lux_window "$DISPLAY_PID" || true)"

# No title-only fallback: a window merely titled "Lux" can be the window
# manager's decoration frame or an unrelated window, and silently capturing
# it would produce false verification evidence — worse than failing here.
[[ -n "$WIN_ID" ]] || die "luxd-display (pid $DISPLAY_PID) is running but its client window could not be resolved via _NET_WM_PID — is it still starting up, or did it just exit?"

# Safety net: raise/activate in case the compositor won't hand back a
# pixmap for a fully-obscured window. import -window reads the composited
# pixmap regardless, so this is belt-and-suspenders, not load-bearing.
xdotool windowactivate --sync "$WIN_ID" >/dev/null 2>&1 || true
xdotool windowraise "$WIN_ID" >/dev/null 2>&1 || true

# Wrap the capture so a locked/idle screen (which can blank the composited
# pixmap on some compositors) doesn't corrupt the shot going forward — this
# blocks a NEW idle transition during the capture; it cannot un-blank a
# session that was already locked when the script started, which is exactly
# why the stddev check below exists.
systemd-inhibit --what=idle --why="lux screenshot capture" \
    import -window "$WIN_ID" "$ABS_OUT" \
    || die "import -window $WIN_ID failed — window may have closed mid-capture"

[[ -s "$ABS_OUT" ]] || die "capture produced an empty file at $ABS_OUT"

# A nonempty PNG is not proof of real content: a locked/blanked session can
# still yield a valid, nonempty, uniformly black image. Reject it so a
# false-positive capture never reaches the caller as trustworthy evidence.
STDDEV="$(convert "$ABS_OUT" -format '%[fx:standard_deviation]' info: 2>/dev/null)" \
    || { rm -f "$ABS_OUT"; die "could not measure capture content at $ABS_OUT"; }
if (($(awk -v s="$STDDEV" -v t="$BLACK_STDDEV_THRESHOLD" 'BEGIN { print (s < t) }'))); then
    rm -f "$ABS_OUT"
    die "capture is blank/black (stddev=$STDDEV) — is the session locked or the window off-screen?"
fi

echo "$ABS_OUT"
