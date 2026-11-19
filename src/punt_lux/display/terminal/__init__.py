r"""A terminal for the Lux display, built on libghostty-vt (SPIKE).

Spike branch ``spike/terminal-ghostty``; see ``docs/adr/0001``-``0006`` for
the decisions and ``spikes/terminal/STEP*.md`` for the evidence.

The package is a pipeline, one module per stage::

    PTY bytes ─▶ ghostty Terminal ─▶ RenderState ─▶ RowBuilder ─▶ Painter ─▶ ImGui
       ▲                                (dirty rows)   (packed cells    (draw list)
       │                                                → runs/spans)
       └──────── Input (Ghostty key/mouse/paste encoders) ◀── ImGui events

=================  ==========================================================
``ffi``            the only module that touches pyghostty internals
``model``          plain data: ``Run``, ``BgSpan``, ``Row``, ``CellStyle``
``cell_layout``    packed ``GhosttyCell`` bit layout, read from the library
``render_state``   Ghostty render state + dirty-row cache of ``Row``\\ s
``row_builder``    one row → runs and background spans (bulk numpy decode)
``painter``        ``Row``\\ s, cursor and selection → ImGui draw list
``keymap``         ImGui key → Ghostty key, and the modifier mapping
``input``          ImGui keyboard/mouse/paste → bytes via Ghostty encoders
``selection``      Ghostty-owned selection: drag, word, line, copy text
``view``           ``TerminalView``: the widget that ties it together
``pty``            a local shell on a PTY, read without threads
``sessions``       named sessions owned by the Display (luxd-pty stand-in)
=================  ==========================================================

Everything runs on the Display's render thread (DES-002); nothing here takes
a lock.
"""

from __future__ import annotations
