"""
maps - the calibrator's name tables ("maps"), fetched with the `mp` command.

Maps turn the numbers in decoded state atoms into names:
  * map "sbucket"            : bucket-list id  -> list name
  * map "sbucket/<list>"     : bucket id       -> bucket name, plus a type spec
  * any other map            : enum value      -> text (used by mapped buckets)

Rebuilt from dpclnk3.dll: DPC3mapStart 0x100057d7, DPC3mapStep 0x10005c93,
bucket-schema builder 0x10023ff4, STA3getBktName 0x1000c0fb. See ../PROTOCOL.md 6.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

ROOT = "sbucket"
FLAG_NAMES = {"exp": "exported", "ro": "read-only", "unr": "unr", "su": "su"}
# type spec -> wire kind name used by memfmt.BUCKET_KINDS
BASIC_TYPES = {"V": "value", "VR": "value+range", "I": "int", "txtid": "int", "U": "unit",
               "T": "time", "V@": "ref", "VR@": "ref", "I@": "ref", "U@": "ref",
               "T@": "ref", "ST@": "ref"}


@dataclass
class MapEntry:
    value: int
    text: str
    extra: Optional[str] = None


@dataclass
class BucketDef:
    id: int
    name: str
    spec: str                 # raw type spec, e.g. "VR", "ST[16]", "units", "V@"
    kind: str                 # value / value+range / int / unit / time / string / mapped / ref / unknown
    flags: List[str]
    map: Optional[str] = None  # enum map name for mapped buckets
    text_id: bool = False      # value is a text id (resolve with Maps.text_id / `ot`)


def parse_map_directory(records: List[bytes]) -> List[dict]:
    """`mp` response records: name,count,checksum"""
    out = []
    for rec in records:
        f = [x.strip() for x in rec.decode("latin-1").split(",")]
        out.append({"name": f[0].replace("|", ","),
                    "count": int(f[1]) if len(f) > 1 else None,
                    "check": int(f[2]) if len(f) > 2 else None})
    return out


def parse_map(records: List[bytes]) -> List[MapEntry]:
    """`mp <name>` response records: value,text[,extra]  (split on the first two commas only)"""
    out = []
    for rec in records:
        parts = rec.decode("latin-1").split(",", 2)
        if len(parts) < 2:
            raise ValueError(f"bad map record {rec!r}")
        out.append(MapEntry(int(parts[0]), parts[1], parts[2] if len(parts) > 2 else None))
    return out


def parse_bucket_spec(bid: int, name: str, extra: Optional[str], known_maps) -> BucketDef:
    """Type spec grammar from 0x10023ff4: <type>[,exp][,ro][,unr][,su]"""
    spec, *flag_parts = (extra or "").split(",")
    flags = [FLAG_NAMES.get(f, f) for f in flag_parts if f]
    if spec in BASIC_TYPES:
        return BucketDef(bid, name, spec, BASIC_TYPES[spec], flags, text_id=(spec == "txtid"))
    if spec.startswith("ST["):
        return BucketDef(bid, name, spec, "string", flags)
    if spec in known_maps:
        return BucketDef(bid, name, spec, "mapped", flags, map=spec)
    return BucketDef(bid, name, spec, "unknown", flags)


class Maps:
    def __init__(self, maps: Optional[Dict[str, List[MapEntry]]] = None):
        self.maps: Dict[str, List[MapEntry]] = maps or {}

    # ---- loading
    @classmethod
    def load(cls, cal) -> "Maps":
        """Upload every map from a dpclink.Calibrator."""
        m = cls()
        for d in parse_map_directory(cal.command("mp").records):
            m.maps[d["name"]] = parse_map(cal.command("mp " + d["name"]).records)
        return m

    # ---- generic lookups (MAP3itos / MAP3stoi)
    def itos(self, map_name: str, value: int) -> Optional[str]:
        for e in self.maps.get(map_name, ()):
            if e.value == value:
                return e.text
        return None

    def stoi(self, map_name: str, text: str) -> Optional[int]:
        for e in self.maps.get(map_name, ()):
            if e.text == text:
                return e.value
        return None

    # ---- bucket schema
    def bucket_lists(self) -> Dict[int, str]:
        return {e.value: e.text for e in self.maps.get(ROOT, ())}

    def schema(self, list_name: str) -> Dict[int, BucketDef]:
        return {e.value: parse_bucket_spec(e.value, e.text, e.extra, self.maps)
                for e in self.maps.get(f"{ROOT}/{list_name}", ())}

    # ---- applying names to a decoded state atom (memfmt kind == "state")
    def annotate(self, state: dict) -> dict:
        lists = self.bucket_lists()
        for lst in state.get("lists", ()):
            lname = lists.get(lst["list"])
            lst["name"] = lname
            schema = self.schema(lname) if lname else {}
            for b in lst["buckets"]:
                d = schema.get(b["id"])
                if d is None:
                    continue
                b["name"], b["spec"], b["flags"] = d.name, d.spec, d.flags
                f = b.get("fields") or []
                if d.kind == "mapped" and f and isinstance(f[0], int):
                    b["text"] = self.itos(d.map, f[0])
                if d.text_id:
                    b["text_id"] = True
        return state


def text_id(cal, tid: int, arg: str = "") -> List[str]:
    """`ot <id>[,arg]` (DPC3mapTextId 0x10004c56): resolve a text id to its string(s)."""
    cmd = f"ot {tid},{arg}" if arg else f"ot {tid}"
    cal.link.send(cmd.encode("latin-1"))
    status = cal.link.recv()
    if status != b"0":
        if status == b"2":
            cal.link.recv()
        raise ValueError(f"{cmd!r} rejected, status={status!r}")
    n = int(cal.link.recv().decode("latin-1"))
    out = [cal.link.recv().decode("latin-1") for _ in range(n)]
    if cal.link.recv() != b"\x04":
        raise ValueError("ot: missing EOT")
    return out
