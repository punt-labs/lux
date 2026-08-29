"""Bidirectional payload<->content-hash-key memo, keyed and forgotten together."""

from __future__ import annotations

import hashlib
from typing import Self


class DataKeyMemo:
    """Memoizes a base64 payload's content-hash key, and the reverse.

    ``TextureCache`` keys a data-sourced image on a SHA-256 of its payload
    rather than on the payload itself, since the payload can be large and the
    renderer asks for the same one every frame. The forward map avoids paying
    the hash more than once per distinct payload; the reverse map lets
    ``forget`` drop both sides together when the LRU evicts a key, so this
    memo is bounded by whatever bounds the LRU instead of growing for the
    process lifetime.
    """

    _data_to_key: dict[str, str]
    _key_to_data: dict[str, str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._data_to_key = {}
        self._key_to_data = {}
        return self

    def __len__(self) -> int:
        return len(self._data_to_key)

    def __contains__(self, data: str) -> bool:
        return data in self._data_to_key

    def key_for(self, data: str) -> str:
        """Return the memoized content-hash key for *data*, computing it if new."""
        if (key := self._data_to_key.get(data)) is None:
            key = self._data_to_key[data] = (
                f"data:{hashlib.sha256(data.encode()).hexdigest()}"
            )
            self._key_to_data[key] = data
        return key

    def forget(self, key: str) -> None:
        """Drop the memo entries for *key*, a no-op if *key* was never data-sourced."""
        if (data := self._key_to_data.pop(key, None)) is not None:
            del self._data_to_key[data]

    def clear(self) -> None:
        self._data_to_key.clear()
        self._key_to_data.clear()
