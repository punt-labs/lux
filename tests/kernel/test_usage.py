"""Verify Lux's usage schema, private local storage and failure isolation."""

from __future__ import annotations

import sqlite3
import stat
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from punt_observe.telemetry import TelemetryConfig

from punt_lux.kernel.usage import capture_usage, record_first_paint, record_operation
from punt_lux.operations.timing import Timed

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    for key in ("PUNT_TELEMETRY", "LUX_TELEMETRY", "PUNT_TELEMETRY_EXPORTER"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path / ".punt-labs" / "lux" / "telemetry.db"


def test_usage_rejects_content_and_never_writes_diagnostics(database: Path) -> None:
    with capture_usage():
        record_operation("customer payload", 1.0, failed=False)
        record_operation("render", 2.0, failed=False)

    with closing(sqlite3.connect(database)) as db:
        [(count, duration, attributes)] = db.execute(
            "SELECT count, sum, attributes FROM metric_points"
        ).fetchall()
    assert (count, duration) == (1, 2.0)
    assert "customer payload" not in attributes
    assert not (database.parent / "logs").exists()


def test_first_paint_records_no_scene_attributes(database: Path) -> None:
    with capture_usage():
        record_first_paint(20.0)

    with closing(sqlite3.connect(database)) as db:
        [(count, duration, attributes)] = db.execute(
            "SELECT count, sum, attributes FROM metric_points"
        ).fetchall()
    assert (count, duration, attributes) == (1, 20.0, "{}")


def test_hub_listener_thread_shares_daemon_capture(database: Path) -> None:
    with capture_usage(), ThreadPoolExecutor(max_workers=1) as listener:
        submitted = listener.submit(
            record_operation, "show_client_details", 2.0, failed=False
        )
        submitted.result()

    with closing(sqlite3.connect(database)) as db:
        [(duration, attributes)] = db.execute(
            "SELECT sum, attributes FROM metric_points"
        ).fetchall()
    assert duration == 2.0
    assert "show_client_details" in attributes


@pytest.mark.parametrize("off_switch", ["PUNT_TELEMETRY", "LUX_TELEMETRY", "config"])
def test_off_switch_prevents_local_capture(
    database: Path, monkeypatch: pytest.MonkeyPatch, off_switch: str
) -> None:
    if off_switch != "config":
        monkeypatch.setenv(off_switch, "off")
    with capture_usage(TelemetryConfig(enabled=off_switch != "config")):
        record_operation("render", 1.0, failed=False)
    assert not database.parent.exists()


def test_store_and_sidecars_are_private(database: Path) -> None:
    with capture_usage():
        assert stat.S_IMODE(database.parent.stat().st_mode) == 0o700
        for suffix in ("", "-wal", "-shm"):
            path = database.with_name(database.name + suffix)
            assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_sqlite_export_failure_does_not_change_operation_result(database: Path) -> None:
    @Timed("clear")
    def operation() -> str:
        return "result"

    with capture_usage():
        with closing(sqlite3.connect(database)) as db, db:
            db.execute("DROP TABLE metric_points")
        assert operation() == "result"

    with closing(sqlite3.connect(database)) as db:
        assert (
            db.execute(
                "SELECT name FROM sqlite_master WHERE name = 'metric_points'"
            ).fetchall()
            == []
        )
