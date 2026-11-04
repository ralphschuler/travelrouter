"""Local aggregate metrics without DNS history or packet capture."""

import time
from pathlib import Path

from .network import command


def parse_meminfo(text):
    fields = {}
    for line in text.splitlines():
        key, value = line.split(':', 1)
        fields[key] = int(value.strip().split()[0]) * 1024
    return {'total_bytes': fields.get('MemTotal', 0), 'available_bytes': fields.get('MemAvailable', 0)}


def parse_netdev(text, interfaces):
    result = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        name, raw = line.split(':', 1)
        name = name.strip()
        fields = raw.split()
        if name in interfaces and len(fields) >= 9:
            result[name] = {'rx_bytes': int(fields[0]), 'tx_bytes': int(fields[8])}
    return result


def snapshot(interfaces):
    temperature = Path('/sys/class/thermal/thermal_zone0/temp')
    result = {'timestamp': time.time(), 'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
              'memory': parse_meminfo(Path('/proc/meminfo').read_text()),
              'interfaces': parse_netdev(Path('/proc/net/dev').read_text(), interfaces),
              'load_average': [float(value) for value in Path('/proc/loadavg').read_text().split()[:3]],
              'temperature_c': int(temperature.read_text()) / 1000 if temperature.exists() else None,
              'clients': [], 'dns': {}}
    leases = Path('/var/lib/misc/dnsmasq.leases')
    if leases.exists():
        for line in leases.read_text().splitlines():
            fields = line.split()
            if len(fields) >= 4 and (fields[0] == '0' or int(fields[0]) > time.time()):
                result['clients'].append({'ip': fields[2], 'hostname': fields[3]})
    try:
        output = command(['/usr/sbin/unbound-control', '-c', '/etc/unbound/unbound.conf', 'stats_noreset'], timeout=3)
        fields = dict(line.split('=', 1) for line in output.splitlines() if '=' in line)
        for name in ('total.num.queries', 'total.num.cachehits', 'total.num.cachemiss', 'total.num.answer.rcode.NXDOMAIN'):
            result['dns'][name] = int(float(fields.get(name, '0')))
    except (OSError, RuntimeError, ValueError):
        result['dns'] = {'available': False}
    return result


def logs():
    files = {'router': '/var/log/travelrouter.log', 'proxy': '/var/log/travelrouter-proxy.log',
             'dns': '/var/log/travelrouter-dns.log', 'recovery': '/var/log/travelrouter-recovery.log'}
    result = {}
    for name, filename in files.items():
        path = Path(filename)
        if path.is_file():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 32768))
                result[name] = stream.read().decode(errors='replace').splitlines()[-150:]
        else:
            result[name] = []
    try:
        result['system'] = command(['/sbin/logread'], timeout=3).splitlines()[-150:]
    except (OSError, RuntimeError):
        result['system'] = []
    return result
