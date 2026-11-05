"""Bounded, credential-conscious diagnostics for local support exports."""

import logging
import re
import subprocess
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
