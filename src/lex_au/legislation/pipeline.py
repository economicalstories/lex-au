"""AU legislation pipeline orchestration."""

from __future__ import annotations

import logging
from collections.abc import Iterator

from lex_au.legislation.parser import AULegislationParser
from lex_au.legislation.scraper import AULegislationScraper, ResumeScanCallback
from lex_au.models import AULegislation, AULegislationType

logger = logging.getLogger(__name__)


class AULegislationPipeline:
    def __init__(
        self,
        scraper: AULegislationScraper | None = None,
        parser: AULegislationParser | None = None,
    ):
        self.scraper = scraper or AULegislationScraper()
        self.parser = parser or AULegislationParser()

    def iter_legislation(
        self,
        years: list[int],
        types: list[AULegislationType],
        limit: int | None = None,
        version_spec: str = "latest",
        resume_after_title_id: str | None = None,
        on_resume_scan: ResumeScanCallback | None = None,
    ) -> Iterator[AULegislation]:
        for payload in self.scraper.iter_title_payloads(
            years=years,
            types=types,
            limit=limit,
            version_spec=version_spec,
            resume_after_title_id=resume_after_title_id,
            on_resume_scan=on_resume_scan,
        ):
            try:
                yield self.parser.parse(
                    summary=payload.summary,
                    title_data=payload.title_data,
                    version_data=payload.version_data,
                    document_pages=payload.document_pages,
                    version_label=version_spec,
                )
            except Exception:
                logger.exception("Failed to parse %s", payload.summary.title_id)
