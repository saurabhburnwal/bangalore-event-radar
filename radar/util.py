from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

IST = timezone(timedelta(hours=5, minutes=30))

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_DOMAINS = {
    "luma": {"api.lu.ma", "lu.ma", "luma.com", "www.luma.com"},
    "unstop": {"unstop.com", "www.unstop.com"},
    "devfolio": {"devfolio.co", "www.devfolio.co"},
    "meetup": {"meetup.com", "www.meetup.com"},
    "gdg": {"gdg.community.dev"},
    "hackbriven": {"hackbriven.com", "www.hackbriven.com"},
    "hasgeek": {"hasgeek.com", "www.hasgeek.com"},
}


def https_url(url: str, source: str | None = None) -> str:
    """Return an HTTPS URL suitable for a source request or registration link."""
    if not isinstance(url, str) or len(url) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", url):
        return ""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme != "https" or not host or parts.username is not None or parts.port not in (None, 443):
            return ""
    except ValueError:
        return ""
    if source is not None and host not in _DOMAINS.get(source, ()):
        if source != "devfolio" or not re.fullmatch(r"[a-z0-9-]+\.devfolio\.co", host):
            return ""
    return url


def next_data(page: str) -> dict:
    """Return the JSON a Next.js page embeds in its __NEXT_DATA__ script tag."""
    m = _NEXT_DATA.search(page)
    if not m:
        raise ValueError("page has no __NEXT_DATA__ block (layout changed?)")
    return json.loads(m.group(1))


def html_to_text(s: str | None, limit: int = 1500) -> str:
    if not isinstance(s, str) or not s:
        return ""
    s = _TAGS.sub(" ", s)
    s = _WS.sub(" ", html.unescape(s)).strip()
    return s[:limit]


def parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive values are taken as IST."""
    if not isinstance(s, str) or not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=IST)


def parse_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = int(value)
    except (ValueError, OverflowError):
        return None
    return number if -(2**63) <= number < 2**63 else None


def fmt_dt(dt: datetime | None, with_time: bool = True, *, show_midnight: bool = False) -> str:
    if not dt:
        return ""
    d = dt.astimezone(IST)
    day = f"{d:%a} {d.day} {d:%b}"
    if not with_time or (not show_midnight and d.hour == 0 and d.minute == 0):
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
