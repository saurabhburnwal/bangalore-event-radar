"""Parsers against real responses saved on 2026-11-11."""
import pytest

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
    assert (inc.team_min, inc.team_max) == (4, 5) and (bs.team_min, bs.team_max) == (1, 1)


def test_unstop_round_lists():
    # CODERED'26 (hybrid, Yelahanka): idea submission → online evaluation → on-campus sprint.
    d = unstop.parse_detail(data("unstop_competition_codered.json"))
    assert d["screen"] is True
    assert d["rounds"].startswith("Round 1 (Idea Submission) (online) → Round 2")
    assert d["rounds"].endswith("(in person)")
    # WIE HackEarth: a "Registration Timeline" step filed as an offline round, then a PPT submission.
    assert unstop.parse_detail(data("unstop_competition_wie_hackearth.json"))["screen"] is True
    # A CTF with only an offline round: no screening.
    assert unstop.parse_detail(data("unstop_competition_ctf_davanagere.json"))["screen"] is False
    # Hacksmart (hybrid): Unstop's "Application Screening" is profile review and doesn't count, but the
    # online Round 1 of a hybrid event does.
    hs = unstop.parse_detail(data("unstop_competition_hacksmart.json"))
    assert hs["screen"] is True and "Application" not in hs["rounds"]
    assert unstop.parse_detail({"data": {"competition": {"rounds": []}}}) == {"screen": None, "rounds": ""}


class FakeHttp:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def json(self, url):
        self.calls.append(url)
        response = self.pages[url]
        if isinstance(response, Exception):
            raise response
        return response


def test_unstop_fetches_round_lists_for_in_person_events_once_until_they_change():
    listing = data("unstop.json")
    listing["data"]["last_page"] = 1
    detail = data("unstop_competition_codered.json")
    pages = {unstop.API.format(page=1): listing}
    in_person = [str(o["id"]) for o in listing["data"]["data"] if o["region"] != "online"]
    for i in in_person:
        pages[unstop.DETAIL.format(id=i)] = detail
    http, cache = FakeHttp(pages), {}
    evs = unstop.fetch(http, {"details_per_run": 100}, cache)
    assert len(http.calls) == 1 + len(in_person) and set(cache) == set(in_person)
    assert all(e.screening is True for e in evs if e.native_id in in_person)
    assert all(e.screening is None for e in evs if e.native_id not in in_person)
    http.calls.clear()
    unstop.fetch(http, {}, cache)
    assert http.calls == [unstop.API.format(page=1)]  # cached: only the listing again
    listing["data"]["data"][0]["updated_at"] = "2099-01-01T00:00:00+05:30"
    http.calls.clear()
    unstop.fetch(http, {}, cache)
    changed = str(listing["data"]["data"][0]["id"])
    assert http.calls == [unstop.API.format(page=1)] + ([unstop.DETAIL.format(id=changed)] if changed in in_person else [])


def test_unstop_detail_fetches_are_capped_per_run():
    listing = data("unstop.json")
    listing["data"]["last_page"] = 1
    pages = {unstop.API.format(page=1): listing}
    for o in listing["data"]["data"]:
        pages[unstop.DETAIL.format(id=o["id"])] = data("unstop_competition_codered.json")
    http, cache = FakeHttp(pages), {}
    unstop.fetch(http, {"details_per_run": 3}, cache)
    assert len(http.calls) == 1 + 3 and len(cache) == 3


@pytest.mark.parametrize("legacy_detail", [
    None,
    {"screen": None, "rounds": ""},
    {"screen": True, "rounds": "Legacy online round"},
])
def test_unstop_retries_failed_details_and_refreshes_legacy_cache(legacy_detail):
    listing = data("unstop.json")
    entry = next(o for o in listing["data"]["data"] if o["region"] != "online")
    listing["data"].update(data=[entry], last_page=1)
    listing_url = unstop.API.format(page=1)
    detail_url = unstop.DETAIL.format(id=entry["id"])
    event_id = str(entry["id"])
    old = {"u": entry.get("updated_at"), **legacy_detail} if legacy_detail is not None else None
    cache = {event_id: old} if old is not None else {}
    http = FakeHttp({listing_url: listing, detail_url: ConnectionError("temporary detail outage")})

    event, = unstop.fetch(http, {}, cache)
    assert event.screening is None
    assert cache.get(event_id) == old

    http.pages[detail_url] = data("unstop_competition_ctf_davanagere.json")
    event, = unstop.fetch(http, {}, cache)
    assert event.screening is False

    event, = unstop.fetch(http, {}, cache)
    assert event.screening is False
    assert http.calls == [listing_url, detail_url, listing_url, detail_url, listing_url]


