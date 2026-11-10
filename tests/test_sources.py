"""Parsers against real responses saved on 2026-11-11."""
from conftest import data, text

from radar.sources import devfolio, gdg, hackbriven, hasgeek, luma, meetup, unstop


def by_title(events, prefix):
    return next(e for e in events if e.title.startswith(prefix))


def test_luma():
    evs = luma.parse(data("luma.json"))
    assert len(evs) == 17
    e = by_title(evs, "Build Out Loud")
    assert e.city == "Bengaluru" and e.spots_left == 295 and e.url == "https://luma.com/" + e.url.rsplit("/", 1)[1]
    assert e.start.isoformat().startswith("2026-11-15")
    full = by_title(evs, "AI Tools that Earn")
    assert full.sold_out


def test_luma_calendar_uses_same_format():
    assert any("Bolna" in e.org for e in luma.parse(data("luma_calendar.json")))


def test_meetup_spots_and_venue():
    evs = meetup.parse(text("meetup.html"))
    assert len(evs) == 11
    ibm = by_title(evs, "[in-person] Polyglot day")
    assert "IBM" in ibm.venue and ibm.spots_left == 9 and ibm.mode == "offline"
    atlassian = by_title(evs, "Agentic AI in Practice")
    assert atlassian.sold_out and "Atlassian" in atlassian.venue
    assert by_title(evs, "AWS Certificate Preparation").mode == "online"


def test_unstop_prizes_and_ppi():
    evs, last = unstop.parse(data("unstop.json"))
    assert last == 7 and len(evs) >= 25
    bs = by_title(evs, "BuildSprint")
    assert bs.ppi and bs.prize_inr == 35000 and "internship" in bs.perks
    inc = by_title(evs, "Inceptrix 3.0")
    assert inc.city == "Bangalore" and inc.prize_inr == 250000 and inc.mode == "hybrid"
    assert inc.reg_deadline is not None and inc.kind == "hackathon"


def test_devfolio_listing_and_detail():
    listing = devfolio.parse_listing(text("devfolio.html"))
    assert len(listing) == 21
    detail = devfolio.parse_detail(text("devfolio_detail_devnexus2.html"))
    assert detail["city"] == "Kolkata"
    ev = devfolio.build(next(h for h in listing if h["slug"] == "devnexus2"), detail)
    assert ev.city == "Kolkata" and ev.reg_deadline is not None and ev.url == "https://devnexus2.devfolio.co/"


def test_gdg_chapter_and_detail():
    chapter, upcoming = gdg.parse_chapter(text("gdg.html"))
    assert chapter["title"] == "GDG Bangalore"
    assert [e["title"] for e in upcoming] == ["Flutter Meetup", "DevFest Bengaluru 2026"]
    detail = gdg.parse_detail(text("gdg_event_flutter.html"))
    assert detail["city"] == "Bengaluru" and "22nd Main" in detail["venue"]
    ev = gdg.build(chapter, upcoming[0], detail)
    assert ev.url.startswith("https://gdg.community.dev/events/details/")
    _, cloud = gdg.parse_chapter(text("gdg_cloud.html"))
    assert cloud and cloud[0]["title"] == "Devfest 2026"


def test_hasgeek_cards():
    evs = hasgeek.parse(text("hasgeek.html"))
    assert len(evs) == 13
    wis = by_title(evs, "Women in Systems")
    assert wis.venue == "Microsoft, Bengaluru" and wis.start.date().isoformat() == "2026-11-28"
    assert by_title(evs, "Sponsor Rootconf").mode == "online"


def test_hasgeek_date_labels():
    p = hasgeek.parse_date_label
    assert p("28 Nov 2026, Bengaluru".split(",")[0]).day == 28
    assert p("20–21 Nov 2026").day == 20
    d = p("20 Nov–12 Dec 2026")
    assert (d.month, d.day) == (11, 20)
    d = p("28 Sep 2025–31 Dec 2026")
    assert (d.year, d.month) == (2025, 9)


def test_hackbriven():
    evs = hackbriven.parse(data("hackbriven_ongoing.json"))
    assert {e.title for e in evs} == {"Notion Workshop BLR", "Build Bengaluru 2.0"}
    assert by_title(evs, "Build Bengaluru").kind == "hackathon"
    assert hackbriven.parse(data("hackbriven_upcoming.json")) == []
