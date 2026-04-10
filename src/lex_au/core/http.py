"""HTTP client with retries, structured errors, and rich diagnostics."""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from requests import exceptions as requests_exceptions

from lex_au.settings import AU_MIN_REQUEST_INTERVAL_SECONDS, AU_REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}

DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_SECONDS = 1.0
DEFAULT_MAX_BACKOFF_SECONDS = 60.0
DEFAULT_JITTER_SECONDS = 0.5

_BODY_PREVIEW_LIMIT = 500


@dataclass
class RequestAttempt:
    """Diagnostic record for a single HTTP attempt."""

    attempt: int
    method: str
    url: str
    status_code: int | None = None
    elapsed_seconds: float = 0.0
    error: str | None = None
    body_preview: str | None = None
    retry_after_seconds: float | None = None

    def format(self) -> str:
        parts = [f"attempt={self.attempt}", f"elapsed={self.elapsed_seconds:.2f}s"]
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.retry_after_seconds is not None:
            parts.append(f"retry_after={self.retry_after_seconds:.1f}s")
        if self.error:
            parts.append(f"error={self.error}")
        if self.body_preview:
            parts.append(f"body={self.body_preview}")
        return " ".join(parts)


class APIRequestError(requests.RequestException):
    """Rich error raised when an HTTP request ultimately fails.

    Unlike ``requests.HTTPError``/``ConnectionError``, this carries the full
    list of :class:`RequestAttempt` records so callers can produce actionable
    diagnostics without re-running the request.
    """

    def __init__(
        self,
        message: str,
        *,
        method: str,
        url: str,
        attempts: list[RequestAttempt],
        response: requests.Response | None = None,
        cause: BaseException | None = None,
    ):
        super().__init__(message, response=response)
        self.method = method
        self.url = url
        self.attempts = attempts
        self.__cause__ = cause

    @property
    def status_code(self) -> int | None:
        if self.response is not None:
            return self.response.status_code
        for attempt in reversed(self.attempts):
            if attempt.status_code is not None:
                return attempt.status_code
        return None

    @property
    def last_error(self) -> str | None:
        for attempt in reversed(self.attempts):
            if attempt.error:
                return attempt.error
        return None

    def diagnostic_report(self) -> str:
        lines = [f"{self.method} {self.url} failed after {len(self.attempts)} attempt(s)"]
        for attempt in self.attempts:
            lines.append(f"  - {attempt.format()}")
        status = self.status_code
        if status == 503:
            lines.append(
                "  hint: 503 Service Unavailable usually means the upstream "
                "API is briefly overloaded or restarting. Try again in a few "
                "minutes, or reduce concurrency."
            )
        elif status == 429:
            lines.append(
                "  hint: 429 Too Many Requests means you are being rate "
                "limited. Increase AU_MIN_REQUEST_INTERVAL_SECONDS or back off."
            )
        elif status in {502, 504}:
            lines.append(
                "  hint: Bad gateway / gateway timeout errors are normally "
                "transient upstream issues. Retry later."
            )
        elif self.last_error and "timed out" in self.last_error.lower():
            lines.append(
                "  hint: Read timeouts indicate the server accepted the "
                "connection but did not respond in time. Consider raising "
                "AU_REQUEST_TIMEOUT_SECONDS."
            )
        return "\n".join(lines)


@dataclass
class HealthCheckResult:
    """Result of a lightweight endpoint probe."""

    name: str
    method: str
    url: str
    ok: bool
    status_code: int | None = None
    elapsed_seconds: float = 0.0
    error: str | None = None
    body_preview: str | None = None
    attempts: list[RequestAttempt] = field(default_factory=list)

    def summary(self) -> str:
        state = "OK" if self.ok else "FAIL"
        parts = [
            f"[{state}]",
            f"{self.name}",
            f"{self.method} {self.url}",
            f"status={self.status_code if self.status_code is not None else '-'}",
            f"elapsed={self.elapsed_seconds:.2f}s",
        ]
        if self.error:
            parts.append(f"error={self.error}")
        return " ".join(parts)


def _response_body_preview(response: requests.Response | None) -> str | None:
    if response is None:
        return None
    try:
        text = response.text
    except Exception:  # pragma: no cover - defensive
        return None
    if not text:
        return None
    text = text.strip()
    if len(text) > _BODY_PREVIEW_LIMIT:
        return text[:_BODY_PREVIEW_LIMIT] + f"... ({len(text)} chars)"
    return text


