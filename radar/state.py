"""Persistent state, committed to the repo by the workflow after each run.

Delivery checkpoints and poll telemetry are saved together after each scheduled cycle.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from .models import Event
from .util import IST, to_iso

_STOP = {"bengaluru", "bangalore", "blr", "the", "a", "an", "in", "at", "and", "x", "of", "for", "with"}


def empty() -> dict:
    return {
        "version": 1,
        "initialized": False,
        "events": {},     # id -> record
        "fps": {},        # fingerprint -> id, to spot the same event listed on two sites
        "queue": [],      # digest entries waiting for the next digest
        "sources": {},    # name -> {"fails": n, "warned": bool, "last_error": str}
        "cache": {},      # per-source detail-page cache (Devfolio city, GDG venue)
        "reminders": {},  # annual-program reminder keys already sent
        "digest_delivery": {},  # same-day office and deadline rows already delivered
    }


def load(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return empty()
    base = empty()
    base.update(data)
    return base


def dumps(state: dict) -> str:
    return json.dumps(state, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def save(path: Path, state: dict) -> bool:
    """Write state if it changed. Returns True when the file was written."""
    new = dumps(state)
    try:
        if path.read_text(encoding="utf-8") == new:
            return False
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    f = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False)
    temp = Path(f.name)
    try:
        with f:
            f.write(new)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return True


# Words too common to tell two events apart on their own.
_GENERIC = {
    "ai", "hackathon", "hackathons", "buildathon", "meetup", "build", "builders", "day", "summit",
    "conference", "workshop", "community", "hack", "tech", "india", "national", "edition", "season",
    "voice", "agentic", "agents", "genai", "challenge", "event", "series", "session", "2", "0",
}


def _day(dt) -> str:
    return dt.astimezone(IST).date().isoformat() if dt else ""


def tokens(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", title.lower())
            if w not in _STOP and not re.fullmatch(r"(19|20)\d\d", w)}


def fingerprint(ev: Event) -> str:
    words = re.findall(r"[a-z0-9]+", ev.title.lower())
    key = " ".join(w for w in words if w not in _STOP)
    return f"{key}|{_day(ev.when)}"


def similar_titles(a: str, b: str) -> bool:
    """True when two titles plausibly name the same event, e.g.
    'Build with Agora - BLR' and 'Build with Agora - Bengaluru 2026 | Voice AI Hackathon'."""
    A, B = tokens(a), tokens(b)
    if not A or not B:
        return False
    small, big = sorted((A, B), key=len)
    if small <= big and small - _GENERIC:
        return True
    return len(A & B) / len(A | B) >= 0.6 and bool((A & B) - _GENERIC)


def same_event(ev: Event, title: str, source: str, when) -> bool:
    """Cross-site duplicate check. A site never lists the same event twice, so same-source pairs never match."""
    return ev.source != source and _day(ev.when) == _day(when) and _day(when) != "" and similar_titles(ev.title, title)


def absorb(primary: Event, dup: Event) -> None:
    """Fill gaps in the event we keep with details only the duplicate listing has."""
    primary.prize_inr = max(primary.prize_inr, dup.prize_inr)
    primary.ppi = primary.ppi or dup.ppi
    if dup.perks and dup.perks not in primary.perks:
        primary.perks = " / ".join(x for x in [primary.perks, dup.perks] if x)
    for f in ("reg_deadline", "spots_left", "venue", "city", "org", "description", "rounds"):
        if not getattr(primary, f) and getattr(dup, f):
            setattr(primary, f, getattr(dup, f))
    if primary.team_min is None and dup.team_min is not None:
        primary.team_min, primary.team_max = dup.team_min, dup.team_max
    if primary.screening is None:
        primary.screening = dup.screening
    if dup.kind == "hackathon":
        primary.kind = "hackathon"
    primary.near_capacity = primary.near_capacity or dup.near_capacity
    listings = primary.extra.setdefault("listing_ids", [])
    if dup.id not in listings:
        listings.append(dup.id)


def new_record(ev: Event, today: str) -> dict:
    rec = {"first_seen": today, "alerted": False, "filling_alerted": False, "queued": False}
    refresh(rec, ev, today)
    return rec


def refresh(rec: dict, ev: Event, today: str) -> None:
    rec["listing_ids"] = sorted({*rec.get("listing_ids", []), ev.id, *ev.extra.get("listing_ids", [])})
    rec.update({
        "title": ev.title,
        "url": ev.url,
        "source": ev.source,
        "start": to_iso(ev.start),
        "end": to_iso(ev.end),
        "reg_deadline": to_iso(ev.reg_deadline),
        "last_seen": today,
    })
