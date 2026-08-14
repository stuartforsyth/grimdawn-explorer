# Grim Dawn Build Assistant — Design Specification

> Status: **v0.2 draft** — expands `initialspec.md` into an actionable design.
> Analysis is read-only. Save **editing is in scope from milestone 10**, under a strict
> **clone-only** rule: the user's existing saves are never a write target (§5.3).

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

- **Character editing via clone** (milestone 10): edits accumulate in an in-memory
  overlay and are committed only by writing a **new derived character** into the save
  folder. See §5.3 — this supersedes the earlier "read-only only" position.

### Out of scope (this iteration)
- **In-place save editing.** Originals are opened read-only and are never written to,
  overwritten, renamed, or deleted. Every write produces a new character (§5.3).
- **Item fabrication.** Editing covers what a character legitimately owns and has
  allocated; inventing gear that never dropped is out of scope.
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
| Save parsing | Custom `.gdc` reader | Format verified against retail saves (see §5). |
| Save writing | **Clone-only**, whole-file re-encrypt | Originals are never a write target. Re-encrypting the full decrypted stream preserves blocks we don't parse, so unknown data can't be lost (§5.3). |

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
containing `player.gdc` (and quest/map files, §5.2).

**Character folders are nested one level deeper than originally assumed.** On the dev
machine they live under `save/main/`, not directly under `save/` — main-campaign
characters in `main/`, custom-game characters in `user/`. The locator must probe
`save/`, `save/main/` and `save/user/`; checking only `save/` finds nothing.

The discovered path is persisted to app config so it is not re-scanned each run.
The UI exposes **Rescan** and **Choose folder…** for installs that move.

## 5. Save file format (`.gdc`)

`player.gdc` is a custom binary format using a rolling XOR "encryption" keyed off an
initial seed, with length-prefixed strings and versioned blocks. Community tools
(`gd-edit`, GDCommunityTools / IAGDBackup) are the reference for field maps; no code
is copied. Parsing is isolated behind `savefile/parser.py` so the brittle part is
swappable.

### 5.1 Obfuscation (VERIFIED on retail saves)

```
seed  = u32_at(0) ^ 0x55555555          # key state starts AT the seed
table = []                              # 256 entries
k = seed
for _ in range(256):
    k = rotate_right_1(k)               # (k >> 1) | (k << 31), 32-bit
    k = (k * 39916801) & 0xFFFFFFFF     # 39916801 == 11! + 1
    table.append(k)
```

Reads XOR the raw little-endian value with the current key, then **advance the key
using the raw (still-encrypted) bytes**: `for b in raw_bytes: key ^= table[b]`.

Verified against all 24 characters in the dev save folder: `u32` at offset 4 decodes
to magic `GDCX` (`0x58434447`), followed by `version = 2`.

Header layout, confirmed: **wide string** name (u32 char count, then 2 bytes/char
UTF-16LE) → `u8` sex → **ASCII string** class tag → `u32` level → `u8` hardcore.
The class tag encodes the mastery pair directly — `tagSkillClassName0609` is
Shaman+Oathkeeper, `tagSkillClassName05` is a single-mastery Arcanist — so masteries
are known from the header before the skills block is reached.

**The character name is stored inside the file**, and on every save checked it matches
the containing `_<Name>` folder. Renaming therefore has to update both.

### 5.2 A character is a folder, not a file

```
_Archon/player.gdc
_Archon/levels_world001.map/<Normal|Elite|Ultimate>/{map.dat, map.fow, quests.gdd, conversations.gdd}
```

Copying only `player.gdc` yields a character with no quest progress and an unexplored
map. Any clone copies the whole tree.

### 5.3 Writing — clone-only (milestone 10)

The keystream is **self-feeding**: the key mutates from every byte consumed, so
changing one byte invalidates the keystream for the remainder of the file. Ciphertext
cannot be spliced.

Two properties, both **verified**, set the cost of writing:

