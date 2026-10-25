"""DisplayLog -- the bounded record of recent events and errors, and its reports."""

from __future__ import annotations

from punt_lux.display.display_log import DisplayLog


class TestTheEventsChannel:
    def test_it_keeps_only_the_last_200(self) -> None:
        log = DisplayLog()
        for i in range(250):
            log.record_event({"index": i})

        report = log.report("events", 1000)

        assert report["total_buffered"] == 200
        assert [e["index"] for e in report["events"]] == list(range(50, 250))

    def test_it_reports_fifty_by_default(self) -> None:
        log = DisplayLog()
        for i in range(80):
            log.record_event({"index": i})

        assert len(log.report("events")["events"]) == 50

    def test_a_count_limits_what_is_returned_not_what_is_kept(self) -> None:
        log = DisplayLog()
        for i in range(20):
            log.record_event({"index": i})

        report = log.report("events", 5)

        assert [e["index"] for e in report["events"]] == [15, 16, 17, 18, 19]
        assert report["total_buffered"] == 20


class TestTheErrorsChannel:
    def test_it_keeps_only_the_last_100(self) -> None:
        log = DisplayLog()
        for i in range(150):
            log.record_error("error", f"msg-{i}", f"ctx-{i}")

        report = log.report("errors", 1000)

        assert report["total_buffered"] == 100
        assert report["errors"][0]["message"] == "msg-50"

    def test_it_reports_twenty_by_default(self) -> None:
        log = DisplayLog()
        for i in range(30):
            log.record_error("error", f"msg-{i}")

        assert len(log.report("errors")["errors"]) == 20

    def test_an_error_carries_its_severity_context_and_a_timestamp(self) -> None:
        log = DisplayLog()

        log.record_error("warning", "boom", "query:x")

        (entry,) = log.report("errors")["errors"]
        assert (entry["severity"], entry["message"], entry["context"]) == (
            "warning",
            "boom",
            "query:x",
        )
        assert entry["timestamp"] > 0


class TestTheChannelsAreSeparate:
    def test_an_event_is_not_an_error(self) -> None:
        log = DisplayLog()

        log.record_event({"index": 1})

        assert log.report("errors") == {"errors": [], "total_buffered": 0}

    def test_a_report_ignores_params_it_does_not_know(self) -> None:
        log = DisplayLog()

        assert log.report("events", None, stray=1) == {
            "events": [],
            "total_buffered": 0,
        }
