# CM5 hardware qualification

Status: **qualification incomplete**. The v0.1.0 image was written to a CM5
Rev 1.0 with 64 GB eMMC on 2026-11-04 and passed the imaging tool's read-back
verification. A physical client can join its hotspot and receives a
`10.42.0.x` lease, but Safari cannot reach `http://10.42.0.1/`. That failure is
under investigation; the image is not yet qualified for travel use.

- [ ] Record CM5 RAM/eMMC variant, carrier board, `lsusb`, both Wi-Fi drivers.
- [x] Boot without Ethernet or upstream and observe the TravelRouter hotspot.
- [x] Join the hotspot and obtain a `10.42.0.x` DHCP lease.
- [ ] Open the operations panel/captive portal and verify the first-setup gate.
- [ ] Replace both credentials; rejoin AP and log in.
- [ ] Scan/join/save upstream; verify Internet checks, DHCP and DNS.
- [ ] Reboot; confirm saved upstream and administrator/AP settings survive.
- [ ] Test a real public captive login and offline portal transitions.
- [ ] Verify unsolicited WAN access and client-to-client access are blocked.
- [ ] Validate DNSSEC failure handling, DoT, recursive cache and filtering.
- [ ] Test domain allowlists, country/TLD blocks, refresh failure preservation.
- [ ] Configure real WireGuard/proxy credentials; test route, DNS and kill-switch.
- [ ] Verify encrypted backup/restore and malformed backup rejection.
- [ ] Stage package/app update and reboot; verify rollback/recovery.
- [ ] Review dashboard counters and confirm logs contain no credentials/history.

CI includes offline package/configuration checks and an
[image boot and client test](image-testing.md). Emulation cannot prove the
physical/network-specific outcomes in this checklist.
