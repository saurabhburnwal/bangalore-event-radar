"""Devfolio: the hackathon listing, plus each hackathon's own page for city, prize, team size and rounds (cached)."""
from __future__ import annotations

from ..eligibility import round_sentences
from ..models import Event
from ..util import html_to_text, next_data, parse_dt
from .details import cached_detail

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


CACHE_VERSION = 2


def parse_detail(page: str, usd_inr: float = 88) -> dict:
    pp = next_data(page)["props"]["pageProps"]
    h = pp["hackathon"]
    value = pp.get("aggregatePrizeValue") or 0
    if str(pp.get("aggregatePrizeCurrency") or "").upper() == "USD":
        value *= usd_inr
    full = html_to_text(((h.get("tagline") or "") + " " + (h.get("desc") or "")).strip(), 20000)
    faqs = " ".join(html_to_text(f"{f.get('question', '')}. {f.get('answer', '')}", 2000)
                    for f in h.get("faqs") or [] if isinstance(f, dict))
    return {
        "v": CACHE_VERSION,
        "city": h.get("city") or "",
        "location": h.get("location") or "",
        "desc": full[:1200],
        "rounds": round_sentences(full + " " + faqs),  # Devfolio has no round list; organisers describe rounds in prose
        "team_min": h.get("team_min"),
        "team_max": h.get("team_max"),
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
        team_min=detail.get("team_min"),
        team_max=detail.get("team_max"),
        rounds=detail.get("rounds", ""),
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
        detail = cached_detail(cache, slug, CACHE_VERSION, lambda: parse_detail(http.text(DETAIL.format(slug=slug)), usd))
        events.append(build(h, detail))
    return events
