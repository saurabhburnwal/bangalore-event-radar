"""The two jobs: poll (every 10 minutes) and digest (daily)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import health, messages
from . import state as st
from .models import Event
from .score import DIGEST, HIGH, IGNORE, Scorer, Verdict
from .sources import SOURCES
from .util import IST, https_url, parse_dt, to_iso


@dataclass
class PollReport:
    scored: list[tuple[Event, Verdict]] = field(default_factory=list)
    alerted: list[str] = field(default_factory=list)
    filling: list[str] = field(default_factory=list)
    queued: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    first_run: bool = False


def _entry(ev: Event, v: Verdict, rid: str) -> dict:
    return {
        "id": rid, "title": ev.title, "url": ev.url, "source": ev.source,
        "when": to_iso(ev.when), "reg_deadline": to_iso(ev.reg_deadline),
        "when_label": messages.when_label(ev), "where": messages.where(ev), "reasons": v.reasons,
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
    failed = 0
    for name, res in results.items():
        h = state["sources"].setdefault(name, {"fails": 0, "warned": False})
        status, err = health.source_status(name, res)
        if status != "failed":
            still_warned = h.get("warned", False) and not _send(notifier, report, messages.source_up(name))
            state["sources"][name] = {"fails": 0, "warned": still_warned}
            continue
        failed += 1
        h["fails"] = h.get("fails", 0) + 1
        h["last_error"] = err[:300]
        if h["fails"] >= limit and not h.get("warned"):
            if _send(notifier, report, messages.source_down(name, h["fails"], err)):
                h["warned"] = True
    if failed == len(results):
        report.errors.append("all enabled event sources failed")


def _merge(results: dict, state: dict) -> list[Event]:
    """Flatten results in source order, dropping repeats of the same event across sites."""
    out: list[Event] = []
    ids: set[str] = set()
    by_fp: dict[str, Event] = {}
    by_record: dict[str, Event] = {}
    listings = {listing: rid for rid, rec in state["events"].items()
                for listing in (rid, *rec.get("listing_ids", []))}
    for name in SOURCES:
        res = results.get(name)
        if not isinstance(res, list):
            continue
        for ev in res:
            if ev.id in ids:
                continue
            ids.add(ev.id)
            fp = st.fingerprint(ev)
            rid = listings.get(ev.id)
            twin = by_record.get(rid) if rid else None
            exact = by_fp.get(fp) if ev.when else None
            if twin is None and exact and _different_listing_source(ev, exact.id, exact.extra.get("listing_ids", [])):
                twin = exact
            twin = twin or next((k for k in out if _different_listing_source(ev, k.id, k.extra.get("listing_ids", []))
                                 and st.same_event(ev, k.title, k.source, k.when)), None)
            if rid:
                by_record[rid] = twin or ev
            if twin:
                st.absorb(twin, ev)
                continue
            by_fp[fp] = ev
            out.append(ev)
    return out


def _different_listing_source(ev: Event, rid: str, aliases: list[str]) -> bool:
    prefix = ev.source + ":"
    return not any(key.startswith(prefix) for key in (rid, *aliases))


def _known(state: dict, ev: Event, fp: str) -> str:
    """The state id this event is stored under: exact fingerprint, then a fuzzy cross-site match, else its own id."""
    if ev.id in state["events"]:
        return ev.id
    ids = {ev.id, *ev.extra.get("listing_ids", [])}
    for rid, rec in state["events"].items():
        if rid in ids or ids.intersection(rec.get("listing_ids", [])):
            return rid
    rid = state["fps"].get(fp)
    if ev.when and rid in state["events"] and _different_listing_source(ev, rid, state["events"][rid].get("listing_ids", [])):
        return rid
    for rid, rec in state["events"].items():
        if (_different_listing_source(ev, rid, rec.get("listing_ids", []))
                and st.same_event(ev, rec["title"], rec["source"], parse_dt(rec.get("start") or rec.get("end")))):
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


def _expired(now: datetime, *dates: datetime | None) -> bool:
    return any(dt is not None and dt <= now for dt in dates)


def poll(results: dict, state: dict, cfg: dict, notifier, now: datetime, checkpoint=None) -> PollReport:
    report = PollReport(first_run=not state.get("initialized"))
    scorer = Scorer(cfg)
    today = now.astimezone(IST).date().isoformat()
    max_instant = (cfg.get("alerts") or {}).get("max_instant_per_run", 8)

    health.record(state.setdefault("health", {}), results, now)
    _health(results, state, cfg, notifier, report)
    pending = {q["id"]: q for q in state["queue"]}

    new_high: list[tuple[Event, Verdict, str]] = []
    newly_filling: list[tuple[Event, str]] = []
    for ev in _merge(results, state):
        fp = st.fingerprint(ev)
        rid = _known(state, ev, fp)
        rec = state["events"].get(rid)
        for listing in (ev.id, *ev.extra.get("listing_ids", [])):
            if listing != rid and listing in pending:
                pending.setdefault(rid, {**pending.pop(listing), "id": rid})
        expired = _expired(now, ev.end or ev.start, ev.reg_deadline)
        v = scorer(ev)
        excluded = v.tier == IGNORE
        if expired and not excluded:
            v = Verdict(IGNORE, ["event ended or registration closed"])
        report.scored.append((ev, v))
        if v.tier == IGNORE:
            withdrawn = pending.pop(rid, None)
            if rec is not None:
                st.refresh(rec, ev, today)
                if withdrawn:
                    rec["queued"] = False
                if excluded:
                    rec["dropped"] = True
                    rec.pop("office", None)
            continue
        if rec is None:
            rec = state["events"][rid] = st.new_record(ev, today)
            state["fps"][fp] = rid
        else:
            st.refresh(rec, ev, today)
            state["fps"].setdefault(fp, rid)
            rec.pop("dropped", None)
        if v.office:
            rec["office"] = {"why": v.reasons[0], "where": messages.where(ev), "when_label": messages.when_label(ev)}
        else:
            rec.pop("office", None)

        if v.tier == HIGH and not rec["alerted"]:
            new_high.append((ev, v, rid))
        elif rec["alerted"] and v.filling and not rec["filling_alerted"]:
            newly_filling.append((ev, rid))
        elif v.tier == DIGEST and not rec["queued"] and not rec["alerted"]:
            rec["queued"] = True
            pending[rid] = _entry(ev, v, rid)
            report.queued.append(ev.title)
        elif v.tier == DIGEST and rid in pending:
            pending[rid] = _entry(ev, v, rid)

    state["queue"] = list(pending.values())
    new_high.sort(key=lambda x: -x[1].score)

    def mark_alerted(ev, verdict, rid):
        state["events"][rid].update(alerted=True, filling_alerted=verdict.filling)
        pending.pop(rid, None)
        report.alerted.append(ev.title)

    def save_deliveries():
        state["queue"] = list(pending.values())
        if checkpoint:
            checkpoint()

    if (report.first_run and not report.errors) or len(new_high) > max_instant:
        by_id = {ev.id: (ev, v, rid) for ev, v, rid in new_high}
        if report.first_run:
            available = (f"{len(new_high)} high-priority events are open right now:" if new_high
                         else "Nothing high-priority is open right now.")
            header = f"📡 <b>Event radar is live.</b> {available}"
        else:
            header = f"🔥 <b>{len(new_high)} new high-priority events</b>"
        pages = messages.bundle([(ev, v) for ev, v, _ in new_high], header)
        for index, page in enumerate(pages):
            if not _send(notifier, report, page.text):
                break
            for key in page.keys:
                mark_alerted(*by_id[key])
            if index == len(pages) - 1:
                state["initialized"] = True
            save_deliveries()
    else:
        for ev, v, rid in new_high:
            if _send(notifier, report, messages.alert(ev, v), https_url(ev.url, ev.source)):
                mark_alerted(ev, v, rid)
                save_deliveries()

    for ev, rid in newly_filling:
        if _send(notifier, report, messages.filling(ev), https_url(ev.url, ev.source)):
            state["events"][rid]["filling_alerted"] = True
            report.filling.append(ev.title)
            save_deliveries()

    state["queue"] = [q for rid, q in pending.items()
                      if not state["events"].get(rid, {}).get("alerted") and not state["events"].get(rid, {}).get("dropped")]
    _prune(state, now)
    return report


def _next_open(month: int, day: int, today: date) -> date | None:
    for year in range(today.year, min(today.year + 9, 10000)):
        try:
            opens = date(year, month, day)
        except ValueError:
            if (month, day) != (2, 29):
                return None
            continue
        if opens >= today:
            return opens
    return None


def _due_reminders(cfg: dict, state: dict, today: date) -> tuple[list[tuple[str, dict, date, int]], dict[str, list[str]]]:
    due, keys = [], {}
    for p in cfg.get("annual_programs") or []:
        try:
            mm, dd = (int(x) for x in str(p["opens"]).split("-"))
            name = p["name"]
        except (KeyError, TypeError, ValueError):
            continue
        opens = _next_open(mm, dd, today)
        if opens is None:
            continue
        days = (opens - today).days
        pending = [f"{name}|{opens.year}|{t}" for t in (14, 3) if days <= t]
        pending = [k for k in pending if k not in state["reminders"]]
        if pending:
            key = f"reminder:{name}|{opens.isoformat()}"
            due.append((key, p, opens, days))
            keys[key] = pending
    return due, keys


def _upcoming_offices(state: dict, now: datetime) -> list[dict]:
    """Office-visit events already alerted that haven't started yet, soonest first, for the top of every digest."""
    out = []
    for rid, rec in state["events"].items():
        when = parse_dt(rec.get("start") or rec.get("end"))
        if not rec.get("dropped") and rec.get("office") and rec.get("alerted") and (when is None or when > now):
            out.append({"id": rid, "title": rec["title"], "url": rec["url"], "source": rec["source"], "when": to_iso(when),
                        **rec["office"]})
    return sorted(out, key=lambda o: parse_dt(o["when"]) or datetime.max.replace(tzinfo=IST))


