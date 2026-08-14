"""Read-only view of a `player.gdc` save as a `Character`.

The binary format lives in two layers below this one: `crypt.py` (the seed-XOR
obfuscation) and `document.py` (the block grammar). This module is purely the
semantic step — pulling the handful of fields the app cares about out of a parsed
`Document`.

Keeping the grammar in exactly one place matters: a second, reader-only copy would be
free to drift from the one the writer uses, and a writer working from a stale grammar
is how save editors corrupt files. See SPEC §5.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from gd_assistant.models.character import (
    Character,
    DevotionAllocation,
    EquippedItem,
    SkillAllocation,
)
from gd_assistant.savefile.crypt import GdcReader
from gd_assistant.savefile.document import Document, find_fields, parse_document

# Devotion allocations share the skills list, distinguished by their record path.
_DEVOTION_PREFIX = "records/skills/devotion/"

# Every character carries the game's built-in actions (kick, move-to, basic attack) at
# level 1. They cost no points and say nothing about a build, so they are not
# allocations and are left out of `Character.skills`.
_DEFAULT_SKILL_PREFIX = "records/skills/default/"

# A mastery bar is stored as an ordinary skill whose record is the class-training
# node, e.g. `records/skills/playerclass09/_classtraining_class09.dbr`; its level is
# the number of points invested in the bar.
_MASTERY_MARKER = "_classtraining_class"

EQUIPMENT_SLOTS = 12
WEAPON_SLOTS = 2

# What each equipment index actually holds. Derived, not assumed: indices 0-10 were
# read off the dev saves by resolving every equipped record through the KB, which gave
# one consistent slot per index across all 24 characters. Index 11 never resolves
# because relics aren't in the KB, but every record found there lives under
# `records/items/gearrelic/`, so the record path names it.
EQUIPMENT_SLOT_NAMES = (
    "Head", "Amulet", "Chest", "Legs", "Feet", "Hands",
    "Ring", "Ring", "Waist", "Shoulders", "Medal", "Relic",
)


def slot_label(slot: str) -> str:
    """Human-readable name for an `EquippedItem.slot`."""
    if slot.isdigit() and int(slot) < len(EQUIPMENT_SLOT_NAMES):
        return EQUIPMENT_SLOT_NAMES[int(slot)]
    if slot.startswith("weapon"):
        weapon_set, _, hand = slot.partition(".")
        which = "Main hand" if hand == "0" else "Off hand"
        return f"{which} ({'set ' + weapon_set.removeprefix('weapon')})"
    return slot


class GdcParseError(ValueError):
    """Raised when a save cannot be parsed — never partially-trusted output."""


@dataclass(frozen=True)
class CharacterHeader:
    """The identity fields that sit at the very start of a save.

    Enough to label a character in a picker without parsing its inventory, stash and
    skill list — which is ~30x the work for data a list never shows.
    """

    name: str
    level: int
    hardcore: bool
    class_tag: str

    @property
    def masteries(self) -> list[str]:
        """The two-digit mastery ids encoded in the class tag."""
        return list(masteries_from_tag(self.class_tag))


def read_header(gdc_path: Path) -> CharacterHeader:
    """Read only a save's header (SPEC §5.1). Cheap enough to call for every character."""
    path = Path(gdc_path)
    try:
        reader = GdcReader(path.read_bytes())
        reader.read_magic()
        name = reader.wide_str()
        reader.u8()  # sex
        class_tag = reader.ascii_str()
        level = reader.u32()
        hardcore = reader.bool8()
    except (ValueError, IndexError, UnicodeDecodeError) as exc:
        raise GdcParseError(f"{path}: {exc}") from exc
    return CharacterHeader(name=name, level=level, hardcore=hardcore, class_tag=class_tag)


def parse_character(gdc_path: Path) -> Character:
    """Parse a `player.gdc` file into a `Character`.

    Raises `GdcParseError` rather than returning a half-populated character: a save
    that doesn't parse cleanly is one we don't understand, and guessing at its
    contents would be worse than saying so.
    """
    path = Path(gdc_path)
    try:
        return character_from_document(parse_document(path.read_bytes()))
    except (ValueError, IndexError, UnicodeDecodeError) as exc:
        raise GdcParseError(f"{path}: {exc}") from exc


def character_from_document(doc: Document) -> Character:
    """Build a `Character` from an already-parsed `Document`."""
    equipped: list[EquippedItem] = []
    for slot in range(EQUIPMENT_SLOTS):
        record = _value(doc, f"equipment.{slot}.base")
        if record:
            equipped.append(EquippedItem(slot=str(slot), item_id=record))
    for set_index in (1, 2):
        for slot in range(WEAPON_SLOTS):
            record = _value(doc, f"weapon{set_index}.{slot}.base")
            if record:
                equipped.append(
                    EquippedItem(slot=f"weapon{set_index}.{slot}", item_id=record)
                )

    skills: list[SkillAllocation] = []
    devotion: list[DevotionAllocation] = []
    masteries: dict[str, int] = {}
    for index in range(_value(doc, "skills.count") or 0):
        name = _value(doc, f"skill{index}.name")
        level = _value(doc, f"skill{index}.level")
        if not level or name.startswith(_DEFAULT_SKILL_PREFIX):
            continue
        if name.startswith(_DEVOTION_PREFIX):
            devotion.append(DevotionAllocation(node_id=name))
            continue
        skills.append(SkillAllocation(skill_id=name, points=level))
        if _MASTERY_MARKER in name:
            masteries[name.rsplit(_MASTERY_MARKER, 1)[1].removesuffix(".dbr")] = level

    return Character(
        name=_value(doc, "name"),
        level=_value(doc, "bio.level") or _value(doc, "level"),
        hardcore=bool(_value(doc, "hardcore")),
        class_tag=_value(doc, "class_tag") or "",
        masteries={**masteries_from_tag(_value(doc, "class_tag")), **masteries},
        skills=skills,
        devotion=devotion,
        equipped=equipped,
        attributes={
            "physique": int(_value(doc, "bio.physique") or 0),
            "cunning": int(_value(doc, "bio.cunning") or 0),
            "spirit": int(_value(doc, "bio.spirit") or 0),
            "unspent_attribute": _value(doc, "bio.attribute_points_unspent") or 0,
            "unspent_skill": _value(doc, "bio.skill_points_unspent") or 0,
            "unspent_devotion": _value(doc, "bio.devotion_points_unspent") or 0,
        },
    )


def masteries_from_tag(class_tag: str) -> dict[str, int]:
    """Split a `tagSkillClassNameNNNN` tag into its mastery ids.

    The tag encodes one or two two-digit mastery numbers (`...0609` is a dual class),
    so the pair is known straight from the header. Bar points are not in the tag —
    they come from the skills block — so values are left at 0 here.
    """
    digits = class_tag.removeprefix("tagSkillClassName")
    if not digits.isdigit() or len(digits) % 2:
        return {}
    return {digits[i : i + 2]: 0 for i in range(0, len(digits), 2)}


def _value(doc: Document, name: str):
    """Return a named field's value, or None when the save doesn't carry it."""
    found = find_fields(doc, name)
    return found[0].value if found else None
