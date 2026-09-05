# Multi-Hub Addressing and Cross-Host Transport — Increment of Work

**Status:** implementation plan for DES-089 (Identity Is a Path) and
DES-090 (Cross-Host Hub-to-Display Transport and Trust), both
`DESIGN.md`, both **Status: PROPOSED — pending operator ratification**.
Do not dispatch any bead below until the operator has ratified the
design as a whole; an evaluator's mission-internal sign-off is not
itself ratification (`DESIGN.md`'s own language for both entries).

This is the bead map and dependency order an implementer builds from.
It is not a second architecture document — for the "why," read
`docs/architecture/system.tex` §"Identity, Addressing, and Multi-Hub
Topology" and §"Cross-Host Transport and Trust," or the full design
record in `DESIGN.md` (DES-089, DES-090). This document answers only
"what ships, in what order, and who else needs to know."

## How to read this document

Every bead below carries: a short description, the source design
section it implements, its explicit dependencies (stated, not
inferred, from the two source design missions — m-2026-09-04-001 for
addressing, m-2026-09-04-003 for cross-host transport), and whether it
is z-spec-REQUIRED. Three beads already exist and become children of
DES-089 rather than independent one-offs: `lux-whb9`, `lux-pgkp`,
`lux-kob7`. Every other bead (`W1`–`W15`) is net-new and not yet filed
— the leader files these against this document, per the design
missions' own contracts.

## Bead map

### Existing beads (become children of DES-089)

| Bead | What it implements | Rung(s) | New dependency |
|---|---|---|---|
| `lux-whb9` | The hidden ImGui id, menus — `AddressBook.address_for(...).hidden_id` on `MenuItem` construction | 2 → 3 | Depends on **W4** (`AddressBook`) — the shared helper this bead must route through, not invent its own partial version of |
| `lux-pgkp` | The visible scoped title, frames and menus — `.title(...)` | 1, 2, 3 | Depends on **W4** |
| `lux-kob7` | `TreeNode` gets an id and a Hub-authoritative `TreeSelectionModel` (mirroring `TableSelectionModel`) — must mint Rung 1 *and* Rung 2 together, Rung-3-ready from the start | 1, 2 | Depends on **W4** |

### Net-new beads, in dependency order

| ID | Bead | Source | Depends on |
|---|---|---|---|
| **W1** | Close the pre-identification content gap | cross-host-transport §"A finding against the current same-host code" | none — prerequisite, ships first |
| **W2** | Hub identity on the wire (required `hub_id` field, populated by every connecting `kind` including `test`, + `HubId` value type) | addressing §"Hub identity on the wire" | none |
| **W3** | Per-Hub-keyed Display storage | addressing §"What must change," point 2 | W2 |
| **W4** | `AddressBook` component | addressing §"Every aggregated surface, uniformly" | W2 |
| **W5** | Scene storage collision regression test | addressing §"Governing invariant" | W3 |
| **W6** | Menu-click routing fix (retire scene-less broadcast) | addressing §"What must change," point 3 | W3 |
| **W7** | Personal CA + enrollment tooling | cross-host-transport §"Authentication and enrollment" | none |
| **W8** | Cross-host TLS listener (non-blocking, bounded-deadline handshake) | cross-host-transport §"Coexistence with the local fast path" | W7 |
| **W9** | Hostname verification at `ConnectMessage` time | cross-host-transport §"Resolving the trust fork" | W8, **W2** (shared touchpoint) |
| **W10** | Cross-host `DisplayLink` client path | cross-host-transport §"Connect, cross-host" | W7, W8 |
| **W11** | Preemption re-keyed onto `HubId` — **the resolved coordination point** | both documents — see below | W3 |
| **W12** | z-spec models, invariants 1 and 2 | cross-host-transport §"z-spec assessment" | W8, W9, W11 |
| **W13** | Threat-model regression tests (T1, T3, T4, T6) | cross-host-transport §"Threat model" | W8, W9 |
| **W14** | Scope manifest purge to the sending Hub's own scenes | addressing §"What must change" (manifest-purge correction) | W3 |
| **W15** | AWS Private CA trust-anchor provider (optional, opt-in) | cross-host-transport §"Provider 2 (Optional): AWS Private CA (Managed)" | W7, W8 |

### Dependency graph

```text
W1 (prerequisite, no dependency — land first regardless of everything else)

W2 ─┬─> W3 ─┬─> W5
    │       ├─> W6
    │       ├─> W11 ─┐
    │       └─> W14  │
    │                │
    └─> W9 <─ W8 <─ W7    W12 <── W9, W11
              │
              ├─> W10
              │
              ├─> W13 <── W9
              │
              └─> W15 (optional, opt-in — alternative provider)

lux-whb9, lux-pgkp, lux-kob7 ──> W4 <── W2
```

W1 has no dependency on anything else in this document and should
land independent of both the addressing and cross-host work — it is a
real gap in the current same-host code today, not merely a
cross-host prerequisite. Everything else forks into two mostly-parallel
tracks after W2: the addressing track (W3 → W4/W5/W6/W14, feeding the
three existing beads) and the cross-host track (W7 → W8 → W9/W10/W13),
which rejoin at **W11** and finish at **W12**. **W15** hangs off the same
W7/W8 pair but is not part of that critical path — it is an optional,
opt-in alternative to Provider 1 and ships (or doesn't) independent of
W9–W13 and the W11/W12 gate.

**W14** is the manifest-purge correction: `SceneReplica.scenes_to_purge`
disowns any scene neither owned by the identifying fd nor named in the
sending manifest — orphan-sweep logic that, unscoped, just as readily
disowns a second, live Hub's own scenes once more than one Hub can send a
manifest. It depends on W3 for the same reason W11 does: there is no
`HubId` to scope the purge predicate on until per-Hub-keyed storage
exists. It is independent of W11 (both depend on W3, but neither depends
on the other) and carries no z-spec requirement of its own — it is a
naming/keying discipline like the governing invariant it extends, not a
concurrency property, and is verified by the same collision-regression
style test as W5.

**W15** is the AWS Private CA trust-anchor provider
(`system.tex` §"Provider 2 (Optional): AWS Private CA (Managed)"): an
alternative to, not a replacement for, W7's self-managed personal CA. It
depends on W7 and W8 existing first, because it plugs into the same mTLS
transport and the same non-blocking TLS listener W7/W8 already built —
the trust-anchor abstraction (`system.tex` §"Trust Anchor Providers:
Pluggable, Not Fixed") means W15 swaps which root the Display's
`ssl.SSLContext` verifies against and how a Hub obtains its leaf; it does
not touch the handshake, the SAN check, or any invariant W8/W9 already
established. It carries no z-spec requirement of its own for the same
reason invariants 3 and 4 don't (`system.tex` §"Invariants" — all four
hold identically under either provider); it is a boundary/configuration
concern, verified by a regression test that the AWS-backed trust anchor
is loaded and enforced identically to W7's, not a new interleaving. W15
is optional and opt-in: Provider 1 (W7) remains sufficient to ship the
whole cross-host design end to end, and nothing else in this document
depends on W15 existing.

## The resolved coordination point: preemption keys on `HubId`, not `name`

Both source design missions flagged the same fork without resolving
it — addressing's own "What already works, unmodified" section
originally claimed preemption "already does the right thing" once a
real `HubId` populates the wire; cross-host-transport's "Preemption" section
correctly identified that claim as premature, because
`SocketListener.hub_fd_for(name)` keys on `ConnectMessage.name`, which
both documents keep meaning "what a human calls this connection" —
never a per-process identity. `system.tex`'s own "What Already Works,
Unmodified" subsection has been corrected to state this plainly: **it
is a required change, not something the current code already gets
right.**

**Resolution, stated once here rather than decided twice:** single-owner
preemption must key on `HubId` — the value W9 guarantees is both
verified (cross-host) and hostname-stable across reconnects — never on
`ConnectMessage.name`. `name` keeps its narrower meaning and plays no
role in preemption after this bead lands.

**Owning bead: W11.** It is deliberately not filed as two independent
beads (one under DES-089, one under DES-090) because addressing's
per-Hub-keyed storage (W3) and cross-host's preemption fix touch the
same dedup/ownership question from two angles — landing them
separately risks two conflicting fixes. W11 depends on W3 (the
per-Hub-keyed storage must exist before preemption has a `HubId` to
key against) and is a prerequisite for W12 (the z-spec model for
invariant 2 needs the corrected preemption logic to model against).

## The two z-spec-REQUIRED items (W12)

Per `cross-host-transport.md`'s own "z-spec assessment" section
(condensed in `system.tex` §"Cross-Host Transport and Trust" §"z-spec
Assessment"), two invariants clear WORKFLOW.md's z-spec trigger list
and must be model-checked, not merely tested, before W12 is
considered done:

1. **Invariant 1 — no content before verification.** A stateful-protocol
   safety property with a real interleaving: the connection's own state
   (TCP connected → TLS handshaking → TLS verified, awaiting
   `ConnectMessage` → identified, `HubId` verified → receiving content)
   is exactly the shape WORKFLOW.md's z-spec trigger list names. The
   concrete race the model must exhibit and then exclude: a
   non-blocking accept path that adds a socket to the client set
   before its TLS handshake or its `ConnectMessage` has actually
   completed, letting a `SceneMessage` arrive against an unverified or
   not-yet-identified connection. **Fidelity requirement:** the model
   must reproduce the defect when the handshake-before-accept ordering
   is removed.
2. **Invariant 2 — at most one live connection per `HubId`.** A
   lock/ownership discipline across a reconnect race, with multiple
   remote Hubs interleaving — the same shape DES-068's own single-owner
   preemption already needed a careful sequential argument for,
   generalized from one Hub to N concurrently-reconnecting Hubs. This
   is precisely WORKFLOW.md's recurrence signal: the same class of
   defect (stale-connection preemption correctness) has already
   surfaced across two design passes (addressing's premature "already
   correct" claim, corrected above; cross-host-transport's own explicit
   flag) — formalize the state machine rather than run a third
   empirical round. **Fidelity requirement:** the model must reproduce
   a double-owner state when preemption is re-keyed incorrectly (kept
   on `name`, with two same-named-but-different-`HubId` connections
   both live).

Invariants 3 (hostname verification is fail-closed) and 4 (the
`AF_UNIX` leg's trust argument is untouched) are boundary checks and a
non-interference statement, not concurrency properties — W13's
rejection-path regression tests plus a code-level audit are the
right-sized verification for those two, per both source documents'
own z-spec scoping.

W12 depends on W8, W9, and W11 all existing to model against — it is
the last bead in the cross-host track before the threat-model
regression tests (W13) close it out.

## Cross-repo coordination the `hub_id` wire bump forces

**W2 is a cross-repo commitment**, not a Display-repo-local change.
Vox and z-spec both run their own Hub connections against Lux's
Display (DES-063's applet model, `applets/README`), and both must add
`hub_id` to the `ConnectMessage` they send, in lockstep with W2
landing here — per the org's cross-repo breaking-change protocol
(`punt-labs/CLAUDE.md` §"Cross-repo breaking changes": notify both
repos' agents, get explicit agreement, land together, verify
end-to-end, release together).

This applies **regardless of whether either repo ever runs
cross-host.** Neither vox nor z-spec runs a Display — both are
Hub-side-only connections — so W7–W13 and W15 (the cross-host transport
track, including the optional AWS Private CA provider) add no
*additional* cross-repo requirement beyond the one W2 already names. The
`hub_id` field is a same-host wire change first; cross-host is what makes
verifying it matter, not what makes adding it necessary.

**`hub_id` is required, not optional, on every connecting `kind`** —
including `kind="test"`, which carries a stub `HubId` rather than
omitting the field (operator ruling, 2026-09-05; `system.tex` §"Hub
identity on the wire"). This raises the lockstep bar rather than lowering
it: because the field is required, a sender that has not yet adopted
`hub_id` will fail at `ConnectMessage` **decode**, not at some later
validation check, the moment W2 lands here. That is the intended
consequence of the ordinary cross-repo breaking-change protocol applied
to a required field, not a new risk this ruling introduces — it is exactly
why the sequencing below lands all three repos together rather than
allowing this repo's decoder to move ahead of its callers.

**Sequencing:** before W2 merges in this repo, notify the vox and
z-spec agents, get their explicit agreement on the field shape (a
plain, required `str` carrying `HubId.wire_token`, populated by every
`kind` — a real Hub's own token for `kind="hub"`, a stub token for
`kind="test"` — see `system.tex` §"Hub identity on the wire"), land the
three repos' changes together, and verify end-to-end before any of the
three releases. Landing this repo's change first, ahead of vox or
z-spec adopting `hub_id`, is not a soft failure to catch later — it is a
hard decode failure on the very next connection either makes.

## Prerequisite bead detail (W1)

`render_loop.py`'s `_handle_scene` / `hub_reconciliation.py`'s
`reject_scene_if_test_kind` rejects a `SceneMessage` only when the
sending fd has already declared `kind="test"`. An fd that has **not
yet sent any `ConnectMessage` at all** — `kind_of(fd)` returns `None`,
which is `!= "test"` — is not rejected today; its `SceneMessage` is
processed and installed. This is harmless on the `AF_UNIX` leg only
because the socket's `0700` permission already means an unidentified
fd is still a same-user process. It stops being harmless the moment a
store is keyed by `HubId` (W3): there is no `HubId` to key an
unidentified connection's content under at all.

**Fix:** every content-bearing message handler (`_handle_scene` and
its equivalents for menus and manifests) must reject a message from
any fd where `kind_of(fd) is None`, not only `kind_of(fd) == "test"`,
uniformly across both transports. This is a real gap in the shipped
code today, independent of whether cross-host ever lands — it should
be filed and fixed on its own timeline, not held for the rest of this
epic.

## Related documents

- `docs/architecture/system.tex` §"Identity, Addressing, and Multi-Hub
  Topology" and §"Cross-Host Transport and Trust" — the architecture
  this plan implements.
- `DESIGN.md` — DES-089, DES-090 (decision record, both PROPOSED).
- `docs/architecture/target/topology.md`, `ui-model.md`, `target.md` —
  the broader target-architecture context these two designs sit inside.
