"""ImageSourceSpec resolves the wire path/data one-of into a discriminated source."""

from __future__ import annotations

import pytest

from punt_lux.protocol.elements.image_source import DataImage, PathImage
from punt_lux.protocol.elements.image_source_spec import ImageSourceSpec


class TestResolve:
    def test_path_only_resolves_to_path_image(self) -> None:
        source = ImageSourceSpec("/a.png", None).resolve()
        assert isinstance(source, PathImage)
        assert (source.path, source.data) == ("/a.png", None)

    def test_data_only_resolves_to_data_image(self) -> None:
        source = ImageSourceSpec(None, "blob").resolve()
        assert isinstance(source, DataImage)
        assert (source.data, source.path) == ("blob", None)

    def test_neither_is_refused(self) -> None:
        with pytest.raises(ValueError, match="requires either"):
            ImageSourceSpec(None, None).resolve()

    def test_both_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not both"):
            ImageSourceSpec("/a.png", "blob").resolve()
