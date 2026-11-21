"""Calibration certificate (PDF) in the layout of the Calibration-Certificate web app
(github.com/jamesdudley-developer/Calibration-Certificate, buildCertificateDoc in app.js),
filled from a calibration read off the calibrator.

Maths matches that app: target = 4 + 16 x (value - LRV) / span (generalised to the
calibrator's measure range), mA error = measured - target, % span error = error / span x 100."""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional

from . import report as R

FIELDS = [  # (key, label) in the order the dialog shows them
    ("certNo", "Certificate No"), ("result", "Result"),
    ("instrumentId", "Instrument ID"), ("processId", "Process ID"),
    ("serialNumber", "Serial Number"), ("manufacturer", "Manufacturer"),
    ("model", "Model"), ("extendedModel", "Extended Model"),
    ("calDate", "Calibration Date"), ("calInterval", "Calibration Interval"),
    ("technician", "Technician"), ("maxErrorLimit", "Max Error Limit (%)"),
    ("serviceReason", "Service Reason"), ("adjLimit", "Adjustment Limit (%)"),
    ("workOrder", "Work Order"), ("criticalService", "Critical Service"),
    ("siteLocation", "Site Location"), ("sensorType", "Sensor Type"),
    ("ambientTemp", "Ambient Temperature"), ("sensorLimits", "Sensor Limits"),
    ("unit", "Unit"), ("lrv", "LRV"), ("urv", "URV"),
    ("equipDevice", "Equipment"), ("equipSerial", "Equipment Serial"), ("equipDue", "Equipment Next Cal Due"),
    ("comments", "Comments"), ("signName", "Sign-off Name"), ("signDate", "Sign-off Date"),
    ("signature", "Signature image"),
]
# fields remembered between certificates (the rest come from the calibrator or change every time)
REMEMBER = ("calInterval", "technician", "serviceReason", "adjLimit", "criticalService", "siteLocation",
            "equipDevice", "equipSerial", "equipDue", "signName", "signature")
NAVY, GREEN, RED, LABEL_GREY, LINE_GREY = (26, 54, 93), (39, 103, 73), (155, 44, 44), (60, 60, 60), (180, 180, 180)


def _num(v) -> Optional[float]:
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _f(v, digits):
    return "" if v is None else f"{v:.{digits}f}"


def _scaled(v, unit):
    """Value in display units, rounded to the calibrator's display resolution (it stores
    float32, so 4.027 mA comes back as 4.02700016)."""
    if v is None:
        return None
    _, scale, dec = R.unit_info(unit)
    return round(v * scale, dec)


def pick(cal: dict, kind: str) -> Optional[dict]:
    """The last result of a kind ('As Found' / 'As Left'): the one that stands if a test was repeated."""
    found = [r for r in cal["results"] if r["kind"] == kind]
    return found[-1] if found else None


def default_fields(cal: dict, device: dict, today: Optional[_dt.date] = None, saved: Optional[dict] = None) -> Dict[str, str]:
    """Certificate fields pre-filled from the calibration and from what was used last time."""
    today = today or _dt.date.today()
    first = pick(cal, "As Found") or pick(cal, "As Left") or cal["results"][0]
    su = first["source_unit"]
    dec = R.unit_info(su)[2]
    d, m, y = cal["date"].split("/")
    f = {k: "" for k, _ in FIELDS}
    f.update({
        "instrumentId": cal["tag"], "serialNumber": cal["serial"],
        "calDate": cal["date"], "calInterval": "12 months", "criticalService": "No",
        "maxErrorLimit": _f(first["tolerance"], 2),
        "sensorType": first["source_function"],
        "unit": R.unit_info(su)[0],
        "lrv": _f(first["source_zero"], dec), "urv": _f(first["source_fs"], dec),
        "equipDevice": " ".join(x for x in ("Fluke", device.get("model", "").replace("FLUKE", "").strip(),
                                           "Documenting Process Calibrator") if x),
        "equipSerial": (device.get("info") or ["", ""])[1] if len(device.get("info") or []) > 1 else "",
        "signDate": today.strftime("%d/%m/%Y"),
    })
    f["certNo"] = f"{y[-2:]}{m}{d}-{cal['tag']}" if cal["tag"] else f"{y[-2:]}{m}{d}-"
    for k in REMEMBER:
        if saved and saved.get(k):
            f[k] = saved[k]
    f["result"] = overall_result(cal, f)
    return f


