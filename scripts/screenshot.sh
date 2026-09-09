#!/usr/bin/env bash
# screenshot.sh — Capture the running lux-display window to a PNG.
#
# Mechanism (Ubuntu/Wayland-with-XWayland, DISPLAY=:0): lux-display is a
# GLFW/OpenGL3 app. GLFW renders it as an XWayland X11 top-level window
# titled "Lux", client instance/class ("Lux" "Lux") — distinct from the
# window manager's decoration frame, which is also titled "Lux" but carries
# the WM's own PID, not luxd-display's. We resolve the real client window by
# matching _NET_WM_PID to a running luxd-display process. Unlike a title
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

mkdir -p "$(dirname "$OUT")"
OUT_DIR="$(cd "$(dirname "$OUT")" && pwd)"
OUT_BASE="$(basename "$OUT")"
ABS_OUT="$OUT_DIR/$OUT_BASE"

# Never leave a prior run's image at the stable output path: every exit
# from here on — including a missing prereq or an unset DISPLAY — must be
# either a fresh, verified capture or no file at all. This has to run
# before every check below, not just before the capture itself.
rm -f "$ABS_OUT"

require import
require convert
require xwininfo
require xprop
require xdotool
require systemd-inhibit

[[ -n "${DISPLAY:-}" ]] || die "DISPLAY is not set — no X server to capture from"

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
# pgrep can return several pids (more than one session/instance running),
# so every candidate is tried below rather than just the first.
mapfile -t DISPLAY_PIDS < <(pgrep -x luxd-display || true)
[[ "${#DISPLAY_PIDS[@]}" -gt 0 ]] || die "luxd-display is not running — start it first (e.g. 'lux display start' or 'make restart')"

find_lux_window() {
    local target_pid="$1"
    local win_id pid
    while read -r win_id; do
        [[ -n "$win_id" ]] || continue
        # `|| true` matters under `set -e`: xprop can exit non-zero if the
        # window vanished mid-scan or lacks _NET_WM_PID, and pipefail would
        # otherwise propagate that through the pipeline into this
        # assignment and abort the whole script instead of letting the
        # loop try the next candidate window.
        pid="$(xprop -id "$win_id" _NET_WM_PID 2>/dev/null | awk -F' = ' '/_NET_WM_PID/ {print $2}' || true)"
        if [[ "$pid" == "$target_pid" ]]; then
            echo "$win_id"
            return 0
        fi
    done < <(printf '%s\n' "$WINDOW_TREE" | awk 'tolower($0) ~ /"lux"/ { print $1 }')
    return 1
}

# Try every luxd-display pid in turn — the first one whose window resolves
# via _NET_WM_PID wins. Used directly as an `if` condition so `set -e`
# doesn't abort on a candidate that doesn't match.
WIN_ID=""
for candidate_pid in "${DISPLAY_PIDS[@]}"; do
    if WIN_ID="$(find_lux_window "$candidate_pid")"; then
        break
    fi
done

# No title-only fallback: a window merely titled "Lux" can be the window
# manager's decoration frame or an unrelated window, and silently capturing
# it would produce false verification evidence — worse than failing here.
[[ -n "$WIN_ID" ]] || die "luxd-display is running (pid(s): ${DISPLAY_PIDS[*]}) but no client window could be resolved via _NET_WM_PID — is it still starting up, or did it just exit?"

# Safety net: raise/activate in case the compositor won't hand back a
# pixmap for a fully-obscured window. import -window reads the composited
# pixmap regardless, so this is belt-and-suspenders, not load-bearing.
xdotool windowactivate --sync "$WIN_ID" >/dev/null 2>&1 || true
xdotool windowraise "$WIN_ID" >/dev/null 2>&1 || true

# Capture to a temp file beside the stable output path, in the same
# format (extension) `import` would otherwise write to $ABS_OUT directly,
# so a failed/interrupted capture or a rejected (black) capture never
# leaves a partial or invalid image at the evidence path. The temp file
# is cleaned up on any exit — success moves it to $ABS_OUT first, which
# clears TMP_OUT so the trap becomes a no-op.
#
# The trap captures $? on entry and re-exits with it explicitly: without
# that, a false `[[ ... ]]` test as cleanup's last command (e.g. when
# TMP_OUT is already empty on the success path) becomes cleanup's own
# exit status, which — because nothing here ever calls `exit` itself —
# silently replaces the script's real exit code with 1 even on success.
TMP_OUT=""
cleanup() {
    local exit_code="$?"
    [[ -n "$TMP_OUT" ]] && rm -f "$TMP_OUT"
    exit "$exit_code"
}
trap cleanup EXIT

if [[ "$OUT_BASE" == *.* ]]; then
    TMP_OUT="$(mktemp --suffix=".${OUT_BASE##*.}" "$OUT_DIR/${OUT_BASE%.*}.XXXXXX")"
else
    TMP_OUT="$(mktemp "$OUT_DIR/${OUT_BASE}.XXXXXX")"
fi

# Wrap the capture so a locked/idle screen (which can blank the composited
# pixmap on some compositors) doesn't corrupt the shot going forward — this
# blocks a NEW idle transition during the capture; it cannot un-blank a
# session that was already locked when the script started, which is exactly
# why the stddev check below exists.
systemd-inhibit --what=idle --why="lux screenshot capture" \
    import -window "$WIN_ID" "$TMP_OUT" \
    || die "import -window $WIN_ID failed — window may have closed mid-capture"

[[ -s "$TMP_OUT" ]] || die "capture produced an empty file"

# A nonempty PNG is not proof of real content: a locked/blanked session can
# still yield a valid, nonempty, uniformly black image. Reject it so a
# false-positive capture never reaches the caller as trustworthy evidence.
STDDEV="$(convert "$TMP_OUT" -format '%[fx:standard_deviation]' info: 2>/dev/null)" \
    || die "could not measure capture content"
if (($(awk -v s="$STDDEV" -v t="$BLACK_STDDEV_THRESHOLD" 'BEGIN { print (s < t) }'))); then
    die "capture is blank/black (stddev=$STDDEV) — is the session locked or the window off-screen?"
fi

mv "$TMP_OUT" "$ABS_OUT"
TMP_OUT=""

echo "$ABS_OUT"
