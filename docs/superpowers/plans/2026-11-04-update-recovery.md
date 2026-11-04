# Update recovery and CM5 USB host

## Goal

Keep a known-good local management path when a staged application or Alpine
package update fails. Enable the CM5 USB 2.0 host used by CM4-compatible carrier
boards. Test the real images, not only mocked update operations.

## Constraints

- Keep boot media, user settings and the previous signed package repository as
  recoverable generations; no update may overwrite its only rollback copy.
- Persist transaction state before destructive renames. Recovery must handle
  interruption at each rename as well as a failed trial boot.
- Select recovery before Alpine extracts the APK overlay or loads packages, and
  use a watchdog and independent readiness check to cover a failed service boot.
- Confirm a trial only after the original local hotspot, DHCP, DNS and HTTP
  management services remain available. Never use Internet availability as a
  health condition for a travel router.
- Fail closed when recovery prerequisites are unavailable; do not claim that a
  destroyed bootloader, broken hardware or lost power supply can be recovered.
- Do not put test keys, failure hooks or simulated devices in release images.
- Existing v0.2.0 images do not have the early recovery component. Installing it
  requires a separately verified image migration; an ordinary app update cannot
  retrofit the initramfs guarantee.

## Verification

- [ ] Exercise signed and tampered app updates, package staging, persistence
  errors and interruption at every publication step.
- [ ] Test preboot recovery, watchdog behavior and a successful trial on real
  QEMU boots, including a deliberately broken candidate and cold reboot.
- [ ] Validate CM5 USB host configuration and retain Pi 4 emulator coverage.
- [ ] Run the native AMD64 and ARM64 installer/boot matrix and security checks.
- [ ] Verify the recovery image and its hardware migration before changing the
  user's configured CM5.
