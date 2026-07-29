"""HttpCall — the bundled request the transport sends.

The two constructors name the two kinds of call the client makes, and
``wire_headers`` decides the content-type by whether a body is present.
"""

from __future__ import annotations

from pydantic import BaseModel

from punt_lux.rest_http_call import HttpCall

_HEADERS = {"X-Lux-Client-Name": "vox"}


class _Body(BaseModel):
    scene_id: str


def test_write_is_a_put_carrying_the_serialized_body() -> None:
    call = HttpCall.write("/scenes/s1", _Body(scene_id="s1"), _HEADERS)
    assert call.method == "PUT"
    assert call.path == "/scenes/s1"
    assert call.body == b'{"scene_id":"s1"}'
    assert call.headers == _HEADERS


def test_read_is_a_get_with_no_body() -> None:
    call = HttpCall.read("/display/ping", _HEADERS)
    assert call.method == "GET"
    assert call.body is None
    assert call.headers == _HEADERS


def test_wire_headers_adds_content_type_only_for_a_body() -> None:
    write = HttpCall.write("/scenes/s1", _Body(scene_id="s1"), _HEADERS)
    read = HttpCall.read("/display/ping", _HEADERS)
    assert write.wire_headers() == {**_HEADERS, "Content-Type": "application/json"}
    assert read.wire_headers() == _HEADERS  # no body, no content-type


def test_wire_headers_does_not_mutate_the_stored_headers() -> None:
    # The content-type is added to a copy, so the identity headers stay pristine.
    call = HttpCall.write("/scenes/s1", _Body(scene_id="s1"), _HEADERS)
    call.wire_headers()
    assert "Content-Type" not in call.headers
