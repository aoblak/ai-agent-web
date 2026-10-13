from __future__ import annotations

import hashlib
from typing import Iterator, Protocol


class SmokeVerificationError(RuntimeError):
    """Raised when a provider smoke check cannot produce valid evidence."""


class TextGenerationProviderLike(Protocol):
    @property
    def provider_name(self) -> str: ...

    def generate(self, prompt: str, *, model: str | None = None) -> str: ...

    def stream(self, prompt: str, *, model: str | None = None) -> Iterator[str]: ...


DEFAULT_SMOKE_PROMPT = (
    "Reply with a short acknowledgement for an OOS provider smoke test."
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def assert_live_opt_in(enabled: bool) -> None:
    if enabled is not True:
        raise SmokeVerificationError(
            "live provider smoke requires explicit opt-in"
        )


def run_provider_smoke(
    provider: TextGenerationProviderLike,
    *,
    model: str,
    prompt: str = DEFAULT_SMOKE_PROMPT,
) -> dict[str, object]:
    """Exercise non-stream and stream generation without retaining raw content."""

    if not isinstance(model, str) or not model.strip():
        raise SmokeVerificationError("model must be explicitly supplied")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SmokeVerificationError("prompt must be a non-empty string")

    selected_model = model.strip()
    generated = provider.generate(prompt, model=selected_model)
    if not isinstance(generated, str) or not generated.strip():
        raise SmokeVerificationError(
            "non-stream generation returned empty output"
        )

    fragments: list[str] = []
    for fragment in provider.stream(prompt, model=selected_model):
        if not isinstance(fragment, str):
            raise SmokeVerificationError(
                "stream yielded a non-string fragment"
            )
        if fragment:
            fragments.append(fragment)

    streamed = "".join(fragments)
    if not streamed.strip():
        raise SmokeVerificationError(
            "stream generation returned empty output"
        )

    return {
        "schema_version": 1,
        "provider": provider.provider_name,
        "model": selected_model,
        "prompt_sha256": _sha256_text(prompt),
        "non_stream": {
            "sha256": _sha256_text(generated),
            "length": len(generated),
        },
        "stream": {
            "sha256": _sha256_text(streamed),
            "length": len(streamed),
            "fragments": len(fragments),
        },
    }
