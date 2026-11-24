# Bangalore Event Radar Audit

The highest-priority findings affect Telegram credential handling, outbound requests, and alert delivery. Event reconciliation can also suppress valid alerts or retain obsolete entries. The review covers the Python CLI, seven source adapters, Telegram messages, persisted state, and GitHub Actions. The baseline suite passed all 107 tests.

## Findings

| Priority | Finding | Impact and fix |
| --- | --- | --- |
| High | Telegram transport errors expose request details | Network exceptions can include the bot token and flow into CLI errors or tracebacks. Report bounded, credential-free Telegram errors. [notify.py](radar/notify.py) |
| High | Telegram setup accepts an unrelated message | Setup picks a private chat from the bot's update history without proving that it belongs to the person configuring the radar. Require a fresh pairing code before saving the chat. [__main__.py](radar/__main__.py) |
| High | Source fetches and published links lack destination checks | Source-provided detail URLs and redirects can leave the expected provider, and registration links are forwarded without checking their destination. Validate HTTPS destinations at each fetch and when rendering links. [http.py](radar/http.py) · [gdg.py](radar/sources/gdg.py) · [messages.py](radar/messages.py) |
| High | Source and Telegram requests can exhaust the workflow timeout | Serial detail requests, retries, unbounded response bodies, and long Telegram rate-limit waits can prevent a run from finishing. Cap response sizes and elapsed fetch time, and bound Telegram retries. [http.py](radar/http.py) · [notify.py](radar/notify.py) |
| High | Partial sends replay delivered messages | An interruption after the first page of a bundle or digest leaves its delivery state unrecorded. Save confirmed deliveries per page and resume from subsequent pages or rows. [runner.py](radar/runner.py) · [__main__.py](radar/__main__.py) |
| High | State can be truncated or read from an older workflow revision | A direct file write can leave an invalid JSON file. A queued workflow can check out an older revision, and the default concurrency queue can replace a waiting digest with a poll. Replace the state file atomically, read the current default branch after concurrency admission, and retain pending jobs. [state.py](radar/state.py) · [poll.yml](.github/workflows/poll.yml) · [digest.yml](.github/workflows/digest.yml) · [GitHub concurrency documentation](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) |
| Medium | Stale details and misleading source health | Devfolio and GDG cache failed detail fetches, and successful details can stay stale indefinitely. A complete source outage can report a successful poll, and a failed recovery notification is dropped. Refresh successful details, retry failures, and report outage and recovery outcomes accurately. [devfolio.py](radar/sources/devfolio.py) · [gdg.py](radar/sources/gdg.py) · [runner.py](radar/runner.py) |
| Medium | Event identity and pending digest entries diverge | Equal fingerprints can conflate distinct listings. When the source changes, a queued entry can retain an old identifier or old metadata, so promotion and withdrawal can miss it. Track source IDs against the canonical record and refresh pending entries. [runner.py](radar/runner.py) · [state.py](radar/state.py) |
| Medium | Closed and expired listings can still be advertised | Polling scores past events and closed registrations. The digest can also display stale queue entries and omit the time of a midnight deadline. Check availability before delivery and display the exact deadline. [runner.py](radar/runner.py) · [messages.py](radar/messages.py) |
| Medium | Feed values and message fields are insufficiently bounded | Unexpected timestamp or numeric field types can interrupt processing, and unusually long message fields can exceed Telegram's size limit. Normalize incoming types, bound rendered fields, and safely format link labels. [util.py](radar/util.py) · [models.py](radar/models.py) · [messages.py](radar/messages.py) · [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage) |
| Medium | Eligibility fallbacks can contradict explicit listing details | A Bangalore mention in a title can override a known out-of-town city. A later online round in prose can qualify an event with an explicitly in-person first round. Prefer known location and first-round details over keyword matches. [score.py](radar/score.py) · [eligibility.py](radar/eligibility.py) |
| Low | Leap-day reminders can fail a digest | The annual reminder rolls the date into the next year without checking whether February 29 exists in that year. Find the next valid occurrence. [runner.py](radar/runner.py) |

## Deployment limit

The poll and digest depend on GitHub's scheduled trigger. GitHub can delay or drop triggers, so the hosted setup has a best-effort cadence. Application fixes can reduce the chance of a run timing out after GitHub starts it. [GitHub schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## Fix verification

All 12 findings have fixes in the working tree. The regression suite passed 127 tests. The live dry run reached all seven sources and used a copy of GitHub's saved state. Telegram delivery was exercised with mocks and console previews. The dependency audit reported no known vulnerabilities, and all three workflows passed schema validation.
