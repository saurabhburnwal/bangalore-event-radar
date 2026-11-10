"""Keyword scoring: decides whether an event is an instant alert (HIGH), digest material, or noise."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Event
from .util import inr

HIGH, DIGEST, IGNORE = "HIGH", "DIGEST", "IGNORE"

CAT_HACK = "Hackathons"
CAT_NET = "Big-tech & networking"
CAT_OTHER = "Other events"
CAT_ONLINE = "Online hackathons"


@dataclass
class Verdict:
    tier: str
    reasons: list[str] = field(default_factory=list)
    category: str = CAT_OTHER
    filling: bool = False
    score: float = 0.0


def _words(items) -> re.Pattern | None:
    items = [i for i in (items or []) if i]
    if not items:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(f"(?:{i})" for i in items) + r")(?![\w])", re.I)


def _find(p: re.Pattern | None, text: str) -> str | None:
    if not p or not text:
        return None
    m = p.search(text)
    return m.group(0) if m else None


class Scorer:
    def __init__(self, cfg: dict):
        s = cfg.get("scoring") or {}
        self.s = s
        self.blr = _words((cfg.get("location") or {}).get("aliases"))
        self.big = _words(s.get("big_tech"))
        self.at_big = re.compile(r"(?:@|\bat)\s*(?:" + "|".join(f"(?:{i})" for i in s.get("big_tech") or ["$^"]) + r")\b", re.I)
        self.intern = _words(s.get("internship_keywords"))
        self.office = _words(s.get("office_visit_keywords"))
        self.high_title = _words(s.get("high_title_keywords"))
        self.hack = _words(s.get("hackathon_keywords"))
        self.tech = _words(s.get("tech_keywords"))
        self.swag = _words(s.get("swag_keywords"))
        self.net = _words(s.get("networking_keywords"))
        self.deny = _words(s.get("deny_keywords"))
        self.restricted = _words(s.get("restricted_keywords"))

    def is_filling(self, ev: Event) -> bool:
        if ev.sold_out:
            return False
        if ev.near_capacity:
            return True
        return ev.spots_left is not None and 0 < ev.spots_left <= self.s.get("filling_spots", 25)

    def __call__(self, ev: Event) -> Verdict:
        s = self.s
        title = ev.title
        blob = " ".join([ev.title, ev.description, ev.perks])

        denied = _find(self.deny, title)
        if denied:
            return Verdict(IGNORE, [f"ignored word: {denied}"])

        restricted = _find(self.restricted, ev.description)
        if restricted:
            return Verdict(IGNORE, [f"restricted: {restricted}"])

        in_blr = bool(_find(self.blr, " ".join([ev.city, ev.venue, ev.title])))
        hack = ev.kind == "hackathon" or bool(_find(self.hack, title))
        offer_text = " ".join([ev.title, ev.perks] + ([] if ev.prize_data else [ev.description]))
        offer = ev.ppi or (hack and bool(_find(self.intern, offer_text)))
        big = _find(self.big, " ".join([ev.venue, ev.org])) or _find(self.at_big, title)
        filling = self.is_filling(ev)
        prize = ev.prize_inr or 0

        reasons: list[str] = []
        tier = DIGEST

        if not in_blr:
            # Outside Bangalore only remote hackathons with something real on offer are worth a look.
            if ev.mode == "offline" or not hack:
                return Verdict(IGNORE, ["not in Bangalore"])
            if offer:
                # Only a structured internship/PPO prize (Unstop) earns a remote event an instant alert.
                reasons.append("internship/PPO offer" if ev.ppi else "internship mentioned")
                tier = HIGH if ev.ppi and s.get("online_ppi_instant", True) else DIGEST
            elif prize >= s.get("min_online_prize_inr", 100000):
                reasons.append(f"{inr(prize)} prize pool")
            else:
                return Verdict(IGNORE, ["online, no internship or big prize"])
        else:
            tech = hack or ev.tech_source or bool(_find(self.tech, blob + " " + ev.host + " " + ev.org))
            if not tech:
                return Verdict(IGNORE, ["not a tech event"])
            if hack and offer:
                reasons.append("internship/PPO offer")
            if big:
                reasons.append(re.sub(r"^(?:@|at\b)\s*", "", big, flags=re.I).strip() + " venue/host")
            office = _find(self.office, blob)
            if office:
                reasons.append(office.lower())
            ht = _find(self.high_title, title)
            if ht:
                reasons.append(ht)
            if hack and prize >= s.get("high_prize_inr", 100000):
                reasons.append(f"{inr(prize)} prize pool")
            tier = HIGH if reasons else DIGEST
            if hack and not reasons:
                reasons.append("hackathon" + (f", {inr(prize)} prizes" if prize else ""))
            if filling:
                reasons.append(f"filling fast ({ev.spots_left} spots left)" if ev.spots_left else "filling fast")
                tier = HIGH
            if not reasons:
                reasons.append("tech event in Bangalore")

        if _find(self.swag, blob):
            reasons.append("swag")
        if ev.sold_out:
            reasons.append("full — waitlist only")

        if not in_blr:
            cat = CAT_ONLINE
        elif hack:
            cat = CAT_HACK
        elif big or _find(self.net, blob) or _find(self.high_title, title):
            cat = CAT_NET
        else:
            cat = CAT_OTHER

        score = (100 if tier == HIGH else 0) + len(reasons) * 5 + min(prize / 20000, 25)
        return Verdict(tier, reasons, cat, filling, score)
