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
