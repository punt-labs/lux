#!/usr/bin/env bash
# Tier 1/2 Python standards audit — runs all grep and static checks from
# python-tooling-enforcement.md without requiring per-command approval.
# Usage: bash tools/audit-python-standards.sh [src_dir]
# Default src_dir: src/punt_lux

set -uo pipefail

SRC="${1:-src/punt_lux}"
FAIL_FILE=$(mktemp)
WARN_FILE=$(mktemp)
PASS_FILE=$(mktemp)
trap 'rm -f "$FAIL_FILE" "$WARN_FILE" "$PASS_FILE"' EXIT

_pass() { echo "  ✓ $1"; echo x >> "$PASS_FILE"; }
_fail() { echo "  ✗ $1"; echo x >> "$FAIL_FILE"; }
_warn() { echo "  ~ $1"; echo x >> "$WARN_FILE"; }
_section() { echo; echo "── $1 ──"; }

# ── PY-TS-1: from __future__ import annotations ──────────────────────────────
_section "PY-TS-1: from __future__ import annotations (every .py)"
missing=$(grep -rL "from __future__ import annotations" --include="*.py" "$SRC" 2>/dev/null | sort)
if [ -z "$missing" ]; then
    _pass "All .py files have the future import"
else
    while IFS= read -r f; do _fail "missing: $f"; done <<< "$missing"
fi

