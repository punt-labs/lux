"""The facade's duration attestation: one INFO line per mutating operation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Cleared, OpError, RenderRequest, SceneShown
from punt_lux.operations.display_reply import DisplayReplied
from punt_lux.operations.models.display_write import FrameRaise
from punt_lux.operations.scope import Scope
from punt_lux.operations.timing import OperationSubject, Timed
from tests.rest._fakes import StubPort, make_facade

if TYPE_CHECKING:
    import pytest

_LOCAL = Scope(ConnectionId("local"))
_TIMING_LOGGER = "punt_lux.operations.timing"


class _StepClock:
    """A clock that advances a fixed number of seconds on every reading."""

    def __init__(self, step: float) -> None:
        self._step = step
        self._now = 0.0

    def __call__(self) -> float:
        now = self._now
        self._now += self._step
        return now


def _render_request(scene_id: str) -> RenderRequest | OpError:
    return RenderRequest.parse(
        {
            "scene_id": scene_id,
            "elements": [{"kind": "text", "id": "t1", "content": "Hi"}],
        }
    )


def test_timed_logs_one_line_with_the_elapsed_milliseconds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    timed = Timed("render", _StepClock(0.025))

    @timed
    def _run() -> SceneShown:
        return SceneShown(scene_id="beads-lux")

    with caplog.at_level(logging.INFO, logger=_TIMING_LOGGER):
        assert _run().scene_id == "beads-lux"

    assert caplog.messages == ["op render scene=beads-lux 25 ms"]


def test_timed_returns_the_operations_own_result() -> None:
    timed = Timed("clear", _StepClock(0.0))

    @timed
    def _run(value: int, *, doubled: bool) -> int:
        return value * 2 if doubled else value

    assert _run(21, doubled=True) == 42


def test_subject_names_the_scene_the_frame_and_the_failure() -> None:
    subject = OperationSubject()
    assert subject.of(SceneShown(scene_id="s1")) == "scene=s1"
    assert subject.of(FrameRaise(frame_id="f1", raised=True)) == "frame=f1"
    assert subject.of(OpError(code="not_found", reason="gone")) == "error=not_found"
    assert subject.of(Cleared()) == "-"


def test_a_render_through_the_facade_is_attested_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    facade = make_facade(display_port=StubPort(DisplayReplied({})), store=HubDisplay())
    with caplog.at_level(logging.INFO, logger=_TIMING_LOGGER):
        result = facade.render(_render_request("s1"), scope=_LOCAL)
    assert isinstance(result, SceneShown)
    lines = [r.message for r in caplog.records if r.name == _TIMING_LOGGER]
    assert len(lines) == 1
    assert lines[0].startswith("op render scene=s1 ")
    assert lines[0].endswith(" ms")


def test_a_rejected_render_is_attested_with_its_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    facade = make_facade(display_port=StubPort(DisplayReplied({})), store=HubDisplay())
    with caplog.at_level(logging.INFO, logger=_TIMING_LOGGER):
        request = RenderRequest.parse(
            {"scene_id": "s1", "elements": [{"kind": "no-such-kind", "id": "x"}]}
        )
        facade.render(request, scope=_LOCAL)
    lines = [r.message for r in caplog.records if r.name == _TIMING_LOGGER]
    assert len(lines) == 1
    assert lines[0].startswith("op render error=")


def test_a_read_only_query_is_not_attested(caplog: pytest.LogCaptureFixture) -> None:
    facade = make_facade(display_port=StubPort(DisplayReplied({})), store=HubDisplay())
    with caplog.at_level(logging.INFO, logger=_TIMING_LOGGER):
        facade.list_scenes()
    assert [r for r in caplog.records if r.name == _TIMING_LOGGER] == []
