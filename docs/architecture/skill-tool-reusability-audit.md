# Skill / Tool Reusability Audit — the interactive io-model knowledge gap

**Status:** recommendation for the operator. No code changed.
**Scope:** read-only audit of skills, MCP tool descriptions, and the wire codecs
that decide dialog / button interaction wiring.

## The concrete problem

To demonstrate Lux's interactive io-model, the leader had to read three source
files that an MCP-only consumer never sees:

- `src/punt_lux/protocol/elements/dialog_codec.py`
- `src/punt_lux/protocol/element_factory.py`
- `src/punt_lux/protocol/elements/button.py` / `dialog.py`

Two facts live only there:

1. A dialog's child button needs a `click` verb
   (`{"click": "confirm" | "cancel" | "close" | "dismiss"}`) to wire to the
   `DialogModel` and dismiss the modal. A child button **without** a verb
   decodes to a **no-op** and the modal can never be dismissed —
   `element_factory.py:144-146` (`canonicalize_button_sugar` returns the dict
   unchanged when `click` and `publish` are both absent) → the button installs
   an empty handler registry.
2. The ask-user loop: dialog buttons carry a `publish` decorator; the agent
   reads answers with `recv`. The verb-to-model binding is resolved at decode
   time by `BoundVerb.resolve_against(model, verb)` (`dialog_codec.py:144`).

Neither fact is reachable over MCP. The audit below establishes where the
knowledge lives today, then ranks fixes. Per the operator's addendum, each gap
is tagged **automate**, **validate**, or **document** — and automate/validate
dominate, because a silent no-op is a defect, not a documentation deficiency.

---

## 1. Skills inventory

Lux ships **four** invocable surfaces. None teaches the interactive io-model.

| Surface | Location | Ships where | Teaches |
|---|---|---|---|
| `/lux` command | `commands/lux.md` | lux plugin (marketplace) | enable/disable display mode only |
| `data-explorer` skill | `skills/data-explorer/SKILL.md` | lux plugin | filterable table + built-in filters + detail; mentions `recv()`/`update()` only for row-action refresh |
| `dashboard` skill | `skills/dashboard/SKILL.md` | lux plugin | metric cards + charts + table; `recv()` only for a refresh button |
| `beads` skill | `skills/beads/SKILL.md` | lux plugin | `show_table` from `bd list --json` |

Findings:

- **Zero skills cover dialogs, ask-user, the `click` verb, or interaction
  observation.** `data-explorer` and `dashboard` mention `recv()` in passing but
  frame it as "detect a refresh-button click," never the publish/recv answer
  loop, and never the dialog dismiss wiring
  (`skills/data-explorer/SKILL.md:144-165`, `skills/dashboard/SKILL.md:114-122`).
- Skills live in **`lux/skills/`** and ship via the **marketplace plugin**
  (`.claude-plugin/plugin.json`), **not** the `punt-lux` PyPI package
  (`pyproject.toml:215` — the wheel includes only `src` and `tests`). A consumer
  who installs `punt-lux` but not the plugin gets **no skills at all**.
- The `allowed-tools` lists in every skill enumerate `show`, `update`, `recv`,
  `set_theme` — but not `publish`, `subscribe`, or any dialog pattern.

---

## 2. MCP tool inventory + doc quality

31 tools total: 27 in `tools/tools.py`, 4 in `tools/subscribe_tools.py`. The
tool **description** is the only surface an MCP-only agent reads. Assessment of
the interaction-relevant ones:

### `show` (`tools/tools.py:41-122`)

The docstring enumerates element kinds by category. Findings:

- **`dialog` is not listed at all.** The "Interactive elements" block
  (`tools.py:53-59`) names slider, checkbox, combo, input_text, radio,
  color_picker. Button is under "Display elements" (`tools.py:49`) as
  `{"kind": "button", "id": "b1", "label": "Click me"}` — **no `click`, no
  `action`, no handler, no `publish`.**
- No mention of the `click` verb, the dismiss vocabulary, or that a bare button
  fires nothing observable.
