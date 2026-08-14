"""Tests for the structural document layer — the basis of safe write-back (SPEC §5.3).

The property that matters is that `parse_document` → `write_document` is exact. If it
is, coverage is complete: every byte was either modelled or captured, and the key
stayed in sync throughout. If it isn't, a real save would be corrupted.

Saves are synthesised so the suite never depends on an installed game. The builder in
`test_savefile_parser` already mirrors the format's rules, including that lengths and
terminators are consumed without advancing the key, so it exercises the same paths a
real file does.
"""

from __future__ import annotations

import pytest

from gd_assistant.savefile.document import (
    Block,
    Field,
    find_fields,
    parse_document,
    write_document,
)
from gd_assistant.savefile.parser import character_from_document, parse_character

from .test_savefile_parser import build_save


def test_round_trip_is_byte_identical() -> None:
    data = build_save(
        name="Tester",
        equipped=["records/items/head.dbr", "", "records/items/ring.dbr"],
        skills=[("records/skills/playerclass06/savagestrike1.dbr", 16)],
    )
    assert write_document(parse_document(data)) == data


@pytest.mark.parametrize("inventory_version", [4, 11])
@pytest.mark.parametrize("skills_version", [6, 8])
def test_round_trip_across_format_variants(
    inventory_version: int, skills_version: int
) -> None:
    """Both format variants seen in the wild must survive a rebuild untouched."""
    data = build_save(
        inventory_version=inventory_version,
        skills_version=skills_version,
        equipped=["records/items/head.dbr"],
        skills=[("records/skills/playerclass06/savagestrike1.dbr", 16)],
    )
    assert write_document(parse_document(data)) == data


def test_rename_shorter_and_longer() -> None:
    """A rename shifts every later offset, so the whole tail must re-encrypt."""
    data = build_save(name="Archon", skills=[("records/skills/a.dbr", 3)])
    for new_name in ("Zz", "Archon", "ArchonTheVeryLongNamedOne"):
        doc = parse_document(data)
        doc.set("name", new_name)
        rebuilt = write_document(doc)

        reread = parse_document(rebuilt)
        assert reread.get("name").value == new_name
        # Everything else must survive the re-encryption unchanged.
        assert character_from_document(reread).skills[0].points == 3
        expected_delta = 2 * (len(new_name) - len("Archon"))
        assert len(rebuilt) - len(data) == expected_delta


def test_rename_and_back_restores_original_bytes() -> None:
    data = build_save(name="Archon")
    doc = parse_document(data)
    doc.set("name", "Temporary")
    once = write_document(doc)
    assert once != data

    doc = parse_document(once)
    doc.set("name", "Archon")
    assert write_document(doc) == data


def test_edited_field_survives_rebuild() -> None:
    data = build_save()
    doc = parse_document(data)
    doc.set("bio.level", 84)
    reread = parse_document(write_document(doc))
    assert character_from_document(reread).level == 84


def test_opaque_blocks_are_preserved_verbatim() -> None:
    """Blocks we don't model are kept byte-for-byte, not dropped or rewritten."""
    doc = parse_document(build_save())
    info = doc.block(1)
    assert info is not None
    trailers = [n for n in info.items if isinstance(n, Field) and n.kind == "raw"]
    assert trailers, "block 1 should be captured as an opaque run"
    assert len(trailers[0].value) > 0


def test_nested_blocks_are_modelled_not_opaque() -> None:
    """Inventory nests, so it must be structured — a bulk skip would desync the key."""
    doc = parse_document(build_save(equipped=["records/items/head.dbr"]))
    inventory = doc.block(3)
    assert inventory is not None
    assert find_fields(inventory, "equipment.0.base")[0].value == "records/items/head.dbr"


def test_setting_an_unknown_field_raises() -> None:
    doc = parse_document(build_save())
    with pytest.raises(KeyError, match="no field named"):
        doc.set("not_a_real_field", 1)


def test_document_and_parser_agree(tmp_path) -> None:
    """The semantic parser reads the same document the writer would rebuild."""
    data = build_save(name="Tester", equipped=["records/items/head.dbr"])
    path = tmp_path / "player.gdc"
    path.write_bytes(data)
    assert parse_character(path) == character_from_document(parse_document(data))


def test_block_ids_survive_the_round_trip() -> None:
    doc = parse_document(build_save())
    ids = [n.block_id for n in doc.items if isinstance(n, Block)]
    rebuilt = parse_document(write_document(doc))
    assert [n.block_id for n in rebuilt.items if isinstance(n, Block)] == ids
