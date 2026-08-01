"""Item model as stored in the knowledge base (SPEC §6.4)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    """An item from the datamined KB, plus optional farming metadata."""

    id: str
    name: str
    slot: str | None = None
    set_id: str | None = None
    granted_skill_id: str | None = None
    plus_skills: dict[str, int] = field(default_factory=dict)  # skill/mastery -> +N
    tags: list[str] = field(default_factory=list)
    farm_sources: list[str] = field(default_factory=list)  # where to farm (SPEC §6.4)
