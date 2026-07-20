"""Unit tests for StoreLock — reentrancy and reader/writer exclusion."""

from __future__ import annotations

import threading

from punt_lux.domain.hub.store_lock import StoreLock


def test_read_and_write_share_one_reentrant_slot() -> None:
    lock = StoreLock()
    # Nested acquisition re-enters — replace_scene calling apply must not deadlock.
    with lock.write(), lock.write(), lock.read():
        pass


def test_a_second_thread_blocks_while_the_lock_is_held() -> None:
    lock = StoreLock()
    held = threading.Event()
    release = threading.Event()
    acquired_second = threading.Event()

    def hold_writer() -> None:
        with lock.write():
            held.set()
            release.wait(timeout=2.0)

    def take_reader() -> None:
        held.wait(timeout=2.0)
        with lock.read():
            acquired_second.set()

    writer = threading.Thread(target=hold_writer)
    reader = threading.Thread(target=take_reader)
    writer.start()
    reader.start()
    try:
        held.wait(timeout=2.0)
        # The reader cannot enter while the writer holds the slot.
        assert not acquired_second.wait(timeout=0.2)
        release.set()
        # Once the writer releases, the reader proceeds.
        assert acquired_second.wait(timeout=2.0)
    finally:
        release.set()
        writer.join(timeout=2.0)
        reader.join(timeout=2.0)


def test_an_exception_inside_a_held_block_releases_the_lock() -> None:
    lock = StoreLock()

    class _BoomError(Exception):
        pass

    try:
        with lock.write():
            raise _BoomError
    except _BoomError:
        pass

    # The lock was released despite the raise — a fresh acquire succeeds at once.
    acquired = threading.Event()

    def take() -> None:
        with lock.write():
            acquired.set()

    t = threading.Thread(target=take)
    t.start()
    t.join(timeout=2.0)
    assert acquired.is_set()