# ── PY-CC-1: No __init__ in non-dataclass classes ────────────────────────────
_section "PY-CC-1: No __init__ in non-dataclass classes"
hits=$(grep -rn "def __init__" --include="*.py" "$SRC" 2>/dev/null | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No __init__ definitions found"
else
    while IFS= read -r h; do _warn "verify is dataclass-generated: $h"; done <<< "$hits"
fi

# ── PY-EN-1: No public attributes (self.name without underscore) ──────────────
_section "PY-EN-1: No public instance attributes"
hits=$(grep -Pn "self\.[a-z][a-zA-Z_0-9]*\s*=" --include="*.py" -r "$SRC" 2>/dev/null \
    | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No public attributes detected"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── PY-CS-7: __all__ in every __init__.py ────────────────────────────────────
_section "PY-CS-7: __all__ in every __init__.py"
missing=$(grep -rL "__all__" --include="__init__.py" "$SRC" 2>/dev/null | sort)
if [ -z "$missing" ]; then
    _pass "All __init__.py files define __all__"
else
    while IFS= read -r f; do _fail "missing __all__: $f"; done <<< "$missing"
fi

# ── PY-TS-8: No Optional[] or Union[] ────────────────────────────────────────
_section "PY-TS-8: No Optional[]/Union[] — use X|Y syntax"
hits=$(grep -Pn "\bOptional\[|\bUnion\[" --include="*.py" -r "$SRC" 2>/dev/null \
    | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No old-style union syntax"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── PY-EH-2: No bare raise Exception ─────────────────────────────────────────
_section "PY-EH-2: No bare raise Exception"
hits=$(grep -rn "raise Exception\b" --include="*.py" "$SRC" 2>/dev/null | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No bare raise Exception"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── PY-TS-10: No hasattr() ────────────────────────────────────────────────────
_section "PY-TS-10: No hasattr() — use Protocol/isinstance"
hits=$(grep -rn "hasattr(" --include="*.py" "$SRC" 2>/dev/null | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No hasattr() calls"
else
    while IFS= read -r h; do _warn "(OK at boundaries, not in core) $h"; done <<< "$hits"
fi

# ── PL-PP-2: No unittest.mock in src/ ────────────────────────────────────────
_section "PL-PP-2: No unittest.mock in production code"
hits=$(grep -rn "unittest\.mock\|from mock import" --include="*.py" "$SRC" 2>/dev/null \
    | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No mock imports in src/"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── PL-PA-6: No print() in MCP server ────────────────────────────────────────
_section "PL-PA-6: No print() in MCP/server code (stdout reserved for stdio transport)"
hits=$(grep -rn "print(" --include="*.py" "$SRC" 2>/dev/null \
    | grep -v "__main__" | grep -v "font.test" | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No print() outside __main__"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── PY-CC-6: @dataclass must have frozen=True ────────────────────────────────
# Checks the decorator line; multi-line decorators still show frozen on that line.
_section "PY-CC-6: @dataclass must use frozen=True, slots=True"
bare=$(grep -rn "@dataclass" --include="*.py" "$SRC" 2>/dev/null \
    | grep -v "frozen=True" | grep -v "# noqa" || true)
if [ -z "$bare" ]; then
    _pass "All @dataclass decorators include frozen=True"
else
    while IFS= read -r h; do _fail "missing frozen=True: $h"; done <<< "$bare"
fi

# ── PY-TS-13: py.typed marker ────────────────────────────────────────────────
_section "PY-TS-13: py.typed marker present"
pkg=$(find "$SRC" -maxdepth 1 -name "py.typed" 2>/dev/null | head -1)
if [ -n "$pkg" ]; then
    _pass "py.typed present: $pkg"
else
    _fail "py.typed missing from $SRC"
fi

# ── PL-PP-1: No backwards-compat alias assignments ───────────────────────────
_section "PL-PP-1: No backwards-compatibility alias assignments"
# Only flag alias assignments (old_name = new_name pattern), not inline comments
hits=$(grep -rn "^[a-z_].*=\s*[a-z_].*\s*#.*\(deprecated\|removed\|backwards\)" \
    --include="*.py" "$SRC" 2>/dev/null | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No backwards-compat alias patterns found"
else
    while IFS= read -r h; do _warn "$h"; done <<< "$hits"
fi

# ── PL-PP-4: No secrets in code ──────────────────────────────────────────────
_section "PL-PP-4: No secrets in source"
hits=$(grep -rn "api_key\s*=\s*['\"].\|sk-[a-zA-Z0-9]" --include="*.py" "$SRC" 2>/dev/null \
    | grep -v "# noqa" | grep -v "os\.environ\|os\.getenv\|getenv" || true)
if [ -z "$hits" ]; then
    _pass "No hardcoded secrets detected"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── Module sizes (PY-OO-2 heuristic) ─────────────────────────────────────────
_section "PY-OO-2: Module sizes (warn > 300, fail > 500; __main__.py exempt)"
while IFS= read -r line; do
    count=$(echo "$line" | awk '{print $1}')
    file=$(echo "$line" | awk '{print $2}')
    [[ "$file" == *"__main__.py"* ]] && continue  # CLI entry point exempt
    if [ "$count" -gt 500 ]; then
        _fail "$count lines: $file"
    elif [ "$count" -gt 300 ]; then
        _warn "$count lines: $file"
    fi
done < <(find "$SRC" -name "*.py" -exec wc -l {} + 2>/dev/null \
    | sort -rn | grep -v "total")

# ── Dependency layering (PL-MD-1 / PY-IC-8) ──────────────────────────────────
# Only flag imports from inner layers (protocol, scene core) into outer layers.
# Within-layer imports (tools/tools.py importing tools/server.py) are fine.
_section "PL-MD-1 / PY-IC-8: Inner layers must not import from outer layers"
# Protocol and types modules importing from display, tools, or CLI
hits=$(grep -rn "from punt_lux\.display\|from punt_lux\.tools\|from punt_lux\.__main__" \
    --include="*.py" "$SRC/protocol" "$SRC/scene" 2>/dev/null | grep -v "# noqa" || true)
if [ -z "$hits" ]; then
    _pass "No inner-layer → outer-layer import violations"
else
    while IFS= read -r h; do _fail "$h"; done <<< "$hits"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
PASS=$(wc -l < "$PASS_FILE" 2>/dev/null || echo 0)
FAIL=$(wc -l < "$FAIL_FILE" 2>/dev/null || echo 0)
WARN=$(wc -l < "$WARN_FILE" 2>/dev/null || echo 0)
echo
echo "══════════════════════════════════════════"
printf "  PASS: %d   WARN: %d   FAIL: %d\n" "$PASS" "$WARN" "$FAIL"
echo "══════════════════════════════════════════"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
