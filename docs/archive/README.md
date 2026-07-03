# Archive

Documents here are retained for history. They are not maintained and do not
describe the current system. Do not use them to guide implementation.

Each archived file carries a banner at the top of its body naming the date it
was archived and what supersedes it.

## Why archive instead of delete

Deleting loses the reasoning trail. Archiving keeps the record readable without
letting a stale document sit alongside current guidance where a reader might
mistake it for live design. When you need the material, read it here; when you
need current design intent, read
[`../architecture/target/target.md`](../architecture/target/target.md); when
you need the current architecture, read
[`../architecture/system.tex`](../architecture/system.tex).

## Contents

- [`claude-code-lux.tex`](./claude-code-lux.tex) — Z specification of a
  Layer-2 "Claude Code + Lux" integration model. Predates the Hub/Display
  architecture and describes a single-process integration that no longer
  reflects the system. Superseded by the target architecture docs.
- [`coverage-audit.md`](./coverage-audit.md) — a point-in-time ImGui-vs-Lux
  element coverage audit taken at Lux v0.5.x (23 element types). The catalog
  has since grown to 25 kinds, so the tallies are stale. The living ImGui API
  reference is [`../imgui/primitive-catalog.md`](../imgui/primitive-catalog.md).
