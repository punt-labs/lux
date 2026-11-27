"""IdentityHeaderField — one field, one header, both wire directions."""

from __future__ import annotations

from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.model.identity_header_field import IdentityHeaderField

_NAME = IdentityHeaderField("name", "X-Lux-Client-Name")
_TTL = IdentityHeaderField("lease_ttl", "X-Lux-Client-Lease-Ttl", is_encoded=False)
_REPO = IdentityHeaderField("repo", "X-Lux-Client-Repo")


def test_free_text_renders_percent_encoded_and_reads_back() -> None:
    identity = ClientIdentity(kind="cli", name="büro", host="h")
    text = _NAME.render(identity)
    assert text.isascii()
    assert _NAME.read({"X-Lux-Client-Name": text}) == "büro"


def test_a_number_renders_as_formatted_not_encoded() -> None:
    identity = ClientIdentity(kind="app", name="voxd", host="h", lease_ttl=30.0)
    assert _TTL.render(identity) == "30.0"


def test_an_absent_value_renders_blank() -> None:
    assert _REPO.render(ClientIdentity(kind="cli", name="x", host="h")) == ""


def test_a_missing_or_blank_header_reads_blank() -> None:
    assert _REPO.read({}) == ""
    assert _REPO.read({"X-Lux-Client-Repo": "   "}) == ""


def test_the_field_names_its_identity_field_and_header() -> None:
    assert (_REPO.name, _REPO.header) == ("repo", "X-Lux-Client-Repo")
