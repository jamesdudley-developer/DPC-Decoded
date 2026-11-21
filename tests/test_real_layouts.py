"""Layouts a real calibrator can produce that the demo simulator does not:
state diffs against a base state, directory indices that are not list positions,
and buckets the decoder only partly understands."""
import csv, os, struct, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dpcreader import memfmt as F, session, store
from dpcreader.simulator import NULL, addr, bucket, f32, marker, ranged, u16s, u8v


def state_bytes(base, *body):
    return bytes([0, 0, 0]) + base + bytes([0]) + b"".join(body)


def atom(index, atype, raw):
    return {"index": index, "vendor": 1, "type": atype, "version": 0, "size": len(raw),
            "decoded": session._plain(F.decode_atom(1, atype, raw))}


def summary(*idx):
    return NULL + NULL + bytes([0, 0]) + struct.pack(">I", 0) + bytes([1]) + u16s(*idx)


def snapshot(atoms, group_index=0):
    g = {"index": group_index, "name": "Calibration", "atoms": atoms}
    return {"lists": {"p": [], "r": [g]}, "maps": {}}, g


class RealLayouts(unittest.TestCase):
    def test_state_diff_applies_base(self):
        base = state_bytes(NULL, marker(1), ranged(1, 4.0, 4.0, 20.0, 7), bucket(2, 2, u8v(1)),
                           marker(2), ranged(1, 0.0, 0.0, 100.0, 20))
        diff = state_bytes(addr(2, 0, 2), marker(1), ranged(1, 12.05, 4.0, 20.0, 7),
                           marker(2), ranged(1, 50.0, 0.0, 100.0, 20))
        snap, g = snapshot([atom(0, 4, summary(3)), atom(1, 9, b"Calibration\0\0\0\0"),
                            atom(2, 3, base), atom(3, 3, diff)])
        t = session.readings(snap, g)
        row = dict(zip(t["columns"], t["rows"][0]))
        self.assertEqual(row["list 1.bucket 1"], "12.05 unit #7")
        self.assertEqual(row["list 1.bucket 2"], "1")          # inherited from the base state
        self.assertEqual(row["list 2.bucket 1"], "50 unit #20")
        self.assertNotIn("Note", t["columns"])

    def test_directory_index_not_list_position(self):
        st = state_bytes(NULL, marker(1), ranged(1, 8.0, 4.0, 20.0, 7))
        snap, g = snapshot([atom(1, 4, summary(2)), atom(2, 3, st)])     # numbered from 1
        t = session.readings(snap, g)
        self.assertEqual(t["rows"][0][2], "8 unit #7")

    def test_bad_range_keeps_value(self):
        bad = bucket(1, 1, f32(9.5), b"\x01\xC9\xE0")                    # range header we can't parse
        st = state_bytes(NULL, marker(1), bad)
        d = F.decode_atom(1, 3, st)
        b = d["lists"][0]["buckets"][0]
        self.assertEqual(b["value"], 9.5)
        self.assertIn("error", b["range"])

    def test_partial_decode_and_note_in_csv(self):
        st = state_bytes(NULL, marker(1), ranged(1, 16.0, 4.0, 20.0, 7)) + b"\x05\x1f"  # unknown type
        snap, g = snapshot([atom(0, 4, summary(1, 7)), atom(1, 3, st)])
        self.assertIn("error", g["atoms"][1]["decoded"])
        t = session.readings(snap, g)
        self.assertEqual(t["columns"][-1], "Note")
        self.assertEqual(t["rows"][0][2], "16 unit #7")
        self.assertIn("partly decoded", t["rows"][0][-1])
        self.assertIn("not found", t["rows"][1][-1])
        p = os.path.join(tempfile.mkdtemp(), "o.csv")
        store.export_values_csv(snap, p)
        with open(p, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0][-1], "Note")
        self.assertEqual(rows[1][6], "16 unit #7")


if __name__ == "__main__":
    unittest.main(verbosity=2)
