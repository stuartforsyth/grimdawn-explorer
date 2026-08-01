"""Friendly labels for raw item/skill stat fields (display + property search).

A curated map for the common fields plus rule-based labels for `offensive*` damage
fields (via `data.damage`) and resistances. Unmapped fields fall back to a
de-camelCased version of the raw name, so *every* field is still shown/searchable —
labels are a convenience layer, never a filter. Kept intentionally simple; this is
not a faithful reproduction of the in-game tooltip formatting.

Note: Grim Dawn renamed the attributes — internal `Strength/Dexterity/Intelligence`
are shown in-game as **Physique/Cunning/Spirit**.
"""

from __future__ import annotations

import re

from gd_assistant.data import damage

# Resistance fields: defensive<Type> -> "<Type> Resistance".
_RESIST_TYPES = {
    "Fire": "Fire", "Cold": "Cold", "Lightning": "Lightning", "Aether": "Aether",
    "Chaos": "Chaos", "Pierce": "Pierce", "Physical": "Physical", "Poison": "Poison",
    "Bleeding": "Bleeding", "Life": "Vitality", "Elemental": "Elemental",
    "Disruption": "Disruption",
}

# Explicit labels for common non-offensive fields.
_LABELS: dict[str, str] = {
    "defensiveProtection": "Armor",
    "defensiveProtectionModifier": "% Armor",
    "defensiveAbsorptionModifier": "% Damage Absorption",
    "characterOffensiveAbility": "Offensive Ability",
    "characterOffensiveAbilityModifier": "% Offensive Ability",
    "characterDefensiveAbility": "Defensive Ability",
    "characterDefensiveAbilityModifier": "% Defensive Ability",
    "characterLife": "Health",
    "characterLifeModifier": "% Health",
    "characterLifeRegen": "Health Regen",
    "characterLifeRegenModifier": "% Health Regen",
    "characterMana": "Energy",
    "characterManaModifier": "% Energy",
    "characterManaRegen": "Energy Regen",
    "characterManaRegenModifier": "% Energy Regen",
    "characterStrength": "Physique",
    "characterStrengthModifier": "% Physique",
    "characterDexterity": "Cunning",
    "characterDexterityModifier": "% Cunning",
    "characterIntelligence": "Spirit",
    "characterIntelligenceModifier": "% Spirit",
    "characterAttackSpeedModifier": "% Attack Speed",
    "characterSpellCastSpeedModifier": "% Casting Speed",
    "characterRunSpeedModifier": "% Movement Speed",
    "characterTotalSpeedModifier": "% Total Speed",
    "characterDodgePercent": "Dodge Chance (melee)",
    "characterDeflectProjectile": "Deflect Chance (projectiles)",
    "characterLightRadius": "Light Radius",
    "skillCooldownReduction": "% Skill Cooldown Reduction",
    "defensiveBlock": "Block Amount",
    "defensiveBlockChance": "Block Chance",
    "defensiveBlockAmountModifier": "% Block Amount",
    "defensiveStun": "Stun Resistance",
    "defensiveFreeze": "Freeze Resistance",
    "defensiveTrap": "Trap Resistance",
    "defensiveTotalSpeedResistance": "Slow Resistance",
    "defensiveReflect": "Reflected Damage Reduction",
    "defensiveConvert": "Conversion Resistance",
    "defensiveLifeLeech": "Life Leech Resistance",
    "racialBonusPercentDamage": "% Damage vs. Race",
    "racialBonusPercentDefense": "% Reduced Damage from Race",
    "conversionPercentage": "Damage Conversion %",
    "conversionInType": "Convert From",
    "conversionOutType": "Convert To",
}

_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
_STRIP_PREFIXES = ("character", "defensive", "offensive", "retaliation", "racial", "skill")

# Items can carry more than one damage conversion; the second slot's raw fields are
# suffixed "2" (e.g. Asterllonos converts both Lightning and Fire to Cold). Each slot
# is folded into one sentence (see `conversions`) instead of three separate rows.
_CONVERSION_SLOTS = ("", "2")


def conversions(stats: dict[str, object]) -> tuple[list[tuple[str, str]], set[str]]:
    """Fold every complete conversion slot into readable sentences.

    Returns ``(phrases, consumed)`` where ``phrases`` is a list of
    ``(sentence, out_type)`` pairs — e.g. ``("30% Cold damage converted to Physical
    damage", "Physical")`` — and ``consumed`` is the set of raw field names that were
    folded (so callers can skip them). An incomplete slot is left untouched.
    """
    phrases: list[tuple[str, str]] = []
    consumed: set[str] = set()
    for suffix in _CONVERSION_SLOTS:
        in_type = stats.get(f"conversionInType{suffix}")
        out_type = stats.get(f"conversionOutType{suffix}")
        pct = stats.get(f"conversionPercentage{suffix}")
        if not (in_type and out_type and pct):
            continue
        pct_str = f"{pct:g}" if isinstance(pct, (int, float)) else str(pct)
        phrases.append((f"{pct_str}% {in_type} damage converted to {out_type} damage", str(out_type)))
        consumed.update((f"conversionInType{suffix}", f"conversionOutType{suffix}",
                         f"conversionPercentage{suffix}"))
    return phrases, consumed


def friendly(field: str) -> str:
    """Return a human-readable label for a raw stat field name."""
    if field in _LABELS:
        return _LABELS[field]

    # offensive* damage fields -> "% Fire Damage" / "Fire Damage" / "Fire Duration"
    dtype = damage.field_type(field)
    if dtype and field.startswith(("offensive", "retaliation")):
        prefix = "Retaliation " if field.startswith("retaliation") else ""
        if field.endswith("Modifier"):
            return f"{prefix}% {dtype} Damage"
        if "Duration" in field:
            return f"{prefix}{dtype} Duration"
        return f"{prefix}{dtype} Damage"

    # defensive<Type>[MaxResist] resistances
    if field.startswith("defensive"):
        rest = field[len("defensive"):]
        max_resist = rest.endswith("MaxResist")
        if max_resist:
            rest = rest[: -len("MaxResist")]
        if rest in _RESIST_TYPES:
            base = f"{_RESIST_TYPES[rest]} Resistance"
            return f"Max {base}" if max_resist else base

    # Fallback: strip a known prefix and de-camelCase.
    rest = field
    for p in _STRIP_PREFIXES:
        if rest.startswith(p) and len(rest) > len(p):
            rest = rest[len(p):]
            break
    return _CAMEL.sub(" ", rest).strip().replace("_", " ").title() or field
