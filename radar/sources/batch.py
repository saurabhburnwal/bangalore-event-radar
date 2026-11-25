"""Keep readable listing pages when another page in the same feed fails."""
from contextlib import contextmanager

from ..http import SourceError, issue
from ..models import Event


def listing_rows(payload: dict, field: str) -> list:
    rows = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise SourceError(f"missing or invalid listing field {field}")
    return rows


class ListingBatch(list[Event]):
    def __init__(self):
        super().__init__()
        self.failures: list[str] = []
        self.completed = 0

    @contextmanager
    def page(self, label: str):
        try:
            yield
        except Exception as exc:  # isolate the fetch and parse of this listing page
            self.failures.append(f"{label}: {issue(exc)}")
        else:
            self.completed += 1

    def deduplicate(self):
        unique = {}
        for event in self:
            unique.setdefault(event.native_id, event)
        self[:] = unique.values()
