"""Local history of uploads (SQLite) and exports."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
from typing import List, Optional

from . import report as R, session as S


def data_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "DPCReader")
    os.makedirs(d, exist_ok=True)
    return d


class Store:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join(data_dir(), "uploads.db")
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE IF NOT EXISTS uploads ("
                        "id INTEGER PRIMARY KEY, taken TEXT, source TEXT, model TEXT, "
                        "ngroups INTEGER, snapshot TEXT)")
        self.db.commit()

    def save(self, snap: dict) -> int:
        n = sum(len(g) for g in snap["lists"].values())
        cur = self.db.execute("INSERT INTO uploads (taken, source, model, ngroups, snapshot) VALUES (?,?,?,?,?)",
                              (snap["when"], snap["source"], snap["device"]["model"], n, json.dumps(snap)))
        self.db.commit()
        return cur.lastrowid

    def list(self) -> List[tuple]:
        return self.db.execute("SELECT id, taken, source, model, ngroups FROM uploads ORDER BY id DESC").fetchall()

    def load(self, uid: int) -> dict:
        row = self.db.execute("SELECT snapshot FROM uploads WHERE id=?", (uid,)).fetchone()
        return json.loads(row[0])

    def delete(self, uid: int):
        self.db.execute("DELETE FROM uploads WHERE id=?", (uid,))
        self.db.commit()


def export_csv(snap: dict, path: str) -> int:
    """Calibration results as the calibrator shows them, one row per test point. Returns the row count."""
    rows = R.all_rows(snap)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=R.COLUMNS)
        wr.writeheader()
        wr.writerows(rows)
    return len(rows)


def export_values_csv(snap: dict, path: str) -> int:
    """Every decoded value of every test point (raw bucket names). Returns the row count."""
    tables = []
    for w, groups in snap["lists"].items():
        for g in groups:
            t = S.readings(snap, g)
            if t["rows"]:
                tables.append((S.LISTS.get(w, w), S.group_summary(g), t))
    cols = []
    for _, _, t in tables:
        for c in t["columns"]:
            if c not in cols:
                cols.append(c)
    if "Note" in cols:
        cols.remove("Note")
        cols.append("Note")
    n = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["Memory", "Task", "Tag", "Serial"] + cols)
        for lname, info, t in tables:
            for row in t["rows"]:
                d = dict(zip(t["columns"], row))
                wr.writerow([lname, info["name"], info["tag"], info["serial"]] + [d.get(c, "") for c in cols])
                n += 1
    return n


def export_json(snap: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snap, f, indent=1)
