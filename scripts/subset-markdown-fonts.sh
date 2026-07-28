#!/usr/bin/env bash
# Subset the DejaVu Sans quad to the glyphs Lux's markdown renderer needs, shrinking
# the packaged fonts from ~2.7 MB to ~0.7 MB. Dev-time only: run once when the source
# fonts change, then commit the subsetted TTFs. fontTools is pulled ephemerally via
# `uv run --with`, so there is no runtime or install-time dependency.
#
# Source: DejaVu Sans (full) — e.g. TeX Live's public/dejavu, or a DejaVu release.
# Kept ranges: Basic Latin / Latin-1 / Latin Extended-A & B, then General Punctuation
# through Miscellaneous Technical (dashes, arrows U+2190-21FF, math), Box Drawing and
# Geometric Shapes, and Miscellaneous Symbols and Arrows.
set -euo pipefail

src="${1:-/usr/local/texlive/2025/texmf-dist/fonts/truetype/public/dejavu}"
dst="$(cd "$(dirname "$0")/.." && pwd)/src/punt_lux/display/fonts/dejavu"
ranges="U+0000-024F,U+2000-23FF,U+2500-259F,U+2B00-2BFF"

subset() {
  uv run --with fonttools python -m fontTools.subset "$src/$1" \
    --output-file="$dst/$2" --unicodes="$ranges" \
    --layout-features='*' --glyph-names --notdef-outline --recalc-bounds
}

subset DejaVuSans.ttf DejaVu-Regular.ttf
subset DejaVuSans-Bold.ttf DejaVu-Bold.ttf
subset DejaVuSans-Oblique.ttf DejaVu-RegularItalic.ttf
subset DejaVuSans-BoldOblique.ttf DejaVu-BoldItalic.ttf

echo "subsetted 4 weights -> $dst"
