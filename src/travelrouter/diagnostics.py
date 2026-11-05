"""Bounded, credential-conscious diagnostics for local support exports."""

import io
import ipaddress
import json
import logging
import re
import shutil
import subprocess
import zipfile
from datetime import UTC, datetime

from .metrics import logs
from .network import CommandFailure, command

LOG = logging.getLogger(__name__)

# Do not export configuration or security-sensitive log entries. These may
# contain arbitrary user-supplied secrets, not just values labelled password.
SENSITIVE = re.compile(r'(?i)password|passphrase|secret|token|credential|cookie|authorization|private.key|psk|ssid|connected to wireless network|config: added|https?://')


def collect():
    checks = {
        'kernel': ['/bin/uname', '-a'],
        'ipv4_addresses': ['/sbin/ip', '-4', 'addr', 'show'],
        'ipv4_routes': ['/sbin/ip', '-4', 'route', 'show'],
        'link_statistics': ['/sbin/ip', '-s', 'link', 'show'],
        'loaded_modules': ['/sbin/lsmod'],
        'internet_ip_ping': ['/bin/ping', '-c', '1', '-W', '3', '1.1.1.1'],
        'local_dns': ['/usr/bin/nslookup', 'example.com', '127.0.0.1'],
        'router_https': ['/usr/bin/curl', '-4', '--noproxy', '*', '--silent', '--show-error', '--head', '--max-time', '5', 'https://example.com'],
    }
    results = {}
    for name, arguments in checks.items():
        try:
            results[name] = {'status': 'ok', 'output': command(arguments, timeout=7)[:16384]}
        except subprocess.TimeoutExpired:
            results[name] = {'status': 'timeout'}
        except CommandFailure as error:
            results[name] = {'status': 'failed', 'exit_code': error.returncode}
        except (OSError, RuntimeError):
            results[name] = {'status': 'unavailable'}
        LOG.info('Diagnostic check %s: %s', name, results[name]['status'])
    safe_logs = {name: [line for line in entries if not SENSITIVE.search(line)] for name, entries in logs().items()}
    return {'format': 'travelrouter-diagnostics-v1', 'created_utc': datetime.now(UTC).isoformat(),
            'privacy': 'Logs are filtered, but may still contain IP addresses, MAC addresses, device names or other private data. Review before sharing.',
            'checks': results, 'logs': safe_logs}



def gateway_from_route(route):
    for line in route.splitlines():
        match = re.match(r'^default via (\S+) dev ([a-zA-Z0-9_.-]{1,15})(?:\s|$)', line)
        if match:
            try:
                return str(ipaddress.IPv4Address(match.group(1))), match.group(2)
            except ValueError:
                continue
    return None


def _safe_text(value, limit=262144):
    return '\n'.join(line for line in value[-limit:].splitlines() if not SENSITIVE.search(line))


def _capture(arguments, timeout=8):
    executable = shutil.which(arguments[0], path='/usr/sbin:/usr/bin:/sbin:/bin')
    if not executable:
        return {'status': 'unavailable'}
    try:
        result = subprocess.run([executable, *arguments[1:]], capture_output=True, text=True,
                                errors='replace', timeout=timeout, check=False)  # nosec B603
        return {'status': 'ok' if result.returncode == 0 else 'failed', 'exit_code': result.returncode,
                'output': _safe_text(result.stdout), 'error': _safe_text(result.stderr, 8192)}
    except subprocess.TimeoutExpired:
        return {'status': 'timeout'}
    except OSError:
        return {'status': 'unavailable'}


def bundle():
    report = collect()
    route = report['checks'].get('ipv4_routes', {}).get('output', '')
    gateway = gateway_from_route(route)
    checks = {
        'neighbours': ['ip', '-4', 'neigh', 'show'],
        'network_devices': ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'],
        'ip_forward': ['sysctl', 'net.ipv4.ip_forward'],
        'service_status': ['rc-status', '-a'],
        'usb_devices': ['lsusb'],
    }
    if gateway:
        address, device = gateway
        checks['gateway_ping'] = ['ping', '-I', device, '-c', '3', '-W', '2', address]
        checks['wifi_link'] = ['iw', 'dev', device, 'link']
    extended = {name: _capture(args) for name, args in checks.items()}
    if not gateway:
        extended['gateway_ping'] = {'status': 'unavailable', 'reason': 'No valid IPv4 default gateway'}
    report['extended_checks'] = extended
    kernel = _capture(['dmesg'])
    system = _capture(['logread'])
    report['extended_checks']['kernel_log'] = {key: value for key, value in kernel.items() if key != 'output'}
    report['extended_checks']['system_log'] = {key: value for key, value in system.items() if key != 'output'}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('README.txt', 'Filtered diagnostic data. IP addresses, MAC addresses, hostnames and other private data may remain. Review before sharing. Logs are bounded and may omit sensitive-looking lines. Configuration files and packet captures are not included.\n')
        archive.writestr('diagnostics.json', json.dumps(report, indent=2))
        archive.writestr('kernel.log', kernel.get('output', ''))
        archive.writestr('system.log', system.get('output', ''))
    return stream.getvalue()
