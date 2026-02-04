"""
PHOENIX Chrome Extension Build & Packaging Script (Build #69)

Packages the Chrome extension for distribution:
- Validates manifest.json
- Creates versioned .zip for Chrome Web Store upload
- Creates update.xml manifest for self-hosted auto-update
- Generates build info JSON

Usage:
    python build_extension.py                    # Build zip
    python build_extension.py --version 1.0.1    # Set version
    python build_extension.py --output dist/     # Custom output dir
    python build_extension.py --update-url https://phoenix.app/ext/  # Set update URL
"""

import argparse
import hashlib
import json
import os
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom.minidom import parseString


REQUIRED_MANIFEST_KEYS = ["manifest_version", "name", "version", "permissions", "background"]

EXPECTED_FILES = [
    "background.js",
    "content.js",
    "popup.html",
    "popup.js",
    "options.html",
    "options.js",
    "onboarding.html",
    "onboarding.js",
    "icons/icon16.png",
    "icons/icon48.png",
    "icons/icon128.png",
]

EXCLUDE_PATTERNS = {"__pycache__", ".git", ".DS_Store"}
EXCLUDE_EXTENSIONS = {".pyc"}

PLACEHOLDER_EXTENSION_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def validate_manifest(ext_dir):
    """Read and validate manifest.json.

    Checks required keys and verifies all referenced files exist on disk.

    Args:
        ext_dir: Path to the extension directory.

    Returns:
        Tuple of (is_valid, errors_list).
    """
    errors = []
    manifest_path = os.path.join(ext_dir, "manifest.json")

    if not os.path.isfile(manifest_path):
        return False, ["manifest.json not found in extension directory"]

    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
    except json.JSONDecodeError as exc:
        return False, [f"manifest.json is not valid JSON: {exc}"]

    for key in REQUIRED_MANIFEST_KEYS:
        if key not in manifest:
            errors.append(f"Missing required manifest key: {key}")

    if manifest.get("manifest_version") != 3:
        errors.append("manifest_version must be 3 (Manifest V3)")

    for rel_path in EXPECTED_FILES:
        full_path = os.path.join(ext_dir, rel_path)
        if not os.path.isfile(full_path):
            errors.append(f"Referenced file missing: {rel_path}")

    is_valid = len(errors) == 0
    return is_valid, errors


def _should_exclude(name):
    """Return True if a file or directory name should be excluded from the zip."""
    if name in EXCLUDE_PATTERNS:
        return True
    _, ext = os.path.splitext(name)
    if ext in EXCLUDE_EXTENSIONS:
        return True
    return False


def build_zip(ext_dir, output_dir, version=None):
    """Create a distributable .zip of the extension.

    If *version* is provided the manifest.json version field is updated
    before packaging.  The zip is written to *output_dir*.

    Args:
        ext_dir: Path to the extension directory.
        output_dir: Directory where the zip will be created.
        version: Optional version string to stamp into the manifest.

    Returns:
        Absolute path to the created zip file.
    """
    manifest_path = os.path.join(ext_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    if version:
        manifest["version"] = version
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2)
            fh.write("\n")
    else:
        version = manifest.get("version", "0.0.0")

    os.makedirs(output_dir, exist_ok=True)

    zip_name = f"phoenix_extension_v{version}.zip"
    zip_path = os.path.join(output_dir, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ext_dir):
            # Filter out excluded directories in-place so os.walk skips them
            dirs[:] = [d for d in dirs if not _should_exclude(d)]

            for filename in files:
                if _should_exclude(filename):
                    continue
                abs_path = os.path.join(root, filename)
                arc_name = os.path.relpath(abs_path, ext_dir)
                zf.write(abs_path, arc_name)

    return os.path.abspath(zip_path)


