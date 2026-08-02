"""The process-wide binding the Hub's Details command runs through.

Kept beside the other Hub singletons but in its own module, because the
interaction dispatch reaches it lazily and the composition roots bind it at
import: a module that holds one thing has no import cycle to dodge.
"""

from __future__ import annotations

from punt_lux.domain.hub.details_binding import DetailsBinding

__all__ = ["hub_client_details"]

# The renderer the Hub's own Details command runs, bound by the composition root
# that builds the operations facade. Until then it is the Null Object.
hub_client_details = DetailsBinding()
