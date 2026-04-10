from __future__ import annotations

import unittest

from lex_au.core.vectorize_client import VectorizeClient, VectorizePoint


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _StubHttpClient:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return _FakeResponse({"success": True})


def _point(point_id: str) -> VectorizePoint:
    return VectorizePoint(
        id=point_id,
        values=[0.1, 0.2],
        sparse_values={"indices": [1, 2], "values": [0.5, 0.5]},
        metadata={"id": point_id},
    )


class VectorizeClientUpsertProgressTest(unittest.TestCase):
    def test_upsert_batches_requests(self):
        http = _StubHttpClient()
        client = VectorizeClient(account_id="acct", api_token="token", http_client=http)

        with self.assertLogs("lex_au.core.vectorize_client", level="INFO") as logs:
            responses = client.upsert(
                "au-legislation-section",
                [_point("a"), _point("b"), _point("c")],
                batch_size=2,
            )

        self.assertEqual(len(responses), 2)
        self.assertEqual(len(http.calls), 2)
        self.assertIn("Vectorize upsert batch 1/2", "\n".join(logs.output))
        self.assertIn("Completed Vectorize upsert batch 2/2", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
