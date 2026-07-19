# Resume

## What we're doing right now

Fixing a real bug: an MCP `clear` call once froze an agent for 38 minutes,
because tools talk to the display directly and block on it. The fix is to make
every tool only touch the Hub's own copy of the interface and return
immediately, and let a background worker inside the Hub push changes to the
display and deal with a slow or dead one. No tool ever waits on the display.

## Where it stands

- The design is written, reviewed, and committed:
  `docs/architecture/mcp-display-liveness.md` on branch `fix/lux-mcp-timeout`
  (commit `e36583f`). It has been through two review rounds and aligned to the
  architecture standard.
- No code is changed yet. Only the design exists.

## Next step

Build the fix. The hard part is the Hub's background worker (the "replicator"):
several threads touch it and it takes a lock, so the design requires
model-checking that concurrency with a Z spec (run through ProB) *before*
writing the code. Order: model-check the worker → implement it → run it and
confirm a stuck display no longer freezes an agent.

## The other lux track (paused)

The Element-ABC migration — moving the remaining UI element types onto the new
Hub/Display path (bead `lux-xs7r`). Live status:
`docs/architecture/migration/README.md`. The display-hang fix comes first.
