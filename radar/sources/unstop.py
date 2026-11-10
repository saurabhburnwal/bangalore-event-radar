"""Unstop: public opportunity search API, open hackathons only."""
from __future__ import annotations

from ..models import Event
from ..util import html_to_text, parse_dt

API = "https://unstop.com/api/public/opportunity/search-result?opportunity=hackathons&oppstatus=open&per_page=30&page={page}"


def _prize(prizes: list, usd_inr: float) -> tuple[int, bool, str]:
    total, ppi, perks = 0, False, []
    for p in prizes or []:
        cash = p.get("cash") or 0
        if isinstance(cash, (int, float)):
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
    for o in d.get("data", []):
        addr = o.get("address_with_country_logo") or {}
        regn = o.get("regnRequirements") or {}
        prize, ppi, perks = _prize(o.get("prizes"), usd_inr)
        region = (o.get("region") or "online").lower()
        out.append(Event(
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
            description=html_to_text(o.get("details")),
            kind="hackathon",
            tech_source=True,
            prize_inr=prize,
            ppi=ppi,
            prize_data=True,
            perks=perks,
            reg_deadline=parse_dt(regn.get("end_regn_dt")),
            extra={"registered": o.get("registerCount")},
        ))
    return out, int(d.get("last_page") or 1)


def fetch(http, cfg: dict, cache: dict) -> list[Event]:
    usd = cfg.get("usd_inr", 88)
    events, last = parse(http.json(API.format(page=1)), usd)
    for page in range(2, min(last, cfg.get("max_pages", 10)) + 1):
        events += parse(http.json(API.format(page=page)), usd)[0]
    return list({e.native_id: e for e in events}.values())
