"""Damage-type / stat colours for the item panel.

The colour *grouping* (which stat gets which colour) is taken verbatim from the
Wanez "Rainbow Filter" mod's `settings/text_en/` tags, which wrap each type in a GD
caret colour code:

    Fire ^O · Cold ^C · Lightning ^Z · Aether ^A · Chaos ^P · Vitality(Life) ^M ·
    Poison ^L · Bleeding & Pierce ^R · Physical ^K · Elemental ^Y

Resistances reuse their damage type's colour (the mod does the same, e.g.
`DefenseFire` uses ^O). GD's engine does not publish the exact RGB for these caret
codes, so the hex values below are GD's recognisable damage-type colours, tuned to
read on both light and dark backgrounds — the *assignment* is authoritative, the
exact shade is a faithful approximation.
"""

from __future__ import annotations

from gd_assistant.data import damage

# Canonical friendly damage type -> hex. DoTs share their parent element's colour,
# and Pierce shares Bleeding's (both ^R in the mod).
TYPE_COLORS: dict[str, str] = {
    "Fire": "#d2691e", "Burn": "#d2691e",
    "Cold": "#2f9fd0", "Frostburn": "#2f9fd0",
    "Lightning": "#c9a227", "Electrocute": "#c9a227",
    "Aether": "#1ca88a",
    "Chaos": "#a83259",
    "Vitality": "#9b45c9", "Vitality Decay": "#9b45c9",
    "Poison": "#5a9e2f",
    "Bleeding": "#c0392b", "Pierce": "#c0392b",
    "Physical": "#7f8c8d", "Internal Trauma": "#7f8c8d",
    "Elemental": "#c8860b",
}

# defensive<Type>[MaxResist] -> canonical friendly type (for resistance colouring).
_RESIST_TO_TYPE = {
    "Fire": "Fire", "Cold": "Cold", "Lightning": "Lightning", "Aether": "Aether",
    "Chaos": "Chaos", "Pierce": "Pierce", "Physical": "Physical", "Poison": "Poison",
    "Bleeding": "Bleeding", "Life": "Vitality", "Elemental": "Elemental",
}

# Loot-source highlight: bosses are the reliable farm targets, so their "Dropped by"
# row is tinted orange to stand out from hero/other droppers and world drops.
SOURCE_BOSS = "#e08a1e"

# A few non-damage stats the mod also tints (kept small and readable).
_ARMOUR = "#95a5a6"
_ABILITY = "#b8860b"
_FIELD_COLORS: dict[str, str] = {
    "defensiveProtection": _ARMOUR,
    "defensiveProtectionModifier": _ARMOUR,
    "defensiveAbsorptionModifier": _ARMOUR,
    "characterOffensiveAbility": _ABILITY,
    "characterOffensiveAbilityModifier": _ABILITY,
    "characterDefensiveAbility": _ABILITY,
    "characterDefensiveAbilityModifier": _ABILITY,
}


# Item rarity (itemClassification) -> hex. GD's tier scheme is White/Yellow/Green/
# Blue/Purple (Common/Magical/Rare/Epic/Legendary); shades tuned to read on a light
# background (pure white/yellow would vanish). Exact engine hex isn't published.
RARITY_COLORS: dict[str, str] = {
    "Broken": "#6f6f6f",
    "Common": "#8a8a8a",
    "Magical": "#c9a227",     # yellow
    "Rare": "#2e8b2e",        # green
    "Epic": "#2f6fd0",        # blue
    "Legendary": "#9b30c0",   # purple
    "Mythical": "#9b30c0",
}


def type_color(damage_type: str) -> str | None:
    """Colour for a canonical damage-type name, if any."""
    return TYPE_COLORS.get(damage_type)


def rarity_color(rarity: str | None) -> str | None:
    """Colour for an item rarity (itemClassification), or None if unknown."""
    return RARITY_COLORS.get(rarity) if rarity else None


def field_color(field: str) -> str | None:
    """Colour for a raw stat field, or None to use the default text colour."""
    dtype = damage.field_type(field)  # offensive*/retaliation* damage fields
    if dtype:
        return TYPE_COLORS.get(dtype)
    if field.startswith("defensive"):
        rest = field[len("defensive"):].removesuffix("MaxResist")
        friendly = _RESIST_TO_TYPE.get(rest)
        if friendly:
            return TYPE_COLORS.get(friendly)
    return _FIELD_COLORS.get(field)
