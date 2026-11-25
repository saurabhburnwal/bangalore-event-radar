"""Multi-run behaviour: no duplicate alerts, one filling-fast re-alert, digest, broken-source warnings."""
from datetime import datetime, timedelta, timezone

import pytest

from radar import messages, runner
from radar import state as st
from radar.http import SourceError
from radar.models import Event

NOW = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)
SOON = NOW + timedelta(days=10)


class Spy:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, text, button_url=None, button_text="Register →"):
        if self.fail:
            raise RuntimeError("telegram down")
        self.sent.append(text)


class OnePage(Spy):
    def send(self, text, button_url=None, button_text="Register →"):
        if self.sent:
            raise RuntimeError("sending the next page failed")
        super().send(text, button_url, button_text)


def google(**kw):
    base = dict(source="gdg", native_id="devfest", title="DevFest Bengaluru 2026", url="https://gdg.example/devfest",
                start=SOON, city="Bengaluru", venue="Google Ananta", tech_source=True)
    base.update(kw)
    return Event(**base)


def meetup_ev(**kw):
    base = dict(source="meetup", native_id="m1", title="Rust Systems Night", url="https://meetup.example/m1",
                start=SOON, city="Bengaluru", venue="Some Cafe", tech_source=True)
    base.update(kw)
    return Event(**base)


def results(**by_source):
    base = {name: [] for name in ("luma", "unstop", "devfolio", "meetup", "gdg", "hackbriven", "hasgeek")}
    base.update(by_source)
    return base


@pytest.fixture
def seeded(cfg):
    """State after a quiet first run."""
    state = st.empty()
    runner.poll(results(), state, cfg, Spy(), NOW)
    assert state["initialized"]
    return state


def test_first_run_sends_one_summary_not_a_flood(cfg):
    state, spy = st.empty(), Spy()
    rep = runner.poll(results(gdg=[google()], meetup=[meetup_ev()]), state, cfg, spy, NOW)
    assert rep.first_run and len(spy.sent) == 1 and "DevFest" in spy.sent[0]
    assert state["initialized"] and len(state["queue"]) == 1  # the meetup waits for the digest
    spy2 = Spy()
    runner.poll(results(gdg=[google()], meetup=[meetup_ev()]), state, cfg, spy2, NOW)
    assert spy2.sent == []


def test_new_high_event_alerts_once(cfg, seeded):
    spy = Spy()
    runner.poll(results(gdg=[google()]), seeded, cfg, spy, NOW)
    assert len(spy.sent) == 1 and "DevFest" in spy.sent[0]
    again = Spy()
    runner.poll(results(gdg=[google()]), seeded, cfg, again, NOW + timedelta(minutes=10))
    assert again.sent == []


def test_failed_send_is_retried_next_run(cfg, seeded):
    rep = runner.poll(results(gdg=[google()]), seeded, cfg, Spy(fail=True), NOW)
    assert rep.errors and not rep.alerted
    spy = Spy()
    runner.poll(results(gdg=[google()]), seeded, cfg, spy, NOW)
    assert len(spy.sent) == 1


def test_partial_bundle_retries_only_undelivered_events(cfg, seeded, monkeypatch):
    monkeypatch.setattr(messages, "LIMIT", 600)
    events = [google(native_id=str(i), title=f"DevFest {i:02} Bengaluru") for i in range(18)]
    first = runner.poll(results(gdg=events), seeded, cfg, OnePage(), NOW)
    assert first.errors and 0 < len(first.alerted) < len(events)
    second = runner.poll(results(gdg=events), seeded, cfg, Spy(), NOW)
    assert set(first.alerted).isdisjoint(second.alerted)
    assert len(first.alerted) + len(second.alerted) == len(events)


def test_partial_digest_persists_queue_progress(cfg, seeded, monkeypatch, tmp_path):
    monkeypatch.setattr(messages, "LIMIT", 600)
    events = [meetup_ev(native_id=str(i), title=f"Rust meetup {i:02}") for i in range(18)]
    runner.poll(results(meetup=events), seeded, cfg, Spy(), NOW)
    path = tmp_path / "seen.json"
    first = OnePage()
    with pytest.raises(RuntimeError, match="next page"):
        runner.digest(seeded, cfg, first, NOW, lambda: st.save(path, seeded))
    stored = st.load(path)
    assert 0 < len(stored["queue"]) < len(events)
    second = "\n".join(runner.digest(stored, cfg, Spy(), NOW))
    for event in events:
        assert (event.title in first.sent[0]) != (event.title in second)
    assert not stored["queue"]


