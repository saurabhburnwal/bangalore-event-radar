from __future__ import annotations

import time

import requests

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class Http:
    """A shared session with a browser user agent, timeouts and a couple of retries."""

    def __init__(self, timeout: float = 20, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})

    def _get(self, url: str, **kw) -> requests.Response:
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = self.s.get(url, timeout=self.timeout, **kw)
                if r.status_code >= 500 or r.status_code == 429:
                    raise requests.HTTPError(f"{r.status_code} from {url}", response=r)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                last = e
                if attempt < self.retries:
                    time.sleep(2 * (attempt + 1))
        raise last  # type: ignore[misc]

    def text(self, url: str, **kw) -> str:
        return self._get(url, **kw).text

    def json(self, url: str, **kw):
        return self._get(url, **kw).json()
