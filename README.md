# Bangalore Event Radar

Schedules checks of Luma, Meetup, Unstop, Devfolio, Google Developer Groups, Hasgeek and Hackbriven every 10 minutes
for Bangalore tech events, and tells you on Telegram:

- **🏢 Office visits, right away** — anything that gets you inside a tech giant's office (Google, Microsoft,
  Atlassian, IBM…): held there, a hackathon finale there (even in another city), an office visit as the prize,
  or an in-person event the company itself organises. These also stay listed at the top of every digest until
  they happen.
- **Right away** — hackathons with an internship / PPI / PPO prize, DevFests, Bangalore hackathons with
  ₹1 lakh+ in prizes, and anything relevant that is **filling fast** (one follow-up when spots run low).
- **In a 09:00 digest** — every other relevant tech event, grouped into Hackathons / Big-tech &
  networking / Other / Outside Bangalore / Online, plus registrations closing within 72 hours and reminders
  before yearly programs (Hacktoberfest, GSoC, Flipkart GRiD…).

Hackathons are only kept if **you can enter solo or as a pair** (the minimum team size is 2 or less). Unstop,
Devfolio and Hackbriven list team sizes; for other sites the description is checked ("teams of 3–4"), and if
it says nothing the event is kept and tagged *team size not listed*.

**Offline hackathons outside Bangalore** are kept only when an **online round comes first** (idea/PPT
submission, online test…), so you travel only once shortlisted, and only with an internship/PPO, ₹1 lakh+
in prizes, or an office visit. Plain application/profile review doesn't count as a screening round.

It runs free on GitHub Actions, so it keeps working while your laptop is off.

## Setup (one time, ~3 minutes)

1. **Create the bot.** In Telegram, open **@BotFather** → `/newbot` → pick a name and a username ending in `bot`.
   It replies with a token like `123456789:AAH…`.
2. **Connect it** (from this folder, in a real terminal):
   ```sh
   python -m venv .venv && .venv/bin/pip install -r requirements.txt   # first time only
   .venv/bin/python -m radar setup
   ```
   Paste the token when asked (it's hidden), open your bot's private chat, and press **Start** if prompted.
   Send the pairing code shown in the terminal. The command verifies your chat, saves both as GitHub repo secrets
   (needs `gh`, logged in), and sends you a confirmation message.
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
| A different team size | `my_team_size` (you enter solo or in a team of this many) |
| Catch more ways of describing an online first round | add a phrase to `screening_keywords` |
| More/fewer companies counted as tech giants | `big_tech` |
| Fewer remote alerts | `online_ppi_instant: false` (remote and out-of-town internship hackathons go to the digest) |
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
  GDG embed their data in the page; Hasgeek is read from its HTML. Devfolio's city and team size, GDG's venue
  and the round list of each in-person Unstop hackathon come from the event's own page. Devfolio and GDG
  refresh their cached details every six hours. Unstop refreshes details when an event is edited, up to 40
  per poll. Failed detail reads are eligible for retry.
- `radar/eligibility.py` — team sizes read from text, and whether an online round decides who goes on to the
  in-person part.
- `radar/score.py` — keyword rules from `config.yaml` decide instant / digest / ignore, with a reason for each.
- `radar/runner.py` — de-duplicates events listed on several sites, remembers what was already sent in
  `state/seen.json` (committed back by the workflow), and warns you after a site fails six polls in a row by default.

## Limits

- Events announced only on LinkedIn, X, Instagram or WhatsApp groups aren't covered.
- Luma's city page is curated; follow specific community calendars in config for full coverage.
- GitHub can delay or drop scheduled runs. Manually run the `poll` workflow on the default branch for an on-demand check.
- Yearly-program dates are approximate; update them in config once the official dates are out.

## Poll coverage

[View live feed status](https://saurabhburnwal.github.io/bangalore-event-radar/) for the last usable check, per-feed freshness, hourly coverage, and longest gap. The browser marks a feed stale after 60 minutes. Quiet hours appear on this page.

Both GitHub workflows can catch up overdue work. The digest workflow polls first if the last usable check is at least an hour old. The first workflow after 09:00 IST sends any due digest once per day and resumes interrupted deliveries. Open the poll workflow and select **Run workflow** for an immediate check.

A partial feed means one or more listing pages failed. Events from readable pages still reach scoring and the next poll retries the configured pages. Counts on the status page describe listings before cross-site de-duplication.

Previously instant-alerted events can trigger one correction when a confirmed venue moves, registration closes earlier, or the organizer explicitly reports cancellation. Missing listings and unconfirmed fields do not trigger corrections. Some feeds remove cancelled events without publishing a cancellation signal.
