"""Headless tests for the Character tab and the Save As New Character dialog.

Runs against synthetic saves under offscreen Qt, so it needs neither an installed
game nor a display. The knowledge base is optional — name resolution degrades to
record basenames without it — so these tests avoid asserting on KB-derived text.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from gd_assistant.savefile import clone as clone_mod

from .test_savefile_parser import build_save


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _game_not_running(monkeypatch):
    monkeypatch.setattr(clone_mod, "find_running_game", lambda: None)


@pytest.fixture
def save_dir(tmp_path):
    """A save folder with two characters, built the way Grim Dawn lays them out."""
    for name, level in (("Archon", 57), ("Bale", 36)):
        char = tmp_path / "main" / f"_{name}"
        (char / "levels_world001.map" / "Normal").mkdir(parents=True)
        (char / "player.gdc").write_bytes(
            build_save(name=name, level=level, skills=[("records/skills/a.dbr", 5)])
        )
        (char / "levels_world001.map" / "Normal" / "quests.gdd").write_bytes(b"q")
    return tmp_path


@pytest.fixture
def tab(app, save_dir, tmp_path):
    from gd_assistant.config.settings import Settings
    from gd_assistant.ui.character import CharacterTab

    settings = Settings(save_dir=str(save_dir))
    settings._path = tmp_path / "config.json"
    return CharacterTab(settings=settings)


def test_lists_characters_from_the_save_folder(tab):
    labels = [tab._picker.itemText(i) for i in range(tab._picker.count())]
    assert [label.split()[0] for label in labels] == ["Archon", "Bale"]


def test_picker_labels_carry_name_and_level(tab):
    """The list is built from headers alone, so it must still show name and level."""
    labels = [tab._picker.itemText(i) for i in range(tab._picker.count())]
    assert labels[0].startswith("Archon  L57")
    assert labels[1].startswith("Bale  L36")


def test_picker_label_survives_an_unreadable_save(tab, save_dir):
    (save_dir / "main" / "_Bale" / "player.gdc").write_bytes(b"nonsense")
    tab._rescan()
    labels = [tab._picker.itemText(i) for i in range(tab._picker.count())]
    assert "Bale  (unreadable)" in labels


def test_select_character_is_label_independent(tab):
    assert tab.select_character("bale") is True
    assert tab.selected_path().name == "_Bale"
    assert tab.select_character("nobody") is False


def test_shows_the_selected_character(tab):
    tab.select_character("Archon")
    assert "Archon" in tab._summary.text()
    assert "level 57" in tab._summary.text()
    assert tab._skills.rowCount() == 1


def test_switching_character_updates_the_view(tab):
    tab.select_character("Bale")
    assert "level 36" in tab._summary.text()


def test_unreadable_save_is_reported_not_crashed(tab, save_dir):
    (save_dir / "main" / "_Archon" / "player.gdc").write_bytes(b"garbage" * 10)
    tab.select_character("Bale")
    tab.select_character("Archon")
    assert "Could not read this save" in tab._summary.text()
    assert tab._skills.rowCount() == 0


# -- the dialog -------------------------------------------------------------


@pytest.fixture
def dialog(app, tab):
    from gd_assistant.ui.save_as_dialog import SaveAsNewCharacterDialog

    tab.select_character("Archon")
    return SaveAsNewCharacterDialog(tab.selected_path(), "Archon")


def test_dialog_previews_the_destination(dialog):
    dialog._name.setText("Archon Two")
    assert "_Archon Two" in dialog._destination.text()
    assert dialog._create.isEnabled()


@pytest.mark.parametrize(
    ("text", "fragment"),
    [("", "Enter a character name"), ("bad/name", "cannot contain"), ("Bale", "already exists")],
)
def test_dialog_blocks_invalid_names(dialog, text, fragment):
    dialog._name.setText(text)
    assert not dialog._create.isEnabled()
    assert fragment in dialog._problem.text()


def test_dialog_explains_each_mode(dialog):
    dialog._name.setText("Archon Two")
    assert "rewritten" in dialog._effect.text()
    dialog._folder_radio.setChecked(True)
    assert "byte for byte" in dialog._effect.text()


def test_dialog_blocks_while_the_game_is_running(app, tab, monkeypatch):
    from gd_assistant.ui import save_as_dialog

    monkeypatch.setattr(save_as_dialog, "find_running_game", lambda: "grim dawn.exe")
    tab.select_character("Archon")
    dlg = save_as_dialog.SaveAsNewCharacterDialog(tab.selected_path(), "Archon")
    dlg._name.setText("Archon Two")
    assert not dlg._create.isEnabled()
    assert "Close Grim Dawn" in dlg._problem.text()


def test_create_clones_and_leaves_the_source_alone(dialog, save_dir):
    from gd_assistant.savefile.parser import parse_character

    source = save_dir / "main" / "_Archon" / "player.gdc"
    original = source.read_bytes()

    dialog._name.setText("Archon Two")
    dialog._on_create()

    plan = dialog.result_plan
    assert plan is not None
    assert parse_character(plan.destination / "player.gdc").name == "Archon Two"
    assert (plan.destination / "levels_world001.map" / "Normal" / "quests.gdd").exists()
    assert source.read_bytes() == original


def test_folder_mode_copies_the_save_verbatim(dialog, save_dir):
    original = (save_dir / "main" / "_Archon" / "player.gdc").read_bytes()
    dialog._folder_radio.setChecked(True)
    dialog._name.setText("Archon Backup")
    dialog._on_create()

    plan = dialog.result_plan
    assert plan is not None
    assert plan.rename_in_file is False
    assert (plan.destination / "player.gdc").read_bytes() == original


def test_tab_picks_up_the_new_character(tab, dialog):
    dialog._name.setText("Archon Two")
    dialog._on_create()
    tab._rescan()
    tab._repopulate(select=dialog.result_plan.destination)
    assert tab._picker.count() == 3
    assert tab._picker.currentText().startswith("Archon Two")
    assert tab.selected_path() == dialog.result_plan.destination


def test_resolve_plan_is_usable_without_a_dialog(tab):
    """Validation is a plain function, so the rules are testable on their own."""
    from gd_assistant.ui.save_as_dialog import MODE_FOLDER, MODE_RENAME, resolve_plan

    source = tab.selected_path() or (tab._paths[0])
    assert resolve_plan(source, MODE_RENAME, "Fresh").ok
    assert not resolve_plan(source, MODE_RENAME, "  ").ok
    preview = resolve_plan(source, MODE_FOLDER, "Fresh")
    assert preview.plan.rename_in_file is False
