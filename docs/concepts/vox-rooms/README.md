# Vox Rooms

> **Status: product concept, brainstorm stage. Not an approved plan.**
> Nothing here is the canonical Lux architecture or a commitment to build it;
> do not use it to guide Lux implementation. The canonical target is still
> [`docs/architecture/target/target.md`](../../architecture/target/target.md).
> This folder is a durable copy of a November 2026 design conversation and
> will probably move to its own repository.

Vox Rooms (working name) is a keyboard-first, voice-forward workspace for
developers who run several AI coding agents across repositories and machines.
It merges ideas from Lux (visual state), Vox (voice) and Biff (agent
messaging). Its thesis: the developer should lead a team of agents, not relay
messages between them. Agents bring decisions to the developer, who answers by
voice or one key. The work's state lives in a shared, typed board instead of
chat scrollback. Agents can build self-describing tools that every other agent
discovers and uses.

## Contents

| Path | What it is |
| --- | --- |
| [`prfaq.tex`](prfaq.tex) | First-draft PR/FAQ, the most complete statement of the concept. Uses a built-in bibliography, so plain `pdflatex` builds it. Not yet compiled. |
| [`prototype/vox-rooms.html`](prototype/vox-rooms.html) | Clickable prototype. Source for a claude.ai artifact page: it has no `<!doctype>` or `<html>` wrapper, because the artifact host adds one. Open it in a browser to run it. |
| [`mockups/`](mockups/) | Thirteen static screens (A–M) and their canvas layout (`canvas.json`). These are claude.ai Design-canvas sources; they load the canvas runtime's `support.js` and render only there. |
| [`notes/01-lux-review-notes.md`](notes/01-lux-review-notes.md) | Review of Lux's design docs and Dear ImGui, plus graphics engines Lux could use. |
| [`notes/02-room-synthesis.md`](notes/02-room-synthesis.md) | First synthesis: terminals, a blackboard and a mesh. Written before the "compete with herdr" reframe. |
| [`notes/03-herdr-competitor-brainstorm.md`](notes/03-herdr-competitor-brainstorm.md) | The reframe as a herdr competitor, ImGui fidelity, and the Python-versus-Rust question. |

## The mockups

| Screen | Idea |
| --- | --- |
| A · Workbench | Terminals beside live views; agent roster with jump-to-blocked |
| B · Rich scrollback | Live widgets inside the terminal scrollback, beside a Biff channel |
| C · Blackboard and mesh | Regions each owned by one agent; signed board history |
| D · Blackboard in Lux's real theme | C rebuilt with hello_imgui `DarculaDarker` and docking |
| E · Live environment | Pharo-inspired halos, inspector, system browser, playground |
| F · C within ImGui limits | Custom theme, fixed layout, one style per text run |
| G · Terminal workspace | Tiled agents and the ask bar, answered with one key |
| H · Listen after speaking | A question answered by voice, step by step |
| I · Agent channel | Agents co-design in precise formats; disagreements escalate |
| J · First run | One command, nothing to configure, and the key layer |
| K · Room home | What needs me, where the work stands, who is on what, tools |
| L · Cross-repo work item | Explicit view on top, the implicit layer one key down, the fact log |
| M · Tools | Defaults, installed tools, and one an agent built on request |

## Key ideas, in one place

- **Rooms:** one container for the repositories, machines, agents, state and
  tools of one body of work.
- **Explicit and implicit hierarchy:** the developer navigates decisions,
  board, work items, team and tools; hosts, sessions, branches and terminals
  sit one keystroke below.
- **The fact log:** one append-only log of typed facts (entity, attribute,
  value, transaction) underlies the board, the transcript and every tool. It
  follows the lineage of Hearsay-II's blackboard, Linda's tuple spaces and
  Datomic.
- **Voice:** questions spoken in one sentence; listen-after-questions, toggled
  with one key; answers matched against the question's options.
- **Tools:** tier one is a composition with no new code; tier two is a scoped,
  approved program. Tools describe themselves, so agents discover and use them
  immediately.

## Related records

- Linear issues from the same session: PL-563 to PL-565 (docs and ImGui
  findings) and PL-719 to PL-726 (dead-code cleanup).
- [`../pharo-inspiration.md`](../pharo-inspiration.md), an earlier concept.