def test_devfolio_listing_and_detail():
    listing = devfolio.parse_listing(text("devfolio.html"))
    assert len(listing) == 21
    detail = devfolio.parse_detail(text("devfolio_detail_devnexus2.html"))
    assert detail["city"] == "Kolkata"
    ev = devfolio.build(next(h for h in listing if h["slug"] == "devnexus2"), detail)
    assert ev.city == "Kolkata" and ev.reg_deadline is not None and ev.url == "https://devnexus2.devfolio.co/"


def test_devfolio_detail_team_size_and_rounds():
    d = devfolio.parse_detail(text("devfolio_detail_innerve11.html"))
    assert (d["team_min"], d["team_max"]) == (2, 4) and d["city"] == "Pune"
    assert "Idea submission round" in d["rounds"] and "*" not in d["rounds"]
    ev = devfolio.build({"slug": "innerve-11", "name": "Innerve 11", "is_online": False}, d)
    assert (ev.team_min, ev.team_max) == (2, 4) and ev.screening is None and ev.rounds


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
    assert wis.end.date().isoformat() == "2026-11-29"


def test_hasgeek_date_labels():
    p = hasgeek.parse_date_label
    assert p("28 Nov 2026, Bengaluru".split(",")[0]).day == 28
    assert p("20–21 Nov 2026").day == 20
    d = p("20 Nov–12 Dec 2026")
    assert (d.month, d.day) == (11, 20)
    d = p("28 Sep 2025–31 Dec 2026")
    assert (d.year, d.month) == (2025, 9)
    assert p("30 Dec–2 Jan 2027").year == 2026


def test_hackbriven():
    evs = hackbriven.parse(data("hackbriven_ongoing.json"))
    assert {e.title for e in evs} == {"Notion Workshop BLR", "Build Bengaluru 2.0"}
    assert by_title(evs, "Build Bengaluru").kind == "hackathon"
    assert hackbriven.parse(data("hackbriven_upcoming.json")) == []


def test_hackbriven_virtual_events_team_size_and_stages():
    evs = hackbriven.parse(data("hackbriven_ongoing_virtual.json"))
    bol = by_title(evs, "BOLBHARAT")
    assert bol.mode == "online"  # Hackbriven calls online events "virtual"
    assert (bol.team_min, bol.team_max) == (1, 1) and bol.screening is True and bol.rounds == "Round 1 (online)"
    notion = by_title(evs, "Notion Workshop")
    assert notion.mode == "offline" and notion.screening is None


def test_unstop_scores_read_pages_and_recovers_without_realert(cfg):
    from datetime import datetime, timezone
    from radar import health, runner, state
    from radar.notify import Console

    def page(n):
        return {"data": {"last_page": 4, "data": [{"id": n, "title": f"Campus Sprint {n}", "region": "offline",
                "address_with_country_logo": {"city": "Bangalore"}, "prizes": [{"cash": 150000}]}]}}

    pages = {unstop.API.format(page=n): page(n) for n in range(1, 5)}
    pages[unstop.API.format(page=3)] = RuntimeError()
    cache = {"unread": {}}
    http = FakeHttp(pages)
    settings = {"details_per_run": 0}
    batch = unstop.fetch(http, settings, cache)
    assert health.source_status("unstop", batch)[0] == "partial" and "unread" in cache
    now = datetime(2026, 11, 1, tzinfo=timezone.utc)
    saved = state.empty()
    first = runner.poll({"unstop": batch}, saved, cfg, Console(), now)
    assert len(first.scored) == len(first.alerted) == 3
    assert saved["health"]["sources"]["unstop"]["outcome"] == "partial"
    pages[unstop.API.format(page=3)] = page(3)
    batch = unstop.fetch(http, settings, cache)
    assert health.source_status("unstop", batch)[0] == "complete" and "unread" not in cache
    second = runner.poll({"unstop": batch}, saved, cfg, Console(), now)
    assert second.alerted == ["Campus Sprint 3"]


@pytest.mark.parametrize("reader,options,payload", [
    (luma, {"calendars": ["second"]}, "luma_calendar.json"),
    (meetup, {"urls": ["first", "second"]}, "meetup.html"),
    (gdg, {"chapters": ["first", "second"]}, "gdg.html"),
    (hackbriven, {}, "hackbriven_ongoing.json"),
])
def test_independent_listing_pages_survive_first_failure(reader, options, payload):
    from radar.health import source_status
    class Feed:
        calls = 0
        def read(self, url):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError()
            return data(payload) if payload.endswith(".json") else text(payload)
        text = json = read

    cache = {"unread": {}}
    batch = reader.fetch(Feed(), options, cache)
    assert source_status(reader.__name__.split(".")[-1], batch)[0] == "partial"
    assert batch and "unread" in cache
