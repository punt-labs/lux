"""DisplayInteraction — lightweight event the Display fires on UI click.

No factory-token guard. Constructed by the display-side renderer when
ImGui detects a click. The ``remote_dispatch`` handler receives this
event and sends an ``InteractionMessage`` to the Hub over the socket.
The Hub constructs the real ``ButtonClicked`` (with the factory token)
on its side.

This event exists so the display-side ``element.fire()`` call has a
typed event to pass. The Hub never sees ``DisplayInteraction`` — only
``InteractionMessage`` crosses the wire.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DisplayInteraction"]


@dataclass(frozen=True, slots=True)
class DisplayInteraction:
    """A UI click detected on the display side.

    Carries only the ``element_id`` — enough for the
    ``remote_dispatch`` handler to construct the outbound
    ``InteractionMessage``. No ``owner_id``, no ``scene_id``
    (the send function stamps ``scene_id`` downstream).
    """

    element_id: str
