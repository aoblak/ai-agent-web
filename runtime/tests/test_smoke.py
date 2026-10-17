import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from oos.smoke import (
    SmokeVerificationError,
    assert_live_opt_in,
    run_provider_smoke,
)


class FakeProvider:
    provider_name = "fake"

    def __init__(
        self,
        *,
        generated="non-stream-output",
        fragments=None,
    ):
        self.generated = generated
        self.fragments = (
            list(fragments)
            if fragments is not None
            else ["stream-", "output"]
        )
        self.calls = []

    def generate(self, prompt, *, model=None):
        self.calls.append(("generate", prompt, model))
        return self.generated

    def stream(self, prompt, *, model=None):
        self.calls.append(("stream", prompt, model))
        yield from self.fragments


class SmokeHarnessTests(unittest.TestCase):
    def test_live_gate_requires_explicit_true(self):
        with self.assertRaises(SmokeVerificationError):
            assert_live_opt_in(False)
        assert_live_opt_in(True)

    def test_documented_direct_runner_reaches_live_gate(self):
        repo_root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        for name in (
            "OOS_OLLAMA_LIVE",
            "OOS_OLLAMA_MODEL",
            "OOS_OLLAMA_RECEIPT",
        ):
            env.pop(name, None)
        result = subprocess.run(
            [sys.executable, "scripts/ollama_live_smoke.py"],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "live provider smoke requires explicit opt-in",
            result.stderr,
        )
        self.assertNotIn("ModuleNotFoundError", result.stderr)

    def test_smoke_exercises_non_stream_and_stream(self):
        provider = FakeProvider()
        receipt = run_provider_smoke(
            provider,
            model="installed-model",
            prompt="private prompt",
        )
        self.assertEqual(
            provider.calls,
            [
                ("generate", "private prompt", "installed-model"),
                ("stream", "private prompt", "installed-model"),
            ],
        )
        self.assertEqual(receipt["provider"], "fake")
        self.assertEqual(receipt["model"], "installed-model")
        self.assertEqual(receipt["stream"]["fragments"], 2)

    def test_receipt_does_not_retain_raw_prompt_or_output(self):
        provider = FakeProvider(
            generated="sensitive response",
            fragments=["sensitive ", "stream"],
        )
        receipt = run_provider_smoke(
            provider,
            model="installed-model",
            prompt="sensitive prompt",
        )
        serialized = json.dumps(receipt)
        self.assertNotIn("sensitive prompt", serialized)
        self.assertNotIn("sensitive response", serialized)
        self.assertNotIn("sensitive stream", serialized)
        self.assertIn("prompt_sha256", receipt)
        self.assertIn("sha256", receipt["non_stream"])
        self.assertIn("sha256", receipt["stream"])

    def test_blank_model_is_rejected_before_provider_call(self):
        provider = FakeProvider()
        with self.assertRaises(SmokeVerificationError):
            run_provider_smoke(provider, model=" ")
        self.assertEqual(provider.calls, [])

    def test_empty_non_stream_output_is_rejected(self):
        provider = FakeProvider(generated=" ")
        with self.assertRaises(SmokeVerificationError):
            run_provider_smoke(provider, model="m")

    def test_empty_stream_output_is_rejected(self):
        provider = FakeProvider(fragments=["", " "])
        with self.assertRaises(SmokeVerificationError):
            run_provider_smoke(provider, model="m")

    def test_non_string_stream_fragment_is_rejected(self):
        provider = FakeProvider(fragments=["ok", 123])
        with self.assertRaises(SmokeVerificationError):
            run_provider_smoke(provider, model="m")


if __name__ == "__main__":
    unittest.main()
