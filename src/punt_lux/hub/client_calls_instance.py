"""The process-wide table of requests pending on a provider's listen leg.

In its own module beside the Hub's other singletons: the listen sessions resolve
its calls from the frames they read, and the operations that relay a request enter
them, so both must hold the one instance.
"""

from __future__ import annotations

from punt_lux.hub.client_calls import ClientCalls

__all__ = ["hub_client_calls"]

hub_client_calls = ClientCalls()
