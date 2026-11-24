"""Can you enter? Allowed team sizes and screening rounds, shared by the source readers and the scorer."""
from __future__ import annotations

import re
from dataclasses import dataclass

_OFFLINE = re.compile(r"\b(?:offline|on[- ]?campus|on[- ]?ground|in[- ]?person|on[- ]?site|finale|finals?|venue)\b", re.I)
_ONLINE = re.compile(r"\b(?:online|virtual|remote)\b", re.I)
# Steps that aren't a round of work: signing up, profile review, joining a group, announcements, mentoring.
_NOT_WORK = re.compile(
    r"\b(?:registrations?|register|whatsapp|discord|telegram|results?|announcements?|declaration|profile|"
    r"application screening|mentor\w*|sessions?|orientation|inauguration|timeline|evaluation period|"
    r"problem statements? release)\b", re.I)


@dataclass
class Round:
    title: str
    online: bool | None       # what the site says about this round: True online, False in person, None unknown
    eliminator: bool = False  # the site marks it as knocking teams out


def round_mode(r: Round) -> bool | None:
    """True online, False in person, None unknown. The title wins over the site's label, because organisers
    often file 'Round 1 (Online)' as an offline round and 'Offline Finals' as a submission round."""
    on, off = _ONLINE.search(r.title), _OFFLINE.search(r.title)
    if on and not off:
        return True
    if off and not on:
        return False
    return r.online


def has_screening(rounds: list[Round], hybrid: bool = False) -> bool:
    """True when the first round of work is online and can screen entrants before they travel.

    The round must eliminate entrants, precede another round, or belong to a hybrid event.
    """
    work = [r for r in rounds if not _NOT_WORK.search(r.title)]
    if not work or round_mode(work[0]) is not True:
        return False
    return work[0].eliminator or len(work) > 1 or hybrid


def summary(rounds: list[Round], limit: int = 300) -> str:
    """'Idea Submission (online) → 24-Hour Hackathon (in person)'."""
    parts = []
    for r in rounds:
        if _NOT_WORK.search(r.title):
            continue
        mode = round_mode(r)
        label = " (online)" if mode is True else " (in person)" if mode is False else ""
        title = re.sub(r"\s+", " ", r.title).strip(" :-–")
        if len(title) > 60:
            title = title[:59].rsplit(" ", 1)[0].rstrip(" :-–(") + "…"
        parts.append(title + label)
    return " → ".join(parts)[:limit]


_ROUNDISH = re.compile(r"\b(?:rounds?|prelim\w*|screening|qualif\w*|submission|shortlist\w*|finale|finals?|stages?)\b", re.I)


def round_sentences(text: str, limit: int = 500) -> str:
    """The sentences of a long description that talk about rounds, for sites that only describe them in prose."""
    text = re.sub(r"[*#>]+", " ", text or "")  # Markdown emphasis and quotes
    found = [re.sub(r"\s+", " ", s).strip() for s in re.split(r"(?<=[.!?])\s+|\n", text) if _ROUNDISH.search(s)]
    return " ".join(found)[:limit]


_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_N = r"(\d{1,2}|one|two|three|four|five|six|seven|eight)"
_TO = r"\s*(?:-|–|—|to|and)\s*"
_PEOPLE = r"(?:members?|people|persons?|participants?|students?|individuals?)"
_TEAM_RANGE = re.compile(rf"\bteams?(?:\s+size)?\s*(?:of|:|=|-|is|can be|between)?\s*(?:between\s+)?{_N}{_TO}{_N}\b", re.I)
_RANGE = re.compile(rf"\b{_N}{_TO}{_N}\s*{_PEOPLE}", re.I)
_UP_TO = re.compile(rf"\bteams?(?:\s+size)?\s*(?:of|:)?\s*(?:up\s?to|max(?:imum)?(?:\s+of)?|at most)\s*{_N}\b", re.I)
_AT_LEAST = re.compile(rf"\b(?:min(?:imum)?\.?|at least)\s*(?:of\s+)?{_N}\s*{_PEOPLE}", re.I)
_EXACT = re.compile(rf"\bteams?\s+of\s+{_N}\b(?!{_TO}\w)", re.I)
_SOLO = re.compile(r"\b(?:solo|individuals?)\s*(?:or|and|/)\s*(?:in\s+)?teams?\b|\bindividual participation\b"
                   r"|\bparticipate (?:individually|solo)\b", re.I)


def _n(s: str) -> int:
    return _WORDS.get(s.lower()) or int(s)


def _sane(lo: int, hi: int | None) -> tuple[int, int | None] | None:
    if 1 <= lo <= 10 and (hi is None or lo <= hi <= 10):
        return lo, hi
    return None


def team_from_text(text: str) -> tuple[int, int | None] | None:
    """(min, max) team size from phrases like 'teams of 2–4 members', 'team size: up to 4',
    'minimum 3 members', 'teams of 3'. Max is None when only a minimum is stated. None if nothing is found."""
    if not text:
        return None
    for pat in (_TEAM_RANGE, _RANGE):
        m = pat.search(text)
        if m and (t := _sane(_n(m.group(1)), _n(m.group(2)))):
            return t
    m = _UP_TO.search(text)
    if m and (t := _sane(1, _n(m.group(1)))):
        return t
    m = _AT_LEAST.search(text)
    if m and (t := _sane(_n(m.group(1)), None)):
        return t
    m = _EXACT.search(text)
    if m and (t := _sane(_n(m.group(1)), _n(m.group(1)))):
        return t
    if _SOLO.search(text):
        return 1, None
    return None


def team_label(lo: int, hi: int | None) -> str:
    if hi == 1:
        return "solo only"
    if hi is None:
        return f"team of {lo}+" if lo > 1 else "solo allowed"
    if lo == hi:
        return f"team of {lo}"
    return f"team {lo}–{hi}"
