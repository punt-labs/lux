"""Ids are never reused; labels are unique among live sessions; specs are listed."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from punt_lux.pty.session_ids import SessionIds
from punt_lux.pty.session_labels import SessionLabels
from punt_lux.pty.session_spec import SessionSpec
from punt_lux.wire.stream.new_request import NewRequest


@dataclass(frozen=True)
class Held:
    """A session id holding a label."""

    name: str
    label: str


def test_ids_count_up_under_one_boot_value() -> None:
    ids = SessionIds("ab12")
    assert [ids.next(), ids.next()] == ["tab12.1", "tab12.2"]


def test_a_new_boot_value_never_collides_with_an_old_one() -> None:
    assert SessionIds.fresh().next() != SessionIds.fresh().next()


@pytest.mark.parametrize("boot", ["", "XYZ", "ab 12", "a" * 17])
def test_a_malformed_boot_value_is_refused(boot: str) -> None:
    with pytest.raises(ValueError, match="boot value"):
        SessionIds(boot)


def test_default_labels_skip_live_ones() -> None:
    labels = SessionLabels()
    labels.claim(Held("t0.1", "Terminal 1"))
    assert labels.unique("") == "Terminal 2"


def test_a_released_label_can_be_requested_again() -> None:
    labels = SessionLabels()
    labels.claim(Held("t0.1", "work"))
    with pytest.raises(ValueError, match="already in use"):
        labels.unique("work")
    labels.release("t0.1")
    assert labels.unique("work") == "work"


def test_claiming_a_live_label_is_refused() -> None:
    labels = SessionLabels()
    labels.claim(Held("t0.1", "work"))
    with pytest.raises(ValueError, match="already in use"):
        labels.claim(Held("t0.2", "work"))


def test_a_spec_for_an_unlisted_launcher_cannot_exist() -> None:
    SessionSpec("t0.1", "work", NewRequest(1))
    with pytest.raises(ValueError, match="unknown launcher"):
        SessionSpec("t0.2", "work", NewRequest(2, launcher="htop"))


def test_a_spec_names_its_session_in_a_listing() -> None:
    spec = SessionSpec("t0.1", "work", NewRequest(1, "work"))
    assert spec.identity() == {"session": "t0.1", "label": "work", "launcher": ""}
