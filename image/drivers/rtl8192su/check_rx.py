#!/usr/bin/env python3
"""Exercise the port's actual receive key selection with protected frames."""

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

source = pathlib.Path(sys.argv[1]).read_text()
match = re.search(r'static enum r92su_rx_control_t\s+r92su_rx_find_key\(.*?(?=\nstatic enum r92su_rx_control_t\s+r92su_rx_port_check)', source, re.S)
if not match:
    raise SystemExit('Cannot locate receive key selection code')

prefix = r'''
#include <stdio.h>
#include <string.h>
typedef unsigned char u8;
enum r92su_rx_control_t { RX_CONTINUE, RX_DROP };
enum { WEP40_ENCRYPTION = 1, WEP104_ENCRYPTION = 2, AESCCMP_ENCRYPTION = 3 };
struct r92su { int unused; };
struct r92su_key { int type; };
struct r92su_sta { struct r92su_key *sta_key; };
struct r92su_rx_info { int has_protect; struct r92su_sta *sta; struct r92su_key *key; };
struct ieee80211_hdr { u8 addr1[6], addr2[6], addr3[6], iv[8]; };
struct sk_buff { void *data; struct r92su_rx_info info; };
struct r92su_bss_priv { struct r92su_sta *sta; struct r92su_key *group_key[4]; };
#define rcu_dereference(x) (x)
#define is_multicast_ether_addr(x) ((x)[0] & 1)
static u8 *r92su_get_i3e_payload(struct ieee80211_hdr *h) { return h->iv; }
static struct r92su_rx_info *r92su_get_rx_info(struct sk_buff *s) { return &s->info; }
'''
suffix = r'''
int main(void) {
    struct r92su r = {0};
    struct r92su_key pair = { AESCCMP_ENCRYPTION }, group = { AESCCMP_ENCRYPTION };
    struct r92su_sta sta = { &pair };
    struct r92su_bss_priv b = { .sta = &sta, .group_key = { &group } };
    struct ieee80211_hdr h = {0};
    struct sk_buff skb = { .data = &h, .info = { .has_protect = 1, .sta = &sta } };
    h.addr1[0] = 2; /* Unicast, while pairwise and group keys both use index zero. */
    if (r92su_rx_find_key(&r, &skb, &b) != RX_CONTINUE || skb.info.key != &pair) {
        fputs("unicast receive must select the pairwise key\n", stderr); return 1;
    }
    h.addr1[0] = 255; skb.info.key = NULL;
    if (r92su_rx_find_key(&r, &skb, &b) != RX_CONTINUE || skb.info.key != &group) {
        fputs("group receive must select the indexed group key\n", stderr); return 1;
    }
    b.group_key[0] = NULL; skb.info.key = NULL;
    if (r92su_rx_find_key(&r, &skb, &b) != RX_DROP || skb.info.key != NULL) {
        fputs("group receive without a group key must be dropped\n", stderr); return 1;
    }
    h.addr1[0] = 2; sta.sta_key = NULL; b.group_key[0] = &group; skb.info.key = NULL;
    if (r92su_rx_find_key(&r, &skb, &b) != RX_DROP || skb.info.key != NULL) {
        fputs("unicast receive must not fall back to a CCMP group key\n", stderr); return 1;
    }
    group.type = WEP40_ENCRYPTION;
    if (r92su_rx_find_key(&r, &skb, &b) != RX_CONTINUE || skb.info.key != &group) {
        fputs("legacy WEP unicast must retain its default key fallback\n", stderr); return 1;
    }
    return 0;
}
'''
compiler = shutil.which('cc')
if compiler is None:
    raise SystemExit('A host C compiler is required for the receive checks')
with tempfile.TemporaryDirectory(prefix='r92su-rx-check-') as directory:
    c_file = pathlib.Path(directory) / 'check.c'
    executable = pathlib.Path(directory) / 'check'
    c_file.write_text(prefix + match.group(0) + suffix)
    # The build supplies pinned, patched driver source and intentionally runs this harness.
    subprocess.run([compiler, '-std=c99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', str(c_file), '-o', str(executable)], check=True)  # nosec B603
    subprocess.run([str(executable)], check=True)  # nosec B603
print('r92su receive key checks passed')
