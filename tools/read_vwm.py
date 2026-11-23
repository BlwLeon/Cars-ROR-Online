#!/usr/bin/env python3
"""Zeigt Transport- (CRNETDBG) und VWM-Status (CRNETVWM) aus einem melonDS-Savestate."""
import struct, sys
d = open(sys.argv[1], 'rb').read()
def find(tag, ver):
    i = d.find(tag)
    while i >= 0 and struct.unpack_from('<I', d, i + 8)[0] != ver: i = d.find(tag, i + 1)
    return i
i = find(b'CRNETDBG', 6)
if i >= 0:
    v = struct.unpack_from('<4I5i', d, i + 8)
    print("Transport: ver %d state %d frame %d fail_step %d | init %d scan %d conn %d dcf %d send %d" % v)
    o = i + 8 + 36 + 12 + 16
    print("  mymac", d[o:o+6].hex(':'), "ap", d[o+6:o+12].hex(':'), "gw", d[o+12:o+18].hex(':'))
    o += 20
    names = "tx tx_cb_err rx rx_nosnap rx_arp rx_ip rx_udp rx_drop txq_full arp_tries aid".split()
    print("  ", dict(zip(names, struct.unpack_from('<11I', d, o))))
i = find(b'CRNETVWM', 1)
if i >= 0:
    names = ("version role my_id my_aid conn_bm rooms_n welcomed dg_tx dg_rx rel_tx rel_resend rel_rx rel_dup rel_drop relq_full "
             "port_tx port_rx ds_tx ds_rx ds_ok ds_nodata last_rtt init_cb init_fail join_res last_api unknown_msg").split()
    v = struct.unpack_from('<%dI' % len(names), d, i + 8)
    for k in range(0, len(names), 7):
        print("VWM:" if k == 0 else "    ", "  ".join(f"{n}={x}" for n, x in zip(names[k:k+7], v[k:k+7])))
    print("     ds_len=%d ds_bm=%#x ds_wait=%d ds_rebase=%d lost=%d net_restart=%d ds_D=%d start_hold=%d sync_fix=%d ds_pre=%d ds_grow=%d repair=%d repaired=%d" % struct.unpack_from("<HHIIIIIIIIIII", d, i + 8 + 4 * len(names)))
    o2 = i + 8 + 4 * len(names) + struct.calcsize("<HHIIIIIIIIIII")
    if o2 + 32 <= len(d):
        print("     clk_hold=%d clk_giveup=%d clk_ahead=%d unrel_drop=%d rel_defer=%d pu_drop=%d clk_ratio=%d ds_shrink=%d" % struct.unpack_from("<IIiIIIII", d, o2))
i = d.find(b'CRQOLDBG')
if i >= 0:
    step, presses, hidden, last = struct.unpack_from('<4I', d, i + 8)
    btn = struct.unpack_from('<5I', d, i + 24); at = struct.unpack_from('<5I', d, i + 64)
    print(f"QOL: step={step} presses={presses} singlecard_hidden={hidden} last_kind={last}  btn={[hex(b) for b in btn]} at={list(at)}")
