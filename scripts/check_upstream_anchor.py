#!/usr/bin/env python3
"""
Triadic Upstream Anchor Integrity Checker

Role:
- verifies downstream repository anchor reference against canonical VECTAETOS anchor
- compares upstream canonical content to local ANCHOR_REF
- compares upstream canonical SHA-256 to local ANCHOR_SHA256.lock
- does not mutate files
- does not define ontology
- does not validate deployment, safety, or L4 evidence

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

    first_token = text.split()[0].strip().lower()

    if len(first_token) != 64:
        raise ValueError(f"Invalid SHA-256 lock format in {path}")

    return first_token


def read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify downstream anchor against canonical VECTAETOS anchor."
    )
    parser.add_argument(
        "--upstream",
        type=Path,
        required=True,
        help="Canonical anchor from VECTAETOS repository.",
    )
    parser.add_argument(
        "--ref",
        type=Path,
        required=True,
        help="Local downstream anchor reference copy.",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        required=True,
        help="Local downstream SHA-256 lock file.",
    )

    args = parser.parse_args()

    upstream_path = args.upstream
    ref_path = args.ref
    lock_path = args.lock

    for path in (upstream_path, ref_path, lock_path):
        if not path.exists():
            print(f"[ERROR] Required file not found: {path}", file=sys.stderr)
            return 2

    try:
        upstream_hash = sha256_file(upstream_path)
        local_ref_hash = sha256_file(ref_path)
        committed_lock = read_lock(lock_path)

        upstream_bytes = read_bytes(upstream_path)
        local_ref_bytes = read_bytes(ref_path)

    except OSError as exc:
        print(f"[ERROR] File access failure: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print("Triadic upstream anchor integrity check")
    print("---------------------------------------")
    print(f"Upstream anchor: {upstream_path}")
    print(f"Local ref:       {ref_path}")
    print(f"Local lock:      {lock_path}")
    print(f"Upstream hash:   {upstream_hash}")
    print(f"Local ref hash:  {local_ref_hash}")
    print(f"Committed lock:  {committed_lock}")
    print()

    if upstream_bytes != local_ref_bytes:
        print("[ERROR] Local ANCHOR_REF does not match canonical VECTAETOS anchor.", file=sys.stderr)
        print("Repair by copying the canonical VECTAETOS anchor into anchors/ANCHOR_REF.", file=sys.stderr)
        return 1

    if upstream_hash != committed_lock:
        print("[ERROR] Local ANCHOR_SHA256.lock does not match canonical VECTAETOS anchor hash.", file=sys.stderr)
        print("Repair by writing the upstream SHA-256 into anchors/ANCHOR_SHA256.lock.", file=sys.stderr)
        return 1

    print("[OK] Downstream anchor matches canonical VECTAETOS anchor.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
