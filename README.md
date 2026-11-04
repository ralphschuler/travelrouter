# TravelRouter

[Project website](https://nyphon.de/travelrouter/) · [Documentation](https://nyphon.de/travelrouter/getting-started.html) · [Releases](https://github.com/ralphschuler/travelrouter/releases)

An offline-first, privacy-focused Alpine Linux travel router for Raspberry Pi
Compute Module 5 and generic AMD64/ARM64 UEFI systems. Boot it without Ethernet, join its protected hotspot, replace
the factory credentials, and choose an upstream Wi-Fi network in the local panel.

**Experimental software. Physical CM5 qualification is tracked in
[the hardware checklist](docs/hardware-test.md).** A successful image build is
not a substitute for testing a specific carrier board, Wi-Fi adapter, VPN provider,
or public captive network.

## Download and first boot

Choose the [build target and installation method](docs/build-targets.md) for your
hardware. Generic UEFI targets provide a directly flashable disk image and a
separate installer ISO. They require an AP-capable Wi-Fi radio. The CM5 steps
below use its dedicated board image.

Download the image and `SHA256SUMS` from [GitHub Releases](https://github.com/ralphschuler/travelrouter/releases).
The release includes a compressed `.img.gz`, package inventory, CycloneDX SBOM,
build metadata, an application update file, and GitHub build provenance.

1. Verify `sha256sum -c SHA256SUMS` in the download directory.
2. Select the `.img.gz` with **Use custom** in Raspberry Pi Imager. Use an 8 GB
   or larger device; the current build metadata/image size is authoritative.
   Flashing replaces the selected device. Back it up first.
3. Boot the CM5 with its integrated radio and a second supported Wi-Fi adapter.
4. Join `TravelRouter-XXXX` using the initial Wi-Fi passphrase `TravelRouter-Setup!`.
5. Open `http://10.42.0.1/` (or `http://router.home.arpa/`). Sign in as `admin`
   with `ChangeMe-TravelRouter!`.
6. The setup portal requires **different replacement administrator and Wi-Fi
   passwords** before routing is enabled. Rejoin with the new Wi-Fi credentials.
7. Scan for an upstream, join it, and optionally configure your VPN or proxy.

All public images share the factory credentials. Perform first setup in a trusted
location. The image contains no personal Wi-Fi passwords, private VPN keys, or
developer SSH keys. There is no password-based root login or SSH service.

## Features

| Area | Included |
|---|---|
| Networking | Two-radio automatic selection, saved upstream Wi-Fi, DHCP, IPv4 NAT, captive-network sign-in passthrough |
| Local access | WPA2/CCMP hotspot, client isolation, forced credential rotation, authenticated operations panel |
| DNS | Unbound cache and DNSSEC, authenticated DNS-over-TLS or full recursive resolution |
| Privacy routes | WireGuard full tunnel; HTTPS CONNECT or SOCKS5 through a TUN interface; client and Unbound kill-switch |
| Filtering | HaGeZi Light/TIF Mini, custom block/allow lists, domain-ending blocks, destination-country IPv4 ranges |
| Dashboard | Traffic counters/rates, CPU load, RAM, temperature, DHCP clients, DNS cache metrics and local service logs |
| Backups | Redacted export and password-encrypted full settings backup/restore (scrypt + AES-256-GCM) |
| Updates | Ed25519-signed application updates; optional daily Alpine stable package staging, activated on reboot |
| Supply chain | Pinned base-image hash/container/actions, offline package validation, CodeQL, secret/dependency/image scans, SBOM and provenance |

Use direct mode to complete a hotel's login, then explicitly re-enable your
protected route. Protected modes do not silently fall back to direct client
traffic. HTTPS CONNECT proxies support TCP; unsupported UDP fails closed.
SOCKS5 itself does not encrypt traffic and requires explicit acknowledgement.

Recursive DNS avoids a central recursive provider, but its authoritative DNS
traffic is normally unencrypted. DNS-over-TLS is the default. Neither DNS mode,
country filtering, nor a VPN guarantees anonymity or prevents every malicious
site. Applications using their own DoH can bypass domain filtering.

## Build and contribute

The build runs on a native aarch64 GitHub runner in a pinned Alpine container:

```sh
docker run --rm --cap-add NET_ADMIN -v "$PWD:/source" -w /source \
  alpine:3.24.3@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a \
  sh image/build.sh
```

Use a fresh checkout for each build. No host block devices are mounted or written.
The builder verifies the official RPi boot bundle, fetches the signed package
closure, proves offline installation, runs real service parsers, and creates a
FAT32 disk image with space for package updates and configuration overlays.
Alpine repositories move within the stable branch; metadata records exact package
versions/hashes. Builds are repeatable, not claimed bit-identical across changing
repository indexes.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check src tests image
.venv/bin/bandit -q -r src image -c pyproject.toml
```

See [operations and recovery](docs/operations.md), [security policy](SECURITY.md),
[design](docs/design.md), [build targets](docs/build-targets.md), [image boot tests](docs/image-testing.md), and
[third-party notices](THIRD_PARTY_NOTICES.md).

## License

TravelRouter's own code is MIT licensed. The system image aggregates separately
licensed Alpine packages, firmware and third-party programs. Their licenses,
source references and notices remain applicable; see THIRD_PARTY_NOTICES.md.
