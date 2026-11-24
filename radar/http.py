from __future__ import annotations

import json
import time
from urllib.parse import urljoin

import requests

from .util import https_url

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class SourceError(RuntimeError):
    """A source failure safe to persist and show to the subscriber."""


class _Retryable(SourceError):
    pass


def issue(exc: Exception) -> str:
    return str(exc) if isinstance(exc, SourceError) else type(exc).__name__


class _SourceSession(requests.Session):
    def get_redirect_target(self, response: requests.Response) -> None:
        # The reader follows redirects itself without buffering their response bodies.
        return None


class Http:
    """One source's HTTPS session, with a deadline shared by all of its requests."""

    MAX_BODY = 8 * 1024 * 1024

    def __init__(self, source: str, timeout: float = 12, retries: int = 1, budget: float = 120):
        self.source = source
        self.timeout = timeout
        self.retries = retries
        self.deadline = time.monotonic() + budget
        self.s = _SourceSession()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"})

    def __enter__(self) -> Http:
        return self

    def __exit__(self, *exc) -> None:
        self.s.close()

    def _remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SourceError("source fetch time limit reached")
        return remaining

    def _read(self, url: str) -> tuple[bytes, str | None]:
        for _ in range(5):
            if not https_url(url, self.source):
                raise SourceError("unexpected source URL")
            timeout = min(self.timeout, self._remaining())
            with self.s.get(url, timeout=timeout, allow_redirects=False, stream=True) as response:
                if response.is_redirect:
                    try:
                        url = urljoin(url, response.headers["Location"])
                    except ValueError:
                        raise SourceError("invalid source redirect") from None
                    continue
                status = response.status_code
                if status >= 500 or status in (408, 429):
                    raise _Retryable(f"HTTP {status}")
                if not 200 <= status < 300:
                    raise SourceError(f"HTTP {status}")
                body = bytearray()
                for chunk in response.iter_content(16 * 1024):
                    self._remaining()
                    if len(body) + len(chunk) > self.MAX_BODY:
                        raise SourceError("source response exceeds size limit")
                    body.extend(chunk)
                return bytes(body), response.encoding
        raise SourceError("too many source redirects")

    def _get(self, url: str) -> tuple[bytes, str | None]:
        for attempt in range(self.retries + 1):
            try:
                return self._read(url)
            except _Retryable as exc:
                error = str(exc)
            except requests.RequestException as exc:
                error = f"source transport failure ({type(exc).__name__})"
            if attempt == self.retries:
                raise SourceError(error)
            time.sleep(min(2, self._remaining()))
        raise AssertionError("unreachable")

    def text(self, url: str) -> str:
        body, encoding = self._get(url)
        try:
            return body.decode(encoding or "utf-8", errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")

    def json(self, url: str):
        body, _ = self._get(url)
        return json.loads(body)
