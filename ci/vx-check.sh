#!/usr/bin/env bash
# Baseline checks, with the same explicitly declared exclusions as upstream.
# Prepared image supplies Python dependencies, compiler, Go and shellcheck.
set -euo pipefail
export CMAKE_BUILD_PARALLEL_LEVEL=2
export CTEST_PARALLEL_LEVEL=1
export OPENPLC_PERSISTENT_DATA_DIR="$PWD/.ci-state"
export OMP_NUM_THREADS=2
report_tool="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/check_reports.py"
python3 "$report_tool" init runtime reports
finish() {
  status=$?
  trap - EXIT
  baseline=()
  if [[ -f ci/test-counts-baseline.json ]]; then baseline=(--expected-counts ci/test-counts-baseline.json); fi
  if ! python3 "$report_tool" finish runtime reports --exit-code "$status" "${baseline[@]}"; then
    if (( status == 0 )); then status=1; fi
  fi
  exit "$status"
}
trap finish EXIT
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
  test -z "$(gofmt -l .)"
  go vet ./...
  go test -race -count=1 -json ./... | tee ../reports/bootloader.jsonl
) 2>&1 | tee reports/bootloader.log
