#!/bin/sh
set -eu
# Run only inside the disposable CI container; never against a host system.
if [ ! -f /.dockerenv ] || [ "${TRAVELROUTER_TEST_CONTAINER:-}" != yes ]; then
    echo 'This test requires its disposable Docker container.' >&2
    exit 1
fi
mkdir -p /run/openrc /var/empty
printf '%s\n' default > /run/openrc/softlevel
cp /source/rootfs/etc/init.d/travelrouter-ssh /etc/init.d/travelrouter-ssh
chmod 755 /etc/init.d/travelrouter-ssh
sed -i 's/^root:[^:]*:/root:!:/' /etc/shadow
ssh-keygen -q -t ed25519 -N '' -f /tmp/allowed
ssh-keygen -q -t ed25519 -N '' -f /tmp/rejected
PYTHONPATH=/source/src python3 -c "from pathlib import Path; from travelrouter.developer import configure_files; configure_files(Path('/etc'), True, Path('/tmp/allowed.pub').read_text().strip())"
expected=$(ssh-keygen -lf /etc/travelrouter/ssh_host_ed25519_key | awk '{print $2}')
actual=$(PYTHONPATH=/source/src python3 -c "from pathlib import Path; from travelrouter.developer import host_fingerprint; print(host_fingerprint(Path('/etc/travelrouter/ssh_host_ed25519_key')))")
[ "$expected" = "$actual" ]
sed -i -e 's/^Port 22$/Port 2222/' -e 's/^ListenAddress 10.42.0.1$/ListenAddress 127.0.0.1/' /etc/travelrouter/sshd_config
/usr/sbin/sshd -t -f /etc/travelrouter/sshd_config
rc-service --nodeps travelrouter-ssh start
ssh -i /tmp/allowed -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@127.0.0.1 'id -u' > /tmp/id
[ "$(cat /tmp/id)" = 0 ]
if ssh -i /tmp/rejected -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@127.0.0.1 true; then exit 1; fi
if ssh -o PreferredAuthentications=password -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@127.0.0.1 true; then exit 1; fi
PYTHONPATH=/source/src python3 -c "from pathlib import Path; from travelrouter.developer import configure_files; configure_files(Path('/etc'), False, '')"
if ssh -i /tmp/allowed -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p 2222 root@127.0.0.1 true; then exit 1; fi
rc-service --nodeps travelrouter-ssh stop
python3 - <<'PY'
import socket
import time
deadline = time.monotonic() + 5
while time.monotonic() < deadline:
    with socket.socket() as client:
        if client.connect_ex(('127.0.0.1', 2222)) != 0:
            break
    time.sleep(0.1)
else:
    raise SystemExit('SSH is still listening after stop')
PY
printf '%s\n' 'Provisioned SSH accepts the configured key, rejects other keys and passwords, and rejects the key after disable.'
