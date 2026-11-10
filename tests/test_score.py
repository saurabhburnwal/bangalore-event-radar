from datetime import datetime, timezone

import pytest
from conftest import data, text

from radar.models import Event
from radar.score import CAT_HACK, CAT_ONLINE, DIGEST, HIGH, IGNORE, Scorer
from radar.sources import luma, meetup, unstop

T = datetime(2026, 11, 21, 4, 30, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def score(cfg):
    return Scorer(cfg)


def ev(**kw):
    base = dict(source="luma", native_id="x", title="Event", url="https://example.com", start=T)
    base.update(kw)
    return Event(**base)


def test_google_office_gdg_event_is_instant(score):
    v = score(ev(source="gdg", title="GSoC Meetup @Google Ananta", city="Bangalore", tech_source=True))
    assert v.tier == HIGH and any("Google" in r for r in v.reasons)


def test_gdg_event_at_google_venue_is_instant(score):
    v = score(ev(source="gdg", title="Flutter Meetup", city="Bengaluru", tech_source=True,
                 venue="Google Ananta, Rio Business Park, Mahadevapura"))
    assert v.tier == HIGH


def test_bangalore_hackathon_with_ppi_is_instant(score):
    v = score(ev(source="unstop", title="Some Hackathon", city="Bengaluru", kind="hackathon",
                 ppi=True, prize_data=True, tech_source=True))
    assert v.tier == HIGH and "internship/PPO offer" in v.reasons and v.category == CAT_HACK


def test_walking_club_is_ignored(score):
    walking = next(e for e in luma.parse(data("luma.json")) if "Walking Club" in e.title)
    assert score(walking).tier == IGNORE


def test_okta_developer_connect_goes_to_digest(score):
    v = score(ev(title="Okta Developer Connect Bengaluru", city="Bengaluru", org="Okta for Developers"))
    assert v.tier == DIGEST


def test_online_hackathon_without_offer_is_ignored(score):
    v = score(ev(source="unstop", title="Tiny Online Hack", mode="online", kind="hackathon",
                 prize_inr=5000, prize_data=True, tech_source=True))
    assert v.tier == IGNORE


def test_online_hackathon_with_structured_ppi_is_instant(score):
    bs = next(e for e in unstop.parse(data("unstop.json"))[0] if e.title == "BuildSprint")
    v = score(bs)
    assert v.tier == HIGH and v.category == CAT_ONLINE


def test_unstop_description_mentioning_internship_season_is_not_an_offer(score):
    eh = next(e for e in unstop.parse(data("unstop.json"))[0] if e.title.startswith("Expanding Horizons 8.0 Chemical"))
    assert score(eh).tier == IGNORE


def test_offline_hackathon_elsewhere_is_ignored_even_with_ppi(score):
    forge = next(e for e in unstop.parse(data("unstop.json"))[0] if e.title == "The Forge")
    assert forge.ppi and score(forge).tier == IGNORE


def test_ibm_meetup_with_few_spots_is_instant_and_filling(score):
    ibm = next(e for e in meetup.parse(text("meetup.html")) if e.title.startswith("[in-person] Polyglot"))
    v = score(ibm)
    assert v.tier == HIGH and v.filling and any("IBM" in r for r in v.reasons)


def test_aws_in_title_at_a_college_is_not_big_tech(score):
    e = next(e for e in meetup.parse(text("meetup.html")) if e.title.startswith("AWS Cloud Quest"))
    assert score(e).tier == DIGEST


def test_luma_event_filling_fast_escalates(score):
    v = score(ev(title="Rust Systems Night", city="Bengaluru", spots_left=12))
    assert v.tier == HIGH and v.filling


def test_sold_out_is_not_filling(score):
    v = score(ev(title="Rust Systems Night", city="Bengaluru", spots_left=0, sold_out=True))
    assert v.tier == DIGEST and not v.filling and "full — waitlist only" in v.reasons


def test_big_bangalore_prize_is_instant(score):
    v = score(ev(source="unstop", title="Inceptrix 3.0", city="Bangalore", mode="hybrid", kind="hackathon",
                 prize_inr=250000, prize_data=True, tech_source=True))
    assert v.tier == HIGH and "₹2,50,000 prize pool" in v.reasons


def test_restricted_event_is_ignored(score):
    crown = next(e for e in meetup.parse(text("meetup_hackathon.html")) if e.title == "Crown Royale")
    assert score(crown).tier == IGNORE


def test_call_for_proposals_is_ignored(score):
    v = score(ev(source="hasgeek", title="Rootconf 2026 Annual Conference: Call for Proposals",
                 city="Bangalore & Hybrid", tech_source=True))
    assert v.tier == IGNORE


def test_non_tech_bangalore_event_is_ignored(score):
    assert score(ev(title="Sunday Brunch Social", city="Bengaluru")).tier == IGNORE


def test_event_closed_to_your_college_is_kept(score):
    v = score(ev(source="meetup", title="CodeSprint", city="Bengaluru", tech_source=True,
                 description="A coding contest. This event is exclusively open to CHRIST (Deemed to be University) students."))
    assert v.tier != IGNORE and "open to your college only" in v.reasons


def test_event_closed_to_another_college_is_still_ignored(score):
    v = score(ev(source="meetup", title="CodeSprint", city="Bengaluru", tech_source=True,
                 description="This event is exclusively open to RV University students. Judges from Christ University."))
    assert v.tier == IGNORE


def test_event_held_at_your_college_is_tagged(score):
    v = score(ev(source="unstop", title="Hack Christ", city="Bangalore", kind="hackathon", tech_source=True,
                 prize_data=True, venue="Christ University, Hosur Road"))
    assert "at your college" in v.reasons


def test_students_of_your_college_phrasing_is_kept(score):
    v = score(ev(source="meetup", title="Cloud Jam", city="Bengaluru", tech_source=True,
                 description="Only for students of Christ University, Bangalore. Bring your laptop."))
    assert v.tier != IGNORE and "open to your college only" in v.reasons
