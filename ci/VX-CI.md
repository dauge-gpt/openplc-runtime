# VX fork CI

Run `bash ci/vx-check.sh` in the prepared, digest-pinned CI image.
The trusted workflow lives in private dauge-gpt/vx_ahu_project.
No self-hosted runner is registered on this public fork.
Upstream workflows are preserved, inactive, in .github/upstream-workflows.
Enable no upstream release/PR automation without review.
The reports directory must be empty; the private wrapper provides a fresh one.
check_reports.py validates measured counts and writes test-summary.json.
Missing reports or tests fail; declared upstream exclusions remain explicit.
This baseline check does not qualify WB/Windows/Android or the VX integration.
