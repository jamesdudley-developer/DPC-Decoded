"""End-to-end: simulated calibrator -> link -> decode -> snapshot -> store -> CSV."""
import csv, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dpcreader import simulator, session, store


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.msgs = []
        cls.snap = session.read_all(simulator.open_demo(), "Demo", lambda m, f: cls.msgs.append((m, f)))

    def test_identity_and_structure(self):
        s = self.snap
        self.assertEqual(s["device"]["model"], "754")
        self.assertEqual([len(s["lists"][w]) for w in "pr"], [2, 2])
        self.assertEqual(self.msgs[-1], ("Done", 1.0))
        json.dumps(s)                                   # snapshot must be JSON-safe

    def test_every_atom_decoded(self):
        for groups in self.snap["lists"].values():
            for g in groups:
                for a in g["atoms"]:
                    self.assertNotIn(a["decoded"]["kind"], ("undecoded", "unknown"), a)
                    self.assertNotIn("trailing", a["decoded"])

    def test_readings_table(self):
        g = self.snap["lists"]["r"][0]
        info = session.group_summary(g)
        self.assertEqual((info["name"], info["tag"], info["serial"]), ("PT-101 Pressure Tx", "PT-101", "SN 48213"))
        t = session.readings(self.snap, g)
        self.assertEqual(t["columns"], ["Result set", "Point", "meas.mPrimary", "meas.mFunc", "src.sPrimary"])
        self.assertEqual(len(t["rows"]), 10)            # 2 result sets x 5 points
        self.assertEqual(t["rows"][0], [1, 1, "4.021 mA", "mA DC", "0 psi"])
        self.assertEqual(t["rows"][9], [2, 5, "20.004 mA", "mA DC", "100 psi"])

    def test_redecode_saved_read(self):
        snap = json.loads(json.dumps(self.snap))        # as loaded back from the store
        for g in snap["lists"]["r"]:
            for a in g["atoms"]:
                a["decoded"] = {"kind": "undecoded"}    # e.g. saved by an older decoder
        session.redecode(snap)
        self.assertEqual(session.readings(snap, snap["lists"]["r"][0]),
                         session.readings(self.snap, self.snap["lists"]["r"][0]))

    def test_store_and_export(self):
        d = tempfile.mkdtemp()
        st = store.Store(os.path.join(d, "t.db"))
        uid = st.save(self.snap)
        self.assertEqual(st.list()[0][0], uid)
        self.assertEqual(st.load(uid), self.snap)
        n = store.export_csv(self.snap, os.path.join(d, "o.csv"))
        with open(os.path.join(d, "o.csv"), encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual((n, len(rows)), (13, 13))
        self.assertEqual((rows[0]["Tag"], rows[0]["Measure"], rows[0]["Source"]), ("PT-101", "4.021 mA", "0.000 psi"))
        n = store.export_values_csv(self.snap, os.path.join(d, "v.csv"))
        with open(os.path.join(d, "v.csv"), encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        self.assertEqual((n, len(rows)), (13, 14))
        self.assertEqual(rows[0][:4], ["Memory", "Task", "Tag", "Serial"])
        st.db.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
