# Grim Dawn Build Assistant

A cross-platform desktop app that reads your local Grim Dawn save files and helps
you understand and advance your characters — explaining **skill synergies**,
**itemisation**, and **where to farm** suggested gear, with a human-in-the-loop
feedback loop so its advice improves over time.

> **Read-only.** This tool does **not** edit or write save files in this
> iteration. It only reads saves to analyse and suggest.

See [`SPEC.md`](SPEC.md) for the full design and [`initialspec.md`](initialspec.md)
for the original brief.

## Status

Early scaffolding — the project structure and module stubs are in place; feature
work follows the milestones in `SPEC.md §10`. Not yet runnable as a full app.

## Features (planned, MVP-first)

- 🔍 **Auto-locate** the Grim Dawn save folder per OS and remember it (rescan/reselect supported).
- 📖 **Parse** `player.gdc` into a character model (masteries, skills, devotion, gear, resistances).
- 🧠 **Knowledge base** of skills/items/devotion as updatable JSON (source: grimtools.com).
- 💡 **Suggestions** for skills, items, and devotion — each with the *why* and farming locations.
- 👍 **Feedback loop** — rate suggestions good/bad; ratings shape future advice.
- 🖼️ Skill-tree / item **visuals** — deferred until the logic works.

## Tech stack

- **Python 3.11+**, **PySide6** (Qt) for the desktop UI.
- **JSON** for the knowledge base and feedback (no database, per design).
- `src/` layout, `pyproject.toml`.

## Run it (easiest)

- **Linux / macOS:** double-click **`run.sh`** (choose *Run* if prompted), or in a
  terminal: `./run.sh`
- **Windows:** double-click **`run.bat`**

The launcher creates a local virtual environment and installs dependencies on first
run, then starts the app. On Linux you can also install a menu entry by copying
`GrimDawnAssistant.desktop` into `~/.local/share/applications/` (edit the paths inside
if you move the project).

> GNOME/Files note: double-clicking a `.sh` may open it in an editor. Either mark it
> *Allow Launching* / enable “run executable text files”, or just use `./run.sh` from a
> terminal or the `.desktop` entry.

## Getting started (development)

```bash
# create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# install in editable mode with dev extras
pip install -e ".[dev]"

# build the knowledge base from your Grim Dawn install (reads .arz/.arc natively)
gd-assistant-build-kb "/path/to/Grim Dawn"
#   e.g. Linux/Steam: ~/.steam/steam/steamapps/common/Grim Dawn
# writes data/kb/{masteries,skills,devotion,items}.json and remembers the install path

# run the (stub) app
python -m gd_assistant

# run tests
pytest
```

### Knowledge base

`gd-assistant-build-kb <install>` datamines your installed game files into JSON:

| File | Contents (full FoA install) |
|------|------|
| `masteries.json` | 10 masteries (base 6 + Inquisitor/Necromancer/Oathkeeper/Berserker) |
| `skills.json` | ~294 player skills (active/passive/modifier/transmuter, by mastery) |
| `devotion.json` | ~110 constellations (affinities given/required, star records) |
| `items.json` | ~6,900 named items (slot, rarity, level req, set, granted/+skills) |

It merges base + expansion databases and localisation, so names always match your
exact patch + DLC. Query it via `gd_assistant.data.repository.KnowledgeBase`. The
generated JSON is git-ignored (regenerate it locally; it's version-specific).

> **Note:** PySide6 wheels may lag the newest Python releases. If install fails on
> a very new interpreter, use a supported Python (3.11–3.13) for the GUI parts.

## Project layout

```
grimdawn_editor/
├── SPEC.md                 # full design spec
├── initialspec.md          # original brief
├── pyproject.toml
├── src/gd_assistant/       # application package (see SPEC.md §9)
├── data/                   # JSON knowledge base + feedback (mostly gitignored)
└── tests/
```

## Data & sources

- Skill/item data is **datamined from your own installed game files** — grimtools has
  no public API and is itself a datamine. The game ships content as `.arz`/`.arc`
  archives; we read them with our **own native, dependency-free reader** (including a
  pure-Python LZ4 decompressor) and normalise into JSON. This always matches your
  exact patch + DLC and needs **no third-party tools**. See `SPEC.md §6` / Appendix A.
  - Readers: `gd_assistant/knowledge/{arz,arc,lz4_block}.py` — verified against a
    retail install (all 34,114 DB records + 11,884 localisation tags decode correctly).
  - **https://www.grimtools.com/db/** is used only as a cross-check/reference, and for
    farming-location data that isn't cleanly available in the local files.
- Save files are read from the OS-specific Grim Dawn `save/` directory; see `SPEC.md §4`.

## License

TBD.
