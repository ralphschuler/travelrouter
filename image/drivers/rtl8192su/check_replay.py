#!/usr/bin/env python3
"""Exercise the port's real CCMP receive replay handling across QoS queues."""

import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

source = pathlib.Path(sys.argv[1]).read_text()
iv_handler = re.search(r'static enum r92su_rx_control_t\s+r92su_rx_iv_handle\(.*?(?=\nstatic enum r92su_rx_control_t\s+r92su_rx_tkip_handle)', source, re.S)
crypto_handler = re.search(r'static enum r92su_rx_control_t\s+r92su_rx_crypto_handle\(.*?(?=\nstatic enum r92su_rx_control_t\s+r92su_rx_data_to_8023)', source, re.S)
if not iv_handler or not crypto_handler:
    raise SystemExit('Cannot locate CCMP receive handling code')
sequence_field = 'unsigned long long rx_seq[16];' if 'ccmp.rx_seq[' in source else 'unsigned long long rx_seq;'
prefix = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;
enum r92su_rx_control_t { RX_CONTINUE, RX_DROP };
enum { WEP40_ENCRYPTION = 1, WEP104_ENCRYPTION, TKIP_ENCRYPTION, AESCCMP_ENCRYPTION };
#define BIT(x) (1U << (x))
#define WARN(...) ((void)0)
#define IEEE80211_WEP_ICV_LEN 4
#define IEEE80211_TKIP_ICV_LEN 4
#define MICHAEL_MIC_LEN 8
#define IEEE80211_CCMP_MIC_LEN 8
struct r92su { int unused; };
struct r92su_bss_priv { int unused; };
struct r92su_key {
 int type, key_len, index;
 struct { void *tfm; unsigned char key[16]; u64 rx_seq; } wep;
 struct { void *tfm; struct { struct { unsigned char key[16]; } _key; } key; u64 rx_seq; } tkip;
 struct { void *tfm; REPLAY_FIELD } ccmp;
};
struct r92su_rx_info { struct r92su_key *key; u64 iv; int needs_decrypt; unsigned int security_idx; };
struct sk_buff { unsigned char *data; unsigned int len; struct r92su_rx_info info; };
struct ieee80211_hdr { uint16_t frame_control; unsigned char data[22]; unsigned char qos[2]; };
static int decrypt_failure;
static struct r92su_rx_info *r92su_get_rx_info(struct sk_buff *s) { return &s->info; }
static unsigned int ieee80211_hdrlen(uint16_t fc) { return (fc & 0x80) ? 26 : 24; }
static int ieee80211_is_data_qos(uint16_t fc) { return !!(fc & 0x80); }
static unsigned int get_tid_h(struct ieee80211_hdr *h) { return h->qos[0] & 15; }
static unsigned int r92su_get_iv_len(struct r92su_key *k) { (void)k; return 8; }
static void skb_pull(struct sk_buff *s, unsigned int n) { s->data += n; s->len -= n; }
static void skb_trim(struct sk_buff *s, unsigned int n) { s->len = n; }
static int ieee80211_wep_decrypt(void *a, struct sk_buff *b, void *c, u64 d, int e, int f) { return 0; }
static int ieee80211_tkip_decrypt_data(void *a, void *b, struct sk_buff *c, u64 d) { return 0; }
static enum r92su_rx_control_t r92su_rx_tkip_handle(struct r92su *a, struct sk_buff *b, struct r92su_key *c) { return RX_CONTINUE; }
static int ieee80211_aes_ccm_decrypt(void *a, struct sk_buff *b, u64 c, int d) { return decrypt_failure; }
'''.replace('REPLAY_FIELD', sequence_field)
suffix = r'''
static int receive(struct r92su_key *key, int qos, int tid, int pn, int fail_decrypt) {
 unsigned char frame[128] = {0};
 struct ieee80211_hdr *h = (struct ieee80211_hdr *)frame;
 unsigned int hdrlen = qos ? 26 : 24;
 struct r92su r = {0}; struct r92su_bss_priv b = {0};
 struct sk_buff skb = { .data = frame, .len = hdrlen + 8 + 16 + 8,
                        .info = { .key = key, .needs_decrypt = 1 } };
 h->frame_control = qos ? 0x80 : 0; h->qos[0] = tid;
 frame[hdrlen] = pn; frame[hdrlen + 3] = BIT(5); decrypt_failure = fail_decrypt;
 if (r92su_rx_iv_handle(&r, &skb, &b) != RX_CONTINUE) return RX_DROP;
 return r92su_rx_crypto_handle(&r, &skb, &b);
}
int main(void) {
 struct r92su_key key = { .type = AESCCMP_ENCRYPTION };
 if (receive(&key, 1, 5, 10, 0) != RX_CONTINUE || receive(&key, 1, 3, 5, 0) != RX_CONTINUE) {
  fputs("independent QoS queues must accept their own increasing packet numbers\n", stderr); return 1;
 }
 if (receive(&key, 1, 5, 10, 0) != RX_DROP || receive(&key, 1, 3, 4, 0) != RX_DROP) {
  fputs("replayed packet numbers must be dropped within each queue\n", stderr); return 1;
 }
 if (receive(&key, 1, 0, 7, 0) != RX_CONTINUE || receive(&key, 0, 0, 6, 0) != RX_DROP) {
  fputs("non-QoS data and QoS TID zero must share replay state\n", stderr); return 1;
 }
 if (receive(&key, 1, 2, 8, 1) != RX_DROP || receive(&key, 1, 2, 8, 0) != RX_CONTINUE) {
  fputs("failed decryption must not advance replay state\n", stderr); return 1;
 }
 return 0;
}
'''
compiler = shutil.which('cc')
if compiler is None:
    raise SystemExit('A host C compiler is required for the replay checks')
with tempfile.TemporaryDirectory(prefix='r92su-replay-check-') as directory:
    c_file = pathlib.Path(directory) / 'check.c'
    executable = pathlib.Path(directory) / 'check'
    c_file.write_text(prefix + iv_handler.group(0) + crypto_handler.group(0) + suffix)
    # The build supplies pinned, patched driver source and intentionally runs this harness.
    subprocess.run([compiler, '-std=c99', '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-sign-compare', str(c_file), '-o', str(executable)], check=True)  # nosec B603
    subprocess.run([str(executable)], check=True)  # nosec B603
print('r92su CCMP per-queue replay checks passed')
