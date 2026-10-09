# Offline rootless CI evidence inventory

The script tests/runtime/rootless-ci-evidence-inventory.py checks **internal consistency only** of caller-supplied GitHub Actions metadata for the three mandatory rootless workflows. It does not authenticate Github, a runner, physical device, collector, benchmark, or backing-release decision.

## Offline input schema

The top-level JSON contains exactly: schema, repository, source_revision, and runs.

- schema: swapz-rootless-ci-evidence-input-v1
- repository: k1moradi/swapz
- source_revision: one 40-character lowercase hexadecimal source SHA
- runs: three entries, one for each rootless workflow, all at the exact same SHA and event

Each run has exactly: id, name, head_sha, run_attempt, event, status, conclusion, jobs. The event is push, pull_request, or workflow_dispatch. Require completed and success, unique positive integer run IDs, and positive integer run attempts. Each run has one job.

Each job has exactly: id, run_id, head_sha, run_attempt, name, status, conclusion, steps. Job identity/attempt/SHA must match its parent run. Name is one-revision for combined, source-only otherwise. Each ordered step has exactly: number (consecutive starting at 1), name (unique), status (completed), conclusion (success or skipped). Every mandatory test step must have succeeded; skipped optional steps are allowed. Failed, canceled, ambiguous, or missing steps deny qualification. No arbitrary log-line PASS markers are treated as executed tests.

The expected workflow names are:

- Rootless combined source qualification
- Rootless teardown safety
- Rootless NBD source safety

Normalize exactly the listed fields from actual downloaded GitHub run and job-step JSON, including the actual run attempt. Never fabricate fields missing from the provider. The normalized input remains *unauthenticated and fabricable*.

## Usage

    python3 -B tests/runtime/rootless-ci-evidence-inventory.py --bundle /path/to/offline-runs.json > /path/to/inventory.json
    python3 -B tests/runtime/rootless-ci-evidence-inventory-test.py -v

Input size is limited to 2 MiB, three runs, one job per run, and 128 steps per job. The code rejects duplicate JSON keys, extra fields, inconsistent run/job/step identities, missing gates, noncanonical source revision, symlink input, invalid regular-file properties, mixed attempts/events, and contradictory outcomes. A retained descriptor, O_NOFOLLOW, bounded reads, and before/after descriptor metadata protect the input-read operation. This does not make the contents independently authentic.

## Output meaning

Success prints deterministic JSON listing source SHA, workflow run/job IDs, attempts, events and required step counts. The inventory explicitly sets:

- source_authenticated: false
- step_execution_independently_attested: false
- repeat_counts_independently_attested: false
- authenticated_collector: false
- independent_device_identity_proved: false
- kernel_drain_proved: false
- physical_selection_authorized: false
- backing_release_authorized: false
- production_qualified: false
- v22_strategy_and_batch_winner: UNDETERMINED

Six authorization flags appear inside the qualification object. A green workflow step records only the provided GitHub-shaped step status, not real worker execution or physically attributable I/O drain. The tool does not qualify a later documentation-only commit as separately tested. Invalid data fails nonzero with stderr-only denial and no success report.

This utility executes no privileged DM, loop, NBD, swap, module, physical storage, or destructive device commands. Both joint workflows must run its rootless adversarial test suite under a timeout; the standalone NBD workflow retains its own mandatory source-only contract.