1. **Key evolution is granularity-independent — but only over key-advancing reads.**
   The key advances by `key ^= table[b]` over each raw byte, so its state depends on
   *which* bytes were fed to it, never on how they were grouped. A block can therefore
   be skipped wholesale **provided it contains no `next_int`** — block lengths and
   terminators are consumed *without* feeding the key, so bulk-skipping a region that
   contains one over-feeds the key and desyncs everything downstream. In practice that
   means blocks containing **nested** blocks (inventory, stash) must be parsed, not
   skipped. This is self-checking rather than a guess: a desync makes the block's
   terminator non-zero immediately, which is what `crypt.try_skip_block` reports.
2. **Decryption is wordwise, not bytewise.** A `u32` read XORs all four bytes against
   the key *before* advancing it; a `u8` read uses only the low byte. These are not
   equivalent — decrypting bytewise yields `G` followed by garbage. So recovering the
   plaintext requires knowing each read's **width**.

Consequence: **writing requires read-width coverage from the edit point to EOF.** An
edit changes the key state for everything downstream, and re-encrypting downstream
needs its plaintext, which needs its widths. Since the name is the *first* field
(§5.1), a rename touches essentially the whole file.

**Coverage does not mean comprehension**, though, and that is what makes this
tractable. Reading a region as a run of `u8`s is a *valid* width assignment: it
advances the key exactly as the game's own widths do (property 1), and re-emitting
those same plaintext bytes reproduces the original ciphertext exactly. So an
unmodelled block can be captured as an opaque byte run and still round-trip
perfectly — **provided it contains no nested block**, whose length fields would be
over-fed by a bulk run.

Measured across the dev saves: only blocks **3 (inventory)** and **4 (stash)** nest.
So `savefile/document.py` models the header (the fields actually edited), bio,
inventory, stash and skills, and preserves every other block verbatim without
pretending to understand it. The round-trip test below is what **proves** the coverage
is complete rather than merely assumed.

Safety rules, enforced in code rather than by convention:

1. Source saves are opened through a **read-only** handle. No write mode, ever.
2. The clone is assembled in a temp dir, then **re-parsed and verified** before it is
   moved into the save folder.
3. It lands as a **new** `_<Name>` folder. Originals are never a write target, so a
   crash mid-write cannot reach them.
4. Writes refuse to run while **Grim Dawn** is running — it holds its saves and
   rewrites them on exit, which would silently discard a clone. *Steam* is
   deliberately **not** a blocker: it runs essentially all the time for a Steam user,
   so refusing on it would make the feature unusable. Steam Cloud reconciles around
   game start/stop, and a clone is additive (a new folder, not a change to one Steam
   is already tracking), so the game is the hazard that actually matters. Detection is
   native per-OS (`/proc`, `ps`, `tasklist`) rather than a third-party process library.
5. The source file's hash is compared before and after the clone, so "the original was
   not touched" is asserted, not assumed.
6. Optional one-time zip snapshot of the whole save tree.

**Blocking test (PASSING):** parse → re-serialize must produce a **byte-identical**
file, for every character in the dev save folder. Because of the width requirement
above, passing this test is equivalent to proving complete structural coverage.
Currently **24/24**, across both format variants, plus synthetic coverage in
`tests/test_savefile_document.py`.

Renaming is verified end-to-end: shortening and lengthening the name both rebuild
correctly (every later offset shifts and the whole tail re-encrypts), the result
re-parses to the new name with all other data intact, and renaming back reproduces the
original bytes exactly.

Cloning still ships in two stages, but only for risk-staging — both are now unblocked:

- **10a — copy-only clone.** Duplicate the character folder under a new folder name,
  `player.gdc` byte-for-byte untouched. Delivers *"keep the name the same, output a
  different file into the save folder"* with no generated bytes at all. (Open question:
  whether Grim Dawn keys the displayed name off the folder or the in-file string —
  testable by trying it.)
- **10b — real edits.** Rename and the other edit surfaces, via
  `document.parse_document` → mutate → `document.write_document`.

