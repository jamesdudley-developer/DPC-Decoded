"""Calibration results laid out the way the 754 shows them: per tag and As Found /
As Left, the measure and source setup, then Source / Measure / Error % per test point."""
from __future__ import annotations

from typing import Dict, List, Optional

from . import session as S

COLUMNS = ["Tag", "Serial No", "Date", "Time", "Result",
           "Test Strategy", "Point", "Source", "Measure", "Error %", "Pass/Fail",
           "Measure function", "Measure 0% Value", "Measure 100% Value", "Tolerance", "Delay",
           "Source function", "Source 0% Value", "Source 100% Value"]

# unit name -> (display unit, scale, decimals)
UNITS = {
    "Amps": ("mA", 1000.0, 3), "Amps DC": ("mA", 1000.0, 3), "Amps AC": ("mA AC", 1000.0, 3),
    "Volts": ("V", 1.0, 3), "Volts DC": ("V", 1.0, 3), "Volts AC": ("V AC", 1.0, 3),
    "Ohms": ("Ω", 1.0, 2), "Hertz": ("Hz", 1.0, 2), "Seconds": ("s", 1.0, 1),
    "Celsius": ("°C", 1.0, 2), "Fahrenheit": ("°F", 1.0, 2),
    "Kelvin": ("K", 1.0, 2), "Rankine": ("°R", 1.0, 2), "Percent": ("%", 1.0, 2),
}
GLYPHS = {"": "↑", "": "↓"}          # calibrator font arrows -> up / down


def fmt_value(value, unit: str = "") -> str:
    if not isinstance(value, (int, float)):
        return "" if value is None else str(value)
    disp, scale, dec = UNITS.get(unit, (unit if unit not in ("None", "String") else "", 1.0, 3))
    return f"{value * scale:.{dec}f}" + (f" {disp}" if disp else "")


def device_text(s: str) -> str:
    """Device strings are UTF-8 with private-use glyphs; the decoder hands them over as latin-1."""
    try:
        s = s.encode("latin-1").decode("utf-8")
    except (UnicodeError, AttributeError):
        return s or ""
    return "".join(GLYPHS.get(c, c) for c in s)


def _values(snapshot: dict, group: dict, atom: Optional[dict]) -> Dict[str, dict]:
    d = (atom or {}).get("decoded") or {}
    if d.get("kind") != "state":
        return {}
    return {v["name"].split(".", 1)[-1]: v for v in S.state_values(snapshot, S.merged_state(snapshot, group, d))}


def _function(vals: Dict[str, dict], side: str) -> str:
    mode = vals.get(f"{side}cMode", {}).get("value")
    if not isinstance(mode, str) or mode == "None":
        return ""
    for n in ("2", "3", "4"):
        mode = mode.replace(f"{n} Wire ", f"{n}W ")
    if "RTD" in mode:
        mode += " " + str(vals.get(f"{side}RtdType", {}).get("value", ""))
    elif mode.startswith("TC"):
        mode += " " + str(vals.get(f"{side}TcType", {}).get("value", ""))
    return mode.strip()


def _when(group: dict):
    t = group.get("time") or {}
    y = t.get("year", 0)
    y = y - 2000 if y > 3000 else y                        # reads saved before the year fix
    return (f"{t.get('day', 0):02d}/{t.get('month', 0):02d}/{y:04d}",
            f"{t.get('hour', 0):02d}:{t.get('minute', 0):02d}:{t.get('second', 0):02d}")


def _strategy_name(snapshot: dict, group: dict, addr: dict) -> str:
    _, a = S.resolve_addr(snapshot, group, addr)
    d = (a or {}).get("decoded") or {}
    return device_text(d.get("name", "")) if d.get("kind") == "strategy" else ""


