"""Tests for the item -> droppers ("obtained from") reverse index."""

from __future__ import annotations

from gd_assistant.knowledge.arz import ArzRecord
from gd_assistant.knowledge.loot import build_item_sources


def _rec(path: str, cls: str, **fields: object) -> ArzRecord:
    return ArzRecord(path, cls, dict(fields))


def test_build_item_sources_walks_tables_and_ranks_droppers():
    tags = {"tagBoss": "Gravebane", "tagHero": "Sethris"}  # tagMissing intentionally absent

    mi = "records/items/mi/gravebane_ring.dbr"          # boss-specific drop
    shared = "records/items/gear/shared_amulet.dbr"     # in a shared pool
    worlddrop = "records/items/gear/world_legendary.dbr"  # in a pool no monster references
    absent = "records/items/gear/crafted_only.dbr"      # in no loot table at all
    component = "records/items/materia/comp.dbr"        # a leaf we don't track

    records = {
        # master table -> a nested item table + a direct MI item
        "records/items/loottables/mt_boss.dbr": _rec(
            "records/items/loottables/mt_boss.dbr", "LootMasterTable",
            lootName1="records/items/loottables/it_gear.dbr", lootWeight1=1000,
            lootName2=mi, lootWeight2=500),
        # item table -> the shared amulet + an untracked component
        "records/items/loottables/it_gear.dbr": _rec(
            "records/items/loottables/it_gear.dbr", "LootItemTable_DynWeight",
            lootName1=shared, lootName2=component,
            prefixTableName1="records/items/lootaffixes/prefix/p.dbr"),  # affix ref -> ignored
        # a self-referential table must not loop forever
        "records/items/loottables/it_loop.dbr": _rec(
            "records/items/loottables/it_loop.dbr", "LootMasterTable",
            lootName1="records/items/loottables/it_loop.dbr"),
        # a pool that no monster references -> its items are random world drops
        "records/items/loottables/it_world.dbr": _rec(
            "records/items/loottables/it_world.dbr", "LootItemTable_DynWeight",
            lootName1=worlddrop),
    }
    monsters = {
        "records/creatures/boss.dbr": _rec(
            "records/creatures/boss.dbr", "Monster",
            description="tagBoss", monsterClassification="Boss",
            lootMisc1Item1="records/items/loottables/mt_boss.dbr"),
        # a hero also drops the shared amulet, and its own table loops (guard test)
        "records/creatures/hero.dbr": _rec(
            "records/creatures/hero.dbr", "Monster",
            description="tagHero", monsterClassification="Hero",
            lootChestItem1="records/items/loottables/it_gear.dbr",
            lootMisc1Item1="records/items/loottables/it_loop.dbr"),
        # unnamed monster (no resolvable tag) contributes nothing
        "records/creatures/trash.dbr": _rec(
            "records/creatures/trash.dbr", "Monster",
            description="tagMissing", monsterClassification="Common",
            lootMisc1Item1="records/items/loottables/mt_boss.dbr"),
    }
    tracked = {mi, shared, worlddrop, absent}

    out = build_item_sources(records, monsters, tags, tracked)

    # MI reachable only from the boss
    assert out[mi] == {"count": 1, "droppers": [{"name": "Gravebane", "class": "Boss"}]}
    # shared amulet: both boss (via nested table) and hero; Boss ranks before Hero
    assert out[shared]["count"] == 2
    assert [d["name"] for d in out[shared]["droppers"]] == ["Gravebane", "Sethris"]
    # in a loot table but no specific dropper -> surfaced as a world drop
    assert out[worlddrop] == {"count": 0, "droppers": [], "world_drop": True}
    # in no loot table at all, and the untracked component, never appear
    assert absent not in out
    assert not any("comp" in k for k in out)


def test_build_item_sources_dedupes_and_caps():
    tags = {f"t{i}": f"Mob{i}" for i in range(30)}
    item = "records/items/gear/x.dbr"
    table = "records/items/loottables/t.dbr"
    records = {table: _rec(table, "LootItemTable_DynWeight", lootName1=item)}
    # 30 distinct monsters all dropping the same item, plus a duplicate name
    monsters = {
        f"records/creatures/m{i}.dbr": _rec(
            f"records/creatures/m{i}.dbr", "Monster",
            description=f"t{i}", monsterClassification="Hero", lootMisc1Item1=table)
        for i in range(30)
    }
    out = build_item_sources(records, monsters, tags, {item}, cap=25)
    assert out[item]["count"] == 30          # true total preserved
    assert len(out[item]["droppers"]) == 25  # list capped
