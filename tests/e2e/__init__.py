"""End-to-end business-event-loop harness — in-process, no socket, no GPU.

The harness wires the production Hub logic and the production Display
receive/wrap/emit logic into one process through the shipped
``InMemoryConnection`` and proves the full bidirectional loop a real
click drives: interaction crosses the faithful ``Connection`` boundary,
the real handler runs once on the Hub's authoritative ``HubDisplay``
copy, a business event a real subscriber receives is published, the
simulated agent reacts by pushing a change back, and the re-pushed
Display replica reflects it.

Design of record: ``docs/architecture/e2e-harness-design.md``.
"""

from __future__ import annotations

__all__: list[str] = []
