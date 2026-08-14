"""Tests for the `.gdc` seed-XOR layer (SPEC §5.1).

Streams are built synthetically so the suite never depends on the developer's own
save files.
"""

from __future__ import annotations

import struct

import pytest

from gd_assistant.savefile.crypt import MAGIC, SEED_MASK, GdcReader, build_table


def encrypt(seed: int, plain_ops: list[tuple[str, object]]) -> bytes:
    """Build an obfuscated stream from typed ops, mirroring the reader's rules.

    Each op XORs against the current key, then advances it using the *ciphertext*
    bytes just produced — the same self-feeding rule the reader relies on.
    """
    table = build_table(seed)
    key = seed
    out = bytearray(struct.pack("<I", seed ^ SEED_MASK))

    def emit(raw: bytes) -> None:
        nonlocal key
        out.extend(raw)
        for b in raw:
            key ^= table[b]

    for kind, value in plain_ops:
        if kind == "u32":
            emit(struct.pack("<I", value ^ key))
        elif kind == "u8":
            emit(bytes([value ^ (key & 0xFF)]))
        elif kind == "ascii":
            emit(struct.pack("<I", len(value) ^ key))
            for ch in value.encode("latin1"):
                emit(bytes([ch ^ (key & 0xFF)]))
        elif kind == "wide":
            emit(struct.pack("<I", len(value) ^ key))
            for ch in value:
                emit(bytes([ord(ch) & 0xFF ^ (key & 0xFF)]))
                emit(bytes([(ord(ch) >> 8) ^ (key & 0xFF)]))
        else:  # pragma: no cover - test helper misuse
            raise AssertionError(kind)
    return bytes(out)


def test_seed_and_table_are_deterministic() -> None:
    table = build_table(0x1234)
    assert len(table) == 256
    assert table == build_table(0x1234)
    assert all(0 <= v <= 0xFFFFFFFF for v in table)


def test_roundtrip_typed_reads() -> None:
    ops = [("u32", MAGIC), ("u32", 2), ("wide", "Archon"), ("u8", 0),
           ("ascii", "tagSkillClassName0609"), ("u32", 57), ("u8", 0)]
    r = GdcReader(encrypt(0x00034B24, ops))
    assert r.read_magic() == 2
    assert r.wide_str() == "Archon"
    assert r.u8() == 0
    assert r.ascii_str() == "tagSkillClassName0609"
    assert r.u32() == 57
    assert r.bool8() is False


def test_skip_keeps_key_in_sync() -> None:
    """Key evolution is granularity-independent, so skipping must not desync it.

    This is the property that lets the parser step over blocks it doesn't model.
    """
    ops = [("u32", 0xAAAA), ("u32", 0xBBBB), ("u32", 1234)]
    data = encrypt(0x99, ops)

    straight = GdcReader(data)
    straight.u32()
    straight.u32()

    skipped = GdcReader(data)
    skipped.skip(8)

    assert skipped.key == straight.key
    assert skipped.u32() == straight.u32() == 1234


def test_bad_magic_is_rejected() -> None:
    r = GdcReader(encrypt(0x11, [("u32", 0xDEADBEEF), ("u32", 2)]))
    with pytest.raises(ValueError, match="not a Grim Dawn save"):
        r.read_magic()


def test_truncated_stream_is_rejected() -> None:
    r = GdcReader(encrypt(0x11, [("u32", 1)]))
    r.u32()
    with pytest.raises(ValueError, match="truncated"):
        r.u32()


def test_implausible_string_length_is_rejected() -> None:
    """A misaligned stream shows up as an absurd length rather than a hang."""
    r = GdcReader(encrypt(0x11, [("u32", 0x7FFFFFFF), ("u32", 0)]))
    with pytest.raises(ValueError, match="misaligned"):
        r.ascii_str()


def test_seed_too_short() -> None:
    with pytest.raises(ValueError, match="too short"):
        GdcReader(b"\x01\x02")
