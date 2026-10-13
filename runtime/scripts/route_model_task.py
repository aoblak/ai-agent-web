#!/usr/bin/env python3
"""Run an OOS task through the evidence-first model router."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from oos.model_router import (  # noqa: E402
    ModelCatalog,
    ModelRouter,
    OpenAIResponsesExecutor,
    RoutingError,
    TaskProfile,
)


def git_value(*args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if process.returncode:
        raise RoutingError("Git branch/HEAD evidence unavailable")
    return process.stdout.strip()


def model_value(argument: str | None, environment_name: str, option_name: str) -> str:
    value = argument or os.environ.get(environment_name, "")
    if not value.strip():
        raise ValueError(f"provide {option_name} or {environment_name}")
    return value.strip()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, type=Path, help="TaskProfile JSON file")
    parser.add_argument("--branch", help="verified branch; defaults to current Git branch")
    parser.add_argument("--head", help="verified commit; defaults to current Git HEAD")
    parser.add_argument("--fast-model", help="or OOS_MODEL_FAST")
    parser.add_argument("--general-model", help="or OOS_MODEL_GENERAL")
    parser.add_argument("--high-model", help="or OOS_MODEL_HIGH")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        task_data = json.loads(args.task.read_text(encoding="utf-8"))
        if not isinstance(task_data, dict):
            raise ValueError("task file must contain a JSON object")
        task = TaskProfile.from_dict(task_data)
        catalog = ModelCatalog(
            model_value(args.fast_model, "OOS_MODEL_FAST", "--fast-model"),
            model_value(args.general_model, "OOS_MODEL_GENERAL", "--general-model"),
            model_value(args.high_model, "OOS_MODEL_HIGH", "--high-model"),
        )
        result = ModelRouter(catalog, OpenAIResponsesExecutor()).run(
            task,
            branch=args.branch or git_value("symbolic-ref", "--short", "HEAD"),
            head=args.head or git_value("rev-parse", "HEAD"),
        )
    except (OSError, ValueError, json.JSONDecodeError, RoutingError) as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
