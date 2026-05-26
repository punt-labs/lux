# OO Refactor Archive

Design documents and peer reviews for OO refactor work that has shipped.
Preserved for history; not authoritative for future work.

| File | Shipped in | One-line summary |
|---|---|---|
| `phase-a-protocol-split.md` | PR #169 (elements), PR #170 (messages) | Split `protocol.py` (1,886 lines, 32 dataclasses) into `protocol/elements/` and `protocol/messages/` family modules. |
| `draw-command-validation-design.md` | PR #176 | Typed `DrawCommand` decoder; replaces silent `.get(field, default)` defaults in the renderer with `ValueError` at the wire boundary. |
| `dynamic-access-design.md` | (multiple PRs) | Removed every `hasattr` / `setattr` / `getattr` from the protocol and message paths. |
| `oo-refactoring-plan-review.md` | n/a (review of `../oo-refactoring-plan.md`) | Peer review by `rej` of the refactoring plan; findings absorbed into the plan. |
| `oo-class-design-review.md` | n/a (review of `../oo-class-design.md`) | Peer review by `rej` of the class design; findings absorbed into the design. |

Remaining transitional docs live in the parent directory:

- `../oo-class-design.md` — class-level OO design (still has open items)
- `../oo-refactoring-plan.md` — historical step-by-step refactoring plan
- `../resume.md` — current status snapshot
