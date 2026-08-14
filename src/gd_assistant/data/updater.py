"""Build/refresh the JSON KB from datamined game files (SPEC §6.3).

Pipeline:  install dir  ->  read .arz (base + expansions) natively  ->  merge
           ->  resolve tags from Text_<LANG>.arc  ->  normalise  ->  data/kb/*.json

No external tools: reading is done by `knowledge.arz` / `knowledge.arc`; record
locations by `knowledge.extractor`; field mapping by `data.normalise`. Expansion
databases override base records with the same path, so the KB reflects the full
installed content (base + AoM + FG + FoA).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from gd_assistant.data import damage, normalise
from gd_assistant.knowledge import extractor, loot
from gd_assistant.knowledge.arc import load_text_tags
from gd_assistant.knowledge.arz import ArzDatabase, ArzRecord

# Only decode records we actually normalise (skips monsters, FX, ...). The devotion
# trees resolve constellation -> star button -> granted skill (for damage/role tags):
# ui/.../devotion/ holds the constellations + star buttons, skills/devotion/ the skills.
_KB_PREFIXES = (
    "records/skills/playerclass",
    "records/skills/devotion/",
    "records/ui/skills/devotion/",
    "records/items/",
)

# Skill records to damage-type index: player skills (targets of item +skills) and
# item-granted skills (targets of granted_skill). Lets items_enabling() also match
# gear that boosts/grants damage skills, not just gear with raw damage stats.
_SKILL_DAMAGE_PREFIXES = (
    "records/skills/playerclass",
    "records/skills/itemskills",
)


def merge_records(database_files: list[Path]) -> dict[str, ArzRecord]:
    """Merge the KB-relevant records across databases (later files win)."""
    merged: dict[str, ArzRecord] = {}
    for arz_path in database_files:
        db = ArzDatabase.open(arz_path)
        for prefix in _KB_PREFIXES:
            for rec in db.records(path_prefix=prefix):
                merged[rec.path] = rec
    return merged


def _monster_records(database_files: list[Path]) -> dict[str, ArzRecord]:
    """Materialise `Monster` records (for the item -> droppers index)."""
    records: dict[str, ArzRecord] = {}
    for arz_path in database_files:
        db = ArzDatabase.open(arz_path)
        for rec in db.records(path_prefix="records/creatures/"):
            if rec.record_class == "Monster":
                records[rec.path] = rec
    return records


def _skill_records(database_files: list[Path]) -> dict[str, ArzRecord]:
    """Materialise player + item-granted skill records (so linked lookups resolve)."""
    records: dict[str, ArzRecord] = {}
    for arz_path in database_files:
        db = ArzDatabase.open(arz_path)
        for prefix in _SKILL_DAMAGE_PREFIXES:
            for rec in db.records(path_prefix=prefix):
                records[rec.path] = rec
    return records


def _resolve_skill_name(rec: ArzRecord, records: dict[str, ArzRecord], tags: dict[str, str]):
    """Skill display name from the record or anywhere along its buff/pet chain."""
    for candidate in [rec, *damage.linked_chain(rec, records)]:
        tag = candidate.fields.get("skillDisplayName")
        if isinstance(tag, str) and tag:
            return tags.get(tag, tag)
    return None


def build_skill_indexes(
    database_files: list[Path], tags: dict[str, str],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Return (skill_damage, skill_names) over player + item-granted skills.

    Both resolve through each skill's linked buff/pet chain, so item-granted skills
    (e.g. procs) and pet modifiers get correct names and damage types.
    """
    records = _skill_records(database_files)
    damage_index: dict[str, list[str]] = {}
    name_index: dict[str, str] = {}
    for path, rec in records.items():
        types = damage.skill_damage_types(rec, records)
        if types:
            damage_index[path] = types
        name = _resolve_skill_name(rec, records, tags)
        if name:
            name_index[path] = name
    return damage_index, name_index