Clones are written into `save/main/` alongside originals so Grim Dawn lists them; this
is additive and does not endanger existing saves. Steam Cloud will sync them.

**To verify during implementation** (not assumed): whether the format carries a
file-level checksum, and whether Grim Dawn tolerates a clone sharing its source's
character UID.

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
- `class_names.json` — `tagSkillClassNameNNNN` → combined class name ("Druid",
  "Archon"). These live in the text archives, not the record database, and a save's
  header stores the tag verbatim (§5.1) — so this is the only way to name a
  character's *combined* class, which is not derivable from its two mastery names.
  Consumed by `KnowledgeBase.class_description`; absent on a KB built before it
  existed, in which case callers fall back to listing the masteries.
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

### 7.1 Build profile (`suggestions/profile.py`)

The shared derivation every build-aware feature reads from. `Character` → `BuildProfile`:

- **Masteries** — single or dual, from the header class tag (§5.1); no skill parsing needed.
- **Damage weights** — each allocated skill's types from `skill_damage.json`, weighted by
  the **points actually invested**, so the profile reflects what the character really does
  rather than every type its masteries could theoretically deal.
- **Resist gaps** — current resistances vs. the 80% soft cap, worst-first.
- **Slot occupancy** — which equipment slots are filled, and with what item level.

### 7.2 Gear advisor (`suggestions/gear.py`)

1. **Candidate window** — `level_requirement <= character.level + 5` (story §13.5),
   floored so long-outgrown items don't resurface.
2. **Scoring**, per slot, every contribution recorded as a reason string (same
   "why it matched" pattern `items_enabling` already uses — no opaque totals):
   - `plus_skills` naming a skill the character has **actually allocated** — heaviest
     signal. Works because `items.json` keys `plus_skills` by the same
     `records/skills/...dbr` ids the save file references.
   - `plus_mastery` / `plus_all_skills`, then damage-type match against the profile
     weights, then resist-gap fill, then rarity / `item_level` as tiebreak.
3. **Farmability** — join `item_sources.json`: rank droppers Boss > Hero > world drop,
   and label items that exist only in generic pools honestly as random world drops
   rather than inventing a target. Map location stays blank until `farming.json`
   exists (§11 grimtools fallback).

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
    locator.py          # per-OS save dir discovery + persistence (probes save/{,main,user})
    crypt.py            # seed-XOR reader + writer, incl. the next_u32 quirk (§5.1)
    document.py         # the block grammar, written once, read+write from one schema
    parser.py           # Document -> Character (semantic layer only)
    clone.py            # copy character folder, rename, verify, atomic move (§5.3)
    cli.py              # gd-assistant-clone: list/clone, dry-run by default
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
    loot.py             # invert Monster->loot tables into item "obtained from"
    sources.py          # verified web sources registry + fetch/cache
    builds.py           # import & normalise reference builds
  suggestions/
    engine.py           # synergy analysis + ranking
    profile.py          # Character -> BuildProfile (damage weights, resist gaps) §7.1
    gear.py             # level-windowed upgrade scoring + farm plan §7.2
    feedback.py         # feedback store (good/bad + notes)
  ui/
    main_window.py      # PySide6 tabbed shell + "Update game data" button
    item_search.py      # Item Search tab: search box, sortable table, detail panel
    skill_search.py     # Skills & Devotions Search tab (damage/role/affinity search)
    character.py        # Character tab: picker, read-only view, edit overlay, Save As
    gear_plan.py        # Gear Plan tab: per-slot ranked upgrades + farm targets
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
5. **UI — Skills & Devotions Search tab** ✅ (User story §13.3): one search box over
   both **player skills** and **devotion constellations**, sharing a results table
   (a *Kind* column separates them) + detail panel. Devotions are now tagged in the KB
   with the **damage types** and capability **roles** (offensive/defensive/sustain/
   speed/attributes/retaliation) they grant — derived by walking each constellation's
   star buttons → granted skill stats (`data.normalise`), so a search for `cold damage`,
   `defensive`, `retaliation`, a mastery, or an affinity (`eldritch`) finds the right
   skills/devotions. Same term semantics as Item Search (AND + `"quoted"` phrases);
   damage rows colour-coded by type. **Multi-select Class + Affinity filters** (OR
   within each) let you span masteries/affinities — e.g. tick Nightblade + Berserker,
   type "cold" → cold synergies across both classes — plus a Kind toggle (All/Skills/
   Devotions). `KnowledgeBase.search_skills/search_devotions` take `masteries=`/
   `affinities=` OR-sets; `mastery_names()`/`affinity_names()` supply the options.
