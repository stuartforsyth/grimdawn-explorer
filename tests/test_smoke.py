"""Smoke tests for the scaffold: packages import and config round-trips."""

from __future__ import annotations

from pathlib import Path

from gd_assistant.config.settings import Settings
from gd_assistant.savefile import locator


def test_package_imports() -> None:
    import gd_assistant

    assert gd_assistant.__version__


def test_settings_roundtrip(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    s = Settings(save_dir="/some/save", kb_game_version="1.2.1.5")
    s.save(cfg)
    loaded = Settings.load(cfg)
    assert loaded.save_dir == "/some/save"
    assert loaded.kb_game_version == "1.2.1.5"


def test_candidate_save_dirs_are_paths() -> None:
    # Should always return a list of Path candidates for the current OS.
    candidates = locator.candidate_save_dirs()
    assert isinstance(candidates, list)
    assert all(isinstance(p, Path) for p in candidates)
