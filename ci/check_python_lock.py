#!/usr/bin/env python3
"""Fail on stale baseline inputs or a Python environment that differs from the lock."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = {
    "ci/requirements-linux.in",
    "requirements.txt",
    "core/src/drivers/plugins/python/modbus_master/requirements.txt",
    "core/src/drivers/plugins/python/modbus_slave/requirements.txt",
    "core/src/drivers/plugins/python/opcua/requirements.txt",
}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(root, installed=False):
    metadata = json.loads((root / "ci/python-lock.json").read_text())
    if metadata["schema"] != "vx.openplc.python-lock/1":
        raise ValueError("unsupported lock metadata schema")
    if sys.platform != "linux" or platform.python_implementation() != "CPython":
        raise ValueError("baseline requires Linux CPython")
    if f"{sys.version_info.major}.{sys.version_info.minor}" not in metadata["python_minors"]:
        raise ValueError("Python minor is outside the validated baseline lock scope")
    if set(metadata["input_files"]) != INPUTS:
        raise ValueError("baseline lock must cover all runtime and plugin requirement inputs")
    for name, expected in metadata["input_files"].items():
        if sha256(root / name) != expected:
            raise ValueError(f"stale Python lock input: {name}")
    digest = sha256(root / "ci/requirements-linux.lock")
    if digest != metadata["lock_sha256"]:
        raise ValueError("Python lock digest does not match ci/python-lock.json")
    result = {
        "schema": "vx.openplc.python-environment/1",
        "lock_sha256": digest,
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "inputs_validated": True,
        "installed_validated": False,
    }
    if installed:
        actual = {
            re.sub(r"[-_.]+", "-", item.metadata["Name"]).lower(): item.version
            for item in importlib.metadata.distributions()
        }
        # pip is supplied by the digest-pinned image's venv bootstrap, not the app.
        result["pip"] = actual.pop("pip", None)
        if actual != metadata["packages"]:
            missing = sorted(set(metadata["packages"]) - set(actual))
            extra = sorted(set(actual) - set(metadata["packages"]))
            changed = {
                name: {"expected": version, "actual": actual[name]}
                for name, version in metadata["packages"].items()
                if name in actual and actual[name] != version
            }
            raise ValueError(f"installed packages differ: missing={missing}, extra={extra}, changed={changed}")
        result["installed_validated"] = True
        result["packages"] = actual
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check(ROOT, args.installed)
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(1, f"Python lock check failed: {exc}\n")
    if args.output:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"Python lock validated ({'installed environment' if args.installed else 'source inputs'})")


if __name__ == "__main__":
    main()
