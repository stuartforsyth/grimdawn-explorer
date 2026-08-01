"""Read-only parser for `player.gdc` save files.

The `.gdc` format is a custom binary layout using a rolling-XOR obfuscation keyed
off an initial seed, with length-prefixed strings and versioned blocks. This
module isolates that brittle logic behind a stable `parse_character()` so the rest
of the app depends only on the `models.Character` result. See SPEC.md §5.

Reference field maps: `gd-edit`, GDCommunityTools / IAGDBackup (no code copied).

STATUS: stub — not implemented yet (MVP milestone 3).
"""

from __future__ import annotations

from pathlib import Path

from gd_assistant.models.character import Character


def parse_character(gdc_path: Path) -> Character:
    """Parse a `player.gdc` file into a `Character`.

    Strategy (to implement):
      1. Read header + seed; build a seeded-XOR reader for typed fields.
      2. Decode blocks (header, bio, inventory, equipment, skills, devotion, ...).
      3. Skip unknown blocks by their length prefix so new patches don't break us.
    """
    raise NotImplementedError("player.gdc parsing not yet implemented (SPEC §5, milestone 3)")
