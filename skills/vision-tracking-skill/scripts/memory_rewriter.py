#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tracking_agent.memory_format import normalize_memory_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize a tracking memory Markdown file.")
    parser.add_argument("memory_path", help="Path to the memory markdown file")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite the file in place. Otherwise print the normalized memory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    memory_path = Path(args.memory_path)
    normalized = normalize_memory_markdown(memory_path.read_text(encoding="utf-8"))
    if args.in_place:
        memory_path.write_text(normalized, encoding="utf-8")
    else:
        print(normalized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
