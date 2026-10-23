"""A test run leaves no ``lux-*`` temp directory behind (the leak guard)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tests.tmp_guard import TmpGuard

_made: list[Path] = []


class TestTmpGuard:
    def test_a_directory_with_the_prefix_is_a_leftover(self, tmp_path: Path) -> None:
        (tmp_path / "lux-abc").mkdir()
        assert TmpGuard(tmp_path).leftovers() == ("lux-abc",)

    def test_assert_clean_names_the_leftover(self, tmp_path: Path) -> None:
        (tmp_path / "lux-abc").mkdir()
        with pytest.raises(AssertionError, match="lux-abc"):
            TmpGuard(tmp_path).assert_clean()

    def test_other_entries_are_not_leftovers(self, tmp_path: Path) -> None:
        (tmp_path / "other").mkdir()
        TmpGuard(tmp_path).assert_clean()


class TestEachTestHasItsOwnTempDir:
    """Two tests in file order: the second sees the first's directory gone."""

    def test_first_makes_a_directory_and_does_not_remove_it(self) -> None:
        made = Path(tempfile.mkdtemp(prefix="lux-"))
        _made.append(made)
        assert made.is_dir()

    def test_second_finds_it_removed(self) -> None:
        assert _made, "the first test of this pair did not run"
        assert not _made[0].exists()
