from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Protocol
from urllib import error, request
from urllib.parse import urlparse


class ProviderError(RuntimeError):
    """Base error for provider execution and protocol failures."""


class ProviderConfigurationError(ValueError):
    """Raised when provider configuration is unsafe or invalid."""


class ProviderTransportError(ProviderError):
    """Raised when the provider transport cannot complete a request."""


class ProviderProtocolError(ProviderError):
    """Raised when a provider returns malformed or explicit error data."""


class TextGenerationProvider(Protocol):
    """Minimal provider-neutral text generation contract."""

    @property
    def provider_name(self) -> str: ...

    def generate(self, prompt: str, *, model: str | None = None) -> str: ...

    def stream(self, prompt: str, *, model: str | None = None) -> Iterator[str]: ...


class JsonTransport(Protocol):
    """HTTP boundary injected into providers so provider logic is testable offline."""

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]: ...

    def stream_json_lines(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Iterator[Mapping[str, Any]]: ...


class UrllibJsonTransport:
    """Standard-library JSON/NDJSON HTTP transport."""

    @staticmethod
    def _build_request(url: str, payload: Mapping[str, Any]) -> request.Request:
        body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        return request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )

    @staticmethod
    def _raise_transport_error(exc: BaseException) -> None:
        if isinstance(exc, error.HTTPError):
            raise ProviderTransportError(f"provider HTTP error: {exc.code}") from exc
        if isinstance(exc, error.URLError):
            raise ProviderTransportError("provider connection failed") from exc
        if isinstance(exc, TimeoutError):
            raise ProviderTransportError("provider request timed out") from exc
        raise ProviderTransportError("provider transport failed") from exc

    def post_json(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        req = self._build_request(url, payload)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            self._raise_transport_error(exc)

        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError("provider returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise ProviderProtocolError("provider JSON response must be an object")
        return decoded

    def stream_json_lines(
        self,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Iterator[Mapping[str, Any]]:
        req = self._build_request(url, payload)
        try:
            response = request.urlopen(req, timeout=timeout)
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            self._raise_transport_error(exc)

        try:
            with response:
                for raw_line in response:
                    if not raw_line.strip():
                        continue
                    try:
                        decoded = json.loads(raw_line.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise ProviderProtocolError("provider stream returned invalid NDJSON") from exc
                    if not isinstance(decoded, Mapping):
                        raise ProviderProtocolError("provider stream item must be a JSON object")
                    yield decoded
        except (error.HTTPError, error.URLError, TimeoutError) as exc:
            self._raise_transport_error(exc)


def _validate_prompt(prompt: str) -> str:
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    return prompt


def _validate_model(model: str) -> str:
    if not isinstance(model, str) or not model.strip():
        raise ProviderConfigurationError("model must be a non-empty string")
    return model.strip()


def _normalize_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ProviderConfigurationError("base_url must be a non-empty string")
    candidate = base_url.strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderConfigurationError("base_url must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ProviderConfigurationError("credentials must not be embedded in base_url")
    if parsed.query or parsed.fragment:
        raise ProviderConfigurationError("base_url must not contain query or fragment")
    return candidate


@dataclass(frozen=True)
class OllamaProvider:
    """Ollama `/api/generate` adapter with real NDJSON streaming."""

    base_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2:3b"
    timeout: float = 300.0
    transport: JsonTransport = field(default_factory=UrllibJsonTransport)

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", _normalize_base_url(self.base_url))
        object.__setattr__(self, "model", _validate_model(self.model))
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool) or self.timeout <= 0:
            raise ProviderConfigurationError("timeout must be a positive number")

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def generate_url(self) -> str:
        return f"{self.base_url}/api/generate"

    def _payload(self, prompt: str, *, model: str | None, stream: bool) -> dict[str, Any]:
        return {
            "model": _validate_model(model) if model is not None else self.model,
            "prompt": _validate_prompt(prompt),
            "stream": stream,
        }

    @staticmethod
    def _raise_provider_error(item: Mapping[str, Any]) -> None:
        error_message = item.get("error")
        if error_message:
            raise ProviderProtocolError(f"ollama error: {error_message}")

    def generate(self, prompt: str, *, model: str | None = None) -> str:
        payload = self._payload(prompt, model=model, stream=False)
        item = self.transport.post_json(self.generate_url, payload, timeout=float(self.timeout))
        self._raise_provider_error(item)
        response = item.get("response")
        if not isinstance(response, str):
            raise ProviderProtocolError("ollama response missing string 'response' field")
        return response

    def stream(self, prompt: str, *, model: str | None = None) -> Iterator[str]:
        payload = self._payload(prompt, model=model, stream=True)
        saw_terminal = False
        for item in self.transport.stream_json_lines(
            self.generate_url,
            payload,
            timeout=float(self.timeout),
        ):
            self._raise_provider_error(item)
            response = item.get("response", "")
            if not isinstance(response, str):
                raise ProviderProtocolError("ollama stream 'response' field must be a string")
            if response:
                yield response
            if item.get("done") is True:
                saw_terminal = True
                break
        if not saw_terminal:
            raise ProviderProtocolError("ollama stream ended without terminal done=true")
