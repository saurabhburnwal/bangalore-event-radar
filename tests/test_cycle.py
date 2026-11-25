from datetime import datetime, timedelta, timezone

import pytest

from radar import __main__ as cli
from radar import runner
from radar import state as st
from radar.notify import Console

START = datetime(2026, 11, 25, 3, 29, tzinfo=timezone.utc)  # 08:59 IST


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    now = [START]
    outcomes = {"gdg": []}
    calls = []
    path = tmp_path / "seen.json"
    monkeypatch.delenv("RADAR_PREVIOUS_DIGEST", raising=False)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]

    def collect(cfg, cache):
        calls.append(now[0])
        return outcomes.copy()

    monkeypatch.setattr(cli, "datetime", Clock)
    monkeypatch.setattr(cli.sources, "collect", collect)
    monkeypatch.setattr(cli, "telegram", Console)
    monkeypatch.setattr(cli.config, "load", lambda _: {})
    def run(trigger, *args):
        return cli.main(["--state", str(path), "cycle", trigger, *args])
    return run, path, now, outcomes, calls


def test_workflows_take_turns_and_roll_over_in_ist(cycle, monkeypatch):
    run, path, now, _, calls = cycle
    digests = []
    monkeypatch.setattr(runner, "digest", lambda *args: digests.append(now[0]) or [])
    assert run("digest") == 0
    assert len(calls) == 1 and not digests
    now[0] += timedelta(minutes=1)
    assert run("digest") == 0
    assert len(calls) == 1 and digests == [now[0]]
    assert run("poll") == 0
    now[0] += timedelta(hours=1)
    assert run("digest") == 0
    assert len(calls) == 3 and len(digests) == 1
    now[0] += timedelta(days=1)
    assert run("poll") == 0 and len(digests) == 2
    assert st.load(path)["last_digest_day"] == "2026-11-26"


def test_outage_empty_digest_remains_due(cycle):
    run, path, now, outcomes, _ = cycle
    now[0] += timedelta(hours=1)
    outcomes["gdg"] = RuntimeError()
    assert run("poll") == 1
    state = st.load(path)
    assert not state["last_digest_day"] and "last_usable" not in state["health"]
    outcomes["gdg"] = []
    assert run("digest") == 0
    assert st.load(path)["last_digest_day"] == "2026-11-25"


def test_outage_can_deliver_saved_queue(cycle):
    run, path, now, outcomes, _ = cycle
    state = st.empty()
    state["queue"] = [{"id": "g", "title": "Rust", "url": "https://meetup.com/rust", "source": "meetup",
                       "category": "Other events"}]
    st.save(path, state)
    now[0] += timedelta(hours=1)
    outcomes["gdg"] = RuntimeError()
    assert run("poll") == 1
    saved = st.load(path)
    assert saved["last_digest_day"] == "2026-11-25" and not saved["queue"]


def test_rollout_and_dry_run(cycle, monkeypatch):
    run, path, now, _, _ = cycle
    now[0] += timedelta(hours=1)
    monkeypatch.setenv("RADAR_PREVIOUS_DIGEST", now[0].isoformat())
    monkeypatch.setattr(runner, "digest", lambda *args: pytest.fail("already delivered today"))
    assert run("poll", "--dry-run") == 0
    assert not path.exists() and not path.with_name("status.json").exists()
    assert run("poll") == 0 and st.load(path)["last_digest_day"] == "2026-11-25"
