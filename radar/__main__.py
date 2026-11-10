"""Command line: python -m radar {setup,run,digest,test-notify,telegram-chat-id} [--dry-run]"""
from __future__ import annotations

import argparse
import copy
import getpass
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config, messages, runner, sources
from . import state as st
from .http import Http
from .models import Event
from .notify import Console, Telegram
from .score import HIGH, Verdict


def telegram() -> Telegram:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set (or use --dry-run).")
    return Telegram(token, chat)


def print_scored(results: dict, scored: list[tuple[Event, Verdict]], verbose: bool) -> None:
    print("Sources:")
    for name, res in results.items():
        if isinstance(res, Exception):
            print(f"  ✗ {name:11} FAILED  {type(res).__name__}: {str(res)[:120]}")
        else:
            flag = "" if res or name in sources.MAY_BE_EMPTY else "   ← no events, check this source"
            print(f"  ✓ {name:11} {len(res):3} events{flag}")
    tiers = Counter(v.tier for _, v in scored)
    print(f"\nScored {len(scored)} unique events: {tiers.get('HIGH', 0)} instant, "
          f"{tiers.get('DIGEST', 0)} digest, {tiers.get('IGNORE', 0)} ignored\n")
    for tier in ("HIGH", "DIGEST") + (("IGNORE",) if verbose else ()):
        rows = sorted([x for x in scored if x[1].tier == tier], key=lambda x: -x[1].score)
        if rows:
            print(f"── {tier} ──")
        for ev, v in rows:
            when = ev.when.strftime("%d %b") if ev.when else "      "
            print(f"  {when}  [{ev.source:10}] {ev.title[:60]:60}  {'; '.join(v.reasons)}")
        if rows:
            print()


def cmd_run(args) -> int:
    cfg = config.load(args.config)
    state = st.load(args.state)
    work = copy.deepcopy(state) if args.dry_run else state
    notifier = Console() if args.dry_run else telegram()
    results = sources.collect(Http(), cfg, work["cache"])
    now = datetime.now(timezone.utc)
    report = runner.poll(results, work, cfg, notifier, now)
    if args.dry_run:
        print_scored(results, report.scored, args.verbose)
        print(f"Would alert {len(report.alerted)}, re-alert {len(report.filling)} filling fast, "
              f"queue {len(report.queued)} for the digest. State not written.")
        return 0
    wrote = st.save(args.state, state)
    print(f"alerted={len(report.alerted)} filling={len(report.filling)} queued={len(report.queued)} "
          f"state_changed={wrote} errors={len(report.errors)}")
    for e in report.errors:
        print("error:", e, file=sys.stderr)
    return 1 if report.errors else 0


def cmd_digest(args) -> int:
    cfg = config.load(args.config)
    state = st.load(args.state)
    work = copy.deepcopy(state) if args.dry_run else state
    notifier = Console() if args.dry_run else telegram()
    sent = runner.digest(work, cfg, notifier, datetime.now(timezone.utc))
    if not sent:
        print("Nothing to send today.")
    if not args.dry_run:
        st.save(args.state, state)
    return 0


def cmd_test_notify(args) -> int:
    ev = Event(source="gdg", native_id="test", title="Sample: GSoC Meetup @Google Ananta",
               url="https://gdg.community.dev/gdg-bangalore/", start=datetime.now(timezone.utc),
               city="Bengaluru", venue="Google Ananta", host="GDG Bangalore")
    v = Verdict(HIGH, ["Google venue/host", "filling fast (18 spots left)"])
    text = "🧪 <i>Test alert from your event radar</i>\n\n" + messages.alert(ev, v)
    (Console() if args.dry_run else telegram()).send(text, ev.url)
    print("Sent." if not args.dry_run else "")
    return 0


def cmd_chat_id(args) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit("Set TELEGRAM_BOT_TOKEN first.")
    chats = {}
    for u in Telegram(token, "").updates():
        msg = u.get("message") or u.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            chats[chat["id"]] = chat.get("username") or chat.get("title") or chat.get("first_name") or ""
    if not chats:
        print("No messages yet. Open your bot in Telegram, press Start (or send it any message), then run this again.")
        return 1
    for cid, name in chats.items():
        print(f"chat id: {cid}   ({name})")
    return 0


def cmd_setup(args) -> int:
    """Connect Telegram: ask for the bot token (hidden), find your chat, store both as GitHub repo secrets."""
    if not shutil.which("gh"):
        sys.exit("This needs the GitHub CLI (gh), logged in.")
    token = getpass.getpass("Paste the bot token from @BotFather (input is hidden): ").strip()
    if not re.fullmatch(r"\d+:[\w-]{30,}", token):
        sys.exit("That doesn't look like a bot token (it looks like 123456789:AAH...). Nothing was saved.")
    bot = Telegram(token, "")
    try:
        me = bot._call("getMe", {})["result"]
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Telegram rejected the token ({e}). Nothing was saved.")
    print(f"\nBot found: @{me['username']}")
    print(f"Now open https://t.me/{me['username']} in Telegram and press Start (or send it any message).")
    print("Waiting for your message", end="", flush=True)
    chat = None
    for _ in range(90):  # up to ~3 minutes
        for u in reversed(bot.updates()):
            c = (u.get("message") or {}).get("chat") or {}
            if c.get("type") == "private" and c.get("id"):
                chat = c
                break
        if chat:
            break
        print(".", end="", flush=True)
        time.sleep(2)
    print()
    if not chat:
        sys.exit("No message arrived. Press Start in the bot chat, then run this again. Nothing was saved.")
    print(f"Got it — chat with {chat.get('first_name') or chat.get('username') or 'you'}.")
    for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", str(chat["id"]))):
        r = subprocess.run(["gh", "secret", "set", name], input=value, text=True,
                           capture_output=True, cwd=config.ROOT)
        if r.returncode:
            sys.exit(f"Couldn't save {name} as a repo secret: {r.stderr.strip()}")
    print("Saved TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub repo secrets.")
    Telegram(token, str(chat["id"])).send("✅ <b>Event radar connected.</b> Alerts will arrive in this chat.")
    print("Sent a confirmation message to your Telegram. Done!")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="radar", description="Bangalore tech-event radar")
    p.add_argument("--config", default=config.DEFAULT_CONFIG)
    p.add_argument("--state", default=config.DEFAULT_STATE, type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="connect Telegram and store the secrets in the GitHub repo")
    r = sub.add_parser("run", help="check every source; alert on new high-priority events")
    r.add_argument("--dry-run", action="store_true", help="print instead of sending; don't write state")
    r.add_argument("-v", "--verbose", action="store_true", help="with --dry-run, also list ignored events")
    d = sub.add_parser("digest", help="send the daily digest")
    d.add_argument("--dry-run", action="store_true")
    t = sub.add_parser("test-notify", help="send a sample alert to Telegram")
    t.add_argument("--dry-run", action="store_true")
    sub.add_parser("telegram-chat-id", help="print the chat id of whoever messaged your bot")
    args = p.parse_args(argv)
    return {"setup": cmd_setup, "run": cmd_run, "digest": cmd_digest, "test-notify": cmd_test_notify,
            "telegram-chat-id": cmd_chat_id}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
