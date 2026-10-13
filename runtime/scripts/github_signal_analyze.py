#!/usr/bin/env python3
"""Analyze stored GitHub signals and optionally enrich known repositories."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oos.github_signal_adapter import GitHubAdapterError, GitHubRestClient  # noqa: E402
from oos.github_signal_analysis import (  # noqa: E402
    analyze,
    enrich_repositories,
)
from oos.github_signal_ingester import (  # noqa: E402
    GitHubSignalError,
    GitHubSignalStore,
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument(
        "--enrich-known",
        action="store_true",
        help="GET metadata for repositories already referenced by stored signals",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timestamp = now_utc()
    try:
        with GitHubSignalStore(args.db) as store:
            enriched = 0
            if args.enrich_known:
                token = os.environ.get("GITHUB_TOKEN", "")
                client = GitHubRestClient(token)
                enriched = enrich_repositories(
                    client,
                    store,
                    store.repository_ids(),
                    observed_at=timestamp,
                )
            summary = analyze(store, detected_at=timestamp)
            patterns = store.patterns()
    except (GitHubAdapterError, GitHubSignalError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "PASS",
                "detected": summary.detected,
                "persisted": summary.persisted,
                "enriched": enriched,
                "patterns": patterns,
                "external_actions_executed": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
