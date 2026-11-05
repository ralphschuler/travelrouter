#!/bin/sh
# This file exists only in the disposable VM's RAM root.
set -eu
case "${1:-}" in initial|restored) ;; *) echo 'Expected initial or restored phase' >&2; exit 2 ;; esac

# Preserve the cold-start condition. Production startup must establish loopback.
ip link set lo down
command -v openssl >/dev/null || { echo 'OpenSSL is required for modloop signature verification'; exit 1; }
if ! openrc sysinit > /root/ci-image-test/openrc-sysinit.log 2>&1; then
    cat /root/ci-image-test/openrc-sysinit.log
    exit 1
fi
cat /root/ci-image-test/openrc-sysinit.log
grep -q 'Verifying modloop' /root/ci-image-test/openrc-sysinit.log
if grep -qi 'verification disabled' /root/ci-image-test/openrc-sysinit.log; then
    echo 'Modloop signature verification was disabled'
    exit 1
fi
rc-service modloop status
rc-service travelrouter-recovery status
openrc boot
modprobe mac80211_hwsim radios=3
modprobe veth
ip netns add tr-client
iw phy phy2 set netns name tr-client
ip netns exec tr-client ip link set lo up

# A separate, synthetic untrusted ingress proves management is LAN-only.
ip netns add tr-untrusted
ip link add ci-wan type veth peer name ci-probe
ip link set ci-probe netns tr-untrusted
ip address add 198.18.0.1/24 dev ci-wan
ip link set ci-wan up
ip netns exec tr-untrusted ip address add 198.18.0.2/24 dev ci-probe
ip netns exec tr-untrusted ip link set ci-probe up
ip netns exec tr-untrusted ip link set lo up
ip netns exec tr-untrusted ip route add 10.42.0.0/24 via 198.18.0.1
ip netns exec tr-untrusted python3 -m http.server 8080 --bind 198.18.0.2 >/root/ci-image-test/untrusted.log 2>&1 &

# Run the shipped default runlevel and service dependency graph unchanged.
openrc default
driver_payload=/opt/travelrouter/modules/r92su.ko
if [ -s "$driver_payload" ]; then
    driver_module="/lib/modules/$(uname -r)/updates/r92su.ko"
    test -s "$driver_module"
    test -d /sys/module/r92su
    modinfo -F vermagic "$driver_module" | grep -F "$(uname -r) " >/dev/null
    modinfo -F alias "$driver_module" | grep -F 'usb:v0BDAp8172' >/dev/null
    test "$(modinfo -F firmware "$driver_module")" = rtlwifi/rtl8712u.bin
fi
python3 /root/ci-image-test/lifecycle.py capture
rc-service hostapd status
rc-service dnsmasq status
rc-service unbound status
rc-service travelrouter status
ip -4 address show dev lo | grep -q '127.0.0.1/8'
attempt=0
until ss -lnt | grep -q '10.42.0.1:80'; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 30 ] || { echo 'Panel did not begin listening'; exit 1; }
    sleep 1
done

cat > /root/ci-image-test/udhcpc.sh <<'EOF'
#!/bin/sh
set -eu
case "$1" in
    deconfig) ip address flush dev "$interface" ;;
    bound|renew)
        [ "$subnet" = 255.255.255.0 ]
        [ "$router" = 10.42.0.1 ]
        [ "$dns" = 10.42.0.1 ]
        ip address flush dev "$interface"
        ip address add "$ip/24" dev "$interface"
        ip route replace default via "$router" dev "$interface"
        printf '%s\n' "$ip" > /root/ci-image-test/client-address
        ;;
esac
EOF
chmod 700 /root/ci-image-test/udhcpc.sh

# Connect with independently expected credentials, never learn the current secret
# from the implementation under test. A lost Wi-Fi password must fail the reboot.
python3 - "$1" <<'PY'
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, '/root/ci-image-test')
from client import FACTORY_WIFI, NEW_WIFI
config = json.loads(Path('/etc/travelrouter/config.json').read_text())
ssid = (config['ssid'] if sys.argv[1] == 'initial' else 'TravelRouter-CI').encode()
expected_wifi = FACTORY_WIFI if sys.argv[1] == 'initial' else NEW_WIFI
if config['ap_password'] != expected_wifi:
    raise RuntimeError('Wi-Fi credential did not match the expected boot phase')
psk = hashlib.pbkdf2_hmac('sha1', expected_wifi.encode(), ssid, 4096, 32).hex()
path = Path('/root/ci-image-test/client-wpa.conf')
control = Path('/root/ci-image-test/wpa-control')
control.mkdir(mode=0o700)
Path('/root/ci-image-test/expected-ssid').write_text(ssid.decode())
path.write_text('ctrl_interface=' + str(control) + '\nnetwork={\nssid=' + ssid.hex() + '\npsk=' + psk + '\n}\n')
path.chmod(0o600)
PY
ip netns exec tr-client ip link set wlan2 up
timeout -k 5 15 ip netns exec tr-client wpa_supplicant -B -s -i wlan2 -c /root/ci-image-test/client-wpa.conf > /root/ci-image-test/client-wpa.log 2>&1
timeout -k 5 55 ip netns exec tr-client python3 /root/ci-image-test/wifi.py
if ! timeout -k 5 40 ip netns exec tr-client udhcpc -i wlan2 -q -n -t 12 -T 2 -s /root/ci-image-test/udhcpc.sh > /root/ci-image-test/client-dhcp.log 2>&1; then
    cat /root/ci-image-test/client-dhcp.log
    echo 'Client DHCP failed or exceeded its bounded timeout'
    exit 1
fi
cat /root/ci-image-test/client-dhcp.log
test -s /root/ci-image-test/client-address