6. **Locate + persist** save directory; list characters. Includes the `save/main/`
   nesting fix (§4) — the current locator finds zero characters on a real install.
7. **Parse** `player.gdc` → `Character` ✅: level, masteries (incl. bar points),
   allocated skills, devotion nodes, equipped gear, attributes and unspent points.
   `savefile/crypt.py` (obfuscation) + `savefile/parser.py` (blocks). Blocks without
   nesting are skipped and the skip is validated by the terminator (§5.3 property 1).
   Verified: **all 24** dev characters parse, and their records resolve against the KB
   (skills name-resolve with the right mastery, gear resolves to real items).
8. **UI — Character tab** (§14.1): picker + read-only character view.
9. **Build profile + gear advisor** (§7.1/§7.2, §14.2): the Gear Plan tab, plus a
   **Fit** column and "Fits my build" filter retrofitted into Item Search, and
   "From my character" on Skills & Devotions.
10. **Clone + writer** (§5.3) — format and clone engine ✅. `savefile/document.py`
    round-trips all 24 dev saves byte-identically; `savefile/clone.py` copies the whole
    character folder, optionally rewrites the in-file name, verifies by re-parsing, and
    only then moves the result into place atomically as a new folder. Exposed for
    testing via `gd-assistant-clone` (dry-run by default; `--sandbox` writes outside
    the save folder; the real save folder additionally needs `--i-mean-it`), and in
    the UI via **Save As New Character…** on the Character tab ✅ (§14.1).
    Remaining: the optional zip snapshot, and the edit overlay.
11. **Rule-based suggestions** (resist gaps, +skills, obvious synergies) in the UI.
12. **Feedback loop** wired to ranking.
13. Iterate; only then consider **visuals** and broader web-build ingestion.

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
- **`.gdc` block structure (RESOLVED).** Implemented in `savefile/parser.py`; all 24
  dev saves parse. The mechanism that made it look intractable is `next_int`: block
  lengths and end-of-block terminators are **consumed but do not advance the key**, so
  a naive linear pass drifts by a constant XOR at every block boundary. See §5.3.
  Two save-format variants appear in the wild on the same install (saves last written
  by different patches), so versions are read, not assumed:
  - inventory block **v4** vs **v11** — the item struct gained **4 trailing ints**;
  - skills block **v6** vs **v8** — the skill entry gained **1 byte**;
  - stash **v11** appends ~20 bytes of per-tab trailer that is skipped, not modelled.
  A useful tool if this ever needs revisiting: because key evolution is
  granularity-independent, the u8-read plaintext at *every* offset can be computed
  without parsing (`plain[i] = raw[i] ^ (key[i] & 0xFF)`), which recovers all record
  paths in a save and anchors the structure.
- **Relics are missing from the KB (OPEN).** Every character's equipment slot 11 holds
  a `records/items/gearrelic/*.dbr`, and **none** resolve against `items.json` — the KB
  has no items under that directory at all. Relics carry a granted skill and
  substantial bonuses, so the gear advisor (§7.2) has a blind spot until
  `data.updater` covers them. Found while building the Character tab (§14.1); the gear
  view falls back to the record name meanwhile.
- Softcore/Hardcore and stash/shared-stash parsing — in scope for suggestions?

