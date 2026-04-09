from __future__ import annotations

import unittest

from lex_au.legislation.scraper import AULegislationScraper
from lex_au.models import AULegislationType, AUTitleSummary


class _StubScraper(AULegislationScraper):
    def __init__(self):
        super().__init__(http_client=None)
        self._titles = {
            (2024, AULegislationType.ACT): ["C2024A00001", "C2024A00002"],
            (2025, AULegislationType.ACT): ["C2025A00001"],
        }

    def discover_titles(self, legislation_type, year, limit=None):
        ids = list(self._titles.get((year, legislation_type), []))
        if limit is not None:
            ids = ids[:limit]
        for title_id in ids:
            yield AUTitleSummary(
                title_id=title_id,
                title=f"Title {title_id}",
                year=year,
                number=1,
                status="InForce",
                collection=legislation_type.collection_name,
                series_type=legislation_type.display_name,
                legislation_type=legislation_type,
            )

    def fetch_title(self, title_id: str):
        return {"id": title_id}

    def fetch_version(self, title_id: str, version_spec: str = "latest"):
        return {"registerId": title_id, "version": version_spec}

    def fetch_document_pages(self, title_id: str, version_spec: str = "latest"):
        return [("u", "<html></html>")]


class ScraperResumeAndCountTest(unittest.TestCase):
    def test_count_titles_groups_by_year_and_type(self):
        scraper = _StubScraper()

        counts = scraper.count_titles(years=[2024, 2025], types=[AULegislationType.ACT])

        self.assertEqual(counts["2024:act"], 2)
        self.assertEqual(counts["2025:act"], 1)
        self.assertEqual(counts["total"], 3)

    def test_iter_title_payloads_resumes_after_specific_title(self):
        scraper = _StubScraper()

        payloads = list(
            scraper.iter_title_payloads(
                years=[2024, 2025],
                types=[AULegislationType.ACT],
                resume_after_title_id="C2024A00001",
            )
        )

        self.assertEqual(
            [payload.summary.title_id for payload in payloads],
            ["C2024A00002", "C2025A00001"],
        )


if __name__ == "__main__":
    unittest.main()
