"""Run-and-prove harness for the dead-connection-reaping model (lux-d84d).

Invoked as:

    uv run --extra display python scripts/prove_reaping.py

Requires a running luxd on the branch code (``lux hub restart``). Connects
through the front door — :class:`LuxClient` builds a :class:`RenderRequest`
exactly as the CLI and any agent would — shows a scene it owns, prints its
connection id and session, then blocks making NO further contact. With no
renewal, its cli-kind lease (90s) lapses and the background lease-reap sweep
(15s poll interval) must reap the connection and release the scene with no
other Hub activity in play.

Pair this script with ``make prove-reaping``, which spawns it, waits out one
lease interval plus a poll cycle, and shows ``lux session ls --json`` /
``lux scene ls --json`` so the operator can see the victim connection gone
from the session list and its scene's ``owners`` empty — while other live
connections remain untouched.
"""

from __future__ import annotations

import asyncio

from punt_lux import LuxClient, RenderRequest, SceneShown

_SCENE = "reap-proof-victim"


async def main() -> None:
    """Show a scene, print identifying info, then block forever (no renewal)."""
    client = LuxClient.connect()
    result = await client.scene.show(
        RenderRequest(
            scene_id=_SCENE,
            elements=[{"kind": "text", "id": "v1", "content": "reap-proof victim"}],
        )
    )
    if isinstance(result, SceneShown):
        print(f"SHOWN scene_id={result.scene_id}", flush=True)
    else:
        print(f"SHOW-RESULT {result!r}", flush=True)
    sessions = await client.session.ls()
    print(f"SESSIONS_AFTER_SHOW {sessions!r}", flush=True)
    print("IDLE — no further contact; awaiting reap", flush=True)
    await asyncio.Event().wait()  # block forever; renew nothing


if __name__ == "__main__":
    asyncio.run(main())
