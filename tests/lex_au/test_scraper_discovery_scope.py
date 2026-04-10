from __future__ import annotations

from lex_au.legislation.scraper import AULegislationScraper
from lex_au.models import AULegislationType


class _StubHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.payload


def test_discover_titles_filters_by_actual_legislation_year():
    http = _StubHttpClient(
        {
            "value": [
                {
                    "id": "C2004A02944",
                    "name": "Insurance Contracts Act 1984",
                    "collection": "Act",
                    "status": "InForce",
                    "makingDate": "1984-06-25",
                    "year": 1984,
                    "number": 44,
                    "isPrincipal": True,
                    "seriesType": "Act",
                },
                {
                    "id": "C2004A00032",
                    "name": "Example Act 2004",
                    "collection": "Act",
                    "status": "InForce",
                    "makingDate": "2004-12-01",
                    "year": 2004,
                    "number": 32,
                    "isPrincipal": True,
                    "seriesType": "Act",
                },
            ]
        }
    )
    scraper = AULegislationScraper(http_client=http)

    titles = list(scraper.discover_titles(AULegislationType.ACT, 2004))

    assert [title.title_id for title in titles] == ["C2004A00032"]
    assert titles[0].year == 2004

    _, kwargs = http.calls[0]
    assert (
        kwargs["params"]["$filter"]
        == "year eq 2004 and collection eq 'Act' and isPrincipal eq true"
    )
