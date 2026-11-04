"""Bounded domain lists and country CIDRs from fixed HTTPS sources."""

import hashlib
import ipaddress
import json
import re
import time
import urllib.request
from pathlib import Path

from .config import atomic_write

SOURCES = {
    'ads': 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/light-onlydomains.txt',
    'threats': 'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/wildcard/tif.mini-onlydomains.txt',
}
DEFAULTS = {'ads': True, 'threats': True, 'domains': [], 'allow': [], 'tlds': [], 'countries': []}


def domain(value, allow_tld=False):
    if not isinstance(value, str) or len(value) > 253:
        raise ValueError('Invalid domain')
    try:
        value = value.lower().strip('.').encode('idna').decode('ascii')
    except UnicodeError as error:
        raise ValueError('Invalid domain') from error
    labels = value.split('.')
    if (not allow_tld and len(labels) < 2) or not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels):
        raise ValueError('Use domain names without URLs or wildcard characters')
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise ValueError('Use domain names rather than IP addresses')


def domains_from_text(text):
    result = set()
    for line in text.splitlines():
        parts = line.split('#', 1)[0].strip().split()
        if not parts:
            continue
        candidate = parts[0]
        if len(parts) == 2 and parts[0] in {'0.0.0.0', '127.0.0.1', '::'}:  # nosec B104 - hosts-file parser, not a listener
            candidate = parts[1]
        elif len(parts) != 1:
            continue
        try:
            result.add(domain(candidate))
        except ValueError:
            continue
        if len(result) > 600000:
            raise ValueError('Domain list exceeds the supported size')
    return result


def validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError('Filtering settings must be an object')
    result = {}
    for category in ('ads', 'threats'):
        value = data.get(category, False)
        if type(value) is not bool:
            raise ValueError('Category switches must be booleans')
        result[category] = value
    for field in ('domains', 'allow', 'tlds', 'countries'):
        values = data.get(field, [])
        if not isinstance(values, list) or len(values) > (30 if field == 'countries' else 500):
            raise ValueError('Too many filtering entries')
        if field == 'countries':
            if any(not isinstance(value, str) or not re.fullmatch('[A-Z]{2}', value) for value in values):
                raise ValueError('Use two-letter uppercase country codes')
            result[field] = sorted(set(values))
        else:
            result[field] = sorted({domain(value, allow_tld=field == 'tlds') for value in values})
            if field == 'tlds' and any('.' in value for value in result[field]):
                raise ValueError('Domain suffixes must be single labels, such as ru')
    return result


def render_block_zones(blocked, allowed, tlds):
    # A more-specific transparent zone exempts an allowed subtree from a parent
    # block; remove nested blocks which would otherwise override that exception.
    safe = [domain(value) for value in allowed]
    blocked = {domain(value) for value in blocked}
    blocked = {value for value in blocked if not any(value == item or value.endswith('.' + item) for item in safe)}
    output = ['# Generated TravelRouter local policy; no query logging.']
    for value in sorted(blocked | {domain(value, allow_tld=True) for value in tlds}):
        output.append(f'local-zone: "{value}" always_nxdomain')
    for value in sorted(safe):
        output.append(f'local-zone: "{value}" transparent')
    return '\n'.join(output) + '\n'


def parse_country_networks(text):
    result = []
    for line in text.splitlines():
        if not line.strip():
            continue
        network = ipaddress.ip_network(line.strip(), strict=True)
        if network.version != 4 or network.prefixlen < 8 or not network.is_global:
            raise ValueError('Country data contains an unsafe or unsupported network')
        result.append(str(network))
        if len(result) > 100000:
            raise ValueError('Country data is too large')
    if not result:
        raise ValueError('Country list is empty')
    return sorted(set(result))


def download(url):
    # Callers construct URLs exclusively from SOURCES or validated ISO codes.
    request = urllib.request.Request(url, headers={'User-Agent': 'TravelRouter/0.1'})
    with urllib.request.urlopen(request, timeout=25) as response:  # nosec B310
        if not response.geturl().startswith('https://'):
            raise ValueError('List download was redirected away from HTTPS')
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('Downloaded list exceeds 16 MiB')
    return data.decode('utf-8-sig')


class Filtering:
    def __init__(self, store):
        self.store = store
        self.directory = Path('/etc/travelrouter/filter-data')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.last_update = 0
        self.error = None

    def settings(self):
        return self.store.load().get('filtering', DEFAULTS.copy())

    def refresh(self, settings=None):
        settings = settings or self.settings()
        metadata = {'updated': time.time(), 'sources': {}}
        # Download and validate everything before replacing the previous cache.
        files = {}
        for category, url in SOURCES.items():
            if settings.get(category):
                text = download(url)
                values = domains_from_text(text)
                if len(values) < 1000:
                    raise ValueError('Downloaded domain list is unexpectedly small')
                files[category + '.txt'] = '\n'.join(sorted(values)) + '\n'
                metadata['sources'][category] = {'url': url, 'domains': len(values),
                                                'sha256': hashlib.sha256(text.encode()).hexdigest()}
        for country in settings['countries']:
            url = f'https://www.ipdeny.com/ipblocks/data/aggregated/{country.lower()}-aggregated.zone'
            text = download(url)
            files[country + '.zone'] = '\n'.join(parse_country_networks(text)) + '\n'
        for name, content in files.items():
            atomic_write(self.directory / name, content)
        atomic_write(self.directory / 'metadata.json', json.dumps(metadata, indent=2))
        self.last_update = time.monotonic()
        self.error = None

    def rules(self, settings=None):
        settings = settings or self.settings()
        blocked = set(settings['domains'])
        for category in SOURCES:
            path = self.directory / (category + '.txt')
            if settings.get(category) and path.exists():
                blocked.update(domains_from_text(path.read_text()))
        regions = set()
        for country in settings['countries']:
            path = self.directory / (country + '.zone')
            if not path.is_file():
                continue
            regions.update(parse_country_networks(path.read_text()))
        return render_block_zones(blocked, settings['allow'], settings['tlds']), sorted(regions)

    def status(self):
        path = self.directory / 'metadata.json'
        metadata = json.loads(path.read_text()) if path.exists() else {'updated': None, 'sources': {}}
        missing = [country for country in self.settings()['countries']
                   if not (self.directory / (country + '.zone')).is_file()]
        return {'settings': self.settings(), 'metadata': metadata, 'last_error': self.error,
                'missing_countries': missing}