def test_digest_event_escalates_when_filling_then_realerts_never(cfg, seeded):
    runner.poll(results(meetup=[meetup_ev()]), seeded, cfg, Spy(), NOW)
    assert len(seeded["queue"]) == 1
    spy = Spy()
    runner.poll(results(meetup=[meetup_ev(spots_left=10)]), seeded, cfg, spy, NOW)
    assert len(spy.sent) == 1 and "filling fast" in spy.sent[0]
    assert seeded["queue"] == []  # alerted events leave the digest queue
    spy2 = Spy()
    runner.poll(results(meetup=[meetup_ev(spots_left=4)]), seeded, cfg, spy2, NOW)
    assert spy2.sent == []


def test_alerted_event_gets_one_filling_fast_followup(cfg, seeded):
    runner.poll(results(gdg=[google()]), seeded, cfg, Spy(), NOW)
    spy = Spy()
    runner.poll(results(gdg=[google(spots_left=8)]), seeded, cfg, spy, NOW)
    assert len(spy.sent) == 1 and spy.sent[0].startswith("⚠️")
    spy2 = Spy()
    runner.poll(results(gdg=[google(spots_left=3)]), seeded, cfg, spy2, NOW)
    assert spy2.sent == []


def test_same_event_on_two_sites_alerts_once_with_merged_details(cfg, seeded):
    lu = Event(source="luma", native_id="agora", title="Build with Agora - Bengaluru 2026 | Voice AI Hackathon",
               url="https://luma.com/agora", start=SOON, city="Bengaluru")
    un = Event(source="unstop", native_id="99", title="Build with Agora - BLR", url="https://unstop.com/x",
               end=SOON, city="Bangalore", kind="hackathon", prize_inr=176000, prize_data=True, tech_source=True)
    spy = Spy()
    rep = runner.poll(results(luma=[lu], unstop=[un]), seeded, cfg, spy, NOW)
    assert len(spy.sent) == 1 and "₹1,76,000" in spy.sent[0] and "luma.com" not in spy.sent[0]
    assert len([e for e, v in rep.scored]) == 1
    # Next day Luma drops it but Unstop still lists it: still no second alert.
    spy2 = Spy()
    runner.poll(results(unstop=[un]), seeded, cfg, spy2, NOW + timedelta(days=1))
    assert spy2.sent == []


def test_different_events_with_overlapping_titles_are_not_merged(cfg, seeded):
    a = Event(source="luma", native_id="a", title="AI Hackathon", url="u1", start=SOON, city="Bengaluru")
    b = Event(source="unstop", native_id="b", title="Agentic AI Hackathon", url="u2", end=SOON, city="Bengaluru",
              kind="hackathon", tech_source=True)
    rep = runner.poll(results(luma=[a], unstop=[b]), seeded, cfg, Spy(), NOW)
    assert len(rep.scored) == 2


def test_same_source_events_with_the_same_title_keep_separate_ids(cfg, seeded):
    runner.poll(results(meetup=[meetup_ev(native_id="first"), meetup_ev(native_id="second")]), seeded, cfg, Spy(), NOW)
    assert {entry["id"] for entry in seeded["queue"]} == {"meetup:first", "meetup:second"}


def test_queue_refreshes_and_withdraws_under_a_second_source_id(cfg, seeded):
    first = meetup_ev(source="luma", native_id="rust-hack", title="Rust Hackathon", url="https://luma.com/rust")
    second = meetup_ev(source="unstop", native_id="rust", title=first.title, url="https://unstop.com/hackathons/rust")
    runner.poll(results(luma=[first]), seeded, cfg, Spy(), NOW)
    runner.poll(results(unstop=[second]), seeded, cfg, Spy(), NOW)
    queued, = seeded["queue"]
    assert queued["id"] == first.id and queued["url"] == second.url
    second.team_min = 4
    runner.poll(results(unstop=[second]), seeded, cfg, Spy(), NOW)
    assert seeded["queue"] == [] and seeded["events"][first.id]["dropped"]


def test_known_duplicate_listings_alert_once_after_a_date_change(cfg, seeded):
    first = meetup_ev(source="luma", native_id="rust-hack", title="Rust Hackathon", url="https://luma.com/rust")
    second = meetup_ev(source="unstop", native_id="rust", title=first.title, url="https://unstop.com/hackathons/rust")
    runner.poll(results(luma=[first], unstop=[second]), seeded, cfg, Spy(), NOW)
    first.start += timedelta(days=1)
    first.spots_left = second.spots_left = 2
    report = runner.poll(results(luma=[first], unstop=[second]), seeded, cfg, Spy(), NOW)
    assert report.alerted == [first.title] and seeded["queue"] == []


