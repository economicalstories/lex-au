"""API diagnostics for the AU legislation endpoints.

Run as a module::

    python -m lex_au.core.diagnostics

to get a human-readable report of which endpoints are reachable, their
latency, and remediation hints when something is wrong.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from lex_au.core.http import HealthCheckResult, HttpClient
from lex_au.settings import AU_API_BASE_URL, AU_WEB_BASE_URL

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DiagnosticsProbe:
    name: str
    method: str
    url: str
    params: dict | None = None


def build_probes(
    api_base_url: str = AU_API_BASE_URL,
    web_base_url: str = AU_WEB_BASE_URL,
    sample_title_id: str = "C2004A04426",
) -> list[DiagnosticsProbe]:
    """Return the list of probes executed by the diagnostics command.

    The sample title id defaults to the well-known Copyright Act 1968
    (``C2004A04426``), which is a stable, long-lived identifier suitable as a
    reachability canary.
    """

    api_base_url = api_base_url.rstrip("/")
    web_base_url = web_base_url.rstrip("/")
    return [
        DiagnosticsProbe(
            name="titles discovery",
            method="GET",
            url=f"{api_base_url}/titles",
            params={
                "$select": "id,name,year",
                "$filter": "collection eq 'Act' and isPrincipal eq true",
                "$top": 1,
            },
        ),
        DiagnosticsProbe(
            name="fetch single title",
            method="GET",
            url=f"{api_base_url}/titles('{sample_title_id}')",
            params={"$expand": "textApplies,administeringDepartments"},
        ),
        DiagnosticsProbe(
            name="resolve latest version",
            method="GET",
            url=(
                f"{api_base_url}/versions/find("
                f"titleId='{sample_title_id}',asAtSpecification='latest')"
            ),
        ),
        DiagnosticsProbe(
            name="fetch version text page",
            method="GET",
            url=f"{web_base_url}/{sample_title_id}/latest/text",
        ),
    ]


def run_diagnostics(
    http_client: HttpClient | None = None,
    probes: list[DiagnosticsProbe] | None = None,
) -> list[HealthCheckResult]:
    """Execute the diagnostics probes and return their results."""

    client = http_client or HttpClient()
    selected = probes or build_probes()

    results: list[HealthCheckResult] = []
    for probe in selected:
        kwargs: dict = {}
        if probe.params is not None:
            kwargs["params"] = probe.params
        logger.info("Probing %s (%s %s)", probe.name, probe.method, probe.url)
        result = client.probe(probe.name, probe.url, method=probe.method, **kwargs)
        results.append(result)
    return results


def _probe_error_texts(result: HealthCheckResult) -> list[str]:
    """Collect all error strings associated with a failing probe."""

    texts: list[str] = []
    if result.error:
        texts.append(result.error)
    for attempt in result.attempts:
        if attempt.error:
            texts.append(attempt.error)
    return texts


def _is_timeout_failure(result: HealthCheckResult) -> bool:
    return any("timeout" in text.lower() for text in _probe_error_texts(result))


def _is_server_side_failure(result: HealthCheckResult) -> bool:
    """Return True when the server responded with 5xx or the request timed out.

    Both cases are symptoms of an upstream problem: the client successfully
    reached the server (or at least got past DNS/TCP/TLS), so the fix is on
    the server side, not the client side.
    """

    if result.status_code and 500 <= result.status_code < 600:
        return True
    return _is_timeout_failure(result)


def format_report(results: list[HealthCheckResult]) -> str:
    lines: list[str] = ["AU legislation API diagnostics", "=" * 32]
    for result in results:
        lines.append(result.summary())
        if not result.ok:
            if result.attempts:
                lines.append(f"    attempts: {len(result.attempts)}")
                for attempt in result.attempts:
                    lines.append(f"      - {attempt.format()}")
            if result.error and result.error not in (result.summary() or ""):
                lines.append(f"    detail: {result.error}")
        elif result.body_preview:
            preview = result.body_preview
            if len(preview) > 160:
                preview = preview[:160] + "..."
            lines.append(f"    body: {preview}")

    ok_count = sum(1 for r in results if r.ok)
    total = len(results)
    lines.append("-" * 32)
    lines.append(f"summary: {ok_count}/{total} probe(s) succeeded")

    if ok_count < total:
        failing = [r for r in results if not r.ok]
        failing_statuses = {r.status_code for r in failing}
        failing_statuses.discard(None)

        if 429 in failing_statuses:
            lines.append(
                "hint: rate limiting detected (429). Increase "
                "AU_MIN_REQUEST_INTERVAL_SECONDS or reduce concurrency."
            )
        elif failing and all(_is_server_side_failure(r) for r in failing):
            if failing_statuses == {503}:
                lines.append(
                    "hint: every failing probe returned 503 Service Unavailable. "
                    "The upstream API is likely degraded or restarting - wait a "
                    "few minutes and retry."
                )
            else:
                status_list = (
                    ", ".join(str(code) for code in sorted(failing_statuses))
                    if failing_statuses
                    else "timeouts"
                )
                lines.append(
                    "hint: every failing probe returned a 5xx or timed out "
                    f"(statuses: {status_list}). This looks like a widespread "
                    "upstream outage at legislation.gov.au - no client-side "
                    "change will help. Wait and retry; a simple poll loop is "
                    "'until python -m lex_au.core.diagnostics; do sleep 300; "
                    "done'."
                )
        elif any(_is_timeout_failure(r) for r in failing):
            lines.append(
                "hint: timeouts indicate the server accepted the connection "
                "but did not respond in time. Raise AU_REQUEST_TIMEOUT_SECONDS "
                "or retry later."
            )
        else:
            lines.append(
                "hint: see per-probe details above; verify DNS/network "
                "reachability and check the AU legislation service status."
            )

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Probe AU legislation API endpoints and report their health."
    )
    parser.add_argument(
        "--api-base-url",
        default=AU_API_BASE_URL,
        help="Override the API base URL (default: %(default)s).",
    )
    parser.add_argument(
        "--web-base-url",
        default=AU_WEB_BASE_URL,
        help="Override the web base URL (default: %(default)s).",
    )
    parser.add_argument(
        "--sample-title-id",
        default="C2004A04426",
        help="Title ID to use as the reachability canary (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Per-request timeout in seconds (overrides AU_REQUEST_TIMEOUT_SECONDS).",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Maximum attempts per probe before declaring it failed (default: %(default)s).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    http_kwargs: dict = {"max_retries": max(args.max_retries, 1)}
    if args.timeout is not None:
        http_kwargs["timeout"] = args.timeout
    client = HttpClient(**http_kwargs)

    probes = build_probes(
        api_base_url=args.api_base_url,
        web_base_url=args.web_base_url,
        sample_title_id=args.sample_title_id,
    )

    results = run_diagnostics(http_client=client, probes=probes)
    report = format_report(results)
    print(report)

    return 0 if all(r.ok for r in results) else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
