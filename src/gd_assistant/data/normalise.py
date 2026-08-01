"""Normalise raw `.arz` records into the KB's JSON-friendly dicts (SPEC §6.3/§6.4).

Pure functions: they take `records` (path -> ArzRecord, already merged across base +
expansions) and `tags` (tag -> display string) and return plain lists of dicts. No
file I/O — that lives in `data.updater` — so these are easy to unit-test.

Field mappings were derived by inspecting a retail database (see SPEC §6):
  * masteries  : records classed `Skill_Mastery`
  * skills     : player skills under records/skills/playerclassNN/
  * devotion   : records/ui/skills/devotion/constellations/constellationNN.dbr
  * items      : equippable records under records/items/ with a resolvable name tag
"""

from __future__ import annotations

import re

from gd_assistant.data import damage
from gd_assistant.knowledge.arz import ArzRecord

# --- item classification ---------------------------------------------------
_EQUIP_PREFIXES = (
    "ArmorProtective", "ArmorJewelry", "ArmorCloth",
    "WeaponMelee", "WeaponRanged", "WeaponArmor",
)
_PLAYERCLASS_RE = re.compile(r"^records/skills/(playerclass\d+)/([^/]+)\.dbr$")


def _resolve(tag: object, tags: dict[str, str]) -> str | None:
    """Resolve a `tag*` string to its display value; pass through plain strings."""
    if not isinstance(tag, str) or not tag:
        return None
    return tags.get(tag, tag)


def _skill_type(record_class: str) -> str:
    if record_class == "Skill_Modifier":
        return "modifier"
    if record_class == "Skill_Transmuter":
        return "transmuter"
    if "Passive" in record_class or "Buff" in record_class:
        return "passive"
    return "active"


