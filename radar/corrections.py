"""Compare confirmed facts from the same listing for previously alerted events."""
import re
import unicodedata
from datetime import timezone

from .models import Event
from .util import parse_dt


def confirmed_cancellation(data: dict) -> bool:
    for key in ("eventStatus", "event_status", "status", "launch_status"):
        status = data.get(key)
        if isinstance(status, str) and status.casefold() in {
            "cancelled", "canceled", "eventcancelled", "https://schema.org/eventcancelled",
        }:
            return True
    return (any(data.get(k) is True for k in ("is_canceled", "is_cancelled", "canceled", "cancelled"))
            or any(parse_dt(data.get(k)) is not None for k in ("canceled_at", "cancelled_at")))


def venue_key(value: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold()))


def _facts(ev: Event) -> dict:
    facts = {}
    venue = venue_key(ev.venue)
    if venue and venue not in {"tba", "tbd", "to be announced", "online", venue_key(ev.city)}:
        facts["venue"] = ev.venue
    if ev.reg_deadline:
        facts["deadline"] = ev.reg_deadline.astimezone(timezone.utc).isoformat()
    return facts


def observe(rec: dict, listings: list[Event]) -> None:
    first_observation = "correction_baseline" not in rec
    baseline = rec.setdefault("correction_baseline", {"listing": listings[0].id})
    pending = rec.get("pending_correction", {})
    for listing in listings:
        for field, value in _facts(listing).items():
            old = baseline.setdefault(field, {"listing": listing.id, "value": value})
            if old["listing"] != listing.id:
                continue
            before = old["value"]
            changed = (venue_key(before) != venue_key(value) if field == "venue"
                       else parse_dt(value) < parse_dt(before))
            if changed:
                pending[field] = [before, value]
            else:
                pending.pop(field, None)
                old["value"] = value
    if any(ev.id == baseline["listing"] and ev.cancelled for ev in listings) and not rec.get("cancelled"):
        if not first_observation:
            pending["cancelled"] = True
        rec["cancelled"] = True
    if pending:
        rec["pending_correction"] = pending
    else:
        rec.pop("pending_correction", None)


def delivered(rec: dict) -> None:
    changes = rec.pop("pending_correction")
    for field in ("venue", "deadline"):
        if field in changes:
            rec["correction_baseline"][field]["value"] = changes[field][1]
