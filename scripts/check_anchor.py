#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def parse_ref_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid line in {path}: {raw_line!r}")
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()

    required = {"owner", "repo", "branch", "path", "sha_path"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Missing keys in {path}: {', '.join(sorted(missing))}")

    return data


def fetch_bytes(url: str, timeout: int = 20) -> bytes:
    req = Request(url, headers={"User-Agent": "anchor-integrity-check/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify local anchor lock against canonical VECTAETOS anchor."
    )
    parser.add_argument(
        "--ref",
        default="anchors/ANCHOR_REF",
        help="Path to ANCHOR_REF file.",
    )
    parser.add_argument(
        "--lock",
        default="anchors/ANCHOR_SHA256.lock",
        help="Path to local lock file.",
    )
    args = parser.parse_args()

    ref_path = Path(args.ref)
    lock_path = Path(args.lock)

    if not ref_path.exists():
        print(f"[ERROR] Missing ref file: {ref_path}", file=sys.stderr)
        return 1

    if not lock_path.exists():
        print(f"[ERROR] Missing lock file: {lock_path}", file=sys.stderr)
        return 1

    try:
        ref = parse_ref_file(ref_path)
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    anchor_url = build_raw_url(
        ref["owner"], ref["repo"], ref["branch"], ref["path"]
    )
    remote_sha_url = build_raw_url(
        ref["owner"], ref["repo"], ref["branch"], ref["sha_path"]
    )

    try:
        anchor_bytes = fetch_bytes(anchor_url)
        remote_sha = fetch_bytes(remote_sha_url).decode("utf-8").strip()
    except HTTPError as exc:
        print(f"[ERROR] HTTP error while fetching canonical anchor: {exc}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"[ERROR] Network error while fetching canonical anchor: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ERROR] Unexpected fetch error: {exc}", file=sys.stderr)
        return 1

    computed_sha = sha256_bytes(anchor_bytes)
    local_sha = lock_path.read_text(encoding="utf-8").strip()

    if remote_sha != computed_sha:
        print("[ERROR] Canonical repo inconsistency detected.", file=sys.stderr)
        print(f"        remote sha file: {remote_sha}", file=sys.stderr)
        print(f"        computed sha   : {computed_sha}", file=sys.stderr)
        return 1

    if local_sha != computed_sha:
        print("[ERROR] Local lock does not match canonical anchor.", file=sys.stderr)
        print(f"        local lock     : {local_sha}", file=sys.stderr)
        print(f"        canonical sha  : {computed_sha}", file=sys.stderr)
        return 1

    print("[OK] Anchor integrity verified.")
    print(f"     Canonical URL: {anchor_url}")
    print(f"     SHA-256      : {computed_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