- The parenthetical "(generate 'changed' events via recv)" on
  interactive elements (`tools.py:53`) is **misleading** — `recv` delivers
  `publish` app events, not raw UI changes. The `recv` docstring itself
  (`subscribe_tools.py:78-79`) contradicts it: "UI wire frames (button clicks,
  slider drags) are not delivered here."

### `recv` (`subscribe_tools.py:71-86`)

Accurate but narrow: "Block for the next business event... Events come from
`Hub.publish` calls scoped to this session." It does **not** connect the loop to
dialog buttons — an agent cannot learn from this text that a dialog button's
`publish` decorator is what feeds `recv`.

### `publish` / `subscribe` (`subscribe_tools.py:33-68`)

Document the pub/sub mechanics (scope, delivery count) but never mention that
dialog/button interactions are the **producer** side. The wire syntax that puts
a `publish` on a button (`{"publish": ["topic"]}`) appears nowhere in any tool
description — it lives only in `element_factory.py:135-141`.

### `register_tool` (`tools.py:438-467`)

Documents menu-item registration and that clicks route back via `recv()`. This
is the **one** tool description that correctly ties an interaction to `recv`.

### `inspect_scene` (`tools.py:588-608`)

"Return the element tree for a scene as JSON... to debug rendering issues."
Does **not** mention that each element carries `render_path` (`abc` | `legacy`)
and `resolved_props` — the exact fields an author needs to verify a dialog
button resolved its verb. Those fields exist
(`scene_inspection.py:37,75-94`) but are undocumented at the tool surface.

### `list_recent_events` / `list_errors` (`tools.py:758-777`)

`list_recent_events`: "button clicks, slider changes, combo selections." Correct
but does not say a **verb-less** dialog button produces no dismiss. `list_errors`
returns "display-side errors and warnings" — a natural warn channel, but nothing
writes a decode-time interaction warning into it today.

**Verdict:** the interactive io-model is **absent from the tool-facing docs** and
reachable only in source. The one tool that gets it right is `register_tool`.

---

## 3. The gap, precisely

To use Lux's interactive elements end-to-end an agent must know five things.
Where each is reachable today:

| Knowledge needed | Reachable via |
|---|---|
| A dialog is `{"kind":"dialog","children":[button,...]}` | README `dialog` row (`README.md:217`); **not** in `show` docstring |
| A child button needs `{"click":"confirm\|cancel\|close\|dismiss"}` to dismiss | **source only** — `dialog.py:54-59`, `element_factory.py:135-167` |
| A verb-less child button is a silent no-op (dead modal) | **source only** — `element_factory.py:144-146` |
| Ask-user loop: button `{"publish":["topic"]}` → agent `recv()` | **source only** for the button syntax; `recv` mechanics in `subscribe_tools.py` |
| Verify wiring via `inspect_scene` → `render_path` / `resolved_props` | **source only** — `scene_inspection.py`; undocumented at tool |

Three of five facts are **source-only**. The README covers the dialog shape and
the pub/sub mechanics but **omits the `click` verb** — so even a consumer who
finds the README (not reachable over MCP; the wheel excludes docs) still cannot
build a dismissable dialog.

---

## 4. Silent no-op audit (the load-bearing finding)

Per the operator's addendum, the deeper problem is not missing docs — it is that
Lux **silently accepts inert interactive configuration**. Three cases:

### S1 — Dialog child button with no verb → dead modal (silent)

`canonicalize_button_sugar` (`element_factory.py:144-146`) returns the dict
unchanged when `click` and `publish` are both absent. The button then decodes
with an empty handler registry (`button_codec.py:96-98`). The modal renders,
the button paints, clicking does nothing, and **the dialog can never be
dismissed**. No warning at decode, no entry in `list_errors`, and `show` still
returns `ack:<scene_id>`. This is the exact defect the leader hit.

The `DialogModel` already owns the verb vocabulary — `confirm`, `cancel`,
`close`, `dismiss` (`dialog.py:54-59`) — so the information needed to auto-wire
is present at decode time.

### S2 — Standalone button with no handler → fires nothing (silent)

A top-level button via `show` with no `click`/`publish` registers only `noop`
(`standalone_button_handler.py:42-45`). Clicking produces a `list_recent_events`
entry but no app event, no `recv` delivery, no state change. The `show`
docstring's canonical button example (`tools.py:49`) is exactly this inert form.
An agent following the docs builds a button that does nothing and gets no signal.

