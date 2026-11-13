#!/usr/bin/env python3
"""Validate actual test reports; measured counts are not a qualified baseline.

The same stdlib-only helper is installed in both public forks. The private
dispatcher owns report-directory cleanup; direct runs reject stale results.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


RUNTIME_EXCLUSIONS = [
    "tests/pytest/plugins (except the five explicitly selected files)",
    "tests/pytest/modbus_master",
    "tests/pytest/modbus_slave",
]
PLUGIN_FILES = [
    "tests/pytest/plugins/opcua/test_string_types.py",
    "tests/pytest/plugins/opcua/test_read_status.py",
    "tests/pytest/plugins/opcua/test_logger_lifetime.py",
    "tests/pytest/plugins/test_vpp_license_delivery.py",
    "tests/pytest/plugins/test_vpp_sibling_delivery.py",
]
COUNT_KEYS = ("total", "passed", "failed", "skipped", "todo", "errors")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def counts(total=0, passed=0, failed=0, skipped=0, todo=0, errors=0):
    result = dict(zip(COUNT_KEYS, (total, passed, failed, skipped, todo, errors)))
    require(all(type(v) is int and v >= 0 for v in result.values()), "invalid test counts")
    require(total == passed + failed + skipped + todo + errors, "inconsistent test counts")
    return result


def healthy(result):
    require(result["total"] > 0 and result["passed"] > 0, "suite has no passing tests")
    require(result["failed"] == 0 and result["errors"] == 0, "suite contains failures/errors")
    return result


def initialize(component, reports, source):
    require(not reports.is_symlink(), "reports must not be a symlink")
    reports.mkdir(parents=True, exist_ok=True)
    # The dispatcher may have recorded its prepared environment before entry.
    require(not any(p.name != "environment" for p in reports.iterdir()),
            "reports is not fresh; preserve previous evidence and use a clean run")
    environment = reports / "environment"
    require(not environment.is_symlink() and (not environment.exists() or environment.is_dir()),
            "environment must be a real directory")
    limits = {
        "schema": "vx.openplc.ci-scope/1", "component": component,
        "scope": "upstream baseline checks; not VX migration acceptance",
        "not_run": ["WB integration/timing", "Windows IDE", "Android client",
                    "physical plant", "24/72 hour soak", "VX runtime extensions"],
        "count_baseline": "not frozen until reviewed successful exact-SHA evidence exists",
    }
    if component == "editor":
        config = load_json(source / "jest.config.json")
        limits["excluded"] = config.get("testPathIgnorePatterns", [])
        limits["test_match"] = config.get("testMatch", [])
        limits["not_run"] += ["native IDE import/upload/debug E2E"]
    else:
        limits["excluded"] = RUNTIME_EXCLUSIONS
        limits["selected_plugin_files"] = PLUGIN_FILES
        limits["not_run"] += ["lifecycle harness (requires IEC payload and scheduling environment)"]
        host_script = (source / "tests/host/run.sh").read_text(encoding="utf-8")
        host_sources = re.findall(r'^\s*"(tests/host/test_[^"\s:]+\.cpp):', host_script, re.MULTILINE)
        require(host_sources and len(host_sources) == len(set(host_sources)), "invalid host test inventory")
        actual_sources = {p.relative_to(source).as_posix() for p in (source / "tests/host").glob("test_*.cpp")}
        require(set(host_sources) == actual_sources, "host sources and run.sh test inventory differ")
        write_json(reports / "host-plan.json", [Path(p).stem for p in host_sources])
    write_json(reports / "limitations.json", limits)


def junit(path):
    root = ET.parse(path).getroot()
    require(root.tag in {"testsuite", "testsuites"}, "invalid JUnit root")
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    # pytest emits flat suites. Reject nested suites to avoid counting twice.
    require(all(not list(s.findall("testsuite")) for s in suites), "nested JUnit suites unsupported")
    result = counts()
    for suite in suites:
        cases = suite.findall("testcase")
        measured = dict.fromkeys(COUNT_KEYS, 0)
        measured["total"] = len(cases)
        for case in cases:
            outcomes = [key for key, tag in (("failed", "failure"), ("errors", "error"),
                                            ("skipped", "skipped")) if case.find(tag) is not None]
            require(len(outcomes) <= 1, "ambiguous JUnit outcome")
            measured[outcomes[0] if outcomes else "passed"] += 1
        for attribute, key in (("tests", "total"), ("failures", "failed"),
                               ("errors", "errors"), ("skipped", "skipped")):
            require(int(suite.attrib.get(attribute, "0")) == measured[key],
                    f"JUnit {attribute} does not match testcase outcomes")
        for key in COUNT_KEYS:
            result[key] += measured[key]
    return counts(**result)


def jest(report, plan):
    data = load_json(report)
    planned = load_json(plan)
    require(isinstance(planned, list) and planned and all(isinstance(p, str) for p in planned),
            "empty/invalid Jest discovery plan")
    require(len(planned) == len(set(planned)), "duplicate Jest discovery entries")
    suites = data["testResults"]
    require(len(suites) == len(planned) and {s["name"] for s in suites} == set(planned),
            "Jest execution differs from discovered test files")
    require(data["numTotalTestSuites"] == len(planned), "Jest suite count differs")
    require(data.get("success") is True and data.get("numFailedTestSuites") == 0
            and data.get("numRuntimeErrorTestSuites", 0) == 0, "Jest reports unsuccessful run")
    result = dict.fromkeys(COUNT_KEYS, 0)
    statuses = {"passed": "passed", "failed": "failed", "pending": "skipped", "todo": "todo"}
    for suite in suites:
        for case in suite["assertionResults"]:
            require(case["status"] in statuses, "unknown Jest assertion status")
            result[statuses[case["status"]]] += 1
            result["total"] += 1
    for field, key in (("numTotalTests", "total"), ("numPassedTests", "passed"),
                       ("numFailedTests", "failed"), ("numPendingTests", "skipped"),
                       ("numTodoTests", "todo")):
        require(type(data.get(field)) is int and data[field] == result[key], f"Jest {field} differs")
    return counts(**result)


def host(log, plan):
    text = log.read_text(encoding="utf-8")
    names = re.findall(r"^=== (test_[A-Za-z0-9_]+) ===$", text, re.MULTILINE)
    require(names == load_json(plan), "executed host test inventory differs")
    require("host tests: all passed" in text and not re.search(r"^\s*FAIL\s", text, re.MULTILINE),
            "host suite did not finish successfully")
    return counts(total=len(names), passed=len(names))


def golang(path):
    completed = {}
    packages = {}
    started = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        action = item["Action"]
        package = item.get("Package")
        test = item.get("Test")
        if test and action == "run":
            started.add((package, test))
        if action in {"pass", "fail", "skip"}:
            target = completed if test else packages
            key = (package, test) if test else package
            require(key not in target, "duplicate Go completion")
            target[key] = action
    require(started == set(completed), "unfinished or unstarted Go test")
    require(packages and all(status != "fail" for status in packages.values()), "Go package failed/missing")
    require(all(package in packages for package, _ in completed), "unfinished Go package")
    values = list(completed.values())
    return counts(total=len(values), passed=values.count("pass"), failed=values.count("fail"),
                  skipped=values.count("skip"))


def native_installers(source):
    """Preserve upstream tests.yml's native-installer contract after archiving YAML."""
    callers = [".github/upstream-workflows/windows-installer.yml.disabled",
               "windows/provision-msys2.sh"]
    images = ["Dockerfile", "Dockerfile.dev"]
    for name in callers:
        text = (source / name).read_text(encoding="utf-8")
        require(not re.search(r"(^|[^-])\./install\.sh[ \t]*$", text, re.MULTILINE),
                f"{name}: calls ./install.sh without --native")
    for name in images:
        text = (source / name).read_text(encoding="utf-8")
        require(re.search(r"install\.sh[ \t]+--native(?:[ \t]|$)", text, re.MULTILINE),
                f"{name}: must run ./install.sh --native")
    return {"status": "pass", "checked_files": callers + images}


