# Bangalore Event Radar

Checks Luma, Meetup, Unstop, Devfolio, Google Developer Groups, Hasgeek and Hackbriven every 10 minutes
for Bangalore tech events, and tells you on Telegram:

- **Right away** — hackathons with an internship / PPI / PPO prize, events at big-tech offices (Google,
  Microsoft, Atlassian, IBM…), DevFests, Bangalore hackathons with ₹1 lakh+ in prizes, and anything
  relevant that is **filling fast** (one follow-up when spots run low).
- **In a 09:00 digest** — every other relevant tech event, grouped into Hackathons / Big-tech &
  networking / Other, plus registrations closing within 72 hours and reminders before yearly programs
  (Hacktoberfest, GSoC, Flipkart GRiD…).

It runs free on GitHub Actions, so it keeps working while your laptop is off.

## Setup (one time, ~3 minutes)

1. **Create the bot.** In Telegram, open **@BotFather** → `/newbot` → pick a name and a username ending in `bot`.
   It replies with a token like `123456789:AAH…`.
2. **Connect it** (from this folder, in a real terminal):
   ```sh
   python -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only
   .venv/bin/python -m radar setup
   ```
   Paste the token when asked (it's hidden), then press **Start** in your bot's chat. The command finds your
   chat id, saves both as GitHub repo secrets (needs `gh`, logged in), and sends you a confirmation message.
   The token never touches your shell history.
3. **Turn the checks on:**
   ```sh
   gh workflow enable poll.yml && gh workflow enable digest.yml
   gh workflow run poll.yml
   ```
   The first run sends one "what's open right now" summary; after that you only hear about new things.

## Tuning

Everything is in [`config.yaml`](config.yaml): the Bangalore area names, big-tech list, prize thresholds,
keyword lists, which GDG chapters and Luma calendars to follow, and the yearly-program dates. Edit it,
push, and the next run uses it. The `tests` workflow checks your edit didn't break anything.

Useful switches:

| Want | Change |
|---|---|
| Fewer remote alerts | `online_ppi_instant: false` (remote internship hackathons go to the digest) |
| More/fewer "filling fast" | `filling_spots` |
| Follow a Luma community | add its `cal-…` id under `sources.luma.calendars` |
| Silence a kind of event | add a word to `deny_keywords` |

## Commands

```sh
python -m radar run --dry-run      # fetch everything, print what would be sent, change nothing
python -m radar run --dry-run -v   # …including what was ignored and why
python -m radar digest --dry-run   # preview tomorrow's digest
python -m radar test-notify        # send a sample alert to your phone
python -m pytest -q
```

## How it works

- `radar/sources/` — one reader per site. Luma, Unstop and Hackbriven have JSON APIs; Meetup, Devfolio and
  GDG embed their data in the page; Hasgeek is read from its HTML. Devfolio's city and GDG's venue come from
  each event's own page, fetched once and cached.
- `radar/score.py` — keyword rules from `config.yaml` decide instant / digest / ignore, with a reason for each.
- `radar/runner.py` — de-duplicates events listed on several sites, remembers what was already sent in
  `state/seen.json` (committed back by the workflow), and warns you if a site stops returning events for
  about an hour, so a broken reader never fails silently.

## Limits

- Events announced only on LinkedIn, X, Instagram or WhatsApp groups aren't covered.
- Luma's city page is curated; follow specific community calendars in config for full coverage.
- GitHub sometimes starts scheduled runs a few minutes late at busy times.
- Yearly-program dates are approximate; update them in config once the official dates are out.
