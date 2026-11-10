"""Luma: the Bengaluru discover feed plus any community calendars listed in config."""
from __future__ import annotations

from ..models import Event
from ..util import parse_dt

DISCOVER = "https://api.lu.ma/discover/get-paginated-events?discover_place_api_id={place}&pagination_limit=50"
CALENDAR = "https://api.lu.ma/calendar/get-items?calendar_api_id={cal}&period=future&pagination_limit=50"


def parse(data: dict) -> list[Event]:
    out = []
    for e in data.get("entries", []):
        ev = e.get("event") or {}
        if not ev.get("url") or not ev.get("name"):
            continue
        ti = e.get("ticket_info") or {}
        geo = ev.get("geo_address_info") or {}
        cal = e.get("calendar") or {}
        hosts = [h.get("name") for h in e.get("hosts") or [] if h.get("name")]
        cal_name = "" if cal.get("is_personal") else (cal.get("name") or "")
        org = ", ".join(([cal_name] if cal_name else []) + hosts)
        loc_type = ev.get("location_type") or "offline"
        out.append(Event(
            source="luma",
            native_id=ev.get("api_id") or ev["url"],
            title=ev["name"].strip(),
            url=f"https://luma.com/{ev['url']}",
            start=parse_dt(ev.get("start_at")),
            end=parse_dt(ev.get("end_at")),
            city=geo.get("city") or "",
            venue=geo.get("address") or geo.get("sublocality") or "",
            mode="online" if loc_type == "online" else "offline",
            host=cal_name or (hosts[0] if hosts else ""),
            org=org,
            spots_left=ti.get("spots_remaining"),
            near_capacity=bool(ti.get("is_near_capacity")),
            sold_out=bool(ti.get("is_sold_out")) or e.get("registration_availability") in ("sold-out", "waitlist"),
            extra={"guests": e.get("guest_count")},
        ))
    return out


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    events = parse(http.json(DISCOVER.format(place=cfg.get("place_id", "discplace-G0tGUVYwl7T17Sb"))))
    seen = {e.native_id for e in events}
    for cal in cfg.get("calendars") or []:
        for e in parse(http.json(CALENDAR.format(cal=cal))):
            if e.native_id not in seen:
                seen.add(e.native_id)
                events.append(e)
    return events
