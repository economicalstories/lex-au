"""Scraper for the Federal Register of Legislation."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterator

from lex_au.core.http import HttpClient
from lex_au.models import AULegislationType, AUTitleSummary, parse_title_id
from lex_au.settings import AU_API_BASE_URL, AU_DISCOVERY_PAGE_SIZE, AU_WEB_BASE_URL

logger = logging.getLogger(__name__)

DOCUMENT_URL_RE = re.compile(
    r"https://www\.legislation\.gov\.au/[^\"']*document_\d+/document_\d+\.html"
)


@dataclass(slots=True)
class AUTitlePayload:
    summary: AUTitleSummary
    title_data: dict
    version_data: dict
    document_pages: list[tuple[str, str]]


class AULegislationScraper:
    def __init__(
        self,
        http_client: HttpClient | None = None,
        api_base_url: str = AU_API_BASE_URL,
        web_base_url: str = AU_WEB_BASE_URL,
        page_size: int = AU_DISCOVERY_PAGE_SIZE,
    ):
        self.http = http_client or HttpClient()
        self.api_base_url = api_base_url.rstrip("/")
        self.web_base_url = web_base_url.rstrip("/")
        self.page_size = page_size

    def discover_titles(
        self,
        legislation_type: AULegislationType,
        year: int,
        limit: int | None = None,
    ) -> Iterator[AUTitleSummary]:
        produced = 0
        skip = 0

        while True:
            top = self.page_size
            if limit is not None:
                remaining = limit - produced
                if remaining <= 0:
                    return
                top = min(top, remaining)

            payload = self.http.get_json(
                f"{self.api_base_url}/titles",
                params={
                    "$select": "id,name,year,number,status,collection,seriesType,isPrincipal",
                    "$filter": (
                        f"startswith(id,'{legislation_type.title_id_prefix(year)}') "
                        f"and collection eq '{legislation_type.collection_name}' "
                        "and isPrincipal eq true"
                    ),
                    "$orderby": "id",
                    "$top": top,
                    "$skip": skip,
                },
            )

            items = payload.get("value", [])
            if not items:
                return

            for item in items:
                parsed_year, parsed_number = parse_title_id(item["id"])
                yield AUTitleSummary(
                    title_id=item["id"],
                    title=item["name"],
                    year=item.get("year") or parsed_year or year,
                    number=item.get("number") or parsed_number,
                    status=item.get("status", ""),
                    collection=item["collection"],
                    series_type=item.get("seriesType", legislation_type.display_name),
                    legislation_type=legislation_type,
                )
                produced += 1

            skip += len(items)
            if len(items) < top:
                return

    def fetch_title(self, title_id: str) -> dict:
        return self.http.get_json(
            f"{self.api_base_url}/titles('{title_id}')",
            params={"$expand": "textApplies,administeringDepartments"},
        )

    def fetch_version(self, title_id: str, version_spec: str = "latest") -> dict:
        return self.http.get_json(
            f"{self.api_base_url}/versions/find(titleId='{title_id}',asAtSpecification='{version_spec}')"
        )

    def fetch_document_urls(self, title_id: str, version_spec: str = "latest") -> list[str]:
        page_html = self.http.get_text(f"{self.web_base_url}/{title_id}/{version_spec}/text")
        urls = sorted(set(DOCUMENT_URL_RE.findall(page_html)))
        if urls:
            return urls

        iframe_match = re.search(
            r'<iframe[^>]+src="([^"]+document_\d+/document_\d+\.html)"',
            page_html,
        )
        if iframe_match:
            raw_url = iframe_match.group(1)
            if raw_url.startswith("http"):
                return [raw_url]
            return [f"{self.web_base_url}/{raw_url.lstrip('/')}"]

        return []

    def fetch_document_pages(
        self, title_id: str, version_spec: str = "latest"
    ) -> list[tuple[str, str]]:
        pages: list[tuple[str, str]] = []
        for url in self.fetch_document_urls(title_id, version_spec):
            pages.append((url, self.http.get_text(url)))
        return pages

    def iter_title_payloads(
        self,
        years: list[int],
        types: list[AULegislationType],
        limit: int | None = None,
        version_spec: str = "latest",
        resume_after_title_id: str | None = None,
    ) -> Iterator[AUTitlePayload]:
        produced = 0
        resuming = resume_after_title_id is not None
        for year in years:
            for legislation_type in types:
                remaining = None if limit is None else max(limit - produced, 0)
                if remaining == 0:
                    return

                for summary in self.discover_titles(legislation_type, year, remaining):
                    if resuming:
                        if summary.title_id == resume_after_title_id:
                            logger.info("Resuming after %s", resume_after_title_id)
                            resuming = False
                        continue
                    title_data = self.fetch_title(summary.title_id)
                    version_data = self.fetch_version(summary.title_id, version_spec)
                    document_pages = self.fetch_document_pages(summary.title_id, version_spec)
                    if not document_pages:
                        logger.warning("No document pages found for %s", summary.title_id)
                        continue

                    yield AUTitlePayload(
                        summary=summary,
                        title_data=title_data,
                        version_data=version_data,
                        document_pages=document_pages,
                    )
                    produced += 1
                    if limit is not None and produced >= limit:
                        return

    def count_titles(
        self,
        years: list[int],
        types: list[AULegislationType],
        limit: int | None = None,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        produced = 0

        for year in years:
            for legislation_type in types:
                remaining = None if limit is None else max(limit - produced, 0)
                if remaining == 0:
                    break

                key = f"{year}:{legislation_type.value}"
                count = sum(
                    1 for _ in self.discover_titles(legislation_type, year, limit=remaining)
                )
                counts[key] = count
                produced += count

        counts["total"] = produced
        return counts
