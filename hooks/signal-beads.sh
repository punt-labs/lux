#!/usr/bin/env bash
# hooks/signal-beads.sh — PostToolUse Bash thin dispatcher (DES-017).
lux hook post-bash < /dev/stdin 2>/dev/null || true
