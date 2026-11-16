"""Tests for maps: parsing, schema, annotation, and a fetch over the simulated link."""
import threading, unittest
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dpcreader import link as d, memfmt as m, maps
from test_dpclink import cable, FakeCalibrator

MAPS = {
    "sbucket": [b"2,meas", b"5,source"],
    "sbucket/meas": [b"18,value,VR,exp,ro", b"19,func,mfunc,exp", b"20,label,ST[16]", b"21,msg,txtid"],
    "sbucket/source": [b"1,out,V"],
    "mfunc": [b"0,VDC", b"1,mA", b"2,T/C, type K"],
}


class MapCal(FakeCalibrator):
    def run(self):
        while True:
            f = self.frame()
            if f.kind == d.SYNC:
                self.seq = 0; self.port.write(d.encode_frame(d.SYNC_ACK)); continue
            self.port.write(d.encode_frame(d.ACK, self.seq)); self.seq = (self.seq + 1) & 3
            cmd = f.payload.decode()
            if cmd == "mp":
                self.reply(*[f"{k},{len(v)},{i}".encode() for i, (k, v) in enumerate(MAPS.items())])
            elif cmd.startswith("mp "):
                self.reply(*MAPS[cmd[3:]])
            elif cmd == "ot 7":
                self.send(b"0"); self.send(b"1"); self.send(b"Connect leads"); self.send(b"\x04")


class Tests(unittest.TestCase):
    def setUp(self):
        host, dev = cable()
        MapCal(dev).start()
        self.cal = d.Calibrator(d.Link(host, retries=3, timeout=1.0))
        self.maps = maps.Maps.load(self.cal)

    def test_load_and_lookup(self):
        self.assertEqual(set(self.maps.maps), set(MAPS))
        self.assertEqual(self.maps.itos("mfunc", 1), "mA")
        self.assertEqual(self.maps.itos("mfunc", 2), "T/C")           # DLL splits at the 2nd comma (0x10005c93)
        self.assertEqual(self.maps.maps["mfunc"][2].extra, " type K")
        self.assertEqual(self.maps.stoi("sbucket", "source"), 5)

    def test_schema(self):
        s = self.maps.schema("meas")
        self.assertEqual((s[18].kind, s[18].flags), ("value+range", ["exported", "read-only"]))
        self.assertEqual((s[19].kind, s[19].map), ("mapped", "mfunc"))
        self.assertEqual(s[20].kind, "string")
        self.assertTrue(s[21].text_id)

    def test_annotate_state(self):
        import struct
        vr = bytes([18, m.T_COMPOUND, 0xC0 | 1, m.T_F32]) + struct.pack(">f", 12.004) + bytes([0xE0])
        fn = bytes([19, m.T_COMPOUND, 0xC0 | 2, 0x40 | m.T_I16, 0xE0])
        raw = bytes([1, 0, 0, 0xFE, 0]) + bytes([0xFF, 0xFF, 0xC0 | 2]) + vr + fn
        st = self.maps.annotate(m.decode_atom(1, 3, raw))
        lst = st["lists"][0]
        self.assertEqual(lst["name"], "meas")
        self.assertEqual((lst["buckets"][0]["name"], lst["buckets"][0]["kind"]), ("value", "value+range"))
        self.assertEqual((lst["buckets"][1]["name"], lst["buckets"][1]["text"]), ("func", "mA"))

    def test_text_id(self):
        self.assertEqual(maps.text_id(self.cal, 7), ["Connect leads"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
