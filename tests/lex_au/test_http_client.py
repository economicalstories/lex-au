from __future__ import annotations

import pytest
import requests

from lex_au.core.http import APIRequestError, HttpClient


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        text: str = "ok",
        json_data: object | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self.headers = headers or {}
        self._json_data = json_data if json_data is not None else {"ok": True}

    def json(self):
        if isinstance(self._json_data, Exception):
            raise self._json_data
        return self._json_data


class _ScriptedSession:
    """Session stub that replays a scripted list of outcomes."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.headers: dict[str, str] = {}

    def request(self, *args, **kwargs):
        self.calls += 1
        if not self.script:
            raise AssertionError("No more scripted responses")
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _make_client(session, **overrides):
    defaults = dict(
        session=session,
        max_retries=3,
        backoff_seconds=0,
        jitter_seconds=0,
        min_request_interval_seconds=0,
    )
    defaults.update(overrides)
    return HttpClient(**defaults)


def test_request_retries_on_connection_error_then_succeeds():
    session = _ScriptedSession(
        [requests.ConnectionError("boom"), _FakeResponse(status_code=200)]
    )
    client = _make_client(session)

    response = client.request("GET", "https://example.invalid")

    assert response.status_code == 200
    assert session.calls == 2


def test_request_raises_api_request_error_after_retries_exhausted():
    session = _ScriptedSession([requests.ConnectionError("always fails")] * 3)
    client = _make_client(session)

    with pytest.raises(APIRequestError) as excinfo:
        client.request("GET", "https://example.invalid")

    assert session.calls == 3
    assert excinfo.value.method == "GET"
    assert len(excinfo.value.attempts) == 3
    assert all(a.error and "always fails" in a.error for a in excinfo.value.attempts)
    assert "failed after 3 attempt" in str(excinfo.value)


def test_request_retries_on_503_then_raises_structured_error():
    body = '{"errors":[{"code":"UPSTREAM","message":"The service is unavailable."}]}'
    session = _ScriptedSession(
        [
            _FakeResponse(status_code=503, text=body, json_data={
                "errors": [{"code": "UPSTREAM", "message": "The service is unavailable."}]
            }),
            _FakeResponse(status_code=503, text=body, json_data={
                "errors": [{"code": "UPSTREAM", "message": "The service is unavailable."}]
            }),
            _FakeResponse(status_code=503, text=body, json_data={
                "errors": [{"code": "UPSTREAM", "message": "The service is unavailable."}]
            }),
        ]
    )
    client = _make_client(session)

    with pytest.raises(APIRequestError) as excinfo:
        client.request("GET", "https://api.example.invalid/v1/titles")

    err = excinfo.value
    assert err.status_code == 503
    assert len(err.attempts) == 3
    assert all(a.status_code == 503 for a in err.attempts)
    assert "The service is unavailable" in str(err)
    report = err.diagnostic_report()
    assert "503" in report
    assert "Service Unavailable" in report or "overloaded" in report


def test_retry_after_header_is_honored_and_capped():
    sleeps: list[float] = []

    session = _ScriptedSession(
        [
            _FakeResponse(
                status_code=503,
                text="busy",
                headers={"Retry-After": "3"},
                json_data={},
            ),
            _FakeResponse(status_code=200),
        ]
    )
    client = _make_client(session, max_backoff_seconds=1.5)

    import lex_au.core.http as http_module

    original_sleep = http_module.time.sleep
    http_module.time.sleep = lambda s: sleeps.append(s)
    try:
        response = client.request("GET", "https://example.invalid")
    finally:
        http_module.time.sleep = original_sleep

    assert response.status_code == 200
    assert len(sleeps) == 1
    # Retry-After asked for 3s, but max_backoff_seconds caps it at 1.5.
    assert sleeps[0] == pytest.approx(1.5)


def test_non_retryable_4xx_is_raised_with_body_preview():
    payload = {"errors": [{"code": "INVALID", "message": "Bad filter"}]}
    session = _ScriptedSession(
        [_FakeResponse(status_code=400, text=str(payload), json_data=payload)]
    )
    client = _make_client(session)

    with pytest.raises(APIRequestError) as excinfo:
        client.request("GET", "https://example.invalid/v1/titles")

    assert excinfo.value.status_code == 400
    assert "Bad filter" in str(excinfo.value)
    assert session.calls == 1  # no retries for 400


def test_get_json_wraps_invalid_json():
    session = _ScriptedSession(
        [
            _FakeResponse(
                status_code=200,
                text="<html>not json</html>",
                json_data=ValueError("not json"),
            )
        ]
    )
    client = _make_client(session)

    with pytest.raises(APIRequestError) as excinfo:
        client.get_json("https://example.invalid/v1/titles")

    assert "Invalid JSON" in str(excinfo.value)
    assert excinfo.value.attempts[0].body_preview is not None


def test_probe_returns_health_check_result_for_success():
    session = _ScriptedSession([_FakeResponse(status_code=200, text="hello")])
    client = _make_client(session)

    result = client.probe("titles", "https://example.invalid/v1/titles")

    assert result.ok is True
    assert result.status_code == 200
    assert result.body_preview == "hello"


def test_probe_returns_health_check_result_for_failure():
    session = _ScriptedSession([_FakeResponse(status_code=503, text="down")] * 3)
    client = _make_client(session)

    result = client.probe("titles", "https://example.invalid/v1/titles")

    assert result.ok is False
    assert result.status_code == 503
    assert len(result.attempts) == 3
    assert "503" in (result.error or "")
