# CM5 hardware qualification

Status: **pending physical test**. The operator temporarily disconnected the CM5
to charge the laptop. No custom TravelRouter image has been written to it yet.

- [ ] Record CM5 RAM/eMMC variant, carrier board, `lsusb`, both Wi-Fi drivers.
- [ ] Boot without Ethernet or upstream and observe `TravelRouter-XXXX`.
- [ ] Obtain a DHCP lease, open captive portal, verify first-setup gate.
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

CI provides offline package and configuration checks. It cannot prove these
physical/network-specific outcomes.
