"""Telegram message text (HTML parse mode)."""
from __future__ import annotations

from datetime import date, datetime
from html import escape

from .models import Event
from .score import CAT_HACK, CAT_NET, CAT_ONLINE, CAT_OTHER, Verdict
from .util import fmt_dt, parse_dt

LABEL = {
    "luma": "Luma", "meetup": "Meetup", "unstop": "Unstop", "devfolio": "Devfolio",
    "gdg": "GDG", "hasgeek": "Hasgeek", "hackbriven": "Hackbriven",
}
CAT_ICON = {CAT_HACK: "🏆", CAT_NET: "🤝", CAT_OTHER: "📌", CAT_ONLINE: "🌐"}
CAT_ORDER = (CAT_HACK, CAT_NET, CAT_OTHER, CAT_ONLINE)
LIMIT = 3900  # Telegram allows 4096 characters per message


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
        return "apply by " + fmt_dt(ev.reg_deadline, False)
    return "ends " + fmt_dt(ev.end, False) if ev.end else ""


def alert(ev: Event, v: Verdict) -> str:
    lines = [f"🔥 <b>{escape(ev.title)}</b>"]
    info = []
    if ev.when:
        info.append(f"🗓 {fmt_dt(ev.start) or 'ends ' + fmt_dt(ev.end, False)}")
    if where(ev):
        info.append(f"📍 {escape(where(ev))}")
    if info:
        lines.append("   ".join(info))
    if ev.reg_deadline:
        lines.append(f"⏳ Registration closes {fmt_dt(ev.reg_deadline)}")
    lines.append(f"💡 {escape(' · '.join(v.reasons))}")
    lines.append(f"Source: {LABEL.get(ev.source, ev.source)}" + (f" · {escape(ev.host)}" if ev.host else ""))
    return "\n".join(lines)


def filling(ev: Event) -> str:
    left = f"only {ev.spots_left} spots left" if ev.spots_left else "almost full"
    return f"⚠️ <b>Filling fast:</b> {escape(ev.title)}\n{left} · {fmt_dt(ev.start)}"


def _line(title: str, url: str, when: str, extra: str = "") -> str:
    s = f"• <a href=\"{escape(url, quote=True)}\">{escape(title)}</a>"
    if when:
        s += f" — {when}"
    if extra:
        s += f"\n   <i>{escape(extra)}</i>"
    return s


def bundle(items: list[tuple[Event, Verdict]], header: str) -> list[str]:
    lines = [header, ""]
    for ev, v in items:
        extra = " · ".join(v.reasons + [where(ev), LABEL.get(ev.source, ev.source)])
        lines.append(_line(ev.title, ev.url, when_label(ev), extra.replace(" ·  ·", " ·")))
    return split(lines)


def source_down(name: str, runs: int, err: str) -> str:
    return (f"🛠 <b>Radar:</b> {LABEL.get(name, name)} has failed {runs} runs in a row, so its events "
            f"aren't being checked.\nLast error: <code>{escape(err[:300])}</code>")


def source_up(name: str) -> str:
    return f"✅ <b>Radar:</b> {LABEL.get(name, name)} is working again."


def digest(queue: list[dict], closing: list[dict], reminders: list[tuple[dict, date, int]], today: datetime) -> list[str]:
    lines = [f"☀️ <b>Event digest — {fmt_dt(today, False)}</b>"]
    if queue:
        lines[0] += f" · {len(queue)} new"
    for cat in CAT_ORDER:
        items = [q for q in queue if q.get("category") == cat]
        if not items:
            continue
        items.sort(key=lambda q: (-q.get("score", 0), q.get("when") or "9999"))
        lines += ["", f"{CAT_ICON[cat]} <b>{cat}</b>"]
        for q in items:
            when = q.get("when_label") or fmt_dt(parse_dt(q.get("when")))
            extra = " · ".join(q.get("reasons", []) + [q.get("where", ""), LABEL.get(q["source"], q["source"])])
            lines.append(_line(q["title"], q["url"], when, extra.replace(" ·  ·", " ·").strip(" ·")))
    if closing:
        lines += ["", "⏳ <b>Registration closing soon</b>"]
        for c in sorted(closing, key=lambda c: c["reg_deadline"]):
            lines.append(_line(c["title"], c["url"], "closes " + fmt_dt(parse_dt(c["reg_deadline"]))))
    if reminders:
        lines += ["", "📅 <b>Coming up</b>"]
        for p, opens, days in reminders:
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            lines.append(_line(p["name"], p["url"], f"usually opens around {opens.day} {opens:%b} ({when})", p.get("note", "")))
    return split(lines)


def split(lines: list[str]) -> list[str]:
    """Join lines into messages that each fit Telegram's size limit."""
    out, cur = [], ""
    for line in lines:
        if cur and len(cur) + len(line) + 1 > LIMIT:
            out.append(cur.rstrip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur.rstrip())
    return out
