# Security policy

Report vulnerabilities using [GitHub private vulnerability reporting](https://github.com/ralphschuler/travelrouter/security/advisories/new).
Do not put passwords, exported backups, WireGuard private keys, proxy credentials,
personal DNS histories, or full public-network captures in an issue.

Releases are experimental. Only the current release is maintained.
Image and CI qualification do not imply a completed physical hardware or provider
test. Review the open hardware acceptance checklist before using it during travel.

## Security boundaries

- WAN input and forwarding default to drop. Management listens on the AP address.
- Factory credentials are public; setup must replace them before routing.
- WPA2/CCMP protects the radio link; the HTTP captive assistant/admin panel assumes
  your private LAN devices are trusted. A compromised LAN device or someone with
  the AP passphrase is inside that boundary. Do not reuse sensitive passwords.
- Sessions, CSRF tokens, Host/Origin checks, bounded requests and login limiting
  protect panel actions. All actions still run through a privileged local controller;
  a controller vulnerability can compromise the router.
- Tunnel modes restrict forwarded client traffic to the tunnel and block Unbound
  from using a physical-WAN DNS fallback, including during configuration changes.
- Router bootstrap DNS for VPN/proxy endpoint discovery, connectivity probes,
  signed update checks and list downloads are system traffic. They can disclose
  endpoint names or source IP to the corresponding services. Protected mode does
  not promise to conceal every router-originated connection.
- IPv6 forwarding is disabled. Application DoH cannot be comprehensively blocked
  without also blocking ordinary HTTPS or inspecting encrypted traffic.
- Country IP data is allocation-based and imperfect. Shared CDNs can be affected.
- Saved upstream/tunnel secrets are root-only, but the boot overlay is not encrypted.
  Physical possession of the boot medium can expose them. Exported full backups
  are encrypted and authenticated with a user-supplied password.
- No remote SSH service or UPnP port mapping is enabled.
- Generic installer ISOs use stock Alpine's local root console. It is separate
  from the installed router's locked root account and is intended for local disk
  installation. The installer requires explicit disk selection and confirmation;
  it does not run the operations panel or persist router configuration to the ISO.

## Updates

Application files must verify against the embedded Ed25519 release public key.
An older/equal version cannot replace the running or already staged version.
The signing private key is a repository secret available only to the tag release
job; forks must generate their own release key and replace the embedded public key.

Alpine updates stay on the pinned stable branch and require official package/index
signatures. They are staged for reboot; the running RAM root is not hot-upgraded.
Kernel, initramfs and boot-firmware changes use a complete verified release image.
The updater retains the previous package repository and configuration generation.
FAT32 and abrupt power loss are still a recovery risk; keep an external backup.

GitHub Actions runs CodeQL (Python, JavaScript, workflow code), Bandit, Ruff,
unit/HTTP tests, ShellCheck, secret scanning, dependency review/audit, and a
HIGH/CRITICAL image package scan. These tools reduce risk; none proves absence
of vulnerabilities.