def group_rows(snapshot: dict, group: dict) -> List[dict]:
    """Report rows for one results group: one per test point, or one for a single reading."""
    info = S.group_summary(group)
    date, time = _when(group)
    head = {"Tag": info["tag"] or group.get("name", ""), "Serial No": info["serial"], "Date": date, "Time": time}
    atoms = group.get("atoms", [])
    sets = [a for a in atoms if (a.get("decoded") or {}).get("kind") == "strategy_summary"]
    rows = []
    for s in sets:
        d = s["decoded"]
        steps = [_values(snapshot, group, S.find_atom(group, i)) for i in d.get("results", [])]
        first = steps[0] if steps else {}
        mu = first.get("mPrimary", {}).get("unit", "")
        su = first.get("sPrimary", {}).get("unit", "")
        tol = first.get("tol", {}).get("value")
        setup = {
            "Result": "As Found" if d.get("status") == 1 else "As Left" if d.get("status") == 0 else "",
            "Measure function": _function(first, "m"),
            "Measure 0% Value": fmt_value(first.get("mUutZero", {}).get("value"), mu),
            "Measure 100% Value": fmt_value(first.get("mUutFS", {}).get("value"), mu),
            "Tolerance": f"{tol:.2f} %" if isinstance(tol, (int, float)) else "",
            "Delay": f"{d['srcd'] / 1000:g} s" if isinstance(d.get("srcd"), int) else "",
            "Source function": _function(first, "s"),
            "Source 0% Value": fmt_value(first.get("sUutZero", {}).get("value"), su),
            "Source 100% Value": fmt_value(first.get("sUutFS", {}).get("value"), su),
            "Test Strategy": _strategy_name(snapshot, group, d.get("strategy")),
        }
        for n, v in enumerate(steps, 1):
            err = v.get("error", {}).get("value")
            row = dict(head, **setup, Point=n,
                       Source=fmt_value(v.get("sPrimary", {}).get("value"), v.get("sPrimary", {}).get("unit", su)),
                       Measure=fmt_value(v.get("mPrimary", {}).get("value"), v.get("mPrimary", {}).get("unit", mu)))
            if isinstance(err, (int, float)):
                row["Error %"] = f"{err:.2f}"
                if isinstance(tol, (int, float)) and tol > 0:
                    row["Pass/Fail"] = "Pass" if abs(round(err, 2)) <= tol else "Fail"
            if not v:
                row["Pass/Fail"] = "no data for this point"
            rows.append(row)
    if not sets:                                           # a stored Measure / Measure Source reading
        states = [a for a in atoms if (a.get("decoded") or {}).get("kind") == "state"]
        if states:
            v = _values(snapshot, group, states[-1])
            sp, mp = v.get("sPrimary", {}), v.get("mPrimary", {})
            rows.append(dict(head, Result=group.get("name", ""),
                             **{"Measure function": _function(v, "m"), "Source function": _function(v, "s")},
                             Point=1, Source=fmt_value(sp.get("value"), sp.get("unit", "")),
                             Measure=fmt_value(mp.get("value"), mp.get("unit", ""))))
    return [{c: r.get(c, "") for c in COLUMNS} for r in rows]


def unit_info(unit: str):
    """(display unit, scale, decimals) for a calibrator unit name."""
    return UNITS.get(unit, (unit if unit not in ("None", "String") else "", 1.0, 3))


def calibration(snapshot: dict, group: dict) -> Optional[dict]:
    """Raw numbers of one calibration (a group with result sets), or None.
    Values are in calibrator units (e.g. Amps); use unit_info() to display them."""
    atoms = group.get("atoms", [])
    sets = [a for a in atoms if (a.get("decoded") or {}).get("kind") == "strategy_summary"]
    if not sets:
        return None
    info = S.group_summary(group)
    date, time = _when(group)
    out = {"tag": info["tag"], "serial": info["serial"], "date": date, "time": time,
           "group_name": group.get("name", ""), "results": []}
    for s in sets:
        d = s["decoded"]
        steps = [_values(snapshot, group, S.find_atom(group, i)) for i in d.get("results", [])]
        first = next((v for v in steps if v), {})
        g = lambda k: first.get(k, {}).get("value")
        out["results"].append({
            "kind": "As Found" if d.get("status") == 1 else "As Left" if d.get("status") == 0 else "",
            "strategy": _strategy_name(snapshot, group, d.get("strategy")),
            "delay_s": d["srcd"] / 1000 if isinstance(d.get("srcd"), int) else None,
            "tolerance": g("tol"),
            "measure_function": _function(first, "m"), "source_function": _function(first, "s"),
            "measure_unit": first.get("mPrimary", {}).get("unit", ""),
            "source_unit": first.get("sPrimary", {}).get("unit", ""),
            "measure_zero": g("mUutZero"), "measure_fs": g("mUutFS"),
            "source_zero": g("sUutZero"), "source_fs": g("sUutFS"),
            "points": [{"source": v.get("sPrimary", {}).get("value"),
                        "measure": v.get("mPrimary", {}).get("value"),
                        "error_pct": v.get("error", {}).get("value")} for v in steps],
        })
    return out


def all_rows(snapshot: dict) -> List[dict]:
    return [r for g in snapshot.get("lists", {}).get("r", []) for r in group_rows(snapshot, g)]
