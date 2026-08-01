# Grim Dawn Build Assistant — Design Specification

> Status: **v0.1 draft** — expands `initialspec.md` into an actionable design.
> Editing scope excluded for this iteration; **read-only** analysis and suggestions only.

## 1. Purpose

A cross-platform Python desktop application that helps a player understand and
advance their Grim Dawn characters. It:

1. Maintains a local, patch-updatable knowledge base of skills and itemisation.
2. Reads local Grim Dawn save files to understand the current character.
3. Explains and suggests skill + item combinations to advance a build, with an
   emphasis on **why** (synergies, itemisation, farming locations) rather than
   just surfacing web results.

The differentiator vs. "search the web" is a curated understanding of **build
synergies** plus a **human-in-the-loop feedback loop** that records whether
suggestions were good or bad, so the assistant improves over time.

## 2. Scope

### In scope (MVP)
- Detect and remember the Grim Dawn save directory per OS; allow rescan/reselect.
- Parse a save file (`.gdc`) into a character model: level, masteries, allocated
  skills, devotion, equipped/inventory items, resistances, attributes.
- A JSON-backed knowledge base of masteries, skills, devotion constellations, and
  items, refreshable between patches.
- A suggestion engine that reports synergies and gaps and proposes skill/item
  changes, with farming locations for suggested items.
- A feedback store: user rates a suggestion good/bad with notes; ratings feed
  back into future ranking.

### Out of scope (this iteration)
- **Save file editing / writing.** Read-only only.
- Skill-tree / item **visuals** — deferred until the logic works (text/list UI first).
- Automated full web crawling of build guides (start with manual import + a small
  set of verified sources).

## 3. Key design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.11+ | Per spec. (Dev machine currently on 3.14 — pin a supported runtime for GUI deps.) |
| GUI toolkit | **PySide6 (Qt)** | Mature, genuinely cross-platform desktop widgets, LGPL. |
| Data storage | **JSON files** | Per spec; human-inspectable, diff-friendly, easy to update between patches. |
| Packaging | `pyproject.toml` (src layout) | Standard, editable installs for fast iteration. |
| Save parsing | Custom `.gdc` reader | Format is documented by the community (see §5). |

## 4. Save file location (per-OS discovery)

Grim Dawn stores saves under `.../My Games/Grim Dawn/save/`. Cloud saves live in
Steam's `userdata` tree. The locator probes known roots for the current OS, in
order, and stops at the first that contains a `save/` folder with `_<name>` dirs.

