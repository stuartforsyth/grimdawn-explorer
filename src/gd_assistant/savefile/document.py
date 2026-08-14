"""Complete structural model of a `player.gdc` file — the layer that makes writing safe.

`parser.py` extracts a `Character` and may skip whatever it doesn't need. A writer
cannot be so relaxed: the cipher's key advances over every byte consumed, so changing
an early field — the character name is the *first* field in the file — invalidates the
keystream for everything after it (SPEC §5.3).

The saving grace is that "coverage" does not mean "understanding". Reading a region as
a run of `u8`s advances the key exactly as any other read widths would, because key
evolution depends only on *which* bytes were consumed, never on how they were grouped.
Re-emitting those same plaintext bytes therefore reproduces the original ciphertext
exactly. So a block can be kept as an opaque byte run and still round-trip perfectly —
provided it contains no **nested** block, whose length fields are consumed *without*
advancing the key and would be over-fed by a bulk run.

Measured against the dev saves: only blocks **3 (inventory)** and **4 (stash)** nest.
Everything else is flat. So this module models:

* the header — the fields we actually edit;
* bio, inventory, stash and skills — structured, for reading and editing;
* every other block — opaque, preserved byte-for-byte without pretending to know it.

The grammar is written once, in `_document_schema`, and driven by two visitors: one
reads a file into a `Document`, one writes a `Document` back out. They cannot drift
apart, and `parse_document` → `write_document` reproducing the input byte-for-byte is
what proves coverage is complete.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from gd_assistant.savefile.crypt import GdcReader, GdcWriter

# Leaf kinds, matching the reader/writer method names.
U8 = "u8"
U32 = "u32"
F32 = "f32"
ASCII = "ascii_str"
WIDE = "wide_str"
NEXT_U32 = "next_u32"
RAW = "raw"

TRAILER = "_trailer"

BLOCK_INFO = 1
BLOCK_BIO = 2
BLOCK_INVENTORY = 3
BLOCK_STASH = 4
BLOCK_SKILLS = 8

# Both variants occur on one install, since a save carries the format of whichever
# patch last wrote it. Measured against real saves, not assumed.
_ITEM_TRAILING = {4: 4, 11: 8}
_SKILL_EXTRA_BYTES = {6: 0, 8: 1}


@dataclass
class Field:
    """A single typed value, tagged with the name it has in the format."""

    name: str
    kind: str
    value: object


@dataclass
class Block:
    """A length-prefixed block, possibly containing nested blocks."""

    block_id: int
    items: list[Node] = dataclasses.field(default_factory=list)


Node = Field | Block


@dataclass
class Document:
    """A whole save file: the seed it was encrypted with, plus its contents."""

    seed: int
    items: list[Node] = dataclasses.field(default_factory=list)

    def block(self, block_id: int) -> Block | None:
        """Return the first top-level block with `block_id`."""
        for node in self.items:
            if isinstance(node, Block) and node.block_id == block_id:
                return node
        return None

    def get(self, name: str) -> Field | None:
        """Return the first field called `name`, at any depth."""
        found = find_fields(self, name)
        return found[0] if found else None

    def set(self, name: str, value: object) -> None:
        """Set the first field called `name`, raising if it isn't present."""
        target = self.get(name)
        if target is None:
            raise KeyError(f"no field named {name!r} in this save")
        target.value = value


def find_fields(node: Block | Document, name: str) -> list[Field]:
    """Return every field called `name` at any depth beneath `node`."""
    found: list[Field] = []
    for item in node.items:
        if isinstance(item, Field):
            if item.name == name:
                found.append(item)
        else:
            found.extend(find_fields(item, name))
    return found


class _Reader:
    """Visitor that pulls values out of a file, recording them as it goes."""

    def __init__(self, r: GdcReader) -> None:
        self.r = r
        self._stack: list[list[Node]] = [[]]
        self._ends: list[int] = []

    @property
    def items(self) -> list[Node]:
        return self._stack[0]

    def value(self, name: str, kind: str) -> object:
        value = getattr(self.r, kind)()
        self._stack[-1].append(Field(name, kind, value))
        return value

    def start_block(self, expected: int | None = None) -> int:
        block_id, end = self.r.block_start()
        if expected is not None and block_id != expected:
            raise ValueError(f"expected block {expected}, found {block_id}")
        block = Block(block_id)
        self._stack[-1].append(block)
        self._stack.append(block.items)
        self._ends.append(end)
        return block_id

    def end_block(self) -> None:
        end = self._ends.pop()
        # Whatever the schema didn't name is captured verbatim. Reading it as u8s
        # advances the key identically to the game's own widths, so the bytes can be
        # replayed exactly — and the terminator below proves we stayed in sync.
        if self.r.pos < end:
            body = bytes(self.r.u8() for _ in range(end - self.r.pos))
            self._stack[-1].append(Field(TRAILER, RAW, body))
        self.r.block_end(end)
        self._stack.pop()

    def more_blocks(self) -> bool:
        """True while another top-level block remains to be read."""
        return self.r.remaining > 8


