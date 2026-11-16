"""Hand-build calibrator-only atoms from the spec; gen2.ps1 feeds them to the DLL."""
import struct
A = lambda l, g, a: struct.pack(">bhh", l, g, a)
u16s = lambda *v: bytes([2 * len(v)]) + b"".join(struct.pack(">H", x) for x in v)
atoms = {
    4:  A(1, 0, 5) + A(1, 0, 1) + bytes([1, 2]) + struct.pack(">I", 42) + bytes([3]) + u16s(10, 11, 12, 13, 14),
    8:  b"ans\0" + A(1, 0, 4) + bytes([0x02]) + struct.pack(">f", 21.5),
    14: b"txt\0" + A(1, 0, 2) + bytes([1]) + u16s(0, 2),
    17: A(1, 0, 3) + A(1, 0, 1),
    18: struct.pack(">hb", 7, 2),
}
if __name__ == "__main__":
    for t, b in atoms.items():
        print(t, b.hex())