## 12. References (data sourcing)

- grimtools item DB: https://www.grimtools.com/db/  (datamine by Dammitt; no public API)
- atom0s — `.arz` extractor: https://github.com/atom0s/grimarz
- atom0s — `.arc` extractor: https://github.com/atom0s/grimarc
- atom0s — file format write-up: https://atom0s.wordpress.com/2014/10/04/grim-dawn-file-archive-database-extractors/
- Official `ArchiveTool.exe`/`AssetManager.exe` ships in the Grim Dawn install (modding tools).
- `.gdc` save format reference: `gd-edit`, GDCommunityTools / IAGDBackup.

## 13. User stories — Build Explorer (future iterations)

Captured for planning; these extend the MVP (§10) and the suggestion engine (§7).
Each story notes what already exists and what it still needs. The umbrella theme is a
**Build Explorer**: load a character, understand it, and get grounded, explained
advice on how to make it stronger.

1. **Find gear for my class & build, and know where it comes from.**
   *"Search and find items that will work with my class and build, and know who dropped
   them and where."*
   - Have: Item Search (§10.4) with property/damage-type/+skill-class search;
     `item_sources.json` gives **who drops it** (bosses/heroes highlighted) and honest
     world-drop labelling (§11 "Obtained from").
   - Needs: **build-aware filtering** — once a `Character` is loaded, rank/filter items
     by class fit (masteries, core skills, damage type, resist gaps); **where** (region)
     still comes from the grimtools/community fallback (§11), cached to `farming.json`.

2. **Load my character and explore skills & items to strengthen it.**
   *"Load my current character and explore skills and items to make my build stronger."*
   - Needs: the `.gdc` parser → `Character` (milestone 6) and a Build Explorer view that
     shows current masteries/skills/devotion/gear with editable "what-if" exploration
     (no save writing — §2), each change scored by the engine (§7).

3. **Search skills & devotions by the attribute I want to boost.**
   *"Search skills and devotions for attributes I'd like to make stronger — e.g. cold
   damage, or defensive capabilities."*
   - Have: skills are tagged by damage type (`skill_damage.json`).
   - Needs: a **skill/devotion search tab** mirroring Item Search, plus damage-type &
     role tagging for **devotions** (parse constellation stat grants, incl. defensive
     roles — armor, resists, DA/OA, sustain — not just damage).

4. **Chat with an assistant that understands my build.**
   *"Interact with a chat window (Claude) that understands the project / skills /
   devotions / classes and recommends how to improve my build or specific elements."*
   - Needs: a **conversational assistant grounded in the local KB** — the loaded
     `Character`, KB records, and the damage model (`docs/DAMAGE_MODEL.md`) supplied as
     structured context so answers are derived from data, not invented (see the
     project's "derive facts from data" principle). Built on the Claude API (Anthropic;
     see the `claude-api` reference) with the engine's structured suggestions (§7) as
     tools/context. Feedback (§8) captures whether advice helped.

5. **Suggest strong upgrades just ahead of my level, and how to farm them.**
   *"Understand powerful items up to 5 levels ahead of my current load and suggest how
   to farm them."*
   - Needs: extend the items lane (§7) with a **level window** (current level → +5 on
     `levelRequirement`) and a farm plan per suggestion — drives off `item_sources`
     (droppers) + `farming.json` (locations), preferring reliable boss/hero targets.

6. **Understand devotions and plan a path to build them.**
   *"Understand devotions and how to build them: a path to specific constellations from
   my current build, and a view of where points could be better spent."*
   - Have: devotion KB carries `affinity_required` / `affinity_given` per constellation.
   - Needs: a **devotion path solver** — given current allocation and a target
     constellation, compute a valid affinity-satisfying order (which cheap constellations
     to take first to unlock affinities), and an **optimiser** that flags points spent
     for little synergy vs. higher-value alternatives for the build's damage/defense goals.

## 14. UI — new tabs (milestones 8–10)

