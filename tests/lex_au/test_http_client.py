from __future__ import annotations

import requests

from lex_au.core.http import HttpClient


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"

    def json(self):
        return {"ok": True}


class _FlakySession:
    def __init__(self):
        self.calls = 0
        self.headers = {}

    def request(self, *args, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise requests.ConnectionError("boom")
        return _FakeResponse(status_code=200)


class _AlwaysFailSession:
    def __init__(self):
        self.calls = 0
        self.headers = {}

    def request(self, *args, **kwargs):
        self.calls += 1
        raise requests.ConnectionError("always fails")


def test_request_retries_on_connection_error_then_succeeds():
    session = _FlakySession()
    client = HttpClient(session=session, max_retries=3, backoff_seconds=0)

    response = client.request("GET", "https://example.invalid")

    assert response.status_code == 200
    assert session.calls == 2


def test_request_raises_after_connection_errors_exhaust_retries():
    session = _AlwaysFailSession()
    client = HttpClient(session=session, max_retries=3, backoff_seconds=0)

    try:
        client.request("GET", "https://example.invalid")
    except requests.ConnectionError as exc:
        assert "after 3 attempts" in str(exc)
    else:
        raise AssertionError("Expected ConnectionError")

    assert session.calls == 3
