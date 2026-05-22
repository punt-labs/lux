"""Unit tests for the ``Snapshot`` class."""

from __future__ import annotations

from pathlib import Path

import pytest

from .snapshot import REPO_ROOT_TOKEN, Snapshot, repo_root, substitute_paths


@pytest.fixture
def sample_snapshot() -> Snapshot:
    return Snapshot(
        tool="show",
        inputs=(("scene_id", "s1"), ("elements", [{"kind": "text", "id": "t1"}])),
        setup={"display_running": True, "client": {"show": {"return": "ack:s1"}}},
        response="ack:s1",
    )


class TestRoundtrip:
    def test_to_file_then_from_file(
        self, tmp_path: Path, sample_snapshot: Snapshot
    ) -> None:
        path = tmp_path / "snap.json"
        sample_snapshot.to_file(path)
        assert Snapshot.from_file(path) == sample_snapshot

    def test_to_file_is_pretty_printed(
        self, tmp_path: Path, sample_snapshot: Snapshot
    ) -> None:
        path = tmp_path / "snap.json"
        sample_snapshot.to_file(path)
        text = path.read_text(encoding="utf-8")
        assert "\n" in text
        assert text.endswith("\n")


class TestMatches:
    def test_exact_match(self, sample_snapshot: Snapshot) -> None:
        assert sample_snapshot.matches("ack:s1")

    def test_exact_mismatch(self, sample_snapshot: Snapshot) -> None:
        assert not sample_snapshot.matches("ack:s2")

    def test_json_response_compares_literally(self) -> None:
        # JSON braces are regex metacharacters but Snapshot.matches is now
        # strict string equality — the comparison cannot misfire on them.
        snap = Snapshot(
            tool="inspect_scene",
            inputs=(("scene_id", "s1"),),
            setup={},
            response='{"scene_id": "s1", "elements": []}',
        )
        assert snap.matches('{"scene_id": "s1", "elements": []}')
        assert not snap.matches('{"scene_id": "s2", "elements": []}')


class TestDiff:
    def test_diff_empty_on_match(self, sample_snapshot: Snapshot) -> None:
        assert sample_snapshot.diff("ack:s1") == ""

    def test_diff_shows_change(self, sample_snapshot: Snapshot) -> None:
        diff = sample_snapshot.diff("ack:s2")
        assert "show (recorded)" in diff
        assert "show (observed)" in diff
        assert "ack:s1" in diff
        assert "ack:s2" in diff


class TestDescribeMismatch:
    def test_falls_back_to_repr_when_diff_empty(self) -> None:
        # describe_mismatch never returns "" — it falls back to the repr
        # of both sides so a failing assertion message is never silent.
        snap = Snapshot(tool="x", inputs=(), setup={}, response="")
        description = snap.describe_mismatch("")
        assert "expected=''" in description
        assert "observed=''" in description

    def test_returns_diff_when_diff_is_non_empty(
        self, sample_snapshot: Snapshot
    ) -> None:
        result = sample_snapshot.describe_mismatch("ack:s2")
        assert "show (recorded)" in result


class TestRepoRootSubstitution:
    def test_to_file_replaces_local_path_with_token(self, tmp_path: Path) -> None:
        local = str(repo_root())
        snap = Snapshot(
            tool="display_mode",
            inputs=(("repo", f"{local}/subdir"),),
            setup={"display_running": False},
            response="display:off",
        )
        target = tmp_path / "snap.json"
        snap.to_file(target)
        on_disk = target.read_text(encoding="utf-8")
        assert local not in on_disk
        assert REPO_ROOT_TOKEN in on_disk

    def test_from_file_substitutes_token_for_local_root(self, tmp_path: Path) -> None:
        local = str(repo_root())
        target = tmp_path / "snap.json"
        snap = Snapshot(
            tool="display_mode",
            inputs=(("repo", f"{local}/x"),),
            setup={"display_running": False},
            response="display:off",
        )
        snap.to_file(target)
        loaded = Snapshot.from_file(target)
        assert dict(loaded.inputs)["repo"] == f"{local}/x"

    def test_substitute_paths_walks_nested_structures(self) -> None:
        result = substitute_paths({"a": ["x", {"b": "x/y"}, 42], "c": "x"}, "x", "Z")
        assert result == {"a": ["Z", {"b": "Z/y"}, 42], "c": "Z"}
