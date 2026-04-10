from __future__ import annotations

import unittest

from lex_au.core.vectorize_client import VectorizeClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _StubHttpClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeResponse(self._responses.pop(0))


class VectorizeClientListVectorsTest(unittest.TestCase):
    def test_list_vectors_passes_pagination_params(self):
        http = _StubHttpClient(
            [
                {
                    "result": {
                        "vectors": [{"id": "C2024A00001"}],
                        "count": 1,
                        "totalCount": 1,
                        "isTruncated": False,
                    }
                }
            ]
        )
        client = VectorizeClient(account_id="acct", api_token="token", http_client=http)

        result = client.list_vectors("au-legislation", count=200, cursor="abc123")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["vectors"][0]["id"], "C2024A00001")

        method, url, kwargs = http.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(
            url,
            "https://api.cloudflare.com/client/v4/accounts/acct/vectorize/v2/indexes/au-legislation/list",
        )
        self.assertEqual(kwargs["params"], {"count": 200, "cursor": "abc123"})
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer token")

    def test_iter_vectors_follows_next_cursor_until_complete(self):
        http = _StubHttpClient(
            [
                {
                    "result": {
                        "vectors": [{"id": "C2024A00001"}],
                        "count": 1,
                        "totalCount": 2,
                        "isTruncated": True,
                        "nextCursor": "page-2",
                    }
                },
                {
                    "result": {
                        "vectors": [{"id": "C2024A00002"}],
                        "count": 1,
                        "totalCount": 2,
                        "isTruncated": False,
                    }
                },
            ]
        )
        client = VectorizeClient(account_id="acct", api_token="token", http_client=http)

        pages = list(client.iter_vectors("au-legislation", count=1))

        self.assertEqual(len(pages), 2)
        self.assertEqual(
            [page["vectors"][0]["id"] for page in pages],
            ["C2024A00001", "C2024A00002"],
        )
        self.assertEqual(http.calls[0][2]["params"], {"count": 1})
        self.assertEqual(http.calls[1][2]["params"], {"count": 1, "cursor": "page-2"})


if __name__ == "__main__":
    unittest.main()
