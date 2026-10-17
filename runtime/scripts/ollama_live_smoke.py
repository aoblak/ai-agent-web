from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from oos.providers import OllamaProvider
from oos.smoke import assert_live_opt_in, run_provider_smoke


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an explicit live OOS Ollama smoke verification."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly permit network access to the configured Ollama endpoint.",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get(
            "OOS_OLLAMA_URL", "http://127.0.0.1:11434"
        ),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OOS_OLLAMA_MODEL"),
        help="An already-installed Ollama model. No model is pulled by this script.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("OOS_OLLAMA_TIMEOUT", "120")),
    )
    parser.add_argument(
        "--receipt",
        default=os.environ.get("OOS_OLLAMA_RECEIPT"),
        help="Path for the privacy-safe JSON verification receipt.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    live_enabled = args.live or _env_truthy("OOS_OLLAMA_LIVE")
    assert_live_opt_in(live_enabled)

    if not args.model or not args.model.strip():
        raise SystemExit(
            "Ollama model is required via --model or OOS_OLLAMA_MODEL"
        )
    if not args.receipt:
        raise SystemExit(
            "receipt path is required via --receipt or OOS_OLLAMA_RECEIPT"
        )

    provider = OllamaProvider(
        base_url=args.base_url,
        model=args.model.strip(),
        timeout=args.timeout,
    )
    receipt = run_provider_smoke(
        provider,
        model=args.model.strip(),
    )
    receipt.update(
        {
            "status": "VERIFIED_LIVE",
            "endpoint": provider.base_url,
            "executed_at_utc": datetime.now(timezone.utc).isoformat(),
            "git_sha": os.environ.get("OOS_GIT_SHA")
            or os.environ.get("GITHUB_SHA"),
        }
    )

    destination = Path(args.receipt)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