def generate_update_xml(version, update_url, output_dir, manifest_path=None):
    """Create an update.xml for self-hosted auto-update.

    Args:
        version: Extension version string.
        update_url: Base URL where the zip will be hosted.
        output_dir: Directory to write update.xml into.
        manifest_path: Optional path to manifest.json to read the key field.

    Returns:
        Absolute path to the written update.xml.
    """
    extension_id = PLACEHOLDER_EXTENSION_ID
    if manifest_path and os.path.isfile(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        key = manifest.get("key", "")
        if key:
            raw = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
            extension_id = "".join(chr(ord("a") + int(c, 16)) for c in raw)

    update_url = update_url.rstrip("/")
    codebase = f"{update_url}/phoenix_extension_v{version}.zip"

    gupdate = Element("gupdate")
    gupdate.set("xmlns", "http://www.google.com/update2/response")
    gupdate.set("protocol", "2.0")

    app = SubElement(gupdate, "app")
    app.set("appid", extension_id)

    updatecheck = SubElement(app, "updatecheck")
    updatecheck.set("codebase", codebase)
    updatecheck.set("version", version)

    raw_xml = tostring(gupdate, encoding="unicode")
    pretty = parseString(raw_xml).toprettyxml(indent="  ", encoding="UTF-8")

    os.makedirs(output_dir, exist_ok=True)
    xml_path = os.path.join(output_dir, "update.xml")
    with open(xml_path, "wb") as fh:
        fh.write(pretty)

    return os.path.abspath(xml_path)


def generate_build_info(ext_dir, version, zip_path, output_dir):
    """Create build_info.json with metadata about the build.

    Args:
        ext_dir: Path to the extension directory.
        version: Version string.
        zip_path: Path to the built zip file.
        output_dir: Directory to write build_info.json into.

    Returns:
        The build-info dict (also written to disk).
    """
    manifest_path = os.path.join(ext_dir, "manifest.json")
    with open(manifest_path, "r", encoding="utf-8") as fh:
        manifest = json.load(fh)

    file_count = 0
    total_size = 0
    for root, dirs, files in os.walk(ext_dir):
        dirs[:] = [d for d in dirs if not _should_exclude(d)]
        for filename in files:
            if _should_exclude(filename):
                continue
            file_count += 1
            total_size += os.path.getsize(os.path.join(root, filename))

    zip_size = os.path.getsize(zip_path)

    sha256 = hashlib.sha256()
    with open(zip_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            sha256.update(chunk)
    sha256_hex = sha256.hexdigest()

    build_info = {
        "version": version,
        "build_date": datetime.now(timezone.utc).isoformat(),
        "manifest_version": manifest.get("manifest_version"),
        "file_count": file_count,
        "total_size_bytes": total_size,
        "zip_size_bytes": zip_size,
        "sha256_hash": sha256_hex,
    }

    os.makedirs(output_dir, exist_ok=True)
    info_path = os.path.join(output_dir, "build_info.json")
    with open(info_path, "w", encoding="utf-8") as fh:
        json.dump(build_info, fh, indent=2)
        fh.write("\n")

    return build_info


def _format_size(size_bytes):
    """Return a human-readable file size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def main():
    parser = argparse.ArgumentParser(
        description="PHOENIX Chrome Extension Build & Packaging Script"
    )
    parser.add_argument(
        "--ext-dir",
        default="phoenix_extension",
        help="Path to the extension source directory (default: phoenix_extension/)",
    )
    parser.add_argument(
        "--output",
        default="dist",
        help="Output directory for build artefacts (default: dist/)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version to stamp into the manifest (default: read from manifest)",
    )
    parser.add_argument(
        "--update-url",
        default=None,
        help="Base URL for self-hosted auto-update (generates update.xml)",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate the manifest, do not build",
    )

    args = parser.parse_args()

    ext_dir = os.path.abspath(args.ext_dir)
    output_dir = os.path.abspath(args.output)

    print("Phoenix Extension Builder")
    print("=" * 24)

    # --- Validate -----------------------------------------------------------
    print("Validating manifest... ", end="", flush=True)
    is_valid, errors = validate_manifest(ext_dir)
    if not is_valid:
        print("FAILED")
        for err in errors:
            print(f"  ERROR: {err}")
        sys.exit(1)
    print("OK")

    if args.validate_only:
        print("\nValidation passed. Exiting (--validate-only).")
        sys.exit(0)

    # --- Determine version --------------------------------------------------
    version = args.version
    if version is None:
        with open(os.path.join(ext_dir, "manifest.json"), "r", encoding="utf-8") as fh:
            version = json.load(fh).get("version", "0.0.0")

    # --- Build zip ----------------------------------------------------------
    print("Building zip... ", end="", flush=True)
    zip_path = build_zip(ext_dir, output_dir, version=args.version)
    zip_size = os.path.getsize(zip_path)
    zip_name = os.path.basename(zip_path)
    print(f"{zip_name} ({_format_size(zip_size)})")

    # --- Optional update.xml ------------------------------------------------
    if args.update_url:
        print("Generating update.xml... ", end="", flush=True)
        manifest_path = os.path.join(ext_dir, "manifest.json")
        generate_update_xml(version, args.update_url, output_dir, manifest_path)
        print("OK")

    # --- Build info ---------------------------------------------------------
    build_info = generate_build_info(ext_dir, version, zip_path, output_dir)
    print(f"Build info written to {os.path.join(output_dir, 'build_info.json')}")

    # --- Summary ------------------------------------------------------------
    print(f"\nBuild complete:")
    print(f"  Version: {version}")
    print(f"  Output:  {zip_path}")
    print(f"  SHA256:  {build_info['sha256_hash']}")


if __name__ == "__main__":
    main()
