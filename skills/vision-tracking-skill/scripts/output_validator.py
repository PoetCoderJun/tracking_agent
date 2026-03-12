#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.output_validator import validate_locate_result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a locate-result JSON file.")
    parser.add_argument("result_path", help="Path to a JSON file with a locate result")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(Path(args.result_path).read_text(encoding="utf-8"))
    normalized = validate_locate_result(payload)
    print(json.dumps(normalized, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