def _response_error_details(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return _response_body_preview(response) or ""

    if not payload:
        return ""

    if isinstance(payload, dict):
        messages = []
        for error in payload.get("errors", []) or []:
            if not isinstance(error, dict):
                continue
            code = error.get("code")
            message = error.get("message")
            pointer = (error.get("source") or {}).get("pointer")
            details = " ".join(str(part) for part in [code, message, pointer] if part)
            if details:
                messages.append(details)
        if messages:
            return "; ".join(messages)
        try:
            return json.dumps(payload, ensure_ascii=True)[:_BODY_PREVIEW_LIMIT]
        except (TypeError, ValueError):
            return _response_body_preview(response) or ""

    return str(payload)[:_BODY_PREVIEW_LIMIT]


def _parse_retry_after(response: requests.Response | None) -> float | None:
    if response is None:
        return None
    header = response.headers.get("Retry-After")
    if not header:
        return None
    header = header.strip()
    if not header:
        return None
    try:
        return max(float(header), 0.0)
    except ValueError:
        # HTTP-date forms are rare for this API; fall back to None rather than
        # guessing a value.
        return None


def _classify_request_exception(exc: requests.RequestException) -> str:
    if isinstance(exc, requests_exceptions.ConnectTimeout):
        return "connect timeout"
    if isinstance(exc, requests_exceptions.ReadTimeout):
        return "read timeout"
    if isinstance(exc, requests_exceptions.Timeout):
        return "timeout"
    if isinstance(exc, requests_exceptions.SSLError):
        return "ssl error"
    if isinstance(exc, requests_exceptions.ProxyError):
        return "proxy error"
    if isinstance(exc, requests_exceptions.ConnectionError):
        return "connection error"
    return exc.__class__.__name__


class HttpClient:
    def __init__(
        self,
        timeout: float = AU_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
        jitter_seconds: float = DEFAULT_JITTER_SECONDS,
        min_request_interval_seconds: float = AU_MIN_REQUEST_INTERVAL_SECONDS,
        session: requests.Session | None = None,
    ):
        self.timeout = timeout
        self.max_retries = max(int(max_retries), 1)
        self.backoff_seconds = max(float(backoff_seconds), 0.0)
        self.max_backoff_seconds = max(float(max_backoff_seconds), 0.0)
        self.jitter_seconds = max(float(jitter_seconds), 0.0)
        self.min_request_interval_seconds = max(min_request_interval_seconds, 0.0)
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "lex-au/0.1")
        self._last_request_started_at = 0.0

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        attempts: list[RequestAttempt] = []

        for attempt_index in range(1, self.max_retries + 1):
            self._wait_for_request_slot()
            started = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                elapsed = time.monotonic() - started
                classification = _classify_request_exception(exc)
                record = RequestAttempt(
                    attempt=attempt_index,
                    method=method,
                    url=url,
                    elapsed_seconds=elapsed,
                    error=f"{classification}: {exc}",
                )
                attempts.append(record)

                if attempt_index == self.max_retries:
                    message = (
                        f"{method} {url} failed after {self.max_retries} attempt(s) "
                        f"({classification})"
                    )
                    logger.error(
                        "Giving up on %s %s after %s attempt(s): %s",
                        method,
                        url,
                        self.max_retries,
                        classification,
                    )
                    raise APIRequestError(
                        message,
                        method=method,
                        url=url,
                        attempts=attempts,
                        cause=exc,
                    ) from exc

                wait_seconds = self._compute_backoff(attempt_index, retry_after=None)
                logger.warning(
                    "Retrying %s %s after %s (attempt %s/%s, elapsed=%.2fs); "
                    "sleeping %.1fs",
                    method,
                    url,
                    classification,
                    attempt_index,
                    self.max_retries,
                    elapsed,
                    wait_seconds,
                )
                time.sleep(wait_seconds)
                continue

            elapsed = time.monotonic() - started
            retry_after = _parse_retry_after(response)
            record = RequestAttempt(
                attempt=attempt_index,
                method=method,
                url=url,
                status_code=response.status_code,
                elapsed_seconds=elapsed,
                retry_after_seconds=retry_after,
            )

            if response.status_code not in RETRYABLE_STATUS_CODES:
                if response.status_code >= 400:
                    details = _response_error_details(response)
                    record.body_preview = details or None
                    record.error = f"HTTP {response.status_code}"
                    attempts.append(record)
                    kind = "Client Error" if response.status_code < 500 else "Server Error"
                    message = f"{response.status_code} {kind} for {url}"
                    if details:
                        message = f"{message}: {details}"
                    logger.error(
                        "%s %s returned HTTP %s (elapsed=%.2fs)%s",
                        method,
                        url,
                        response.status_code,
                        elapsed,
                        f": {details}" if details else "",
                    )
                    raise APIRequestError(
                        message,
                        method=method,
                        url=url,
                        attempts=attempts,
                        response=response,
                    )
                attempts.append(record)
                logger.debug(
                    "%s %s -> %s in %.2fs",
                    method,
                    url,
                    response.status_code,
                    elapsed,
                )
                return response

            # Retryable status code
            details = _response_error_details(response)
            record.body_preview = details or None
            record.error = f"HTTP {response.status_code}"
            attempts.append(record)

            if attempt_index == self.max_retries:
                message = f"{response.status_code} Error for {url}"
                if details:
                    message = f"{message}: {details}"
                logger.error(
                    "Giving up on %s %s after %s attempt(s); last status=%s",
                    method,
                    url,
                    self.max_retries,
                    response.status_code,
                )
                raise APIRequestError(
                    message,
                    method=method,
                    url=url,
                    attempts=attempts,
                    response=response,
                )

            wait_seconds = self._compute_backoff(attempt_index, retry_after=retry_after)
            logger.warning(
                "Retrying %s %s after HTTP %s (attempt %s/%s, elapsed=%.2fs, "
                "retry_after=%s); sleeping %.1fs%s",
                method,
                url,
                response.status_code,
                attempt_index,
                self.max_retries,
                elapsed,
                f"{retry_after:.1f}s" if retry_after is not None else "-",
                wait_seconds,
                f" | body={details}" if details else "",
            )
            time.sleep(wait_seconds)

        # Defensive: the loop always returns or raises; reaching here is a bug.
        raise APIRequestError(
            f"Request failed unexpectedly: {method} {url}",
            method=method,
            url=url,
            attempts=attempts,
        )

    def _compute_backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.max_backoff_seconds)

        base = self.backoff_seconds * (2 ** (attempt - 1))
        base = min(base, self.max_backoff_seconds)
        if self.jitter_seconds > 0:
            base += random.uniform(0.0, self.jitter_seconds)
        return base

    def _wait_for_request_slot(self) -> None:
        if self.min_request_interval_seconds <= 0:
            return

        now = time.monotonic()
        elapsed = now - self._last_request_started_at
        if self._last_request_started_at and elapsed < self.min_request_interval_seconds:
            time.sleep(self.min_request_interval_seconds - elapsed)

        self._last_request_started_at = time.monotonic()

    def get_json(self, url: str, **kwargs: Any) -> Any:
        response = self.request("GET", url, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            preview = _response_body_preview(response)
            raise APIRequestError(
                f"Invalid JSON in response from {url}: {exc}",
                method="GET",
                url=url,
                attempts=[
                    RequestAttempt(
                        attempt=1,
                        method="GET",
                        url=url,
                        status_code=response.status_code,
                        body_preview=preview,
                        error=f"invalid json: {exc}",
                    )
                ],
                response=response,
                cause=exc,
            ) from exc

    def get_text(self, url: str, **kwargs: Any) -> str:
        response = self.request("GET", url, **kwargs)
        response.encoding = response.encoding or "utf-8"
        return response.text

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        response = self.request("GET", url, **kwargs)
        return response.content

    def probe(
        self,
        name: str,
        url: str,
        *,
        method: str = "GET",
        **kwargs: Any,
    ) -> HealthCheckResult:
        """Issue a single request and return a :class:`HealthCheckResult`.

        This is intended for diagnostics: it never raises, returning the
        outcome as data so callers can print a consolidated report.
        """

        started = time.monotonic()
        try:
            response = self.request(method, url, **kwargs)
        except APIRequestError as exc:
            elapsed = time.monotonic() - started
            return HealthCheckResult(
                name=name,
                method=method,
                url=url,
                ok=False,
                status_code=exc.status_code,
                elapsed_seconds=elapsed,
                error=str(exc),
                attempts=list(exc.attempts),
            )
        except Exception as exc:  # pragma: no cover - defensive
            elapsed = time.monotonic() - started
            return HealthCheckResult(
                name=name,
                method=method,
                url=url,
                ok=False,
                elapsed_seconds=elapsed,
                error=f"{exc.__class__.__name__}: {exc}",
            )

        elapsed = time.monotonic() - started
        return HealthCheckResult(
            name=name,
            method=method,
            url=url,
            ok=True,
            status_code=response.status_code,
            elapsed_seconds=elapsed,
            body_preview=_response_body_preview(response),
        )
