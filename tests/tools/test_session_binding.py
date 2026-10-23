"""SessionBinding -- the key and peer tokens one session binds and releases."""

from __future__ import annotations

from punt_lux.tools.server import bind_session, current_peer, unbind_session
from punt_lux.tools.session_binding import SessionBinding


def test_binding_a_session_returns_its_two_tokens() -> None:
    binding = bind_session("sess", "127.0.0.1")
    try:
        assert isinstance(binding, SessionBinding)
        assert binding.key is not binding.peer
    finally:
        unbind_session(binding)


def test_releasing_restores_the_unbound_peer() -> None:
    unbind_session(bind_session("sess", "::1"))

    assert current_peer() is None
