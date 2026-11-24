"""Team sizes read from text, and screening rounds read from round lists."""
import pytest

from radar.eligibility import Round, has_screening, round_mode, summary, team_from_text, team_label


@pytest.mark.parametrize("text, expected", [
    ("Teams of 2-4 members can register.", (2, 4)),
    ("Team size: 1 – 3", (1, 3)),
    ("Form a team of two to four people", (2, 4)),
    ("Each team must have 3-5 members.", (3, 5)),
    ("Teams can have between 2 and 4 participants", (2, 4)),
    ("Team size: up to 4", (1, 4)),
    ("teams of maximum 3", (1, 3)),
    ("A minimum of 3 members is required", (3, None)),
    ("Compete in teams of 4.", (4, 4)),
    ("Open to individuals or teams!", (1, None)),
    ("Individual participation only.", (1, None)),
    ("Win prizes worth 2 lakh. 36 hours of hacking.", None),
    ("Top 3 teams win swag.", None),
    ("", None),
])
def test_team_from_text(text, expected):
    assert team_from_text(text) == expected


def test_team_labels():
    assert team_label(1, 1) == "solo only"
    assert team_label(2, 2) == "team of 2"
    assert team_label(1, 4) == "team 1–4"
    assert team_label(3, None) == "team of 3+"
    assert team_label(1, None) == "solo allowed"


def test_title_overrides_the_sites_round_label():
    assert round_mode(Round("Round 1 (Online round-Free Participation)", online=False)) is True
    assert round_mode(Round("Round 2 – Offline Grand Finale", online=True)) is False
    assert round_mode(Round("Finals at IIT Madras", online=True)) is False
    assert round_mode(Round("Prelims", online=True)) is True


def test_online_submission_before_campus_finale_is_screening():
    rounds = [Round("Round 1 (Idea Submission)", True, True), Round("Round 2 (Online Meet Based Evaluation)", True, True),
              Round("Round 3 (On-Campus Product Development Sprint)", False)]
    assert has_screening(rounds)
    assert summary(rounds).startswith("Round 1 (Idea Submission) (online) → ")


def test_a_lone_online_round_counts_only_if_it_eliminates_or_the_event_is_hybrid():
    assert has_screening([Round("Abstract Submission (through Unstop)", True, eliminator=True)])
    assert not has_screening([Round("Build Phase", True)])
    assert has_screening([Round("Build Phase", True)], hybrid=True)


def test_offline_only_and_paperwork_steps_are_not_screening():
    assert not has_screening([Round("Offline Round", False)])
    assert not has_screening([Round("Registration", False), Round("Join our official WhatsApp group", True),
                              Round("Offline Round", False)])
    assert not has_screening([Round("Profile Review & Registration Form", True), Round("Grand Finale", None)])


def test_registration_step_before_an_online_evaluation_still_counts():
    rounds = [Round("Registration", False), Round("Round 1: Online Evaluation", False, True),
              Round("Round 2: AI VIBEATHON – Offline Finale", False, True)]
    assert has_screening(rounds)


@pytest.mark.parametrize("first_round", [Round("Offline qualifier", False), Round("Qualifier", None)])
def test_online_screening_must_precede_any_round_that_could_require_travel(first_round):
    rounds = [first_round, Round("Online pitch", True, eliminator=True), Round("Offline final", False)]
    assert not has_screening(rounds, hybrid=True)
