# Systemd runtime-health release readiness

The runtime-health helper and service are installed by
`packaging/package-dkms.sh`, covered by package ownership hashes, upgrade
rollback, modified-copy uninstall refusal, and exact uninstall cleanup. The
official rootless runner still invokes
`tests/runtime/native/systemd/swapz-primary-systemd-test.py`, and the separate
systemd/package readiness workflow provides a fast CI result that cannot be
hidden by an earlier benchmark or source-contract failure.

## Hibernation and resume boundary

Primary swapz does not support hibernation because its mapper/run authority is
volatile across a fresh boot. The generated hibernate, hybrid-sleep, and
suspend-then-hibernate guards are read-only. While a valid primary target is
configured, hibernation is refused for the complete configured interval even if
`/proc/swaps` is currently empty. Mapper activation independently refuses to
start while a hibernation-capable systemd unit is active or activating. This
two-sided admission policy closes the check-then-activate race without
automatically stopping swap.

Resume aliases that cannot be resolved are rejected when a selected swapz
identity exists. A provably distinct canonical PARTUUID may still be treated as
unrelated when the removable target is absent. Current runtime/config checks do
not by themselves prove the bytes embedded in every distribution's initramfs
or UKI; release qualification must inspect the actual boot artifact and
boot-loader configuration for the release host.

## Runtime operations

`swapz-primary-runtime-health.service` is an observer only. Its active systemd
state is not a health verdict: operators must use the latest
`SWAPZ_RUNTIME_HEALTH=` journal record. `FAIL` preserves evidence and never
causes automatic swapoff, mapper removal, reformatting, or lifecycle restart.
External observation commands are time-bounded and the production helper uses a
fixed system executable path and locale.

Package installation keeps all primary units disabled and does not start the
mapper, monitor, passive swap, hibernation action, or any swap mutation. The
production userspace lifecycle compile gate remains disabled until a frozen
release candidate completes the physical lifecycle/capacity qualification.

## Release evidence still required

Before promotion, use one immutable source SHA and exact artifact digests for
all required gates. Required evidence includes the fast rootless
systemd/package gate, the broader mandatory CI, exact-source physical lifecycle
and capacity qualification, install/upgrade/uninstall verification,
daemon-reload generation of all three hibernation guards, real monitor
state-change evidence, controlled native stop-failure diagnostics, actual
initramfs/UKI resume inspection, and the owner-triggered cold-boot
arm/reboot/observe result. No rootless fixture may manufacture a physical or
cold-boot PASS.
