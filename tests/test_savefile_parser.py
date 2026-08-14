"""Tests for the `.gdc` block parser (SPEC §5).

Saves are synthesised here rather than read from disk, so the suite is independent of
any installed game. The encoder mirrors the format's own rules — notably that block
lengths and terminators are consumed *without* advancing the key — so a parser bug
that desyncs the key fails these tests the same way it would fail on a real save.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

import pytest

from gd_assistant.savefile.crypt import MAGIC, SEED_MASK, build_table
from gd_assistant.savefile.parser import GdcParseError, parse_character

SEED = 0x00034B24


class Writer:
    """Builds an obfuscated `.gdc` stream mirroring Grim Dawn's writer."""

    def __init__(self, seed: int = SEED) -> None:
        self.table = build_table(seed)
        self.key = seed
        self.out = bytearray(struct.pack("<I", seed ^ SEED_MASK))

    def _emit(self, raw: bytes) -> None:
        self.out.extend(raw)
        for b in raw:
            self.key ^= self.table[b]

    def u32(self, value: int) -> None:
        self._emit(struct.pack("<I", (value ^ self.key) & 0xFFFFFFFF))

    def u8(self, value: int) -> None:
        self._emit(bytes([value ^ (self.key & 0xFF)]))

    def f32(self, value: float) -> None:
        self.u32(struct.unpack("<I", struct.pack("<f", value))[0])

    def next_u32(self, value: int) -> None:
        """Consumed but does not advance the key — lengths and terminators."""
        self.out.extend(struct.pack("<I", (value ^ self.key) & 0xFFFFFFFF))

    def ascii(self, text: str) -> None:
        self.u32(len(text))
        for ch in text.encode("latin1"):
            self.u8(ch)

    def wide(self, text: str) -> None:
        self.u32(len(text))
        for ch in text:
            self.u8(ord(ch) & 0xFF)
            self.u8(ord(ch) >> 8)

    def block(self, block_id: int, body: Callable[[], object]) -> None:
        """Write a block, back-filling its length once the body is known.

        The length is encoded against the key that was live at that point — and
        because it does not advance the key, back-filling it later is safe.
        """
        self.u32(block_id)
        key_for_length = self.key
        length_at = len(self.out)
        self.out.extend(b"\0\0\0\0")  # placeholder
        start = len(self.out)
        body()
        length = len(self.out) - start
        self.out[length_at : length_at + 4] = struct.pack(
            "<I", (length ^ key_for_length) & 0xFFFFFFFF
        )
        self.next_u32(0)  # terminator


def _item(w: Writer, base: str = "", trailing: int = 4) -> None:
    for text in (base, "", "", "", ""):
        w.ascii(text)
    w.u32(0)
    w.ascii("")
    w.ascii("")
    w.u32(0)
    w.ascii("")
    for _ in range(trailing):
        w.u32(0)


def build_save(
    *,
    name: str = "Tester",
    class_tag: str = "tagSkillClassName0609",
    level: int = 57,
    hardcore: bool = False,
    equipped: list[str] | None = None,
    skills: list[tuple[str, int]] | None = None,
    inventory_version: int = 4,
    skills_version: int = 6,
) -> bytes:
    equipped = equipped or []
    skills = skills or []
    # Unknown versions still write a v4 body, so the parser's version guard is what
    # rejects them rather than a malformed stream.
    trailing = {4: 4, 11: 8}.get(inventory_version, 4)
    extra = {6: 0, 8: 1}.get(skills_version, 0)
    w = Writer()

    w.u32(MAGIC)
    w.u32(2)
    w.wide(name)
    w.u8(0)
    w.ascii(class_tag)
    w.u32(level)
    w.u8(int(hardcore))
    w.u8(7)
    w.next_u32(0)
    w.u32(8)
    for _ in range(16):
        w.u8(0)

    w.block(1, lambda: [w.u32(5), *(w.u8(0) for _ in range(8))])
    def bio() -> None:
        w.u32(8)
        for value in (level, 0, 3, 2, 1, 0):
            w.u32(value)
        for value in (400.0, 50.0, 98.0, 1000.0, 500.0):
            w.f32(value)
    w.block(2, bio)

    def inventory() -> None:
        w.u32(inventory_version)
        w.u8(1)
        w.u32(0)  # no bags
        w.u32(0)
        w.u32(0)
        w.u8(0)
        slots = list(equipped) + [""] * (12 - len(equipped))
        for record in slots[:12]:
            _item(w, record, trailing)
            w.u8(0)
        for _ in range(2):
            w.u8(0)
            for _ in range(2):
                _item(w, "", trailing)
                w.u8(0)
    w.block(3, inventory)

    w.block(4, lambda: [w.u32(6), w.u32(0)])

    def skills_block() -> None:
        w.u32(skills_version)
        w.u32(len(skills))
        for record, points in skills:
            w.ascii(record)
            w.u32(points)
            w.u8(1)
            w.u32(0)
            w.u32(0)
            w.u32(0)
            w.u8(0)
            w.u8(0)
            for _ in range(extra):
                w.u8(0)
            w.ascii("")
            w.ascii("")
        w.u32(2)
        w.u32(0)
        w.u32(0)
        w.u32(0)
    w.block(8, skills_block)
    return bytes(w.out)


@pytest.fixture
def save_path(tmp_path):
    def _write(data: bytes):
        path = tmp_path / "player.gdc"
        path.write_bytes(data)
        return path
    return _write


def test_parses_header_fields(save_path) -> None:
    ch = parse_character(save_path(build_save(name="Tester", level=57)))
    assert ch.name == "Tester"
    assert ch.level == 57
    assert ch.hardcore is False
    assert ch.attributes["physique"] == 400


