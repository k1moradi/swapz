# Systemd runtime-health integration handoff

This change adds the source contract for `swapz-primary-runtime-health` and
`swapz-primary-runtime-health.service`, generator hibernation guards, mapper
post-stop diagnostics, cold-boot resume exclusion, and the rootless regression
coverage. It intentionally does not edit the package installer owned by Agent
10 and does not add a second test runner owned by Agent 12.

## Agent 10 installation contract

Install `packaging/swapz-primary-runtime-health` to the package sbin directory
mode 0755 and `packaging/swapz-primary-runtime-health.service` to the systemd
unit directory mode 0644. Substitute `@SWAPZ_SBINDIR@` in the new service as
for existing lifecycle units. Include both files in package ownership hashes,
upgrade rollback, modified-copy uninstall refusal, and exact uninstall cleanup.
The helper must be installed before the package's daemon-reload so generated
hibernation drop-ins never reference a missing executable.

Package install must keep all primary units disabled and must not start the
monitor, mapper, passive swap, hibernation action, swapon/swapoff, or mapper
mutation. An upgrade must preserve the existing no-live-mapper safety gate.

## Agent 12 runner contract

No new runner registration is required: the owned test file
`tests/runtime/native/systemd/swapz-primary-systemd-test.py` is already invoked
by the official rootless stage. Preserve that registration and its CI contract;
do not create an alternate public test command.

## Real-host evidence still required

After Agent 10 lands installation, the development host still needs exact-source
package regression, install/upgrade/uninstall ownership checks, daemon-reload
generation of all three hibernation guards, runtime monitor start/stop and
journal state-change evidence, and a controlled native stop-failure diagnostic
exercise where safe. No agent reboot is authorized. The existing owner-triggered
cold-boot arm/reboot/observe harness remains the only source of observed
cold-boot PASS.
