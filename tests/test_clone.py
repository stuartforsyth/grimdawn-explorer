"""Tests for character cloning (SPEC §5.3).

The invariant under test is that the source is never modified — including when the
clone fails part-way — and that nothing lands in the save folder until the rebuilt
save has been re-parsed and checked.
"""

from __future__ import annotations

import pytest

from gd_assistant.savefile import clone
from gd_assistant.savefile.clone import (
    CloneError,
    GameRunningError,
    clone_character,
    plan_clone,
    validate_character_name,
)
from gd_assistant.savefile.parser import parse_character

from .test_savefile_parser import build_save


@pytest.fixture(autouse=True)
def _game_not_running(monkeypatch):
    """Default to "game closed" so tests exercise the happy path deliberately."""
    monkeypatch.setattr(clone, "find_running_game", lambda: None)


@pytest.fixture
def save_dir(tmp_path):
    """A save folder holding one character with the usual map/quest tree."""
    def _make(name: str = "Archon", **kwargs):
        char = tmp_path / "main" / f"_{name}"
        (char / "levels_world001.map" / "Normal").mkdir(parents=True)
        (char / "player.gdc").write_bytes(build_save(name=name, **kwargs))
        (char / "levels_world001.map" / "Normal" / "quests.gdd").write_bytes(b"quest")
        (char / "levels_world001.map" / "Normal" / "map.fow").write_bytes(b"fog")
        return char
    return _make


def test_rename_clone_creates_new_character(save_dir):
    source = save_dir("Archon", skills=[("records/skills/a.dbr", 5)])
    original = (source / "player.gdc").read_bytes()

    plan = plan_clone(source, new_name="Archon Two")
    clone_character(plan)

    assert plan.destination.name == "_Archon Two"
    cloned = parse_character(plan.destination / "player.gdc")
    assert cloned.name == "Archon Two"
    assert cloned.skills[0].points == 5
    # The source is untouched, byte for byte.
    assert (source / "player.gdc").read_bytes() == original


def test_clone_copies_the_whole_character_folder(save_dir):
    """Copying only the .gdc would lose quest progress and the explored map."""
    source = save_dir()
    plan = plan_clone(source, new_name="Copy")
    clone_character(plan)

    quests = plan.destination / "levels_world001.map" / "Normal" / "quests.gdd"
    assert quests.read_bytes() == b"quest"
    assert (plan.destination / "levels_world001.map" / "Normal" / "map.fow").exists()


def test_folder_only_clone_writes_no_save_bytes(save_dir):
    """"Same name, different folder" needs no rewriting at all."""
    source = save_dir("Archon")
    original = (source / "player.gdc").read_bytes()

    plan = plan_clone(source, folder_name="Archon Backup")
    assert plan.rename_in_file is False
    clone_character(plan)

    assert plan.destination.name == "_Archon Backup"
    assert (plan.destination / "player.gdc").read_bytes() == original
    assert parse_character(plan.destination / "player.gdc").name == "Archon"


def test_refuses_to_overwrite_an_existing_folder(save_dir):
    source = save_dir("Archon")
    save_dir("Taken")
    plan = plan_clone(source, new_name="Taken")
    with pytest.raises(CloneError, match="already exists"):
        clone_character(plan)


def test_refuses_while_the_game_is_running(save_dir, monkeypatch):
    monkeypatch.setattr(clone, "find_running_game", lambda: "grim dawn.exe")
    source = save_dir()
    plan = plan_clone(source, new_name="Nope")
    with pytest.raises(GameRunningError, match="running"):
        clone_character(plan)
    assert not plan.destination.exists()


def test_game_running_can_be_overridden(save_dir, monkeypatch):
    monkeypatch.setattr(clone, "find_running_game", lambda: "grim dawn.exe")
    source = save_dir()
    plan = plan_clone(source, new_name="Forced")
    clone_character(plan, allow_game_running=True)
    assert plan.destination.exists()


@pytest.mark.parametrize("bad", ["", "   ", "a/b", "a\\b", "a:b", "a\0b", ".", ".."])
def test_rejects_unusable_names(bad):
    with pytest.raises(CloneError):
        validate_character_name(bad)


def test_plan_requires_a_target_name(save_dir):
    source = save_dir()
    with pytest.raises(CloneError, match="either new_name or folder_name"):
        plan_clone(source)
    with pytest.raises(CloneError, match="not both"):
        plan_clone(source, new_name="A", folder_name="B")


def test_plan_rejects_a_folder_without_a_save(tmp_path):
    empty = tmp_path / "_Empty"
    empty.mkdir()
    with pytest.raises(CloneError, match="does not contain"):
        plan_clone(empty, new_name="X")


def test_failed_clone_leaves_nothing_behind(save_dir, monkeypatch):
    """A verification failure must not leave a partial character in the save dir."""
    source = save_dir()
    plan = plan_clone(source, new_name="Broken")
    monkeypatch.setattr(
        clone, "_verify", lambda *a, **k: (_ for _ in ()).throw(CloneError("boom"))
    )
    with pytest.raises(CloneError, match="boom"):
        clone_character(plan)

    assert not plan.destination.exists()
    # No staging directories survive either.
    leftovers = [p for p in plan.destination.parent.iterdir() if p.name.startswith(".gd-clone-")]
    assert leftovers == []


def test_clone_into_a_different_save_dir(save_dir, tmp_path):
    source = save_dir()
    elsewhere = tmp_path / "other"
    plan = plan_clone(source, new_name="Away", save_dir=elsewhere)
    clone_character(plan)
    assert (elsewhere / "_Away" / "player.gdc").exists()


def test_cloned_character_is_discoverable(save_dir, tmp_path):
    """A clone must show up in the character list the UI uses."""
    from gd_assistant.savefile import locator

    source = save_dir("Archon")
    clone_character(plan_clone(source, new_name="Second"))
    names = [p.name for p in locator.list_characters(tmp_path)]
    assert names == ["_Archon", "_Second"]
