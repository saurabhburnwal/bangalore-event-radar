"""Hackbriven: JSON events API, upcoming and ongoing phases."""
from __future__ import annotations

from ..models import Event
from ..util import html_to_text, parse_dt

API = "https://hackbriven.com/api/events?status=Approved&limit=50&phase={phase}"


def _prize(breakdown) -> int:
    total = 0
    for p in breakdown or []:
        if isinstance(p, dict):
            for k in ("amount", "cash", "value", "prize"):
                v = p.get(k)
                if isinstance(v, (int, float)):
                    total += int(v)
                    break
    return total


def parse(data: dict) -> list[Event]:
    out = []
    for e in data.get("events", []):
        if not e.get("slug"):
            continue
        lt = (e.get("locationType") or "").lower()
        out.append(Event(
            source="hackbriven",
            native_id=e["slug"],
            title=(e.get("eventName") or e["slug"]).strip(),
            url=f"https://hackbriven.com/events/{e['slug']}",
            start=parse_dt(e.get("startDate")),
            end=parse_dt(e.get("endDate")),
            venue=e.get("location") or "",
            mode="online" if lt == "online" else "hybrid" if lt == "hybrid" else "offline",
            host=e.get("organizationName") or "",
            org=e.get("organizationName") or "",
            description=html_to_text(e.get("description")),
            kind="hackathon" if (e.get("eventType") or "").lower() == "hackathon" else "",
            tech_source=True,
            prize_inr=_prize(e.get("prizeBreakdown")),
            reg_deadline=parse_dt(e.get("registrationEndDate") or e.get("registrationDeadline")),
            extra={"participants": e.get("participants")},
        ))
    return out


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    events: dict[str, Event] = {}
    for phase in ("upcoming", "ongoing"):
        for e in parse(http.json(API.format(phase=phase))):
            events.setdefault(e.native_id, e)
    return list(events.values())
