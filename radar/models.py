from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .util import parse_int


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
    team_min: int | None = None   # allowed team size, when the source states it
    team_max: int | None = None
    screening: bool | None = None # an online round comes first (None: the source lists no rounds)
    rounds: str = ""              # short round summary, e.g. "Idea Submission (online) → Grand Finale (offline)"
    extra: dict = field(default_factory=dict)
    cancelled: bool = False

    def __post_init__(self) -> None:
        for field_name in ("title", "city", "venue", "host", "org"):
            value = getattr(self, field_name)
            clean = "".join(c for c in value if c.isprintable() or c.isspace()) if isinstance(value, str) else ""
            setattr(self, field_name, " ".join(clean.split())[:1000])
        for field_name in ("description", "perks", "rounds"):
            value = getattr(self, field_name)
            setattr(self, field_name, value[:20000] if isinstance(value, str) else "")
        self.prize_inr = max(0, parse_int(self.prize_inr) or 0)
        self.spots_left = parse_int(self.spots_left)
        self.team_min = parse_int(self.team_min)
        self.team_max = parse_int(self.team_max)
        if self.team_min is not None and self.team_min < 1:
            self.team_min = None
        if self.team_max is not None and (self.team_max < 1 or self.team_max < (self.team_min or 1)):
            self.team_max = None

    @property
    def id(self) -> str:
        return f"{self.source}:{self.native_id}"

    @property
    def when(self) -> datetime | None:
        return self.start or self.end
