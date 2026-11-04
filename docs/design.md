# TravelRouter design

TravelRouter is a public, English-only Alpine Linux appliance for CM5 and generic
AMD64/ARM64 UEFI travel routers. A diskless APK overlay and a local signed package
repository make first boot independent of Ethernet or Internet access. The
dedicated CM5 target uses the official Raspberry Pi boot bundle. Generic targets
use the matching standard Alpine kernel/module bundle and a GRUB UEFI loader.
See [platforms and installation media](build-targets.md) for firmware boundaries
and the separate offline installer ISO.

## Boot and setup

The initial SSID is `TravelRouter-XXXX`, with Wi-Fi passphrase
`TravelRouter-Setup!`. The administrator is `admin` and the initial password is
`ChangeMe-TravelRouter!`. All public images share these documented credentials.
The first portal requires replacing both passwords before upstream forwarding
or other configuration changes. Initial setup should take place in a trusted
location. There is no root password login, and SSH is disabled.

The admin password is stored as a salted scrypt hash; upstream Wi-Fi secrets
are root-only NetworkManager keyfiles. The boot medium/overlay is not encrypted.
Physical access can expose saved network credentials.

Two Wi-Fi adapters are the supported routing configuration. The integrated
radio hosts the AP when identifiable, and a second radio joins upstream Wi-Fi.
All available Alpine Linux firmware is bundled. Kernel modules and driver
support remain bounded by the selected Alpine kernel; unsupported vendor
drivers are reported rather than silently installed. A single radio always
offers setup but requires another adapter for upstream Wi-Fi in this version.

## Networking and isolation

The AP uses `10.42.0.1/24`, hostapd WPA2-PSK/CCMP and client isolation.
NetworkManager manages upstream interfaces, and cannot manage the AP.
dnsmasq provides DHCP and client DNS. Unbound listens on loopback port 5335
and forwards over authenticated DNS-over-TLS. The monitor maintains these
states with debouncing:

- Offline: Internet is not verified and no upstream captive response is found.
  Client DNS and plaintext HTTP lead to the local portal.
- Captive: the upstream HTTP probe returns a login redirect or unexpected page.
  Local interception stops; bounded upstream DNS fallback and client forwarding
  permit the public network's login. A local panel banner explains this state.
- Online: an exact HTTP connectivity response and validated HTTPS succeed.
  Unbound handles client DNS and the local portal does not intercept requests.

An explicit external connectivity endpoint is contacted periodically and sees
the router's public IP. DNS-over-TLS failure fails closed in online mode; it
does not silently fall back to plaintext DNS. IPv6 routing is disabled for v1
to prevent bypassing the IPv4 policy.

The nftables input and forwarding policies drop by default. DHCP/DNS/panel
traffic is accepted only on the AP; WAN DHCP replies and established flows
are accepted. NAT and forwarding target only the selected upstream interface.
Forwarding stays off until setup is complete. Client TCP/UDP DNS is redirected
to the router; arbitrary application DoH is outside this DNS enforcement.
The router is not an anonymity service, VPN, or HTTPS inspection proxy.

## Panel

The panel at `http://10.42.0.1/` or `http://router.home.arpa/` uses sessions,
HttpOnly/SameSite cookies, CSRF tokens, origin and Host validation, bounded
request sizes, rate limits, and escaped DOM text. Every mutation requires an
authenticated session. It is served only over the private encrypted AP and
uses HTTP so captive assistants can open it without certificate warnings.
Credentials are not protected from a compromised local client; do not reuse
passwords from other services. The panel has no Internet-facing listener.

Available operations are status, scan/join/saved-network selection, forgetting
an upstream, priority changes, AP settings, administrator password changes,
and a redacted configuration export. Runtime work is serialized and commands
use fixed executable paths and argument arrays without a shell.

## Persistence and supply chain

Persistent changes create a new APK overlay on the boot medium, fsync it, then
atomically replace the preceding overlay. The preceding generation is retained
with a non-apkovl extension for recovery. Code and web assets are embedded in
the overlay and retained when it is regenerated. No settings or secrets from
the operator's machine enter release builds.

The build pins the Alpine boot bundle checksum, verifies package signatures,
records exact package versions and hashes, and proves offline APK installation.
Repository/package updates can change artifacts: the build is repeatable and
auditable, not claimed bit-for-bit reproducible against moving Alpine indexes.
CI runs lint, tests, real service configuration validation, CodeQL, secret and
dependency checks. Release images include SHA-256 checksums, a package SBOM,
build metadata and GitHub artifact attestation. CM5 boot remains a required
hardware qualification separate from CI.