### S3 — Incomplete wiring "succeeds"

Both S1 and S2 return `ack:<scene_id>`. Success is indistinguishable from a
correctly-wired scene. There is no decode-time contract that "an interactive
element must have an observable effect."

Contrast: the codecs are **loud** about the cases they do guard — an unknown
verb raises (`dialog_codec.py:144` via `BoundVerb.resolve_against`), a bad event
name raises (`button_codec.py:131-138`), a missing `publish_sink` raises at
construction (`dialog_codec.py:47-49`). The gap is precisely the **absence** of
a handler, which today is a legal (and common) no-op.

---

## 5. Reusable-form options, ranked

Two axes: (A) **automate / validate / document** and (B) **single source of
truth** — can the fix be derived from the codecs rather than hand-maintained?

### Option ranking

**Rank 1 — Auto-wire dialog dismissal from button labels (AUTOMATE).**
When a dialog child button carries no `click` verb, bind it to the model verb
matching its label: `OK`/`Confirm` → `confirm`, `Cancel`/`Dismiss`/`Close` →
`cancel`/`close`. A dialog with **zero** dismissable buttons gets a default
dismiss affordance. This removes the knowledge requirement entirely for the
common case — the agent writes `{"kind":"dialog","children":[{"kind":"button",
"label":"OK"}]}` and it works. Derives from the model vocabulary
(`dialog.py:54-59`) — single source of truth, no doc to drift. Fixes **S1**.
Element-purity note: the label→verb map belongs on `DialogModel` (it owns the
vocabulary), applied in `JsonDialogDecoder._decode_children`, not spread into
the agent-facing layer. Trust model unchanged — the Hub still owns dispatch.

**Rank 2 — Validate + warn at decode time (VALIDATE).**
Where auto-wire would guess wrong or does not apply (S2; an ambiguous dialog
button label), emit a warning the author sees immediately: return it on the
`show` ack (`ack:<scene_id> warnings:[...]`) and/or record it to the Hub error
log surfaced by `list_errors`. Example: *"dialog button 'Proceed' has no `click`
verb and will be a no-op; expected one of confirm/cancel/close/dismiss"* and
*"button 'b1' has no click handler or publish topic; clicking it produces no
observable effect."* The warning text derives from the same vocabulary tables
(`dialog.py:54-59`, `button_codec.py:41`) — single source of truth. Fixes the
**observability** half of S1/S2/S3: success stops being silent. This is the
highest-value change if only one ships, because it turns every remaining gap
into an immediate, self-describing signal instead of a dead modal.

**Rank 3 — Enrich the MCP tool descriptions in-package (DOCUMENT, but shipped
with the package).**
Add a `dialog` entry and the `click`/`publish` sugar to the `show` docstring;
fix the misleading "changed events via recv" line (`tools.py:53`); document
`render_path`/`resolved_props` on `inspect_scene`. Ships in `punt-lux`, visible
to every MCP client, no plugin needed. **Weakness:** hand-maintained prose that
drifts from the codecs — the very failure mode that produced this audit (the
README already omits the `click` verb). Acceptable as a **complement** to Rank
1–2, not a substitute.

