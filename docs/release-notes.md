## Experimental CM5, AMD64 and ARM64 images

This pre-release includes early-boot recovery for signed updates, opt-in
key-only developer SSH, and Android/iPhone USB tethering controls. It is for
controlled testing. The recovery-enabled CM5 image still needs a physical
boot and hotspot qualification on the target carrier board; CI uses simulated
Wi-Fi radios. USB tethering also needs testing with real phones and cables.

Choose the target for your hardware:

- `travelrouter-cm5-aarch64.img.gz`: Raspberry Pi Compute Module 5.
- `travelrouter-generic-x86_64.img.gz`: Intel/AMD 64-bit UEFI systems.
- `travelrouter-generic-aarch64.img.gz`: ARM64 UEFI systems.
- `travelrouter-installer-x86_64.iso` and `travelrouter-installer-aarch64.iso`:
  offline installers for the corresponding generic UEFI runtime.

Generic ARM64 does not replace board-specific firmware. Generic runtimes require
Secure Boot to be disabled and do not support legacy BIOS boot. All targets need
an AP-capable supported Wi-Fi radio; a separate radio provides upstream Wi-Fi.

This release also corrects the service lifecycle behind the disappearing panel:
controller-managed DNS and access-point restarts preserve the controller instead
of stopping it through OpenRC's reverse dependencies. Startup explicitly prepares
loopback for local DNS. RAM-root capacity scales with installed memory, and all
targets include the OpenSSL executable needed for signed module verification.

Download the matching image and `SHA256SUMS`. Verify the checksum,
then select the compressed image in Raspberry Pi Imager using **Use custom**.
Writing an image erases the selected device. Keep a verified backup first.

For ISO installation, boot the stock Alpine local root console, run
`sh /media/cdrom/travelrouter/install.sh` (adjust the media mount path), and
confirm the selected disk. The installer verifies both the payload and full disk
readback. Remove the ISO after installation. The installed router's root login
remains locked and SSH is disabled.

Each target includes an inventory, SBOM, build metadata and checksums. Release
publication requires all platform boot tests and security checks. UEFI tests
exercise the installer on disposable disks; simulated radios exercise service
integration and cold-reboot persistence. Emulation does not qualify every
physical board, USB adapter, public captive network or VPN provider.

The initial hotspot is `TravelRouter-XXXX`, using `TravelRouter-Setup!`.
Open `http://10.42.0.1/`. Sign in with `ChangeMe-TravelRouter!`, then replace
both the administrator and Wi-Fi passwords. Setup is mandatory before routing.

See README.md and docs/operations.md for configuration, security boundaries,
recovery and the physical hardware acceptance checklist. CI validation does
not establish that an untested USB adapter works on the CM5 kernel.
