"""Tests for memfmt. Byte strings are hand-built from the recovered spec (no real
calibrator dump was available), so these prove the decoder matches the spec,
not that the spec matches a device."""
import struct, unittest
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dpcreader import memfmt as m


def val(b): return m.read_value(m.Reader(bytes(b)))


class TypedValues(unittest.TestCase):
    def test_scalars_full(self):
        self.assertAlmostEqual(val(bytes([m.T_F32]) + struct.pack(">f", 4.25)).value, 4.25)
        self.assertEqual(val(bytes([m.T_F64]) + struct.pack(">d", -1e-9)).value, -1e-9)
        self.assertEqual(val(bytes([m.T_I32]) + struct.pack(">i", -70000)).value, -70000)
        self.assertEqual(val(bytes([m.T_U32]) + struct.pack(">I", 4000000000)).value, 4000000000)
        self.assertEqual(val(bytes([m.T_STR]) + b"mA\0").value, "mA")

    def test_compact_forms(self):
        self.assertEqual(val([0x20 | m.T_F32]).value, 0.0)            # zero
        self.assertEqual(val([0x40 | m.T_I32]).value, 1)              # one
        self.assertEqual(val([0x60 | m.T_I32, 0xFE]).value, -2)       # 1-byte signed
        self.assertEqual(val([0x60 | m.T_U16, 0xFE]).value, 254)      # 1-byte unsigned
        self.assertEqual(val([0x80 | m.T_I32, 0xFF, 0x00]).value, -256)
        self.assertEqual(val([0x80 | m.T_U32, 0xFF, 0x00]).value, 0xFF00)
        self.assertEqual(val([0xA0 | 0x1F]).value, -1)                # inline signed
        self.assertEqual(val([0xA0 | 0x0F]).value, 15)
        self.assertEqual(val([0xC0 | 0x1F]).value, 31)                # inline unsigned
        # float with zero low word: 20.0 = 0x41A00000 -> 2 bytes
        self.assertEqual(val([0x80 | m.T_F32, 0x41, 0xA0]).value, 20.0)

    def test_arrays_and_varlen(self):
        v = val(bytes([m.T_F32A, 8]) + struct.pack(">ff", 1.5, 2.5))
        self.assertEqual(v.value, [1.5, 2.5])
        big = struct.pack(">100H", *range(100))                       # 200 bytes -> long length form
        v = val(bytes([m.T_U16A, 0x81, 200]) + big)
        self.assertEqual(v.value, list(range(100)))
        v = val(bytes([m.T_STRA, 0, 2]) + b"Pass\0Fail\0")
        self.assertEqual(v.value, ["Pass", "Fail"])

    def test_compound_nested(self):
        v = val([m.T_COMPOUND, 0xC0 | 1, m.T_COMPOUND, 0xA0 | 3, 0xE0, 0x40 | m.T_I16, 0xE0])
        self.assertEqual(v.plain(), [1, [3], 1])

    def test_quark_ids(self):
        self.assertEqual(m.read_quark(m.Reader(bytes([0x05, 0xC0 | 7])))[0], 5)
        self.assertEqual(m.read_quark(m.Reader(bytes([0x81, 0x23, 0xC0 | 7])))[0], 0x123)
        self.assertEqual(m.read_quark(m.Reader(bytes([0xFF, 0xFF, 0xC0 | 2])))[0], m.LIST_MARKER)


ADDR = bytes([0x00]) + struct.pack(">hh", 3, 7)        # memlist 0, group 3, atom 7
NULL = bytes([0xFE])


class Atoms(unittest.TestCase):
    def test_task_start(self):
        d = m.decode_atom(1, 9, b"PT-101 cal\0" + struct.pack(">H", 2) + b"note\0")
        self.assertEqual((d["kind"], d["name"], d["number"], d["text"]), ("task_start", "PT-101 cal", 2, "note"))
        self.assertNotIn("trailing", d)

    def test_instrument_tag(self):
        d = m.decode_atom(1, 11, b"PT-101\0SN123\0Unit 4\0")
        self.assertEqual((d["tag"], d["text2"], d["text3"]), ("PT-101", "SN123", "Unit 4"))

    def test_strategy_summary(self):
        raw = ADDR + NULL + bytes([1, 0]) + struct.pack(">I", 5) + bytes([2, 4]) + struct.pack(">HH", 1, 0)
        d = m.decode_atom(1, 4, raw)
        self.assertEqual(d["state"], m.AtomAddr(0, 3, 7))
        self.assertTrue(d["strategy"].is_null)
        self.assertEqual((d["srcd"], d["status"], d["results"]), (5, 2, [1, 0]))

    def test_list_definition(self):
        d = m.decode_atom(1, 12, b"Condition\0" + struct.pack(">H", 2) + b"Good\0Bad\0")
        self.assertEqual(d["items"], ["Good", "Bad"])

    def test_prompt_result(self):
        d = m.decode_atom(1, 8, b"Enter temp\0" + ADDR + bytes([m.T_F32]) + struct.pack(">f", 21.5))
        self.assertEqual(d["value"], 21.5)

    def test_state_buckets(self):
        bucket_v = bytes([0x12, m.T_COMPOUND, 0xC0 | 0, m.T_F32]) + struct.pack(">f", 4.002) + bytes([0xE0])
        bucket_u = bytes([0x13, m.T_COMPOUND, 0xC0 | 6, 0xC0 | 0, 0x60 | m.T_U16, 40, 0xE0])
        anti = bytes([0x14, m.T_NONE])
        raw = bytes([1, 0, 0]) + NULL + bytes([0]) + bytes([0xFF, 0xFF, 0xC0 | 2]) + bucket_v + bucket_u + anti
        d = m.decode_atom(1, 3, raw)
        self.assertEqual(d["lists"][0]["list"], 2)
        b = d["lists"][0]["buckets"]
        self.assertEqual((b[0]["id"], b[0]["kind"]), (0x12, "value"))
        self.assertAlmostEqual(b[0]["fields"][0], 4.002, places=5)
        self.assertEqual((b[1]["kind"], b[1]["fields"]), ("ref", [0, 40]))
        self.assertTrue(b[2]["deleted"])

    def test_state_setup_ops(self):
        raw = bytes([3]) + struct.pack(">H", 9) + bytes([1, 0x02, 0x60 | m.T_I16, 5])
        d = m.decode_atom(1, 2, raw)
        self.assertEqual(d["ops"], [{"op": 3, "item": 9, "args": [{"id": 2, "value": 5}]}])

    def test_log_buffer(self):
        t = bytes([30, 15, 9, 2, 16, 11, 82])                       # 2026-11-16 09:15:30
        raw = t + t + struct.pack(">III", 0, 2, 0) + bytes([8]) + struct.pack(">ff", 1.0, 2.0) + bytes([2, 0, 1]) + b"\0\0"
        d = m.decode_atom(1, 15, raw)
        self.assertEqual((d["start"]["year"], d["start"]["month"], d["start"]["hour"]), (2026, 11, 9))
        self.assertEqual((d["values"], d["flags"], d["nranges"]), ([1.0, 2.0], [0, 1], 0))

    def test_unknown_type_kept_raw(self):
        self.assertEqual(m.decode_atom(1, 99, b"xyz")["raw"], b"xyz")


