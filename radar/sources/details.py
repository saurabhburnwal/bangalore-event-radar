from __future__ import annotations

import time

from ..http import SourceError


def cached_detail(cache: dict, key: str, version: int, read) -> dict:
    """Refresh detail data periodically and keep last good data if a refresh fails."""
    now = int(time.time())
    previous = cache.get(key) or {}
    if previous.get("v") == version and previous.get("expires", 0) > now:
        return previous
    try:
        detail = read()
    except (AttributeError, ConnectionError, SourceError, TypeError, ValueError, LookupError):
        return previous if previous.get("v") == version else {}
    cache[key] = {**detail, "v": version, "expires": now + 6 * 60 * 60}
    return cache[key]
