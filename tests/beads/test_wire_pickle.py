"""Beads sends wire data; no product class is needed by the Display unpickler."""

from __future__ import annotations

import base64
import json
import pickle
import subprocess
import sys
from typing import cast

import pytest

from punt_lux.beads.beads_board import BeadsBoard
from punt_lux.beads.beads_result import BeadsFailure, BeadsRows
from punt_lux.hub.hub_factory import hub_element_factory
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.model.compositions.table_composition import TableComposition
from punt_lux.wire.model.elements import Element
from punt_lux.wire.model.messages.scene import SceneMessage
from punt_lux.wire.operations import RenderTableRequest
from tests.beads.board_doubles import ISSUE


@pytest.mark.parametrize("state", ["populated", "empty", "error"])
def test_beads_scene_decodes_with_both_beads_package_paths_blocked(state: str) -> None:
    result = (
        BeadsFailure("offline")
        if state == "error"
        else BeadsRows.of([ISSUE] if state == "populated" else [])
    )
    request = BeadsBoard.for_project("pickle").request(result)
    assert b"punt_lux.beads" not in pickle.dumps(request, protocol=0)
    if isinstance(request, RenderTableRequest):
        elements = cast("list[Element]", TableComposition.build(request.to_spec()))
    else:
        factory = hub_element_factory(ConnectionId("beads-wire"))
        elements = [factory.element_from_dict(raw) for raw in request.elements]
    scene = SceneMessage(
        id=request.scene_id, frame_id="beads-pickle", elements=elements
    )
    payload = scene.to_dict()
    for entry in payload["elements"]:
        raw = base64.b64decode(entry["_pickled"])
        assert b"punt_lux.beads" not in raw
        assert b"punt_lux.applets" not in raw
    code = """
import importlib.abc
import json
import sys
from punt_lux.wire.model.messages.scene import SceneMessage

class NoProduct(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + '.')
               for p in ('punt_lux.beads', 'punt_lux.applets')):
            raise ModuleNotFoundError(fullname)

sys.meta_path.insert(0, NoProduct())
data = json.load(sys.stdin)
scene = SceneMessage.from_dict(data['wire'])
assert [element.to_dict() for element in scene.elements] == data['elements']
assert not any(name.startswith(('punt_lux.beads', 'punt_lux.applets'))
               for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-P", "-c", code],
        check=True,
        capture_output=True,
        text=True,
        input=json.dumps(
            {"wire": payload, "elements": [e.to_dict() for e in elements]}
        ),
    )
