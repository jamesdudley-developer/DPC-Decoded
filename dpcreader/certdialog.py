"""'Create certificate' window: pick a calibration from the read, check / fill in the
certificate fields, save the PDF."""
from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import certificate as C, report as R, store

# fields that come from the calibration and are refilled when another calibration is picked
FROM_CAL = ("certNo", "instrumentId", "serialNumber", "calDate", "maxErrorLimit", "sensorType", "unit", "lrv", "urv", "result")
CHOICES = {"result": ("PASSED", "FAILED"), "criticalService": ("No", "Yes")}
WIDE = ("equipDevice", "signature")


def settings_path() -> str:
    return os.path.join(store.data_dir(), "certificate.json")


def load_settings() -> dict:
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(fields: dict):
    try:
        with open(settings_path(), "w", encoding="utf-8") as f:
            json.dump({k: fields.get(k, "") for k in C.REMEMBER}, f, indent=1)
    except Exception:
        pass


def calibrations(snapshot: dict):
    """[(label, calibration, group)] for every calibration in the read."""
    out = []
    for g in snapshot.get("lists", {}).get("r", []):
        cal = R.calibration(snapshot, g)
        if cal:
            kinds = " + ".join(r["kind"] or "result" for r in cal["results"])
            out.append((f"{cal['tag'] or g.get('name', '')}  -  {cal['date']} {cal['time']}  ({kinds})", cal, g))
    return out


class CertificateDialog(tk.Toplevel):
    def __init__(self, master, snapshot: dict, group=None, on_done=None):
        super().__init__(master)
        self.title("Create calibration certificate")
        self.transient(master)
        self.resizable(True, True)
        self.snapshot, self.on_done = snapshot, on_done
        self.cals = calibrations(snapshot)
        self.vars = {k: tk.StringVar() for k, _ in C.FIELDS if k != "comments"}
        self._result_touched = False
        self._build()
        start = next((i for i, (_, _, g) in enumerate(self.cals) if g is group), 0)
        self.pick.current(start)
        self._fill(first=True)
        self.grab_set()
        self.focus_set()

    # ------------------------------------------------------------ layout
    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Label(top, text="Calibration:").pack(side="left")
        self.pick = ttk.Combobox(top, state="readonly", width=60, values=[c[0] for c in self.cals])
        self.pick.pack(side="left", padx=6, fill="x", expand=True)
        self.pick.bind("<<ComboboxSelected>>", lambda e: self._fill())
        ttk.Label(outer, text="Fields marked * were filled from the calibrator. Check everything before saving.",
                  foreground="gray").pack(anchor="w", pady=(6, 8))

        form = ttk.Frame(outer)
        form.pack(fill="both", expand=True)
        for c in (1, 3):
            form.columnconfigure(c, weight=1)
        r = c = 0
        for key, label in C.FIELDS:
            if key == "comments":
                continue
            star = " *" if key in FROM_CAL and key != "result" else ""
            if key in WIDE and c:
                r, c = r + 1, 0
            ttk.Label(form, text=label + star).grid(row=r, column=c, sticky="w", padx=(0, 6), pady=2)
            if key in CHOICES:
                w = ttk.Combobox(form, textvariable=self.vars[key], values=CHOICES[key], state="readonly", width=18)
            else:
                w = ttk.Entry(form, textvariable=self.vars[key], width=28)
            span = 3 if key in WIDE else 1
            if key == "signature":
                fr = ttk.Frame(form)
                fr.grid(row=r, column=c + 1, columnspan=3, sticky="we", pady=2)
                ttk.Entry(fr, textvariable=self.vars[key]).pack(side="left", fill="x", expand=True)
                ttk.Button(fr, text="Browse...", command=self._browse_sig).pack(side="left", padx=(4, 0))
                ttk.Button(fr, text="Clear", command=lambda: self.vars["signature"].set("")).pack(side="left", padx=(4, 0))
            else:
                w.grid(row=r, column=c + 1, columnspan=span, sticky="we", pady=2, padx=(0, 12))
            if key in WIDE:
                r, c = r + 1, 0
            else:
                c += 2
                if c > 2:
                    r, c = r + 1, 0
        if c:
            r += 1
        ttk.Label(form, text="Comments").grid(row=r, column=0, sticky="nw", pady=2)
        self.comments = tk.Text(form, height=4, width=60, wrap="word", font=("Segoe UI", 9))
        self.comments.grid(row=r, column=1, columnspan=3, sticky="we", pady=2)

        for k in ("maxErrorLimit", "lrv", "urv"):
            self.vars[k].trace_add("write", lambda *a: self._auto_result())
        self.vars["result"].trace_add("write", lambda *a: setattr(self, "_result_touched", not self._setting))
        self.vars["instrumentId"].trace_add("write", lambda *a: self._auto_cert_no())
        self._setting = False

        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="Save certificate PDF...", command=self.save).pack(side="right", padx=6)

    def _browse_sig(self):
        p = filedialog.askopenfilename(parent=self, title="Signature image",
                                       filetypes=[("Images", "*.png *.jpg *.jpeg"), ("All files", "*.*")])
        if p:
            self.vars["signature"].set(p)

    # ------------------------------------------------------------ data
    @property
    def cal(self):
        return self.cals[self.pick.current()][1]

    def fields(self) -> dict:
        f = {k: v.get().strip() for k, v in self.vars.items()}
        f["comments"] = self.comments.get("1.0", "end").strip()
        return f

    def _set(self, key, value):
        self._setting = True
        try:
            self.vars[key].set(value)
        finally:
            self._setting = False

    def _fill(self, first=False):
        current = {} if first else self.fields()
        d = C.default_fields(self.cal, self.snapshot.get("device", {}), saved=load_settings())
        for k, v in d.items():
            if k == "comments":
                if first:
                    self.comments.delete("1.0", "end")
                    self.comments.insert("1.0", v)
            elif first or k in FROM_CAL:
                self._set(k, v)
            elif not current.get(k):
                self._set(k, v)
        self._result_touched = False

    def _auto_result(self):
        if not self._result_touched and not self._setting:
            self._set("result", C.overall_result(self.cal, self.fields()))

    def _auto_cert_no(self):
        if self._setting:
            return
        no = self.vars["certNo"].get()
        stamp = no.split("-", 1)[0] if "-" in no else ""
        if stamp.isdigit() and len(stamp) == 6:
            self._set("certNo", f"{stamp}-{self.vars['instrumentId'].get().strip()}")

    def save(self):
        f = self.fields()
        if not f["certNo"]:
            messagebox.showwarning("Certificate", "Enter a certificate number.", parent=self)
            return
        if f["signature"] and not os.path.isfile(f["signature"]):
            messagebox.showwarning("Certificate", "The signature image file was not found.", parent=self)
            return
        safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in f["certNo"])
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
                                            initialfile=f"{safe}.pdf", title="Save certificate")
        if not path:
            return
        try:
            C.build_pdf(self.cal, f, path)
        except PermissionError:
            messagebox.showerror("Certificate", "Could not write the file. Is it open in a PDF viewer?", parent=self)
            return
        except Exception as e:
            messagebox.showerror("Certificate", f"Could not create the certificate:\n{type(e).__name__}: {e}", parent=self)
            return
        save_settings(f)
        if self.on_done:
            self.on_done(path)
        if messagebox.askyesno("Certificate saved", f"Saved {os.path.basename(path)}.\n\nOpen it now?", parent=self):
            try:
                os.startfile(path)
            except Exception:
                pass
        self.destroy()
