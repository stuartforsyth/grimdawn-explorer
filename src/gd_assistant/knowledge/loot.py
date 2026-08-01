"""Reverse "obtained from" index: which monsters can drop each item (SPEC §11).

Grim Dawn's drop data is fully in the `.arz` — this reconstructs it natively (no
grimtools). The forward graph is:

    Monster.loot*Item*  ->  LootMasterTable.lootName*  ->  (nested tables) / item

so we invert it. For every monster we walk its top-level loot tables down to the
item leaves it can yield, then record the monster as a *source* of each of those
items. Monster names resolve from the `description` tag via `Text_<LANG>.arc`, the
same way item names do.

Two honest limitations, both inherent to the data (see the module that documents
them, `loot-drop-source-data-model`):
  * **World drops** — legendaries sitting only in generic rarity/type pools (e.g.
    Asterllonos in "any legendary caster 1h") are reachable from the dynamic loot
    system, not from a specific monster, so they simply have no droppers here.
  * **Where** — spawn *location* (which region) lives in the map files, not the
    item DB, so this gives *who* drops an item, not *where* they live.
"""

from __future__ import annotations

from gd_assistant.knowledge.arz import ArzRecord

# lootName* children we follow; other *TableName* fields on item tables are affix
# (prefix/suffix/broken) references, not item drops, so they're deliberately ignored.
_CHILD_PREFIX = "lootName"
_TABLE_CLASSES = ("LootMasterTable", "LootItemTable_DynWeight")

# Rank droppers so the most notable enemy shows first in a capped list.
_CLASS_RANK = {"SuperBoss": 0, "Boss": 1, "Nemesis": 2, "Hero": 3,
               "Quest": 4, "Champion": 5, "Common": 6}


def _is_dbr(value: object) -> bool:
    return isinstance(value, str) and value.lower().endswith(".dbr")


def _monster_name(rec: ArzRecord, tags: dict[str, str]) -> str | None:
    tag = rec.fields.get("description")
    if isinstance(tag, str) and tag in tags:
        return tags[tag]
    return None


def _table_children(records: dict[str, ArzRecord]) -> dict[str, list[str]]:
    """table path -> its lootName* child paths (other tables or item leaves)."""
    children: dict[str, list[str]] = {}
    for path, rec in records.items():
        if rec.record_class not in _TABLE_CLASSES:
            continue
        kids = [v.lower() for k, v in rec.fields.items()
                if k.startswith(_CHILD_PREFIX) and _is_dbr(v)]
        if kids:
            children[path.lower()] = kids
    return children


def build_item_sources(
    records: dict[str, ArzRecord],
    monsters: dict[str, ArzRecord],
    tags: dict[str, str],
    item_paths: set[str],
    *,
    cap: int = 25,
) -> dict[str, dict]:
    """Map item path -> {"count": n, "droppers": [{name, class}], "world_drop": bool}.

    `records` supplies the loot tables (they live under `records/items/loottables/`),
    `monsters` the `Monster` records, `item_paths` the lowercased set of items we track
    (leaves are filtered to these, so components/materials are excluded). `count` is the
    true number of distinct droppers; `droppers` is capped at `cap`, ranked by how
    notable the enemy is (SuperBoss/Boss/Hero first). An item that appears in a loot
    table but has no specific dropper (only generic pools — a random world drop) still
    gets an entry, with empty `droppers` and `world_drop=True`. Items absent entirely
    have no known monster drop source (crafted/quest/vendor — the data can't say).
    """
    item_paths = {p.lower() for p in item_paths}
    children = _table_children(records)
    is_table = children.__contains__

    # Tracked items that appear anywhere in a loot table => obtainable as a drop.
    droppable = {c for kids in children.values() for c in kids if c in item_paths}

    # Memoised: item leaves reachable from a table (cycle-guarded).
    reach_cache: dict[str, frozenset[str]] = {}

    def reach(table: str, stack: frozenset[str]) -> frozenset[str]:
        if table in reach_cache:
            return reach_cache[table]
        if table in stack:
            return frozenset()  # guard against a table referencing itself
        inner = stack | {table}
        found: set[str] = set()
        for child in children.get(table, ()):
            if is_table(child):
                found |= reach(child, inner)
            elif child in item_paths:
                found.add(child)
        result = frozenset(found)
        reach_cache[table] = result
        return result

    # item path -> list of (rank, name, class) droppers
    sources: dict[str, list[tuple[int, str, str]]] = {}
    for rec in monsters.values():
        if rec.record_class != "Monster":
            continue
        name = _monster_name(rec, tags)
        if not name:
            continue
        classification = rec.fields.get("monsterClassification") or "Common"
        rank = _CLASS_RANK.get(classification, 9)
        # Every item this monster can yield, via its own loot fields.
        items: set[str] = set()
        for key, value in rec.fields.items():
            if not (key.startswith("loot") and _is_dbr(value)):
                continue
            v = value.lower()
            if is_table(v):
                items |= reach(v, frozenset())
            elif v in item_paths:
                items.add(v)
        for item in items:
            sources.setdefault(item, []).append((rank, name, str(classification)))

    out: dict[str, dict] = {}
    for item, droppers in sources.items():
        # dedupe by monster name, keep the best (lowest) rank per name
        best: dict[str, tuple[int, str]] = {}
        for rank, name, cls in droppers:
            if name not in best or rank < best[name][0]:
                best[name] = (rank, cls)
        ranked = sorted(((r, name, cls) for name, (r, cls) in best.items()))
        out[item] = {
            "count": len(ranked),
            "droppers": [{"name": name, "class": cls} for _r, name, cls in ranked[:cap]],
        }
    # World drops: droppable, but with no specific notable dropper of their own.
    for item in droppable:
        if item not in out:
            out[item] = {"count": 0, "droppers": [], "world_drop": True}
    return out
