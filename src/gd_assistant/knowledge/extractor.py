"""Locate the game's data files inside an install (SPEC §6.1/§6.2).

The actual reading is done natively by `arz.ArzDatabase` and `arc.ArcArchive` — no
external extractor, no third-party GD tools. This module just finds the `.arz`
databases (base game + expansions) and the `Text_XX.arc` localisation archive
within an install directory, so the KB builder (`data.updater`) can consume them.

Install layout (verified on a retail Linux/Steam install):
    <install>/database/database.arz          # base game
    <install>/gdx1/database/GDX1.arz         # Ashes of Malmouth
    <install>/gdx2/database/GDX2.arz         # Forgotten Gods
    <install>/gdx3/database/GDX3.arz         # Fangs of Asterkarn
    <install>/resources/Text_EN.arc          # localisation tags
"""

from __future__ import annotations

from pathlib import Path

# Base game first, then expansions in release order. Later entries override earlier
# records with the same path when the KB is merged.
_DATABASE_GLOBS = (
    "database/database.arz",
    "gdx1/database/GDX1.arz",
    "gdx2/database/GDX2.arz",
    "gdx3/database/GDX3.arz",
)


def find_database_files(install_dir: Path) -> list[Path]:
    """Return existing `.arz` databases (base + expansions), base-game first."""
    install_dir = Path(install_dir)
    found = [install_dir / rel for rel in _DATABASE_GLOBS]
    return [p for p in found if p.exists()]


def find_text_archive(install_dir: Path, language: str = "EN") -> Path | None:
    """Return the base-game `Text_<LANG>.arc`, if present."""
    candidate = Path(install_dir) / "resources" / f"Text_{language.upper()}.arc"
    return candidate if candidate.exists() else None


# Expansions ship their own localisation (mastery/skill/item names live there).
_TEXT_ARCHIVE_DIRS = ("resources", "gdx1/resources", "gdx2/resources", "gdx3/resources")


def find_text_archives(install_dir: Path, language: str = "EN") -> list[Path]:
    """Return all `Text_<LANG>.arc` archives (base + expansions), base first.

    Merge them base-first so later (expansion) tags override — expansion masteries
    like Inquisitor/Necromancer/Oathkeeper/Berserker are only named in the gdx*
    text archives.
    """
    install_dir = Path(install_dir)
    found = [install_dir / d / f"Text_{language.upper()}.arc" for d in _TEXT_ARCHIVE_DIRS]
    return [p for p in found if p.exists()]


def looks_like_install(path: Path) -> bool:
    """True if `path` is a Grim Dawn install root (has database/database.arz)."""
    return (Path(path) / "database" / "database.arz").exists()