Existing shell: `Overview | Item Search | Skills & Devotions`. Two tabs are added, and
the two search tabs gain build-awareness once a character is loaded.

### 14.1 Character tab ✅ (`ui/character.py`, `ui/save_as_dialog.py`)

Shipped: save-folder strip (Rescan / Choose folder…), character picker labelled
`Name  L57  Archon (Shaman + Oathkeeper)` — built from `parser.read_header`, which
reads only the first ~60 bytes of each save, so listing 24 characters costs a fraction
of a full parse — summary
(name, level, hardcore, masteries with bar points, attributes, unspent points), and
Skills / Devotions / Gear sub-tabs. Records resolve through the KB, so the view shows
*Primal Strike (Shaman)* and *Wildcaller's Cowl*, not record paths. Devotion stars are
grouped into their constellations with an `n/total stars` count
(`KnowledgeBase.constellation_for_star`). The game's built-in actions (kick, move-to)
are excluded from allocations — they cost no points. Equipment slot names are derived
from the saves rather than assumed (`parser.EQUIPMENT_SLOT_NAMES`).

**Save As New Character…** shows the destination folder before acting, states whether
any save bytes will be written, blocks on an invalid/colliding name or a running game,
and only closes once the clone has been created and verified. There is deliberately no
"Save" button — committing is always creating (§5.3).

Still to come below: the edit overlay and the inner Inventory view.

- **Header strip** — save-dir status + `Rescan` / `Choose folder…`; character dropdown
  showing name, level, mastery pair and hardcore flag (all available from the §5.1
  header, so the list populates without a full parse); `Reload`.
- **Left rail** — identity, attributes, resistances (colour-coded via `data/colors.py`),
  unspent points.
- **Inner sub-tabs** — Skills · Devotions · Gear · Inventory.
- **Edit overlay** — edits accumulate in memory against the loaded character. Nothing
  touches disk until committed, and the overlay doubles as the "what-if" explorer of
  story §13.2, scored live by the engine.
- **`Save As New Character…`** — the only write path (§5.3). Dialog takes the new name,
  offers *keep the same name in a different folder*, and states plainly which folder
  will be created. Derived characters are badged *"derived from &lt;source&gt;"*.

There is deliberately no "Save" button. Committing is always creating.

### 14.2 Gear Plan tab

Driven by the §7.1 build profile.

- **Left** — equipment slots, each with the currently equipped item and its fit score.
- **Centre** — ranked upgrade candidates for the selected slot, within the level window.
- **Right / detail** — the reason list (*why* this beats what's worn), the "Dropped by"
  panel from `item_sources.json`, and the existing **Pin** button so chosen upgrades
  flow into the farm list already backed by `Settings.pinned_items`.

### 14.3 Retrofits to existing tabs

Cheap reuse of two tabs that already work:

- **Item Search** — a **Fit** column and a *"Fits my build"* filter, active only while a
  character is loaded.
- **Skills & Devotions** — the backlogged **"From my character"** button, auto-ticking
  the character's actual masteries in the Class filter.

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

### A.4 `.gdc` (character save) — little-endian
Seed-XOR obfuscation, **not** compression. `seed = u32@0 ^ 0x55555555`; key state starts
at the seed; 256-entry table built by repeated `ror1` then `× 39916801 (mod 2^32)`. Each
read XORs with the current key, then advances it with the **raw** bytes just consumed
(`key ^= table[b]`), making the keystream self-feeding and unspliceable. Reads are
**wordwise**: a `u32` XORs all four bytes against the key before advancing it, so the
cipher is *not* a bytewise stream and decoding depends on read width (§5.3). Key
evolution, however, depends only on the bytes consumed — not their grouping.
`u32@4` is magic
`GDCX`; version 2 on current retail. Strings come in two flavours — **wide** (UTF-16LE,
u32 char count) for the character name, **ASCII** (u32 byte count) for record paths and
tags. Verified on 24 retail saves; full detail and the write model in §5.
