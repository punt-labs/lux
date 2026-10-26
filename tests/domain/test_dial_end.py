"""DialEnd -- the first cause recorded wins; the Hub only asks; the reader decides."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_end import DialEnd
from punt_lux.domain.hub.reply_sink import ReplySink


class TestRecording:
    def test_the_first_cause_recorded_stands(self) -> None:
        end = DialEnd()

        assert end.record("display") is True
        assert end.record("unresponsive") is False
        assert end.cause == "display"

    def test_a_new_end_has_no_cause_and_is_not_closing(self) -> None:
        end = DialEnd()

        assert (end.cause, end.closing) == (None, None)


class TestTheHubsRequest:
    def test_a_request_records_no_cause_but_the_dial_is_closing_for_the_hub(
        self,
    ) -> None:
        end = DialEnd()

        assert end.ask_hub() is True
        assert end.ask_hub() is False
        assert end.cause is None
        assert end.closing == "hub"

    def test_a_recorded_cause_is_what_a_closing_dial_reports_even_after_a_request(
        self,
    ) -> None:
        end = DialEnd()
        end.record("display")
        end.ask_hub()

        assert end.closing == "display"


class TestDeciding:
    def test_the_end_of_file_a_reader_saw_is_the_displays_even_after_a_request(
        self,
    ) -> None:
        end = DialEnd()
        end.ask_hub()

        assert end.decide(saw_end=True) == "display"

    def test_a_request_with_no_end_seen_is_the_hubs(self) -> None:
        end = DialEnd()
        end.ask_hub()

        assert end.decide(saw_end=False) == "hub"

    def test_a_recorded_cause_stands_over_what_was_seen(self) -> None:
        end = DialEnd()
        end.record("unresponsive")

        assert end.decide(saw_end=True) == "unresponsive"
        assert end.cause == "unresponsive"

    def test_a_dial_nothing_ended_has_no_cause_to_decide(self) -> None:
        with pytest.raises(ValueError, match="no cause to decide"):
            DialEnd().decide(saw_end=False)

    def test_a_decision_is_made_once(self) -> None:
        end = DialEnd()
        end.ask_hub()
        end.decide(saw_end=False)

        assert end.decide(saw_end=True) == "hub"


class TestTheSinkThatOwnsOne:
    def test_a_hub_request_refuses_writes_but_records_nothing(self) -> None:
        sink = ReplySink()

        assert sink.request_hub() is True

        assert sink.ended is None
        assert sink.closing == "hub"
        with pytest.raises(ConnectionClosedError):
            sink.owe_ack("a")

    def test_a_request_fails_a_waiter_at_once(self) -> None:
        sink = ReplySink()
        ping = sink.expect_pong(1.0)
        sink.request_hub()

        with pytest.raises(ConnectionClosedError):
            sink.await_reply(ping, 5.0)

    def test_deciding_after_a_request_records_the_hubs_cause(self) -> None:
        sink = ReplySink()
        sink.request_hub()

        assert sink.decide(saw_end=False) == "hub"
        assert sink.ended == "hub"

    def test_the_ledger_is_not_taken_until_a_cause_is_decided(self) -> None:
        sink = ReplySink()
        sink.request_hub()

        with pytest.raises(ValueError, match="no ledger to capture"):
            sink.capture()
