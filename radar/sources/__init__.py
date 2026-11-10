"""Source registry. Each module has fetch(http, cfg, cache) -> list[Event]."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from . import devfolio, gdg, hackbriven, hasgeek, luma, meetup, unstop

# Order matters for de-duplication: when two sources list the same event, the earlier one wins.
SOURCES = {
    "luma": luma,
    "unstop": unstop,
    "devfolio": devfolio,
    "meetup": meetup,
    "gdg": gdg,
    "hackbriven": hackbriven,
    "hasgeek": hasgeek,
}

# Sources that can legitimately list zero events; an empty result there is not a breakage.
MAY_BE_EMPTY = {"gdg", "hackbriven"}


def collect(http, cfg: dict, cache: dict) -> dict[str, list | Exception]:
    """Fetch every enabled source in parallel. A failing source returns its exception instead of raising."""
    scfg = cfg.get("sources") or {}
    names = [n for n in SOURCES if (scfg.get(n) or {}).get("enabled", True)]
    for n in names:
        cache.setdefault(n, {})

    def run(name):
        try:
            sub = dict(scfg.get(name) or {})
            sub.setdefault("usd_inr", cfg.get("scoring", {}).get("usd_inr", 88))
            return SOURCES[name].fetch(http, sub, cache[name])
        except Exception as e:  # noqa: BLE001 - one broken site must never stop the rest
            return e

    with ThreadPoolExecutor(max_workers=len(names) or 1) as pool:
        return dict(zip(names, pool.map(run, names)))
