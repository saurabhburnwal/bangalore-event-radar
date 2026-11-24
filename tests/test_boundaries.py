from types import SimpleNamespace

import pytest
import requests

from radar import __main__ as cli
from radar import messages, state
from radar.http import Http, SourceError
from radar.models import Event
from radar.notify import Telegram
from radar.score import HIGH, Verdict
from radar.sources.details import cached_detail
from radar.util import https_url, parse_dt


def test_telegram_network_errors_omit_request_details(monkeypatch):
    telegram = Telegram("test-bot-token", "23")

    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("private transport details")

    monkeypatch.setattr(telegram.s, "post", unavailable)
    with pytest.raises(RuntimeError, match="Telegram getUpdates failed") as error:
        telegram.updates()
    assert "private transport details" not in str(error.value)
    assert error.value.__suppress_context__


def test_telegram_rate_limit_beyond_the_retry_budget_returns_promptly(monkeypatch):
    telegram = Telegram("test-bot-token", "23")
    reply = SimpleNamespace(status_code=429, headers={"content-type": "application/json"},
                            json=lambda: {"parameters": {"retry_after": 60}})
    monkeypatch.setattr(telegram.s, "post", lambda *a, **kw: reply)

    def unexpected_sleep(*args):
        pytest.fail("A long rate limit should return without sleeping")

    monkeypatch.setattr("radar.notify.time.sleep", unexpected_sleep)
    with pytest.raises(RuntimeError, match="rate-limited"):
        telegram.send("Example update")


def test_setup_pairs_only_the_chat_with_the_fresh_code(monkeypatch):
    writes = []
    token = "123:" + "a" * 32

    class Bot:
        def __init__(self, token, chat_id):
            pass

        def _call(self, method, payload):
            return {"result": {"username": "radar_bot"}}

        def updates(self, offset):
            return [
                {"update_id": 1, "message": {"chat": {"type": "private", "id": 10}, "text": "hello"}},
                {"update_id": 2, "message": {"chat": {"type": "private", "id": 20}, "text": "pairing-code"}},
                {"update_id": 3, "message": {"chat": {"type": "private", "id": 30}, "text": "hello"}},
            ]

        def send(self, text):
            pass

    def secret_set(args, *, input, **kwargs):
        writes.append((args[-1], input))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli, "Telegram", Bot)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "gh")
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: token)
    monkeypatch.setattr(cli.secrets, "token_urlsafe", lambda _: "pairing-code")
    monkeypatch.setattr(cli.subprocess, "run", secret_set)
    assert cli.cmd_setup(None) == 0
    assert writes == [("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", "20")]


def test_source_urls_and_alert_links_are_checked_before_use():
    url = "https://gdg.community.dev/events/details/sample/"
    assert https_url(url, "gdg") == url
    assert https_url("https://example.org/", "gdg") == ""
    with Http("gdg") as http, pytest.raises(SourceError, match="unexpected source URL"):
        http.text("https://example.org/")
    event = Event("gdg", "a", "Test event", "https://example.org/")
    page, = messages.bundle([(event, Verdict(HIGH))], "New events")
    assert "Test event" in page.text and "<a " not in page.text


def test_oversized_fields_fit_in_a_rendered_message():
    event = Event("gdg", "a", "&" * 9000, "https://gdg.community.dev/event", venue="&" * 9000)
    page, = messages.bundle([(event, Verdict(HIGH, ["&" * 9000]))], "New events")
    assert len(page.text) <= messages.LIMIT and "…" in page.text


def test_unexpected_feed_field_types_are_normalized():
    assert parse_dt(42) is None
    event = Event("devfolio", "a", "Test event", "", spots_left="12", team_min="2", team_max=[])
    assert (event.spots_left, event.team_min, event.team_max) == (12, 2, None)


def test_detail_cache_retries_and_preserves_the_last_good_detail(monkeypatch):
    cache = {}
    now = [5]
    monkeypatch.setattr("radar.sources.details.time.time", lambda: now[0])

    def unavailable():
        raise SourceError("HTTP 503")

    assert cached_detail(cache, "event", 1, unavailable) == {} and not cache
    assert cached_detail(cache, "event", 1, lambda: {"venue": "First"})["venue"] == "First"
    now[0] += 6 * 60 * 60 + 1
    assert cached_detail(cache, "event", 1, unavailable)["venue"] == "First"
    assert cached_detail(cache, "event", 1, lambda: {"venue": "Updated"})["venue"] == "Updated"


def test_interrupted_state_replacement_preserves_the_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "seen.json"
    snapshot = state.empty()
    assert state.save(path, snapshot)
    snapshot["initialized"] = True

    def unavailable(*args):
        raise OSError("replace failed")

    monkeypatch.setattr("radar.state.os.replace", unavailable)
    with pytest.raises(OSError, match="replace failed"):
        state.save(path, snapshot)
    assert not state.load(path)["initialized"]
    assert list(tmp_path.iterdir()) == [path]