def test_hardcore_flag(save_path) -> None:
    ch = parse_character(save_path(build_save(hardcore=True)))
    assert ch.hardcore is True


def test_masteries_from_class_tag(save_path) -> None:
    ch = parse_character(save_path(build_save(class_tag="tagSkillClassName0609")))
    assert set(ch.masteries) == {"06", "09"}


def test_single_mastery(save_path) -> None:
    ch = parse_character(save_path(build_save(class_tag="tagSkillClassName05")))
    assert set(ch.masteries) == {"05"}


def test_mastery_bar_points_come_from_skills(save_path) -> None:
    """Mastery bars are stored as skills; their level is the bar investment."""
    data = build_save(
        class_tag="tagSkillClassName06",
        skills=[("records/skills/playerclass06/_classtraining_class06.dbr", 45)],
    )
    ch = parse_character(save_path(data))
    assert ch.masteries["06"] == 45


def test_skills_and_devotion_are_separated(save_path) -> None:
    data = build_save(
        skills=[
            ("records/skills/playerclass06/savagestrike1.dbr", 16),
            ("records/skills/devotion/tier1_01a.dbr", 1),
            ("records/skills/playerclass09/unspent.dbr", 0),  # zero points: dropped
        ]
    )
    ch = parse_character(save_path(data))
    assert [s.skill_id for s in ch.skills] == [
        "records/skills/playerclass06/savagestrike1.dbr"
    ]
    assert [d.node_id for d in ch.devotion] == ["records/skills/devotion/tier1_01a.dbr"]


def test_default_actions_are_not_treated_as_allocations(save_path) -> None:
    """Kick/move-to are granted to every character and cost no points."""
    data = build_save(
        skills=[
            ("records/skills/default/defaultkickattack.dbr", 1),
            ("records/skills/default/defaultmoveto.dbr", 1),
            ("records/skills/playerclass06/savagestrike1.dbr", 16),
        ]
    )
    ch = parse_character(save_path(data))
    assert [s.skill_id for s in ch.skills] == [
        "records/skills/playerclass06/savagestrike1.dbr"
    ]


@pytest.mark.parametrize(
    ("slot", "expected"),
    [
        ("0", "Head"),
        ("6", "Ring"),
        ("7", "Ring"),
        ("11", "Relic"),
        ("weapon1.0", "Main hand (set 1)"),
        ("weapon2.1", "Off hand (set 2)"),
        ("something-else", "something-else"),
    ],
)
def test_slot_labels(slot: str, expected: str) -> None:
    from gd_assistant.savefile.parser import slot_label

    assert slot_label(slot) == expected


def test_equipped_items_and_empty_slots(save_path) -> None:
    data = build_save(equipped=["records/items/head.dbr", "", "records/items/ring.dbr"])
    ch = parse_character(save_path(data))
    assert [e.item_id for e in ch.equipped] == [
        "records/items/head.dbr",
        "records/items/ring.dbr",
    ]
    assert [e.slot for e in ch.equipped] == ["0", "2"]


@pytest.mark.parametrize("inventory_version", [4, 11])
def test_both_item_layouts(save_path, inventory_version: int) -> None:
    """Item gained four trailing ints between inventory formats 4 and 11."""
    data = build_save(
        inventory_version=inventory_version, equipped=["records/items/head.dbr"]
    )
    ch = parse_character(save_path(data))
    assert [e.item_id for e in ch.equipped] == ["records/items/head.dbr"]


@pytest.mark.parametrize("skills_version", [6, 8])
def test_both_skill_layouts(save_path, skills_version: int) -> None:
    """Skill entries gained one byte between block versions 6 and 8."""
    data = build_save(
        skills_version=skills_version,
        skills=[("records/skills/playerclass06/savagestrike1.dbr", 16)],
    )
    ch = parse_character(save_path(data))
    assert ch.skills[0].points == 16


def test_unknown_inventory_version_is_rejected(save_path) -> None:
    """An unrecognised format is refused outright, not parsed on a guess."""
    with pytest.raises(GdcParseError, match="unsupported inventory format"):
        parse_character(save_path(build_save(inventory_version=99)))


def test_unknown_skills_version_is_rejected(save_path) -> None:
    with pytest.raises(GdcParseError, match="unsupported skills format"):
        parse_character(save_path(build_save(skills_version=99)))


def test_not_a_save_is_rejected(save_path) -> None:
    with pytest.raises(GdcParseError, match="not a Grim Dawn save"):
        parse_character(save_path(b"\x00" * 64))


def test_truncated_save_is_rejected(save_path) -> None:
    with pytest.raises(GdcParseError):
        parse_character(save_path(build_save()[:80]))


def test_read_header_is_cheap_and_complete(save_path) -> None:
    """The picker builds from headers alone, so they must carry the label fields."""
    from gd_assistant.savefile.parser import read_header

    data = build_save(name="Getaspark", level=61, hardcore=True,
                      class_tag="tagSkillClassName0506")
    header = read_header(save_path(data))
    assert (header.name, header.level, header.hardcore) == ("Getaspark", 61, True)
    assert header.class_tag == "tagSkillClassName0506"
    assert header.masteries == ["05", "06"]


def test_read_header_rejects_a_non_save(save_path) -> None:
    from gd_assistant.savefile.parser import read_header

    with pytest.raises(GdcParseError):
        read_header(save_path(b"\x00" * 64))


def test_character_carries_its_class_tag(save_path) -> None:
    ch = parse_character(save_path(build_save(class_tag="tagSkillClassName0609")))
    assert ch.class_tag == "tagSkillClassName0609"
