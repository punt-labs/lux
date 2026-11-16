# ADR-0002: Bind libghostty-vt with pyghostty, pinned exactly, behind one module

- **Status:** Accepted (spike)
- **Date:** 2026-11-15
- **Evidence:** `spikes/terminal/STEP1.md`; `src/punt_lux/display/terminal/ffi.py`

## Context

The Lux display is Python. There are several Python bindings for libghostty-vt:

- **pyghostty** (AnswerDotAI): cffi, prebuilt wheels for macOS and Linux, the
  most used.
- **evp:** PyO3 over the Rust crate, with the nicest Python API.
- **python-libghostty-vt:** cffi, fully typed.

pyghostty's friendly layer (`Terminal`) covers text, cursor, style and resize.
The renderer needs much more: render state, raw packed cells, key and mouse
encoders, selection and paste. Those are only in pyghostty's generated
low-level layer (`ffi`/`lib`), plus two private helpers.

## Decision

- Use **pyghostty 0.1.4**, **pinned exactly** in the `display` extra, because
  the code uses its low-level and private API.
- Keep **every** touch of pyghostty internals in one module, `terminal/ffi.py`:
  - the raw terminal handle
  - the scroll call that passes a union by value
  - string reads
  - re-exports of `ffi`, `lib` and `init_sized`

  The rest of the package imports from `ffi.py`.
- Read the packed-cell bit layout from the loaded library's
  `ghostty_type_json()` manifest at run time, never hard-coded (ADR-0003).

## Consequences

- A pyghostty or Ghostty upgrade is checked in two places: `ffi.py`, plus
  `cell_layout.py` for the manifest.
- Type checking:
  - pyghostty has no type stubs, so it is in mypy's `ignore_missing_imports`
    list.
  - The terminal modules turn off pyright's unknown-member reports at file
    level, as Lux already does for `imgui_bundle`.
- Platforms: pyghostty has wheels for macOS (arm64, x86_64) and Linux (x86_64,
  aarch64), matching Lux's platforms (DES-001). There is no Windows wheel.
- If pyghostty stalls, the C ABI is stable, so a fork or another binding only
  touches `ffi.py`.

## Alternatives considered

- **evp:** better API, but very new, and it doesn't expose the raw cell view
  the bulk decoder relies on.
- **A C or Cython extension:** fastest, but adds a build step to an otherwise
  pure-Python install. Not needed after ADR-0003.
- **Our own cffi binding:** pyghostty already does exactly this, generated from
  the headers.
