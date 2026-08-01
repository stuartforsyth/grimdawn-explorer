"""Skill / mastery model as stored in the knowledge base (SPEC §6.4)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Skill:
    """A skill, its modifiers and transmuters, from the datamined KB."""

    id: str
    name: str
    mastery: str
    max_points: int = 0
    is_transmuter: bool = False
    modifies_skill_id: str | None = None  # for modifier skills
    tags: list[str] = field(default_factory=list)  # e.g. damage types, playstyle
