"""Unstop: public opportunity search API, open hackathons only, plus each in-person event's round list (cached)."""
from __future__ import annotations

from ..eligibility import Round, has_screening, round_sentences, summary
from ..corrections import confirmed_cancellation
from ..models import Event
from .batch import ListingBatch, listing_rows
from ..util import html_to_text, parse_dt, parse_int

API = "https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&oppstatus=open&per_page=30&page={page}"
DETAIL = "https://unstop.com/api/public/competition/{id}"
DETAIL_CACHE_VERSION = 1


def _prize(prizes: list, usd_inr: float) -> tuple[int, bool, str]:
    total, ppi, perks = 0, False, []
    for p in prizes or []:
        if not isinstance(p, dict):
            continue
        raw_cash = p.get("cash")
        cash = parse_int(raw_cash)
        if cash is not None and isinstance(raw_cash, float):
            cash = raw_cash
        if cash is not None and cash > 0:
            rate = usd_inr if "dollar" in str(p.get("currency") or "").lower() else 1
            total += int(cash * rate)
        if p.get("pre_placement_internship") or p.get("pre_placement_opportunity"):
            ppi = True
        if p.get("others"):
            perks.append(str(p["others"]).strip())
    return total, ppi, " / ".join(dict.fromkeys(perks))[:400]


def parse(data: dict, usd_inr: float = 88) -> tuple[list[Event], int]:
    """Return (events, last_page)."""
    d = data["data"]
    out = []
    for o in listing_rows(d, "data"):
        addr = o.get("address_with_country_logo") or {}
        regn = o.get("regnRequirements") or {}
        prize, ppi, perks = _prize(o.get("prizes"), usd_inr)
        region = (o.get("region") or "online").lower()
        full = html_to_text(o.get("details"), 20000)
        out.append(Event(
            cancelled=confirmed_cancellation(o),
            source="unstop",
            native_id=str(o["id"]),
            title=(o.get("title") or "").strip(),
            url=o.get("seo_url") or f"https://unstop.com/{o.get('public_url', '')}",
            end=parse_dt(o.get("end_date")),
            city=addr.get("city") or "",
            venue=addr.get("address") or "",
            mode=region if region in ("online", "offline", "hybrid") else "online",
            host=(o.get("organisation") or {}).get("name") or "",
            org=(o.get("organisation") or {}).get("name") or "",
            description=full[:1500],
            rounds=round_sentences(full),  # the round plan in prose; replaced by the real round list when there is one
            kind="hackathon",
            tech_source=True,
            prize_inr=prize,
            ppi=ppi,
            prize_data=True,
            perks=perks,
            reg_deadline=parse_dt(regn.get("end_regn_dt")),
            team_min=parse_int(regn.get("min_team_size")),
            team_max=parse_int(regn.get("max_team_size")),
            extra={"registered": o.get("registerCount"), "updated": o.get("updated_at")},
        ))
    return out, int(d.get("last_page") or 1)


def _round(r: dict) -> Round | None:
    if (r.get("subtype") or "").lower() == "screening":
        return None  # Unstop's "Application Screening": the organiser reviews profiles, no work is submitted
    d = r.get("details")
    d = (d[0] if d else {}) if isinstance(d, list) else (d or {})
    kind = r.get("entity_type") or ""
    seo = ((d.get("seo_data") or {}).get("description") or "").lower()
    if "OfflineRound" in kind or seo.startswith("offline"):
        online = False
    elif kind.endswith(("\\Rounds", "AssessmentRound")):
        online = True  # a submission or a test taken on Unstop
    else:
        online = None
    return Round(title=d.get("title") or "", online=online, eliminator=bool(r.get("eliminator_round")))


def parse_detail(data: dict) -> dict:
    """{'screen': bool | None, 'rounds': summary}. 'screen' is None when the event lists no rounds."""
    c = data["data"]["competition"]
    raw = sorted(c.get("rounds") or [], key=lambda r: r.get("round_order") or 0)
    rounds = [x for x in map(_round, raw) if x and x.title]
    if not raw:
        return {"screen": None, "rounds": ""}
    hybrid = (c.get("region") or "").lower() == "hybrid"
    return {"screen": has_screening(rounds, hybrid), "rounds": summary(rounds)}


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    usd = cfg.get("usd_inr", 88)
    events = ListingBatch()
    last = max(1, cfg.get("max_pages", 10))
    for page in range(1, last + 1):
        if page > last:
            break
        with events.page(f"page {page}"):
            rows, reported = parse(http.json(API.format(page=page)), usd)
            last = min(last, reported)
            events.extend(rows)
    events.deduplicate()

    # Reuse successful detail reads until the event changes. Cap requests per run so a cold cache
    # or a detail endpoint outage doesn't send a request for every in-person event at once.
    live = {e.native_id for e in events}
    if not events.failures:
        for k in cache.keys() - live:
            del cache[k]
    budget = cfg.get("details_per_run", 40)
    for e in events:
        if e.mode == "online":
            continue
        updated = e.extra.get("updated")
        hit = cache.get(e.native_id)
        if not hit or hit.get("version") != DETAIL_CACHE_VERSION or hit.get("u") != updated:
            if budget <= 0:
                continue
            budget -= 1
            try:
                detail = parse_detail(http.json(DETAIL.format(id=e.native_id)))
            except Exception:
                continue  # Use the listing description this run and retry the detail on a later poll.
            hit = {"version": DETAIL_CACHE_VERSION, "u": updated, **detail}
            cache[e.native_id] = hit
        e.screening = hit["screen"]
        e.rounds = hit["rounds"] or e.rounds
    return events
