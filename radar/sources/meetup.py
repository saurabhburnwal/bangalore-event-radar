"""Meetup: search result pages, read from the Apollo state in __NEXT_DATA__."""
from __future__ import annotations

from ..models import Event
from ..util import next_data, parse_dt

DEFAULT_URLS = [
    "https://www.meetup.com/find/?location=in--Bengaluru&source=EVENTS&categoryId=546",
    "https://www.meetup.com/find/?keywords=hackathon&location=in--Bengaluru&source=EVENTS",
]
MODES = {"ONLINE": "online", "PHYSICAL": "offline", "HYBRID": "hybrid"}


def parse(page: str) -> list[Event]:
    state = next_data(page)["props"]["pageProps"]["__APOLLO_STATE__"]

    def ref(x):
        return state.get(x["__ref"], x) if isinstance(x, dict) and "__ref" in x else (x or {})

    out = []
    for key, e in state.items():
        if not key.startswith("Event:") or not e.get("title") or not e.get("eventUrl"):
            continue
        group = ref(e.get("group"))
        venue = ref(e.get("venue"))
        going = (e.get("rsvps") or {}).get("totalCount")
        cap = e.get("maxTickets") or 0
        spots = max(cap - going, 0) if cap and going is not None else None
        venue_name = venue.get("name") or ""
        if venue_name.lower() == "online event":
            venue_name = ""
        out.append(Event(
            source="meetup",
            native_id=str(e["id"]),
            title=e["title"].replace("​", "").strip(),
            url=e["eventUrl"],
            start=parse_dt(e.get("dateTime")),
            city=venue.get("city") or "",
            venue=", ".join(x for x in [venue_name, venue.get("address") or ""] if x),
            mode=MODES.get(e.get("eventType", ""), "offline"),
            host=group.get("name") or "",
            description=(e.get("description") or "")[:1500],
            spots_left=spots,
            sold_out=spots == 0,
            extra={"going": going, "capacity": cap or None},
        ))
    return out


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    events: dict[str, Event] = {}
    for url in cfg.get("urls") or DEFAULT_URLS:
        for e in parse(http.text(url)):
            events.setdefault(e.native_id, e)
    return list(events.values())
