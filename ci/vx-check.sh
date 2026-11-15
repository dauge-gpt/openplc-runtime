#!/usr/bin/env bash
# Baseline checks, with the same explicitly declared exclusions as upstream.
# Prepared image supplies Python/venv, compiler, Go and shellcheck.
# Application Python dependencies are installed into a disposable locked venv.
set -euo pipefail
export CMAKE_BUILD_PARALLEL_LEVEL=2
export CTEST_PARALLEL_LEVEL=1
export OPENPLC_PERSISTENT_DATA_DIR="$PWD/.ci-state"
export OMP_NUM_THREADS=2
report_tool="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/check_reports.py"
python3 "$report_tool" init runtime reports
python_venv=""
finish() {
  status=$?
  trap - EXIT
  baseline=()
  if [[ -f ci/test-counts-baseline.json ]]; then baseline=(--expected-counts ci/test-counts-baseline.json); fi
  if ! python3 "$report_tool" finish runtime reports --exit-code "$status" "${baseline[@]}"; then
    if (( status == 0 )); then status=1; fi
  fi
  if [[ -n "$python_venv" ]]; then rm -rf -- "$python_venv"; fi
  exit "$status"
}
trap finish EXIT
python3 -m unittest discover -s ci -p test_python_lock.py -v 2>&1 | tee reports/python-lock-tests.log
python3 ci/check_python_lock.py
python_venv=$(mktemp -d "$PWD/.ci-python.XXXXXX")
python3 -m venv "$python_venv"
export VIRTUAL_ENV="$python_venv"
export PATH="$python_venv/bin:$PATH"
export PYTHONNOUSERSITE=1
python3 -m pip --isolated --disable-pip-version-check install --timeout 30 --retries 2 \
  --require-hashes --only-binary=:all: -r ci/requirements-linux.lock 2>&1 | tee reports/python-install.log
python3 -m pip --isolated --disable-pip-version-check check 2>&1 | tee reports/pip-check.log
python3 ci/check_python_lock.py --installed --output reports/python-lock.json
mkdir -p "$OPENPLC_PERSISTENT_DATA_DIR"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release 2>&1 | tee reports/configure.log
cmake --build build --parallel 2 2>&1 | tee reports/build.log
bash tests/host/run.sh 2>&1 | tee reports/host.log
python3 -m pytest tests/pytest -q -ra --junitxml=reports/webserver.xml \
  --ignore=tests/pytest/plugins --ignore=tests/pytest/modbus_master \
  --ignore=tests/pytest/modbus_slave 2>&1 | tee reports/webserver.log
python3 -m pytest -q -ra --junitxml=reports/plugins.xml \
  tests/pytest/plugins/opcua/test_string_types.py \
  tests/pytest/plugins/opcua/test_read_status.py \
  tests/pytest/plugins/opcua/test_logger_lifetime.py \
  tests/pytest/plugins/test_vpp_license_delivery.py \
  tests/pytest/plugins/test_vpp_sibling_delivery.py 2>&1 | tee reports/plugins.log
shellcheck -S warning install.sh scripts/install-docker.sh windows/provision-msys2.sh tests/integration/harness.sh 2>&1 | tee reports/shellcheck.log
python3 "$report_tool" installers runtime reports 2>&1 | tee reports/native-installers.log
(
  cd bootloader
  export GOTOOLCHAIN=local
  go version | tee ../reports/go-version.txt
  go env GOVERSION GOTOOLCHAIN | tee ../reports/go-toolchain.txt
  # Enforce go.mod with the image toolchain; never fetch a replacement SDK.
  go list -m >/dev/null
  test -z "$(gofmt -l .)"
  go vet ./...
  go test -race -count=1 -json ./... | tee ../reports/bootloader.jsonl
) 2>&1 | tee reports/bootloader.log
