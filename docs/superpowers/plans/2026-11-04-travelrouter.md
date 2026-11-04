# TravelRouter Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Publish an English public Alpine diskless travel router project, build a downloadable CM5 image, and install it for hardware testing.

**Architecture:** Assemble Alpine's checksum-pinned Raspberry Pi aarch64 boot bundle with a root-owned APK overlay and a complete signed offline package repository. OpenRC brings up a dedicated AP before enabling the authenticated local panel and upstream controller.

**Tech Stack:** Alpine 3.24.3, OpenRC, Python standard library, hostapd, NetworkManager, dnsmasq, Unbound, nftables, GitHub Actions.

**Spec:** `docs/design.md` (the user request overrides the earlier draft's random initial password and no-default-password requirement).

## Global Constraints

- English code, UI, documentation, commit messages, and GitHub metadata.
- Public repository and release image, with broad upstream Linux firmware support.
- Stock initial AP and administrator credentials must be replaced in the captive portal before upstream forwarding is permitted.
- All packages needed for the AP and local panel are installed offline on every diskless boot.
- Private settings and WLAN keys never enter GitHub or public build artifacts.
- Authentication, anti-CSRF, input validation, WAN isolation, and configuration persistence are required.
- Physical CM5 boot and actual adapter support are distinct from successful CI.

## Review Focus

- A WAN association without Internet must not incorrectly dismiss the local setup portal.
- A hotel captive login must remain usable and must not be intercepted as the router's own setup.
- Power failure while saving must preserve the preceding valid configuration.
- Malicious SSIDs, HTTP origins, and malformed requests must not execute commands or bypass setup/authentication.
- Unknown or delayed USB adapters must not cause the protected AP to disappear.

## Task 1: Bootstrap and authentication

**Files:** `src/travelrouter/config.py`, `security.py`, `tests/test_security.py`, `docs/design.md`.
**Interfaces:** `ConfigStore(path).load/save`, `PasswordStore.verify/change`, `SessionStore.create/get/revoke`, `validate_setup`.

- [ ] Write and run tests for password rotation, mandatory setup, credential lengths, malformed inputs, and private atomic writes.
- [ ] Implement durable JSON configuration and scrypt password hashing with unique salts and constant-time comparison.
- [ ] Test expired sessions, invalid credentials, and setup persistence. Commit.

## Task 2: Router policy and hardware integration

**Files:** `src/travelrouter/policy.py`, `network.py`, `system.py`, `rootfs/etc/init.d/*`, `tests/test_policy.py`.
**Interfaces:** `render_firewall(config, state, wan) -> str`, `render_dns(config, state, resolvers) -> str`, `Network.scan/connect/saved`, `System.commit/apply`.

- [ ] Write and run tests for offline/captive/online transitions, forwarding blocked before setup, unsafe interfaces, DNS rebinding defenses, and SSIDs with separators.
- [ ] Implement hostapd AP, automatic radio roles, safe NetworkManager keyfiles, upstream probes, DNS routing, firewall, and boot-media overlay persistence.
- [ ] Run unit tests and real Alpine config parsers in CI. Commit.

## Task 3: Captive portal and operations panel

**Files:** `src/travelrouter/web.py`, `__main__.py`, `static/*`, `tests/test_web.py`.
**Interfaces:** local HTTP session API, forced setup endpoint, authenticated Wi-Fi operations and settings endpoints.

- [ ] Test the real HTTP server for unauthorized operations, hostile Host/Origin headers, CSRF, oversized requests, forced setup, and network state transitions.
- [ ] Implement the English UI with safe DOM text rendering, session authentication, rate limiting, and setup that rotates both AP and administrator passwords.
- [ ] Run all tests and browser smoke check. Commit.

## Task 4: Offline image build and security workflows

**Files:** `image/build.sh`, `image/packages.txt`, `image/overlay.py`, `.github/workflows/*`, `.github/dependabot.yml`, `SECURITY.md`, `README.md`, `LICENSE`.
**Interfaces:** Build outputs `travelrouter-cm5-aarch64.img.gz`, `SHA256SUMS`, package manifest, CycloneDX SBOM, and build metadata.

- [ ] Assemble a FAT32 disk image using mtools without mounting the host's devices. Embed signed upstream indexes and recursively fetched packages.
- [ ] Check every overlay package can be installed from the image repository with networking disabled. Check hostapd, Unbound, dnsmasq and nftables configurations.
- [ ] Configure lint, unit/integration tests, CodeQL, dependency review, secret scanning, vulnerability scanning, pinned actions, Dependabot, release provenance, and public release publishing.
- [ ] Create the public repository, push the implementation, fix any failed builds/security checks, and publish the first experimental release.

## Task 5: Review and physical installation

**Files:** `docs/hardware-test.md`, `docs/operations.md`.

- [ ] Fresh whole-project review and fix material issues with regression tests.
- [ ] Download and verify the released image and validate the exact external CM5 disk.
- [ ] Write and verify the image; user handles any OS authorization prompt and boot-mode/power changes.
- [ ] Hardware acceptance: protected AP, DHCP, setup gate, saved upstream, DNS, WAN firewall, and reboot persistence. Report actual outcomes and any unresolved hardware limits.
