"""The facade's typed duration telemetry."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from punt_lux.hub.hub_store_factory import HubStoreFactory
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.kernel.usage import capture_usage
from punt_lux.operations.display_reply import DisplayReplied
from punt_lux.operations.timing import Timed
from punt_lux.wire.model.scope import Scope
from punt_lux.wire.operations import OpError, RenderRequest, SceneShown
from tests.rest._fakes import StubPort, make_facade

if TYPE_CHECKING:
    from pathlib import Path

_LOCAL = Scope.in_process(ConnectionId("local"))


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PUNT_TELEMETRY", raising=False)
    monkeypatch.delenv("LUX_TELEMETRY", raising=False)
    return tmp_path / ".punt-labs" / "lux" / "telemetry.db"


def _metrics(database: Path) -> list[tuple[str, int, str, int, float, str]]:
    with closing(sqlite3.connect(database)) as db:
        return db.execute(
            "SELECT name, schema_version, unit, count, sum, attributes "
            "FROM metric_points"
        ).fetchall()


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


def test_timed_records_elapsed_milliseconds(database: Path) -> None:
    timed = Timed("render", _StepClock(0.025))

    @timed
    def _run() -> SceneShown:
        return SceneShown(scene_id="beads-lux")

    with capture_usage():
        assert _run().scene_id == "beads-lux"

    [(name, version, unit, count, elapsed, attributes)] = _metrics(database)
    assert (name, version, unit, count, elapsed) == (
        "lux.hub.operation_duration",
        1,
        "ms",
        1,
        25.0,
    )
    assert '"operation": "render"' in attributes
    assert '"outcome": "ok"' in attributes
    assert "beads-lux" not in attributes


def test_timed_returns_the_operations_own_result() -> None:
    timed = Timed("clear", _StepClock(0.0))

    @timed
    def _run(value: int, *, doubled: bool) -> int:
        return value * 2 if doubled else value

    assert _run(21, doubled=True) == 42


def test_timed_records_a_raised_operation_as_an_error(database: Path) -> None:
    error = ValueError("private scene content")

    @Timed("render", _StepClock(0.025))
    def _run() -> None:
        raise error

    with capture_usage(), pytest.raises(ValueError) as caught:
        _run()

    assert caught.value is error
    [metric] = _metrics(database)
    assert metric[3:5] == (1, 25.0)
    assert '"outcome": "error"' in metric[-1]
    assert "private scene content" not in metric[-1]


def test_a_render_through_the_facade_is_attested_once(database: Path) -> None:
    facade = make_facade(
        display_port=StubPort(DisplayReplied({})), factory=HubStoreFactory()
    )
    with capture_usage():
        result = facade.render(_render_request("s1"), scope=_LOCAL)
    assert isinstance(result, SceneShown)
    [metric] = _metrics(database)
    assert metric[3] == 1
    assert "s1" not in metric[-1]


def test_a_rejected_render_records_only_the_error_outcome(database: Path) -> None:
    facade = make_facade(
        display_port=StubPort(DisplayReplied({})), factory=HubStoreFactory()
    )
    with capture_usage():
        request = RenderRequest.parse(
            {"scene_id": "s1", "elements": [{"kind": "no-such-kind", "id": "x"}]}
        )
        facade.render(request, scope=_LOCAL)
    [metric] = _metrics(database)
    assert '"outcome": "error"' in metric[-1]
    assert "no-such-kind" not in metric[-1]


def test_list_scenes_is_not_attested(database: Path) -> None:
    facade = make_facade(
        display_port=StubPort(DisplayReplied({})), factory=HubStoreFactory()
    )
    with capture_usage():
        facade.list_scenes()
    assert _metrics(database) == []


def test_timed_logs_a_success_without_request_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @Timed("render", _StepClock(0.025))
    def _run() -> SceneShown:
        return SceneShown(scene_id="private-scene")

    with caplog.at_level("INFO", logger="punt_lux.operations.timing"):
        _run()

    assert caplog.messages == ["Hub operation render succeeded (25.0 ms)"]


def test_timed_logs_a_rejection_by_its_code_not_its_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    @Timed("update", _StepClock(0.0))
    def _run() -> OpError:
        return OpError(code="not_found", reason="private-scene is unknown")

    with caplog.at_level("INFO", logger="punt_lux.operations.timing"):
        _run()

    assert caplog.messages == ["Hub operation update failed: not_found (0.0 ms)"]
    assert caplog.records[0].levelname == "INFO"


def test_timed_logs_a_raised_operation(caplog: pytest.LogCaptureFixture) -> None:
    @Timed("clear", _StepClock(0.0))
    def _run() -> None:
        raise ValueError("private scene content")

    with (
        caplog.at_level("INFO", logger="punt_lux.operations.timing"),
        pytest.raises(ValueError),
    ):
        _run()

    assert caplog.messages == ["Hub operation clear failed: raised (0.0 ms)"]
