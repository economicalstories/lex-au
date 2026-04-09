"""Minimal HTTP client with retries for AU ingestion."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from lex_au.settings import AU_MIN_REQUEST_INTERVAL_SECONDS, AU_REQUEST_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def _response_error_details(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text.strip()

    if not payload:
        return ""

    if isinstance(payload, dict):
        messages = []
        for error in payload.get("errors", []):
            code = error.get("code")
            message = error.get("message")
            pointer = error.get("source", {}).get("pointer")
            details = " ".join(str(part) for part in [code, message, pointer] if part)
            if details:
                messages.append(details)
        if messages:
            return "; ".join(messages)
        return json.dumps(payload, ensure_ascii=True)

    return str(payload)


class HttpClient:
    def __init__(
        self,
        timeout: float = AU_REQUEST_TIMEOUT_SECONDS,
        max_retries: int = 5,
        backoff_seconds: float = 1.0,
        min_request_interval_seconds: float = AU_MIN_REQUEST_INTERVAL_SECONDS,
        session: requests.Session | None = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_request_interval_seconds = max(min_request_interval_seconds, 0.0)
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "lex-au/0.1")
        self._last_request_started_at = 0.0

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        for attempt in range(1, self.max_retries + 1):
            self._wait_for_request_slot()
            response = self.session.request(method, url, timeout=self.timeout, **kwargs)

            if response.status_code not in RETRYABLE_STATUS_CODES:
                if response.status_code >= 400:
                    details = _response_error_details(response)
                    message = (
                        f"{response.status_code} Client Error for {url}"
                        if response.status_code < 500
                        else f"{response.status_code} Server Error for {url}"
                    )
                    if details:
                        message = f"{message}: {details}"
                    raise requests.HTTPError(message, response=response)
                return response

            if attempt == self.max_retries:
                details = _response_error_details(response)
                message = f"{response.status_code} Error for {url}"
                if details:
                    message = f"{message}: {details}"
                raise requests.HTTPError(message, response=response)

            wait_seconds = self.backoff_seconds * (2 ** (attempt - 1))
            logger.warning(
                "Retrying %s %s after HTTP %s",
                method,
                url,
                response.status_code,
            )
            time.sleep(wait_seconds)

        raise RuntimeError(f"Request failed unexpectedly: {method} {url}")

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
        return response.json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        response = self.request("GET", url, **kwargs)
        response.encoding = response.encoding or "utf-8"
        return response.text

    def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        response = self.request("GET", url, **kwargs)
        return response.content
