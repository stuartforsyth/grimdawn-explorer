"""Persistent config: remembers the save dir and extractor path across sessions.

Stored as JSON in the per-OS user config directory (via platformdirs) so the app
does not re-scan for the Grim Dawn install every run. Per SPEC.md §4/§6.2.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from platformdirs import user_config_dir
except ImportError:  # keep importable before deps are installed
    def user_config_dir(appname: str, appauthor: str | None = None) -> str:  # type: ignore[misc]
        return str(Path.home() / ".config" / appname)


APP_NAME = "gd-assistant"


def _config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.json"


@dataclass
class Settings:
    """User settings persisted between sessions."""

    save_dir: str | None = None          # Grim Dawn save/ folder (SPEC §4)
    game_install_dir: str | None = None  # install dir holding .arz/.arc (SPEC §6.1)
    extractor_path: str | None = None    # AssetManager/ArchiveTool or grimarz (SPEC §6.2)
    kb_game_version: str | None = None    # game version the KB was built from
    pinned_items: list[str] = field(default_factory=list)  # item ids pinned to a farm list
    prefs: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or _config_path()
        settings = cls()
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
            settings = cls(**known)
        settings._path = path  # remember where we loaded from, so save() round-trips there
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or getattr(self, "_path", None) or _config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
