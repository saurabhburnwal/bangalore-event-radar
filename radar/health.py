"""Public poll telemetry. All timestamps describe completed source checks."""
from datetime import datetime, timedelta, timezone

from .http import issue
from .sources import MAY_BE_EMPTY
from .util import parse_dt


def source_status(name, result):
    if isinstance(result, Exception):
        return "failed", issue(result)
    if not result and name not in MAY_BE_EMPTY:
        return "failed", "returned no events"
    return "complete", ""


def record(health: dict, results: dict, now: datetime) -> bool:
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    health.setdefault("started_at", stamp)
    previous = health.get("sources", {})
    rows = {}
    usable = False
    for name, result in results.items():
        status, _ = source_status(name, result)
        last = previous.get(name, {}).get("last_usable")
        if status != "failed":
            last = stamp
            usable = True
        rows[name] = {"outcome": status, "events": 0 if isinstance(result, Exception) else len(result),
                      "last_usable": last}
    health.update(last_attempt=stamp, sources=rows)
    if usable:
        health["last_usable"] = stamp
    cutoff = (now - timedelta(days=8)).astimezone(timezone.utc).isoformat(timespec="seconds")
    history = [t for t in health.get("polls", []) if t >= cutoff]
    if usable and (not history or history[-1] != stamp):
        history.append(stamp)
    health["polls"] = history
    return usable


def poll_due(health: dict, now: datetime) -> bool:
    last = parse_dt(health.get("last_usable"))
    return last is None or now - last >= timedelta(hours=1)
