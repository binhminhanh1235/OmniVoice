#!/usr/bin/env python3
"""Compare real cold/warm hosted-runtime startup evidence.

Usage:
    python scripts/hosted_cache_acceptance.py cold.json warm.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return payload


def evaluate(cold: dict[str, Any], warm: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if cold.get("package_ref") != warm.get("package_ref"):
        failures.append("package_ref differs; compare the same exact code revision")
    if warm.get("resource_fast_path") is not True:
        failures.append("warm resource_fast_path is not true")
    if warm.get("wheel_fast_path") is not True:
        failures.append("warm wheel_fast_path is not true")

    cold_seconds = cold.get("bootstrap_seconds")
    warm_seconds = warm.get("bootstrap_seconds")
    if not isinstance(cold_seconds, (int, float)) or not isinstance(
        warm_seconds, (int, float)
    ):
        failures.append("bootstrap_seconds is missing or non-numeric")
    elif warm_seconds >= cold_seconds:
        failures.append(
            f"warm bootstrap is not faster: cold={cold_seconds:.3f}s warm={warm_seconds:.3f}s"
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate OmniVoice hosted-runtime cold/warm cache evidence."
    )
    parser.add_argument("cold", type=Path, help="cold startup-cache-evidence.json")
    parser.add_argument("warm", type=Path, help="warm startup-cache-evidence.json")
    args = parser.parse_args()

    cold = _load(args.cold)
    warm = _load(args.warm)
    failures = evaluate(cold, warm)

    print(f"cold: {cold.get('bootstrap_seconds')}s")
    print(f"warm: {warm.get('bootstrap_seconds')}s")
    if isinstance(cold.get("bootstrap_seconds"), (int, float)) and isinstance(
        warm.get("bootstrap_seconds"), (int, float)
    ) and cold["bootstrap_seconds"]:
        improvement = 100.0 * (
            float(cold["bootstrap_seconds"]) - float(warm["bootstrap_seconds"])
        ) / float(cold["bootstrap_seconds"])
        print(f"startup improvement: {improvement:.1f}%")

    if failures:
        print("FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS: warm cache is exact-revision compatible and measurably faster")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
