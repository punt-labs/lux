"""The process-wide binding the replicator resolves a scene's owner facts on.

Kept beside the other Hub singletons but in its own module, mirroring
``details_instance.py``: the replicator is built at import time, before the
operations layer exists to answer a facts query, so it holds this rebindable
port from the start; the composition root binds the real reader once
operations are composed.
"""

from __future__ import annotations

from punt_lux.domain.hub.frame_owner_facts import FrameOwnerFactsBinding

__all__ = ["hub_frame_owner_facts"]

# The reader the replicator asks for a scene's owner facts on every send,
# bound by the composition root that builds the operations facade. Until
# then it is the Null Object, reporting every scene as unowned.
hub_frame_owner_facts = FrameOwnerFactsBinding()
