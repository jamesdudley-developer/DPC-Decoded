"""Hand-build a state bucket atom (type 3) from the spec for gen3.ps1."""
import struct
END = b"\xE0"
def bucket(bid, kind, *fields):
    idb = bytes([bid]) if bid < 0x80 else bytes([0x80 | bid >> 8, bid & 0xFF])
    return idb + bytes([0x01, 0xC0 | kind]) + b"".join(fields) + END
marker = lambda lid: b"\xFF\xFF" + (b"\x27" if lid == 0 else bytes([0x67, lid]))
state = (bytes([0, 0, 0, 0xFE, 0])
    + marker(0) + bucket(1, 2, b"\x24")                                   # root.dummy = 0
    + marker(2) + bucket(18, 0, b"\x02" + struct.pack(">f", 4.002))       # meas.value
                + bucket(19, 2, b"\x64\x05")                              # meas.count = 5
                + bucket(200, 0, b"\x82\xbf\xc0")                         # meas.big = -1.5
                + bucket(20, 5, b"\x0ahello\0")                           # meas.label
                + bucket(21, 1, b"\x02" + struct.pack(">f", 12.5),        # meas.ranged = 12.5 + full range record
                         bytes([0x12, 3, 0xA8, 0x34, 0x02]), b"\xC3", b"\x82\x41\xa0",
                         b"\x02" + struct.pack(">f", 100.5), b"\x22", b"\xC7")
    + marker(5) + bucket(3, 2, b"\x84\x01\x2c"))                          # src.mode = 300
if __name__ == "__main__":
    print(3, state.hex())
