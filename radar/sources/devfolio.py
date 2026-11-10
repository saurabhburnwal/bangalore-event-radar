"""Devfolio: the hackathon listing, plus each hackathon's own page for city and prize (cached)."""
from __future__ import annotations

from ..models import Event
from ..util import html_to_text, next_data, parse_dt

LISTING = "https://devfolio.co/hackathons"
DETAIL = "https://{slug}.devfolio.co/"


def parse_listing(page: str) -> list[dict]:
    queries = next_data(page)["props"]["pageProps"]["dehydratedState"]["queries"]
    found: dict[str, dict] = {}
    for q in queries:
        data = (q.get("state") or {}).get("data")
        if not isinstance(data, dict):
            continue
        for key in ("open_hackathons", "upcoming_hackathons", "featured_hackathons"):
            for h in data.get(key) or []:
                if h.get("slug"):
                    found.setdefault(h["slug"], h)
    return list(found.values())


def parse_detail(page: str, usd_inr: float = 88) -> dict:
    pp = next_data(page)["props"]["pageProps"]
    h = pp.get("hackathon") or {}
    value = pp.get("aggregatePrizeValue") or 0
    if str(pp.get("aggregatePrizeCurrency") or "").upper() == "USD":
        value *= usd_inr
    return {
        "city": h.get("city") or "",
        "location": h.get("location") or "",
        "desc": html_to_text(((h.get("tagline") or "") + " " + (h.get("desc") or "")).strip(), 1200),
        "prize_inr": int(value),
    }


def build(h: dict, detail: dict) -> Event:
    settings = h.get("settings") or {}
    themes = [t.get("theme", {}).get("name", "") for t in h.get("themes") or [] if isinstance(t, dict)]
    return Event(
        source="devfolio",
        native_id=h["slug"],
        title=(h.get("name") or h["slug"]).strip(),
        url=DETAIL.format(slug=h["slug"]),
        start=parse_dt(h.get("starts_at")),
        end=parse_dt(h.get("ends_at")),
        city=detail.get("city", ""),
        venue=detail.get("location", ""),
        mode="online" if h.get("is_online") else "offline",
        description=detail.get("desc", "") + (" Themes: " + ", ".join(themes) if themes else ""),
        kind="hackathon",
        tech_source=True,
        prize_inr=detail.get("prize_inr", 0),
        reg_deadline=parse_dt(settings.get("reg_ends_at")),
        extra={"participants": h.get("participants_count")},
    )


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    usd = cfg.get("usd_inr", 88)
    listing = parse_listing(http.text(LISTING))
    live = {h["slug"] for h in listing}
    for slug in list(cache):
        if slug not in live:
            del cache[slug]
    events = []
    for h in listing:
        slug = h["slug"]
        if slug not in cache and not h.get("is_online"):
            try:
                cache[slug] = parse_detail(http.text(DETAIL.format(slug=slug)), usd)
            except Exception:
                cache[slug] = {}  # fetch once; don't hammer a broken page every run
        events.append(build(h, cache.get(slug) or {}))
    return events
