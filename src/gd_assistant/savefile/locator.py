"""Locate the Grim Dawn save directory per OS, and list characters.

Grim Dawn AppID is 219990. Saves live under `.../My Games/Grim Dawn/save/`, with
each character in a `_<CharName>` folder containing `player.gdc`. Steam Cloud keeps
a mirror under `userdata/<id>/219990/remote/save/`. See SPEC.md §4.

The discovered path is persisted by the caller (config.Settings) so we don't
re-scan every run; `candidate_save_dirs()` is exposed for a rescan/reselect flow.
"""

from __future__ import annotations

import sys
from pathlib import Path

STEAM_APP_ID = "219990"


def candidate_save_dirs() -> list[Path]:
    """Return plausible Grim Dawn save/ locations for the current OS, best-first.

    Existence is NOT checked here — callers filter with `is_save_dir()`. Steam
    Cloud `userdata` paths embed an account id, so those roots are globbed.
    """
    home = Path.home()
    docs_tail = Path("My Games") / "Grim Dawn" / "save"
    candidates: list[Path] = []

    if sys.platform.startswith("win"):
        candidates.append(home / "Documents" / docs_tail)
        for root in (Path("C:/Program Files (x86)/Steam"), Path("C:/Program Files/Steam")):
            candidates.extend((root / "userdata").glob(f"*/{STEAM_APP_ID}/remote/save"))
    elif sys.platform == "darwin":
        candidates.append(home / "Library" / "Application Support" / docs_tail)
        candidates.append(
            home / "Documents" / docs_tail  # some setups
        )
    else:  # Linux (Steam native + Proton)
        steam_roots = [
            home / ".steam" / "steam",
            home / ".local" / "share" / "Steam",
        ]
        for root in steam_roots:
            # Steam Cloud mirror
            candidates.extend((root / "userdata").glob(f"*/{STEAM_APP_ID}/remote/save"))
            # Proton prefix (game runs under Windows layout)
            proton = (
                root / "steamapps" / "compatdata" / STEAM_APP_ID / "pfx"
                / "drive_c" / "users" / "steamuser" / "Documents" / docs_tail
            )
            candidates.append(proton)

    return candidates


def is_save_dir(path: Path) -> bool:
    """True if `path` looks like a Grim Dawn save dir (has `_<name>` char folders)."""
    return path.is_dir() and any(p.name.startswith("_") and p.is_dir() for p in path.iterdir())


def find_save_dir() -> Path | None:
    """Return the first existing, valid save dir, or None if not found."""
    for candidate in candidate_save_dirs():
        try:
            if is_save_dir(candidate):
                return candidate
        except OSError:
            continue
    return None


def list_characters(save_dir: Path) -> list[Path]:
    """Return character folders (each holding `player.gdc`) under `save_dir`."""
    if not save_dir.is_dir():
        return []
    return sorted(
        p for p in save_dir.iterdir()
        if p.is_dir() and p.name.startswith("_") and (p / "player.gdc").exists()
    )
