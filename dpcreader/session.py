"""Read everything from a calibrator into one plain-data snapshot, and turn a
snapshot into rows for display / CSV. No GUI code here."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
from typing import Callable, List, Optional, Tuple

from . import link as L, maps as M, memfmt as F

LISTS = {"p": "Procedures", "r": "Results"}
UNIT_MAPS = ("unit", "units", "unit.common")


def open_port(port: str, baud: int, timeout: float = 2.0) -> L.Calibrator:
    return L.open_calibrator(port, baud, timeout=timeout)


FLUKE_USB_VID = 0x0F7E        # Fluke's USB vendor id (754 shows as VID_0F7E&PID_9009)


def list_ports() -> List[str]:
    """COM ports, with any Fluke calibrator first and labelled as such."""
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    except Exception:
        return []
    fluke = [p for p in ports if getattr(p, "vid", None) == FLUKE_USB_VID]
    other = [p for p in ports if p not in fluke]
    return ([f"{p.device} - Fluke calibrator ({p.description})" for p in fluke]
            + [f"{p.device} - {p.description}" for p in other])


def _plain(o):
    """Make decoded data JSON-safe."""
    if dataclasses.is_dataclass(o):
        return {k: _plain(v) for k, v in dataclasses.asdict(o).items()}
    if isinstance(o, (bytes, bytearray)):
        return {"hex": bytes(o).hex()}
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return o


def _decode(a: dict, raw: bytes, maps: M.Maps) -> dict:
    try:
        d = F.decode_atom(a["vendor"], a["type"], raw, a["version"])
        if d.get("kind") == "state":
            maps.annotate(d)
    except Exception as e:                 # keep the raw bytes; never lose an upload to a decode bug
        d = {"kind": "undecoded", "error": f"{type(e).__name__}: {e}"}
    return d


def redecode(snapshot: dict) -> dict:
    """Decode a saved snapshot again from its raw bytes, so reads saved by an older
    version benefit from decoder fixes."""
    try:
        maps = M.Maps({k: [M.MapEntry(**e) for e in v] for k, v in snapshot.get("maps", {}).items()})
    except Exception:
        maps = M.Maps()
    for groups in snapshot.get("lists", {}).values():
        for g in groups:
            t = g.get("time") or {}
            if t.get("year", 0) > 3000:                # saved before the directory year fix
                t["year"] -= 2000
            for a in g.get("atoms", ()):
                raw = (a.get("raw") or {}).get("hex")
                if raw is not None:
                    a["decoded"] = _plain(_decode(a, bytes.fromhex(raw), maps))
    return snapshot


def read_all(cal: L.Calibrator,source: str, progress: Optional[Callable[[str, float], None]] = None) -> dict:
    say = progress or (lambda msg, frac: None)
    say("Identifying calibrator", 0.0)
    ident = cal.identify()
    say("Loading name tables", 0.05)
    try:
        maps = M.Maps.load(cal)
    except Exception:                      # maps are a convenience; carry on without names
        maps = M.Maps()
    dirs = {}
    for w in LISTS:
        say(f"Reading {LISTS[w].lower()} directory", 0.1)
        dirs[w] = F.parse_directory(cal.command(f"md {w},all").records)
    total = sum(len(g["atoms"]) for gs in dirs.values() for g in gs) or 1
    done = 0
    for w, groups in dirs.items():
        for g in groups:
            for a in g["atoms"]:
                raw = cal.upload_atom(w, g["index"], a["index"])
                a["raw"] = raw
                a["decoded"] = _decode(a, raw, maps)
                done += 1
                say(f"Reading {LISTS[w].lower()}: {g['name']}", 0.1 + 0.9 * done / total)
    say("Done", 1.0)
    return _plain({
        "when": _dt.datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "device": {"model": ident[0] if ident else "", "info": ident[1:]},
        "maps": {k: [dataclasses.asdict(e) for e in v] for k, v in maps.maps.items()},
        "lists": dirs,
    })


# ---------------------------------------------------------------- views
def _unit_text(snapshot, rng) -> str:
    if not rng:
        return ""
    if rng.get("unit_name"):
        return rng["unit_name"]
    uid = rng.get("unit")
    if uid is None:
        return ""
    for name in UNIT_MAPS:
        for e in snapshot.get("maps", {}).get(name, ()):
            if e["value"] == uid:
                return e["text"]
    return f"unit #{uid}"


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return "" if v is None else str(v)


def state_values(snapshot: dict, state: dict) -> List[dict]:
    """Flatten a decoded state atom into [{name, value, unit}]."""
    out = []
    for lst in state.get("lists", ()):
        lname = lst.get("name") or f"list {lst.get('list')}"
        for b in lst.get("buckets", ()):
            if b.get("deleted"):
                continue
            name = f"{lname}.{b.get('name') or 'bucket ' + str(b['id'])}"
            if "text" in b and b["text"] is not None:
                val = b["text"]
            elif "value" in b:
                val = b["value"]
            else:
                f = b.get("fields") or [None]
                val = f[0] if len(f) == 1 else f
            out.append({"name": name, "value": val, "unit": _unit_text(snapshot, b.get("range"))})
    return out


def group_summary(group: dict) -> dict:
    """Pull the obvious header facts out of a group."""
    info = {"name": group.get("name", ""), "tag": "", "serial": "", "time": group.get("time")}
    for a in group["atoms"]:
        d = a.get("decoded") or {}
        if d.get("kind") == "task_start" and d.get("name"):
            info["name"] = d["name"]
        elif d.get("kind") == "instrument_tag":
            info["tag"], info["serial"] = d.get("tag", ""), d.get("text2", "")
    return info


MEMLIST_KEYS = {1: "p", 2: "r"}


def _list_key(snapshot: dict, group: dict) -> Optional[str]:
    for w, groups in snapshot.get("lists", {}).items():
        if any(g is group for g in groups):
            return w
    return None


def find_atom(group: dict, idx: int) -> Optional[dict]:
    """Atom by its directory index (falls back to list position)."""
    for a in group.get("atoms", ()):
        if a.get("index") == idx:
            return a
    atoms = group.get("atoms", ())
    return atoms[idx] if 0 <= idx < len(atoms) else None


def resolve_addr(snapshot: dict, group: dict, addr: Optional[dict]) -> Tuple[Optional[dict], Optional[dict]]:
    """(group, atom) an embedded atom address points at, or (None, None)."""
    if not addr or addr.get("group", -1) < 0 or addr.get("atom", -1) < 0:
        return None, None
    w = MEMLIST_KEYS.get(addr.get("memlist")) or _list_key(snapshot, group)
    for g in snapshot.get("lists", {}).get(w, ()):
        if g.get("index") == addr["group"]:
            return g, find_atom(g, addr["atom"])
    return None, None


def _has_unit(b: dict) -> bool:
    rng = b.get("range") or {}
    return "unit" in rng or "unit_name" in rng


def merged_state(snapshot: dict, group: dict, state: dict) -> dict:
    """The full state a state atom describes: its diff applied over the base chain, with
    alias buckets (spec 'VR@') resolved to the bucket they point at."""
    out = _merge(snapshot, group, state)
    for lst in out.get("lists", ()):
        by_id = {b["id"]: b for b in lst.get("buckets", ()) if not b.get("deleted")}
        for b in lst.get("buckets", ()):
            t = by_id.get(b.get("ref"))
            if t is not None and t is not b and "value" in t:
                b.update(value=t["value"], target=t.get("name"))
                if "range" in t:
                    b["range"] = t["range"]
                if "text" in t:
                    b["text"] = t["text"]
    return out


def _merge(snapshot: dict, group: dict, state: dict, _depth: int = 0) -> dict:
    g, base_atom = resolve_addr(snapshot, group, state.get("base"))
    base = (base_atom or {}).get("decoded") or {}
    if _depth > 16 or base.get("kind") != "state" or base is state:
        return json.loads(json.dumps(state))          # private copy; callers may modify it
    base = _merge(snapshot, g, base, _depth + 1)
    lists = {}
    for lst in base.get("lists", ()):
        lists[lst.get("list")] = dict(lst, buckets={b["id"]: b for b in lst.get("buckets", ()) if not b.get("deleted")})
    for lst in state.get("lists", ()):
        cur = lists.setdefault(lst.get("list"), dict(lst, buckets={}))
        if lst.get("name"):
            cur["name"] = lst["name"]
        for b in lst.get("buckets", ()):
            if b.get("deleted"):
                cur["buckets"].pop(b["id"], None)
            else:
                old = cur["buckets"].get(b["id"], {})
                new = {**{k: old[k] for k in ("name", "spec") if k in old}, **b}
                if _has_unit(old) and not _has_unit(new):  # range given as a back-reference: keep the unit
                    new["range"] = old["range"]
                cur["buckets"][b["id"]] = new
    out = dict(state)
    out["lists"] = [dict(l, buckets=list(l["buckets"].values())) for l in lists.values()]
    return out


def readings(snapshot: dict, group: dict) -> dict:
    """Table of test-point readings for one group: {'columns': [...], 'rows': [[...]]}.
    One row per step of each result set (strategy summary). A 'Note' column explains
    any point whose result record could not be turned into values."""
    atoms = group["atoms"]
    sets = [a for a in atoms if (a.get("decoded") or {}).get("kind") == "strategy_summary"]
    cols, rows, any_note = [], [], False
    for si, s in enumerate(sets, 1):
        for step, idx in enumerate(s["decoded"].get("results", []), 1):
            vals, note = {}, ""
            a = find_atom(group, idx)
            d = (a or {}).get("decoded") or {}
            if a is None:
                note = f"result record {idx} not found"
            elif d.get("kind") != "state":
                note = f"record {idx} is '{d.get('kind', '?')}', not a state" + (
                    f" ({d['error']})" if d.get("error") else "")
            else:
                for v in state_values(snapshot, merged_state(snapshot, group, d)):
                    vals[v["name"]] = (_fmt(v["value"]) + (" " + v["unit"] if v["unit"] else "")).strip()
                if d.get("error"):
                    note = f"record {idx} only partly decoded ({d['error']})"
                elif not vals:
                    note = f"record {idx} holds no values"
            any_note = any_note or bool(note)
            for k in vals:
                if k not in cols:
                    cols.append(k)
            rows.append((si, step, vals, note))
    extra = ["Note"] if any_note else []
    return {"columns": ["Result set", "Point"] + cols + extra,
            "rows": [[si, step] + [vals.get(c, "") for c in cols] + ([note] if any_note else [])
                     for si, step, vals, note in rows]}