def finish(component, reports, exit_code, expected_counts=None):
    result = {"schema": "vx.openplc.ci-results/1", "component": component,
              "command_exit_code": exit_code, "groups": {}, "errors": [],
              "baseline_counts_locked": expected_counts is not None}
    readers = {"jest": lambda: jest(reports / "jest.json", reports / "jest-plan.json")} if component == "editor" else {
        "host_executables": lambda: host(reports / "host.log", reports / "host-plan.json"),
        "webserver": lambda: junit(reports / "webserver.xml"),
        "selected_plugins": lambda: junit(reports / "plugins.xml"),
        "bootloader": lambda: golang(reports / "bootloader.jsonl"),
    }
    try:
        scope = load_json(reports / "limitations.json")
        require(scope["component"] == component, "scope component mismatch")
    except (ValueError, KeyError, TypeError, OSError) as error:
        result["errors"].append(f"scope: {error}")
    for name, reader in readers.items():
        try:
            measured = reader()
            result["groups"][name] = measured
            healthy(measured)
        except (ValueError, KeyError, TypeError, OSError, ET.ParseError) as error:
            result["errors"].append(f"{name}: {error}")
    if expected_counts is not None:
        try:
            baseline = load_json(expected_counts)
            require(baseline["component"] == component, "count baseline component mismatch")
            require(baseline["groups"] == result["groups"], "test counts differ from reviewed baseline")
        except (ValueError, KeyError, TypeError, OSError) as error:
            result["errors"].append(f"count baseline: {error}")
    result["status"] = "pass" if exit_code == 0 and not result["errors"] else "fail"
    write_json(reports / "test-summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["init", "finish", "installers"])
    parser.add_argument("component", choices=["editor", "runtime"])
    parser.add_argument("reports", type=Path)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--expected-counts", type=Path)
    args = parser.parse_args()
    try:
        if args.operation == "init":
            initialize(args.component, args.reports, args.source)
            return 0
        if args.operation == "installers":
            require(args.component == "runtime", "installer contract belongs to runtime")
            result = native_installers(args.source)
            write_json(args.reports / "native-installers.json", result)
            print(json.dumps(result, sort_keys=True))
            return 0
        result = finish(args.component, args.reports, args.exit_code, args.expected_counts)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "pass" else 1
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
