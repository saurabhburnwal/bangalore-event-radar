from datetime import datetime, timezone

import pytest
from conftest import data, text

from radar.models import Event
from radar.score import CAT_AWAY, CAT_HACK, CAT_NET, CAT_OFFICE, CAT_ONLINE, DIGEST, HIGH, IGNORE, Scorer
from radar.sources import hasgeek, luma, meetup, unstop

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
    v = score(ev(source="unstop", title="Remote Hiring Hack", mode="online", kind="hackathon", ppi=True,
                 prize_data=True, tech_source=True, team_min=1, team_max=2))
    assert v.tier == HIGH and v.category == CAT_ONLINE and "team 1–2" in v.reasons


def test_hybrid_hackathon_elsewhere_with_online_quiz_first_and_ppi_is_instant(score):
    # BuildSprint (Hyderabad, hybrid, solo): "Round 1 – Online Technical Quiz", finale at the organiser's office.
    bs = next(e for e in unstop.parse(data("unstop.json"))[0] if e.title == "BuildSprint")
    v = score(bs)
    assert v.tier == HIGH and v.category == CAT_AWAY
    assert v.reasons[:2] == ["internship/PPO offer", "online round first"] and "solo only" in v.reasons


def test_unstop_description_mentioning_internship_season_is_not_an_offer(score):
    eh = next(e for e in unstop.parse(data("unstop.json"))[0] if e.title.startswith("Expanding Horizons 8.0 Chemical"))
    assert score(eh).tier == IGNORE


def forge():
    return next(e for e in unstop.parse(data("unstop.json"))[0] if e.title == "The Forge")


def test_offline_hackathon_elsewhere_without_a_screening_round_is_ignored_even_with_ppi(score):
    e = forge()
    e.screening = False  # what Unstop's round list would say if there were no online round
    assert e.ppi and score(e).tier == IGNORE


def test_offline_hackathon_elsewhere_with_online_round_first_is_kept(score):
    # The Forge (Delhi): "Round 1: Online — …", then the shortlisted go to Delhi NCR. No round list here,
    # so the description decides.
    e = forge()
    assert e.screening is None
    v = score(e)
    assert v.tier == HIGH and v.category == CAT_AWAY and "online round first" in v.reasons


def test_offline_hackathon_elsewhere_with_screening_but_nothing_on_offer_is_ignored(score):
    v = score(ev(source="unstop", title="Small College Hack", city="Bidar", mode="offline", kind="hackathon",
                 prize_inr=30000, prize_data=True, tech_source=True, screening=True, team_min=2, team_max=4))
    assert v.tier == IGNORE


def test_offline_hackathon_elsewhere_with_screening_and_big_prize_goes_to_digest(score):
    v = score(ev(source="unstop", title="Quasar 5.0", city="Mumbai", mode="offline", kind="hackathon",
                 prize_inr=300000, prize_data=True, tech_source=True, screening=True, team_min=2, team_max=4))
    assert v.tier == DIGEST and v.category == CAT_AWAY
    assert v.reasons == ["₹3,00,000 prize pool", "online round first", "team 2–4"]


def test_hackathon_needing_three_or_more_is_ignored(score):
    v = score(ev(source="unstop", title="StarForge", city="Bangalore", mode="offline", kind="hackathon",
                 prize_inr=65000, prize_data=True, tech_source=True, team_min=3, team_max=4))
    assert v.tier == IGNORE and v.reasons == ["needs a team of 3+"]


def test_solo_and_pairs_only_hackathons_are_kept(score):
    for lo, hi, label in ((1, 1, "solo only"), (2, 2, "team of 2"), (1, 4, "team 1–4"), (2, 5, "team 2–5")):
        v = score(ev(source="unstop", title="Some Hack", city="Bangalore", kind="hackathon", tech_source=True,
                     prize_data=True, team_min=lo, team_max=hi))
        assert v.tier != IGNORE and label in v.reasons


def test_team_size_from_the_description_when_the_site_has_none(score):
    big_team = score(ev(source="meetup", title="Weekend Hackathon", city="Bengaluru",
                        description="Form teams of 3-4 members and build for 24 hours."))
    assert big_team.tier == IGNORE and big_team.reasons == ["needs a team of 3+"]
    unknown = score(ev(title="AI Tools that Earn: a hackathon by Apify", city="Bengaluru"))
    assert unknown.tier != IGNORE and "team size not listed" in unknown.reasons


def test_team_size_does_not_apply_to_meetups(score):
    v = score(ev(source="meetup", title="Kafka Meetup", city="Bengaluru", tech_source=True,
                 description="Come in teams of 5 from your company!"))
    assert v.tier == DIGEST and not any("team" in r for r in v.reasons)


