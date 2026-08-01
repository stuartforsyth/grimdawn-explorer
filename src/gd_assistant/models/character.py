"""Character model — the parsed, in-memory view of a save file.

Deliberately decoupled from the `.gdc` layout: the parser produces this, and the
suggestion engine + UI consume it. STATUS: skeleton fields; expand as the parser
and engine mature (SPEC §5/§7).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SkillAllocation:
    """A skill and how many points the character has put into it."""

    skill_id: str
    points: int


@dataclass
class DevotionAllocation:
    """An allocated devotion constellation node."""

    node_id: str


@dataclass
class EquippedItem:
    """An item occupying an equipment slot (references KB item by id)."""

    slot: str
    item_id: str


@dataclass
class Character:
    """The player character parsed from `player.gdc` (read-only)."""

    name: str = ""
    level: int = 0
    hardcore: bool = False
    masteries: dict[str, int] = field(default_factory=dict)  # mastery id -> bar points
    skills: list[SkillAllocation] = field(default_factory=list)
    devotion: list[DevotionAllocation] = field(default_factory=list)
    equipped: list[EquippedItem] = field(default_factory=list)
    attributes: dict[str, int] = field(default_factory=dict)   # physique/cunning/spirit
    resistances: dict[str, int] = field(default_factory=dict)  # damage type -> %
