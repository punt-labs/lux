"""The REST error-body renderer — one decoded body to one human reason."""

from __future__ import annotations

from punt_lux.rest_error_body import ErrorBody


def test_a_semantic_op_error_detail_is_the_reason() -> None:
    assert ErrorBody(b'{"detail":"nope"}').reason(422) == "nope"


def test_a_located_list_detail_is_flattened() -> None:
    body = b'{"detail":[{"loc":["body","layout"],"msg":"bad value","type":"x"}]}'
    assert ErrorBody(body).reason(422) == "bad value"


def test_a_multi_item_located_detail_joins_the_messages() -> None:
    body = b'{"detail":[{"msg":"first"},{"msg":"second"}]}'
    assert ErrorBody(body).reason(422) == "first; second"


def test_a_dict_error_body_without_detail_preserves_its_content() -> None:
    assert ErrorBody(b'{"error":"boom"}').reason(502) == '{"error":"boom"}'


def test_a_non_json_body_is_its_own_reason() -> None:
    assert ErrorBody(b"boom").reason(500) == "boom"


def test_an_empty_body_falls_back_to_the_status_line() -> None:
    assert ErrorBody(b"").reason(503) == "HTTP 503"


def test_a_blank_detail_falls_back_to_the_body() -> None:
    body = b'{"detail":""}'
    assert ErrorBody(body).reason(502) == body.decode()


def test_a_non_utf8_body_maps_cleanly_without_raising() -> None:
    raw = b"\xff\xfe boom"
    assert ErrorBody(raw).reason(502) == raw.decode(errors="replace")


def test_snippet_folds_whitespace_and_drops_non_printables() -> None:
    assert ErrorBody(b"a\t b\n\nc").snippet() == "a b c"


def test_snippet_truncates_a_huge_body_with_a_marker() -> None:
    snippet = ErrorBody(b"A" * 5000).snippet()
    assert snippet.endswith("…")
    assert len(snippet) < 200
