"""FocusRequest — the one-shot focus, and who is entitled to withdraw it.

Two properties carry this class. Focus is *spent* when it is consumed, so a
frame is focused on the render after the request and not again; and a frame
withdrawing its own claim must not withdraw another frame's, which is the
invariant that used to be written out at each of the three places a frame stops
being paintable.
"""

from __future__ import annotations

from punt_lux.display.replica.focus_request import FocusRequest


class TestConsume:
    def test_nothing_is_awaiting_focus_to_begin_with(self) -> None:
        assert FocusRequest().consume("f1") is False

    def test_the_frame_that_asked_is_the_frame_that_gets_it(self) -> None:
        focus = FocusRequest()
        focus.ask("f1")
        assert focus.consume("f1") is True

    def test_consuming_spends_the_request(self) -> None:
        """The renderer asks once per render; a standing request would refocus."""
        focus = FocusRequest()
        focus.ask("f1")

        assert focus.consume("f1") is True
        assert focus.consume("f1") is False

    def test_another_frame_asking_does_not_consume_it(self) -> None:
        focus = FocusRequest()
        focus.ask("f1")

        assert focus.consume("f2") is False
        assert focus.consume("f1") is True, "f1's request was spent by f2's query"

    def test_a_later_request_displaces_an_earlier_one(self) -> None:
        """At most one frame is ever awaiting focus, so the newest gesture wins."""
        focus = FocusRequest()
        focus.ask("f1")
        focus.ask("f2")

        assert focus.consume("f1") is False
        assert focus.consume("f2") is True


class TestRelease:
    def test_a_frame_withdraws_its_own_claim(self) -> None:
        focus = FocusRequest()
        focus.ask("f1")

        focus.release("f1")

        assert focus.consume("f1") is False

    def test_a_frame_does_not_withdraw_another_frames_claim(self) -> None:
        """The invariant the three inlined copies existed to hold."""
        focus = FocusRequest()
        focus.ask("f2")

        focus.release("f1")

        assert focus.consume("f2") is True

    def test_releasing_with_nothing_outstanding_is_a_noop(self) -> None:
        focus = FocusRequest()
        focus.release("f1")  # no raise
        assert focus.consume("f1") is False


class TestClear:
    def test_clear_withdraws_whatever_request_stands(self) -> None:
        focus = FocusRequest()
        focus.ask("f1")

        focus.clear()

        assert focus.consume("f1") is False

    def test_clear_on_an_empty_request_is_a_noop(self) -> None:
        FocusRequest().clear()  # no raise
