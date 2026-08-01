"""Human-in-the-loop feedback store (SPEC §8).

Every surfaced suggestion can be rated good/bad with a note. Stored as JSON at
`data/feedback/feedback.json`, keyed by a stable suggestion signature (skill/item/
rule id + character archetype). The engine down-weights repeatedly-rejected
suggestions and surfaces prior notes next to similar future ones. This is the
primary mechanism for the app to learn what the user actually wants. STATUS: stub.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

FEEDBACK_PATH = Path(__file__).resolve().parents[3] / "data" / "feedback" / "feedback.json"


@dataclass
class Rating:
    signature: str
    good: bool
    note: str = ""


class FeedbackStore:
    """Load/save/query suggestion ratings."""

    def __init__(self, path: Path = FEEDBACK_PATH) -> None:
        self.path = path

    def record(self, rating: Rating) -> None:
        raise NotImplementedError("feedback store not yet implemented (SPEC §8, milestone 6)")

    def score_for(self, signature: str) -> float:
        """Return a ranking adjustment in [-1, 1] for a suggestion signature."""
        raise NotImplementedError("feedback store not yet implemented (SPEC §8, milestone 6)")
