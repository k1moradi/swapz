# R119 Agent 10 — IN_PROGRESS; source transport only, AUTH0

[Issue #237](https://github.com/k1moradi/swapz/issues/237) · [run 46170807374](https://github.com/k1moradi/swapz/actions/runs/46170807374) · [job 141058585035](https://github.com/k1moradi/swapz/actions/runs/46170807374/job/141058585035), attempt 1. Actual complete Linux checkout and independent agent-container restore not yet qualified; no build or native runtime credit.

## Exact source and publication
Freeze `c5237321d0eb01002cec990deebff60c6f39ac64`, tree `327f200f9e45e4f06a335945cc8fbd6f41aa4f65`, kernel subtree `880d169f92383f438513d55e5fa2652bb3d9e0ae`. Task `c80097ba6ed9f9a80a955726c802f138e27c53c8`; Linux `c339f4010dea8b0d754f84ace70cd1b089878ef8` tree `7494ea078a05b0b824c3f263260e45c1f78bcfd3`. [Source 1bd094c3fcd5d9a294b33b7fb512b696bf34ac33](https://github.com/k1moradi/swapz/commit/1bd094c3fcd5d9a294b33b7fb512b696bf34ac33), sole parent task, tree `41c55a74c20b91d822fbe0dfd38d1a9379ddd726`, expected-head nonforce single-commit update to main and remote readback. Four exact blobs:
- tests/tools/round119-pinned-source-transport.py `aa36a89b28c02f92eddc0b6e369e59886cbe1082`
- tests/runtime/native/round119-pinned-source-transport-test.py `d928211225a85fb1069f454e49cbcd0bc32395a8`
- .github/workflows/phase-a-round119-pinned-source-transport.yml `2a3c21e4783abe300c034c0baff6169681858bd5`
- docs/testing_standards.md `5d53f983d14a44cd1a11421a61342810aebf8bce`
Prior standards blob `6814d8e261086ed96fb4fb21b8622a3e654615c8` recreated exactly, complete prefix preserved. No product change or Agent2 candidate integration.

## Local actual rootless evidence
- Git 2.47.3. Unprivileged actual `python -B tests/runtime/native/round119-pinned-source-transport-test.py` in repository-shaped scratch layout, exit 0, 1 unittest in 0.183s. Real two-commit disposable local repository, shallow clone (actual parent absent), multi-chunk pack, fresh detached restore, source hashes and exact object census. Five negative controls reject corrupted chunk, missing chunk, wrong pack digest, wrong commit pin and dirty checkout. Fixture only, not pinned Linux.
- Workflow PyYAML BaseLoader, both Bash run blocks bash -n, embedded and actual source/test Python AST parse PASS. Exact local Git blob hashes independently matched remote blobs before source publication. Source workflow only own path and read-only contents; 33 possible separate artifact uploads (one manifest, up to 32 chunks).
- Actual direct `git ls-remote https://github.com/torvalds/linux.git HEAD` exit 128: Could not resolve host: github.com. No full local upstream checkout yet.

## Transport and acceptance boundary
Only complete reachable Git object data; no copied Git config, remotes, hooks or credentials. Exact shallow boundary, full tracked clean source, >=50000 tracked paths, required MM/BIO/DM/headers/Kbuild file SHA256/size, no partial/sparse/alternate objects. Separate 16 MiB pack parts, maximum 512 MiB pack, each chunk SHA256/size and combined pack SHA256, 14-day artifact expiry. Fresh restore uses Git strict index-pack, detached exact commit/tree, fsck connectivity, required hashes and object census, no remotes or refs. Hosted toolchain availability inventory, no compile. Actual independent download, materialization, ZIP integrity and full local restore still required. No artifact yet at snapshot; no claim hosted or local Linux PASS.
Hosted snapshot: 1 Set up job: completed/success; 2 Run actions/checkout@v4: completed/success; 3 Exact task and transport source: completed/success; 4 Run actions/checkout@v4: completed/success; 5 Export exact complete source and independently restore: in_progress. First CI error: none observed (not terminal). Artifact count 1.

AUTH=0 Phase A BLOCKED observation UNKNOWN ordinary route compressed handoff/forced RAW/import OFF native/physical NO_GO. Zero full builds, manual dispatches, reruns, native execution, device activity or selector changes. A10 writer lease remains pending terminal disposition; A1 acceptance and integration only. A2 independent candidate unchanged.
