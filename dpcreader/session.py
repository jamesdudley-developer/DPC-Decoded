"""Read everything from a calibrator into one plain-data snapshot, and turn a
snapshot into rows for display / CSV. No GUI code here."""
from __future__ import annotations

import dataclasses
import datetime as _dt
from typing import Callable, List, Optional

from . import link as L, maps as M, memfmt as F

LISTS = {"p": "Procedures", "r": "Results"}
UNIT_MAPS = ("unit", "units", "unit.common")


def open_port(port: str, baud: int, timeout: float = 2.0) -> L.Calibrator:
    return L.open_calibrator(port, baud, timeout=timeout)


def list_ports() -> List[str]:
    try:
        from serial.tools import list_ports
        return [f"{p.device} - {p.description}" for p in list_ports.comports()]
    except Exception:
        return []


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


def read_all(cal: L.Calibrator, source: str, progress: Optional[Callable[[str, float], None]] = None) -> dict:
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
                try:
                    d = F.decode_atom(a["vendor"], a["type"], raw, a["version"])
                    if d.get("kind") == "state":
                        maps.annotate(d)
                except Exception as e:     # keep the raw bytes; never lose an upload to a decode bug
                    d = {"kind": "undecoded", "error": str(e)}
                a["decoded"] = d
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


def readings(snapshot: dict, group: dict) -> dict:
    """Table of test-point readings for one group: {'columns': [...], 'rows': [[...]]}.
    One row per step of each result set (strategy summary)."""
    atoms = group["atoms"]
    sets = [a for a in atoms if (a.get("decoded") or {}).get("kind") == "strategy_summary"]
    cols, rows = [], []
    for si, s in enumerate(sets, 1):
        for step, idx in enumerate(s["decoded"].get("results", []), 1):
            vals = {}
            if 0 <= idx < len(atoms) and (atoms[idx].get("decoded") or {}).get("kind") == "state":
                for v in state_values(snapshot, atoms[idx]["decoded"]):
                    vals[v["name"]] = (_fmt(v["value"]) + (" " + v["unit"] if v["unit"] else "")).strip()
            for k in vals:
                if k not in cols:
                    cols.append(k)
            rows.append((si, step, vals))
    return {"columns": ["Result set", "Point"] + cols,
            "rows": [[si, step] + [vals.get(c, "") for c in cols] for si, step, vals in rows]}
