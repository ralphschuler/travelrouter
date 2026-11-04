# Verification record

## Software

- Unit/HTTP tests cover mandatory setup, credential hashing/rotation, sessions,
  CSRF/Host/Origin validation, unsafe inputs, DNS modes, firewall policy, filtering,
  encrypted backups, signed updates and archive traversal/version rejection.
- A fresh independent whole-project review identified and led to fixes for DNS
  protection during tunnel transitions, FAT32 package staging, and imported schema
  validation. Additional fixes enforce staged update versions and refresh missing
  imported country data promptly.
- CI proves installation from the embedded signed repositories with networking
  disabled, checks all enabled OpenRC service files, and invokes actual Unbound,
  dnsmasq, nftables, sing-box and hostapd parsers. Hostapd reaches driver setup;
  no radio is emulated on the hosted runner.
- CodeQL scans Python, JavaScript and workflows. Secret scanning, dependency
  audit, lint, tests and an image package vulnerability scan gate releases.
- The local disposable browser preview verified forced setup, authenticated
  dashboard rendering, navigation, local fonts, safe untrusted SSID text, live
  metrics and logs. The 390 px mobile view was visually inspected; layout width
  checks were performed at 320 px. Desktop was inspected at 1280 px.

## Remaining physical qualification

The operator disconnected the CM5 to charge the laptop before the custom image
was ready. Installation and physical boot are pending. Live DHCP, adapter support,
public captive login, DNS behavior, VPN/proxy routes, kill-switch packet tests,
package updates and reboot persistence must be verified on the hardware.

The public image is an experimental release, not a completed travel deployment.
See hardware-test.md for the acceptance checklist.
