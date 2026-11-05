#!/usr/bin/env python3
"""Exercise the port's actual key and descriptor selection with 802.11 frames."""

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

source = pathlib.Path(sys.argv[1]).read_text()
match = re.search(r'static enum r92su_tx_control_t\s+r92su_tx_select_key\(.*?(?=\nstatic enum r92su_tx_control_t\s+r92su_tx_invalidate_rcu_data)', source, re.S)
descriptor = re.search(r'SET_TX_DESC_BMC\(hdr, (.*)\);', source)
if not match or not descriptor:
    raise SystemExit('Cannot locate transmit selection code')

prefix = r'''
#include <stdio.h>
#include <string.h>
enum r92su_tx_control_t { TX_CONTINUE, TX_DROP };
struct r92su { int unused; };
struct r92su_key { int uploaded; };
struct r92su_sta { int enc_sta; struct r92su_key *sta_key; };
struct r92su_tx_info { struct r92su_sta *sta; struct r92su_key *key; int needs_encrypt; };
struct ieee80211_hdr { int frame_control; unsigned char addr1[6], addr2[6], addr3[6]; };
struct sk_buff { void *data; int protocol; struct r92su_tx_info info; };
struct r92su_bss_priv { struct r92su_sta *sta; struct r92su_key *group_key[4]; int def_multi_key_idx, def_uni_key_idx, control_port_ethertype; };
#define rcu_dereference(x) (x)
#define cpu_to_le16(x) (x)
#define IEEE80211_FCTL_PROTECTED 0x4000
#define ieee80211_is_data_present(x) 1
#define is_multicast_ether_addr(x) ((x)[0] & 1)
#define ieee80211_get_DA(x) (((x)->frame_control & 2) ? (x)->addr1 : (x)->addr3)
static struct r92su_sta *peer;
static struct r92su_tx_info *r92su_get_tx_info(struct sk_buff *s) { return &s->info; }
static struct r92su_sta *r92su_sta_get(struct r92su *r, const unsigned char *a) { (void)r; return a[0] == 2 ? peer : NULL; }
'''
suffix = r'''
int main(void) {
    struct r92su r = {0};
    struct r92su_key pair = {1}, group = {1};
    struct r92su_sta sta = {1, &pair};
    struct r92su_bss_priv b = { .sta = &sta, .group_key = { &group } };
    struct ieee80211_hdr h = {0};
    struct sk_buff skb = { .data = &h, .info = { .sta = &sta } };
    peer = &sta;
    /* Station DHCP broadcast: receiver is the AP, Ethernet destination is group. */
    h.frame_control = 1; h.addr1[0] = 2; h.addr3[0] = 255;
    if (classify(&h) || r92su_tx_select_key(&r, &skb, &b) != TX_CONTINUE || skb.info.key != &pair) {
        fputs("station broadcast must use unicast receiver and pairwise key\n", stderr); return 1;
    }
    /* Ordinary station unicast uses the AP pairwise key as well. */
    memset(&skb.info, 0, sizeof(skb.info)); skb.info.sta = &sta;
    h.frame_control = 1; h.addr1[0] = 2; h.addr3[0] = 4;
    if (classify(&h) || r92su_tx_select_key(&r, &skb, &b) != TX_CONTINUE || skb.info.key != &pair) {
        fputs("station unicast must use the pairwise key\n", stderr); return 1;
    }
    /* AP broadcast: the 802.11 receiver itself is multicast. */
    memset(&skb.info, 0, sizeof(skb.info)); skb.info.sta = &sta;
    h.frame_control = 2; h.addr1[0] = 255; h.addr3[0] = 2;
    if (!classify(&h) || r92su_tx_select_key(&r, &skb, &b) != TX_CONTINUE || skb.info.key != &group) {
        fputs("AP broadcast must use group receiver and key\n", stderr); return 1;
    }
    return 0;
}
'''
program = prefix + '\nstatic int classify(struct ieee80211_hdr *i3e) { return ' + descriptor.group(1) + '; }\n' + match.group(0) + suffix
compiler = shutil.which('cc')
if compiler is None:
    raise SystemExit('A host C compiler is required for the transmit checks')
with tempfile.TemporaryDirectory(prefix='r92su-tx-check-') as directory:
    c_file = pathlib.Path(directory) / 'check.c'
    executable = pathlib.Path(directory) / 'check'
    c_file.write_text(program)
    # The build supplies pinned, patched driver source and intentionally runs this test harness.
    subprocess.run([compiler, '-std=c99', '-Wall', '-Wextra', '-Werror', str(c_file), '-o', str(executable)], check=True)  # nosec B603
    subprocess.run([str(executable)], check=True)  # nosec B603
print('r92su transmit receiver and key checks passed')
