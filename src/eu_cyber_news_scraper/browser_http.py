"""Opt-in HTTP transport using an installed Chrome/Chromium, without page scripts.

Only the requested main document is loaded. Redirects are returned to HttpClient
so its URL/robots checks run before every hop; page assets and frames are blocked.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

import httpx
from playwright.async_api import Browser, BrowserContext, Error, Playwright, Route, async_playwright
from playwright.async_api import TimeoutError as BrowserTimeoutError

from . import __version__


class BrowserResponseTooLargeError(httpx.RequestError):
    pass


def system_chrome() -> str:
    candidates = [os.environ.get("CHROME_PATH", ""),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    candidates.extend(shutil.which(name) or "" for name in
                      ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"))
    for root in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", "")):
        if root:
            candidates.append(str(Path(root) / "Google/Chrome/Application/chrome.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("System Chrome/Chromium not found; install Chrome or set CHROME_PATH")


class BrowserHttpTransport(httpx.AsyncBaseTransport):
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._contexts: dict[tuple[str, str], BrowserContext] = {}
        self._user_agent = ""

    async def _start(self) -> Browser:
        if self._browser is None:
            executable = system_chrome()
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(executable_path=executable, headless=True)
            context = await self._browser.new_context(java_script_enabled=False)
            try:
                page = await context.new_page()
                actual = await page.evaluate("navigator.userAgent")
                self._user_agent = (str(actual) + f" eu-cyber-news-scraper/{__version__} "
                                    "(+https://github.com/ECJura2000/eu-cyber-news-scraper)")
            finally:
                await context.close()
        return self._browser

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET" or request.url.scheme != "https":
            raise httpx.UnsupportedProtocol("Browser transport accepts HTTPS GET only", request=request)
        async with self._lock:
            browser = await self._start()
            origin = str(request.url.copy_with(path="/", query=None, fragment=None))
            # Cookies are isolated per official origin, never taken from a user profile.
            key = (origin, request.headers.get("user-agent", ""))
            if key not in self._contexts:
                self._contexts[key] = await browser.new_context(
                    java_script_enabled=False, service_workers="block", accept_downloads=False,
                    user_agent=self._user_agent,
                )
            context = self._contexts[key]
            headers = {k: v for k, v in request.headers.items()
                       if k not in {"host", "user-agent", "accept-encoding", "cookie"}}
            await context.set_extra_http_headers(headers)
            page = await context.new_page()
            responses = []
            oversized = False
            received = 0

            async def guard(route: Route) -> None:
                incoming = route.request
                if (incoming.is_navigation_request() and incoming.frame == page.main_frame
                        and incoming.redirected_from is None and incoming.url == str(request.url)):
                    await route.continue_()
                else:
                    await route.abort()

            await page.route("**/*", guard)
            page.on("response", lambda response: responses.append(response)
                    if response.request.is_navigation_request() and response.request.redirected_from is None else None)
            session = await context.new_cdp_session(page)
            await session.send("Network.enable")

            async def limit_download(event: dict[str, object]) -> None:
                nonlocal oversized, received
                received += int(str(event.get("dataLength", 0)))
                if received > self.max_bytes:
                    oversized = True
                    await session.send("Page.stopLoading")

            session.on("Network.dataReceived", limit_download)
            try:
                try:
                    await page.goto(str(request.url), wait_until="domcontentloaded",
                                    timeout=1000 * float(request.extensions.get("timeout", {}).get("read", 25)))
                except Error:
                    # A blocked redirect is returned to the outer HTTP/robots loop.
                    if not responses or not 300 <= responses[0].status < 400:
                        raise
                if not responses:
                    raise httpx.ReadError("Chrome returned no HTTP response", request=request)
                response = responses[0]
                result_headers = await response.all_headers()
                try:
                    declared_size = int(result_headers.get("content-length", "0"))
                except ValueError:
                    declared_size = 0
                if declared_size > self.max_bytes:
                    oversized = True
                if oversized:
                    raise BrowserResponseTooLargeError("Chrome response exceeds byte limit", request=request)
                body = b"" if 300 <= response.status < 400 else await response.body()
                if oversized or len(body) > self.max_bytes:
                    raise BrowserResponseTooLargeError("Chrome response exceeds byte limit", request=request)
                result_headers.pop("content-encoding", None)
                result_headers.pop("content-length", None)
                return httpx.Response(response.status, headers=result_headers, content=body, request=request,
                                      extensions={"transport": "system_chrome"})
            except BrowserTimeoutError as exc:
                raise httpx.ReadTimeout(f"System Chrome request timed out: {exc}", request=request) from exc
            except Error as exc:
                if oversized:
                    raise BrowserResponseTooLargeError("Chrome response exceeds byte limit", request=request) from exc
                raise httpx.ConnectError(f"System Chrome request failed: {exc}", request=request) from exc
            finally:
                await page.close()

    async def aclose(self) -> None:
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()