- **Windows (Steam/local):**
  `%USERPROFILE%\Documents\My Games\Grim Dawn\save\`
- **Windows (Steam Cloud):**
  `<Steam>\userdata\<accountid>\219990\remote\save\`
- **Linux (Steam Proton):**
  `~/.steam/steam/steamapps/compatdata/219990/pfx/drive_c/users/steamuser/Documents/My Games/Grim Dawn/save/`
  (also `~/.local/share/Steam/...` variant)
- **Linux (Steam Cloud):**
  `~/.steam/steam/userdata/<accountid>/219990/remote/save/`
- **macOS:** `~/Library/Application Support/...` (best-effort; GD macOS support is limited)

`219990` is Grim Dawn's Steam AppID. Each character is a folder `_<CharName>`
containing `player.gdc` (and `levels.gdc`, quest files, etc.).

The discovered path is persisted to app config so it is not re-scanned each run.
The UI exposes **Rescan** and **Choose folder…** for installs that move.

## 5. Save file format (`.gdc`)

`player.gdc` is a custom binary format using a rolling XOR "encryption" keyed off
an initial seed, with length-prefixed strings and versioned blocks. It is well
documented by open-source tools; we implement a read-only reader modelled on
them (no code is copied; formats/offsets are the reference):

- `gd-edit` (Clojure) — thorough field maps.
- GDCommunityTools / IAGDBackup — item stash + character parsing.

Parser strategy: a small binary reader (seed-XOR + typed reads) → block decoders
→ a `Character` dataclass. Unknown blocks are skipped by length so parsing is
resilient to new patches. Parser is isolated behind `savefile/parser.py` so the
brittle part is swappable.

## 6. Knowledge base — data sourcing

**grimtools.com has no public API.** grimtools (by "Dammitt", unaffiliated with
Crate) is itself a **datamine** of the game's local data files. So our primary
source is the *same* one: extract the player's own installed game files. This is
legitimate (the user owns the game), always matches their exact patch + DLC/mods,
and needs no scraping. grimtools stays a **reference/cross-check** (notably for
its correctly-averaged item values and for sanity-checking our parse).

### 6.1 Where the game data lives
Grim Dawn ships content as archive files in the install directory:

- **`.arz`** — the packed **database** (all records: skills, items, affixes, sets…).
- **`.arc`** — **archives** of assets, and crucially the localisation `text_en.arc`
  (maps `tag*` keys → display names/descriptions).

Extraction produces **`.dbr`** files — plain-text `key,value;` records. Each item,
skill, constellation, etc. is one `.dbr`; records reference each other by path.

### 6.2 Extraction toolchain — native reader (IMPLEMENTED)
**Decision (v0.1):** the app reads `.arz`/`.arc` **natively in pure Python**, with a
bundled pure-Python **LZ4 block** decompressor — **zero third-party / GD-specific
dependencies**, so it keeps working across patches and outlives any external tool.
This is now built and verified against a retail install:
- `knowledge/lz4_block.py` — LZ4 block decompression (no `lz4` package needed).
- `knowledge/arz.py` — `.arz` database → decoded records (validated: all 34,114
  records of retail `database.arz` decode cleanly).
- `knowledge/arc.py` — `.arc` archive → files + `load_text_tags()` (validated:
  11,884 tags from `Text_EN.arc`; `.arz` name-tags resolve to real item names).
- `knowledge/extractor.py` — locates the `.arz` databases (base + `gdx1/2/3`) and
  `Text_<LANG>.arc` inside an install dir.

Third-party tools are **not required**. For reference only: official
`ArchiveTool.exe`/`AssetManager.exe` (ships with the game, Windows) and atom0s's
`grimarz`/`grimarc` do the same extraction externally.

### 6.3 Pipeline: game files → JSON KB
```
install dir  →  extract .arz/.arc  →  raw .dbr + text_en tags  →  normalise  →  data/kb/*.json
```
`data/updater.py` orchestrates this. It is triggered from the CLI
(`gd-assistant-build-kb`) **and from an "Update game data" button in the UI**
(`ui/main_window.py`, runs on a worker thread) so users can refresh content after a
patch or new DLC without external tooling. **Design rules:**
1. Keep the raw `.dbr` dump separate from the normalised KB, so re-normalising after
   a schema change doesn't require re-extracting.
2. Detect **`game_version`** from the install (and record it in each KB `meta`
   header) so the assistant can warn when KB and save disagree.
3. Idempotent + patch-resilient: unknown `.dbr` fields are ignored, not fatal.
4. grimtools cross-check is optional and rate-limited; never required to build the KB.

### 6.4 KB files (`data/kb/`, each with a `meta` header: `game_version`, `source`, `built_at`)
- `masteries.json` — the 6 masteries and their skill trees.
- `skills.json` — skills, modifiers, transmuters, scaling.
- `devotion.json` — constellations, affinities, bound-skill procs.
- `items.json` — items: slot, rarity, level req, set, granted/+skills, and non-zero
  `offensive*` damage bonuses (per damage type) so the KB can rank build-enabling gear
  (e.g. `items_enabling("bleed")`).
- `farming.json` — item → source(s) (boss, faction, dungeon, MI mob + location).
  *(Drop-source data is weaker in `.dbr` than item stats — may need grimtools/community
  data to fill farming locations; flagged as an open question in §11.)*

## 7. Suggestion engine

Input: parsed `Character` + KB + feedback history.
Output: ranked, explained suggestions across three lanes:

- **Skills** — under-invested synergies, missing transmuters, devotion proc
  targets, resist/defensive gaps.
- **Items** — upgrades that push set completion, needed resistances, +skills to
  the character's core skills; each with **where to farm**.
- **Devotion** — constellation paths matching the damage type / playstyle.

Each suggestion is a structured object: `{what, why, expected_effect, sources,
confidence}`. `why` is first-class — this is the "understand synergies" goal.
Ranking blends rule-based synergy scoring with the feedback store (§8).

The engine's reasoning is grounded in the game's actual **damage & defense model**
(documented in [`docs/DAMAGE_MODEL.md`](docs/DAMAGE_MODEL.md)) — additive % stacking,
damage conversion order, %WD vs flat, DoT stacking, OA/crit, the three resistance-
reduction categories, and armor-vs-Physical-Resistance. These rules are what turn raw
KB numbers into correct interaction advice (e.g. RR category coverage, conversion
enabling a build's %bonuses, over-cap resist offsetting enemy RR).

Parsed web builds (manually imported to start) are stored as "reference builds"
and used to explain nuance/context, not copied blindly.

## 8. Human-in-the-loop feedback

Every surfaced suggestion can be rated **good / bad** with an optional note.
Stored in `data/feedback/feedback.json` keyed by a stable suggestion signature
(e.g. skill id / item id / rule id + character archetype). The engine
down-weights repeatedly-rejected suggestions and surfaces user notes next to
similar future suggestions. This is the primary mechanism for the app to "learn
what I actually want."

## 9. Proposed module structure

```
src/gd_assistant/
  app.py                # entry point, wires config + UI
  config/settings.py    # persistent config (save dir, KB version, prefs)
  savefile/
    locator.py          # per-OS save dir discovery + persistence
    parser.py           # .gdc binary reader -> Character
  models/
    character.py        # Character, mastery allocation, equipped items
    skill.py            # Skill, transmuter, modifier
    item.py             # Item, affix, set, granted skill
  data/
    repository.py       # load/query JSON knowledge base
    normalise.py        # raw .arz records -> KB dicts (pure, testable)
    updater.py          # build KB from local install (+ CLI: gd-assistant-build-kb)
  knowledge/
    arz.py              # native .arz database reader
    arc.py              # native .arc archive reader + text-tag loader
    lz4_block.py        # pure-Python LZ4 block decompressor
    extractor.py        # locate .arz / Text_*.arc inside an install
    sources.py          # verified web sources registry + fetch/cache
    builds.py           # import & normalise reference builds
  suggestions/
    engine.py           # synergy analysis + ranking
    feedback.py         # feedback store (good/bad + notes)
  ui/
    main_window.py      # PySide6 tabbed shell + "Update game data" button
    item_search.py      # Item Search tab: search box, sortable table, detail panel
data/                   # JSON KB, feedback, cached fetches (gitignored where large)
tests/
```

## 10. MVP milestones

1. **Skeleton** ✅: structure, config, README, module stubs.
2. **Native data readers** ✅: pure-Python `.arz`/`.arc` + LZ4 (§6.2), verified on retail.
3. **Knowledge base** ✅: `data.updater.build_kb` reads base+expansion `.arz`, merges
   base+expansion `Text_<LANG>.arc`, and writes `kb/{masteries,skills,devotion,items}.json`
   (`gd-assistant-build-kb`, and an **"Update game data" button** in the UI, SPEC §6.3).
   On a full FoA install: 10 masteries, 317 skills, 110 constellations, 6,913 items,
   plus `skill_damage.json` (damage-type tags) and `skill_names.json` (name index for
   player + item-granted + pet skills), both resolved through skills' buff/pet chains.
   Items capture non-zero `offensive*` damage bonuses and skills are tagged by the
   damage they deal (`data/damage.py`, array-aware), so the KB answers build-enabling
   queries **for any damage type**: `KnowledgeBase.items_enabling("fire" | "cold" |
   "lightning" | "aether" | "vitality" | "chaos" | "bleed" | …)`. Each result records
   *why* it matched — own `stats`, a `grants_skill`, or `boosts_skills` (+skills to a
   skill that deals the type) — and element queries include their DoT + Elemental
   family (fire → Fire/Burn/Elemental). All type↔field mappings were confirmed against
   retail records (e.g. Vitality = `offensiveLife*`), not assumed.
   `data.repository.KnowledgeBase` is the query side.
4. **UI — Item Search tab** ✅: search items by name *or* property (rarity, slot, set,
   +skill/granted-skill names, damage types, friendly stat labels), sortable table
   (incl. numeric Req/Item Level), and a right-hand detail panel showing the item's
   full property list. Items now carry a comprehensive `stats` block + `item_level`;
   `data/labels.py` gives friendly stat labels. **Stat rows are colour-coded by damage
   type** (`data/colors.py`) using the grouping from the installed Wanez "Rainbow
   Filter" mod (`settings/text_en/`) — Fire orange, Cold/Frostburn blue, Bleeding/Pierce
   red, etc.; resistances share their type's colour. **Item name + rarity and the
   search-table rows are tinted by rarity** (GD's White/Yellow/Green/Blue/Purple tiers).
   **`+skill` rows show the skill's class inline** (e.g. "Maelstrom (Shaman)"), and
   the class is **searchable** — `cold occultist` finds items with cold stats *and*
   +Occultist skills (multi-term AND over name + properties + damage types + skill
   classes). **Pinning:** a Pin/Unpin button builds a persistent "farm list"
   (`Settings.pinned_items`, saved to config); pinned items always show at the top
   regardless of search/sort, marked with a drawn pin icon (name text/sorting
   unaffected). Verified headless on a dark palette (legibility, pinning) and by
   screenshot. PySide6 confirmed on Python 3.14.
5. **Locate + persist** save directory; list characters.
6. **Parse** `player.gdc` → basic `Character` (level, masteries, skills, gear).
7. **Rule-based suggestions** (resist gaps, +skills, obvious synergies) in the UI.
8. **Feedback loop** wired to ranking.
9. Iterate; only then consider **visuals** and broader web-build ingestion.

## 11. Open questions

- **Extractor (RESOLVED):** native pure-Python `.arz`/`.arc` reader with a bundled
  LZ4 — no third-party tools, cross-platform. Built and verified (§6.2).
- **Farming locations (DECIDED):** loot data in the `.arz` is indirect (loot tables
  → item pools) and lacks human-readable "farm boss X in area Y". So: derive what we
  can from `.arz` loot tables where practical, and otherwise **pull farming
  locations from grimtools / community data**, cached into a `farming.json`. Local
  source is preferred when viable; grimtools/community is the fallback.
  - **"Obtained from" — WHO (DONE, native):** `knowledge.loot` inverts the drop graph
    (`Monster.loot*Item*` → `LootMasterTable` → nested tables/items) into
    `item_sources.json` (item → ranked droppers with name + classification), surfaced
    as a **"Dropped by"** panel row and searchable by monster name. Monster names
    resolve from the `description` tag via `Text_<LANG>.arc`. World-drop legendaries
    sit only in generic pools (e.g. Asterllonos) so they have no specific dropper — an
    honest "random world drop". **WHERE (region/area)** is *not* in the item DB (it
    lives in the map files), so map locations remain the grimtools/community fallback.
- **+skill / granted-skill resolution (DONE):** names/damage that live on a linked
  `buffSkillName`/`petSkillName` record now resolve via a **transitive** chain walk —
  one hop (*Siphon Souls* on `soulsiphon1_buff`) and two hops (pet modifier → pet
  skill → its buff, e.g. *Blood Pact*). A `skill_names.json` index (all player +
  item-granted + pet skills) backs `KnowledgeBase.skill_name`, so **0** playerclass
  `+skill` refs and **99%** of item-granted skills now name-resolve. Buff/pet children
  are collapsed into their base to avoid duplicates.
- **Devotion star effects & modifier→parent skill graph:** the KB captures
  constellations (name, affinities, star records) and skill types, but not yet the
  per-star stat effects or which active a modifier augments. Add when the suggestion
  engine needs them.
- Which save variant is primary — local vs. Steam Cloud `remote/`? (Locator must
  handle both; may need to pick the newest by mtime.)
- Softcore/Hardcore and stash/shared-stash parsing — in scope for suggestions?

## 12. References (data sourcing)

- grimtools item DB: https://www.grimtools.com/db/  (datamine by Dammitt; no public API)
- atom0s — `.arz` extractor: https://github.com/atom0s/grimarz
- atom0s — `.arc` extractor: https://github.com/atom0s/grimarc
- atom0s — file format write-up: https://atom0s.wordpress.com/2014/10/04/grim-dawn-file-archive-database-extractors/
- Official `ArchiveTool.exe`/`AssetManager.exe` ships in the Grim Dawn install (modding tools).
- `.gdc` save format reference: `gd-edit`, GDCommunityTools / IAGDBackup.

## Appendix A. Verified binary formats

Confirmed byte-for-byte against a retail Linux/Steam install (magic/version and the
offset arithmetic all check out). Authoritative source is the code in
`knowledge/arz.py`, `knowledge/arc.py`, `knowledge/lz4_block.py`.

### A.1 `.arz` (database) — little-endian
```
Header (24 bytes): u16 magic=2, u16 version=3,
    u32 record_table_start, u32 record_table_size, u32 record_table_entries,
    u32 string_table_start,  u32 string_table_size
    -> record_table_start + record_table_size == string_table_start (verified).
Record-data region: [24 .. record_table_start); record offsets are relative to 24.
String table @ string_table_start: u32 count, then count × (u32 len, bytes[len]).
Record table @ record_table_start: record_table_entries × (variable length):
    u32 name_id(->string table: .dbr path), u32 type_len, bytes[type_len] (class),
    u32 offset, u32 compressed_len, u32 decompressed_len, u64 filetime.
Record payload (LZ4 block -> decompressed_len): stream of fields:
    u16 value_type, u16 value_count, u32 key_id(->string table: field name),
    value_count × u32 raw; decode: 0=int32 1=float32(bits) 2=string(->table) 3=bool.
```

### A.2 `.arc` (archive) — little-endian
```
Header (28 bytes): u32 magic=b"ARC\0", u32 version=3, u32 file_count, u32 part_count,
    u32 parts_table_size(=part_count*12), u32 string_table_size, u32 record_table_offset.
File data: [28 .. record_table_offset).
Footer, in order:
    Parts table @ record_table_offset: part_count × (u32 part_offset, u32 comp, u32 decomp).
    String table (null-terminated filenames), size string_table_size.
    TOC (at end): file_count × 44 bytes:
        u32 entry_type(=3), u32 file_offset, u32 comp, u32 decomp, u32 hash,
        u64 filetime, u32 part_count, u32 first_part_index, u32 name_len, u32 name_offset.
A file = concat of parts[first_part_index : +part_count]; a part is stored when
comp==decomp, else an LZ4 block. `Text_<LANG>.arc` holds `key=value` `.txt` tag files.
```

### A.3 LZ4 block
Raw LZ4 block format (no frame header). Sequences of `token`, literals, 2-byte LE
match offset, match copy; high/low token nibbles give literal / (match-4) lengths,
nibble 15 → extension bytes. Final sequence is literals-only. Overlapping matches
(offset < length) copy byte-by-byte. Decompressed size known from the container.
