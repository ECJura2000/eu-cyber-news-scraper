from __future__ import annotations

import threading

import requests
import truststore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import DEFAULT_HTTP_CONCURRENCY, DEFAULT_TIMEOUT, USER_AGENT

truststore.inject_into_ssl()
_HTTP_LIMITER = threading.BoundedSemaphore(DEFAULT_HTTP_CONCURRENCY)


class HttpClient:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            retry = Retry(
                total=1,
                connect=1,
                read=1,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "HEAD"}),
                respect_retry_after_header=True,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=12, pool_maxsize=12)
            session = requests.Session()
            session.headers.update(
                {
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en,fr,de;q=0.9",
                }
            )
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            self._local.session = session
        return session

    def get(self, url: str) -> requests.Response:
        with _HTTP_LIMITER:
            response = self._session().get(url, timeout=(min(8, self.timeout), self.timeout))
        response.raise_for_status()
        return response
