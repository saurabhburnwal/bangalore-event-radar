"""Telegram delivery, plus a console stand-in for dry runs."""
from __future__ import annotations

import html
import re
import time

import requests

API = "https://api.telegram.org/bot{token}/{method}"


class Telegram:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.s = requests.Session()

    def _call(self, method: str, payload: dict) -> dict:
        for attempt in range(3):
            r = self.s.post(API.format(token=self.token, method=method), json=payload, timeout=20)
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 429:
                time.sleep(int((data.get("parameters") or {}).get("retry_after", 3)) + 1)
                continue
            if not data.get("ok"):
                # Never include the token in errors: it is part of the URL, not the message.
                raise RuntimeError(f"Telegram {method} failed: {r.status_code} {data.get('description', '')}")
            return data
        raise RuntimeError(f"Telegram {method} rate-limited three times")

    def send(self, text: str, button_url: str | None = None, button_text: str = "Register →") -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if button_url:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
        self._call("sendMessage", payload)

    def updates(self) -> list[dict]:
        return self._call("getUpdates", {}).get("result", [])


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
