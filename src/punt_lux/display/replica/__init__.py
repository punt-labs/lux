"""The Display's replica of the UI state the Hub sent it.

Every module here holds state that is re-derivable from a Hub re-send: the
Display replaces its copy wholesale when a scene changes, so nothing in this
package is authoritative.

The exception is a frame's visibility. Where a frame sits — on screen, docked,
or put away — is the user's decision, held here and never sent back to the Hub,
so a re-send does not re-derive it (DES-065 R8).
"""

from __future__ import annotations

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.display.replica.scene_replica import SceneReplica
from punt_lux.display.replica.widget_state import WidgetState

__all__ = ["Frame", "FrameVisibility", "SceneReplica", "WidgetState"]