def digest(state: dict, cfg: dict, notifier, now: datetime, checkpoint=None) -> list[str]:
    """Send the daily digest. Returns the messages sent (empty when there was nothing to say)."""
    window = timedelta(hours=(cfg.get("scoring") or {}).get("closing_soon_hours", 72))
    queue = {}
    for q in state["queue"]:
        rec = state["events"].get(q["id"], {})
        if rec.get("dropped") or rec.get("alerted"):
            continue
        when = parse_dt(rec.get("end") or rec.get("start") or q.get("when"))
        deadline = parse_dt(rec.get("reg_deadline", q.get("reg_deadline")))
        if not _expired(now, when, deadline):
            queue[q["id"]] = q
        elif rec:
            rec["queued"] = False
    state["queue"] = list(queue.values())
    today = now.astimezone(IST).date()
    day = today.isoformat()
    delivery = state.get("digest_delivery", {})
    delivered = set(delivery.get("keys", [])) if delivery.get("day") == day else set()
    closing = [
        {"id": rid, "title": r["title"], "url": r["url"], "source": r["source"], "reg_deadline": r["reg_deadline"]}
        for rid, r in state["events"].items()
        if "closing:" + rid not in delivered and (r.get("alerted") or r.get("queued")) and not r.get("dropped")
        and not _expired(now, parse_dt(r.get("end") or r.get("start")))
        and (deadline := parse_dt(r.get("reg_deadline"))) is not None and now < deadline <= now + window
    ]
    reminders, keys = _due_reminders(cfg, state, today)
    offices = [o for o in _upcoming_offices(state, now) if "office:" + o["id"] not in delivered]
    if not (queue or closing or reminders or offices):
        return []
    sent = []
    pages = messages.digest(list(queue.values()), closing, reminders, now.astimezone(IST), offices)
    for index, page in enumerate(pages):
        notifier.send(page.text)
        sent.append(page.text)
        for key in page.keys:
            if key.startswith("queue:"):
                queue.pop(key.removeprefix("queue:"), None)
            elif key in keys:
                state["reminders"].update(dict.fromkeys(keys[key], day))
            else:
                delivered.add(key)
        state["queue"] = list(queue.values())
        state["digest_delivery"] = {"day": day, "keys": sorted(delivered)} if delivered else {}
        if index == len(pages) - 1:
            state["last_digest_day"] = day
        if checkpoint:
            checkpoint()
    state["reminders"] = {k: v for k, v in state["reminders"].items()
                          if len(parts := k.rsplit("|", 2)) == 3 and parts[1] >= f"{today.year:04}"}
    return sent
