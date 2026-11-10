from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    """One event, normalized from any source."""

    source: str
    native_id: str
    title: str
    url: str
    start: datetime | None = None
    end: datetime | None = None
    city: str = ""            # structured city from the source, if it has one
    venue: str = ""
    mode: str = "offline"     # offline | online | hybrid
    host: str = ""            # display name: group, community or organiser
    org: str = ""             # organiser names used for big-tech matching (not community groups)
    description: str = ""     # plain text, truncated
    kind: str = ""            # "hackathon" when the source says so
    tech_source: bool = False # source only lists tech events, so no tech keyword is required
    prize_inr: int = 0
    ppi: bool = False         # structured internship / pre-placement flag (Unstop)
    prize_data: bool = False  # source gives structured prizes, so the description isn't searched for offers
    perks: str = ""           # non-cash prize text, e.g. "Internship + goodies"
    spots_left: int | None = None
    near_capacity: bool = False
    sold_out: bool = False
    reg_deadline: datetime | None = None
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.native_id}"

    @property
    def when(self) -> datetime | None:
        return self.start or self.end
