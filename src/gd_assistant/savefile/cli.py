"""Command-line front end for cloning a character — the safe way to try write-back.

Deliberately cautious defaults, because this is the first code in the project that
produces save bytes:

* it **lists** characters and does nothing else unless told to clone;
* a clone is a **dry run** unless `--write` is passed;
* `--sandbox DIR` clones into a scratch directory instead of the real save folder,
  which is the recommended way to try it the first time;
* writing into the real save folder additionally requires `--i-mean-it`.

Whatever the flags, the source character is only ever read (SPEC §5.3).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gd_assistant.savefile import locator
from gd_assistant.savefile.clone import (
    CloneError,
    clone_character,
    find_running_game,
    plan_clone,
)
from gd_assistant.savefile.parser import GdcParseError, parse_character


def _resolve_save_dir(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise SystemExit(f"save dir not found: {path}")
        return path
    found = locator.find_save_dir()
    if found is None:
        raise SystemExit(
            "could not find a Grim Dawn save directory; pass --save-dir explicitly"
        )
    return found


def _find_character(save_dir: Path, name: str) -> Path:
    wanted = name.lstrip("_").casefold()
    for candidate in locator.list_characters(save_dir):
        if candidate.name.lstrip("_").casefold() == wanted:
            return candidate
    raise SystemExit(f"no character called {name!r} under {save_dir}")


def _cmd_list(args: argparse.Namespace) -> int:
    save_dir = _resolve_save_dir(args.save_dir)
    characters = locator.list_characters(save_dir)
    print(f"{save_dir}  ({len(characters)} characters)\n")
    for path in characters:
        try:
            ch = parse_character(path / "player.gdc")
        except GdcParseError as exc:
            print(f"  {path.name:28} !! {exc}")
            continue
        masteries = "/".join(f"{m}:{p}" for m, p in sorted(ch.masteries.items()))
        print(
            f"  {ch.name:28} lvl {ch.level:>3}  {'HC' if ch.hardcore else '  '}  "
            f"masteries {masteries or '-':12} "
            f"{len(ch.skills):>3} skills, {len(ch.devotion):>2} devotion, "
            f"{len(ch.equipped):>2} equipped"
        )
    return 0


def _cmd_clone(args: argparse.Namespace) -> int:
    save_dir = _resolve_save_dir(args.save_dir)
    source = _find_character(save_dir, args.character)
    target = Path(args.sandbox).expanduser() if args.sandbox else None

    try:
        plan = plan_clone(
            source,
            new_name=args.rename,
            folder_name=args.folder,
            save_dir=target,
        )
    except CloneError as exc:
        raise SystemExit(f"cannot plan clone: {exc}") from exc

    print(f"source       {plan.source}")
    print(f"destination  {plan.destination}")
    print(f"character    {plan.source_name!r} -> {plan.new_name!r}")
    print(
        "mode         "
        + (
            "rewrite the name inside player.gdc"
            if plan.rename_in_file
            else "copy only — no save bytes are written"
        )
    )
    if running := find_running_game():
        print(f"warning      {running} is running; cloning will refuse until it exits")

    if not args.write:
        print("\nDRY RUN — nothing written. Re-run with --write to perform the clone.")
        return 0

    if target is None and not args.i_mean_it:
        raise SystemExit(
            "refusing to write into the real save folder without --i-mean-it\n"
            "(try --sandbox /tmp/gd-clone-test first)"
        )

    try:
        result = clone_character(plan)
    except CloneError as exc:
        raise SystemExit(f"clone failed (nothing was written): {exc}") from exc

    print(f"\ncloned {result.files_copied} files to {plan.destination}")
    cloned = parse_character(plan.destination / "player.gdc")
    print(f"verified: {cloned.name!r}, level {cloned.level}, {len(cloned.equipped)} equipped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gd-assistant-clone",
        description="Inspect characters and clone one into a new save folder. "
        "Originals are never modified.",
    )
    parser.add_argument("--save-dir", help="override save directory discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="list characters in the save folder")
    listing.set_defaults(func=_cmd_list)

    cloning = sub.add_parser("clone", help="clone a character into a new folder")
    cloning.add_argument("character", help="name of the character to clone")
    naming = cloning.add_mutually_exclusive_group(required=True)
    naming.add_argument("--rename", help="new character name (folder and save file)")
    naming.add_argument(
        "--folder",
        help="keep the character's name, write to this folder name instead",
    )
    cloning.add_argument("--sandbox", help="clone into this directory instead of the save folder")
    cloning.add_argument("--write", action="store_true", help="actually perform the clone")
    cloning.add_argument(
        "--i-mean-it",
        action="store_true",
        help="required to write into the real save folder",
    )
    cloning.set_defaults(func=_cmd_clone)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
