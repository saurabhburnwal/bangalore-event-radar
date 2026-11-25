`seen.json` is written by the bot after each run: which events it has already alerted on, the digest
queue, and source health. Don't edit it by hand while the workflows are running. Deleting it makes the
next run behave like a first run (one "what's open now" summary, no flood).

`status.json` is the public projection of poll health in `seen.json`. Each completed check records the outcome and listing count per enabled feed and keeps eight days of usable poll timestamps for the status page. Delivery progress stays in `seen.json`.
