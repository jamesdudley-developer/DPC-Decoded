"""
memfmt - decoder for the Fluke DPC calibrator memory image format (the bytes
returned by the `mu` upload command / MEM3readAtom in dpclnk3.dll).

Rebuilt from Ghidra decompilation; see ../PROTOCOL.md section 5. Addresses in
comments are functions in dpclnk3.dll.

Everything multi-byte is BIG-endian on the wire (the PC byte-swaps, 0x100127d1).
An atom carries no header of its own: its (vendor, type, version) signature
comes from the directory (`md`), and selects which layout below applies.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


class FormatError(Exception):
    pass


# ------------------------------------------------------------------ byte stream
class Reader:
    def __init__(self, data: bytes):
        self.d, self.p = data, 0

    def eof(self) -> bool:
        return self.p >= len(self.d)

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise FormatError(f"read past end at {self.p}+{n}/{len(self.d)}")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def rest(self) -> bytes:
        return self.take(len(self.d) - self.p)

    def u8(self): return self.take(1)[0]
    def i8(self): return struct.unpack(">b", self.take(1))[0]
    def u16(self): return struct.unpack(">H", self.take(2))[0]
    def i16(self): return struct.unpack(">h", self.take(2))[0]
    def u32(self): return struct.unpack(">I", self.take(4))[0]
    def i32(self): return struct.unpack(">i", self.take(4))[0]
    def f32(self): return struct.unpack(">f", self.take(4))[0]
    def f64(self): return struct.unpack(">d", self.take(8))[0]

    def cstr(self) -> str:  # 0x10012a0f: NUL-terminated
        end = self.d.index(b"\0", self.p)
        s = self.d[self.p:end].decode("latin-1")
        self.p = end + 1
        return s

    def varlen(self) -> int:  # 0x10012e2b: byte count prefix
        b = self.u8()
        if b < 0x80:
            return b
        return int.from_bytes(self.take(b & 0x7F), "big")


# ------------------------------------------------------------------ typed values
# QUARK_TYPED_VALUE::x  0x1001cdb5 / tag codec 0x1001ca4a / flags @0x10030998
T_NONE, T_COMPOUND, T_F32, T_F64, T_I32, T_U32, T_I16, T_U16, T_I8, T_U8, T_STR = range(11)
T_F32A, T_F64A, T_I32A, T_U32A, T_I16A, T_U16A, T_I8A, T_U8A, T_STRA = range(11, 20)
T_NIL, T_BYTE = 20, 21
TYPE_NAMES = ["none", "compound", "f32", "f64", "i32", "u32", "i16", "u16", "i8", "u8", "str",
              "f32[]", "f64[]", "i32[]", "u32[]", "i16[]", "u16[]", "i8[]", "u8[]", "str[]",
              "nil", "byte"]
_UNSIGNED = {T_U32, T_U16, T_U8, T_BYTE}
_ARRAYS = {T_F32A: ">f", T_F64A: ">d", T_I32A: ">i", T_U32A: ">I",
           T_I16A: ">h", T_U16A: ">H", T_I8A: ">b", T_U8A: ">B"}


class _End:
    def __repr__(self): return "<END>"


END = _End()


@dataclass
class Value:
    type: int
    value: Any

    @property
    def type_name(self): return TYPE_NAMES[self.type]

    def plain(self):
        v = self.value
        if self.type == T_COMPOUND:
            return [x.plain() for x in v]
        return v


def read_value(r: Reader):
    """Returns Value, or END for the compound terminator (tag 0xE0..0xFF)."""
    tag = r.u8()
    mod, t = tag & 0xE0, tag & 0x1F
    if mod == 0xE0:
        return END
    if mod == 0xA0:                       # inline 5-bit signed i8
        return Value(T_I8, t - 32 if t & 0x10 else t)
    if mod == 0xC0:                       # inline 5-bit unsigned u8
        return Value(T_U8, t)
    if t > T_BYTE:
        raise FormatError(f"unknown type {t} (tag 0x{tag:02x})")
    if mod == 0x20:
        return Value(t, 0.0 if t in (T_F32, T_F64) else 0)
    if mod == 0x40:
        return Value(t, 1)
    if mod == 0x60:                       # value packed into one byte
        return Value(t, r.u8() if t in _UNSIGNED else r.i8())
    if mod == 0x80:                       # value packed into two bytes
        if t == T_F32:                    # upper 16 bits of the float, low 16 zero
            return Value(t, struct.unpack(">f", r.take(2) + b"\0\0")[0])
        return Value(t, r.u16() if t in _UNSIGNED else r.i16())
    # mod == 0: full encoding
    if t in (T_NONE, T_NIL): return Value(t, None)
    if t == T_F32: return Value(t, r.f32())
    if t == T_F64: return Value(t, r.f64())
    if t == T_I32: return Value(t, r.i32())
    if t == T_U32: return Value(t, r.u32())
    if t == T_I16: return Value(t, r.i16())
    if t == T_U16: return Value(t, r.u16())
    if t == T_I8: return Value(t, r.i8())
    if t in (T_U8, T_BYTE): return Value(t, r.u8())
    if t == T_STR: return Value(t, r.cstr())
    if t in _ARRAYS:
        fmt = _ARRAYS[t]
        size = struct.calcsize(fmt)
        raw = r.take(r.varlen())
        if len(raw) % size:
            raise FormatError("array byte length not a multiple of element size")
        return Value(t, [struct.unpack_from(fmt, raw, i)[0] for i in range(0, len(raw), size)])
    if t == T_STRA:                       # 0x100132f1
        return Value(t, [r.cstr() for _ in range(r.u16())])
    if t == T_COMPOUND:
        items = []
        while True:
            v = read_value(r)
            if v is END:
                return Value(t, items)
            items.append(v)
    raise FormatError(f"unhandled type {t}")


def read_quark(r: Reader) -> Tuple[int, Any]:
    """QUARK = id + typed value. id is 1 byte, or 2 if the top bit is set (0x1001de72)."""
    b = r.u8()
    qid = ((b & 0x7F) << 8) | r.u8() if b & 0x80 else b
    return qid, read_value(r)


# ------------------------------------------------------------------ embedded structs
@dataclass
class AtomAddr:
    memlist: Optional[int]   # 1 = procedures, 2 = results (confirmed against dpclnk3.dll)
    group: int
    atom: int

    @property
    def is_null(self): return self.group < 0 or self.atom < 0


def read_group_rel(r):  # MLGROUP_REL_ADDR 0x100103c2
    return r.i16()


def read_group_full(r):  # MLGROUP_FULL_ADDR 0x100106dc
    g = r.i16()
    ml = r.i8()
    return {"memlist": None if ml == -1 else ml, "group": g}


def read_atom_full(r) -> AtomAddr:  # MLATOM_FULL_ADDR 0x100108b4
    ml = r.i8()
    if ml == -2:                       # null, nothing follows
        return AtomAddr(None, -1, -1)
    g, a = r.i16(), r.i16()            # MLATOM_REL_ADDR 0x1001054e
    return AtomAddr(None if ml == -1 else ml, g, a)


DOW = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]  # [inf] numbering not confirmed


def read_time(r) -> Dict[str, int]:  # RTC_EMBEDDABLE_TIME 0x1002046b, validated by 0x1002084a
    sec, mi, hr, dow, day, mon, yr = r.take(7)
    return {"year": 1944 + yr, "month": mon, "day": day, "hour": hr, "minute": mi,
            "second": sec, "dow": dow}


# ------------------------------------------------------------------ atom layouts
def _state_setup(r):                    # type 2  STATE_SETUP_ATOM 0x1002bdd5 / op 0x1002b24a
    ops = []
    while not r.eof():
        op, item, nargs = r.u8(), r.u16(), r.u8()
        ops.append({"op": op, "item": item,
                    "args": [{"id": q, "value": v.plain()} for q, v in (read_quark(r) for _ in range(nargs))]})
    return {"ops": ops}


# wire kind codes (0x100278ac); names per the type specs in maps.py
BUCKET_KINDS = {0: "value", 1: "value+range", 2: "int", 3: "unit", 4: "time", 5: "string", 6: "ref"}
LIST_MARKER = 0x7FFF
SETUP_OPS = {1: "init", 2: "set", 4: "eval"}             # item 1 + quark id 0 = select bucket list


def decode_range(vals: List[Value]) -> dict:
    """Range record that follows the value in a value+range bucket (0x10028784, unit 0x100284b2).
    Layout confirmed via STA3getRange; the meaning of the individual numbers is not known yet."""
    hdr = vals[0].value
    out = {"mode": (hdr[0] >> 1) & 3}
    if len(hdr) == 1:                       # back-reference to an identical range stored earlier
        out["same_as"] = {"group": vals[1].value, "atom": vals[2].value, "mark": vals[3].value}
        return out
    out.update({"flag": hdr[0] >> 7, "x4": (hdr[0] >> 3) & 0xF, "hi": hdr[1] >> 4, "lo": hdr[1] & 0xF,
                "b2": hdr[2] - 256 if hdr[2] > 127 else hdr[2]})
    if len(hdr) > 3:
        out["b3"] = hdr[3]
    i = 1
    if out["mode"] == 0:
        n = vals[i].value
        f = [x.value for x in vals[i + 1:i + 1 + n]]
        i += 1 + n
        out["f0"], out["f1"], out["f2"] = f[0], f[1], f[2]
        out["f3"] = f[3] if n == 4 else f[0]
    if i < len(vals):
        u = vals[i]
        if u.type == T_STR:
            out["unit_name"] = u.value
        elif u.type == T_U8:
            out["unit"] = u.value
        elif u.type == T_I8:
            out["unit"] = u.value + 16
            if out["unit"] == 1 and i + 1 < len(vals):
                out["unit_name"] = vals[i + 1].value
    return out


def read_bucket_stream(r, lists: Optional[List[dict]] = None) -> List[dict]:
    """State buckets: QUARK(0x7fff, list id) starts a bucket list; every other quark is a
    bucket whose compound value is [kind, field, field, ...] (0x100278ac, 0x1002a448).
    Pass `lists` to keep what was decoded so far if the stream fails part-way."""
    lists = [] if lists is None else lists
    cur = None
    while not r.eof():
        qid, v = read_quark(r)
        if v is END:
            raise FormatError("stray end marker in bucket stream")
        if qid == LIST_MARKER:
            cur = {"list": v.value, "buckets": []}
            lists.append(cur)
            continue
        if cur is None:
            cur = {"list": None, "buckets": []}
            lists.append(cur)
        if (v.type == T_COMPOUND and len(v.value) == 2 and isinstance(v.value[0].value, list)
                and v.value[1].type == T_COMPOUND):
            # shared value [[id, id, ...], [kind, fields...]]: every listed bucket gets the same value
            for bid in v.value[0].value:
                cur["buckets"].append(_make_bucket(bid, v.value[1].value))
        elif v.type == T_COMPOUND and v.value:
            cur["buckets"].append(_make_bucket(qid, v.value))
        else:                             # antiquark: bucket deleted relative to the base state
            cur["buckets"].append({"id": qid, "deleted": True})
    return lists


def _make_bucket(qid: int, items: List[Value]) -> dict:
    kind = items[0].value
    b = {"id": qid, "kind": BUCKET_KINDS.get(kind, kind) if isinstance(kind, int) else kind,
         "fields": [x.plain() for x in items[1:]]}
    if kind == 1 and len(items) > 1:
        b["value"] = items[1].value
        if len(items) > 2:
            try:                          # range layout is only partly known; never lose the value over it
                b["range"] = decode_range(items[2:])
            except Exception as e:
                b["range"] = {"error": f"{type(e).__name__}: {e}"}
    elif kind == 0 and len(items) > 1:
        b["value"] = items[1].value
    elif kind == 6 and len(items) > 2:    # alias of another bucket (spec "VR@"): [6, mode, target, (cached value)]
        b["ref"] = items[2].value
        if len(items) > 3:
            b["value"] = items[3].value
    return b


def _state_bucket(r):                   # type 3  STATE_BUCKET_ATOM 0x1002aa31
    out = {"version": r.u8(), "colormap": r.u8(), "redefines": r.u8(),
           "base": read_atom_full(r), "flags": r.u8()}
    out["lists"] = []
    try:
        read_bucket_stream(r, out["lists"])
    except Exception as e:              # keep the buckets read before the failure
        out["error"] = f"{type(e).__name__}: {e}"
        out["trailing"] = r.rest()
    return out


def _strat_common(r):
    return {"state": read_atom_full(r), "strategy": read_atom_full(r),
            "b0": r.u8(), "b1": r.u8(), "srcd": r.u32()}


def _u16_array(r):                      # 0x1001315f / 0x10018129: varlen byte count, u16 BE each
    raw = r.take(r.varlen())
    return [struct.unpack_from(">H", raw, i)[0] for i in range(0, len(raw) - 1, 2)]


def _strategy_summary(r):               # type 4  STRATEGY_SUMMARY 0x10019917
    d = _strat_common(r)
    d["status"] = r.u8()
    d["results"] = _u16_array(r)     # atom index (same group) of each step's result atom
    return d


def _proc_strat_ref(r):                 # type 5  PROC_STRAT_REF 0x1001a63f
    d = _strat_common(r)
    d["text1"], d["text2"] = r.cstr(), r.cstr()
    return d


PROMPT_INPUT = {0: "ordinary", 1: "alphanumeric", 2: "numeric", 3: "boolean"}   # 0x100075b8


def _prompt_defn(r):                    # type 6  PROMPT_DEFINITION 0x100185aa
    d = {"text": r.cstr(), "b0": r.u8(), "b1": r.u8(), "b2": r.u8(), "text2": r.cstr()}
    d["input"] = PROMPT_INPUT.get(d["b0"], d["b0"])   # b2 = value from the "font" map
    return d


def _prompt(r):                         # type 7  PROMPT 0x10018975
    return {"definition": read_atom_full(r)}


def _prompt_result(r):                  # type 8  PROMPT_RESULT 0x10018a21
    text = r.cstr()
    ref = read_atom_full(r)
    v = read_value(r)
    return {"text": text, "definition": ref, "value": None if v is END else v.plain()}


def _task_start(r):                     # type 9  TASK_START 0x1001b44b
    return {"name": r.cstr(), "number": r.u16(), "text": r.cstr()}


def _strategy(r):                       # type 10 STRATEGY 0x10019e3a
    d = {"name": r.cstr(), "items": _u16_array(r)}
    d["points"] = [x / 10000 for x in d["items"]]     # fraction of span, 0 <= x < 3 (0x1001aaa8)
    return d


def _instrument_tag(r):                 # type 11 INSTRUMENT_TAG 0x100174c0
    return {"tag": r.cstr(), "text2": r.cstr(), "text3": r.cstr()}


def _list_defn(r):                      # type 12 USER_LIST_DEFN 0x10017ad6
    name = r.cstr()
    return {"name": name, "items": [r.cstr() for _ in range(r.u16())]}


def _list_ref(r):                       # type 13 USER_LIST_REF 0x10017f7b
    return {"prompt": read_atom_full(r), "list": read_atom_full(r), "flags": r.u8()}


def _list_result(r):                    # type 14 USER_LIST_RESULT 0x100176df
    return {"text": r.cstr(), "list": read_atom_full(r), "flags": r.u8(), "selected": _u16_array(r)}


def _state_log(r):                      # type 15 STATE_LOG_BUFFER 0x1002c0ff
    d = {"start": read_time(r), "stop": read_time(r), "n0": r.u32(), "samples": r.u32(), "n2": r.u32()}
    raw = r.take(r.varlen())
    d["values"] = [struct.unpack_from(">f", raw, i)[0] for i in range(0, len(raw) - 3, 4)]
    d["flags"] = list(r.take(r.varlen()))
    d["nranges"] = r.u16()
    d["ranges_raw"] = r.rest()          # nranges x SRANGE (0x10028784), not decoded yet
    return d


def _switch_test(r):                    # type 16 SWITCH_TEST 0x1001ac11
    d = _instrument_tag(r)
    d["ref"] = read_atom_full(r)
    return d


def _switch_result(r):                  # type 17 SWITCH_TEST_RESULT 0x1001ae32
    return {"ref1": read_atom_full(r), "ref2": read_atom_full(r)}


def _task_result_ref(r):                # type 18 TASK_RESULT_REF 0x1001b64f
    return {"result_group": read_group_full(r)}


FLUKE = 1
ATOM_TYPES = {
    2: ("state_setup", _state_setup), 3: ("state", _state_bucket),
    4: ("strategy_summary", _strategy_summary), 5: ("strategy_ref", _proc_strat_ref),
    6: ("prompt_definition", _prompt_defn), 7: ("prompt", _prompt),
    8: ("prompt_result", _prompt_result), 9: ("task_start", _task_start),
    10: ("strategy", _strategy), 11: ("instrument_tag", _instrument_tag),
    12: ("list_definition", _list_defn), 13: ("list_ref", _list_ref),
    14: ("list_result", _list_result), 15: ("state_log", _state_log),
    16: ("switch_test", _switch_test), 17: ("switch_test_result", _switch_result),
    18: ("task_result_ref", _task_result_ref),
}


def decode_atom(vendor: int, atype: int, data: bytes, version: int = 0) -> dict:
    """Decode one atom. Unknown types come back as {'kind': 'unknown', 'raw': ...}."""
    if vendor != FLUKE or atype not in ATOM_TYPES:
        return {"kind": "unknown", "vendor": vendor, "type": atype, "raw": data}
    name, fn = ATOM_TYPES[atype]
    r = Reader(data)
    out = {"kind": name}
    out.update(fn(r))
    if not r.eof():
        out["trailing"] = r.rest()
    return out


# ------------------------------------------------------------------ directory (`md`) records
def _split(rec: str) -> Tuple[List[int], str]:
    head, _, name = rec.partition('"')
    nums = [int(x) for x in head.replace(" ", "").rstrip(",").split(",") if x != ""]
    return nums, name.rstrip('"')


def parse_group_record(rec: str) -> dict:   # 16 fields + "name"  (0x10003d84)
    n, name = _split(rec)
    return {"index": n[0], "natoms": n[1], "vendor": n[2], "type": n[3], "version": n[4],
            "f5": n[5],
            "time": {"year": n[6] if n[6] >= 100 else 2000 + n[6],   # real 754 sends the full year"month": n[7], "day": n[8], "dow": n[9],
                     "hour": n[10], "minute": n[11], "second": n[12]},
            "alias": n[13], "sysflags": n[14], "userflags": n[15], "name": name}


def parse_atom_record(rec: str) -> dict:    # 8 fields + "name"
    n, name = _split(rec)
    return {"index": n[0], "vendor": n[1], "type": n[2], "version": n[3], "size": n[4],
            "alias": n[5], "sysflags": n[6], "userflags": n[7], "name": name}


def parse_directory(records: List[bytes]) -> List[dict]:
    """Records of an `md p,all` / `md r,all` response -> groups with their atoms."""
    groups, i = [], 0
    while i < len(records):
        g = parse_group_record(records[i].decode("latin-1"))
        i += 1
        g["atoms"] = [parse_atom_record(x.decode("latin-1")) for x in records[i:i + g["natoms"]]]
        i += g["natoms"]
        groups.append(g)
    return groups


def dump_memory(cal, which: str = "r") -> List[dict]:
    """Upload and decode one memory list ('p' procedures / 'r' results) from a dpclink.Calibrator."""
    groups = parse_directory(cal.command(f"md {which},all").records)
    for g in groups:
        for a in g["atoms"]:
            raw = cal.upload_atom(which, g["index"], a["index"])
            a["decoded"] = decode_atom(a["vendor"], a["type"], raw, a["version"])
    return groups
