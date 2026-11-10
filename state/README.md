`seen.json` is written by the bot after each run: which events it has already alerted on, the digest
queue, and source health. Don't edit it by hand while the workflows are running. Deleting it makes the
next run behave like a first run (one "what's open now" summary, no flood).
