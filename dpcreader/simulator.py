"""
A simulated calibrator, so the app can be tried with no hardware.

It speaks the same link protocol and serves a small, invented memory image
(two tasks with result sets). The bucket names, units and readings here are
MADE UP for the demo - they are not what a real calibrator reports.
"""
from __future__ import annotations

import queue
import struct
import threading

from . import link as L


# ---------------------------------------------------------------- in-memory serial cable
class Pipe:
    def __init__(self, rx, tx):
        self.rx, self.tx = rx, tx

    def write(self, b):
        for x in b:
            self.tx.put(x)

    def read(self, n=1):
        try:
            return bytes([self.rx.get(timeout=0.02)])
        except queue.Empty:
            return b""

    def reset_input_buffer(self):
        while not self.rx.empty():
            try:
                self.rx.get_nowait()
            except queue.Empty:
                break

    def close(self):
        pass


def cable():
    a, b = queue.Queue(), queue.Queue()
    return Pipe(a, b), Pipe(b, a)


# ---------------------------------------------------------------- atom encoders (see PROTOCOL.md 5)
def f32(x): return b"\x02" + struct.pack(">f", x)
def u8v(x): return bytes([0xC0 | x]) if x < 32 else bytes([0x09, x])
def addr(l, g, a): return struct.pack(">bhh", l, g, a)
def u16s(*v): return bytes([2 * len(v)]) + b"".join(struct.pack(">H", x) for x in v)
NULL = b"\xFE"


def bucket(bid, kind, *fields):
    idb = bytes([bid]) if bid < 0x80 else bytes([0x80 | bid >> 8, bid & 0xFF])
    return idb + bytes([0x01, 0xC0 | kind]) + b"".join(fields) + b"\xE0"


def marker(list_id):
    return b"\xFF\xFF" + bytes([0x67, list_id])


def ranged(bid, value, lo, hi, unit, digits=3):
    hdr = bytes([0x12, 3, 0x00, digits & 0x0F, 0x00])
    return bucket(bid, 1, f32(value), hdr, b"\xC3", f32(lo), f32(hi), f32(0.0), u8v(unit))


def state(src_value, src_unit, src_rng, meas_value, meas_unit, meas_rng, func):
    return (bytes([0, 0, 0]) + NULL + bytes([0])
            + marker(1) + ranged(1, meas_value, *meas_rng, meas_unit) + bucket(2, 2, u8v(func))
            + marker(2) + ranged(1, src_value, *src_rng, src_unit))


MAPS = {
    "sbucket": ["1,meas", "2,src"],
    "sbucket/meas": ["1,mPrimary,VR,exp", "2,mFunc,mfunc,exp"],
    "sbucket/src": ["1,sPrimary,VR,exp"],
    "mfunc": ["0,V DC", "1,mA DC", "2,Pressure"],
    "unit": ["3,V", "7,mA", "20,psi", "30,degC"],
}


def _task(name, tag, serial, src_unit, src_rng, runs):
    """Returns (procedure atoms, result atoms). runs = list of [(source, measured), ...]."""
    n = len(runs[0])
    points = [int(10000 * i / (n - 1)) for i in range(n)]
    proc = [(9, 1407, "start", name.encode() + b"\0\0\0" + b"Demo task\0"),
            (11, 1410, "tag", tag.encode() + b"\0" + serial.encode() + b"\0\0"),
            (10, 1409, "strategy", f"{n} pt up".encode() + b"\0" + u16s(*points))]
    res = [(9, 1407, "start", name.encode() + b"\0\0\0" + b"Demo task\0"),
           (11, 1410, "tag", tag.encode() + b"\0" + serial.encode() + b"\0\0")]
    first_state = len(res) + len(runs)
    states = []
    for r, run in enumerate(runs):
        idx = [first_state + r * n + i for i in range(n)]
        res.append((4, 1404, f"result {r + 1}",
                    NULL + NULL + bytes([0, 0]) + struct.pack(">I", 0) + bytes([1]) + u16s(*idx)))
        for src, meas in run:
            states.append((3, 1402, "state", state(src, src_unit, src_rng, meas, 7, (4.0, 20.0), 1)))
    return proc, res + states


