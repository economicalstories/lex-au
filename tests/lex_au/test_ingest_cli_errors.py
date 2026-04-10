from __future__ import annotations

from unittest import mock

from lex_au.core.http import APIRequestError, RequestAttempt
from lex_au.ingest import __main__ as ingest_main


def _build_api_error() -> APIRequestError:
    attempts = [
        RequestAttempt(
            attempt=1,
            method="GET",
            url="https://api.example.invalid/v1/titles",
            status_code=503,
            elapsed_seconds=60.0,
            error="HTTP 503",
            body_preview="The service is unavailable.",
        ),
    ]
    return APIRequestError(
        "503 Error for https://api.example.invalid/v1/titles: The service is unavailable.",
        method="GET",
        url="https://api.example.invalid/v1/titles",
        attempts=attempts,
    )


def test_main_reports_api_error_gracefully(capsys, monkeypatch):
    monkeypatch.setattr(
        ingest_main, "run_ingest", mock.Mock(side_effect=_build_api_error())
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "ingest",
            "--mode",
            "full",
            "--year",
            "2024",
            "--type",
            "act",
            "--dry-run",
            "--skip-embed",
        ],
    )

    rc = ingest_main.main()

    assert rc == 2
    captured = capsys.readouterr()
    assert "upstream API error" in captured.err
    assert "503" in captured.err
    assert "lex_au.core.diagnostics" in captured.err


def test_main_reports_setup_api_error(capsys, monkeypatch):
    monkeypatch.setattr(
        ingest_main, "setup_vectorize_indexes", mock.Mock(side_effect=_build_api_error())
    )
    monkeypatch.setattr("sys.argv", ["ingest", "--mode", "setup"])

    rc = ingest_main.main()

    assert rc == 2
    captured = capsys.readouterr()
    assert "upstream API error" in captured.err


def test_main_reports_transport_error(capsys, monkeypatch):
    import requests

    monkeypatch.setattr(
        ingest_main,
        "run_ingest",
        mock.Mock(side_effect=requests.ConnectionError("network down")),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "ingest",
            "--mode",
            "full",
            "--year",
            "2024",
            "--type",
            "act",
            "--dry-run",
            "--skip-embed",
        ],
    )

    rc = ingest_main.main()

    assert rc == 2
    captured = capsys.readouterr()
    assert "network/transport error" in captured.err
    assert "network down" in captured.err
