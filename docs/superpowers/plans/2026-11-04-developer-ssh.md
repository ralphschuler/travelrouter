# Developer SSH mode

- Default off. Only the authenticated, CSRF-protected panel can change it after setup.
- Accept exactly one Ed25519 public key; never accept or handle a private key.
- Bind the daemon to 10.42.0.1 and allow port 22 only from the hotspot interface and subnet; explicitly drop it before established-connection acceptance when disabled.
- Disable password, keyboard-interactive, agent, X11 and TCP forwarding. Disclose that the key grants root access. Generate unique host keys on the router, persist them privately and show their fingerprint.
- Preserve a password-locked local account while enabling key authentication without introducing a usable console password. Do not enable an SSH listener by default.
- Exercise real accepted/rejected SSH connections, WAN isolation, disabling an existing connection, persistence across restart, credential changes and update rollback before publishing.
