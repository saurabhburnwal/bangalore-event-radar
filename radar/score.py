"""Keyword scoring: decides whether an event is an instant alert (HIGH), digest material, or noise."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .eligibility import team_from_text, team_label
from .models import Event
from .util import inr

HIGH, DIGEST, IGNORE = "HIGH", "DIGEST", "IGNORE"

CAT_OFFICE = "Office visits"
CAT_HACK = "Hackathons"
CAT_NET = "Big-tech & networking"
CAT_OTHER = "Other events"
CAT_AWAY = "Outside Bangalore, online round first"
CAT_ONLINE = "Online hackathons"


@dataclass
class Verdict:
    tier: str
    reasons: list[str] = field(default_factory=list)
    category: str = CAT_OTHER
    filling: bool = False
    score: float = 0.0
    office: str = ""  # the tech giant whose office the event takes you into


_OFFICE_WORDS = r"(?:offices?|campus|headquarters|hq|reactor)"
_FINALE = re.compile(r"\b(?:finale|finals?|final round|offline round|demo day|on-?site round)\b", re.I)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n|•|\s\|\s")
_ORG_PARTS = re.compile(r",\s*|\s+[x×&]\s+")


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


def _name(text: str) -> str:
    """Display form of a matched company name: keep the source's casing unless it was all lower case."""
    t = text.strip()
    if not t.islower():
        return t
    return t.upper() if len(t) <= 3 else t.title()