def demo_memory():
    t1 = _task("PT-101 Pressure Tx", "PT-101", "SN 48213", 20, (0.0, 100.0),
               [[(0, 4.021), (25, 8.035), (50, 12.048), (75, 16.052), (100, 20.061)],
                [(0, 4.002), (25, 8.001), (50, 12.003), (75, 16.002), (100, 20.004)]])
    t2 = _task("TT-205 Temp Tx", "TT-205", "SN 77120", 30, (0.0, 200.0),
               [[(0, 3.998), (100, 12.004), (200, 19.997)]])
    return {"p": [("PT-101 Pressure Tx", t1[0]), ("TT-205 Temp Tx", t2[0])],
            "r": [("PT-101 Pressure Tx", t1[1]), ("TT-205 Temp Tx", t2[1])]}


# ---------------------------------------------------------------- the simulated device
class SimCalibrator(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port, self.seq, self.dec = port, 0, L.FrameDecoder()
        self.mem = demo_memory()
        self.alive = True

    def _frame(self):
        while self.alive:
            c = self.port.read(1)
            if c:
                f = self.dec.feed(c[0])
                if f:
                    return f
        raise SystemExit

    def _send(self, payload):
        self.port.write(L.encode_frame(L.DATA, self.seq, payload))
        f = self._frame()
        if f.kind == L.SYNC:
            self.seq = 0
            self.port.write(L.encode_frame(L.SYNC_ACK))
            raise ConnectionResetError
        self.seq = (self.seq + 1) & 3

    def _reply(self, *records):
        self._send(b"0")
        for r in records:
            self._send(r if isinstance(r, bytes) else r.encode("latin-1"))
        self._send(bytes([L.EOT]))

    def _directory(self, which):
        out = []
        for gi, (name, atoms) in enumerate(self.mem[which]):
            out.append(f'{gi},{len(atoms)},1,1,0,0,26,11,16,1,9,30,0,1500,0,0,"{name}')
            for ai, (typ, alias, aname, data) in enumerate(atoms):
                out.append(f'{ai},1,{typ},0,{len(data)},{alias},0,0,"{aname}')
        return out

    def _handle(self, cmd):
        if cmd == "id":
            self._reply("754, DEMO-0001, 1.00")
        elif cmd == "ms":
            self._reply(*[f"{w},0,1000,500,0,{len(self.mem[w])}" for w in "pr"])
        elif cmd == "mp":
            self._reply(*[f"{k},{len(v)},{i}" for i, (k, v) in enumerate(MAPS.items())])
        elif cmd.startswith("mp "):
            self._reply(*MAPS.get(cmd[3:], []))
        elif cmd.startswith("md "):
            self._reply(*self._directory(cmd[3]))
        elif cmd.startswith("mu "):
            w, g, a = cmd[3:].split(",")
            data = self.mem[w][int(g)][1][int(a)][3]
            self._reply(f"0,0,0,0,0,0,0,{len(data)}", *[data[i:i + 200] for i in range(0, len(data), 200)])
        elif cmd.startswith(("ps", "cs ")):
            self._reply()
        else:
            self._send(b"1")

    def run(self):
        try:
            while True:
                f = self._frame()
                if f.kind == L.SYNC:
                    self.seq = 0
                    self.port.write(L.encode_frame(L.SYNC_ACK))
                    continue
                if f.kind != L.DATA or f.seq != self.seq:
                    continue
                self.port.write(L.encode_frame(L.ACK, self.seq))
                self.seq = (self.seq + 1) & 3
                try:
                    self._handle(f.payload.decode("latin-1"))
                except ConnectionResetError:
                    pass
        except SystemExit:
            pass


def open_demo() -> L.Calibrator:
    host, dev = cable()
    sim = SimCalibrator(dev)
    sim.start()
    cal = L.Calibrator(L.Link(host, retries=3, timeout=1.0))
    cal._sim = sim
    return cal
