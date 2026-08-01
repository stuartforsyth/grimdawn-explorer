"""Native reader for Grim Dawn `.arc` archive files (SPEC §6.1/§6.2).

Used to read `Text_XX.arc` localisation archives, whose files map `tag*` keys to
display names/descriptions — the `.arz` database stores names as tags (e.g.
`itemNameTag = "tagBoosterBL_B01"`), and these files resolve them. Like the `.arz`
reader, this is fully self-contained (no external extractor, pure-Python LZ4).

Format (verified against retail `resources/Text_EN.arc`, magic "ARC\\0" version 3):

    Header (28 bytes, little-endian):
        u32 magic (== b"ARC\\0")   u32 version (== 3)
        u32 file_count            u32 part_count
        u32 parts_table_size      u32 string_table_size
        u32 record_table_offset

    File data lives in [28 .. record_table_offset). The footer, in order, is:
        parts table:  part_count × 12-byte entries   @ record_table_offset (== parts_table_size)
        string table: null-terminated filenames       (== string_table_size)
        TOC:          file_count × 44-byte entries    (at the very end)
      (record_table_offset + parts_table_size + string_table_size + file_count*44 == EOF, confirmed.)

    TOC entry (44 bytes):
        u32 entry_type, u32 file_offset, u32 compressed_size, u32 decompressed_size,
        u32 unknown(hash), u64 filetime, u32 part_count, u32 first_part_index,
        u32 name_len, u32 name_offset (into the string table)

    Parts entry (12 bytes): u32 part_offset, u32 compressed_size, u32 decompressed_size
      A part is stored uncompressed when compressed_size == decompressed_size,
      otherwise it is an LZ4 block. A file is the concatenation of `part_count`
      parts from `first_part_index`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from gd_assistant.knowledge import lz4_block

HEADER_SIZE = 28
TOC_ENTRY_SIZE = 44
PART_ENTRY_SIZE = 12
_ARC_MAGIC = b"ARC\x00"
_ARC_VERSION = 3


@dataclass
class _TocEntry:
    file_offset: int
    compressed_size: int
    decompressed_size: int
    part_count: int
    first_part_index: int
    name: str


class ArcArchive:
    """Read-only view over an `.arc` archive."""

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        magic, version = struct.unpack_from("<4sI", raw, 0)
        if magic != _ARC_MAGIC or version != _ARC_VERSION:
            raise ValueError(f"unrecognised .arc header: magic={magic!r} version={version}")
        (
            self._file_count,
            self._part_count,
            self._parts_table_size,
            self._string_table_size,
            self._record_table_offset,
        ) = struct.unpack_from("<5I", raw, 8)

        # Footer order: parts table, then string table, then TOC (at the end).
        self._parts_offset = self._record_table_offset
        self._strings_offset = self._parts_offset + self._parts_table_size
        self._toc_offset = self._strings_offset + self._string_table_size
        self._toc = self._read_toc()

    @classmethod
    def open(cls, path: str | Path) -> ArcArchive:
        return cls(Path(path).read_bytes())

    # -- public API -------------------------------------------------------
    def names(self) -> list[str]:
        return [e.name for e in self._toc]

    def read(self, name: str) -> bytes:
        for entry in self._toc:
            if entry.name == name:
                return self._read_entry(entry)
        raise KeyError(name)

    def files(self):
        """Yield `(name, bytes)` for every file in the archive."""
        for entry in self._toc:
            yield entry.name, self._read_entry(entry)

    # -- internals --------------------------------------------------------
    def _read_toc(self) -> list[_TocEntry]:
        raw = self._raw
        entries: list[_TocEntry] = []
        for i in range(self._file_count):
            base = self._toc_offset + i * TOC_ENTRY_SIZE
            (
                _entry_type,
                file_offset,
                comp_size,
                decomp_size,
                _unknown,
                _filetime,
                part_count,
                first_part_index,
                name_len,
                name_offset,
            ) = struct.unpack_from("<IIIIIQIIII", raw, base)
            start = self._strings_offset + name_offset
            name = raw[start:start + name_len].decode("latin-1")
            entries.append(
                _TocEntry(file_offset, comp_size, decomp_size,
                          part_count, first_part_index, name)
            )
        return entries

    def _read_entry(self, entry: _TocEntry) -> bytes:
        raw = self._raw
        out = bytearray()
        for p in range(entry.first_part_index, entry.first_part_index + entry.part_count):
            base = self._parts_offset + p * PART_ENTRY_SIZE
            part_offset, comp_size, decomp_size = struct.unpack_from("<III", raw, base)
            chunk = raw[part_offset:part_offset + comp_size]
            if comp_size == decomp_size:
                out += chunk                                   # stored
            else:
                out += lz4_block.decompress(chunk, decomp_size)  # LZ4 block
        return bytes(out)


def load_text_tags(path: str | Path) -> dict[str, str]:
    """Read a `Text_XX.arc` and return a merged `{tag: display_string}` map.

    Each contained `.txt` file holds `key=value` lines (UTF-8, BOM-tolerant); later
    files win on duplicate keys. This resolves the `tag*` references stored in the
    `.arz` database (SPEC §6.3).
    """
    archive = ArcArchive.open(path)
    tags: dict[str, str] = {}
    for name, data in archive.files():
        if not name.lower().endswith(".txt"):
            continue
        text = data.decode("utf-8-sig", errors="replace")
        for line in text.splitlines():
            key, sep, value = line.partition("=")
            if sep and key:
                tags[key.strip()] = value.strip()
    return tags