class Scorer:
    def __init__(self, cfg: dict):
        s = cfg.get("scoring") or {}
        self.s = s
        self.blr = _words((cfg.get("location") or {}).get("aliases"))
        self.big = _words(s.get("big_tech"))
        big_alt = "|".join(f"(?:{i})" for i in s.get("big_tech") or ["$^"])
        self.at_big = re.compile(rf"(?:@|\bat)\s*(?P<co>{big_alt})\b", re.I)
        # "held at the Google office", "at Microsoft Reactor", "venue: Atlassian's Bengaluru office"
        self.at_office = re.compile(
            rf"(?:\bat|@|\bvenue\s*:?|\bin)\s+(?:the\s+)?(?P<co>{big_alt})(?:'s|’s)?\s+(?:[\w-]+\s+){{0,3}}?{_OFFICE_WORDS}\b", re.I)
        # "a visit to Google's office", "Atlassian office tour"
        self.visit_co = re.compile(
            rf"(?:visit|tour)\w*\s+(?:to\s+|of\s+|at\s+)?(?:the\s+)?(?P<co>{big_alt})(?:'s|’s)?\s+(?:[\w-]+\s+){{0,3}}?{_OFFICE_WORDS}\b"
            rf"|(?P<co2>{big_alt})(?:'s|’s)?\s+(?:[\w-]+\s+){{0,2}}?{_OFFICE_WORDS}\s+(?:visit|tour)", re.I)
        self.intern = _words(s.get("internship_keywords"))
        self.office_kw = _words(s.get("office_visit_keywords"))
        self.not_company = _words(s.get("organiser_not_company"))
        self.high_title = _words(s.get("high_title_keywords"))
        self.hack = _words(s.get("hackathon_keywords"))
        self.tech = _words(s.get("tech_keywords"))
        self.screen = _words(s.get("screening_keywords"))
        self.swag = _words(s.get("swag_keywords"))
        self.net = _words(s.get("networking_keywords"))
        self.deny = _words(s.get("deny_keywords"))
        self.restricted = _words(s.get("restricted_keywords"))
        self.college = _words(s.get("my_college"))

    def is_filling(self, ev: Event) -> bool:
        if ev.sold_out:
            return False
        if ev.near_capacity:
            return True
        return ev.spots_left is not None and 0 < ev.spots_left <= self.s.get("filling_spots", 25)

    def org_company(self, org: str) -> str | None:
        """A big-tech organiser, skipping student clubs and user groups that only carry the brand name."""
        for part in _ORG_PARTS.split(org or ""):
            co = _find(self.big, part)
            if co and not _find(self.not_company, part):
                return co
        return None

    def office(self, ev: Event, in_person: bool) -> tuple[str, str] | None:
        """(company, reason) when the event takes you into a tech giant's office: held there, its finale is
        there, the prize is a visit, or (in person) the company itself organises it."""
        if in_person:
            co = _find(self.big, ev.venue)
            if co:
                return _name(co), f"at {_name(co)} office"
            m = self.at_big.search(ev.title)
            if m:
                return _name(m.group("co")), f"at {_name(m.group('co'))} office"
        text = " ".join([ev.title, ev.description, ev.perks, ev.rounds])
        sentences = [x for x in _SENTENCES.split(text) if x and x.strip()]
        held = None
        for sent in sentences:
            m = self.at_office.search(sent)
            if m and _FINALE.search(sent):
                return _name(m.group("co")), f"finale at {_name(m.group('co'))} office"
            held = held or (m and _name(m.group("co")))
        if held:
            return held, f"at {held} office"
        for sent in sentences:
            m = self.visit_co.search(sent)
            co = (m.group("co") or m.group("co2")) if m else (_find(self.big, sent) if _find(self.office_kw, sent) else None)
            if co:
                return _name(co), f"{_name(co)} office visit"
        if in_person:
            co = self.org_company(ev.org)
            if co:
                return _name(co), f"organised by {_name(co)}"
        return None

    def __call__(self, ev: Event) -> Verdict:
        s = self.s
        title = ev.title
        blob = " ".join([ev.title, ev.description, ev.perks])

        denied = _find(self.deny, title)
        if denied:
            return Verdict(IGNORE, [f"ignored word: {denied}"])

        m = self.restricted.search(ev.description) if self.restricted and ev.description else None
        mine_only = False
        if m:
            # Closed events are skipped unless they're closed to *your* college.
            # Look at the matched phrase plus the rest of its sentence ("…only for students of X.").
            tail = re.split(r"[.!?\n]", ev.description[m.end():m.end() + 80], maxsplit=1)[0]
            if _find(self.college, m.group(0) + tail):
                mine_only = True
            else:
                return Verdict(IGNORE, [f"restricted: {m.group(0)}"])

        in_blr = bool(_find(self.blr, " ".join([ev.city, ev.venue, ev.title])))
        in_person = ev.mode != "online"
        hack = ev.kind == "hackathon" or bool(_find(self.hack, title))

        # Team size: you enter solo or as a pair, so skip hackathons that need a bigger team.
        team = None
        if hack:
            team = (ev.team_min, ev.team_max) if ev.team_min else team_from_text(" ".join([ev.description, ev.rounds]))
            if team and team[0] > s.get("my_team_size", 2):
                return Verdict(IGNORE, [f"needs a team of {team[0]}+"])

        offer_text = " ".join([ev.title, ev.perks] + ([] if ev.prize_data else [ev.description]))
        offer = ev.ppi or (hack and bool(_find(self.intern, offer_text)))
        org_co = self.org_company(ev.org)
        big = _find(self.big, ev.venue) or org_co or _find(self.at_big, title)
        filling = self.is_filling(ev)
        prize = ev.prize_inr or 0
        office = self.office(ev, in_person)

        reasons: list[str] = [office[1]] if office else []
        tier = DIGEST

        if not in_blr:
            # Outside Bangalore: hackathons only. In-person ones need an online round first, so you only
            # travel once shortlisted; then they need something real on offer, like remote ones.
            if not hack:
                return Verdict(IGNORE, ["not in Bangalore"])
            if in_person:
                screened = ev.screening if ev.screening is not None else \
                    bool(_find(self.screen, " ".join([ev.description, ev.rounds])))
                if not screened:
                    return Verdict(IGNORE, ["outside Bangalore, no online screening round"])
            if offer:
                # Only a structured internship/PPO prize (Unstop) earns an out-of-town event an instant alert.
                reasons.append("internship/PPO offer" if ev.ppi else "internship mentioned")
                tier = HIGH if ev.ppi and s.get("online_ppi_instant", True) else DIGEST
            elif prize >= s.get("min_online_prize_inr", 100000):
                reasons.append(f"{inr(prize)} prize pool")
            elif not office:
                return Verdict(IGNORE, ["no internship, big prize or office visit"])
            if office:
                tier = HIGH
            if in_person:
                reasons.append("online round first")
        else:
            tech = hack or ev.tech_source or bool(_find(self.tech, blob + " " + ev.host + " " + ev.org))
            if not tech:
                return Verdict(IGNORE, ["not a tech event"])
            if hack and offer:
                reasons.append("internship/PPO offer")
            if org_co and not office:
                reasons.append(f"hosted by {_name(org_co)}")  # an online event run by the company itself
            generic_visit = _find(self.office_kw, blob)
            if generic_visit and not office:
                reasons.append(generic_visit.lower())
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

        if hack:
            reasons.append(team_label(*team) if team else "team size not listed")
        if mine_only:
            reasons.append("open to your college only")
        elif _find(self.college, " ".join([ev.title, ev.venue, ev.host, ev.org])):
            reasons.append("at your college")
        if _find(self.swag, blob):
            reasons.append("swag")
        if ev.sold_out:
            reasons.append("full — waitlist only")

        if office:
            cat = CAT_OFFICE
        elif not in_blr:
            cat = CAT_AWAY if in_person else CAT_ONLINE
        elif hack:
            cat = CAT_HACK
        elif big or _find(self.net, blob) or _find(self.high_title, title):
            cat = CAT_NET
        else:
            cat = CAT_OTHER

        score = (100 if tier == HIGH else 0) + (20 if office else 0) + len(reasons) * 5 + min(prize / 20000, 25)
        return Verdict(tier, reasons, cat, filling, score, office[0] if office else "")
