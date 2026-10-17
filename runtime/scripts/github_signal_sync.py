#!/usr/bin/env python3
"""Read GitHub behavioral state and ingest evidence-supported signal changes."""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oos.github_signal_adapter import (  # noqa: E402
    GitHubAdapterError,
    GitHubRestClient,
    GitHubSignalSynchronizer,
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
    parser.add_argument("--actor", required=True, help="authenticated GitHub login")
    parser.add_argument("--stars", action="store_true")
    parser.add_argument("--follows", action="store_true")
    parser.add_argument(
        "--watch",
        action="append",
        default=[],
        metavar="OWNER/REPO",
        help="explicit repository subscription to check; may be repeated",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.stars and not args.follows and not args.watch:
        print(
            json.dumps({"status": "BLOCKED", "error": "select stars/follows/watch"}),
            file=sys.stderr,
        )
        return 2

    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        client = GitHubRestClient(token)
        actor = client.authenticated_login()
        if actor.casefold() != args.actor.casefold():
            raise GitHubAdapterError("requested actor does not match authenticated GitHub account")
        with GitHubSignalStore(args.db) as store:
            sync = GitHubSignalSynchronizer(client, store, actor=actor)
            observed_at = now_utc()
            summaries = []
            if args.stars:
                summaries.append(sync.sync_stars(observed_at=observed_at))
            if args.follows:
                summaries.append(sync.sync_following(observed_at=observed_at))
            if args.watch:
                summaries.append(
                    sync.sync_watch_targets(args.watch, observed_at=observed_at)
                )
    except (GitHubAdapterError, GitHubSignalError, OSError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": "PASS",
                "read_only": True,
                "summaries": [asdict(summary) for summary in summaries],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
