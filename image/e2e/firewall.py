"""Prove offline firewall denial using same-path controls in the disposable VM.

Run after prepare.sh, before client.py changes setup. Only uniquely tagged probe
rules are added; production rules/configuration and processes are never replaced.
"""

import ipaddress
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

TABLE = ('inet', 'travelrouter')
ROOT = Path('/root/ci-image-test')

# Each connection binds a new source port, avoiding a preceding established flow.
PROBE = r'''
import json, socket, sys
address, port, forbidden = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
source_port = int(sys.argv[4])
result = {'connected': False}
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(3)
    sock.bind(('0.0.0.0', source_port))
    result['source_port'] = sock.getsockname()[1]
    if result['source_port'] == forbidden:
        print(json.dumps({'retry_port': True}))
        sys.exit(0)
    try:
        sock.connect((address, port))
        result['connected'] = True
        sock.sendall(('GET / HTTP/1.0\r\nHost: ' + address + '\r\n\r\n').encode())
        result['response'] = sock.recv(128).decode('ascii', errors='replace').split('\r\n')[0]
    except OSError as error:
        result['error'] = type(error).__name__
print(json.dumps(result))
'''


class PolicyChanged(RuntimeError):
    """The real controller replaced the table during a measurement."""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def command(arguments, input_text=None):
    return subprocess.run(arguments, input=input_text, text=True, capture_output=True,
                          check=True, timeout=20).stdout  # nosec B603


def rules():
    data = json.loads(command(['nft', '-j', '-a', 'list', 'table', *TABLE]))
    return data['nftables']


def chain_rules(chain):
    return [entry['rule'] for entry in rules()
            if 'rule' in entry and entry['rule']['chain'] == chain]


def delete_tagged(prefix):
    # Resolve handles afresh: a controller reload may have reused old handles.
    entries = rules()
    for entry in entries:
        rule = entry.get('rule', {})
        if str(rule.get('comment', '')).startswith(prefix):
            command(['nft', 'delete', 'rule', *TABLE, rule['chain'], 'handle', str(rule['handle'])])


def counter(chain, tag):
    entries = chain_rules(chain)
    matching = [entry for entry in entries if entry.get('comment') == tag]
    if len(matching) != 1:
        raise PolicyChanged('Controller replaced the probe counter')
    return sum(expression['counter']['packets'] for expression in matching[0]['expr']
               if 'counter' in expression)


def probe(namespace, address, port, forbidden=0, source_port=0):
    for _ in range(5):
        result = json.loads(command(['ip', 'netns', 'exec', namespace, 'python3', '-c', PROBE,
                                     address, str(port), str(forbidden), str(source_port)]))
        if not result.get('retry_port'):
            return result
    raise RuntimeError('Could not allocate a fresh probe source port')


def fresh_port(namespace, forbidden):
    code = ("import socket; s=socket.socket(); s.bind(('0.0.0.0',0)); "
            "print(s.getsockname()[1]); s.close()")
    for _ in range(5):
        port = int(command(['ip', 'netns', 'exec', namespace, 'python3', '-c', code]))
        if port != forbidden:
            return port
    raise RuntimeError('Could not reserve a distinct negative-control port')


def measure(name, namespace, address, port, chain, match, return_match=None):
    for attempt in range(3):
        prefix = 'ci-firewall-' + secrets.token_hex(8) + '-'
        counter_tag, allow_tag = prefix + 'counter', prefix + 'allow'
        try:
            baseline = rules()
            policies = [entry['chain']['policy'] for entry in baseline if 'chain' in entry
                        and entry['chain']['name'] == chain]
            require(policies == ['drop'], 'Expected actual production chain policy drop')
            additions = [f'add rule inet travelrouter {chain} {match} counter comment "{counter_tag}"',
                         f'add rule inet travelrouter {chain} {match} accept comment "{allow_tag}"']
            if return_match:
                additions.append('add rule inet travelrouter forward ' + return_match
                                 + f' accept comment "{prefix}return"')
            command(['nft', '-f', '-'], '\n'.join(additions) + '\n')
            allowed = probe(namespace, address, port)
            positive_packets = counter(chain, counter_tag)
            require(allowed['connected'] and ' 200 ' in allowed.get('response', ''),
                    f'{name}: same-path positive HTTP control failed: {allowed}')
            require(positive_packets > 0, f'{name}: positive control missed the measured firewall path')
            # Remove temporary verdicts, retaining only the passive terminal counter.
            current = rules()
            for entry in current:
                rule = entry.get('rule', {})
                if rule.get('comment') in {allow_tag, prefix + 'return'}:
                    command(['nft', 'delete', 'rule', *TABLE, rule['chain'], 'handle', str(rule['handle'])])
            # Count only the fresh negative flow, never late packets from the
            # positive control after its temporary allow rules are removed.
            denied_port = fresh_port(namespace, allowed['source_port'])
            denied_tag = prefix + 'denied'
            counter(chain, counter_tag)  # Detect a controller replacement first.
            command(['nft', '-f', '-'],
                    f'add rule inet travelrouter {chain} {match} tcp sport {denied_port} '
                    f'counter comment "{denied_tag}"\n')
            current = chain_rules(chain)
            if not current or current[-1].get('comment') != denied_tag:
                raise PolicyChanged('Counter is no longer immediately before production drop policy')
            before = counter(chain, denied_tag)
            denied = probe(namespace, address, port, allowed['source_port'], denied_port)
            after = counter(chain, denied_tag)
            counter(chain, counter_tag)
            require(not denied['connected'], f'{name}: production firewall allowed a fresh connection')
            require(after > before, f'{name}: denial did not reach the production drop policy')
            result = {'test': name, 'result': 'passed', 'attempt': attempt + 1,
                      'allowed_source_port': allowed['source_port'],
                      'denied_source_port': denied['source_port'],
                      'denied_packets': after - before}
            print(json.dumps(result), flush=True)
            return result
        except PolicyChanged:
            if attempt == 2:
                raise
        finally:
            delete_tagged(prefix)
    raise RuntimeError('Firewall measurement did not complete')


def main():
    config = json.loads(Path('/etc/travelrouter/config.json').read_text())
    ap = config['ap_interface']
    require(isinstance(ap, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', ap), 'Invalid AP interface')
    client = str(ipaddress.IPv4Address((ROOT / 'client-address').read_text().strip()))
    require(ipaddress.ip_address(client) in ipaddress.ip_network('10.42.0.0/24'), 'Invalid client lease')
    results = [measure('untrusted panel ingress', 'tr-untrusted', '10.42.0.1', 80, 'input',
                       'iifname "ci-wan" ip saddr 198.18.0.2 ip daddr 10.42.0.1 tcp dport 80'),
               measure('offline client forwarding', 'tr-client', '198.18.0.2', 8080, 'forward',
                       f'iifname "{ap}" oifname "ci-wan" ip saddr {client} ip daddr 198.18.0.2 tcp dport 8080',
                       f'iifname "ci-wan" oifname "{ap}" ip saddr 198.18.0.2 ip daddr {client} tcp sport 8080')]
    (ROOT / 'firewall-results.json').write_text(json.dumps(results, indent=2) + '\n')
    print('FIREWALL E2E PASSED: same-path positive controls and measured production drops', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('FIREWALL E2E FAILED:', error, file=sys.stderr, flush=True)
        sys.exit(1)
