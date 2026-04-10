from __future__ import annotations

from lex_au.core.diagnostics import build_probes, format_report, run_diagnostics
from lex_au.core.http import HealthCheckResult, HttpClient, RequestAttempt


class _FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok"):
        self.status_code = status_code
        self.text = text
        self.encoding = "utf-8"
        self.headers: dict[str, str] = {}

    def json(self):
        return {"ok": True}


class _ScriptedSession:
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.headers: dict[str, str] = {}

    def request(self, *args, **kwargs):
        self.calls += 1
        outcome = self.script.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _client(session):
    return HttpClient(
        session=session,
        max_retries=2,
        backoff_seconds=0,
        jitter_seconds=0,
        min_request_interval_seconds=0,
    )


def test_build_probes_returns_expected_endpoints():
    probes = build_probes(
        api_base_url="https://api.example.invalid/v1",
        web_base_url="https://web.example.invalid",
        sample_title_id="C2004A04426",
    )
    urls = [probe.url for probe in probes]
    assert urls == [
        "https://api.example.invalid/v1/titles",
        "https://api.example.invalid/v1/titles('C2004A04426')",
        (
            "https://api.example.invalid/v1/versions/find("
            "titleId='C2004A04426',asAtSpecification='latest')"
        ),
        "https://web.example.invalid/C2004A04426/latest/text",
    ]


def test_run_diagnostics_all_ok():
    script = [_FakeResponse(status_code=200, text="payload") for _ in range(4)]
    session = _ScriptedSession(script)
    client = _client(session)

    results = run_diagnostics(http_client=client)

    assert len(results) == 4
    assert all(r.ok for r in results)
    assert session.calls == 4


def test_run_diagnostics_reports_503_failures():
    # Each probe sees two 503s, exhausting max_retries=2.
    script = [_FakeResponse(status_code=503, text="down") for _ in range(8)]
    session = _ScriptedSession(script)
    client = _client(session)

    results = run_diagnostics(http_client=client)

    assert len(results) == 4
    assert all(not r.ok for r in results)
    assert all(r.status_code == 503 for r in results)

    report = format_report(results)
    assert "FAIL" in report
    assert "0/4 probe(s) succeeded" in report
    assert "503" in report
    assert "upstream API is likely degraded" in report


def test_format_report_widespread_upstream_outage_detected():
    """Mix of 5xx statuses and timeouts across tiers -> 'upstream outage' hint.

    Mirrors the real failure the diagnostics tool observed during the
    legislation.gov.au outage (504 on discovery, read-timeout-then-503 on
    title fetch, 503 on version find, 500 on the web tier).
    """

    results = [
        HealthCheckResult(
            name="titles discovery",
            method="GET",
            url="https://api.example.invalid/v1/titles",
            ok=False,
            status_code=504,
            attempts=[
                RequestAttempt(
                    attempt=1,
                    method="GET",
                    url="https://api.example.invalid/v1/titles",
                    status_code=504,
                    error="HTTP 504",
                ),
            ],
        ),
        HealthCheckResult(
            name="fetch single title",
            method="GET",
            url="https://api.example.invalid/v1/titles('X')",
            ok=False,
            status_code=503,
            attempts=[
                RequestAttempt(
                    attempt=1,
                    method="GET",
                    url="https://api.example.invalid/v1/titles('X')",
                    error="read timeout: ...",
                ),
                RequestAttempt(
                    attempt=2,
                    method="GET",
                    url="https://api.example.invalid/v1/titles('X')",
                    status_code=503,
                    error="HTTP 503",
                ),
            ],
        ),
        HealthCheckResult(
            name="resolve latest version",
            method="GET",
            url="https://api.example.invalid/v1/versions/find(...)",
            ok=False,
            status_code=503,
            attempts=[
                RequestAttempt(
                    attempt=1,
                    method="GET",
                    url="https://api.example.invalid/v1/versions/find(...)",
                    status_code=503,
                    error="HTTP 503",
                ),
            ],
        ),
        HealthCheckResult(
            name="fetch version text page",
            method="GET",
            url="https://web.example.invalid/X/latest/text",
            ok=False,
            status_code=500,
            attempts=[
                RequestAttempt(
                    attempt=1,
                    method="GET",
                    url="https://web.example.invalid/X/latest/text",
                    status_code=500,
                    error="HTTP 500",
                ),
            ],
        ),
    ]

    report = format_report(results)

    assert "0/4 probe(s) succeeded" in report
    assert "widespread upstream outage" in report
    assert "legislation.gov.au" in report
    # The status list must include every distinct failing code.
    assert "500" in report
    assert "503" in report
    assert "504" in report
    # It must NOT fall through to the generic "DNS/network reachability" hint.
    assert "DNS/network" not in report


def test_format_report_rate_limit_hint_beats_outage_hint():
    results = [
        HealthCheckResult(
            name="titles discovery",
            method="GET",
            url="https://api.example.invalid/v1/titles",
            ok=False,
            status_code=429,
            error="HTTP 429",
        ),
        HealthCheckResult(
            name="fetch single title",
            method="GET",
            url="https://api.example.invalid/v1/titles('X')",
            ok=False,
            status_code=503,
            error="HTTP 503",
        ),
    ]

    report = format_report(results)

    assert "rate limiting detected" in report
    assert "widespread upstream outage" not in report


def test_format_report_mixes_ok_and_failures():
    results = [
        HealthCheckResult(
            name="titles discovery",
            method="GET",
            url="https://api.example.invalid/v1/titles",
            ok=True,
            status_code=200,
            elapsed_seconds=0.12,
            body_preview="{}",
        ),
        HealthCheckResult(
            name="fetch title",
            method="GET",
            url="https://api.example.invalid/v1/titles('X')",
            ok=False,
            status_code=503,
            elapsed_seconds=61.0,
            error="503 Error for https://api.example.invalid/v1/titles('X')",
            attempts=[
                RequestAttempt(
                    attempt=1,
                    method="GET",
                    url="https://api.example.invalid/v1/titles('X')",
                    status_code=503,
                    elapsed_seconds=60.0,
                    error="HTTP 503",
                )
            ],
        ),
    ]

    report = format_report(results)

    assert "[OK]" in report
    assert "[FAIL]" in report
    assert "1/2 probe(s) succeeded" in report
    assert "attempts: 1" in report
