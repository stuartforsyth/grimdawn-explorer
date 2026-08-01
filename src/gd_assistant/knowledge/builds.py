"""Import and normalise reference builds (SPEC §7).

Web/community builds are imported (manually to start) and stored as "reference
builds" used to explain nuance and context — not copied blindly. The engine cites
them when a suggestion echoes a known build. STATUS: stub.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReferenceBuild:
    """A normalised build imported from a verified source."""

    name: str
    source_url: str
    masteries: list[str] = field(default_factory=list)
    key_skills: list[str] = field(default_factory=list)
    key_items: list[str] = field(default_factory=list)
    notes: str = ""


def import_from_grimtools_url(url: str) -> ReferenceBuild:
    """Import a build from a grimtools calculator share URL. STATUS: stub."""
    raise NotImplementedError("build import not yet implemented (SPEC §7)")
