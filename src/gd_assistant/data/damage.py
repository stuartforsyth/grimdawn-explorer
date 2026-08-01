"""Grim Dawn damage-type helpers shared by normalisation and the repository.

Maps the game's internal `offensive*` field tokens to friendly damage-type names
and extracts the damage types a skill *deals* (array-aware — skills store damage as
per-level lists). Centralised so items, skills, and queries all agree on names.

All mappings below were confirmed against retail item/skill records (not memory):
Vitality damage is stored as `offensiveLife*` (Vitality Decay = `offensiveSlowLife*`),
each element also has an `offensiveBase<Type>*` flat variant, and DoTs use the
`offensiveSlow<Type>*` prefix (SlowBleeding=Bleeding, SlowFire=Burn, …).
"""

from __future__ import annotations

from gd_assistant.knowledge.arz import ArzRecord

# Internal offensive-field token -> canonical friendly damage-type name.
TOKEN_TO_TYPE: dict[str, str] = {
    "Physical": "Physical", "Pierce": "Pierce", "Fire": "Fire", "Cold": "Cold",
    "Lightning": "Lightning", "Aether": "Aether", "Chaos": "Chaos",
    "Poison": "Poison", "Elemental": "Elemental",
    "Life": "Vitality", "LifeLeech": "Life Leech",
    # Damage-over-time variants:
    "SlowBleeding": "Bleeding", "SlowPhysical": "Internal Trauma",
    "SlowFire": "Burn", "SlowCold": "Frostburn", "SlowLightning": "Electrocute",
    "SlowLife": "Vitality Decay", "SlowPoison": "Poison",
}

# Friendly user input (any case) -> canonical friendly name.
_ALIASES: dict[str, str] = {
    "bleed": "Bleeding", "bleeding": "Bleeding",
    "vitality": "Vitality", "vitality decay": "Vitality Decay", "decay": "Vitality Decay",
    "internal trauma": "Internal Trauma", "trauma": "Internal Trauma",
    "burn": "Burn", "frostburn": "Frostburn", "electrocute": "Electrocute",
    "acid": "Poison", "poison": "Poison", "leech": "Life Leech", "life leech": "Life Leech",
    "elemental": "Elemental",
}

# A build of one type also benefits from its DoT and (for single elements) Elemental.
_FAMILY: dict[str, set[str]] = {
    "Fire": {"Fire", "Burn", "Elemental"},
    "Cold": {"Cold", "Frostburn", "Elemental"},
    "Lightning": {"Lightning", "Electrocute", "Elemental"},
    "Physical": {"Physical", "Internal Trauma"},
    "Vitality": {"Vitality", "Vitality Decay"},
    "Elemental": {"Elemental", "Fire", "Cold", "Lightning", "Burn", "Frostburn", "Electrocute"},
}

# Longest token first so "SlowBleeding"/"LifeLeech" match before "Slow"/"Life".
_TOKENS_BY_LEN = sorted(TOKEN_TO_TYPE, key=len, reverse=True)

# Suffixes marking a field as actual damage dealt (flat or %), not duration/chance.
_DEALS_SUFFIXES = ("Min", "Max", "Modifier")


def canonical(name: str) -> str:
    """Normalise a damage-type name (e.g. "bleed" -> "Bleeding", "vitality" -> "Vitality")."""
    stripped = name.strip()
    key = stripped.lower()
    if key in _ALIASES:
        return _ALIASES[key]
    return TOKEN_TO_TYPE.get(stripped, stripped.title())


def family(damage_type: str) -> set[str]:
    """Canonical type plus related types a build of it benefits from (DoT, Elemental)."""
    canon = canonical(damage_type)
    return _FAMILY.get(canon, {canon})


def _match_token(field: str) -> tuple[str | None, str]:
    """Split an `offensive[Base]<Token><suffix>` field into (token, suffix)."""
    if not field.startswith("offensive"):
        return None, ""
    # offensiveBaseFireMin -> flat fire; strip the optional "Base" so it maps to Fire.
    rest = field[len("offensive"):].removeprefix("Base")
    for token in _TOKENS_BY_LEN:
        if rest.startswith(token):
            return token, rest[len(token):]
    return None, ""


def field_type(field: str) -> str | None:
    """Friendly damage type for ANY offensive field of a damage type (incl. duration)."""
    token, _ = _match_token(field)
    return TOKEN_TO_TYPE.get(token) if token else None


def field_deals_type(field: str) -> str | None:
    """Friendly damage type only for fields that deal damage (flat or %modifier)."""
    token, suffix = _match_token(field)
    if token and suffix in _DEALS_SUFFIXES:
        return TOKEN_TO_TYPE[token]
    return None


def _nonzero(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, list):
        return any(isinstance(x, (int, float)) and x for x in value)
    return False


# Fields that link a skill to the sub-record carrying its real effect/name.
LINK_FIELDS = ("buffSkillName", "petSkillName")


def _own_damage_types(rec: ArzRecord) -> set[str]:
    found: set[str] = set()
    for field, value in rec.fields.items():
        if field.startswith("retaliation"):
            continue
        dtype = field_deals_type(field)
        if dtype and _nonzero(value):
            found.add(dtype)
    return found


def linked_chain(rec: ArzRecord, lookup: dict[str, ArzRecord] | None) -> list[ArzRecord]:
    """All sub-records reachable via buff/pet links, transitively (breadth-first).

    Some skills chain more than once: a pet *modifier* -> the pet's granted skill ->
    that skill's buff (which holds the name/damage), e.g. Shaman's "Blood Pact". A
    `seen` set guards against cycles.
    """
    if not lookup:
        return []
    seen: set[str] = set()
    result: list[ArzRecord] = []
    frontier = [rec]
    while frontier:
        current = frontier.pop()
        for field in LINK_FIELDS:
            path = current.fields.get(field)
            if isinstance(path, str) and path in lookup and path not in seen:
                seen.add(path)
                child = lookup[path]
                result.append(child)
                frontier.append(child)
    return result


def skill_damage_types(rec: ArzRecord, lookup: dict[str, ArzRecord] | None = None) -> list[str]:
    """Damage types a skill deals — including its linked buff/pet chain if provided.

    Many skills (e.g. Necromancer's *Siphon Souls*, or pet modifiers like *Blood
    Pact*) store their damage on a linked sub-record, not the base; pass `lookup`
    (path -> record) to resolve the whole chain.
    """
    found = _own_damage_types(rec)
    for linked in linked_chain(rec, lookup):
        found.update(_own_damage_types(linked))
    return sorted(found)
