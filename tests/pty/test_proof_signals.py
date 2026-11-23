"""Proof timeouts and interrupts use the normal idempotent cleanup path."""

from __future__ import annotations

import signal
from unittest.mock import Mock

import pytest

from spikes.terminal.proof_signals import ProofSignals


def test_normal_exit_cleans_up_once_and_restores_handlers() -> None:
    original = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    cleanup = Mock()
    with ProofSignals(cleanup) as owner:
        owner.close()
        owner.close()
    cleanup.assert_called_once_with()
    assert {sig: signal.getsignal(sig) for sig in original} == original


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_interrupt_cleans_up_once_despite_repeated_signals(sig: signal.Signals) -> None:
    original = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    cleanup = Mock(side_effect=lambda: signal.raise_signal(sig))
    with pytest.raises(SystemExit) as error, ProofSignals(cleanup):
        signal.raise_signal(sig)
    assert error.value.code == 128 + sig
    cleanup.assert_called_once_with()
    assert {s: signal.getsignal(s) for s in original} == original


def test_body_failure_still_cleans_up() -> None:
    cleanup = Mock()
    with pytest.raises(RuntimeError, match="proof failed"), ProofSignals(cleanup):
        raise RuntimeError("proof failed")
    cleanup.assert_called_once_with()


def test_cleanup_failure_propagates_and_restores_handlers() -> None:
    original = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    cleanup = Mock(side_effect=OSError("cleanup failed"))
    with pytest.raises(OSError, match="cleanup failed"), ProofSignals(cleanup):
        pass
    cleanup.assert_called_once_with()
    assert {sig: signal.getsignal(sig) for sig in original} == original
