"""Unit tests for :func:`punt_lux.cli._identity_errors.describe_identity_error`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from punt_lux.cli._identity_errors import describe_identity_error
from punt_lux.domain.hub.client_identity import ClientIdentity


def test_maps_the_bad_field_to_its_flag_name() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ClientIdentity(kind="bogus", name="x")  # type: ignore[arg-type]

    message = describe_identity_error(exc_info.value)

    assert "--kind" in message


def test_joins_multiple_errors_with_a_semicolon() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ClientIdentity(kind="bogus", name="")  # type: ignore[arg-type]

    message = describe_identity_error(exc_info.value)

    assert "--kind" in message
    assert "--name" in message
    assert "; " in message
