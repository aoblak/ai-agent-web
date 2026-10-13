#!/usr/bin/env python3
"""Ingest one GitHub webhook payload into the local signal evidence store."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oos.github_signal_adapter import ingest_webhook  # noqa: E402
from oos.github_signal_ingester import (  # noqa: E402
    GitHubSignalError,
    GitHubSignalStore,
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--event", required=True, help="X-GitHub-Event value")
    parser.add_argument("--delivery", required=True, help="X-GitHub-Delivery value")
    parser.add_argument(
        "--payload",
        type=Path,
        help="JSON payload file; stdin when omitted",
    )
    parser.add_argument("--received-at", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        raw = (
            args.payload.read_text(encoding="utf-8")
            if args.payload is not None
            else sys.stdin.read()
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("webhook payload must be a JSON object")
        with GitHubSignalStore(args.db) as store:
            stored = ingest_webhook(
                store,
                args.event,
                payload,
                delivery_id=args.delivery,
                received_at=args.received_at or now_utc(),
            )
    except (OSError, ValueError, json.JSONDecodeError, GitHubSignalError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "PASS",
                "signal_id": stored.signal_id,
                "raw_event_id": stored.raw_event_id,
                "canonical_action": stored.normalized.canonical_action,
                "semantic_class": stored.normalized.semantic_class,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
