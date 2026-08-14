"""Locator tests — character folders may be nested under `main/` or `user/` (SPEC §4)."""

from __future__ import annotations

from pathlib import Path

from gd_assistant.savefile import locator


def _make_character(parent: Path, name: str) -> Path:
    """Create a minimal `_<name>` character folder holding a `player.gdc`."""
    char = parent / f"_{name}"
    char.mkdir(parents=True)
    (char / "player.gdc").write_bytes(b"\x00")
    return char


def test_flat_layout(tmp_path: Path) -> None:
    save = tmp_path / "save"
    _make_character(save, "Flat")
    assert locator.is_save_dir(save)
    assert [p.name for p in locator.list_characters(save)] == ["_Flat"]


def test_nested_main_layout(tmp_path: Path) -> None:
    # The retail layout that the original locator missed entirely.
    save = tmp_path / "save"
    _make_character(save / "main", "Archon")
    assert locator.is_save_dir(save)
    assert [p.name for p in locator.list_characters(save)] == ["_Archon"]


def test_main_and_user_are_merged_and_sorted(tmp_path: Path) -> None:
    save = tmp_path / "save"
    _make_character(save / "main", "beta")
    _make_character(save / "user", "Alpha")
    _make_character(save, "Gamma")
    # Sorted by name case-insensitively, regardless of which subdir they came from.
    assert [p.name for p in locator.list_characters(save)] == ["_Alpha", "_beta", "_Gamma"]


def test_character_without_player_gdc_is_ignored(tmp_path: Path) -> None:
    save = tmp_path / "save"
    (save / "main" / "_Empty").mkdir(parents=True)
    assert locator.list_characters(save) == []


def test_empty_dir_is_not_a_save_dir(tmp_path: Path) -> None:
    save = tmp_path / "save"
    save.mkdir()
    assert not locator.is_save_dir(save)
    assert locator.list_characters(save) == []


def test_missing_dir_is_handled(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert not locator.is_save_dir(missing)
    assert locator.list_characters(missing) == []