def test_event_at_microsoft_office_is_an_office_visit(score):
    wis = next(e for e in hasgeek.parse(text("hasgeek.html")) if e.title.startswith("Women in Systems"))
    v = score(wis)
    assert v.tier == HIGH and v.office == "Microsoft" and v.category == CAT_OFFICE
    assert v.reasons[0] == "at Microsoft office"


def test_hackathon_finale_at_a_tech_giant_office_elsewhere_is_an_office_visit(score):
    v = score(ev(source="unstop", title="Build for Bharat", city="Hyderabad", mode="hybrid", kind="hackathon",
                 prize_data=True, tech_source=True, screening=True, team_min=1, team_max=3,
                 description="Round 1 is an online idea submission. The grand finale will be held at Google's Hyderabad office."))
    assert v.tier == HIGH and v.office == "Google" and v.reasons[0] == "finale at Google office"
    assert v.category == CAT_OFFICE and "online round first" in v.reasons


def test_finale_at_an_office_elsewhere_still_needs_a_screening_round(score):
    v = score(ev(source="unstop", title="Walk-in Hack", city="Hyderabad", mode="offline", kind="hackathon",
                 prize_data=True, tech_source=True, screening=False, venue="Google, Gachibowli"))
    assert v.tier == IGNORE


def test_office_visit_prize_on_an_online_hackathon(score):
    v = score(ev(source="unstop", title="Remote Design Sprint", mode="online", kind="hackathon", prize_data=True,
                 tech_source=True, perks="Office visit to Atlassian HQ for the winners / Goodies"))
    assert v.tier == HIGH and v.office == "Atlassian" and v.reasons[0] == "Atlassian office visit"


def test_in_person_event_organised_by_the_company_counts(score):
    v = score(ev(title="Gemini Builders Night", city="Bengaluru", venue="WeWork Galaxy", org="Google for Developers"))
    assert v.tier == HIGH and v.office == "Google" and v.reasons[0] == "organised by Google"


def test_student_club_with_a_brand_name_is_not_the_company(score):
    v = score(ev(title="Azure Study Jam", city="Bengaluru", venue="RV College",
                 org="Microsoft Learn Student Ambassadors RVCE"))
    assert not v.office and v.category != CAT_OFFICE


def test_online_event_run_by_the_company_is_not_an_office_visit(score):
    v = score(ev(title="Gemini API Office Hours Bengaluru", mode="online", org="Google for Developers"))
    assert v.tier == HIGH and not v.office and "hosted by Google" in v.reasons and v.category == CAT_NET


def test_description_naming_a_company_without_its_office_is_not_a_visit(score):
    v = score(ev(source="hasgeek", title="Serverless Workshop", city="Bengaluru", venue="91springboard", tech_source=True,
                 description="Hands-on with AWS Lambda. Speakers from Google and Microsoft."))
    assert not v.office and v.tier == DIGEST


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


@pytest.mark.parametrize("plan, screened", [
    ("Round 1: Online — Open Innovation in Cybersecurity. Round 2: Final Round — Delhi NCR.", True),
    ("Round 1 – Online Technical Quiz. Grand Finale at our office.", True),
    ("Round 1 - Ideation Round (Online Abstract). Round 2 is an in-person demo at IIT Bombay.", True),
    ("Round 1 - Online Submission (Screening). Round 2 - On-Campus Hackathon.", True),
    ("The Phase I (Idea submission round) is online and Phase II (Hackathon round) is offline.", True),
    ("Submit your PPT by 5 Dec; shortlisted teams come to campus.", True),
    ("Applications are reviewed and shortlisted teams will be notified.", False),  # profile review only
    ("Round 1 starts at 10 AM at the venue, Round 2 after lunch.", False),
])
def test_screening_round_phrasings_in_descriptions(score, plan, screened):
    e = ev(source="devfolio", title="Campus Hack", city="Pune", mode="offline", kind="hackathon", tech_source=True,
           prize_inr=200000, team_min=2, team_max=4, description=plan)
    assert (score(e).tier != IGNORE) is screened


def test_unstop_round_plan_past_the_description_cut_still_counts(score):
    listing = data("unstop.json")
    o = next(o for o in listing["data"]["data"] if o["title"] == "The Forge")
    o["details"] = "<p>" + "About the event. " * 120 + "</p><p>Round 1 - Online Submission (Screening): a concept note.</p>"
    e = next(e for e in unstop.parse(listing)[0] if e.title == "The Forge")
    assert "Online Submission" not in e.description and "Online Submission" in e.rounds
    v = score(e)
    assert v.tier == HIGH and "online round first" in v.reasons