def test_expired_registrations_are_removed_before_alert_and_digest(cfg, seeded):
    early = meetup_ev(reg_deadline=NOW + timedelta(minutes=15))
    runner.poll(results(meetup=[early]), seeded, cfg, Spy(), NOW)
    assert seeded["queue"]
    now = NOW + timedelta(minutes=30)
    assert runner.digest(seeded, cfg, Spy(), now) == []
    closed = google(reg_deadline=NOW)
    ended = google(native_id="ended", start=NOW - timedelta(days=1))
    report = runner.poll(results(gdg=[closed, ended]), seeded, cfg, Spy(), now)
    assert not report.alerted


def test_digest_groups_closing_soon_and_clears_queue(cfg, seeded):
    hack = Event(source="unstop", native_id="h", title="Rewired (Tech Hackathon)", url="https://unstop.com/h",
                 end=SOON, city="Bangalore", kind="hackathon", prize_inr=20000, prize_data=True, tech_source=True,
                 reg_deadline=NOW + timedelta(hours=30))
    runner.poll(results(unstop=[hack], meetup=[meetup_ev()]), seeded, cfg, Spy(), NOW)
    spy = Spy()
    sent = runner.digest(seeded, cfg, spy, NOW + timedelta(hours=1))
    body = "\n".join(sent)
    assert "Hackathons" in body and "Rewired" in body and "Rust Systems Night" in body
    assert "Registration closing soon" in body
    assert seeded["queue"] == []


def test_empty_digest_sends_nothing(cfg, seeded):
    spy = Spy()
    assert runner.digest(seeded, cfg, spy, NOW) == [] and spy.sent == []


def test_annual_reminder_fires_once_per_threshold(cfg, seeded):
    hf = datetime(2027, 9, 1, 4, 0, tzinfo=timezone.utc)  # 14 days before Hacktoberfest's 09-15
    body = "\n".join(runner.digest(seeded, cfg, Spy(), hf))
    assert "Hacktoberfest" in body and "in 14 days" in body
    assert runner.digest(seeded, cfg, Spy(), hf + timedelta(days=1)) == []
    body = "\n".join(runner.digest(seeded, cfg, Spy(), datetime(2027, 9, 12, 4, 0, tzinfo=timezone.utc)))
    assert "Hacktoberfest" in body and "in 3 days" in body


def test_leap_day_reminder_survives_non_leap_years(seeded):
    cfg = {"annual_programs": [{"opens": "02-29", "name": "Leap Day", "url": "https://example.org/leap"}]}
    assert runner.digest(seeded, cfg, Spy(), datetime(2024, 3, 1, tzinfo=timezone.utc)) == []
    body = "\n".join(runner.digest(seeded, cfg, Spy(), datetime(2028, 2, 15, tzinfo=timezone.utc)))
    assert "Leap Day" in body and "in 14 days" in body


def test_broken_source_warns_once_and_recovers(cfg, seeded):
    seeded["sources"] = {}  # the seeding run saw every source empty
    # Give the other sources an event each so only Luma is broken.
    ok = {n: [meetup_ev(source=n, native_id=n)] for n in ("unstop", "devfolio", "meetup", "hasgeek")}
    boom = results(luma=SourceError("HTTP 403"), **ok)
    for i in range(5):
        spy = Spy()
        runner.poll(boom, seeded, cfg, spy, NOW)
        assert not [s for s in spy.sent if "Radar" in s], f"warned too early on run {i + 1}"
    spy = Spy()
    runner.poll(boom, seeded, cfg, spy, NOW)
    warns = [s for s in spy.sent if "Radar" in s]
    assert len(warns) == 1 and "Luma" in warns[0] and "403" in warns[0]
    spy = Spy()
    runner.poll(boom, seeded, cfg, spy, NOW)
    assert not [s for s in spy.sent if "Radar" in s]
    spy = Spy()
    runner.poll(results(luma=[meetup_ev(source="luma", native_id="l1")], **ok), seeded, cfg, spy, NOW)
    assert any("Luma is working again" in s for s in spy.sent)


def test_empty_result_counts_as_broken_only_for_sources_that_always_have_events(cfg, seeded):
    for _ in range(6):
        runner.poll(results(), seeded, cfg, Spy(), NOW)
    assert seeded["sources"]["unstop"]["fails"] == 6 + 1  # +1 from the seeding run
    assert seeded["sources"]["gdg"]["fails"] == 0


def test_all_sources_down_does_not_send_a_startup_summary(cfg):
    state, spy = st.empty(), Spy()
    report = runner.poll({"luma": RuntimeError("network unavailable")}, state, cfg, spy, NOW)
    assert report.errors and not state["initialized"] and not spy.sent


