"""Tests for the clone CLI — chiefly that its safety gates actually gate."""

from __future__ import annotations

import pytest

from gd_assistant.savefile import clone as clone_mod
from gd_assistant.savefile.cli import main

from .test_savefile_parser import build_save


@pytest.fixture(autouse=True)
def _game_not_running(monkeypatch):
    monkeypatch.setattr(clone_mod, "find_running_game", lambda: None)


@pytest.fixture
def save_dir(tmp_path):
    char = tmp_path / "main" / "_Archon"
    (char / "levels_world001.map" / "Normal").mkdir(parents=True)
    (char / "player.gdc").write_bytes(build_save(name="Archon", level=57))
    (char / "levels_world001.map" / "Normal" / "quests.gdd").write_bytes(b"quest")
    return tmp_path


def test_list_reports_characters(save_dir, capsys):
    assert main(["--save-dir", str(save_dir), "list"]) == 0
    out = capsys.readouterr().out
    assert "Archon" in out
    assert "lvl  57" in out


def test_clone_defaults_to_a_dry_run(save_dir, capsys):
    assert main(["--save-dir", str(save_dir), "clone", "Archon", "--rename", "Two"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (save_dir / "main" / "_Two").exists()


def test_writing_to_the_real_save_dir_needs_confirmation(save_dir):
    """--write alone must not be enough to touch the actual save folder."""
    with pytest.raises(SystemExit, match="i-mean-it"):
        main(["--save-dir", str(save_dir), "clone", "Archon", "--rename", "Two", "--write"])
    assert not (save_dir / "main" / "_Two").exists()


def test_confirmed_write_performs_the_clone(save_dir, capsys):
    code = main([
        "--save-dir", str(save_dir), "clone", "Archon",
        "--rename", "Two", "--write", "--i-mean-it",
    ])
    assert code == 0
    assert (save_dir / "main" / "_Two" / "player.gdc").exists()
    assert "verified: 'Two'" in capsys.readouterr().out


def test_sandbox_write_needs_no_confirmation(save_dir, tmp_path, capsys):
    sandbox = tmp_path / "sandbox"
    code = main([
        "--save-dir", str(save_dir), "clone", "Archon",
        "--rename", "Two", "--sandbox", str(sandbox), "--write",
    ])
    assert code == 0
    assert (sandbox / "_Two" / "player.gdc").exists()
    # The real save folder is untouched.
    assert not (save_dir / "main" / "_Two").exists()


def test_unknown_character_is_reported(save_dir):
    with pytest.raises(SystemExit, match="no character called"):
        main(["--save-dir", str(save_dir), "clone", "Nobody", "--rename", "X"])


def test_missing_save_dir_is_reported(tmp_path):
    with pytest.raises(SystemExit, match="save dir not found"):
        main(["--save-dir", str(tmp_path / "nope"), "list"])


def test_rename_and_folder_are_mutually_exclusive(save_dir):
    with pytest.raises(SystemExit):
        main([
            "--save-dir", str(save_dir), "clone", "Archon",
            "--rename", "A", "--folder", "B",
        ])


def test_folder_mode_reports_that_no_bytes_are_written(save_dir, capsys):
    main(["--save-dir", str(save_dir), "clone", "Archon", "--folder", "Backup"])
    assert "no save bytes are written" in capsys.readouterr().out
