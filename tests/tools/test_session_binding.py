"""SessionBinding -- the key and host tokens one session binds and releases."""

from __future__ import annotations

from punt_lux.client_host import UNOBSERVED, ClientHost
from punt_lux.tools.server import bind_session, current_client_host, unbind_session
from punt_lux.tools.session_binding import SessionBinding


def test_binding_a_session_returns_its_two_tokens() -> None:
    binding = bind_session("sess", ClientHost("127.0.0.1"))
    try:
        assert isinstance(binding, SessionBinding)
        assert binding.key.var.get() == "sess"
        assert binding.client_host.var.get() == ClientHost("127.0.0.1")
    finally:
        unbind_session(binding)


def test_a_bound_host_is_the_calling_contexts_host() -> None:
    binding = bind_session("sess", ClientHost("::1"))
    try:
        assert current_client_host() == ClientHost("::1")
    finally:
        unbind_session(binding)


def test_releasing_restores_the_unobserved_host() -> None:
    unbind_session(bind_session("sess", ClientHost("::1")))

    assert current_client_host() == UNOBSERVED


def test_releasing_the_binding_releases_both_tokens() -> None:
    binding = bind_session("sess", ClientHost("::1"))

    binding.release()

    assert current_client_host() == UNOBSERVED