class _Writer:
    """Visitor that replays a recorded document back into bytes."""

    def __init__(self, w: GdcWriter, items: list[Node]) -> None:
        self.w = w
        self._cursor: list[list[Node]] = [list(items)]
        self._index: list[int] = [0]

    def value(self, name: str, kind: str) -> object:
        node = self._next()
        if not isinstance(node, Field) or node.name != name or node.kind != kind:
            raise ValueError(
                f"document/schema mismatch: expected {name}:{kind}, found {node!r}"
            )
        self._emit(node)
        return node.value

    def start_block(self, expected: int | None = None) -> int:
        node = self._next()
        if not isinstance(node, Block):
            raise TypeError(f"document/schema mismatch: expected a block, found {node!r}")
        self.w.block_start(node.block_id)
        self._cursor.append(node.items)
        self._index.append(0)
        return node.block_id

    def end_block(self) -> None:
        # Anything the schema didn't consume must be a captured raw run.
        while self._index[-1] < len(self._cursor[-1]):
            node = self._next()
            if not isinstance(node, Field) or node.kind != RAW:
                raise ValueError(f"unconsumed node at block end: {node!r}")
            self._emit(node)
        self._cursor.pop()
        self._index.pop()
        self.w.block_end()

    def more_blocks(self) -> bool:
        """True while top-level nodes remain, mirroring the reader's cue."""
        return self._index[0] < len(self._cursor[0])

    def pending(self) -> int:
        return len(self._cursor[0]) - self._index[0]

    def _emit(self, node: Field) -> None:
        if node.kind == RAW:
            self.w.raw_bytes(node.value)  # type: ignore[arg-type]
        else:
            getattr(self.w, node.kind)(node.value)

    def _next(self) -> Node:
        items, i = self._cursor[-1], self._index[-1]
        if i >= len(items):
            raise ValueError("document ended before the schema did")
        self._index[-1] = i + 1
        return items[i]


# --------------------------------------------------------------------------------
# The grammar. `v` is whichever visitor is driving — reader or writer.
# --------------------------------------------------------------------------------


def _item(v, prefix: str, trailing: int) -> None:
    for name in ("base", "prefix", "suffix", "modifier", "transmute"):
        v.value(f"{prefix}.{name}", ASCII)
    v.value(f"{prefix}.seed", U32)
    v.value(f"{prefix}.component", ASCII)
    v.value(f"{prefix}.relic_bonus", ASCII)
    v.value(f"{prefix}.component_seed", U32)
    v.value(f"{prefix}.augment", ASCII)
    for i in range(trailing):
        v.value(f"{prefix}.trailing{i}", U32)


def _opaque_block(v) -> int:
    """Consume a whole block without interpreting it, preserving its bytes."""
    block_id = v.start_block()
    v.end_block()
    return block_id


def _block_bio(v) -> None:
    """Block 2 — level, experience, attributes, unspent points."""
    v.start_block(BLOCK_BIO)
    v.value("bio.version", U32)
    v.value("bio.level", U32)
    v.value("bio.experience", U32)
    v.value("bio.attribute_points_unspent", U32)
    v.value("bio.skill_points_unspent", U32)
    v.value("bio.devotion_points_unspent", U32)
    v.value("bio.total_devotion_unlocked", U32)
    for name in ("physique", "cunning", "spirit", "health", "energy"):
        v.value(f"bio.{name}", F32)
    v.end_block()


def _block_inventory(v) -> int:
    """Block 3 — bags and equipped gear. Nests, so it must be modelled."""
    v.start_block(BLOCK_INVENTORY)
    version = v.value("inventory.version", U32)
    trailing = _ITEM_TRAILING.get(version)
    if trailing is None:
        raise ValueError(
            f"unsupported inventory format {version}; known: {sorted(_ITEM_TRAILING)}"
        )
    if v.value("inventory.flag", U8):
        bags = v.value("inventory.num_bags", U32)
        v.value("inventory.focused", U32)
        v.value("inventory.selected", U32)
        for bag in range(bags):
            v.start_block(0)
            v.value(f"bag{bag}.temp_bool", U8)
            count = v.value(f"bag{bag}.count", U32)
            for i in range(count):
                _item(v, f"bag{bag}.item{i}", trailing)
                v.value(f"bag{bag}.item{i}.x", U32)
                v.value(f"bag{bag}.item{i}.y", U32)
            v.end_block()
        v.value("inventory.use_alternate", U8)
        for slot in range(12):
            _item(v, f"equipment.{slot}", trailing)
            v.value(f"equipment.{slot}.attached", U8)
        for set_index in (1, 2):
            v.value(f"inventory.alternate{set_index}", U8)
            for slot in range(2):
                _item(v, f"weapon{set_index}.{slot}", trailing)
                v.value(f"weapon{set_index}.{slot}.attached", U8)
    v.end_block()
    return trailing


