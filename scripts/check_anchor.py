#!/usr/bin/env python3
"""
Triadic Anchor Integrity Checker

Role:
- verifies that a downstream repository keeps its canonical anchor reference locked
- compares ANCHOR_REF content hash against ANCHOR_SHA256.lock
- does not fetch remote content
- does not mutate files
- does not define ontology
- does not validate deployment, safety, or operational legitimacy

Python:
- 3.11+
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)

    return hasher.hexdigest()


def read_lock(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()

    if not text:
        raise ValueError(f"Empty lock file: {path}")

    first_token = text.split()[0].strip()

    if len(first_token) != 64:
        raise ValueError(f"Invalid SHA-256 lock format in {path}")

    return first_token.lower()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify downstream triadic anchor integrity lock."
    )
    parser.add_argument(
        "--ref",
        type=Path,
        required=True,
        help="Path to anchor reference file.",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        required=True,
        help="Path to SHA-256 lock file.",
    )

    args = parser.parse_args()

    ref_path = args.ref
    lock_path = args.lock

    if not ref_path.exists():
        print(f"[ERROR] Anchor reference not found: {ref_path}", file=sys.stderr)
        return 2

    if not lock_path.exists():
        print(f"[ERROR] Anchor lock not found: {lock_path}", file=sys.stderr)
        return 2

    try:
        computed = sha256_file(ref_path)
        committed = read_lock(lock_path)
    except OSError as exc:
        print(f"[ERROR] File access failure: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print(f"Reference: {ref_path}")
    print(f"Lock:      {lock_path}")
    print(f"Computed:  {computed}")
    print(f"Committed: {committed}")

    if computed != committed:
        print("[ERROR] Anchor integrity mismatch.", file=sys.stderr)
        return 1

    print("[OK] Anchor integrity verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
