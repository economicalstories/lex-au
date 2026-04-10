"""Cloudflare Vectorize REST client for AU ingestion."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from lex_au.core.http import HttpClient
from lex_au.settings import (
    AU_EMBEDDING_DIMENSIONS,
    AU_VECTORIZE_BATCH_SIZE,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VectorizePoint:
    id: str
    values: list[float]
    sparse_values: dict[str, list[int] | list[float]]
    metadata: dict[str, Any]

    def to_ndjson(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "values": self.values,
                "sparse_values": self.sparse_values,
                "metadata": self.metadata,
            },
            ensure_ascii=True,
        )


def make_vector_id(source_id: str) -> str:
    """Return a Vectorize-safe deterministic ID.

    Cloudflare Vectorize limits IDs to 64 bytes. Many AU section IDs exceed
    that once we append human-readable fragments, so hash only when needed.
    """
    if len(source_id.encode("utf-8")) <= 64:
        return source_id
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()
    return f"au-{digest[:40]}"


class VectorizeClient:
    def __init__(
        self,
        account_id: str,
        api_token: str,
        http_client: HttpClient | None = None,
    ):
        self.account_id = account_id
        self.api_token = api_token
        self.http = http_client or HttpClient()

    @classmethod
    def from_env(cls) -> "VectorizeClient":
        if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
            raise RuntimeError(
                "CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN must be set for Vectorize uploads."
            )
        return cls(CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN)

    def _url(self, suffix: str) -> str:
        return f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}{suffix}"

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": content_type,
        }

    def list_indexes(self) -> list[dict[str, Any]]:
        response = self.http.request(
            "GET",
            self._url("/vectorize/v2/indexes"),
            headers=self._headers(),
        )
        payload = response.json()
        return payload.get("result", [])

    def create_index(
        self,
        index_name: str,
        dimensions: int = AU_EMBEDDING_DIMENSIONS,
        metric: str = "cosine",
        description: str | None = None,
        preset: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": index_name}
        if preset:
            payload["config"] = {"preset": preset}
        else:
            payload["config"] = {"dimensions": dimensions, "metric": metric}
        if description:
            payload["description"] = description

        response = self.http.request(
            "POST",
            self._url("/vectorize/v2/indexes"),
            headers=self._headers(),
            json=payload,
        )
        return response.json()

    def upsert(
        self,
        index_name: str,
        points: list[VectorizePoint],
        batch_size: int = AU_VECTORIZE_BATCH_SIZE,
    ) -> list[dict[str, Any]]:
        responses: list[dict[str, Any]] = []
        total = len(points)
        total_batches = (total + batch_size - 1) // batch_size if total else 0

        for batch_number, start in enumerate(range(0, total, batch_size), start=1):
            batch = points[start : start + batch_size]
            logger.info(
                "Vectorize upsert batch %s/%s to %s (%s-%s of %s)",
                batch_number,
                total_batches,
                index_name,
                start + 1,
                start + len(batch),
                total,
            )
            payload = "\n".join(point.to_ndjson() for point in batch)
            response = self.http.request(
                "POST",
                self._url(f"/vectorize/v2/indexes/{index_name}/upsert"),
                headers=self._headers("application/x-ndjson"),
                data=payload.encode("utf-8"),
            )
            responses.append(response.json())
            logger.info(
                "Completed Vectorize upsert batch %s/%s to %s",
                batch_number,
                total_batches,
                index_name,
            )
        return responses

    def list_vectors(
        self,
        index_name: str,
        *,
        count: int = 1000,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        page_size = max(1, min(count, 1000))
        params: dict[str, Any] = {"count": page_size}
        if cursor:
            params["cursor"] = cursor

        response = self.http.request(
            "GET",
            self._url(f"/vectorize/v2/indexes/{index_name}/list"),
            headers=self._headers(),
            params=params,
        )
        return response.json().get("result", {})

    def iter_vectors(
        self,
        index_name: str,
        *,
        count: int = 1000,
    ) -> Iterator[dict[str, Any]]:
        cursor: str | None = None

        while True:
            page = self.list_vectors(index_name, count=count, cursor=cursor)
            yield page

            if not page.get("isTruncated"):
                return

            cursor = page.get("nextCursor")
            if not cursor:
                return