def build_kb(install_dir: Path, out_dir: Path, language: str = "EN") -> dict[str, int]:
    """Read game data and (re)build the JSON KB under `out_dir`. Returns counts."""
    install_dir = Path(install_dir)
    if not extractor.looks_like_install(install_dir):
        raise FileNotFoundError(f"not a Grim Dawn install (no database/database.arz): {install_dir}")

    database_files = extractor.find_database_files(install_dir)

    # Merge localisation base-first so expansion tags override (expansion masteries
    # like Inquisitor/Necromancer/Oathkeeper/Berserker are only named in gdx* text).
    text_archives = extractor.find_text_archives(install_dir, language)
    tags: dict[str, str] = {}
    for arc_path in text_archives:
        tags.update(load_text_tags(arc_path))

    records = merge_records(database_files)
    skill_damage, skill_names = build_skill_indexes(database_files, tags)

    masteries = normalise.normalise_masteries(records, tags)
    skills = normalise.normalise_skills(records, tags, masteries)
    devotion = normalise.normalise_devotion(records, tags)
    items = normalise.normalise_items(records, tags)

    # "Obtained from": walk Monster loot tables (already in `records`) down to the
    # items we track. Monsters live under records/creatures/, read separately.
    monsters = _monster_records(database_files)
    item_sources = loot.build_item_sources(
        records, monsters, tags, {item["id"] for item in items}
    )

    meta_common = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "language": language,
        "source_files": [str(p.relative_to(install_dir)) for p in database_files],
        "text_files": [str(p.relative_to(install_dir)) for p in text_archives],
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "masteries": ("masteries", masteries),
        "skills": ("skills", skills),
        "devotion": ("constellations", devotion),
        "items": ("items", items),
    }
    counts: dict[str, int] = {}
    for filename, (key, data) in payloads.items():
        doc = {"meta": {**meta_common, "category": filename, "count": len(data)}, key: data}
        (out_dir / f"{filename}.json").write_text(
            json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        counts[filename] = len(data)

    # Flat {skill_path: ...} lookups (not record lists) used by the repository to
    # match/name gear that grants or boosts skills — covers item-granted & pet skills.
    for filename, key, data in (
        ("skill_damage", "skill_damage", skill_damage),
        ("skill_names", "skill_names", skill_names),
        ("item_sources", "item_sources", item_sources),
        ("class_names", "class_names", normalise.normalise_class_names(tags)),
    ):
        (out_dir / f"{filename}.json").write_text(
            json.dumps({"meta": {**meta_common, "category": filename, "count": len(data)},
                        key: data}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        counts[filename] = len(data)
    return counts


def _default_out_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "kb"


def main(argv: list[str] | None = None) -> int:
    """CLI: build the KB. `gd-assistant-build-kb <install_dir> [out_dir] [--lang XX]`.

    If `install_dir` is omitted, tries the saved config, then auto-detection.
    """
    import argparse

    from gd_assistant.config.settings import Settings

    parser = argparse.ArgumentParser(description="Build the Grim Dawn knowledge base from a game install.")
    parser.add_argument("install_dir", nargs="?", help="Grim Dawn install directory")
    parser.add_argument("out_dir", nargs="?", help="output dir for kb/*.json (default: data/kb)")
    parser.add_argument("--lang", default="EN", help="localisation language (default: EN)")
    args = parser.parse_args(argv)

    settings = Settings.load()
    install = args.install_dir or settings.game_install_dir
    if not install:
        raise SystemExit("No install dir given and none saved in config. Pass it explicitly.")

    out_dir = Path(args.out_dir) if args.out_dir else _default_out_dir()
    counts = build_kb(Path(install), out_dir, language=args.lang)

    # Remember the install for next time.
    settings.game_install_dir = str(install)
    settings.save()

    print(f"KB written to {out_dir}:")
    for name, n in counts.items():
        print(f"  {name:10} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