**Rank 4 — A runtime `describe`/`help` MCP tool returning derived reference.**
A tool that introspects the codec registries (`_BUTTON_EVENT_TYPES`,
`DialogModel._ACTIONS`, the factory's `_ABC_KINDS`) and returns the live wire
grammar — the "runtime truth" pattern. Single source of truth by construction:
it reads the same tables the decoder uses, so it cannot drift. Ships in the
package. **Weakness:** discoverability — an agent must know to call it; it does
not prevent the silent no-op, only answers when asked. Good companion to Rank 2.

**Rank 5 — A Lux plugin skill (interaction/ask-user recipe) (DOCUMENT, plugin
only).** A new `skills/interaction/SKILL.md` teaching the dialog dismiss pattern
and the publish/recv loop. **Weakness:** ships only in the marketplace plugin,
not the package — fails the "no source install needed" test for a `punt-lux`-only
consumer, and is hand-maintained prose. Lowest rank for the stated problem,
though still worth doing for plugin users once Rank 1–2 land.

### Per-gap disposition

| Gap | Right fix | Rank |
|---|---|---|
| S1 — verb-less dialog button = dead modal | **Automate** (label→verb) + **validate** (warn on ambiguous) | 1 + 2 |
| S2 — standalone button no-op | **Validate** (warn: no effect) | 2 |
| S3 — incomplete wiring "succeeds" | **Validate** (warnings on ack / list_errors) | 2 |
| `dialog` absent from `show` docs | **Document in-package** | 3 |
| `click`/`publish` sugar undocumented | **Document in-package**, backed by **runtime `describe`** | 3 + 4 |
| ask-user loop not tied to dialogs | **Document in-package** + **skill** | 3 + 5 |
| `render_path`/`resolved_props` undocumented | **Document in-package** | 3 |

Automate/validate cover the two defects (S1, S2, S3). Document/derive cover the
discoverability gaps. Documentation alone fixes nothing that matters most.

---

## 6. Recommendation, framed for the operator

The leader's read: **the primary fix is behavioral, not documentary.** A silent
no-op interactive element is a silent-failure defect (org silent-failure-hunter
/ PY-EH ethos). Ship Rank 1 + Rank 2 first; treat docs (Rank 3–5) as the
follow-on that makes the now-loud system discoverable.

Three decisions needed before any implementation dispatches:

1. **Auto-wire dialog dismissal (S1).** Recommend **yes** — bind verb-less
   dialog child buttons to the model verb matching their label, and give a
   button-less dialog a default dismiss affordance. Derives from
   `DialogModel._ACTIONS`; no agent knowledge required for the common case.
   *Risk to weigh:* an author who genuinely wants a non-dismissing button in a
   dialog must now opt out explicitly. Recommend that be a loud, explicit
   `{"click": "none"}` rather than the current silent default.

2. **Validate + warn at show/decode time (S2, S3).** Recommend **yes** — surface
   "this interactive element has no observable effect" on the `show` ack and in
   `list_errors`, with text derived from the codec vocabulary tables. This is the
   single highest-value change and should ship even if #1 is deferred.

3. **In-package doc + runtime `describe` (discoverability).** Recommend **yes,
   as a follow-on** — enrich the `show`/`inspect_scene` docstrings and add a
   codec-derived `describe` tool so the grammar cannot drift. Defer the plugin
   skill (Rank 5) until #1–2 land.

If the operator confirms, the natural work split (per the Lux pairing table): the
decode-time auto-wire + validation is a protocol/handler change (worker `gvr` or
`rmh`, evaluator the other; `djb` for the trust-boundary review since decode runs
Hub-side); the tool-description and `describe`-tool work is the MCP surface
(worker `mdm`, evaluator `rmh`). This is a `standard`-pipeline change — it
touches the wire-decode contract.

---

## Appendix — file:line index

- Silent no-op (S1): `src/punt_lux/protocol/element_factory.py:144-146`
- Dialog verb vocabulary: `src/punt_lux/protocol/elements/dialog.py:54-59`
- Verb resolution at decode: `src/punt_lux/protocol/elements/dialog_codec.py:144`
- Standalone button noop-only: `src/punt_lux/protocol/standalone_button_handler.py:42-45`
- Loud guards (contrast): `button_codec.py:131-138`, `dialog_codec.py:47-49`
- `show` docstring (no dialog, inert button): `src/punt_lux/tools/tools.py:41-122`
- Misleading recv line: `src/punt_lux/tools/tools.py:53`
- `recv` mechanics: `src/punt_lux/tools/subscribe_tools.py:71-86`
- `publish`/`subscribe`: `src/punt_lux/tools/subscribe_tools.py:33-68`
- `inspect_scene` (no render_path doc): `src/punt_lux/tools/tools.py:588-608`
- `render_path`/`resolved_props`: `src/punt_lux/scene_inspection.py:37,75-94`
- Skills (none teach io-model): `skills/{data-explorer,dashboard,beads}/SKILL.md`
- Wheel excludes docs: `pyproject.toml:215`
- README covers dialog shape but omits `click` verb: `README.md:217`, `README.md:162-175`
