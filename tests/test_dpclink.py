"""Self-tests: CRC check value, frame round-trip, and a full exchange against a
simulated calibrator that implements the device side of the protocol."""
import threading, queue, unittest
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dpcreader import link as d


class Pipe:
    """One end of an in-memory serial cable."""
    def __init__(self, rx, tx):
        self.rx, self.tx = rx, tx
    def write(self, b):
        for x in b: self.tx.put(x)
    def read(self, n=1):
        try: return bytes([self.rx.get(timeout=0.05)])
        except queue.Empty: return b""
    def reset_input_buffer(self):
        while not self.rx.empty(): self.rx.get_nowait()


def cable():
    a, b = queue.Queue(), queue.Queue()
    return Pipe(a, b), Pipe(b, a)


class FakeCalibrator(threading.Thread):
    BLOB = bytes(range(256)) * 3  # contains 0x10 bytes -> exercises stuffing

    def __init__(self, port):
        super().__init__(daemon=True)
        self.port, self.seq, self.dec = port, 0, d.FrameDecoder()

    def frame(self):
        while True:
            c = self.port.read(1)
            if c:
                f = self.dec.feed(c[0])
                if f: return f

    def send(self, payload):
        self.port.write(d.encode_frame(d.DATA, self.seq, payload))
        f = self.frame()
        assert f.kind == d.ACK and f.seq == self.seq, f
        self.seq = (self.seq + 1) & 3

    def reply(self, *records):
        self.send(b"0")
        for r in records: self.send(r)
        self.send(bytes([d.EOT]))

    def run(self):
        while True:
            f = self.frame()
            if f.kind == d.SYNC:
                self.seq = 0
                self.port.write(d.encode_frame(d.SYNC_ACK)); continue
            assert f.kind == d.DATA and f.seq == self.seq
            self.port.write(d.encode_frame(d.ACK, self.seq)); self.seq = (self.seq + 1) & 3
            cmd = f.payload.decode("latin-1")
            if cmd == "id":
                self.reply(b"754, 1234567, V1.10")
            elif cmd.startswith("ps "):
                self.reply()
            elif cmd.startswith("mu "):
                self.reply(f"0,0,0,0,0,0,0,{len(self.BLOB)}".encode(),
                           *[self.BLOB[i:i + 200] for i in range(0, len(self.BLOB), 200)])
            elif cmd == "ds":
                self.reply(); self.mem = []
            elif cmd == "mc p":
                self.reply(); self.mem = []
            elif cmd == "mc r":
                self.cleared_results = True; self.reply()
            elif cmd.startswith("mg p,"):
                self.mem.append({"sig": cmd[5:], "atoms": []}); self.reply()
            elif cmd.startswith("ma p,"):
                g = self.mem[-1]; f = cmd[5:].split(",")
                g["atoms"].append({"sig": ",".join(f[:6]), "data": bytearray(int(f[6]))})
                self.reply(str(len(g["atoms"]) - 1).encode())
            elif cmd.startswith("mbp"):
                p = f.payload
                n, gi, ai, off = (int.from_bytes(p[3:5], "big"), int.from_bytes(p[5:9], "big"),
                                  int.from_bytes(p[9:13], "big"), int.from_bytes(p[13:17], "big"))
                self.mem[gi]["atoms"][ai]["data"][off:off + n] = p[17:17 + n]; self.reply()
            elif cmd == "mf p":
                self.reply(str(len(self.mem) - 1).encode())
            elif cmd.startswith("mv "):
                self.send(b"2"); self.send(b"1,0,3,bad strategy"); self.send(bytes([d.EOT]))
            else:
                self.port.write(d.encode_frame(d.DATA, self.seq, b"1"))


class Tests(unittest.TestCase):
    def test_crc_x25_check_value(self):
        self.assertEqual(~d.crc_update(0xFFFF, b"123456789") & 0xFFFF, 0x906E)

    def test_roundtrip_with_stuffing(self):
        payload = b"a\x10b\x10\x10c\x02\x03"
        dec = d.FrameDecoder()
        out = [dec.feed(b) for b in d.encode_frame(d.DATA, 2, payload)]
        f = [x for x in out if x][0]
        self.assertEqual((f.kind, f.seq, f.payload), (d.DATA, 2, payload))

    def test_crc_error_detected(self):
        raw = bytearray(d.encode_frame(d.DATA, 0, b"hello")); raw[4] ^= 1
        dec = d.FrameDecoder()
        self.assertEqual([x for x in map(dec.feed, raw) if x][0].kind, d.CRC_ERR)

    def test_sync_frame_bytes(self):
        self.assertEqual(d.encode_frame(d.SYNC)[:6], bytes([0x10] * 4 + [0x02, 0x03]))

    def test_full_session(self):
        host, dev = cable()
        FakeCalibrator(dev).start()
        cal = d.Calibrator(d.Link(host, retries=3, timeout=1.0))
        self.assertEqual(cal.identify(), ["754", "1234567", "V1.10"])
        cal.show("Uploading, please wait")
        self.assertEqual(cal.upload_atom("r", 0, 0), FakeCalibrator.BLOB)


class Download(unittest.TestCase):
    def test_download_and_validate(self):
        host, dev = cable()
        fake = FakeCalibrator(dev); fake.start()
        cal = d.Calibrator(d.Link(host, retries=3, timeout=1.0))
        big = bytes(range(256)) + b"tail"                      # 260 bytes -> 3 chunks, includes 0x10
        groups = [{"vendor": 1, "type": 1, "alias": 1500, "sysflags": 1, "atoms": [
            {"vendor": 1, "type": 9, "alias": 1407, "data": b"PT-101\0\0\0note\0"},
            {"vendor": 1, "type": 2, "alias": 1401, "data": big}]}]
        cal.download(groups, settle=0)
        self.assertEqual(fake.mem[0]["sig"], "1,1,0,1500,1,0")
        self.assertEqual(fake.mem[0]["atoms"][0]["sig"], "1,9,0,1407,0,0")
        self.assertEqual(bytes(fake.mem[0]["atoms"][1]["data"]), big)
        self.assertTrue(fake.cleared_results)
        self.assertEqual(cal.validate("p"), (0, 3, "bad strategy"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
