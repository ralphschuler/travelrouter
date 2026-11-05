# Image boot and client tests

The image job boots the compressed disk image produced by the build. Successful
configuration parsing alone cannot establish that the hotspot, resolver and
operations panel start together. The boot test exercises their real service
integration and blocks artifact/release publication when it fails.

## What runs

The test extracts the kernel, initramfs and Pi 4 device tree from the finished
image and starts QEMU's `raspi4b` machine. Its writable qcow2 layer leaves the
base image unchanged. Alpine restores the image's `apkovl` and installs its
embedded APK packages through the normal diskless initramfs path.

The extracted test device tree declares the emulator's upper 1 GiB RAM bank:
QEMU 11.0.3 otherwise advertises only its lower 960 MiB to Linux despite allocating
2 GiB. The reserved VideoCore region stays excluded. Original/test device-tree
hashes and this fixup are recorded in `result.json`; the release image, kernel
and initramfs are unchanged.
The copied device tree also disables the absent Bluetooth device on the emulated
serial controller, exposing its terminal device for the test harness.

A CI-only initial shell loads `mac80211_hwsim` and creates three simulated radios:
two for the router and one in a separate client network namespace. It runs the
shipped OpenRC sysinit, boot and default runlevels. Production service files,
application code and package contents are not replaced with mocks.

When the CM5 build includes the experimental RTL8191SU module, the guest also
loads its declared dependencies from Alpine's read-only `modloop`, inserts the
module from the writable application overlay, and checks its kernel version,
USB ID and firmware name.
QEMU has no RTL8191SU radio, so this proves module loading only; RF scanning and
upstream association still require the physical CM5 and adapter.

The client checks:

- WPA2 association with the actual hostapd process.
- A DHCP lease with the expected gateway, DNS address and subnet.
- Local/captive DNS responses, including redirected external DNS traffic.
- HTTP page, JavaScript, stylesheet and font responses through the firewall.
- Captive redirects, Host/Origin restrictions and authenticated API access.
- Mandatory first setup, CSRF rejection and credential rotation.
- Configuration persistence across a cold VM restart, followed by a second
  association, DHCP exchange, login, metrics request and logs request.
- Denial of management access from synthetic untrusted ingress and forwarding
  while the router is offline.

Firewall denial checks first require successful HTTP over the same network path
with narrowly scoped temporary test allowances. After removing those allowances,
fresh connections must hit passive counters immediately before the shipped drop
policy. A timeout caused by a broken route cannot pass this check. The temporary
rules exist only in the disposable VM and are cleaned up after each measurement.

## Generic UEFI targets

The AMD64 and ARM64 jobs boot their installer ISO through QEMU's corresponding
UEFI firmware and GRUB. A disposable ISO copy changes only the external GRUB
configuration to select a serial console and the test's initial shell. The
installer script, embedded runtime image, bootloader code and Alpine packages
remain the shipped versions.

The test runs the actual installer against an empty file-backed virtual disk,
provides its explicit disk/erase confirmations, and requires its complete
read-back verification. After stopping that VM, the host independently hashes
the whole written image region and compares it with the built runtime image.

That installed disk then boots through UEFI and GRUB for both runtime test
phases. Only its copied external GRUB configuration receives the test console
and initial-shell arguments. The same simulated-radio, OpenRC, DHCP, DNS,
HTTP, firewall and cold-reboot checks run against each architecture. Original
ISO/image hashes, test-copy hashes and firmware hashes appear in the diagnostics.
The released images contain no VM-specific serial argument or test account.

## Boundaries

This is a **Pi 4-compatible image boot and service integration test**. QEMU does
not currently provide a CM5/BCM2712 machine. It does not validate the physical
CM5 firmware, RP1, carrier board, radio firmware, USB adapter or RF behavior.
The test's initial shell also replaces the usual PID 1 entry point so it can
inject simulated hardware; normal init process signal/reaping behavior is not
qualified by that instrumentation.

HTTP client checks do not execute browser JavaScript. Browser layout and
interaction checks are separate from the image test. Public captive networks,
external VPN/proxy providers and real tunnel-failure packet tests remain in
the [hardware qualification checklist](hardware-test.md).

## Running and diagnosing

The normal quality/image workflow runs this test after each new image build,
before uploading the release image. Publication is restricted to tag pushes;
all release gates, including the image boot test, must succeed.

An additional release gate runs the extended `--recovery` scenario against the
built CM5 image. It exercises panel-controlled SSH from trusted and untrusted
simulated networks, stages an ephemeral-key-signed update, cold-boots it, and
stages a deliberately broken update to test automatic rollback. The test key and
broken application exist only on the disposable VM disk. Its QEMU build pins
upstream commit `21fcfb6046082a06b82c17688634a1b769ee63a0`: QEMU 11.0 and
11.1 treat arming the BCM2835 watchdog as an immediate reset and cannot test
this behavior. See the [upstream watchdog fix](https://qemu.googlesource.com/qemu/+/21fcfb6046082a06b82c17688634a1b769ee63a0).
The VM uses a Pi 4 model, not actual CM5 hardware; a separate CM5 hardware test
is still necessary.

For a reported problem with an existing release, manually run the workflow on
a branch and set `image_release` to a semantic tag such as `v0.1.0`. That mode
downloads the published image and verifies its checksum instead of rebuilding
it. It never publishes a release and is rejected on tag refs.

Inside the pinned aarch64 Alpine build container:

```sh
sh image/e2e/run.sh dist/travelrouter-cm5-aarch64.img.gz
```

This requires no host block device, privileged container, KVM or physical Wi-Fi
adapter. QEMU uses software emulation. The harness uses a fresh scratch directory
under `build/e2e-vm`; guest writes are disposable.

GitHub uploads `image-boot-diagnostics` even after a test failure. The compact
results under `build/e2e-results` contain image hashes, the failed stage, serial
boot logs, OpenRC status, interfaces/routes, listeners, firewall rules and service
logs when the guest is responsive. A host preparation or early boot failure may
only have the result summary and console output. Missing readiness, an assertion
failure or a timeout exits nonzero; it is never counted as a pass.

References: [QEMU Raspberry Pi models](https://www.qemu.org/docs/master/system/arm/raspi.html)
and [Linux mac80211_hwsim](https://www.kernel.org/doc/html/latest/networking/mac80211_hwsim/mac80211_hwsim.html).