# --- masteries -------------------------------------------------------------
def normalise_masteries(records: dict[str, ArzRecord], tags: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    for path, rec in records.items():
        if rec.record_class != "Skill_Mastery":
            continue
        m = _PLAYERCLASS_RE.match(path)
        out.append({
            "id": rec.fields.get("MasteryEnumeration") or path,
            "name": _resolve(rec.fields.get("skillDisplayName"), tags)
                    or rec.fields.get("FileDescription"),
            "record": path,
            "dir": m.group(1) if m else None,
            "bar_max_level": rec.fields.get("skillMaxLevel"),
        })
    out.sort(key=lambda d: d["dir"] or d["id"])
    return out


def _mastery_dir_names(masteries: list[dict]) -> dict[str, str]:
    return {m["dir"]: m["name"] for m in masteries if m.get("dir")}


# --- skills ----------------------------------------------------------------
def normalise_skills(
    records: dict[str, ArzRecord],
    tags: dict[str, str],
    masteries: list[dict],
) -> list[dict]:
    dir_names = _mastery_dir_names(masteries)
    # Buff/pet sub-records are children of a base skill; the base represents them.
    child_paths = {
        p for rec in records.values() for f in damage.LINK_FIELDS
        if isinstance(p := rec.fields.get(f), str)
    }
    out: list[dict] = []
    for path, rec in records.items():
        m = _PLAYERCLASS_RE.match(path)
        if not m:
            continue
        if rec.record_class == "Skill_Mastery" or path in child_paths:
            continue  # the mastery itself, or a buff/pet component of another skill
        # Name/description may live on the base record or somewhere along its linked
        # buff/pet chain ("Siphon Souls" is on soulsiphon1_buff; the pet modifier
        # "Blood Pact" resolves two hops away via petSkillName -> buffSkillName).
        name = _resolve(rec.fields.get("skillDisplayName"), tags)
        desc = _resolve(rec.fields.get("skillBaseDescription"), tags)
        for linked in damage.linked_chain(rec, records):
            name = name or _resolve(linked.fields.get("skillDisplayName"), tags)
            desc = desc or _resolve(linked.fields.get("skillBaseDescription"), tags)
        if not name:
            continue  # genuinely internal/unnamed helper
        mastery_dir = m.group(1)
        out.append({
            "id": path,
            "name": name,
            "mastery": dir_names.get(mastery_dir),
            "mastery_dir": mastery_dir,
            "type": _skill_type(rec.record_class),
            "record_class": rec.record_class,
            "max_level": rec.fields.get("skillMaxLevel"),
            "ultimate_level": rec.fields.get("skillUltimateLevel"),
            "tier": rec.fields.get("skillTier"),
            "description": desc,
            "damage_types": damage.skill_damage_types(rec, records),
        })
    out.sort(key=lambda d: (d["mastery_dir"], d["tier"] or 0, d["name"]))
    return out


# --- devotion --------------------------------------------------------------
def _affinities(rec: ArzRecord, prefix: str) -> dict[str, int]:
    """Collect affinityGiven/Required pairs into {name: amount} (amount > 0)."""
    result: dict[str, int] = {}
    for i in range(1, 6):
        name = rec.fields.get(f"{prefix}Name{i}")
        amount = rec.fields.get(f"{prefix}{i}")
        if isinstance(name, str) and name and isinstance(amount, int) and amount > 0:
            result[name] = amount
    return result


def normalise_devotion(records: dict[str, ArzRecord], tags: dict[str, str]) -> list[dict]:
    out: list[dict] = []
    for path, rec in records.items():
        if "constellationDisplayTag" not in rec.fields:
            continue
        stars = [
            rec.fields[k] for k in
            ("devotionButton1", "devotionButton2", "devotionButton3",
             "devotionButton4", "devotionButton5")
            if isinstance(rec.fields.get(k), str) and rec.fields.get(k)
        ]
        out.append({
            "id": path,
            "name": _resolve(rec.fields.get("constellationDisplayTag"), tags),
            "description": _resolve(rec.fields.get("constellationInfoTag"), tags),
            "affinity_required": _affinities(rec, "affinityRequired"),
            "affinity_given": _affinities(rec, "affinityGiven"),
            "stars": stars,
            "star_count": len(stars),
        })
    out.sort(key=lambda d: d["name"] or d["id"])
    return out


# --- items -----------------------------------------------------------------
def _slot_and_category(record_class: str) -> tuple[str, str]:
    category, _, slot = record_class.partition("_")
    return category, (slot or record_class)


def _set_names(records: dict[str, ArzRecord], tags: dict[str, str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for path, rec in records.items():
        if "/lootsets/" in path:
            name = _resolve(rec.fields.get("setName"), tags)
            if name:
                names[path] = name
    return names


def _plus_skills(rec: ArzRecord) -> dict[str, int]:
    result: dict[str, int] = {}
    for i in (1, 2, 3, 4):
        name = rec.fields.get(f"augmentSkillName{i}")
        level = rec.fields.get(f"augmentSkillLevel{i}")
        if isinstance(name, str) and name and level:
            result[name] = level
    return result


def _plus_mastery(rec: ArzRecord) -> dict[str, int]:
    result: dict[str, int] = {}
    for i in (1, 2):
        name = rec.fields.get(f"augmentMasteryName{i}")
        level = rec.fields.get(f"augmentMasteryLevel{i}")
        if isinstance(name, str) and name and level:
            result[name] = level
    return result


# Boolean/flag suffixes that aren't build-relevant magnitudes.
_OFFENSIVE_SKIP_SUFFIXES = ("Chance", "Global", "XOR")

# Non-offensive stat prefixes worth surfacing on an item (resists, attributes,
# OA/DA, speeds, block, cooldown, retaliation, racial). Excludes bitmap/cost/template
# metadata. `offensive*` is captured separately (see _offensive_bonuses).
_STAT_PREFIXES = ("defensive", "character", "retaliation", "racial", "skill")


def _item_stats(rec: ArzRecord) -> dict[str, object]:
    """Capture non-zero non-offensive stat fields for display + property search."""
    out: dict[str, object] = {}
    for k, v in rec.fields.items():
        if k.startswith(_STAT_PREFIXES):
            if isinstance(v, bool):
                continue
            if (isinstance(v, (int, float)) and v) or (
                isinstance(v, list) and any(isinstance(x, (int, float)) and x for x in v)
            ):
                out[k] = v
        elif k.startswith("conversion") and v not in (0, 0.0, "", None, False):
            out[k] = v  # keep in/out types (strings) and percentage together
    return out


def _offensive_bonuses(rec: ArzRecord) -> dict[str, float]:
    """Capture non-zero `offensive*` damage fields (flat, %modifier, duration).

    Keyed by the raw game field name (e.g. `offensiveSlowBleedingModifier`), which
    encodes the damage type — so the repository can answer "items that enable a
    <damage-type> build" for any type (bleed, poison, fire, ...) without hardcoding.
    Booleans and proc-chance flags are skipped; only magnitudes are kept.
    """
    out: dict[str, float] = {}
    for k, v in rec.fields.items():
        if not k.startswith("offensive"):
            continue
        if k.endswith(_OFFENSIVE_SKIP_SUFFIXES) or isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and v:
            out[k] = v
    return out


def normalise_items(records: dict[str, ArzRecord], tags: dict[str, str]) -> list[dict]:
    set_names = _set_names(records, tags)
    out: list[dict] = []
    for path, rec in records.items():
        if not rec.record_class.startswith(_EQUIP_PREFIXES):
            continue
        name = _resolve(rec.fields.get("itemNameTag"), tags)
        if not name:
            continue  # only named, real items
        category, slot = _slot_and_category(rec.record_class)
        set_path = rec.fields.get("itemSetName")
        out.append({
            "id": path,
            "name": name,
            "category": category,
            "slot": slot,
            "record_class": rec.record_class,
            "rarity": rec.fields.get("itemClassification"),
            "level_requirement": rec.fields.get("levelRequirement"),
            "item_level": rec.fields.get("itemLevel"),
            "set": set_names.get(set_path) if isinstance(set_path, str) else None,
            "set_record": set_path if isinstance(set_path, str) and set_path else None,
            "granted_skill": rec.fields.get("itemSkillName") or None,
            "plus_skills": _plus_skills(rec),
            "plus_mastery": _plus_mastery(rec),
            "plus_all_skills": rec.fields.get("augmentAllLevel") or None,
            "offensive": _offensive_bonuses(rec),
            "stats": _item_stats(rec),
        })
    out.sort(key=lambda d: (d["category"], d["slot"], d["name"]))
    return out
