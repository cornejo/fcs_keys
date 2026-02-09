#!/usr/bin/env python3

"""Decrypt disk images from an IPSW using FCS keys from this repository.

Requires the 'ipsw' tool (https://github.com/blacktop/ipsw).

Usage:
    ./decrypt.py iPhone16,2_18.0_22A5307f_Restore.ipsw
    ./decrypt.py --dmg sys firmware.ipsw -o /tmp/decrypted
    ./decrypt.py --pem-db /path/to/fcs-keys.json firmware.ipsw
"""

import argparse
import os
import plistlib
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
KEYS_DIR = SCRIPT_DIR / "keys"
FCS_KEYS_JSON = SCRIPT_DIR / "fcs-keys.json"

DMG_TYPES = ["sys", "app", "fs", "exc", "rdisk"]


def get_ipsw_info(ipsw_path: str) -> tuple[str, str | None]:
    """Extract build ID and OS from an IPSW's BuildManifest.plist."""
    with zipfile.ZipFile(ipsw_path) as zf:
        with zf.open("BuildManifest.plist") as f:
            manifest = plistlib.load(f)

    build_id = manifest["ProductBuildVersion"]
    product_types = manifest.get("SupportedProductTypes", [])

    apple_os = None
    for pt in product_types:
        if pt.startswith(("iPhone", "iPod")):
            apple_os = "iOS"
        elif pt.startswith("iPad"):
            apple_os = "iPadOS"
        elif pt.startswith(("Mac", "iMac", "VirtualMac")):
            apple_os = "macOS"
        if apple_os:
            break

    return build_id, apple_os


def find_keys(apple_os: str, build_id: str) -> list[Path]:
    """Find individual PEM key files for a given OS and build."""
    key_dir = KEYS_DIR / apple_os / build_id
    if not key_dir.is_dir():
        return []
    return sorted(key_dir.glob("*.pem"))


def main():
    parser = argparse.ArgumentParser(
        description="Decrypt IPSW disk images using FCS keys from this repository.",
        epilog="By default, extracts all DMG types (sys, app, fs, exc, rdisk). "
        "Non-existent DMG types for a given IPSW are silently skipped.",
    )
    parser.add_argument("ipsw", help="Path to the IPSW file")
    parser.add_argument(
        "-o",
        "--output",
        help="Output directory (default: current directory)",
        default=".",
    )
    parser.add_argument(
        "--dmg",
        choices=DMG_TYPES,
        action="append",
        dest="dmg_types",
        help="DMG type to extract (default: all). Can be repeated.",
    )
    parser.add_argument(
        "--os",
        choices=["iOS", "iPadOS", "macOS"],
        dest="apple_os",
        help="Override OS auto-detection",
    )
    parser.add_argument(
        "--build",
        help="Override build ID auto-detection",
    )
    parser.add_argument(
        "--pem-db",
        help="Path to an FCS keys JSON database (default: fcs-keys.json in repo root)",
    )
    args = parser.parse_args()

    ipsw_path = args.ipsw
    if not os.path.isfile(ipsw_path):
        print(f"Error: file not found: {ipsw_path}", file=sys.stderr)
        sys.exit(1)

    # --- Detect build info from the IPSW ---
    build_id: str | None = args.build
    apple_os: str | None = args.apple_os
    if not (build_id and apple_os):
        print("Reading IPSW metadata...")
        try:
            detected_build, detected_os = get_ipsw_info(ipsw_path)
            build_id = build_id or detected_build
            apple_os = apple_os or detected_os
        except Exception as e:
            print(f"Warning: could not read IPSW metadata: {e}", file=sys.stderr)

    if build_id:
        print(f"  Build: {build_id}")
    if apple_os:
        print(f"  OS:    {apple_os}")

    # --- Resolve key source ---
    pem_db = Path(args.pem_db) if args.pem_db else None

    if pem_db is None:
        # Check for individual PEM keys first, fall back to fcs-keys.json
        pem_keys: list[Path] = []
        if apple_os and build_id:
            pem_keys = find_keys(apple_os, build_id)

        if pem_keys:
            # apple_os and build_id are guaranteed non-None when pem_keys is non-empty (see above)
            assert apple_os is not None and build_id is not None
            print(f"  Keys:  {len(pem_keys)} PEM file(s) in {KEYS_DIR / apple_os / build_id}")
        elif FCS_KEYS_JSON.is_file():
            pem_db = FCS_KEYS_JSON
            print(f"  Keys:  {pem_db}")
        else:
            print(
                "Error: no keys found. Ensure this repo has keys/ or fcs-keys.json,\n"
                "       or pass --pem-db explicitly.",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        pem_keys = []
        if not pem_db.is_file():
            print(f"Error: PEM database not found: {pem_db}", file=sys.stderr)
            sys.exit(1)
        print(f"  Keys:  {pem_db}")

    # --- Build ipsw extract command ---
    dmg_types = args.dmg_types or DMG_TYPES
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    # When individual PEMs are available, build a temporary pem-db JSON from them
    # so we can use the same ipsw extract --pem-db interface for both paths.
    if pem_keys and pem_db is None:
        import base64
        import json
        import hashlib
        import tempfile

        db: dict[str, str] = {}
        for pem_path in pem_keys:
            pem_data = pem_path.read_bytes()
            key_hash = base64.urlsafe_b64encode(hashlib.sha256(pem_data).digest()).decode()
            db[key_hash] = base64.b64encode(pem_data).decode()

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="fcs-keys-", delete=False)
        json.dump(db, tmp)
        tmp.close()
        pem_db = Path(tmp.name)
        cleanup_pem_db = True
    else:
        cleanup_pem_db = False

    assert pem_db is not None
    try:
        extracted_any = False
        for dmg_type in dmg_types:
            cmd: list[str] = [
                "ipsw",
                "extract",
                "--dmg",
                dmg_type,
                "--pem-db",
                str(pem_db),
                "--output",
                output_dir,
                ipsw_path,
            ]
            print(f"\nExtracting {dmg_type} DMG: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                extracted_any = True
                if result.stdout.strip():
                    print(result.stdout.strip())
            else:
                # ipsw returns non-zero when a DMG type doesn't exist in the IPSW,
                # which is expected — not every IPSW has all five DMG types.
                stderr = result.stderr.strip()
                if stderr:
                    print(f"  Skipped ({stderr})")
                else:
                    print(f"  Skipped (no {dmg_type} DMG in this IPSW)")

        if extracted_any:
            print(f"\nDecrypted DMGs written to: {os.path.abspath(output_dir)}")
        else:
            print(
                "\nNo DMGs could be extracted. The IPSW may not contain AEA-encrypted images,\n"
                "or the required key may not be in the database.",
                file=sys.stderr,
            )
            sys.exit(1)
    finally:
        if cleanup_pem_db:
            os.unlink(pem_db)


if __name__ == "__main__":
    main()
