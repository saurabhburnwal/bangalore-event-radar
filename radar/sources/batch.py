"""Keep readable listing pages when another page in the same feed fails."""
from contextlib import contextmanager

from ..http import issue
from ..models import Event


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
