from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def next_data(page: str) -> dict:
    """Return the JSON a Next.js page embeds in its __NEXT_DATA__ script tag."""
    m = _NEXT_DATA.search(page)
    if not m:
        raise ValueError("page has no __NEXT_DATA__ block (layout changed?)")
    return json.loads(m.group(1))


def html_to_text(s: str | None, limit: int = 1500) -> str:
    if not s:
        return ""
    s = _TAGS.sub(" ", s)
    s = _WS.sub(" ", html.unescape(s)).strip()
    return s[:limit]


def parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are taken as IST."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def fmt_dt(dt: datetime | None, with_time: bool = True) -> str:
    if not dt:
        return ""
    d = dt.astimezone(IST)
    day = f"{d:%a} {d.day} {d:%b}"
    if not with_time or (d.hour == 0 and d.minute == 0):
        return day
    return f"{day} · {d:%H:%M} IST"


def to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def inr(n: int) -> str:
    """Format rupees the Indian way: 250000 -> ₹2,50,000."""
    s = str(int(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"₹{s}"
