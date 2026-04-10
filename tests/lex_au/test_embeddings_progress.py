from __future__ import annotations

from unittest.mock import patch

from lex_au.core import embeddings


class _FakeEmbeddings:
    def __init__(self, rows):
        self._rows = rows

    def tolist(self):
        return self._rows


class _FakeModel:
    def __init__(self):
        self.calls = []

    def encode(self, texts, **kwargs):
        captured = list(texts)
        self.calls.append((captured, kwargs))
        return _FakeEmbeddings([[float(len(text))] for text in captured])


def test_embed_batch_chunks_large_requests_and_preserves_order():
    model = _FakeModel()

    with patch("lex_au.core.embeddings.get_model", return_value=model):
        with patch("lex_au.core.embeddings._MODEL_DEVICE", "cpu"):
            vectors = embeddings.embed_batch(["a", "bb", "ccc", "dddd", "eeeee"], batch_size=2)

    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert [call[0] for call in model.calls] == [["a", "bb"], ["ccc", "dddd"], ["eeeee"]]
    assert [call[1]["batch_size"] for call in model.calls] == [2, 2, 1]
