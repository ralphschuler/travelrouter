# CM5 hardware qualification

Status: **qualification incomplete**. A local test image was written to a CM5
with 64 GB eMMC and verified by full readback. A physical client joined the
hotspot, completed initial credential rotation and reached the dashboard.
The attached USB adapter was not detected, so Internet routing and the new
recovery-enabled image still require physical verification.

The tested Realtek RTL8191SU adapter (`0bda:8172`) is not supported by the
shipped Linux 6.18 kernel: its former `r8712u` driver was removed upstream.
The presence of `rtl8712u.bin` firmware alone does not provide a driver. See
the [upstream removal](https://lkml.rescloud.iu.edu/hypermail/linux/kernel/2410.2/06082.html).
See the [Wi-Fi support policy](wifi-support.md) for the maintained module set
and this adapter's compatibility boundary.

- [ ] Record CM5 RAM/eMMC variant, carrier board, `lsusb`, both Wi-Fi drivers.
- [x] Boot without Ethernet or upstream and observe the TravelRouter hotspot.
- [x] Join the hotspot and obtain a `10.42.0.x` DHCP lease.
- [x] Open the operations panel/captive portal and verify the first-setup gate.
- [x] Replace both credentials; rejoin AP and log in.
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
