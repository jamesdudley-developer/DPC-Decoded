"""Certificate built from the real 754 read (real 754 data, tag and serials replaced): fields, maths and the PDF itself."""
import datetime as dt, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dpcreader import certificate as C, report as R, session

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "real754_sample.json")


class Certificate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE) as f:
            cls.snap = session.redecode(json.load(f))
        cls.cal = R.calibration(cls.snap, cls.snap["lists"]["r"][0])
        cls.fields = C.default_fields(cls.cal, cls.snap["device"], today=dt.date(2026, 11, 21))

    def test_fields_from_calibrator(self):
        f = self.fields
        self.assertEqual((f["certNo"], f["instrumentId"], f["serialNumber"], f["calDate"]),
                         ("260714-TT-100", "TT-100", "SN-0001", "14/07/2026"))
        self.assertEqual((f["maxErrorLimit"], f["unit"], f["lrv"], f["urv"], f["sensorType"]),
                         ("0.50", "°C", "0.00", "100.00", "2W RTD Pt100 (385)"))
        self.assertEqual((f["equipSerial"], f["signDate"], f["result"]), ("0000000", "21/11/2026", "PASSED"))

    def test_saved_fields_are_reused(self):
        f = C.default_fields(self.cal, self.snap["device"], saved={"technician": "A. Tech", "instrumentId": "X"})
        self.assertEqual(f["technician"], "A. Tech")
        self.assertEqual(f["instrumentId"], "TT-100")          # calibrator fields are never overridden

    def test_rows_use_certificate_app_maths(self):
        rows = C.test_rows(C.pick(self.cal, "As Found"), self.fields)
        got = [(r["value"], r["target"], r["measured"], round(r["error"], 6), round(r["pct"], 4)) for r in rows]
        self.assertEqual(got, [(0.0, 4.0, 4.027, 0.027, 0.1688), (50.0, 12.0, 12.03, 0.03, 0.1875),
                               (100.0, 20.0, 20.027, 0.027, 0.1688)])
        self.assertTrue(all(r["error"] == 0 for r in C.test_rows(C.pick(self.cal, "As Left"), self.fields)))

    def test_result_follows_as_left(self):
        self.assertEqual(C.overall_result(self.cal, dict(self.fields, maxErrorLimit="0.1")), "PASSED")
        only_found = dict(self.cal, results=[C.pick(self.cal, "As Found")])
        self.assertEqual(C.overall_result(only_found, dict(self.fields, maxErrorLimit="0.1")), "FAILED")
        self.assertEqual(C.overall_result(only_found, self.fields), "PASSED")

    def test_pdf(self):
        p = os.path.join(tempfile.mkdtemp(), "c.pdf")
        C.build_pdf(self.cal, dict(self.fields, comments="line 1\nline 2 & <more>"), p)
        with open(p, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 3000)
        only_found = dict(self.cal, results=[C.pick(self.cal, "As Found")])     # no As Left table rows
        C.build_pdf(only_found, self.fields, p)


if __name__ == "__main__":
    unittest.main(verbosity=2)
