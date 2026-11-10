"""Hasgeek: the "Upcoming" cards on the home page (HTML, no structured data)."""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import Event
from ..util import IST

HOME = "https://hasgeek.com/"
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
_DATE = re.compile(r"(\d{1,2})(?:\s+([A-Z][a-z]{2}))?(?:\s+(\d{4}))?")


def parse_date_label(label: str) -> datetime | None:
    """Parse the start date from labels like '20–21 Nov 2026' or '28 Sep 2025–31 Dec 2026'."""
    parts = re.split(r"\s*[–-]\s*", label)
    end = _DATE.match(parts[-1].strip())
    start = _DATE.match(parts[0].strip())
    if not end or not start or not end.group(2) or not end.group(3):
        return None
    month = start.group(2) or end.group(2)
    year = start.group(3) or end.group(3)
    try:
        return datetime(int(year), MONTHS[month], int(start.group(1)), tzinfo=IST)
    except (KeyError, ValueError):
        return None


def parse(page: str) -> list[Event]:
    soup = BeautifulSoup(page, "html.parser")
    out, seen = [], set()
    for card in soup.select(".card--upcoming"):
        href = card.get("href") or ""
        if not href:
            a = card.select_one("a[href^='/']")
            href = a.get("href", "") if a else ""
        label_el = card.select_one(".card__body [aria-label]")
        title_el = card.select_one(".card__body__title")
        if not href or not label_el or not title_el or href in seen:
            continue  # cards without a date are calls for proposals, not events
        seen.add(href)
        label = label_el.get("aria-label", "")
        place = label.split(",", 1)[1].strip() if "," in label else ""
        loc_el = card.select_one(".card__body__location")
        venue = loc_el.get_text(" ", strip=True) if loc_el else place
        host_el = card.select_one(".profile-avatar-title")
        low = place.lower()
        mode = "online" if low == "online" else "hybrid" if "hybrid" in low or "online" in low else "offline"
        out.append(Event(
            source="hasgeek",
            native_id=href.strip("/"),
            title=title_el.get_text(" ", strip=True),
            url="https://hasgeek.com" + href,
            start=parse_date_label(label),
            city=place,
            venue=venue,
            mode=mode,
            host=host_el.get_text(strip=True) if host_el else href.strip("/").split("/")[0],
            tech_source=True,
        ))
    return out


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    return parse(http.text(HOME))
