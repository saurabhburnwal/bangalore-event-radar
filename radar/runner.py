"""The two jobs: poll (every 10 minutes) and digest (daily)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import messages
from . import state as st
from .models import Event
from .score import DIGEST, HIGH, IGNORE, Scorer, Verdict
from .sources import MAY_BE_EMPTY, SOURCES
from .util import IST, parse_dt, to_iso


@dataclass
class PollReport:
    scored: list[tuple[Event, Verdict]] = field(default_factory=list)
    alerted: list[str] = field(default_factory=list)
    filling: list[str] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first_run: bool = False


def _entry(ev: Event, v: Verdict) -> dict:
    return {
        "id": ev.id, "title": ev.title, "url": ev.url, "source": ev.source,
        "when": to_iso(ev.when), "when_label": messages.when_label(ev), "where": messages.where(ev), "reasons": v.reasons,
        "category": v.category, "score": round(v.score, 1),
    }


def _send(notifier, report: PollReport, text: str, url: str | None = None) -> bool:
    try:
        notifier.send(text, url)
        return True
    except Exception as e:  # noqa: BLE001 - record and keep going; unsent alerts retry next run
        report.errors.append(str(e))
        return False


def _health(results: dict, state: dict, cfg: dict, notifier, report: PollReport) -> None:
    limit = (cfg.get("alerts") or {}).get("source_fail_runs", 6)
    for name, res in results.items():
        h = state["sources"].setdefault(name, {"fails": 0, "warned": False})
        if isinstance(res, Exception):
            err = f"{type(res).__name__}: {res}"
        elif not res and name not in MAY_BE_EMPTY:
            err = "returned no events"
        else:
            if h.get("warned"):
                _send(notifier, report, messages.source_up(name))
            state["sources"][name] = {"fails": 0, "warned": False}
            continue
        h["fails"] = h.get("fails", 0) + 1
        h["last_error"] = err[:300]
        if h["fails"] >= limit and not h.get("warned"):
            if _send(notifier, report, messages.source_down(name, h["fails"], err)):
                h["warned"] = True


def _merge(results: dict) -> list[Event]:
    """Flatten results in source order, dropping repeats of the same event across sites."""
    out: list[Event] = []
    ids: set[str] = set()
    by_fp: dict[str, Event] = {}
    for name in SOURCES:
        res = results.get(name)
        if not isinstance(res, list):
            continue
        for ev in res:
            if ev.id in ids:
                continue
            fp = st.fingerprint(ev)
            twin = by_fp.get(fp) if by_fp.get(fp) and by_fp[fp].source != ev.source else None
            twin = twin or next((k for k in out if st.same_event(ev, k.title, k.source, k.when)), None)
            if twin:
                st.absorb(twin, ev)
                continue
            ids.add(ev.id)
            by_fp[fp] = ev
            out.append(ev)
    return out


def _known(state: dict, ev: Event, fp: str) -> str:
    """The state id this event is stored under: exact fingerprint, then a fuzzy cross-site match, else its own id."""
    if ev.id in state["events"]:
        return ev.id
    rid = state["fps"].get(fp)
    if rid in state["events"]:
        return rid
    for rid, rec in state["events"].items():
        if st.same_event(ev, rec["title"], rec["source"], parse_dt(rec.get("start") or rec.get("end"))):
            return rid
    return ev.id


def _prune(state: dict, now: datetime) -> None:
    cutoff = now - timedelta(days=7)
    stale_day = (now.astimezone(IST).date() - timedelta(days=30)).isoformat()
    for eid in list(state["events"]):
        rec = state["events"][eid]
        when = parse_dt(rec.get("end") or rec.get("start"))
        if (when and when < cutoff) or (not when and rec.get("last_seen", "") < stale_day):
            del state["events"][eid]
    state["fps"] = {fp: eid for fp, eid in state["fps"].items() if eid in state["events"]}


def poll(results: dict, state: dict, cfg: dict, notifier, now: datetime) -> PollReport:
    report = PollReport(first_run=not state.get("initialized"))
    scorer = Scorer(cfg)
    today = now.astimezone(IST).date().isoformat()
    max_instant = (cfg.get("alerts") or {}).get("max_instant_per_run", 8)

    _health(results, state, cfg, notifier, report)

    new_high: list[tuple[Event, Verdict, dict]] = []
    newly_filling: list[tuple[Event, Verdict, dict]] = []
    for ev in _merge(results):
        v = scorer(ev)
        report.scored.append((ev, v))
        if v.tier == IGNORE:
            continue
        fp = st.fingerprint(ev)
        rid = _known(state, ev, fp)
        rec = state["events"].get(rid)
        if rec is None:
            rec = state["events"][rid] = st.new_record(ev, today)
            state["fps"][fp] = rid
        else:
            st.refresh(rec, ev, today)
            state["fps"].setdefault(fp, rid)

        if v.tier == HIGH and not rec["alerted"]:
            new_high.append((ev, v, rec))
        elif rec["alerted"] and v.filling and not rec["filling_alerted"]:
            newly_filling.append((ev, v, rec))
        elif v.tier == DIGEST and not rec["queued"] and not rec["alerted"]:
            rec["queued"] = True
            state["queue"].append(_entry(ev, v))
            report.queued.append(ev.title)

    new_high.sort(key=lambda x: -x[1].score)
    if report.first_run:
        # Seed silently, then send one summary of what's open right now instead of a flood.
        items = [(ev, v) for ev, v, _ in new_high]
        texts = messages.bundle(items, f"📡 <b>Event radar is live.</b> {len(items)} high-priority events are open right now:") \
            if items else ["📡 <b>Event radar is live.</b> Nothing high-priority is open right now; you'll hear the moment something is."]
        if all(_send(notifier, report, t) for t in texts):
            for ev, v, rec in new_high:
                rec["alerted"] = True
                rec["filling_alerted"] = v.filling
                report.alerted.append(ev.title)
            state["initialized"] = True
    elif len(new_high) > max_instant:
        items = [(ev, v) for ev, v, _ in new_high]
        texts = messages.bundle(items, f"🔥 <b>{len(items)} new high-priority events</b>")
        if all(_send(notifier, report, t) for t in texts):
            for ev, v, rec in new_high:
                rec["alerted"] = True
                rec["filling_alerted"] = v.filling
                report.alerted.append(ev.title)
    else:
        for ev, v, rec in new_high:
            if _send(notifier, report, messages.alert(ev, v), ev.url):
                rec["alerted"] = True
                rec["filling_alerted"] = v.filling
                report.alerted.append(ev.title)

    for ev, v, rec in newly_filling:
        if _send(notifier, report, messages.filling(ev), ev.url):
            rec["filling_alerted"] = True
            report.filling.append(ev.title)

    alerted_ids = {rid for rid, rec in state["events"].items() if rec["alerted"]}
    state["queue"] = [q for q in state["queue"] if q["id"] not in alerted_ids]
    _prune(state, now)
    return report


def _due_reminders(cfg: dict, state: dict, today: date) -> tuple[list[tuple[dict, date, int]], list[str]]:
    due, keys = [], []
    for p in cfg.get("annual_programs") or []:
        try:
            mm, dd = (int(x) for x in str(p["opens"]).split("-"))
            opens = date(today.year, mm, dd)
        except (KeyError, ValueError):
            continue
        if opens < today:
            opens = date(today.year + 1, mm, dd)
        days = (opens - today).days
        pending = [f"{p['name']}|{opens.year}|{t}" for t in (14, 3) if days <= t]
        pending = [k for k in pending if k not in state["reminders"]]
        if pending:
            due.append((p, opens, days))
            keys += pending
    return due, keys


def digest(state: dict, cfg: dict, notifier, now: datetime) -> list[str]:
    """Send the daily digest. Returns the messages sent (empty when there was nothing to say)."""
    window = timedelta(hours=(cfg.get("scoring") or {}).get("closing_soon_hours", 72))
    queue = [q for q in state["queue"] if not q.get("when") or parse_dt(q["when"]) > now]
    closing = [
        {"title": r["title"], "url": r["url"], "reg_deadline": r["reg_deadline"]}
        for r in state["events"].values()
        if (r.get("alerted") or r.get("queued")) and r.get("reg_deadline")
        and now < parse_dt(r["reg_deadline"]) <= now + window
    ]
    today = now.astimezone(IST).date()
    reminders, keys = _due_reminders(cfg, state, today)
    if not (queue or closing or reminders):
        state["queue"] = []
        return []
    texts = messages.digest(queue, closing, reminders, now.astimezone(IST))
    for t in texts:
        notifier.send(t)
    state["queue"] = []
    for k in keys:
        state["reminders"][k] = today.isoformat()
    state["reminders"] = {k: v for k, v in state["reminders"].items() if int(k.rsplit("|", 2)[1]) >= today.year}
    return texts