def test_rows(res: Optional[dict], fields: Dict[str, str]) -> List[dict]:
    """Table rows for one result: point, process value, target, measured, error, % span error."""
    if not res:
        return []
    lrv, urv = _num(fields.get("lrv")), _num(fields.get("urv"))
    mu = res["measure_unit"]
    mz = _scaled(res["measure_zero"], mu)
    mf = _scaled(res["measure_fs"], mu)
    if mz is None or mf is None or mf == mz:
        mz, mf = 4.0, 20.0
    rows = []
    for n, p in enumerate(res["points"], 1):
        val = _scaled(p["source"], res["source_unit"])
        meas = _scaled(p["measure"], mu)
        target = (mz + (mf - mz) * (val - lrv) / (urv - lrv)
                  if None not in (val, lrv, urv) and urv != lrv else None)
        err = meas - target if None not in (meas, target) else None
        pct = err / (mf - mz) * 100 if err is not None else None
        rows.append({"point": n, "value": val, "target": target, "measured": meas, "error": err, "pct": pct})
    return rows


def overall_result(cal: dict, fields: Dict[str, str]) -> str:
    """PASSED when the As Left (or, without one, As Found) points are all inside the max error limit."""
    limit = _num(fields.get("maxErrorLimit"))
    res = pick(cal, "As Left") or pick(cal, "As Found")
    rows = test_rows(res, fields)
    if limit is None or not rows or any(r["pct"] is None for r in rows):
        return "PASSED"
    return "PASSED" if all(abs(r["pct"]) < abs(limit) for r in rows) else "FAILED"


