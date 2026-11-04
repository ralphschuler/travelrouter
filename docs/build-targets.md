# Platforms and installation media

TravelRouter builds a dedicated CM5 image and two generic UEFI targets. The
application, security policy and mandatory first setup are shared. Boot firmware,
kernel/module bundles, package architecture and installation media are specific
to each target.

| Target | CPU architecture | Runtime boot | Download formats |
|---|---|---|---|
| `cm5` | ARM64 / `aarch64` | Raspberry Pi CM5 firmware | `travelrouter-cm5-aarch64.img.gz` |
| `generic-x86_64` | AMD64 / `x86_64` (Intel and AMD) | 64-bit UEFI | `.img.gz` and installer `.iso` |
| `generic-aarch64` | ARM64 / `aarch64` | ARM64 UEFI | `.img.gz` and installer `.iso` |

Generic ARM64 is **not a universal single-board-computer image**. Boards that
need a vendor bootloader, a board-specific device tree or Raspberry Pi firmware
need their own target. Use the CM5 image for the CM5. Generic runtime images
require Secure Boot to be disabled. Legacy BIOS runtime boot is not included;
the x86 installer ISO preserves Alpine's BIOS boot entry, but installs a UEFI
runtime.

## Hardware requirements

- A matching 64-bit CPU and boot firmware.
- At least 2 GiB RAM and an 8 GB or larger installation disk. Consult the exact
  image size in its build metadata for capacity checks.
- A Linux-supported Wi-Fi radio capable of AP mode for the local hotspot.
- A separate supported Wi-Fi radio for upstream Wi-Fi. An existing Ethernet
  upstream route can also be used by the connectivity controller.

Firmware packages are included broadly, but that does not guarantee a driver or
AP mode for every USB adapter. A VM needs suitable Wi-Fi hardware passthrough for
normal router use. CI provides simulated radios only inside its disposable test
environment; production images do not contain those test fixtures.

## Choose an installation method

Use the matching `.img.gz` when writing removable media with Raspberry Pi Imager
or another imaging tool. It contains a writable FAT boot volume, kernel, module
bundle, signed offline APK repositories and the router overlay. On first boot,
join the hotspot and replace the administrator and Wi-Fi credentials.

Use `travelrouter-installer-x86_64.iso` or
`travelrouter-installer-aarch64.iso` to boot a local console and install onto a
separate disk. The ISO is an **installer**, not a persistent live router. An
ISO9660 filesystem cannot store the mandatory password change and later settings.

1. Verify the release `SHA256SUMS` before booting the selected media.
2. Boot the ISO on the matching architecture. The stock Alpine installer console
   uses the local `root` login without a password. This is separate from the
   installed router, whose root login is locked and SSH is disabled.
3. Run `sh /media/cdrom/travelrouter/install.sh`, adjusting the mount path if
   necessary. All required installer tools and the image are included offline.
4. Select the exact whole-disk path from the displayed device list. The installer
   shows model, identity and capacity and requires typing `ERASE /dev/DEVICE`.
   Installation replaces the selected disk's partition table and image region;
   back up that disk first.
5. Wait for complete SHA256 read-back verification. Shut down, remove the ISO,
   and boot the installed disk in UEFI mode.

The installer rejects mounted disks and their underlying devices, active swap,
the running system and installation media, read-only targets, partitions and
insufficient capacity. It rechecks identity before writing. An interrupted or
unverified target must be reinstalled before use.

## Build and verify

Generic targets use checksum-pinned official Alpine standard ISOs, retaining the
matching kernel, initramfs and signed module bundle. The installer ISO preserves
the original El Torito boot structures; the writable runtime uses its own GRUB
UEFI executable and external configuration. Target inputs are recorded in
`image/targets/manifest.json`.

Run in the matching architecture's pinned Alpine container:

```sh
sh image/build-generic.sh generic-x86_64
sh image/build-generic.sh generic-aarch64
```

Each command is for its matching native architecture, not both in one container.
Outputs go to `dist/<target>/`; use fresh target build/output directories. The
existing CM5 command remains `sh image/build.sh` in an aarch64 container.

The CI matrix builds each architecture on a matching GitHub runner, validates
offline package installation, runs parsers and boot tests, scans installed
packages and preserves diagnostics. Releases require the CM5 and both generic
jobs to pass. Each target includes its own SBOM, package inventory, boot/input
hashes and checksums. The signed Python/web application update is shared, while
Alpine package staging uses the installed system's APK architecture.

See [image boot tests](image-testing.md) for instrumentation and test boundaries,
and [hardware qualification](hardware-test.md) for remaining physical checks.