def test_recovery_notification_retries_after_failed_send(cfg, seeded):
    seeded["sources"]["luma"] = {"fails": 6, "warned": True}
    ok = {"luma": [meetup_ev(source="luma")]}
    runner.poll(ok, seeded, cfg, Spy(fail=True), NOW)
    assert seeded["sources"]["luma"]["warned"]
    spy = Spy()
    runner.poll(ok, seeded, cfg, spy, NOW)
    assert "Luma is working again" in spy.sent[0]
    assert not seeded["sources"]["luma"]["warned"]


def test_past_events_are_pruned(cfg, seeded):
    runner.poll(results(gdg=[google()]), seeded, cfg, Spy(), NOW)
    assert seeded["events"]
    runner.poll(results(), seeded, cfg, Spy(), SOON + timedelta(days=8))
    assert seeded["events"] == {} and seeded["fps"] == {}


def test_state_round_trip_is_stable(tmp_path, cfg, seeded):
    runner.poll(results(gdg=[google()], meetup=[meetup_ev(spots_left=200)]), seeded, cfg, Spy(), NOW)
    p = tmp_path / "seen.json"
    assert st.save(p, seeded)
    loaded = st.load(p)
    # Spot counts change constantly upstream; they must not churn the state file.
    runner.poll(results(gdg=[google()], meetup=[meetup_ev(spots_left=150)]), loaded, cfg, Spy(), NOW)
    # (The fake results leave the other sources empty, which bumps their failure counters; ignore those.)
    loaded["sources"] = seeded["sources"]
    assert not st.save(p, loaded)


def test_office_visit_alert_has_its_own_badge(cfg, seeded):
    spy = Spy()
    runner.poll(results(gdg=[google()]), seeded, cfg, spy, NOW)
    assert spy.sent[0].startswith("🏢 <b>OFFICE VISIT · Google</b>\n<b>DevFest Bengaluru 2026</b>")
    assert "at Google office" in spy.sent[0]


def test_bundled_alerts_put_office_visits_first(cfg, seeded):
    cfg = {**cfg, "alerts": {**cfg["alerts"], "max_instant_per_run": 1}}
    hack = Event(source="unstop", native_id="h", title="Big Prize Hack", url="https://unstop.com/h", end=SOON,
                 city="Bangalore", kind="hackathon", prize_inr=500000, prize_data=True, tech_source=True,
                 team_min=1, team_max=4)
    spy = Spy()
    runner.poll(results(unstop=[hack], gdg=[google()]), seeded, cfg, spy, NOW)
    body = spy.sent[0]
    assert body.index("🏢 <b>Office visits</b>") < body.index("DevFest") < body.index("Other high-priority") < body.index("Big Prize")


def test_digest_lists_upcoming_office_visits_every_day_until_they_happen(cfg, seeded):
    runner.poll(results(gdg=[google()]), seeded, cfg, Spy(), NOW)  # alerted instantly, never queued
    assert seeded["queue"] == []
    for day in (1, 2):
        body = "\n".join(runner.digest(seeded, cfg, Spy(), NOW + timedelta(days=day)))
        assert "🏢 <b>Office visits</b>" in body and "DevFest Bengaluru 2026" in body and "at Google office" in body
    assert runner.digest(seeded, cfg, Spy(), SOON + timedelta(hours=1)) == []  # it has started: gone


def test_office_visit_section_comes_before_the_new_events(cfg, seeded):
    runner.poll(results(gdg=[google()], meetup=[meetup_ev()]), seeded, cfg, Spy(), NOW)
    body = "\n".join(runner.digest(seeded, cfg, Spy(), NOW + timedelta(hours=1)))
    assert body.index("Office visits") < body.index("Rust Systems Night")


def test_out_of_town_hackathon_with_online_first_round_reaches_the_digest(cfg, seeded):
    away = Event(source="unstop", native_id="q", title="Quasar 5.0", url="https://unstop.com/q", end=SOON,
                 city="Mumbai", mode="offline", kind="hackathon", prize_inr=300000, prize_data=True,
                 tech_source=True, team_min=2, team_max=4, screening=True,
                 rounds="Round 0 : PPT Submission Round (online) → Final Offline Round : 36 Hour Hackathon (in person)")
    runner.poll(results(unstop=[away]), seeded, cfg, Spy(), NOW)
    body = "\n".join(runner.digest(seeded, cfg, Spy(), NOW + timedelta(hours=1)))
    assert "🧳 <b>Outside Bangalore, online round first</b>" in body and "Quasar 5.0" in body
    assert "online round first · team 2–4" in body


