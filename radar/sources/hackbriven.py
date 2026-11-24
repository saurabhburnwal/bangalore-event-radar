"""Hackbriven: JSON events API, upcoming and ongoing phases."""
from __future__ import annotations

import re

from ..eligibility import Round, has_screening, summary
from ..models import Event
from ..util import html_to_text, parse_dt, parse_int

API = "https://hackbriven.com/api/events?status=Approved&limit=50&phase={phase}"
MODES = {"online": "online", "virtual": "online", "hybrid": "hybrid", "in-person": "offline", "offline": "offline"}


def _prize(breakdown) -> int:
    total = 0
    for p in breakdown or []:
        if isinstance(p, dict):
            for k in ("amount", "cash", "value", "prize"):
                v = parse_int(p.get(k))
                if v is not None and v >= 0:
                    total += v
                    break
    return total


def _team(label) -> tuple[int | None, int | None]:
    """'Individual' -> (1, 1), '2-4 members' -> (2, 4), '3 members' -> (3, 3)."""
    s = str(label or "")[:200].lower()
    if "individual" in s or "solo" in s:
        return 1, 1
    nums = [n for value in re.findall(r"\d+", s) if (n := parse_int(value)) is not None][:2]
    if not nums:
        return None, None
    return nums[0], nums[-1]


def _rounds(stages) -> list[Round]:
    out = []
    for s in stages or []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        kind = (s.get("type") or "").lower()
        # Submissions and quizzes happen on Hackbriven itself; judging/result/custom steps say nothing either way.
        online = True if kind in ("submission", "assessment") else None
        out.append(Round(title=s["name"], online=online, eliminator=bool(s.get("isEliminator")) and not s.get("isFinal")))
    return out


def parse(data: dict) -> list[Event]:
    out = []
    for e in data.get("events", []):
        if not e.get("slug"):
            continue
        mode = MODES.get((e.get("locationType") or "").lower(), "offline")
        team_min, team_max = _team(e.get("teamSize"))
        rounds = _rounds(e.get("stages"))
        out.append(Event(
            source="hackbriven",
            native_id=e["slug"],
            title=(e.get("eventName") or e["slug"]).strip(),
            url=f"https://hackbriven.com/events/{e['slug']}",
            start=parse_dt(e.get("startDate")),
            end=parse_dt(e.get("endDate")),
            venue=e.get("location") or "",
            mode=mode,
            host=e.get("organizationName") or "",
            org=e.get("organizationName") or "",
            description=html_to_text(e.get("description")),
            kind="hackathon" if (e.get("eventType") or "").lower() == "hackathon" else "",
            tech_source=True,
            prize_inr=_prize(e.get("prizeBreakdown")),
            reg_deadline=parse_dt(e.get("registrationEndDate") or e.get("registrationDeadline")),
            team_min=team_min,
            team_max=team_max,
            screening=has_screening(rounds, mode == "hybrid") if rounds else None,
            rounds=summary(rounds),
            extra={"participants": e.get("participants")},
        ))
    return out


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    events: dict[str, Event] = {}
    for phase in ("upcoming", "ongoing"):
        for e in parse(http.json(API.format(phase=phase))):
            events.setdefault(e.native_id, e)
    return list(events.values())
