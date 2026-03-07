"""End-to-end tests: full display server + client lifecycle.

These are placeholder tests for when the display server exists.
Run with: uv run pytest -m e2e
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.e2e
def test_display_server_placeholder() -> None:
    """Placeholder: display server starts and accepts a connection.

    Will be implemented when the display server module exists.
    """
    # This test will be replaced with a real E2E test in Phase 1.
    # For now, verify the test infrastructure can discover and skip E2E tests.
    assert True


@pytest.mark.e2e
def test_image_scene_fixture_path(image_scene: dict[str, object]) -> None:
    """Image scene fixture creates a valid PNG file."""
    elements = image_scene["elements"]
    assert isinstance(elements, list)
    img_element = elements[0]
    assert isinstance(img_element, dict)
    assert img_element["kind"] == "image"
    path = Path(str(img_element["path"]))
    assert path.exists()
    # Verify PNG magic bytes
    assert path.read_bytes()[:4] == b"\x89PNG"
