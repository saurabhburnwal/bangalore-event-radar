"""Telegram message text (HTML parse mode)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from html import escape

from .models import Event
from .score import CAT_AWAY, CAT_HACK, CAT_NET, CAT_OFFICE, CAT_ONLINE, CAT_OTHER, Verdict
from .util import fmt_dt, https_url, parse_dt

LABEL = {
    "luma": "Luma", "meetup": "Meetup", "unstop": "Unstop", "devfolio": "Devfolio",
    "gdg": "GDG", "hasgeek": "Hasgeek", "hackbriven": "Hackbriven",
}
CAT_ICON = {CAT_OFFICE: "🏢", CAT_HACK: "🏆", CAT_NET: "🤝", CAT_OTHER: "📌", CAT_AWAY: "🧳", CAT_ONLINE: "🌐"}
CAT_ORDER = (CAT_HACK, CAT_NET, CAT_OTHER, CAT_AWAY, CAT_ONLINE)  # office visits get their own section on top
LIMIT = 3900  # Telegram allows 4096 characters per message


@dataclass
class Page:
    text: str
    keys: list[str]


def _text(value: str, limit: int) -> str:
    return escape(value if len(value) <= limit else value[:limit - 1].rstrip() + "…")


def where(ev: Event) -> str:
    if ev.mode == "online":
        return "Online"
    venue = ev.venue.split(",")[0].strip() if ev.venue else ""
    parts = [p for p in [venue, ev.city] if p]
    if len(parts) == 2 and parts[1].lower() in parts[0].lower():
        parts = parts[:1]
    text = ", ".join(parts)
    return text + (" (hybrid)" if ev.mode == "hybrid" else "")


def when_label(ev: Event) -> str:
    """Compact date for lists: the start, else the application deadline, else the end."""
    if ev.start:
        return fmt_dt(ev.start)
    if ev.reg_deadline:
        return "apply by " + fmt_dt(ev.reg_deadline, show_midnight=True)
    return "ends " + fmt_dt(ev.end, False) if ev.end else ""


def alert(ev: Event, v: Verdict) -> str:
    if v.office:
        lines = [f"🏢 <b>OFFICE VISIT · {_text(v.office, 100)}</b>", f"<b>{_text(ev.title, 200)}</b>"]
    else:
        lines = [f"🔥 <b>{_text(ev.title, 200)}</b>"]
    info = []
    if ev.when:
        info.append(f"🗓 {fmt_dt(ev.start) or 'ends ' + fmt_dt(ev.end, False)}")
    if where(ev):
        info.append(f"📍 {_text(where(ev), 200)}")
    if info:
        lines.append("   ".join(info))
    if ev.reg_deadline:
        lines.append(f"⏳ Registration closes {fmt_dt(ev.reg_deadline, show_midnight=True)}")
    lines.append(f"💡 {_text(' · '.join(v.reasons), 400)}")
    if ev.rounds and ev.screening is not None:  # a real round list, not prose pulled from a description
        lines.append(f"🪜 {_text(ev.rounds, 200)}")
    lines.append(f"Source: {LABEL.get(ev.source, ev.source)}" + (f" · {_text(ev.host, 150)}" if ev.host else ""))
    return "\n".join(lines)


def correction(rec: dict) -> str:
    changes = rec["pending_correction"]
    lines = [f"📍 <b>Event update · {_text(rec['title'], 180)}</b>"]
    if changes.get("cancelled"):
        lines.append("The organizer has cancelled this event.")
    if "venue" in changes:
        old, new = changes["venue"]
        lines.append(f"Venue: {_text(old, 160)} → {_text(new, 160)}")
    if "deadline" in changes:
        old, new = [fmt_dt(parse_dt(t), show_midnight=True) for t in changes["deadline"]]
        lines.append(f"Registration now closes earlier: {old} → {new}")
    return "\n".join(lines)


def filling(ev: Event) -> str:
    left = f"only {ev.spots_left} spots left" if ev.spots_left else "almost full"
    return f"⚠️ <b>Filling fast:</b> {_text(ev.title, 200)}\n{left} · {fmt_dt(ev.start)}"


def _line(title: str, url: str, when: str, extra: str = "", source: str | None = None) -> str:
    safe_url = escape(https_url(url, source), quote=True)
    label = _text(title, 200)
    s = f"• <a href=\"{safe_url}\">{label}</a>" if safe_url and len(safe_url) <= 1000 else f"• {label}"
    if when:
        s += f" — {_text(when, 100)}"
    if extra:
        s += f"\n   <i>{_text(extra, 150)}</i>"
    return s


def bundle(items: list[tuple[Event, Verdict]], header: str) -> list[Page]:
    offices = [x for x in items if x[1].office]
    rest = [x for x in items if not x[1].office]
    lines = [(header, "")]
    for title, group in (("🏢 <b>Office visits</b>", offices), ("🔥 <b>Other high-priority</b>", rest)):
        if not group:
            continue
        lines.append(("", ""))
        if offices:
            lines.append((title, ""))
        for ev, v in group:
            extra = " · ".join(v.reasons + [where(ev), LABEL.get(ev.source, ev.source)])
            lines.append((_line(ev.title, ev.url, when_label(ev), extra.replace(" ·  ·", " ·"), ev.source), ev.id))
    return _pages(lines)


def source_down(name: str, runs: int, err: str) -> str:
    return (f"🛠 <b>Radar:</b> {LABEL.get(name, name)} has failed {runs} runs in a row, so its events "
            f"aren't being checked.\nLast error: <code>{escape(err[:300])}</code>")


def source_up(name: str) -> str:
    return f"✅ <b>Radar:</b> {LABEL.get(name, name)} is working again."


def digest(queue: list[dict], closing: list[dict], reminders: list[tuple[str, dict, date, int]], today: datetime,
           offices: list[dict]) -> list[Page]:
    count = f" · {len(queue)} new" if queue else ""
    lines = [(f"☀️ <b>Event digest — {fmt_dt(today, False)}</b>{count}", "")]
    if offices:
        lines += [("", ""), (f"{CAT_ICON[CAT_OFFICE]} <b>Office visits</b> — every upcoming one, until it happens", "")]
        for o in offices:
            extra = " · ".join(x for x in [o.get("why", ""), o.get("where", ""), LABEL.get(o["source"], o["source"])] if x)
            lines.append((_line(o["title"], o["url"], o.get("when_label") or "", extra, o["source"]), "office:" + o["id"]))
    for cat in CAT_ORDER:
        items = [q for q in queue if q.get("category") == cat]
        if not items:
            continue
        items.sort(key=lambda q: (-q.get("score", 0), _date_order(q.get("when"))))
        lines += [("", ""), (f"{CAT_ICON[cat]} <b>{cat}</b>", "")]
        for q in items:
            when = q.get("when_label") or fmt_dt(parse_dt(q.get("when")))
            extra = " · ".join(q.get("reasons", []) + [q.get("where", ""), LABEL.get(q["source"], q["source"])])
            line = _line(q["title"], q["url"], when, extra.replace(" ·  ·", " ·").strip(" ·"), q["source"])
            lines.append((line, "queue:" + q["id"]))
    if closing:
        lines += [("", ""), ("⏳ <b>Registration closing soon</b>", "")]
        for c in sorted(closing, key=lambda c: _date_order(c["reg_deadline"])):
            when = "closes " + fmt_dt(parse_dt(c["reg_deadline"]), show_midnight=True)
            line = _line(c["title"], c["url"], when, source=c["source"])
            lines.append((line, "closing:" + c["id"]))
    if reminders:
        lines += [("", ""), ("📅 <b>Coming up</b>", "")]
        for key, p, opens, days in reminders:
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            line = _line(p["name"], p["url"], f"usually opens around {opens.day} {opens:%b} ({when})", p.get("note", ""))
            lines.append((line, key))
    return _pages(lines)


def _date_order(value: str | None) -> float:
    dt = parse_dt(value)
    return dt.timestamp() if dt else float("inf")


def _is_header(line: str) -> bool:
    return line.strip() == "" or (line.startswith(tuple(CAT_ICON.values()) + ("⏳", "📅", "🔥")) and "<b>" in line)


def split(lines: list[str]) -> list[str]:
    return [page.text for page in _pages([(line, "") for line in lines])]


def _pages(lines: list[tuple[str, str]]) -> list[Page]:
    """Paginate bounded rows, retaining the IDs delivered by each message."""
    out: list[Page] = []
    cur: list[tuple[str, str]] = []
    for line, key in lines:
        if cur and sum(len(text) + 1 for text, _ in cur) + len(line) + 1 > LIMIT:
            carry = []
            while len(cur) > 1 and _is_header(cur[-1][0]):
                carry.insert(0, cur.pop())
            out.append(Page("\n".join(text for text, _ in cur).rstrip(), [key for _, key in cur if key]))
            cur = [(text, key) for text, key in carry if text.strip()]
        cur.append((line, key))
    if any(text.strip() for text, _ in cur):
        out.append(Page("\n".join(text for text, _ in cur).rstrip(), [key for _, key in cur if key]))
    return out