# ---------------------------------------------------------------- PDF
def build_pdf(cal: dict, fields: Dict[str, str], path: str, generated: Optional[_dt.datetime] = None):
    from reportlab.graphics.charts.legends import LineLegend
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.widgets.markers import makeMarker
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)

    rgb = lambda c: colors.Color(c[0] / 255, c[1] / 255, c[2] / 255)
    generated = generated or _dt.datetime.now()
    page_w = A4[0]
    content_w = page_w - 28 * mm
    title_s = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=16, leading=20, alignment=1)
    line_s = ParagraphStyle("l", fontName="Helvetica", fontSize=11, leading=14, alignment=1)
    head_s = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11, leading=13, spaceAfter=1 * mm)
    cell_s = ParagraphStyle("c", fontName="Helvetica", fontSize=8, leading=10)
    note_s = ParagraphStyle("n", fontName="Helvetica", fontSize=9, leading=11)
    esc = lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    dash = lambda v: v if (v or "").strip() else "—"
    grid = [("GRID", (0, 0), (-1, -1), 0.2 * mm, rgb(LINE_GREY)), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]

    story = [Paragraph("Calibration Certificate", title_s), Spacer(1, 2 * mm),
             Paragraph(esc(f"Certificate No: {dash(fields['certNo'])}") + "&nbsp;" * 4 + esc(f"Result: {fields['result']}"), line_s),
             Spacer(1, 4 * mm)]

    def section(title, flowable, gap=6):
        story.append(KeepTogether([Paragraph(esc(title), head_s), flowable]))
        story.append(Spacer(1, gap * mm))

    def pairs(title, rows):
        body = [[a, Paragraph(esc(dash(fields.get(b, ""))), cell_s), c, Paragraph(esc(dash(fields.get(d, ""))), cell_s)]
                for a, b, c, d in rows]
        t = Table(body, colWidths=[42 * mm, 48 * mm, 42 * mm, 48 * mm], hAlign="LEFT")
        t.setStyle(TableStyle(grid + [
            ("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8),
            ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 8), ("TEXTCOLOR", (0, 0), (0, -1), rgb(LABEL_GREY)),
            ("TEXTCOLOR", (2, 0), (2, -1), rgb(LABEL_GREY)), ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm), ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm)]))
        section(title, t)

    pairs("Device Details", [("Instrument ID", "instrumentId", "Process ID", "processId"),
                             ("Serial Number", "serialNumber", "Manufacturer", "manufacturer"),
                             ("Model", "model", "Extended Model", "extendedModel")])
    pairs("Calibration Details", [("Calibration Date", "calDate", "Calibration Interval", "calInterval"),
                                  ("Technician", "technician", "Max Error Limit (%)", "maxErrorLimit"),
                                  ("Service Reason", "serviceReason", "Adjustment Limit (%)", "adjLimit"),
                                  ("Work Order", "workOrder", "Critical Service", "criticalService"),
                                  ("Site Location", "siteLocation", "Sensor Type", "sensorType"),
                                  ("Ambient Temperature", "ambientTemp", "Sensor Limits", "sensorLimits")])
    lrv, urv = _num(fields["lrv"]), _num(fields["urv"])
    span = {"span": _f(urv - lrv, 2) if None not in (lrv, urv) else ""}
    fields = dict(fields, **span)
    pairs("Range & Span", [("Unit", "unit", "Span", "span"), ("LRV", "lrv", "URV", "urv")])

    def navy_table(head, body, widths=None, center=False, extra=()):
        t = Table([head] + body, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle(grid + [
            ("BACKGROUND", (0, 0), (-1, 0), rgb(NAVY)), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8), ("FONT", (0, 1), (-1, -1), "Helvetica", 8),
            ("ALIGN", (0, 1 if not center else 0), (-1, -1), "CENTER" if center else "LEFT")] + list(extra)))
        return t

    section("Calibration Equipment", navy_table(
        ["Device", "Serial", "Next Calibration Due"],
        [[dash(fields["equipDevice"]), dash(fields["equipSerial"]), dash(fields["equipDue"]) if fields["equipDue"] else "-"]],
        widths=[content_w / 3] * 3), gap=8)

    limit = _num(fields["maxErrorLimit"])
    sdec = R.unit_info((pick(cal, "As Found") or pick(cal, "As Left") or cal["results"][0])["source_unit"])[2]
    series = {}
    for kind, title in (("As Found", "AS FOUND"), ("As Left", "AS LEFT")):
        res = pick(cal, kind)
        rows = test_rows(res, fields)
        mu = R.unit_info(res["measure_unit"])[0] if res else "mA"
        head = ["Test Point", fields["unit"] or "Value", f"Target {mu}", f"Measured {mu}", f"{mu} Error", "% Span Error"]
        body, extra = [], []
        for i, r in enumerate(rows, 1):
            body.append([str(r["point"]), dash(_f(r["value"], sdec)), dash(_f(r["target"], 4)),
                         dash(_f(r["measured"], 4)), dash(_f(r["error"], 6)), dash(_f(r["pct"], 4))])
            if r["pct"] is not None and limit is not None:
                ok = abs(r["pct"]) < abs(limit)
                extra += [("TEXTCOLOR", (5, i), (5, i), rgb(GREEN if ok else RED)), ("FONT", (5, i), (5, i), "Helvetica-Bold", 8)]
        if not body:
            body = [["—", "—", "—", "—", "—", "—"]]
            extra.append(("TEXTCOLOR", (0, 1), (-1, 1), colors.grey))
        series[title] = [(r["point"], r["pct"]) for r in rows if r["pct"] is not None]
        section(title, navy_table(head, body, widths=[content_w / 6] * 6, center=True, extra=extra), gap=8)

    # % span error chart: AS FOUND red circles, AS LEFT green triangles dashed, symmetric Y axis
    chart_h = 70 * mm
    dr = Drawing(content_w, chart_h)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 16 * mm, 12 * mm, content_w - 22 * mm, chart_h - 22 * mm
    data = [series.get("AS FOUND") or [(1, 0)], series.get("AS LEFT") or [(1, 0)]]
    lp.data = data
    vals = [abs(v) for s in series.values() for _, v in s]
    top = max(vals + [0.1]) * 1.15
    pts = [p for s in series.values() for p, _ in s] or [1]
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = min(pts) - 0.25, max(pts) + 0.25
    lp.xValueAxis.valueSteps = list(range(min(pts), max(pts) + 1))
    lp.xValueAxis.labelTextFormat = "%d"
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = -top, top
    lp.yValueAxis.labelTextFormat = lambda v: f"{v:.2f}"
    lp.yValueAxis.gridStrokeColor, lp.yValueAxis.visibleGrid = colors.Color(0, 0, 0, 0.06), 1
    for ax in (lp.xValueAxis, lp.yValueAxis):
        ax.labels.fontName, ax.labels.fontSize = "Helvetica", 7
    lp.lines[0].strokeColor, lp.lines[0].strokeWidth = colors.HexColor("#c53030"), 1.25
    lp.lines[0].symbol = makeMarker("FilledCircle", size=5, fillColor=colors.HexColor("#c53030"))
    lp.lines[1].strokeColor, lp.lines[1].strokeWidth = colors.HexColor("#276749"), 1.25
    lp.lines[1].strokeDashArray = [5, 4]
    lp.lines[1].symbol = makeMarker("FilledTriangle", size=7, fillColor=colors.HexColor("#38a169"))
    if not series.get("AS FOUND"):
        lp.lines[0].strokeColor, lp.lines[0].symbol = colors.transparent, None
    if not series.get("AS LEFT"):
        lp.lines[1].strokeColor, lp.lines[1].symbol = colors.transparent, None
    dr.add(lp)
    dr.add(String(lp.x + lp.width / 2, 2 * mm, "Test Point", fontName="Helvetica", fontSize=8, textAnchor="middle"))
    yl = String(0, 0, "% Span Error", fontName="Helvetica", fontSize=8, textAnchor="middle")
    from reportlab.graphics.shapes import Group
    g = Group(yl)
    g.transform = (0, 1, -1, 0, 4 * mm, lp.y + lp.height / 2)
    dr.add(g)
    lg = LineLegend()
    lg.x, lg.y = content_w / 2 - 25 * mm, chart_h - 4 * mm
    lg.alignment, lg.columnMaximum, lg.deltax, lg.fontName, lg.fontSize = "right", 1, 30 * mm, "Helvetica", 8
    lg.colorNamePairs = [(colors.HexColor("#c53030"), "AS FOUND"), (colors.HexColor("#276749"), "AS LEFT")]
    dr.add(lg)
    section("% Span Error Chart", dr, gap=8)

    para = Paragraph(esc(dash(fields["comments"])).replace("\n", "<br/>"), note_s)
    text_h = para.wrap(content_w - 6 * mm, 1000 * mm)[1]
    comments = Table([[para]], colWidths=[content_w], rowHeights=[max(18 * mm, text_h + 6 * mm)], hAlign="LEFT")
    comments.setStyle(TableStyle(grid + [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
                                         ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm)]))
    section("Comments", comments, gap=8)

    sign = Table([["Name", dash(fields["signName"]), "Date", dash(fields["signDate"])]],
                 colWidths=[25 * mm, 60 * mm, 25 * mm, 60 * mm], hAlign="LEFT")
    sign.setStyle(TableStyle(grid + [("FONT", (0, 0), (-1, -1), "Helvetica", 9),
                                     ("FONT", (0, 0), (0, 0), "Helvetica-Bold", 9), ("FONT", (2, 0), (2, 0), "Helvetica-Bold", 9),
                                     ("TEXTCOLOR", (0, 0), (0, 0), rgb(LABEL_GREY)), ("TEXTCOLOR", (2, 0), (2, 0), rgb(LABEL_GREY))]))
    sig_cell = ""
    if fields.get("signature"):
        try:
            img = Image(fields["signature"])
            ratio = min(60 * mm / img.imageWidth, 24 * mm / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * ratio, img.imageHeight * ratio
            img.hAlign = "LEFT"
            sig_cell = img
        except Exception:
            sig_cell = ""
    sig = Table([["Signature", sig_cell]], colWidths=[30 * mm, 140 * mm], rowHeights=[28 * mm], hAlign="LEFT")
    sig.setStyle(TableStyle(grid + [("FONT", (0, 0), (0, 0), "Helvetica-Bold", 9),
                                    ("TEXTCOLOR", (0, 0), (0, 0), rgb(LABEL_GREY))]))
    story.append(KeepTogether([Paragraph("Sign Off", head_s), sign, Spacer(1, 4 * mm), sig]))

    stamp = generated.strftime("%d/%m/%Y, %I:%M:%S %p").replace(" 0", " ")

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            n = len(self._pages)
            for st in self._pages:
                self.__dict__.update(st)
                self.setFont("Helvetica", 8)
                self.setFillColorRGB(120 / 255, 120 / 255, 120 / 255)
                self.drawCentredString(page_w / 2, 7 * mm, f"Page {self._pageNumber} of {n}  •  Generated {stamp}")
                super().showPage()
            super().save()

    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=10 * mm,
                            bottomMargin=14 * mm, title=f"Calibration Certificate {fields['certNo']}",
                            author=fields.get("technician") or "", subject=fields.get("instrumentId") or "")
    doc.build(story, canvasmaker=NumberedCanvas)
