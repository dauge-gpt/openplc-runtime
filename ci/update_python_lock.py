#!/usr/bin/env python3
"""Explicitly refresh the baseline wheel lock; never called by ordinary CI checks."""
import argparse
import concurrent.futures
import datetime
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from check_python_lock import INPUTS, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        parser.error("--source-sha must be a complete commit SHA")
    if sys.platform != "linux" or platform.python_implementation() != "CPython" or sys.version_info[:2] not in ((3, 12), (3, 13)):
        parser.error("resolve using Linux CPython 3.12 or 3.13")
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "pip-report.json"
        subprocess.run([
            sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check",
            "install", "--dry-run", "--ignore-installed", "--only-binary=:all:",
            "--timeout", "30", "--retries", "2", "--report", str(report),
            "-r", str(ROOT / "ci/requirements-linux.in"),
        ], check=True)
        resolution = json.loads(report.read_text())
    date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    lines = [
        f"# OpenPLC baseline Python lock, resolved {date}.",
        "# Scope: Linux CPython 3.12/3.13. Install only wheels with --require-hashes.",
        "# All published wheel hashes for each pinned release; source archives are excluded.",
        "# Input hashes and resolver identity: ci/python-lock.json.", "",
    ]
    packages = {}
    def release_hashes(item):
        name = re.sub(r"[-_.]+", "-", item["metadata"]["name"]).lower()
        version = item["metadata"]["version"]
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=30) as response:
            release = json.load(response)
        hashes = sorted({entry["digests"]["sha256"] for entry in release["urls"] if entry["packagetype"] == "bdist_wheel"})
        selected = item["download_info"]["archive_info"]["hashes"]["sha256"]
        if not hashes or selected not in hashes:
            raise ValueError(f"resolver wheel hash missing from PyPI release: {name}=={version}")
        return name, version, hashes

    # Fetch independent release metadata concurrently; output order stays stable.
    items = sorted(resolution["install"], key=lambda item: item["metadata"]["name"].lower())
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        releases = list(pool.map(release_hashes, items))
    for name, version, hashes in releases:
        lines.append(f"{name}=={version} \\")
        lines.extend(f"    --hash=sha256:{digest}" + (" \\" if index < len(hashes) - 1 else "") for index, digest in enumerate(hashes))
        lines.append("")
        packages[name] = version
    lock = "\n".join(lines)
    metadata = {
        "schema": "vx.openplc.python-lock/1",
        "resolved_date": date,
        "scope": "baseline-only; not a qualified WB install",
        "python_minors": ["3.12", "3.13"], "platform": "linux",
        "source_base_sha": args.source_sha,
        "resolver": {"python": platform.python_version(), "pip": importlib.metadata.version("pip")},
        "input_files": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(INPUTS)},
        "lock_sha256": hashlib.sha256(lock.encode()).hexdigest(),
        "packages": packages,
    }
    (ROOT / "ci/requirements-linux.lock").write_text(lock)
    (ROOT / "ci/python-lock.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(f"Updated baseline lock: {len(packages)} packages; review diff and validate all declared targets before commit")


if __name__ == "__main__":
    main()
