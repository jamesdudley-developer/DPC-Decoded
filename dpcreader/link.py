"""
dpclink - clean-room Python reimplementation of the Fluke DPC link protocol
(the wire protocol of dpclnk3.dll v1.4, used by DPCTrack2 to talk to Fluke
74x/75x documenting process calibrators).

Rebuilt from Ghidra decompilation; see ../PROTOCOL.md. Function addresses in
comments refer to the original dpclnk3.dll so behaviour can be cross-checked.

Requires: pyserial  (pip install pyserial)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

DLE, STX, ETX, EOT = 0x10, 0x02, 0x03, 0x04

# Frame types (index into the table at 0x1002f1a8): (ctrl code, carries seq)
DATA, ACK, SYNC, SYNC_ACK, RESET = range(5)
_TYPES = [(0x00, True), (0x01, True), (0x03, False), (0x07, False), (0x0B, False)]
# Decoder-only results
OVERFLOW, CRC_ERR, SEQ_ERR, UNKNOWN = 5, 6, 7, 8

BAUD_RATES = (9600, 19200, 38400)


# ---------------------------------------------------------------- CRC (0x1000181b)
def _make_table() -> List[int]:
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
        t.append(c)
    return t


_CRC_TABLE = _make_table()
assert _CRC_TABLE[1] == 0x1189  # matches table @0x1002f200


def crc_update(crc: int, data: Iterable[int]) -> int:
    for b in data:
        crc = (crc >> 8) ^ _CRC_TABLE[(b ^ crc) & 0xFF]
    return crc


# ---------------------------------------------------------------- framing (0x100011cb)
def encode_frame(ftype: int, seq: int = 0, payload: bytes = b"") -> bytes:
    code, has_seq = _TYPES[ftype]
    ctrl = code | ((seq & 3) << 5 if has_seq else 0)
    out = bytearray()
    if ftype in (SYNC, RESET):
        out += bytes([DLE] * 3)
    out += bytes([DLE, STX, ctrl])
    crc = crc_update(0xFFFF, [ctrl])
    if ftype == DATA:
        for b in payload:
            if b == DLE:
                out += bytes([DLE, DLE])
                crc = crc_update(crc, [DLE, DLE])
            else:
                out.append(b)
                crc = crc_update(crc, [b])
    out += bytes([DLE, ETX])
    crc = crc_update(crc, [DLE, ETX])
    out += bytes([~crc & 0xFF, (~crc >> 8) & 0xFF])
    return bytes(out)


# Decoder state table @0x1002f1bc: rows=state, cols=(DLE, STX, ETX, other)
_NEXT = [
    (1, 0, 0, 0),
    (1, 2, 0, 0),
    (3, 3, 3, 3),
    (4, 3, 3, 3),
    (3, 2, 5, 0),
    (6, 6, 6, 6),
]


def _col(b: int) -> int:
    return {DLE: 0, STX: 1, ETX: 2}.get(b, 3)


@dataclass
class Frame:
    kind: int  # DATA/ACK/SYNC/SYNC_ACK/RESET or CRC_ERR/SEQ_ERR/UNKNOWN/OVERFLOW
    seq: int = 0
    payload: bytes = b""


class FrameDecoder:
    """Byte-at-a-time decoder mirroring 0x10001512."""

    def __init__(self, max_payload: int = 4096):
        self.max_payload = max_payload
        self.reset()

    def reset(self):
        self.state = 0
        self.crc = 0xFFFF
        self.ctrl = 0
        self.buf = bytearray()
        self.crc_lo = 0

    def feed(self, b: int) -> Optional[Frame]:
        s = self.state
        if s == 2:  # CTRL byte
            self.ctrl = b
            self.buf = bytearray()
            self.crc = crc_update(0xFFFF, [b])
        elif s == 3:
            self.crc = crc_update(self.crc, [b])
            if b != DLE:
                self.buf.append(b)
        elif s == 4:
            if b == DLE:
                self.buf.append(b)
            self.crc = crc_update(self.crc, [b])
        elif s == 5:
            self.crc_lo = b
        elif s == 6:
            ok = (self.crc ^ (self.crc_lo | b << 8)) == 0xFFFF
            self.state = 0
            return self._finish(ok)
        if len(self.buf) > self.max_payload:
            self.reset()
            return Frame(OVERFLOW)
        self.state = _NEXT[s][_col(b)]
        return None

    def _finish(self, crc_ok: bool) -> Frame:
        if not crc_ok:
            return Frame(CRC_ERR)
        low = self.ctrl & 0x0F
        for idx, (code, has_seq) in enumerate(_TYPES):
            if code == low:
                seq = (self.ctrl >> 5) & 3 if has_seq else 0
                return Frame(idx, seq, bytes(self.buf))
        return Frame(UNKNOWN)


# ---------------------------------------------------------------- link layer
class LinkError(Exception):
    pass


class Link:
    """PKTCOM equivalent: sync, sequenced DATA/ACK with retries."""

    def __init__(self, port, retries: int = 3, timeout: float = 2.0):
        self.port = port  # pyserial-like object: read(n), write(b), reset_input_buffer()
        self.retries = retries
        self.timeout = timeout
        self.seq = 0
        self.synced = False
        self.dec = FrameDecoder()

    # -- raw I/O
    def _write(self, ftype, payload=b"", seq=None):
        self.port.write(encode_frame(ftype, self.seq if seq is None else seq, payload))

    def _read_frame(self) -> Optional[Frame]:
        self.dec.reset()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            chunk = self.port.read(1)
            if not chunk:
                continue
            f = self.dec.feed(chunk[0])
            if f is not None:
                if f.kind in (DATA, ACK) and f.seq != self.seq:
                    return Frame(SEQ_ERR, f.seq, f.payload)
                return f
        return None

    # -- 0x1000e941
    def sync(self):
        for _ in range(self.retries):
            self.port.reset_input_buffer()
            self._write(SYNC)
            f = self._read_frame()
            if f and f.kind == SYNC_ACK:
                self.seq = 0
                self.synced = True
                return
        self.synced = False
        raise LinkError("link sync failed (no SYNC_ACK)")

    def ensure(self):
        if not self.synced:
            self.sync()

    # -- 0x1000ec15
    def send(self, payload: bytes):
        self.ensure()
        for _ in range(self.retries):
            self._write(DATA, payload)
            f = self._read_frame()
            if f is None or f.kind in (CRC_ERR, OVERFLOW, UNKNOWN):
                continue
            if f.kind == ACK:
                self.seq = (self.seq + 1) & 3
                return
            self.sync()  # DATA / RESET / seq mismatch
        raise LinkError("send failed")

    # -- 0x1000eaad
    def recv(self) -> bytes:
        self.ensure()
        for _ in range(self.retries):
            f = self._read_frame()
            if f is None or f.kind in (CRC_ERR, OVERFLOW, UNKNOWN):
                continue
            if f.kind == DATA:
                self._write(ACK)
                self.seq = (self.seq + 1) & 3
                return f.payload
            if f.kind in (RESET, SEQ_ERR):
                self.sync()
                raise LinkError("peer reset / sequence error")
        raise LinkError("receive failed")


# ---------------------------------------------------------------- command layer
class CommandError(Exception):
    pass


def split_fields(record: bytes) -> List[str]:
    """CSV split per 0x1000221a: skip leading blanks, ',' separates, '|' -> ','."""
    text = record.decode("latin-1")
    return [f.lstrip(" \t").replace("|", ",") for f in text.split(",")]


@dataclass
class Response:
    status: str
    records: List[bytes] = field(default_factory=list)

    def fields(self) -> List[List[str]]:
        return [split_fields(r) for r in self.records]


class Calibrator:
    def __init__(self, link: Link):
        self.link = link

    def command(self, cmd: str, max_records: int = 10000) -> Response:
        self.link.send(cmd.encode("latin-1"))
        status = self.link.recv().decode("latin-1")
        if status != "0":
            # rejected; drain to EOT if the device sends one
            raise CommandError(f"{cmd!r} rejected, status={status!r}")
        recs = []
        for _ in range(max_records):
            p = self.link.recv()
            if p == bytes([EOT]):
                return Response(status, recs)
            recs.append(p)
        raise CommandError("no EOT")

    # --- high level, mirroring DPC3* exports
    def identify(self) -> List[str]:  # DPC3get7XX
        return self.command("id").fields()[0]

    def ed(self) -> List[str]:
        return self.command("ed").fields()[0]

    def mem_stats(self) -> List[List[str]]:  # DPC3memstats (raw records)
        return self.command("ms").fields()

    def show(self, text: str):  # 'ps' progress string on the calibrator screen
        text = text.split("\r")[0].split("\n")[0].replace(",", "|")[:252]
        self.command("ps " + text)

    def set_clock(self, *vals: int):  # DPC3setClock
        self.command("cs " + ",".join(str(v) for v in vals))

    def directory(self, which: str = "r") -> List[List[str]]:  # 'md p,all' / 'md r,all'
        return self.command(f"md {which},all").fields()

    def upload_atom(self, which: str, group: int, atom: int) -> bytes:  # DPC3uplStep
        self.link.send(f"mu {which},{group},{atom}".encode())
        if self.link.recv() != b"0":
            raise CommandError("mu rejected")
        header = split_fields(self.link.recv())
        length = int(header[7])
        data = bytearray()
        while len(data) < length:
            data += self.link.recv()
        if self.link.recv() != bytes([EOT]):
            raise CommandError("mu: missing EOT")
        return bytes(data)


    # --- download (DPC3dnlStart 0x10002e9d / DPC3dnlStep 0x10003353 / DPC3validate 0x10002fb3)
    CHUNK = 0x6F  # max data bytes per `mb` command

    def _simple(self, payload: bytes) -> List[bytes]:
        self.link.send(payload)
        if self.link.recv() != b"0":
            raise CommandError(f"{payload[:16]!r} rejected")
        recs = []
        while True:
            p = self.link.recv()
            if p == bytes([EOT]):
                return recs
            recs.append(p)

    def download(self, groups, settle: float = 1.0, progress=None):
        """Replace the calibrator's procedure memory.

        groups: [{"vendor","type","version","alias","sysflags","userflags",
                  "atoms":[{"vendor","type","version","alias","sysflags","userflags","data":bytes}]}]
        This ERASES the procedure memory first and the results memory afterwards,
        exactly as the original software does.
        """
        self._simple(b"ds")                      # start download session; the calibrator drops the link
        self.link.synced = False
        time.sleep(settle)                       # original waits 1 s, then re-syncs
        self.link.sync()
        self.show("Clearing Task Memory")
        self._simple(b"mc p")
        sig = lambda x: "%u,%u,%u,%u,%u,%u" % (x["vendor"], x["type"], x.get("version", 0), x.get("alias", 0),
                                               x.get("sysflags", 0), x.get("userflags", 0))
        for gi, g in enumerate(groups):
            self._simple(("mg p," + sig(g)).encode())
            for ai, a in enumerate(g["atoms"]):
                data = a["data"]
                recs = self._simple(("ma p,%s,%d" % (sig(a), len(data))).encode())
                if not recs or int(recs[0]) != ai:
                    raise CommandError(f"ma: calibrator allocated atom {recs!r}, expected {ai}")
                for off in range(0, len(data), self.CHUNK):
                    chunk = data[off:off + self.CHUNK]
                    hdr = b"mbp" + len(chunk).to_bytes(2, "big") + gi.to_bytes(4, "big")                         + ai.to_bytes(4, "big") + off.to_bytes(4, "big")
                    self._simple(hdr + chunk)
                if progress:
                    progress(gi, ai)
            recs = self._simple(b"mf p")         # finish group; calibrator answers with the group index
            if not recs or int(recs[0]) != gi:
                raise CommandError(f"mf: calibrator closed group {recs!r}, expected {gi}")
        self.show("Clearing Results Memory")
        self._simple(b"mc r")

    def validate(self, which: str = "p", group: Optional[int] = None, atom: Optional[int] = None):
        """`mv`: ask the calibrator to check its memory. Returns None if OK, else
        (group, atom, message) for the first bad item."""
        cmd = "mv " + which + ("" if group is None else f",{group}") + ("" if atom is None else f",{atom}")
        self.link.send(cmd.encode())
        status = self.link.recv()
        if status == b"0":
            self.link.recv()
            return None
        if status != b"2":
            raise CommandError(f"{cmd!r} rejected, status={status!r}")
        f = self.link.recv().decode("latin-1").split(",", 3)
        self.link.recv()
        return int(f[1]), int(f[2]), f[3] if len(f) > 3 else ""


def open_calibrator(port: str, baud: int = 9600, timeout: float = 2.0, retries: int = 3) -> Calibrator:
    import serial  # pyserial

    if baud not in BAUD_RATES:
        raise ValueError(f"baud must be one of {BAUD_RATES}")
    sp = serial.Serial(port, baud, bytesize=8, parity="N", stopbits=1,
                       timeout=0.05, xonxoff=False, rtscts=False, dsrdtr=False)
    return Calibrator(Link(sp, retries=retries, timeout=timeout))


if __name__ == "__main__":
    import argparse, json

    ap = argparse.ArgumentParser(description="Talk to a Fluke DPC calibrator")
    ap.add_argument("port", help="e.g. COM3")
    ap.add_argument("--baud", type=int, default=9600, choices=BAUD_RATES)
    ap.add_argument("cmd", nargs="?", default="id", help="raw command, e.g. id, ms, 'md r,all'")
    a = ap.parse_args()
    cal = open_calibrator(a.port, a.baud)
    print(json.dumps(cal.command(a.cmd).fields(), indent=2))
