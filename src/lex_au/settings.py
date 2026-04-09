"""Settings for the AU ingestion pipeline."""

from __future__ import annotations

import os
from datetime import datetime

AU_API_BASE_URL = os.environ.get("AU_API_BASE_URL", "https://api.prod.legislation.gov.au/v1")
AU_WEB_BASE_URL = os.environ.get("AU_WEB_BASE_URL", "https://www.legislation.gov.au")

AU_EMBEDDING_MODEL_NAME = os.environ.get("AU_EMBEDDING_MODEL_NAME", "BAAI/bge-large-en-v1.5")
AU_EMBEDDING_BATCH_SIZE = int(os.environ.get("AU_EMBEDDING_BATCH_SIZE", "64"))
AU_EMBEDDING_DIMENSIONS = int(os.environ.get("AU_EMBEDDING_DIMENSIONS", "1024"))
AU_VECTORIZE_PRESET = os.environ.get("AU_VECTORIZE_PRESET", "@cf/baai/bge-large-en-v1.5")

AU_SPARSE_HASH_DIMENSIONS = int(os.environ.get("AU_SPARSE_HASH_DIMENSIONS", "30000"))
AU_DISCOVERY_PAGE_SIZE = int(os.environ.get("AU_DISCOVERY_PAGE_SIZE", "100"))
AU_VECTORIZE_BATCH_SIZE = int(os.environ.get("AU_VECTORIZE_BATCH_SIZE", "1000"))
AU_REQUEST_TIMEOUT_SECONDS = float(os.environ.get("AU_REQUEST_TIMEOUT_SECONDS", "60"))

AU_VECTORIZE_INDEX_NAME = os.environ.get("AU_VECTORIZE_INDEX_NAME", "au-legislation")
AU_VECTORIZE_SECTION_INDEX_NAME = os.environ.get(
    "AU_VECTORIZE_SECTION_INDEX_NAME", "au-legislation-section"
)

CLOUDFLARE_ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
CLOUDFLARE_API_TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN", "")

CURRENT_YEAR = datetime.now().year
FIRST_AU_FEDERAL_YEAR = 1901


def expand_year_tokens(year_tokens: list[str] | None) -> list[int]:
    """Expand year tokens like ['2022', '2023-2024'] into a sorted list."""
    if not year_tokens:
        return []

    years: set[int] = set()
    for token in year_tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        if "-" in cleaned:
            start_text, end_text = cleaned.split("-", maxsplit=1)
            start_year = int(start_text)
            end_year = int(end_text)
            if end_year < start_year:
                raise ValueError(f"Invalid year range: {token}")
            years.update(range(start_year, end_year + 1))
            continue
        years.add(int(cleaned))

    return sorted(years)
