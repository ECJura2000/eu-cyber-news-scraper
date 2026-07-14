from eu_cyber_news_scraper.http import HttpClient


class FakeResponse:
    def __init__(self):
        self.raised = False

    def raise_for_status(self):
        self.raised = True


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.mounts = []
        self.calls = []
        self.response = FakeResponse()

    def mount(self, prefix, adapter):
        self.mounts.append((prefix, adapter))

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        return self.response


def test_http_client_reuses_thread_local_retry_session(monkeypatch):
    sessions = []

    def factory():
        session = FakeSession()
        sessions.append(session)
        return session

    monkeypatch.setattr("eu_cyber_news_scraper.http.requests.Session", factory)
    client = HttpClient(timeout=7)
    first = client.get("https://example.eu/one")
    second = client.get("https://example.eu/two")
    assert first is second
    assert first.raised
    assert len(sessions) == 1
    assert sessions[0].calls == [("https://example.eu/one", 7), ("https://example.eu/two", 7)]
    assert {prefix for prefix, _ in sessions[0].mounts} == {"https://", "http://"}
    assert "EU-cyber-legal-observation" in sessions[0].headers["User-Agent"]