def _block_stash(v, trailing: int) -> None:
    """Block 4 — personal stash. Nests (one block per tab), so it must be modelled.

    Newer formats append per-tab bytes the field maps don't describe; those are kept
    as an opaque trailer rather than guessed at.
    """
    v.start_block(BLOCK_STASH)
    v.value("stash.version", U32)
    tabs = v.value("stash.tabs_purchased", U32)
    for tab in range(tabs):
        v.start_block(0)
        v.value(f"stash{tab}.width", U32)
        v.value(f"stash{tab}.height", U32)
        count = v.value(f"stash{tab}.count", U32)
        for i in range(count):
            _item(v, f"stash{tab}.item{i}", trailing)
            v.value(f"stash{tab}.item{i}.x", F32)
            v.value(f"stash{tab}.item{i}.y", F32)
        v.end_block()
    v.end_block()


def _block_skills(v) -> None:
    """Block 8 — allocated skills and devotion nodes.

    The tail (reclamation counters, item-granted skills) is left to the opaque
    trailer: it is never read, and item skills are recoverable from equipped gear.
    """
    version = v.value("skills.version", U32)
    extra = _SKILL_EXTRA_BYTES.get(version)
    if extra is None:
        raise ValueError(
            f"unsupported skills format {version}; known: {sorted(_SKILL_EXTRA_BYTES)}"
        )
    count = v.value("skills.count", U32)
    for i in range(count):
        v.value(f"skill{i}.name", ASCII)
        v.value(f"skill{i}.level", U32)
        v.value(f"skill{i}.enabled", U8)
        v.value(f"skill{i}.devotion_level", U32)
        v.value(f"skill{i}.experience", U32)
        v.value(f"skill{i}.active", U32)
        v.value(f"skill{i}.unknown1", U8)
        v.value(f"skill{i}.unknown2", U8)
        for x in range(extra):
            v.value(f"skill{i}.extra{x}", U8)
        v.value(f"skill{i}.auto_cast_skill", ASCII)
        v.value(f"skill{i}.auto_cast_controller", ASCII)


def _document_schema(v) -> None:
    """The whole file, start to finish. Order is the format's own."""
    v.value("magic", U32)
    v.value("format_version", U32)
    v.value("name", WIDE)
    v.value("sex", U8)
    v.value("class_tag", ASCII)
    v.value("level", U32)
    v.value("hardcore", U8)
    v.value("expansions", U8)
    v.value("zero", NEXT_U32)
    v.value("file_version", U32)
    for i in range(16):
        v.value(f"uid.{i}", U8)

    _opaque_block(v)  # 1 — general info; flat, nothing here is edited
    _block_bio(v)
    trailing = _block_inventory(v)
    _block_stash(v, trailing)

    # Every remaining block is flat, so each is preserved wholesale — except skills,
    # which is modelled because the Character needs it. Walking generically keeps this
    # robust to blocks appearing, moving or vanishing between game versions.
    while v.more_blocks():
        block_id = v.start_block()
        if block_id == BLOCK_SKILLS:
            _block_skills(v)
        v.end_block()


def parse_document(data: bytes) -> Document:
    """Read a whole save into a `Document`, accounting for every byte."""
    # Check the magic on a throwaway reader first, so a file that simply isn't a save
    # says so plainly instead of failing deep in the schema as a misaligned string.
    GdcReader(data).read_magic()

    reader = GdcReader(data)
    visitor = _Reader(reader)
    _document_schema(visitor)
    if reader.remaining:
        raise ValueError(
            f"{reader.remaining} trailing bytes after the final block — "
            "the schema does not cover this save"
        )
    return Document(seed=reader.seed, items=visitor.items)


def write_document(doc: Document) -> bytes:
    """Serialise a `Document` back into an obfuscated save."""
    writer = GdcWriter(doc.seed)
    visitor = _Writer(writer, doc.items)
    _document_schema(visitor)
    if visitor.pending():
        raise ValueError(
            f"{visitor.pending()} document node(s) the schema did not write"
        )
    return writer.getvalue()
