"""Suggestion engine — the heart of the app (SPEC §7).

Input:  parsed Character + KnowledgeBase + FeedbackStore
Output: ranked, EXPLAINED suggestions across three lanes (skills / items / devotion).

Each suggestion is structured so the *why* is first-class — the goal is to help the
user UNDERSTAND synergies and itemisation, not just surface web results. Ranking
blends rule-based synergy scoring with the feedback store (down-weighting
repeatedly-rejected advice). STATUS: stub — first rules land in milestone 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from gd_assistant.models.character import Character


class Lane(str, Enum):
    SKILL = "skill"
    ITEM = "item"
    DEVOTION = "devotion"


@dataclass
class Suggestion:
    """A single explained recommendation."""

    lane: Lane
    what: str                       # the concrete change
    why: str                        # synergy/gap rationale (first-class)
    expected_effect: str = ""
    sources: list[str] = field(default_factory=list)  # KB ids / reference builds
    confidence: float = 0.0         # 0..1, blends rule score + feedback
    signature: str = ""             # stable id for feedback keying (SPEC §8)


def suggest(character: Character, kb, feedback) -> list[Suggestion]:
    """Produce ranked suggestions for a character. STATUS: stub.

    Early rules to implement (milestone 5): resistance gaps, under-invested core
    skills, missing transmuters, +skills item upgrades, devotion proc targets.
    """
    raise NotImplementedError("suggestion engine not yet implemented (SPEC §7, milestone 5)")
