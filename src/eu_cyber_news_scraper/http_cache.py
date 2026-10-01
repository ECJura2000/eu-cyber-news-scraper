"""Bounded conditional-response cache. Cached content always needs revalidation."""
from __future__ import annotations

import json
import sqlite3
import time
from hashlib import sha256
from pathlib import Path

import httpx


class ResponseCache:
    def __init__(self, directory: Path, max_bytes: int = 100 * 1024 * 1024) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.connection = sqlite3.connect(directory / "responses.sqlite3", timeout=10)
        self.connection.execute("""CREATE TABLE IF NOT EXISTS responses (
            key TEXT PRIMARY KEY, url TEXT, headers TEXT, body BLOB, digest TEXT, checked REAL
        )""")

    def close(self) -> None:
        self.connection.close()

    def load(self, url: str, variant: str) -> httpx.Response | None:
        key = sha256((url + "\n" + variant).encode()).hexdigest()
        row = self.connection.execute(
            "SELECT url, headers, body, digest, checked FROM responses WHERE key = ?", (key,),
        ).fetchone()
        if row is None:
            return None
        cached_url, headers_text, body, digest, checked = row
        if checked < time.time() - 30 * 86400 or sha256(body).hexdigest() != digest:
            self.delete(url, variant)
            return None
        try:
            headers = json.loads(headers_text)
            if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                       for k, v in headers.items()):
                raise ValueError("invalid cached headers")
            return httpx.Response(200, headers=headers, content=body, request=httpx.Request("GET", cached_url))
        except (ValueError, TypeError):
            self.delete(url, variant)
            return None

    def delete(self, url: str, variant: str) -> None:
        key = sha256((url + "\n" + variant).encode()).hexdigest()
        with self.connection:
            self.connection.execute("DELETE FROM responses WHERE key = ?", (key,))

    def save(self, response: httpx.Response, variant: str) -> None:
        url = str(response.url)
        controls = response.headers.get("cache-control", "").casefold()
        vary = {value.strip().casefold() for value in response.headers.get("vary", "").split(",") if value.strip()}
        if (response.status_code != 200 or "no-store" in controls or "set-cookie" in response.headers
                or vary - {"accept", "accept-language", "accept-encoding", "user-agent"}
                or not (response.headers.get("etag") or response.headers.get("last-modified"))):
            self.delete(url, variant)
            return
        key = sha256((url + "\n" + variant).encode()).hexdigest()
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?)",
                                    (key, url, json.dumps(dict(response.headers)), response.content,
                                     sha256(response.content).hexdigest(), time.time()))
            self.connection.execute("DELETE FROM responses WHERE checked < ?", (time.time() - 30 * 86400,))
            total = self.connection.execute("SELECT COALESCE(SUM(LENGTH(body)), 0) FROM responses").fetchone()[0]
            while total > self.max_bytes:
                oldest = self.connection.execute(
                    "SELECT key, LENGTH(body) FROM responses ORDER BY checked, key LIMIT 1",
                ).fetchone()
                self.connection.execute("DELETE FROM responses WHERE key = ?", (oldest[0],))
                total -= oldest[1]
