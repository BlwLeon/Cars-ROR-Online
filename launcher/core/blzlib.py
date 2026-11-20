import struct,sys
def blz(d):
    d=bytearray(d); enc_len=struct.unpack_from('<I',d,len(d)-8)[0]; inc=struct.unpack_from('<I',d,len(d)-4)[0]
    hdr=enc_len>>24; enc_len&=0xffffff
    out=bytearray(d)+bytearray(inc); src=len(d)-hdr; dst=len(out); lim=len(d)-enc_len
    while src>lim:
        src-=1;flags=d[src]
        for _ in range(8):
            if src<=lim:break
            if flags&0x80:
                src-=2; v=d[src]|(d[src+1]<<8); n=(v>>12)+3; disp=(v&0xfff)+3
                for _ in range(n): dst-=1; out[dst]=out[dst+disp]
            else:
                src-=1;dst-=1;out[dst]=d[src]
            flags<<=1
    return bytes(out)