def test_event_dropped_by_the_new_rules_leaves_every_digest_list(cfg, seeded):
    hack = Event(source="unstop", native_id="sf", title="StarForge", url="https://unstop.com/sf", end=SOON,
                 city="Bangalore", kind="hackathon", prize_inr=65000, prize_data=True, tech_source=True,
                 reg_deadline=NOW + timedelta(hours=30))
    runner.poll(results(unstop=[hack]), seeded, cfg, Spy(), NOW)
    assert seeded["queue"]
    hack.team_min, hack.team_max = 3, 4  # now we know it needs three people
    runner.poll(results(unstop=[hack]), seeded, cfg, Spy(), NOW)
    assert seeded["queue"] == [] and seeded["events"]["unstop:sf"]["dropped"]
    assert runner.digest(seeded, cfg, Spy(), NOW + timedelta(hours=1)) == []


def test_long_messages_never_end_on_a_section_header():
    from radar import messages
    lines = ["☀️ <b>Event digest</b>", ""] + [f"• item {i} " + "x" * 300 for i in range(12)] + \
            ["", "🧳 <b>Outside Bangalore, online round first</b>"] + [f"• away {i} " + "y" * 300 for i in range(6)]
    parts = messages.split(lines)
    assert len(parts) >= 2 and all(len(p) <= messages.LIMIT for p in parts)
    assert not any(p.rstrip().splitlines()[-1].startswith("🧳") for p in parts)
    assert any(p.startswith("🧳 <b>Outside Bangalore") for p in parts[1:])


def test_round_titles_are_cut_at_a_word():
    from radar.eligibility import Round, summary
    s = summary([Round("Build Phase (1 Jan – 10 Jan): Working on the problem statement released earlier", True)])
    assert s == "Build Phase (1 Jan – 10 Jan): Working on the problem… (online)"


def test_confirmed_corrections_combine_retry_and_skip_quiet_digest_events(cfg, seeded):
    original = google(venue="Campus Hall A", reg_deadline=NOW + timedelta(days=4))
    runner.poll(results(gdg=[original], meetup=[meetup_ev()]), seeded, cfg, Spy(), NOW)
    changed = google(venue="Campus Hall <B>", reg_deadline=NOW + timedelta(days=2))
    rep = runner.poll(results(gdg=[changed], meetup=[meetup_ev(venue="New hall")]), seeded, cfg, Spy(fail=True), NOW)
    assert rep.errors and not rep.corrected
    spy = Spy()
    rep = runner.poll(results(), seeded, cfg, spy, NOW)
    assert rep.corrected == [original.title] and len(spy.sent) == 1
    assert "Campus Hall A → Campus Hall &lt;B&gt;" in spy.sent[0] and "closes earlier" in spy.sent[0]
    assert not runner.poll(results(gdg=[changed]), seeded, cfg, Spy(), NOW).corrected


def test_corrections_require_same_listing_and_confirmed_values(cfg, seeded):
    ev = google(venue="Campus, North")
    twin = google(source="meetup", native_id="another", venue="Unrelated secondary venue")
    runner.poll(results(gdg=[ev]), seeded, cfg, Spy(), NOW)
    for feeds in [dict(gdg=[ev], meetup=[twin]), dict(meetup=[twin]), dict(gdg=[google(venue="TBD")]),
                  dict(gdg=[google(venue="CAMPUS NORTH")]), dict(gdg=[])]:
        assert not runner.poll(results(**feeds), seeded, cfg, Spy(), NOW).corrected
    twin.cancelled = True
    assert not runner.poll(results(meetup=[twin]), seeded, cfg, Spy(), NOW).corrected
    cancelled = google(cancelled=True, venue="Campus, North")
    spy = Spy()
    rep = runner.poll(results(gdg=[cancelled]), seeded, cfg, spy, NOW)
    assert rep.corrected == [ev.title] and "organizer has cancelled" in spy.sent[0]
    assert not runner.poll(results(gdg=[ev]), seeded, cfg, Spy(), NOW).corrected
    assert not runner.digest(seeded, cfg, Spy(), NOW)


def test_existing_alert_silently_establishes_baseline(cfg, seeded):
    ev = google(venue="Campus hall")
    runner.poll(results(gdg=[ev]), seeded, cfg, Spy(), NOW)
    seeded["events"][ev.id].pop("correction_baseline")
    rep = runner.poll(results(gdg=[google(venue="New building")]), seeded, cfg, Spy(), NOW)
    assert not rep.corrected
    assert runner.poll(results(gdg=[ev]), seeded, cfg, Spy(), NOW).corrected == [ev.title]
