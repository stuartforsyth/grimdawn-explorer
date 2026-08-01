"""Load and query the JSON knowledge base under `data/kb/` (SPEC §6.4).

Read side of the KB produced by `data.updater`. Loads the four JSON files lazily
and exposes typed lookups the suggestion engine and UI need (skills by mastery,
items by slot/rarity, resolving +skill paths to names, etc.). Dict-backed for the
MVP; can be wrapped in the `models.*` dataclasses later.
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

from gd_assistant.data import colors, damage, labels

# Repo-root/data/kb — where updater.build_kb writes by default.
KB_DIR = Path(__file__).resolve().parents[3] / "data" / "kb"

_RARITY_ORDER = {"Broken": 0, "Common": 1, "Magical": 2, "Rare": 3, "Epic": 4, "Legendary": 5}

# Notable named enemies (the reliable farm targets) get the highlighted "Dropped by"
# row; everything else (Champion/Quest/Common) stays on the plain row.
_BOSS_TIERS = ("SuperBoss", "Boss", "Hero")


def _tokenise(query: str) -> list[str]:
    """Split a search query into lowercased terms, honouring double-quoted phrases.

    A double-quoted run becomes one term matched as a contiguous phrase, so
    `"converted to cold"` requires those words adjacent, whereas `converted to cold`
    (no quotes) is three terms that may match anywhere. An unterminated quote runs to
    the end of the string, so a phrase still narrows results while it's being typed.
    """
    q = query.lower()
    tokens: list[str] = []
    i, n = 0, len(q)
    while i < n:
        c = q[i]
        if c.isspace():
            i += 1
        elif c == '"':
            end = q.find('"', i + 1)
            if end == -1:  # unterminated -> treat the rest as one phrase
                phrase = q[i + 1:].strip()
                if phrase:
                    tokens.append(phrase)
                break
            phrase = q[i + 1:end].strip()
            if phrase:
                tokens.append(phrase)
            i = end + 1
        else:
            start = i
            while i < n and not q[i].isspace() and q[i] != '"':
                i += 1
            tokens.append(q[start:i])
    return tokens


def _fmt_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        nums = [x for x in value if isinstance(x, (int, float))]
        if nums:  # per-level array -> show the range
            return f"{nums[0]:g}–{nums[-1]:g}" if nums[0] != nums[-1] else f"{nums[0]:g}"
    return str(value)


class KnowledgeBase:
    """In-memory, queryable view over the datamined JSON KB."""

    def __init__(self, kb_dir: Path = KB_DIR) -> None:
        self.kb_dir = Path(kb_dir)

    # -- existence / meta -------------------------------------------------
    def is_built(self) -> bool:
        return all((self.kb_dir / f"{n}.json").exists()
                   for n in ("masteries", "skills", "devotion", "items"))

    def meta(self) -> dict:
        """Return the meta header from the skills file (built_at, sources, ...)."""
        return self._load("skills").get("meta", {})

    # -- raw sections (cached) -------------------------------------------
    @cached_property
    def masteries(self) -> list[dict]:
        return self._load("masteries")["masteries"]

    @cached_property
    def skills(self) -> list[dict]:
        return self._load("skills")["skills"]

    @cached_property
    def devotion(self) -> list[dict]:
        return self._load("devotion")["constellations"]

    @cached_property
    def items(self) -> list[dict]:
        return self._load("items")["items"]

    @cached_property
    def skill_damage(self) -> dict[str, list[str]]:
        """{skill_path: [damage_types]} — empty if the index wasn't built."""
        return self._load_index("skill_damage")

    @cached_property
    def skill_names(self) -> dict[str, str]:
        """{skill_path: name} for all skills (incl. item-granted/pet) — empty if absent."""
        return self._load_index("skill_names")

    @cached_property
    def item_sources(self) -> dict[str, dict]:
        """{item_path: {"count": n, "droppers": [{name, class}]}} — empty if absent.

        Keyed by lowercased item path (see `knowledge.loot`). Items absent here have no
        specific dropper in the data — i.e. they are random world drops.
        """
        return self._load_index("item_sources")

    def _load_index(self, name: str) -> dict:
        path = self.kb_dir / f"{name}.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))[name]

    # -- indexes ----------------------------------------------------------
    @cached_property
    def _skill_by_id(self) -> dict[str, dict]:
        return {s["id"]: s for s in self.skills}

    @cached_property
    def _item_by_id(self) -> dict[str, dict]:
        return {i["id"]: i for i in self.items}

    @cached_property
    def _mastery_by_record(self) -> dict[str, dict]:
        return {m["record"]: m for m in self.masteries if m.get("record")}

    @cached_property
    def _item_search_index(self) -> dict[str, str]:
        """Item id -> lowercased searchable text (name + properties)."""
        index: dict[str, str] = {}
        for item in self.items:
            parts: list[str] = [
                item.get("name") or "", item.get("rarity") or "",
                item.get("slot") or "", item.get("category") or "", item.get("set") or "",
            ]
            granted = item.get("granted_skill")
            if granted:
                parts.append(self.skill_name(granted) or "")
            for sid in (item.get("plus_skills") or {}):
                parts.append(self.skill_name(sid) or "")
                skill = self.skill(sid)
                if skill and skill.get("mastery"):
                    parts.append(skill["mastery"])  # e.g. "occultist" matches +occultist skills
            for mid in (item.get("plus_mastery") or {}):
                parts.append((self._mastery_by_record.get(mid) or {}).get("name") or "")
            stats = item.get("stats") or {}
            conversions, conv_keys = labels.conversions(stats)
            if conversions:  # e.g. "Damage Conversion | 30% Cold damage converted to Physical damage"
                parts.append("Damage Conversion")
                parts.extend(phrase for phrase, _ in conversions)
            stat_fields = list(item.get("offensive") or {}) + list(stats)
            for field in stat_fields:
                if field in conv_keys:
                    continue  # folded into the conversion phrase(s) above
                parts.append(labels.friendly(field))
                dtype = damage.field_type(field)
                if dtype:
                    parts.append(dtype)
            src = self.item_sources.get(item["id"].lower())
            if src:  # searchable by dropper name ("kyzogg") or "world drop"
                parts.extend(d["name"] for d in src["droppers"])
                parts.append("World drop" if not src["droppers"] else "Dropped by")
            index[item["id"]] = " | ".join(p for p in parts if p).lower()
        return index

    # -- queries ----------------------------------------------------------
    def skills_for(self, mastery: str) -> list[dict]:
        """Skills for a mastery, by display name (e.g. "Soldier") or dir ("playerclass01")."""
        return [s for s in self.skills
                if mastery in (s.get("mastery"), s.get("mastery_dir"))]

    def skill(self, skill_id: str) -> dict | None:
        return self._skill_by_id.get(skill_id)

    def skill_name(self, skill_id: str) -> str | None:
        """Resolve a skill record path to its display name (for +skills, granted, etc.).

        Checks the player-skill list first, then the broader skill-name index (which
        also covers item-granted and pet skills).
        """
        s = self._skill_by_id.get(skill_id)
        if s:
            return s["name"]
        return self.skill_names.get(skill_id)

    def item(self, item_id: str) -> dict | None:
        return self._item_by_id.get(item_id)

    def item_sources_for(self, item_id: str) -> dict | None:
        """{"count": n, "droppers": [{name, class}]} for an item, or None (world drop)."""
        return self.item_sources.get(item_id.lower())

    def search_items(
        self, query: str = "", *, sort_by: str = "level", descending: bool = False,
    ) -> list[dict]:
        """Search items by name OR property text; sortable.

        Every term in `query` must appear in the item's name or one of its properties
        (rarity, slot, set, granted/+skill names, damage types, friendly stat labels).
        Terms are whitespace-separated, but a `"double-quoted"` run is one term matched
        as a contiguous phrase (e.g. `"converted to cold"`; properties are indexed with
        ` | ` separators, so a phrase only matches within a single property).
        `sort_by` ∈ {"level", "item_level", "name", "rarity"}.
        """
        terms = _tokenise(query)
        if terms:
            index = self._item_search_index
            result = [it for it in self.items
                      if all(t in index[it["id"]] for t in terms)]
        else:
            result = list(self.items)
        return self._sort_items(result, sort_by, descending)

    def sort_items(self, items: list[dict], sort_by: str, descending: bool = False) -> list[dict]:
        """Public sort helper (used to keep pinned rows ordered like the rest)."""
        return self._sort_items(items, sort_by, descending)

    @staticmethod
    def _sort_items(items: list[dict], sort_by: str, descending: bool) -> list[dict]:
        def key(item: dict):
            if sort_by in ("name", "slot"):
                return (0, (item.get(sort_by) or "").lower())
            if sort_by == "rarity":
                return (0, _RARITY_ORDER.get(item.get("rarity"), -1))
            value = item.get("item_level" if sort_by == "item_level" else "level_requirement")
            # None sorts last regardless of direction.
            return (1, 0) if value is None else (0, value)
        return sorted(items, key=key, reverse=descending)

    def item_properties(self, item: dict) -> list[tuple[str, str, str | None]]:
        """Ordered (label, value, colour) rows for the detail panel.

        `colour` is a hex string for stat rows that map to a damage type / coloured
        stat (see `data.colors`, matching the in-game Rainbow-Filter grouping), else
        None to use the default text colour. `+skill` values include the class the
        skill belongs to in parentheses, e.g. "Maelstrom (Shaman)".
        """
        rarity_col = colors.rarity_color(item.get("rarity"))
        rows: list[tuple[str, str, str | None]] = [("Name", item["name"], rarity_col)]
        for label, field in (("Rarity", "rarity"), ("Slot", "slot"), ("Category", "category"),
                             ("Required Level", "level_requirement"), ("Item Level", "item_level"),
                             ("Set", "set")):
            if item.get(field) not in (None, ""):
                # tint the rarity value itself; other header rows stay default
                rows.append((label, str(item[field]), rarity_col if field == "rarity" else None))

        granted = item.get("granted_skill")
        if granted:
            rows.append(("Grants Skill", self.skill_name(granted) or granted.split("/")[-1], None))
        for sid, lvl in (item.get("plus_skills") or {}).items():
            name = self.skill_name(sid) or sid.split("/")[-1]
            skill = self.skill(sid)
            mastery = skill.get("mastery") if skill else None  # class the skill belongs to
            value = f"{name} ({mastery})" if mastery else name
            rows.append((f"+{lvl} to Skill", value, None))
        for mid, lvl in (item.get("plus_mastery") or {}).items():
            mastery = self._mastery_by_record.get(mid)
            rows.append((f"+{lvl} to Mastery", (mastery or {}).get("name") or mid.split("/")[-1], None))
        if item.get("plus_all_skills"):
            rows.append((f"+{item['plus_all_skills']} to All Skills", "", None))

        for field, value in (item.get("offensive") or {}).items():
            rows.append((labels.friendly(field), _fmt_value(value), colors.field_color(field)))
        stats = item.get("stats") or {}
        conversions, conv_keys = labels.conversions(stats)
        for phrase, out_type in conversions:  # one row per conversion slot
            rows.append(("Damage Conversion", phrase, colors.type_color(out_type)))
        for field, value in stats.items():
            if field in conv_keys:
                continue
            rows.append((labels.friendly(field), _fmt_value(value), colors.field_color(field)))

        src = self.item_sources.get(item["id"].lower())
        if src:  # who drops it; absent entirely => no known monster drop source
            boss = [d["name"] for d in src["droppers"] if d["class"] in _BOSS_TIERS]
            other = [d["name"] for d in src["droppers"] if d["class"] not in _BOSS_TIERS]
            if boss:  # notable named enemies -> highlighted orange
                rows.append(("Dropped by (Boss/Hero)", ", ".join(boss), colors.SOURCE_BOSS))
            if other:
                shown = other[:10]
                remaining = src["count"] - len(boss) - len(shown)
                value = ", ".join(shown) + (f" (+{remaining} more)" if remaining > 0 else "")
                rows.append(("Dropped by", value, None))
            if not src["droppers"]:  # in loot tables but no specific dropper
                rows.append(("Source", "World drop", None))
        return rows

    def items_by(self, *, slot: str | None = None, rarity: str | None = None) -> list[dict]:
        result = self.items
        if slot is not None:
            result = [i for i in result if i.get("slot") == slot]
        if rarity is not None:
            result = [i for i in result if i.get("rarity") == rarity]
        return result

    def items_granting_skill(self, skill_id: str) -> list[dict]:
        """Items whose granted skill or +skills reference `skill_id`."""
        return [i for i in self.items
                if i.get("granted_skill") == skill_id or skill_id in (i.get("plus_skills") or {})]

    def items_enabling(self, damage_type: str) -> list[dict]:
        """Items that support a `damage_type` build, ranked, with match reasons.

        `damage_type` accepts friendly names (e.g. "bleed", "poison", "fire"). An item
        matches on any of three grounds, captured in `match`:
          * `stats`         — the item's own `offensive` bonuses of this type,
          * `grants_skill`  — a granted skill that deals this type,
          * `boosts_skills` — +skills to a skill that deals this type.
        Items with raw stats rank first (by strongest bonus), then skill-only support.
        """
        fam = damage.family(damage_type)   # e.g. "fire" -> {Fire, Burn, Elemental}
        sd = self.skill_damage
        matched: list[tuple[bool, float, dict]] = []
        for item in self.items:
            match: dict[str, object] = {}
            stats = {k: v for k, v in (item.get("offensive") or {}).items()
                     if damage.field_type(k) in fam}
            if stats:
                match["stats"] = stats
            granted = item.get("granted_skill")
            if granted and fam.intersection(sd.get(granted, ())):
                match["grants_skill"] = granted
            boosts = [p for p in (item.get("plus_skills") or {})
                      if fam.intersection(sd.get(p, ()))]
            if boosts:
                match["boosts_skills"] = boosts

            if match:
                stats = match.get("stats")
                score = max(stats.values()) if isinstance(stats, dict) else 0.0
                matched.append((bool(stats), score, {**item, "match": match}))
        # stat-bearing items first (by strength); then skill-only (stable by name order).
        matched.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [item for _, _, item in matched]

    # -- internals --------------------------------------------------------
    def _load(self, name: str) -> dict:
        path = self.kb_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"KB file {path} not found — build it first with data.updater.build_kb()."
            )
        return json.loads(path.read_text(encoding="utf-8"))
