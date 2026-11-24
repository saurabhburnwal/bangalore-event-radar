"""Telegram delivery, plus a console stand-in for dry runs."""
from __future__ import annotations

import html
import re
import time

import requests

from .util import https_url

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.s = requests.Session()
        self.send_deadline: float | None = None

    def _call(self, method: str, payload: dict) -> dict:
        for attempt in range(3):
            remaining = self.send_deadline - time.monotonic() if self.send_deadline is not None else 10
            if remaining <= 0:
                raise RuntimeError("Telegram delivery time limit reached")
            try:
                r = self.s.post(API.format(token=self.token, method=method), json=payload,
                                timeout=min(10, remaining), allow_redirects=False)
                data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            except (requests.RequestException, ValueError):
                raise RuntimeError(f"Telegram {method} failed during transport or response decoding") from None
            if not isinstance(data, dict):
                raise RuntimeError(f"Telegram {method} returned an invalid response")
            if r.status_code == 429:
                parameters = data.get("parameters")
                delay = parameters.get("retry_after", 3) if isinstance(parameters, dict) else 3
                if attempt < 2 and isinstance(delay, int) and 0 <= delay <= 5 and delay + 1 < remaining:
                    time.sleep(delay + 1)
                    continue
                raise RuntimeError(f"Telegram {method} rate-limited (HTTP 429)")
            if not 200 <= r.status_code < 300 or data.get("ok") is not True:
                raise RuntimeError(f"Telegram {method} failed (HTTP {r.status_code})")
            return data
        raise AssertionError("unreachable")

    def send(self, text: str, button_url: str | None = None, button_text: str = "Register →") -> None:
        if self.send_deadline is None:
            self.send_deadline = time.monotonic() + 120
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if button_url and https_url(button_url):
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
        self._call("sendMessage", payload)

    def updates(self, offset: int | None = None) -> list[dict]:
        return self._call("getUpdates", {"offset": offset} if offset is not None else {}).get("result", [])


class Console:
    """Prints what would be sent. Used by --dry-run."""

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text: str, button_url: str | None = None, button_text: str = "Register →") -> None:
        plain = html.unescape(re.sub(r"<[^>]+>", "", text))
        if button_url:
            plain += f"\n[{button_text}] {button_url}"
        self.sent.append(plain)
        print("┌─ would send ─────────────────────────────")
        for line in plain.splitlines():
            print("│ " + line)
        print("└──────────────────────────────────────────")
