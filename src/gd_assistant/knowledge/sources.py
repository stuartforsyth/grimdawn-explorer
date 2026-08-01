"""Registry of verified web sources for cross-checking and build context (SPEC §6/§7).

grimtools (no API) is used only as a reference/cross-check for values our datamine
computes; other sources provide build guides for context. Anything fetched here is
rate-limited, cached, and never required to build the KB. STATUS: stub.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    trusted: bool
    notes: str = ""


VERIFIED_SOURCES: list[Source] = [
    Source("grimtools", "https://www.grimtools.com/db/", trusted=True,
           notes="Reference/cross-check only; datamine by Dammitt, no public API."),
]
