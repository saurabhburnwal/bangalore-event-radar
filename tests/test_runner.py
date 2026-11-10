"""Multi-run behaviour: no duplicate alerts, one filling-fast re-alert, digest, broken-source warnings."""
from datetime import datetime, timedelta, timezone

import pytest

from radar import runner
from radar import state as st
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


def test_broken_source_warns_once_and_recovers(cfg, seeded):
    seeded["sources"] = {}  # the seeding run saw every source empty
    # Give the other sources an event each so only Luma is broken.
    ok = {n: [meetup_ev(source=n, native_id=n)] for n in ("unstop", "devfolio", "meetup", "hasgeek")}
    boom = results(luma=RuntimeError("HTTP 403"), **ok)
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
