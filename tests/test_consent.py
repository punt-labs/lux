"""Tests for the consent dialog state machine.

These test construction and state transitions — not the ImGui draw calls,
which require a running display.
"""

from __future__ import annotations

from punt_lux.consent import ConsentDialog, ConsentResult


class TestConsentResult:
    def test_has_three_members(self) -> None:
        members = list(ConsentResult)
        assert len(members) == 3
        assert ConsentResult.PENDING in members
        assert ConsentResult.ALLOWED in members
        assert ConsentResult.DENIED in members


class TestConsentDialog:
    def test_initial_state_is_pending(self) -> None:
        dialog = ConsentDialog("x = 1")
        assert dialog.result == ConsentResult.PENDING

    def test_source_stored(self) -> None:
        dialog = ConsentDialog("print('hello')")
        assert dialog.source == "print('hello')"

    def test_source_lines_cached(self) -> None:
        dialog = ConsentDialog("a = 1\nb = 2\nc = 3")
        assert dialog.source_lines == ["a = 1", "b = 2", "c = 3"]

    def test_warnings_default_empty(self) -> None:
        dialog = ConsentDialog("x = 1")
        assert dialog.warnings == []

    def test_warnings_stored(self) -> None:
        warnings = ["Imports `os`", "Calls `open()`"]
        dialog = ConsentDialog("import os", warnings=warnings)
        assert dialog.warnings == warnings

    def test_warnings_none_becomes_empty(self) -> None:
        dialog = ConsentDialog("x = 1", warnings=None)
        assert dialog.warnings == []

    def test_modal_title(self) -> None:
        assert "custom code" in ConsentDialog.MODAL_TITLE.lower()

    def test_created_at_set(self) -> None:
        dialog = ConsentDialog("x = 1")
        assert isinstance(dialog.created_at, float)
