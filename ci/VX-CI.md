# VX fork CI

Run `bash ci/vx-check.sh` in the prepared, digest-pinned CI image.
The trusted workflow lives in private dauge-gpt/vx_ahu_project.
No self-hosted runner is registered on this public fork.
Unity admits at most two Linux runners from different repositories, one job per repository.
Both OpenPLC forks use the AHU runner and share the vx_ahu_project admission slot.
Before dispatch, review active/admitted queued runs and unfinished job chains, including wirenboard.
Allow AHU only when one slot is free and no other AHU run is admitted; coordinate with other operators.
This review is procedural, not an atomic host semaphore; wirenboard settings are unchanged.
Keep two build tasks and one CTest worker per job, with 24 GiB as the combined soft host budget.
Upstream workflows are preserved, inactive, in .github/upstream-workflows.
Enable no upstream release/PR automation without review.
The reports directory must be empty; the private wrapper provides a fresh one.
check_reports.py validates measured counts and writes test-summary.json.
Missing reports or tests fail; declared upstream exclusions remain explicit.
This baseline check does not qualify WB/Windows/Android or the VX integration.

## M01 Python baseline lock (2026-11-15)

`ci/requirements-linux.in` covers the upstream runtime requirements and all three
Python plugin requirement files used by the upstream test setup. Their contents
remain unchanged. `ci/requirements-linux.lock` fixes the complete 56-package
closure and published wheel SHA-256 values. `ci/python-lock.json` records the
input/lock hashes, versions, source commit and resolver identity.

`ci/vx-check.sh` checks input hashes before installation, creates a disposable
venv in the checkout, and uses pip `--isolated --require-hashes
--only-binary=:all:` with a 30-second network timeout and two retries. Source
archives cannot start an unpinned build-backend dependency chain. Pip comes from
the existing digest-pinned image's venv bootstrap; its version is recorded.
`pip check` and an exact installed-package comparison precede the existing tests.
The venv is removed on exit; the image and host Python are not modified.
Ordinary CI never refreshes the lock. Reports include `python-install.log`,
`pip-check.log`, and `python-lock.json` with installed versions and the lock hash.

The existing image must provide Linux CPython 3.12 or 3.13 with venv and development
headers/libpython, C/C++17, CMake, Ninja, pkg-config, shellcheck, and Go satisfying
`bootloader/go.mod` (currently >=1.25.0). Go runs with `GOTOOLCHAIN=local`; an
insufficient image fails instead of downloading another SDK. Module-context
`go-version.txt` and `go-toolchain.txt` report the actual compiler selection.
Go modules remain covered by the existing `go.sum`.

Refresh only as an explicit dependency update from a reviewed source revision:

```sh
python3 ci/update_python_lock.py --source-sha <full-reviewed-runtime-commit>
python3 -m unittest discover -s ci -p test_python_lock.py -v
python3 -m venv .venv-lock-review
.venv-lock-review/bin/python -m pip --isolated --disable-pip-version-check install \
  --timeout 30 --retries 2 --require-hashes --only-binary=:all: \
  -r ci/requirements-linux.lock
.venv-lock-review/bin/python -m pip check
.venv-lock-review/bin/python ci/check_python_lock.py --installed
```

Review the complete version/hash diff, resolve with pip for each declared Python
minor/architecture, and run `bash ci/vx-check.sh` in the existing trusted wrapper.
Refresh uses only stdlib and pip; it resolves upstream constraints, confirms each
selected wheel digest against PyPI release metadata, and records all published
wheel hashes for the selected versions. Do not freeze test-count baselines until
the complete suite passes in its intended unity environment.

The dated local evidence in `ci/validation/local-2026-11-15.json` records a native
Linux x86_64 CPython 3.12 install, CMake build, six host suites, selected plugin
checks, installer checks and Go race tests. The complete webserver scope had six
socket-related failures in the local execution sandbox; these are recorded, not
skipped or treated as a green baseline. Hash-verified wheel resolution also
succeeded for CPython 3.12/3.13 x86_64/aarch64 (the selected wheels need glibc >=2.34).
Cross-target resolution does not execute those interpreters or qualify the WB
runtime. The next acceptance run belongs on unity, followed by direct WB8.5
hardware validation using the existing read-only `wirenboard/wbqt.sh` deployment
path; no emulator, VM or additional workflow chain is introduced here.