class RealBytes(unittest.TestCase):
    """Atoms produced by the original dpclnk3.dll v1.4 (see ../validate/gen.ps1)."""
    H = bytes.fromhex

    def test_task_start(self):
        d = m.decode_atom(1, 9, self.H("50542d3130312063616c0000004c6f6f7020636865636b00"))
        self.assertEqual((d["name"], d["number"], d["text"]), ("PT-101 cal", 0, "Loop check"))

    def test_strategy(self):
        d = m.decode_atom(1, 10, self.H("357074207570000a000009c413881d4c2710"))
        self.assertEqual((d["name"], d["points"]), ("5pt up", [0, 0.25, 0.5, 0.75, 1.0]))

    def test_list_definition(self):
        d = m.decode_atom(1, 12, self.H("436f6e646974696f6e000003476f6f6400426164004e656564732c2072657061697200"))
        self.assertEqual(d["items"], ["Good", "Bad", "Needs, repair"])

    def test_strategy_ref(self):
        d = m.decode_atom(1, 5, self.H("01000000010100000001010201020304766965774100766965774200"))
        self.assertEqual((d["state"], d["srcd"], d["text2"]), (m.AtomAddr(1, 0, 1), 0x01020304, "viewB"))

    def test_prompt_definition(self):
        d = m.decode_atom(1, 6, self.H("456e74657220616d6269656e742074656d70000200016465674300"))
        self.assertEqual((d["text"], d["input"], d["b2"], d["text2"]), ("Enter ambient temp", "numeric", 1, "degC"))

    def test_state_setup(self):
        d = m.decode_atom(1, 2, self.H(
            "01000000020001010065020200000112024080106202000001122202000001128241a00200000180c882bfc002000001"
            "136405020000011384ff380200000113040001117002000101006505020000010384012c0200010100650204000000"))
        vals = [(a["id"], a["value"]) for o in d["ops"] for a in o["args"]]
        self.assertEqual(vals[3:9], [(18, 20.0), (200, -1.5), (19, 5), (19, -200), (19, 70000), (0, 5)])
        self.assertNotIn("trailing", d)


class DllAccepted(unittest.TestCase):
    """Bytes hand-built from the spec that the original DLL read back correctly
    (../validate/build3.py + gen3.ps1 + check2.py)."""

    def test_state_with_range(self):
        raw = bytes.fromhex("000000fe00ffff27010 1c224e0ffff6702".replace(" ", "")
                            + "1201c0024080106 2e0".replace(" ", "") + "1301c26405e0"
                            + "1501c1024148000012 03a83402c38241a00242c9000022c7e0".replace(" ", ""))
        d = m.decode_atom(1, 3, raw)
        self.assertNotIn("trailing", d)
        b = d["lists"][1]["buckets"]
        self.assertEqual([x["id"] for x in b], [18, 19, 21])
        r = b[2]["range"]
        self.assertEqual((b[2]["value"], r["f0"], r["f1"], r["f3"], r["unit"]), (12.5, 20.0, 100.5, 20.0, 7))
        self.assertEqual((r["flag"], r["x4"], r["hi"], r["lo"], r["b2"]), (1, 5, 3, 4, 2))


class Directory(unittest.TestCase):
    def test_parse(self):
        recs = [b'0,2,1,1,0,0,26,11,16,2,9,15,30,1500,0,0,"PT-101"',
                b'0,1,9,0,24,1407,0,0,"start"',
                b'1,1,11,0,20,1410,0,0,"tag"']
        g = m.parse_directory(recs)[0]
        self.assertEqual((g["name"], g["natoms"], g["time"]["year"]), ("PT-101", 2, 2026))
        self.assertEqual([a["type"] for a in g["atoms"]], [9, 11])
        self.assertEqual(g["atoms"][1]["size"], 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
