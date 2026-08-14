"""Clone a character into a **new** save folder. The originals are never written to.

This is the only path that produces save bytes, and it is deliberately shaped so that
the user's existing characters cannot be affected even by a bug here (SPEC §5.3):

* the source is only ever **read** — no call in this module opens it for writing;
* the clone is assembled in a temporary directory, then **verified by re-parsing**;
* only after verification is it moved into place, as a *new* folder, atomically;
* the source file's hash is checked before and after, so "we didn't touch it" is
  asserted rather than assumed.

A character is a folder, not a file (SPEC §5.2) — `player.gdc` plus the map/quest
tree — so the whole directory is copied. Copying only the `.gdc` would produce a
character with no quest progress and an unexplored map.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gd_assistant.savefile.document import parse_document, write_document
from gd_assistant.savefile.parser import character_from_document

SAVE_FILE = "player.gdc"

# Process names that indicate Grim Dawn itself is running. Steam is deliberately not
# included: it is running essentially all the time for a Steam user, so refusing on it
# would block the feature permanently. Steam Cloud only reconciles around game
# start/stop, and cloning is additive — it creates a new folder rather than modifying
# one Steam is tracking — so the game holding its saves is the hazard that matters.
GAME_PROCESS_NAMES = frozenset(
    {"grim dawn.exe", "grim dawn", "grimdawn", "grimdawn.exe", "grim dawn.x86_64"}
)

# Characters that must not appear in a save folder name.
_ILLEGAL_NAME_CHARS = set('/\\:*?"<>|\0')


class CloneError(RuntimeError):
    """A clone could not be completed. The save folder is unchanged."""


class GameRunningError(CloneError):
    """Grim Dawn is running; it would overwrite the clone when it exits."""


@dataclass(frozen=True)
class ClonePlan:
    """What a clone would do, resolved before anything touches the disk."""

    source: Path
    destination: Path
    new_name: str
    rename_in_file: bool

    @property
    def source_name(self) -> str:
        return self.source.name.lstrip("_")


@dataclass(frozen=True)
class CloneResult:
    """The outcome of a completed clone."""

    plan: ClonePlan
    files_copied: int


def find_running_game() -> str | None:
    """Return the name of a running Grim Dawn process, or None.

    Implemented natively per-OS rather than pulling in a process library, in keeping
    with the project's no-third-party-tools stance for core behaviour.
    """
    try:
        if sys.platform.startswith("win"):
            output = subprocess.run(
                ["tasklist", "/fo", "csv", "/nh"],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout
            names = [line.split(",")[0].strip('" ').lower() for line in output.splitlines()]
        elif sys.platform == "darwin":
            output = subprocess.run(
                ["ps", "-Ao", "comm="],
                capture_output=True, text=True, timeout=10, check=False,
            ).stdout
            names = [Path(line.strip()).name.lower() for line in output.splitlines()]
        else:
            names = []
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    names.append((entry / "comm").read_text().strip().lower())
                except OSError:
                    continue  # process exited, or not ours to read
    except (OSError, subprocess.SubprocessError):
        return None  # can't tell; the verify-before-move step still protects us

    for name in names:
        if name in GAME_PROCESS_NAMES:
            return name
    return None


def validate_character_name(name: str) -> str:
    """Return `name` if it is usable as a character/folder name, else raise."""
    cleaned = name.strip()
    if not cleaned:
        raise CloneError("character name cannot be empty")
    if illegal := sorted(_ILLEGAL_NAME_CHARS & set(cleaned)):
        raise CloneError(f"character name cannot contain: {' '.join(illegal)}")
    if any(ord(ch) < 32 for ch in cleaned):
        raise CloneError("character name cannot contain control characters")
    if cleaned in {".", ".."}:
        raise CloneError(f"{cleaned!r} is not a usable character name")
    return cleaned


def plan_clone(
    source: Path,
    *,
    new_name: str | None = None,
    folder_name: str | None = None,
    save_dir: Path | None = None,
) -> ClonePlan:
    """Resolve a clone without touching the disk, so the UI can show it first.

    `new_name` renames the character (folder *and* the name stored inside the save).
    `folder_name` instead keeps the in-file name and only varies the folder, which is
    the "same name, different file" case — it needs no save bytes to be written at all.
    """
    source = Path(source)
    if not (source / SAVE_FILE).is_file():
        raise CloneError(f"{source} does not contain a {SAVE_FILE}")
    if new_name and folder_name:
        raise CloneError("give either new_name or folder_name, not both")

    parent = Path(save_dir) if save_dir else source.parent
    if new_name is not None:
        resolved = validate_character_name(new_name)
        return ClonePlan(source, parent / f"_{resolved}", resolved, rename_in_file=True)

    if folder_name is None:
        raise CloneError("a clone needs either new_name or folder_name")
    resolved = validate_character_name(folder_name)
    in_file = source.name.lstrip("_")
    return ClonePlan(source, parent / f"_{resolved}", in_file, rename_in_file=False)


def clone_character(plan: ClonePlan, *, allow_game_running: bool = False) -> CloneResult:
    """Execute `plan`, leaving the source untouched.

    Nothing is placed in the save folder until the clone has been rebuilt and
    re-parsed successfully, so a failure part-way through leaves no half-written
    character behind.
    """
    source_file = plan.source / SAVE_FILE
    if not source_file.is_file():
        raise CloneError(f"{plan.source} does not contain a {SAVE_FILE}")
    if plan.destination.exists():
        raise CloneError(f"{plan.destination} already exists — refusing to overwrite")
    if plan.destination == plan.source:
        raise CloneError("clone destination is the source")

    if not allow_game_running and (game := find_running_game()):
        raise GameRunningError(
            f"{game} is running; close Grim Dawn before cloning, or it will "
            "overwrite the new character when it exits"
        )

    original_digest = _digest(source_file)
    parent = plan.destination.parent
    parent.mkdir(parents=True, exist_ok=True)

    # Staged in the destination's own directory so the final move is an atomic rename
    # on the same filesystem rather than a copy that could be seen half-done.
    staging = Path(tempfile.mkdtemp(prefix=".gd-clone-", dir=parent))
    work = staging / plan.destination.name
    try:
        shutil.copytree(plan.source, work)
        if plan.rename_in_file:
            _rewrite_name(work / SAVE_FILE, plan.new_name)
        _verify(work / SAVE_FILE, plan, source_file)

        if _digest(source_file) != original_digest:
            raise CloneError("source save changed during the clone — aborted")

        os.replace(work, plan.destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    else:
        shutil.rmtree(staging, ignore_errors=True)

    return CloneResult(plan=plan, files_copied=sum(1 for _ in plan.destination.rglob("*")))


def _rewrite_name(gdc_path: Path, new_name: str) -> None:
    """Rewrite the character name inside a *copied* save file."""
    document = parse_document(gdc_path.read_bytes())
    document.set("name", new_name)
    gdc_path.write_bytes(write_document(document))


def _verify(gdc_path: Path, plan: ClonePlan, source_file: Path) -> None:
    """Re-parse the rebuilt save and confirm it says what it should.

    Everything except the name must survive a rename untouched; that is checked by
    comparing against the source character rather than trusting the writer.
    """
    try:
        rebuilt = character_from_document(parse_document(gdc_path.read_bytes()))
    except ValueError as exc:
        raise CloneError(f"clone did not parse back cleanly: {exc}") from exc

    if rebuilt.name != plan.new_name:
        raise CloneError(
            f"clone name is {rebuilt.name!r}, expected {plan.new_name!r}"
        )

    original = character_from_document(parse_document(source_file.read_bytes()))
    expected = type(original)(**{**vars(original), "name": plan.new_name})
    if rebuilt != expected:
        raise CloneError("clone differs from the source in more than the name")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
