"""A real Fluke 754 (firmware 1.18) results group, uploaded over USB: one tag, As Found and
As Left, 2W RTD Pt100 source -> 4-20 mA measure. Expected values are what the
calibrator itself shows on its Results screens."""
import csv, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dpcreader import report, session, store

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "real754_sample.json")


class Real754(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE) as f:
            cls.snap = session.redecode(json.load(f))
        cls.rows = report.all_rows(cls.snap)

    def test_every_record_decodes_fully(self):
        for groups in self.snap["lists"].values():
            for g in groups:
                for a in g["atoms"]:
                    self.assertNotIn("error", a["decoded"], a["index"])
                    self.assertNotIn("trailing", a["decoded"], a["index"])

    def test_setup_matches_calibrator_screen(self):
        r = self.rows[0]
        self.assertEqual((r["Tag"], r["Serial No"], r["Date"], r["Time"]), ("TT-100", "SN-0001", "14/07/2026", "15:25:58"))
        self.assertEqual((r["Measure 0% Value"], r["Measure 100% Value"], r["Tolerance"], r["Delay"]),
                         ("4.000 mA", "20.000 mA", "0.50 %", "10 s"))
        self.assertEqual((r["Source function"], r["Source 0% Value"], r["Source 100% Value"], r["Test Strategy"]),
                         ("2W RTD Pt100 (385)", "0.00 °C", "100.00 °C", "3 ↑"))

    def test_points_match_calibrator_screen(self):
        got = [(r["Result"], r["Point"], r["Source"], r["Measure"], r["Error %"]) for r in self.rows]
        C = "°C"
        self.assertEqual(got, [
            ("As Found", 1, f"0.00 {C}", "4.027 mA", "0.17"),
            ("As Found", 2, f"50.00 {C}", "12.030 mA", "0.19"),
            ("As Found", 3, f"100.00 {C}", "20.027 mA", "0.17"),
            ("As Left", 1, f"0.00 {C}", "4.000 mA", "0.00"),
            ("As Left", 2, f"50.00 {C}", "12.000 mA", "0.00"),
            ("As Left", 3, f"100.00 {C}", "20.000 mA", "0.00"),
        ])
        self.assertTrue(all(r["Pass/Fail"] == "Pass" for r in self.rows))

    def test_csv(self):
        p = os.path.join(tempfile.mkdtemp(), "o.csv")
        self.assertEqual(store.export_csv(self.snap, p), 6)
        with open(p, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(list(rows[0]), report.COLUMNS)
        self.assertEqual(rows[2]["Measure"], "20.027 mA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
