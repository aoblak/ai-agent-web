import unittest
from unittest.mock import patch
from collections.abc import Iterator
from typing import Any, Mapping

from oos.providers import (
    OllamaProvider,
    ProviderConfigurationError,
    ProviderProtocolError,
    UrllibJsonTransport,
)


class FakeTransport:
    def __init__(self, *, response=None, stream_items=None):
        self.response = response if response is not None else {"response": "ok"}
        self.stream_items = list(stream_items or [])
        self.calls = []

    def post_json(self, url: str, payload: Mapping[str, Any], *, timeout: float):
        self.calls.append(("post", url, dict(payload), timeout))
        return self.response

    def stream_json_lines(self, url: str, payload: Mapping[str, Any], *, timeout: float) -> Iterator[Mapping[str, Any]]:
        self.calls.append(("stream", url, dict(payload), timeout))
        yield from self.stream_items


class FakeHTTPResponse:
    def __init__(self, *, body: bytes = b"", lines=None):
        self.body = body
        self.lines = list(lines or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body

    def __iter__(self):
        return iter(self.lines)


class ProviderTests(unittest.TestCase):
    def test_non_stream_generation_uses_ollama_generate_contract(self):
        transport = FakeTransport(response={"response": "hello", "done": True})
        provider = OllamaProvider(model="local-model", transport=transport)
        self.assertEqual(provider.generate("hi"), "hello")
        kind, url, payload, timeout = transport.calls[0]
        self.assertEqual(kind, "post")
        self.assertEqual(url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(payload, {"model": "local-model", "prompt": "hi", "stream": False})
        self.assertEqual(timeout, 300.0)

    def test_model_can_be_overridden_per_request(self):
        transport = FakeTransport(response={"response": "ok"})
        provider = OllamaProvider(model="default", transport=transport)
        provider.generate("hi", model="override")
        self.assertEqual(transport.calls[0][2]["model"], "override")

    def test_stream_yields_real_fragments_and_requires_terminal_done(self):
        transport = FakeTransport(stream_items=[
            {"response": "hel", "done": False},
            {"response": "lo", "done": False},
            {"response": "", "done": True},
            {"response": "ignored", "done": True},
        ])
        provider = OllamaProvider(transport=transport)
        self.assertEqual(list(provider.stream("hi")), ["hel", "lo"])
        self.assertTrue(transport.calls[0][2]["stream"])

    def test_stream_without_done_is_rejected(self):
        provider = OllamaProvider(transport=FakeTransport(stream_items=[{"response": "partial"}]))
        with self.assertRaises(ProviderProtocolError):
            list(provider.stream("hi"))

    def test_provider_error_is_rejected_non_stream(self):
        provider = OllamaProvider(transport=FakeTransport(response={"error": "model not found"}))
        with self.assertRaisesRegex(ProviderProtocolError, "model not found"):
            provider.generate("hi")

    def test_provider_error_is_rejected_stream(self):
        provider = OllamaProvider(transport=FakeTransport(stream_items=[{"error": "boom"}]))
        with self.assertRaisesRegex(ProviderProtocolError, "boom"):
            list(provider.stream("hi"))

    def test_missing_response_is_rejected(self):
        provider = OllamaProvider(transport=FakeTransport(response={"done": True}))
        with self.assertRaises(ProviderProtocolError):
            provider.generate("hi")

    def test_invalid_stream_response_type_is_rejected(self):
        provider = OllamaProvider(transport=FakeTransport(stream_items=[{"response": 123, "done": False}]))
        with self.assertRaises(ProviderProtocolError):
            list(provider.stream("hi"))

    def test_invalid_configuration_is_rejected(self):
        bad_urls = ["", "localhost:11434", "ftp://localhost", "http://user:pass@localhost", "http://localhost?q=x"]
        for url in bad_urls:
            with self.subTest(url=url):
                with self.assertRaises(ProviderConfigurationError):
                    OllamaProvider(base_url=url)
        with self.assertRaises(ProviderConfigurationError):
            OllamaProvider(model=" ")
        with self.assertRaises(ProviderConfigurationError):
            OllamaProvider(timeout=0)

    def test_blank_prompt_is_rejected(self):
        provider = OllamaProvider(transport=FakeTransport())
        with self.assertRaises(ValueError):
            provider.generate("  ")

    def test_transport_rejects_malformed_json(self):
        transport = UrllibJsonTransport()
        response = FakeHTTPResponse(body=b"not-json")
        with patch("oos.providers.request.urlopen", return_value=response):
            with self.assertRaises(ProviderProtocolError):
                transport.post_json("http://localhost/api/generate", {"x": 1}, timeout=1.0)

    def test_transport_rejects_malformed_ndjson(self):
        transport = UrllibJsonTransport()
        response = FakeHTTPResponse(lines=[b'{"response":"ok","done":false}\n', b'not-json\n'])
        with patch("oos.providers.request.urlopen", return_value=response):
            with self.assertRaises(ProviderProtocolError):
                list(transport.stream_json_lines("http://localhost/api/generate", {"x": 1}, timeout=1.0))


if __name__ == "__main__":
    unittest.main()
