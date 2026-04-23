#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


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
    req = Request(url, headers={"User-Agent": "vectaetos-boot-guard/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def load_json_bytes(data: bytes, source_name: str) -> dict[str, Any]:
    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid remote JSON in {source_name}: {exc}") from exc


def parse_present_components(raw: str | None, current_component: str, ontological_root: str) -> set[str]:
    present = set()
    if raw:
        for item in raw.split(","):
            value = item.strip()
            if value:
                present.add(value)

    # current component is by definition present if this script is running inside it
    present.add(current_component)
    # ontological root is considered present only after remote verification succeeds,
    # but we add it later explicitly when verification passes
    if ontological_root in present:
        present.remove(ontological_root)

    return present


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def emit_result(state: str, component_name: str, details: dict[str, Any], as_json: bool) -> None:
    payload = {
        "component": component_name,
        "state": state,
        "details": details,
    }
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[{state}] {component_name}")
        for key, value in details.items():
            print(f"  - {key}: {value}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Boot guard for ASIMULATOR / ASI_MOD triadic assembly."
    )
    parser.add_argument(
        "--identity",
        default="contracts/COMPONENT_IDENTITY.json",
        help="Path to local COMPONENT_IDENTITY.json",
    )
    parser.add_argument(
        "--require-full-boot",
        action="store_true",
        help="Fail if full structural boot is not available.",
    )
    parser.add_argument(
        "--present-components",
        default=os.getenv("ASSEMBLY_PRESENT_COMPONENTS", ""),
        help="Comma-separated components considered present in the current assembly.",
    )
    parser.add_argument(
        "--safety-unlock",
        default=os.getenv("VECTAETOS_SAFETY_UNLOCK", "false"),
        help="Empirical safety unlock flag: true/false",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit result as JSON.",
    )
    args = parser.parse_args()

    try:
        identity = load_json_file(Path(args.identity))
    except ValueError as exc:
        emit_result(
            "NO_BOOT",
            "UNKNOWN",
            {"reason": str(exc)},
            args.json,
        )
        return 1

    try:
        component_name = identity["component_name"]
        ontological_root = identity["ontological_root"]
        sibling_component = identity["sibling_component"]
        anchor_ref_path = Path(identity["anchor_ref_path"])
        anchor_lock_path = Path(identity["anchor_lock_path"])
        manifest_path = identity.get("canonical_manifest_path", "contracts/ASSEMBLY_MANIFEST.json")
        standalone_valid = bool(identity["standalone_valid"])
        requires_safety_unlock = bool(identity["operative_mode_requires_empirical_safety_unlock"])
    except KeyError as exc:
        emit_result(
            "NO_BOOT",
            identity.get("component_name", "UNKNOWN"),
            {"reason": f"Missing key in COMPONENT_IDENTITY.json: {exc}"},
            args.json,
        )
        return 1

    if standalone_valid:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": "Upper-layer component declares standalone_valid=true, which is forbidden."},
            args.json,
        )
        return 1

    try:
        ref = parse_ref_file(anchor_ref_path)
    except ValueError as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": str(exc)},
            args.json,
        )
        return 1

    if not anchor_lock_path.exists():
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": f"Missing lock file: {anchor_lock_path}"},
            args.json,
        )
        return 1

    local_lock = anchor_lock_path.read_text(encoding="utf-8").strip()

    anchor_url = build_raw_url(ref["owner"], ref["repo"], ref["branch"], ref["path"])
    remote_sha_url = build_raw_url(ref["owner"], ref["repo"], ref["branch"], ref["sha_path"])
    manifest_url = build_raw_url(ref["owner"], ref["repo"], ref["branch"], manifest_path)

    try:
        anchor_bytes = fetch_bytes(anchor_url)
        remote_sha = fetch_bytes(remote_sha_url).decode("utf-8").strip()
        manifest_bytes = fetch_bytes(manifest_url)
    except HTTPError as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": f"HTTP error while fetching canonical resources: {exc}"},
            args.json,
        )
        return 1
    except URLError as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": f"Network error while fetching canonical resources: {exc}"},
            args.json,
        )
        return 1
    except Exception as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": f"Unexpected fetch error: {exc}"},
            args.json,
        )
        return 1

    computed_anchor_sha = sha256_bytes(anchor_bytes)

    if remote_sha != computed_anchor_sha:
        emit_result(
            "NO_BOOT",
            component_name,
            {
                "reason": "Canonical anchor sha mismatch inside Vectaetos.",
                "remote_sha": remote_sha,
                "computed_anchor_sha": computed_anchor_sha,
            },
            args.json,
        )
        return 1

    if local_lock != computed_anchor_sha:
        emit_result(
            "NO_BOOT",
            component_name,
            {
                "reason": "Local lock does not match canonical anchor sha.",
                "local_lock": local_lock,
                "canonical_sha": computed_anchor_sha,
            },
            args.json,
        )
        return 1

    try:
        manifest = load_json_bytes(manifest_bytes, manifest_url)
    except ValueError as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": str(exc)},
            args.json,
        )
        return 1

    try:
        manifest_root = manifest["ontological_root"]
        required_components = set(manifest["required_components"])
        full_boot_requires = set(manifest["full_boot_requires"][component_name])
        safety_unlock_required_by_manifest = bool(
            manifest["operative_mode_requires_empirical_safety_unlock"]
        )
    except KeyError as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": f"Missing key in ASSEMBLY_MANIFEST.json: {exc}"},
            args.json,
        )
        return 1

    if manifest_root != ontological_root:
        emit_result(
            "NO_BOOT",
            component_name,
            {
                "reason": "Ontological root mismatch between COMPONENT_IDENTITY and ASSEMBLY_MANIFEST.",
                "identity_root": ontological_root,
                "manifest_root": manifest_root,
            },
            args.json,
        )
        return 1

    if component_name not in required_components:
        emit_result(
            "NO_BOOT",
            component_name,
            {
                "reason": "Component is not listed in canonical required_components.",
                "required_components": sorted(required_components),
            },
            args.json,
        )
        return 1

    try:
        safety_unlock = parse_bool(args.safety_unlock, default=False)
    except ValueError as exc:
        emit_result(
            "NO_BOOT",
            component_name,
            {"reason": str(exc)},
            args.json,
        )
        return 1

    present_components = parse_present_components(
        args.present_components, component_name, ontological_root
    )

    # Remote anchor+manifest verification counts as ontological root presence.
    present_components.add(ontological_root)

    missing_for_full_boot = sorted(full_boot_requires - present_components)

    common_details = {
        "ontological_root": ontological_root,
        "sibling_component": sibling_component,
        "present_components": sorted(present_components),
        "missing_for_full_boot": missing_for_full_boot,
        "anchor_url": anchor_url,
        "manifest_url": manifest_url,
        "canonical_anchor_sha": computed_anchor_sha,
        "safety_unlock": safety_unlock,
    }

    if missing_for_full_boot:
        emit_result(
            "NO_FULL_BOOT",
            component_name,
            {
                **common_details,
                "reason": "Required sibling component missing for full structural boot.",
            },
            args.json,
        )
        return 2 if args.require_full_boot else 0

    if requires_safety_unlock and safety_unlock_required_by_manifest and not safety_unlock:
        emit_result(
            "NO_OPERATIVE_MODE",
            component_name,
            {
                **common_details,
                "reason": "Empirical safety unlock is false; operative mode remains suspended.",
            },
            args.json,
        )
        return 3 if args.require_full_boot else 0

    emit_result(
        "FULL_BOOT",
        component_name,
        {
            **common_details,
            "reason": "Assembly verified, sibling present, empirical safety unlock true.",
        },
        args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
