"""Google Developer Groups: upcoming events of the configured chapters, with venue from each event page (cached)."""
from __future__ import annotations

from ..models import Event
from ..util import html_to_text, next_data, parse_dt

BASE = "https://gdg.community.dev"


def parse_chapter(page: str) -> tuple[dict, list[dict]]:
    pp = next_data(page)["props"]["pageProps"]
    chapter = pp.get("chapterData") or {}
    upcoming = ((pp.get("prerenderData") or {}).get("upcomingEvents") or {}).get("results") or []
    return chapter, upcoming


def parse_detail(page: str) -> dict:
    """Pull venue fields out of an event page. They sit at different depths, so search the tree."""
    data = next_data(page)
    found: dict = {}

    def walk(o):
        if isinstance(o, dict):
            for k in ("venue_name", "venue_address", "venue_city", "description"):
                v = o.get(k)
                if isinstance(v, str) and v and k not in found:
                    found[k] = v
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return {
        "venue": ", ".join(dict.fromkeys(x for x in [found.get("venue_name"), found.get("venue_address")] if x)),
        "city": found.get("venue_city", ""),
        "desc": html_to_text(found.get("description"), 1200),
    }


def build(chapter: dict, e: dict, detail: dict) -> Event:
    url = e.get("url") or ""
    if url.startswith("/"):
        url = BASE + url
    etype = (e.get("event_type_title") or "").lower()
    return Event(
        source="gdg",
        native_id=url.rstrip("/").rsplit("/", 1)[-1],
        title=(e.get("title") or "").strip(),
        url=url,
        start=parse_dt(e.get("start_date")),
        city=detail.get("city") or chapter.get("city") or "",
        venue=detail.get("venue", ""),
        mode="online" if "virtual" in etype or "online" in etype else "offline",
        host=chapter.get("title") or "GDG",
        description=detail.get("desc") or html_to_text(e.get("description_short")),
        tech_source=True,
    )


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    events, live = [], set()
    for slug in cfg.get("chapters") or ["gdg-bangalore", "gdg-cloud-bengaluru"]:
        chapter, upcoming = parse_chapter(http.text(f"{BASE}/{slug}/"))
        for e in upcoming:
            url = e.get("url") or ""
            if not url:
                continue
            full = BASE + url if url.startswith("/") else url
            live.add(full)
            if full not in cache:
                try:
                    cache[full] = parse_detail(http.text(full))
                except Exception:
                    cache[full] = {}
            events.append(build(chapter, e, cache[full]))
    for k in list(cache):
        if k not in live:
            del cache[k]
    return events
