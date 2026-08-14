"""Tests for KB normalisation, the repository, and a real-data build.

Normaliser/repository tests are self-contained (they build `ArzRecord`s and JSON in
memory / tmp). `test_real_build_*` run only when a Grim Dawn install is found.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from gd_assistant.data import colors, damage, labels, normalise
from gd_assistant.data.repository import KnowledgeBase
from gd_assistant.knowledge.arz import ArzRecord

TAGS = {
    "tagSoldier": "Soldier",
    "tagBladeArc": "Blade Arc",
    "tagLaceration": "Laceration",
    "tagCleanSweep": "Clean Sweep",
    "tagCrab": "Crab",
    "tagSiphon": "Siphon Souls",
    "tagBloodPact": "Blood Pact",
    "tagAmulet": "Thread of Mortality",
    "tagSetName": "The Example Set",
}


def _records(*recs: ArzRecord) -> dict[str, ArzRecord]:
    return {r.path: r for r in recs}


# --------------------------------------------------------------------------- #
# normalisers
# --------------------------------------------------------------------------- #
def _mastery_rec() -> ArzRecord:
    return ArzRecord(
        "records/skills/playerclass01/_classtraining_class01.dbr", "Skill_Mastery",
        {"skillDisplayName": "tagSoldier", "MasteryEnumeration": "SkillClass01",
         "skillMaxLevel": 50, "FileDescription": "Soldier"},
    )


def test_normalise_masteries():
    out = normalise.normalise_masteries(_records(_mastery_rec()), TAGS)
    assert out == [{
        "id": "SkillClass01", "name": "Soldier",
        "record": "records/skills/playerclass01/_classtraining_class01.dbr",
        "dir": "playerclass01", "bar_max_level": 50,
    }]


def test_normalise_skills_types_and_mastery():
    recs = _records(
        _mastery_rec(),
        ArzRecord("records/skills/playerclass01/bladearc1.dbr", "Skill_AttackWeapon",
                  {"skillDisplayName": "tagBladeArc", "skillMaxLevel": 16,
                   "skillUltimateLevel": 26, "skillTier": 3}),
        ArzRecord("records/skills/playerclass01/bladearc2.dbr", "Skill_Modifier",
                  {"skillDisplayName": "tagLaceration", "skillMaxLevel": 12}),
        ArzRecord("records/skills/playerclass01/bladearc1b.dbr", "Skill_Transmuter",
                  {"skillDisplayName": "tagCleanSweep", "skillMaxLevel": 1}),
        # unnamed internal helper -> skipped
        ArzRecord("records/skills/playerclass01/somebuff.dbr", "SkillBuff_Passive", {}),
    )
    masteries = normalise.normalise_masteries(recs, TAGS)
    skills = normalise.normalise_skills(recs, TAGS, masteries)
    by_name = {s["name"]: s for s in skills}
    assert set(by_name) == {"Blade Arc", "Laceration", "Clean Sweep"}
    assert by_name["Blade Arc"]["type"] == "active"
    assert by_name["Blade Arc"]["mastery"] == "Soldier"
    assert by_name["Laceration"]["type"] == "modifier"
    assert by_name["Clean Sweep"]["type"] == "transmuter"


def test_normalise_skills_resolves_buff_named_skill():
    # base active has no name/damage; both live on its linked buff (like Siphon Souls).
    recs = _records(
        ArzRecord("records/skills/playerclass08/soulsiphon1.dbr", "Skill_AttackBuffRadius",
                  {"buffSkillName": "records/skills/playerclass08/soulsiphon1_buff.dbr",
                   "skillMaxLevel": 12, "skillTier": 1}),
        ArzRecord("records/skills/playerclass08/soulsiphon1_buff.dbr", "SkillBuff_Debuf",
                  {"skillDisplayName": "tagSiphon",
                   "offensiveLifeModifier": [10.0, 20.0, 30.0]}),  # Vitality damage
    )
    skills = normalise.normalise_skills(recs, TAGS, [])
    assert len(skills) == 1                      # buff child collapsed into the base
    (skill,) = skills
    assert skill["id"].endswith("soulsiphon1.dbr")
    assert skill["name"] == "Siphon Souls"       # name pulled from the buff
    assert skill["damage_types"] == ["Vitality"]  # damage pulled from the buff


def test_normalise_skills_resolves_two_hop_pet_chain():
    # pet modifier -> pet skill (unnamed) -> its buff (name + damage). Two hops.
    recs = _records(
        ArzRecord("records/skills/playerclass06/totem_petmod.dbr", "SkillSecondary_PetModifier",
                  {"petSkillName": "records/skills/playerclass06/pets/petskill.dbr",
                   "skillMaxLevel": 12}),
        ArzRecord("records/skills/playerclass06/pets/petskill.dbr", "Skill_Passive",
                  {"buffSkillName": "records/skills/playerclass06/pets/petskill_buff.dbr"}),
        ArzRecord("records/skills/playerclass06/pets/petskill_buff.dbr", "SkillBuff_Passive",
                  {"skillDisplayName": "tagBloodPact",
                   "offensiveSlowBleedingModifier": [10.0, 20.0]}),  # Bleeding
    )
    skills = normalise.normalise_skills(recs, TAGS, [])
    # only the pet-modifier is a top-level skill (the pets/ records aren't 4-segment)
    (skill,) = skills
    assert skill["id"].endswith("totem_petmod.dbr")
    assert skill["name"] == "Blood Pact"          # resolved two hops away
    assert skill["damage_types"] == ["Bleeding"]  # damage from the chain end


def test_normalise_devotion():
    rec = ArzRecord(
        "records/ui/skills/devotion/constellations/constellation52.dbr", "",
        {"constellationDisplayTag": "tagCrab",
         "affinityGivenName1": "Ascendant", "affinityGiven1": 3,
         "affinityRequiredName1": "Ascendant", "affinityRequired1": 6,
         "affinityRequiredName2": "Order", "affinityRequired2": 4,
         "devotionButton1": "records/ui/skills/devotion/tier2_17a.dbr",
         "devotionButton2": "records/ui/skills/devotion/tier2_17b.dbr"},
    )
    # star buttons -> granted skills carrying damage (Cold) + defensive/OA stats
    button_a = ArzRecord("records/ui/skills/devotion/tier2_17a.dbr", "",
                         {"skillName": "records/skills/devotion/tier2_17a.dbr"})
    button_b = ArzRecord("records/ui/skills/devotion/tier2_17b.dbr", "",
                         {"skillName": "records/skills/devotion/tier2_17b.dbr"})
    skill_a = ArzRecord("records/skills/devotion/tier2_17a.dbr", "Skill_Passive",
                        {"offensiveColdMin": 20.0, "offensiveColdMax": 40.0,
                         "characterOffensiveAbility": 15.0})
    skill_b = ArzRecord("records/skills/devotion/tier2_17b.dbr", "Skill_Passive",
                        {"defensiveFire": 25.0, "characterConstitution": 10.0})

    (out,) = normalise.normalise_devotion(
        _records(rec, button_a, button_b, skill_a, skill_b), TAGS)
    assert out["name"] == "Crab"
    assert out["affinity_given"] == {"Ascendant": 3}
    assert out["affinity_required"] == {"Ascendant": 6, "Order": 4}
    assert out["star_count"] == 2
    # damage types + capability roles derived from the star skills
    assert out["damage_types"] == ["Cold"]
    assert out["roles"] == ["attributes", "defensive", "offensive"]


def test_normalise_items_with_set_and_augments():
    recs = _records(
        ArzRecord("records/items/lootsets/itemset_x.dbr", "ItemSet",
                  {"setName": "tagSetName"}),
        ArzRecord("records/items/gearaccessories/necklaces/x.dbr", "ArmorJewelry_Amulet",
                  {"itemNameTag": "tagAmulet", "itemClassification": "Legendary",
                   "levelRequirement": 58, "itemSetName": "records/items/lootsets/itemset_x.dbr",
                   "augmentSkillName1": "records/skills/playerclass01/bladearc1.dbr",
                   "augmentSkillLevel1": 3, "augmentAllLevel": 1}),
        # not equippable -> skipped
        ArzRecord("records/items/loottables/t.dbr", "LootItemTable_DynWeight", {}),
    )
    (item,) = normalise.normalise_items(recs, TAGS)
    assert item["name"] == "Thread of Mortality"
    assert item["slot"] == "Amulet"
    assert item["category"] == "ArmorJewelry"
    assert item["rarity"] == "Legendary"
    assert item["set"] == "The Example Set"
    assert item["plus_skills"] == {"records/skills/playerclass01/bladearc1.dbr": 3}
    assert item["plus_all_skills"] == 1


def test_normalise_items_captures_offensive_bonuses():
    rec = ArzRecord("records/items/gearweapons/swords2h/x.dbr", "WeaponMelee_Sword2h", {
        "itemNameTag": "tagBladeArc",  # any resolvable name
        "offensiveSlowBleedingModifier": 500.0,   # +500% Bleeding damage
        "offensiveSlowBleedingMax": 85.0,         # flat bleeding
        "offensiveSlowBleedingChance": 100.0,     # a proc-chance flag -> skipped
        "offensiveSlowBleedingGlobal": True,       # bool flag -> skipped
        "offensivePhysicalMin": 0.0,               # zero -> skipped
        "offensiveFireModifier": 40.0,             # unrelated type, still captured
    })
    (item,) = normalise.normalise_items({rec.path: rec}, TAGS)
    off = item["offensive"]
    assert off["offensiveSlowBleedingModifier"] == 500.0
    assert off["offensiveSlowBleedingMax"] == 85.0
    assert off["offensiveFireModifier"] == 40.0
    assert "offensiveSlowBleedingChance" not in off  # chance flag excluded
    assert "offensiveSlowBleedingGlobal" not in off  # bool excluded
    assert "offensivePhysicalMin" not in off          # zero excluded


# --------------------------------------------------------------------------- #
# repository
# --------------------------------------------------------------------------- #
def _write_kb(tmp: Path) -> None:
    (tmp / "masteries.json").write_text(json.dumps({"meta": {}, "masteries": [
        {"id": "SkillClass01", "name": "Soldier", "dir": "playerclass01", "bar_max_level": 50},
        {"id": "SkillClass02", "name": "Nightblade", "dir": "playerclass02", "bar_max_level": 50}]}))
    (tmp / "skills.json").write_text(json.dumps({"meta": {"built_at": "x"}, "skills": [
        {"id": "records/skills/playerclass01/bladearc1.dbr", "name": "Blade Arc",
         "mastery": "Soldier", "mastery_dir": "playerclass01", "type": "active",
         "max_level": 16, "damage_types": ["Physical", "Bleeding"]},
        {"id": "records/skills/playerclass02/ringoffrost.dbr", "name": "Ring of Frost",
         "mastery": "Nightblade", "mastery_dir": "playerclass02", "type": "active",
         "max_level": 12, "damage_types": ["Cold"]}]}))
    (tmp / "devotion.json").write_text(json.dumps({"meta": {}, "constellations": [
        {"id": "d1", "name": "Crab", "description": "a shield", "star_count": 3, "stars": [],
         "affinity_required": {"Order": 4}, "affinity_given": {"Ascendant": 3},
         "damage_types": [], "roles": ["defensive"]},
        {"id": "d2", "name": "Hawk", "description": "swift", "star_count": 3, "stars": [],
         "affinity_required": {"Eldritch": 5}, "affinity_given": {},
         "damage_types": ["Cold", "Pierce"], "roles": ["offensive", "speed"]}]}))
    # broader name index also covers item-granted / pet skills not in skills.json
    (tmp / "skill_names.json").write_text(json.dumps({"meta": {}, "skill_names": {
        "records/skills/itemskills/legendary/item_gore.dbr": "Gorefeast Proc"}}))
    (tmp / "items.json").write_text(json.dumps({"meta": {}, "items": [
        {"id": "i1", "name": "Ring of X", "slot": "Ring", "rarity": "Legendary",
         "level_requirement": 90, "item_level": 94,
         "granted_skill": None, "plus_skills": {"records/skills/playerclass01/bladearc1.dbr": 2},
         "offensive": {"offensiveSlowBleedingModifier": 40.0}, "stats": {"defensiveFire": 25.0}},
        {"id": "i2", "name": "Gutwrench", "slot": "Sword2h", "rarity": "Epic",
         "level_requirement": 17, "item_level": 14,
         "granted_skill": None, "plus_skills": {}, "stats": {},
         "offensive": {"offensiveSlowBleedingModifier": 500.0, "offensiveSlowBleedingMax": 85.0}},
        {"id": "i3", "name": "Fire Wand", "slot": "Offhand", "rarity": "Rare",
         "level_requirement": 50, "item_level": 50,
         "granted_skill": None, "plus_skills": {}, "stats": {},
         "offensive": {"offensiveFireModifier": 60.0}},
        {"id": "i4", "name": "Bloodhound Shoulders", "slot": "Shoulders", "rarity": "Epic",
         "level_requirement": 40, "item_level": 40, "granted_skill": None, "plus_skills": {},
         "offensive": {}, "stats": {"conversionInType": "Cold", "conversionOutType": "Physical",
                                    "conversionPercentage": 30.0, "defensivePoison": 12.0}},
        {"id": "i5", "name": "Asterllonos", "slot": "Scepter", "rarity": "Legendary",
         "level_requirement": 94, "item_level": 100, "granted_skill": None, "plus_skills": {},
         "offensive": {}, "stats": {
             "conversionInType": "Lightning", "conversionOutType": "Cold", "conversionPercentage": 45.0,
             "conversionInType2": "Fire", "conversionOutType2": "Cold", "conversionPercentage2": 45.0}}]}))


def test_repository_queries(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    assert kb.is_built()
    assert len(kb.skills_for("Soldier")) == 1
    assert kb.skill_name("records/skills/playerclass01/bladearc1.dbr") == "Blade Arc"
    # item-granted skill resolves via the skill_names index fallback
    assert kb.skill_name("records/skills/itemskills/legendary/item_gore.dbr") == "Gorefeast Proc"
    assert kb.items_by(slot="Ring", rarity="Legendary")[0]["name"] == "Ring of X"
    granting = kb.items_granting_skill("records/skills/playerclass01/bladearc1.dbr")
    assert granting[0]["name"] == "Ring of X"


def test_search_items_by_name_property_and_sort(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    # by name
    assert [i["name"] for i in kb.search_items("gutwrench")] == ["Gutwrench"]
    # by property label: only the ring has Fire Resistance (the wand has % Fire *Damage*)
    assert [i["name"] for i in kb.search_items("fire resistance")] == ["Ring of X"]
    # by damage type token (from offensive fields)
    assert {i["name"] for i in kb.search_items("bleeding")} == {"Ring of X", "Gutwrench"}
    # by class of a +skill: only Ring of X boosts a Soldier skill (Blade Arc)
    assert [i["name"] for i in kb.search_items("soldier")] == ["Ring of X"]
    # multi-term AND: fire (resistance) AND soldier (+skill class) -> Ring of X only
    assert [i["name"] for i in kb.search_items("fire soldier")] == ["Ring of X"]
    # empty query returns all; sort by required level ascending / descending
    asc = [i["name"] for i in kb.search_items("", sort_by="level")]
    assert asc == ["Gutwrench", "Bloodhound Shoulders", "Fire Wand", "Ring of X", "Asterllonos"]
    desc = [i["name"] for i in kb.search_items("", sort_by="level", descending=True)]
    assert desc == ["Asterllonos", "Ring of X", "Fire Wand", "Bloodhound Shoulders", "Gutwrench"]


def test_tokenise_honours_quoted_phrases():
    from gd_assistant.data.repository import _tokenise
    assert _tokenise("converted to cold") == ["converted", "to", "cold"]
    assert _tokenise('"converted to cold"') == ["converted to cold"]
    assert _tokenise('fire "converted to cold" occultist') == ["fire", "converted to cold", "occultist"]
    assert _tokenise('  Fire   "Cold Damage"  ') == ["fire", "cold damage"]  # lowercased, trimmed
    assert _tokenise('"converted to col') == ["converted to col"]  # unterminated -> phrase to end
    assert _tokenise("") == [] and _tokenise('""') == []


def test_search_quoted_phrase_vs_loose_terms(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    # Bloodhound's phrase is "30% cold damage converted to physical damage".
    # Loose terms (any order, anywhere) match; so does the correct contiguous phrase...
    assert [i["name"] for i in kb.search_items("converted physical cold")] == ["Bloodhound Shoulders"]
    assert [i["name"] for i in kb.search_items('"converted to physical"')] == ["Bloodhound Shoulders"]
    # ...but a phrase whose words aren't adjacent in that order does not.
    # (Bloodhound converts TO physical; only Asterllonos converts *to* cold.)
    assert [i["name"] for i in kb.search_items('"converted to cold"')] == ["Asterllonos"]
    assert kb.search_items('"physical converted"') == []          # wrong word order
    # a phrase must stay within one property (the " | " separators are boundaries)
    assert kb.search_items('"physical damage epic"') == []        # spans two properties


def test_search_skills_and_devotions(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    # skills by damage type (and the "<type> damage" phrase)
    assert [s["name"] for s in kb.search_skills("bleeding")] == ["Blade Arc"]
    assert [s["name"] for s in kb.search_skills("physical damage")] == ["Blade Arc"]
    assert [s["name"] for s in kb.search_skills("cold")] == ["Ring of Frost"]  # Blade Arc has none
    # devotions by capability role, damage type, and affinity name
    assert [d["name"] for d in kb.search_devotions("defensive")] == ["Crab"]
    assert [d["name"] for d in kb.search_devotions("cold damage")] == ["Hawk"]
    assert [d["name"] for d in kb.search_devotions("eldritch")] == ["Hawk"]
    assert {d["name"] for d in kb.search_devotions("")} == {"Crab", "Hawk"}  # empty = all
    # detail rows: damage types are colour-coded, roles/affinities surfaced
    hawk = kb.devotion_by_id("d2")
    props = kb.devotion_properties(hawk)
    damage_rows = [(v, c) for label, v, c in props if label == "Damage"]
    assert damage_rows == [("Cold", colors.TYPE_COLORS["Cold"]),
                           ("Pierce", colors.TYPE_COLORS["Pierce"])]
    rows = {label: (value, color) for label, value, color in props}
    assert rows["Capabilities"] == ("offensive, speed", None)
    assert rows["Requires"] == ("Eldritch 5", None)
    srows = {label: value for label, value, _c in kb.skill_properties(kb.skill(
        "records/skills/playerclass01/bladearc1.dbr"))}
    assert srows["Mastery"] == "Soldier" and srows["Max Level"] == "16"


def test_search_skill_class_and_affinity_facets(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    # filter option lists for the UI
    assert kb.mastery_names() == ["Nightblade", "Soldier"]
    assert set(kb.affinity_names()) == {"Ascendant", "Eldritch", "Order"}
    # a single class narrows; an OR set spans several classes (the Nightblade+Berserker use case)
    assert [s["name"] for s in kb.search_skills(masteries={"Soldier"})] == ["Blade Arc"]
    assert {s["name"] for s in kb.search_skills(masteries={"Soldier", "Nightblade"})} == \
        {"Blade Arc", "Ring of Frost"}
    # class filter AND-combines with the text query
    assert kb.search_skills("cold", masteries={"Soldier"}) == []
    assert [s["name"] for s in kb.search_skills("cold", masteries={"Soldier", "Nightblade"})] == \
        ["Ring of Frost"]
    # affinity filter (OR) on devotions
    assert [d["name"] for d in kb.search_devotions(affinities={"Order"})] == ["Crab"]
    assert {d["name"] for d in kb.search_devotions(affinities={"Order", "Eldritch"})} == \
        {"Crab", "Hawk"}


def test_item_sources_dropped_by_row_and_search(tmp_path: Path):
    _write_kb(tmp_path)
    (tmp_path / "item_sources.json").write_text(json.dumps({"meta": {}, "item_sources": {
        # a boss + a hero + a champion drop i5; i4 is a generic world drop
        "i5": {"count": 3, "droppers": [{"name": "Ol' Bloodbriar", "class": "Boss"},
                                        {"name": "Sir Bumbleworth", "class": "Hero"},
                                        {"name": "Some Mook", "class": "Champion"}]},
        "i4": {"count": 0, "droppers": [], "world_drop": True}}}))
    kb = KnowledgeBase(tmp_path)
    rows = {label: (value, color) for label, value, color in kb.item_properties(kb.item("i5"))}
    # notable enemies (boss + hero) get their own row, tinted orange; the rest stay plain
    assert rows["Dropped by (Boss/Hero)"] == ("Ol' Bloodbriar, Sir Bumbleworth", colors.SOURCE_BOSS)
    assert rows["Dropped by"] == ("Some Mook", None)
    # searchable by dropper name...
    assert [i["name"] for i in kb.search_items("bloodbriar")] == ["Asterllonos"]  # i5's name
    # ...and world drops are surfaced as a row and findable via "world drop"
    wrows = {label: value for label, value, _c in kb.item_properties(kb.item("i4"))}
    assert wrows["Source"] == "World drop"
    assert "Bloodhound Shoulders" in {i["name"] for i in kb.search_items('"world drop"')}


def test_item_with_two_conversions_folds_both(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    item = kb.item("i5")  # Asterllonos: Lightning->Cold and Fire->Cold
    conv_rows = [(v, c) for label, v, c in kb.item_properties(item) if label == "Damage Conversion"]
    assert [v for v, _c in conv_rows] == [
        "45% Lightning damage converted to Cold damage",
        "45% Fire damage converted to Cold damage",
    ]
    # both rows tinted by the resulting (Cold) type; no raw Convert* rows leak through
    assert {c for _v, c in conv_rows} == {colors.TYPE_COLORS["Cold"]}
    labels_shown = {label for label, _v, _c in kb.item_properties(item)}
    assert not any("Convert" in l for l in labels_shown if l != "Damage Conversion")
    # each phrase is independently searchable
    assert [i["name"] for i in kb.search_items('"lightning damage converted to cold"')] == ["Asterllonos"]
    assert [i["name"] for i in kb.search_items('"fire damage converted to cold"')] == ["Asterllonos"]


def test_damage_conversion_folded_into_one_row_and_searchable(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    item = kb.item("i4")
    rows = {label: value for label, value, _c in kb.item_properties(item)}
    colours = {label: c for label, _v, c in kb.item_properties(item)}
    # the three raw conversion fields collapse into one readable sentence...
    assert rows["Damage Conversion"] == "30% Cold damage converted to Physical damage"
    assert "Convert From" not in rows and "Convert To" not in rows
    assert "Damage Conversion %" not in rows
    # ...tinted by the resulting (out) damage type, and other stats still shown
    assert colours["Damage Conversion"] == colors.TYPE_COLORS["Physical"]
    assert rows["Poison Resistance"] == "12"
    # the whole phrase — including the type values — is searchable
    assert [i["name"] for i in kb.search_items("cold converted to physical")] == ["Bloodhound Shoulders"]
    # the "Damage Conversion" label is searchable (matches any item with a conversion)
    assert {i["name"] for i in kb.search_items("damage conversion")} == {"Bloodhound Shoulders", "Asterllonos"}


def test_item_properties_labels_and_skill_names(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    ring = kb.item("i1")
    props = kb.item_properties(ring)
    rows = {label: value for label, value, _c in props}
    colours = {label: color for label, _v, color in props}
    assert rows["Required Level"] == "90"
    assert rows["Item Level"] == "94"
    # +skill value shows the resolved name AND the class it belongs to, inline
    assert rows["+2 to Skill"] == "Blade Arc (Soldier)"
    assert rows["% Bleeding Damage"] == "40"        # offensive field labelled
    assert rows["Fire Resistance"] == "25"          # stat field labelled
    # stat rows are colour-coded by type; header rows are not
    assert colours["% Bleeding Damage"] == "#c0392b"   # Bleeding red
    assert colours["Fire Resistance"] == "#d2691e"     # Fire orange (resist shares type colour)
    assert colours["Required Level"] is None
    # name + rarity rows tinted by rarity (Ring of X is Legendary -> purple)
    from gd_assistant.data import colors
    assert colours["Name"] == colors.RARITY_COLORS["Legendary"]
    assert colours["Rarity"] == colors.RARITY_COLORS["Legendary"]


def test_colors_field_color():
    from gd_assistant.data import colors
    # offensive damage fields coloured by damage type
    assert colors.field_color("offensiveFireModifier") == colors.TYPE_COLORS["Fire"]
    assert colors.field_color("offensiveSlowBleedingModifier") == colors.TYPE_COLORS["Bleeding"]
    # resistances share their damage type's colour
    assert colors.field_color("defensiveFire") == colors.TYPE_COLORS["Fire"]
    assert colors.field_color("defensiveFireMaxResist") == colors.TYPE_COLORS["Fire"]
    assert colors.field_color("defensiveLife") == colors.TYPE_COLORS["Vitality"]
    # Pierce shares Bleeding's colour (both ^R in the mod)
    assert colors.field_color("defensivePierce") == colors.field_color("defensiveBleeding")
    # armour / ability get their own tint; unmapped stats stay uncoloured
    assert colors.field_color("defensiveProtection") is not None
    assert colors.field_color("characterRunSpeedModifier") is None
    # rarity colours: known tiers map, unknown/None do not
    assert colors.rarity_color("Legendary") == colors.RARITY_COLORS["Legendary"]
    assert colors.rarity_color("Epic") != colors.rarity_color("Rare")
    assert colors.rarity_color(None) is None


def test_labels_friendly():
    assert labels.friendly("offensiveFireModifier") == "% Fire Damage"
    assert labels.friendly("offensiveFireMax") == "Fire Damage"
    assert labels.friendly("defensiveFire") == "Fire Resistance"
    assert labels.friendly("defensiveFireMaxResist") == "Max Fire Resistance"
    assert labels.friendly("characterStrength") == "Physique"      # GD attribute rename
    assert labels.friendly("skillCooldownReduction") == "% Skill Cooldown Reduction"
    # unknown field -> de-camelCased fallback (prefix stripped)
    assert labels.friendly("characterSomeNovelStat") == "Some Novel Stat"


def test_repository_items_enabling_bleed(tmp_path: Path):
    _write_kb(tmp_path)
    kb = KnowledgeBase(tmp_path)
    bleed = kb.items_enabling("bleed")  # friendly name -> "Bleeding"
    names = [i["name"] for i in bleed]
    assert names == ["Gutwrench", "Ring of X"]  # ranked by strongest bonus, fire excluded
    assert bleed[0]["match"]["stats"]["offensiveSlowBleedingModifier"] == 500.0
    # other damage types work too
    assert [i["name"] for i in kb.items_enabling("fire")] == ["Fire Wand"]


def test_repository_items_enabling_folds_in_skill_gear(tmp_path: Path):
    # Only items.json + skill_damage.json are needed for items_enabling.
    (tmp_path / "skill_damage.json").write_text(json.dumps({"meta": {}, "skill_damage": {
        "records/skills/playerclass01/bladearc2.dbr": ["Bleeding"],   # Laceration
        "records/skills/itemskills/legendary/item_gore.dbr": ["Bleeding"],
        "records/skills/playerclass05/flames.dbr": ["Fire"]}}))
    (tmp_path / "items.json").write_text(json.dumps({"meta": {}, "items": [
        {"id": "a", "name": "Bleed Stat Sword", "slot": "Sword2h", "rarity": "Epic",
         "granted_skill": None, "plus_skills": {},
         "offensive": {"offensiveSlowBleedingModifier": 300.0}},
        {"id": "b", "name": "Laceration Amulet", "slot": "Amulet", "rarity": "Legendary",
         "granted_skill": None,
         "plus_skills": {"records/skills/playerclass01/bladearc2.dbr": 2}, "offensive": {}},
        {"id": "c", "name": "Gore Ring", "slot": "Ring", "rarity": "Legendary",
         "granted_skill": "records/skills/itemskills/legendary/item_gore.dbr",
         "plus_skills": {}, "offensive": {}},
        {"id": "d", "name": "Fire Hat", "slot": "Head", "rarity": "Rare",
         "granted_skill": None,
         "plus_skills": {"records/skills/playerclass05/flames.dbr": 3}, "offensive": {}}]}))
    kb = KnowledgeBase(tmp_path)
    bleed = kb.items_enabling("bleed")
    names = [i["name"] for i in bleed]
    # stat item ranks first; both skill-boost and skill-grant items fold in; fire excluded
    assert names[0] == "Bleed Stat Sword"
    assert set(names) == {"Bleed Stat Sword", "Laceration Amulet", "Gore Ring"}
    by_name = {i["name"]: i["match"] for i in bleed}
    assert by_name["Laceration Amulet"]["boosts_skills"] == \
        ["records/skills/playerclass01/bladearc2.dbr"]
    assert by_name["Gore Ring"]["grants_skill"].endswith("item_gore.dbr")


def test_damage_helpers():
    assert damage.canonical("bleed") == "Bleeding"
    assert damage.canonical("Fire") == "Fire"
    assert damage.field_deals_type("offensiveSlowBleedingModifier") == "Bleeding"
    assert damage.field_deals_type("offensivePhysicalMax") == "Physical"
    # duration / chance fields are not "dealing" damage
    assert damage.field_deals_type("offensiveSlowBleedingDurationMin") is None
    assert damage.field_deals_type("offensiveSlowBleedingChance") is None
    # array-valued (per-level) damage is detected; duration-only is not
    deals = ArzRecord("p", "Skill_Modifier",
                      {"offensiveSlowBleedingModifier": [10.0, 20.0, 30.0]})
    assert damage.skill_damage_types(deals) == ["Bleeding"]
    dur_only = ArzRecord("p", "Skill", {"offensiveSlowBleedingDurationMin": [3.0]})
    assert damage.skill_damage_types(dur_only) == []


def test_repository_missing_kb(tmp_path: Path):
    kb = KnowledgeBase(tmp_path)
    assert not kb.is_built()
    with pytest.raises(FileNotFoundError):
        _ = kb.skills


# --------------------------------------------------------------------------- #
# real-data build (skipped when no install is found)
# --------------------------------------------------------------------------- #
def _find_install() -> Path | None:
    env = os.environ.get("GD_INSTALL_DIR")
    if env and (Path(env) / "database" / "database.arz").exists():
        return Path(env)
    default = Path.home() / ".steam/steam/steamapps/common/Grim Dawn"
    return default if (default / "database" / "database.arz").exists() else None


@pytest.mark.skipif(_find_install() is None, reason="no Grim Dawn install found")
def test_real_build_resolves_all_masteries(tmp_path: Path):
    from gd_assistant.data.updater import build_kb

    counts = build_kb(_find_install(), tmp_path)
    assert counts["masteries"] >= 6
    assert counts["skills"] > 100
    assert counts["items"] > 1000

    masteries = KnowledgeBase(tmp_path).masteries
    # every mastery name must be resolved (no leftover raw tags)
    assert all(m["name"] and not m["name"].startswith("tag") for m in masteries)
    assert "Soldier" in {m["name"] for m in masteries}


# --- class names (combined mastery titles) ---------------------------------

def _kb_with_classes(tmp_path: Path) -> KnowledgeBase:
    """A minimal KB carrying two masteries and the combined-class tag index."""
    (tmp_path / "masteries.json").write_text(json.dumps({"meta": {}, "masteries": [
        {"id": "SkillClass05", "name": "Arcanist", "dir": "playerclass05",
         "record": "records/skills/playerclass05/_classtraining_class05.dbr"},
        {"id": "SkillClass06", "name": "Shaman", "dir": "playerclass06",
         "record": "records/skills/playerclass06/_classtraining_class06.dbr"},
    ]}))
    (tmp_path / "class_names.json").write_text(json.dumps({"meta": {}, "class_names": {
        "tagSkillClassName05": "Arcanist",
        "tagSkillClassName0506": "Druid",
    }}))
    return KnowledgeBase(kb_dir=tmp_path)


def test_normalise_class_names_keeps_only_class_tags() -> None:
    tags = {"tagSkillClassName0506": "Druid", "tagBladeArc": "Blade Arc",
            "tagSkillClassName05": "", "tagSkillClassName01": "Soldier"}
    assert normalise.normalise_class_names(tags) == {
        "tagSkillClassName0506": "Druid", "tagSkillClassName01": "Soldier",
    }


def test_class_description_dual_mastery(tmp_path: Path) -> None:
    """A dual class needs the combined name — "Druid" isn't derivable from its parts."""
    kb = _kb_with_classes(tmp_path)
    assert kb.class_description("tagSkillClassName0506") == "Druid (Arcanist + Shaman)"


def test_class_description_single_mastery_is_not_repeated(tmp_path: Path) -> None:
    kb = _kb_with_classes(tmp_path)
    assert kb.class_description("tagSkillClassName05") == "Arcanist"


def test_class_description_falls_back_without_the_index(tmp_path: Path) -> None:
    """A KB built before class_names existed still names what it can."""
    kb = _kb_with_classes(tmp_path)
    (tmp_path / "class_names.json").unlink()
    kb = KnowledgeBase(kb_dir=tmp_path)
    assert kb.class_description("tagSkillClassName0506") == "Arcanist + Shaman"


def test_class_description_of_an_unknown_tag_is_empty(tmp_path: Path) -> None:
    kb = _kb_with_classes(tmp_path)
    assert kb.class_description("tagSkillClassName99") == ""
    assert kb.class_description("") == ""


def test_mastery_name_resolves_save_ids(tmp_path: Path) -> None:
    kb = _kb_with_classes(tmp_path)
    assert kb.mastery_name("06") == "Shaman"
    assert kb.mastery_name("99") is None
