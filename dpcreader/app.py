"""DPC Reader - desktop window (tkinter)."""
from __future__ import annotations

import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__, session as S, simulator, store

DEMO = "Demo (simulated calibrator)"
BAUDS = ("9600", "19200", "38400")
ABOUT = (f"DPC Reader {__version__}\n\n"
         "Reads the procedure and results memory of Fluke 74x / 75x documenting "
         "process calibrators over a serial (COM) port and shows what is stored.\n\n"
         "This is an independent tool. It is not made or supported by Fluke.\n\n"
         "IMPORTANT: it has been tested against a simulator and the original link "
         "library, but NOT yet against a real calibrator. Treat readings from a real "
         "device as unverified until you have checked them against the instrument.\n\n"
         "It only reads. It never writes to or erases the calibrator.")


class App(tk.Tk):
    def __init__(self, db_path=None):
        super().__init__()
        self.title("DPC Reader")
        self.geometry("1180x700")
        self.minsize(900, 520)
        self.store = store.Store(db_path)
        self.snap = None
        self.q = queue.Queue()
        self.busy = False
        self._nodes = {}
        self._build()
        self._refresh_ports()
        self._refresh_history()
        self.after(80, self._pump)

    # ------------------------------------------------------------ layout
    def _build(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        menu = tk.Menu(self)
        m = tk.Menu(menu, tearoff=0)
        m.add_command(label="Export readings to CSV...", command=self.export_csv)
        m.add_command(label="Export everything to JSON...", command=self.export_json)
        m.add_separator()
        m.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=m)
        h = tk.Menu(menu, tearoff=0)
        h.add_command(label="About DPC Reader", command=lambda: messagebox.showinfo("About DPC Reader", ABOUT))
        menu.add_cascade(label="Help", menu=h)
        self.config(menu=menu)

        bar = ttk.Frame(self, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Connect to:").pack(side="left")
        self.port = ttk.Combobox(bar, width=44, state="readonly")
        self.port.pack(side="left", padx=(6, 4))
        ttk.Button(bar, text="Refresh", width=8, command=self._refresh_ports).pack(side="left")
        ttk.Label(bar, text="Baud:").pack(side="left", padx=(14, 4))
        self.baud = ttk.Combobox(bar, width=7, state="readonly", values=BAUDS)
        self.baud.set(BAUDS[0])
        self.baud.pack(side="left")
        self.read_btn = ttk.Button(bar, text="Read calibrator", command=self.read)
        self.read_btn.pack(side="left", padx=14)
        ttk.Button(bar, text="Export CSV", command=self.export_csv).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        left = ttk.Frame(body)
        ttk.Label(left, text="Saved reads").pack(anchor="w")
        self.hist = ttk.Treeview(left, columns=("when", "src"), show="headings", height=6, selectmode="browse")
        self.hist.heading("when", text="Date / time")
        self.hist.heading("src", text="Source")
        self.hist.column("when", width=130)
        self.hist.column("src", width=120)
        self.hist.pack(fill="x")
        self.hist.bind("<<TreeviewSelect>>", self._on_history)
        ttk.Button(left, text="Delete selected read", command=self._delete_history).pack(anchor="w", pady=(4, 10))
        ttk.Label(left, text="Calibrator memory").pack(anchor="w")
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree)
        body.add(left, weight=1)

        right = ttk.Frame(body)
        self.header = ttk.Label(right, text="Read a calibrator, or pick a saved read.", font=("Segoe UI", 11, "bold"))
        self.header.pack(anchor="w", pady=(0, 4))
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)
        f1 = ttk.Frame(self.tabs)
        self.table = ttk.Treeview(f1, show="headings")
        sy = ttk.Scrollbar(f1, orient="vertical", command=self.table.yview)
        sx = ttk.Scrollbar(f1, orient="horizontal", command=self.table.xview)
        self.table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side="right", fill="y")
        sx.pack(side="bottom", fill="x")
        self.table.pack(fill="both", expand=True)
        self.tabs.add(f1, text="Readings")
        f2 = ttk.Frame(self.tabs)
        self.detail = tk.Text(f2, wrap="none", font=("Consolas", 10), state="disabled")
        dy = ttk.Scrollbar(f2, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=dy.set)
        dy.pack(side="right", fill="y")
        self.detail.pack(fill="both", expand=True)
        self.tabs.add(f2, text="Record details")
        body.add(right, weight=3)

        foot = ttk.Frame(self, padding=(10, 0, 10, 8))
        foot.pack(fill="x")
        self.status = ttk.Label(foot, text="Ready.")
        self.status.pack(side="left")
        self.prog = ttk.Progressbar(foot, length=220, maximum=1.0)
        self.prog.pack(side="right")

    # ------------------------------------------------------------ ports / history
    def _refresh_ports(self):
        ports = S.list_ports()
        self.port["values"] = ports + [DEMO]
        if self.port.get() not in self.port["values"]:
            self.port.set(ports[0] if ports else DEMO)

    def _refresh_history(self, select=None):
        self.hist.delete(*self.hist.get_children())
        for uid, taken, source, model, n in self.store.list():
            self.hist.insert("", "end", iid=str(uid), values=(taken.replace("T", "  "), f"{model} / {source}"))
        if select is not None and self.hist.exists(str(select)):
            self.hist.selection_set(str(select))

    def _on_history(self, _=None):
        sel = self.hist.selection()
        if sel and not self.busy:
            self.show(self.store.load(int(sel[0])))

    def _delete_history(self):
        sel = self.hist.selection()
        if sel and messagebox.askyesno("Delete read", "Delete this saved read from this computer?"):
            self.store.delete(int(sel[0]))
            self._refresh_history()

    # ------------------------------------------------------------ reading
    def read(self):
        if self.busy:
            return
        choice, baud = self.port.get(), int(self.baud.get())
        self.busy = True
        self.read_btn.state(["disabled"])
        threading.Thread(target=self._worker, args=(choice, baud), daemon=True).start()

    def _worker(self, choice, baud):
        cal = None
        try:
            if choice == DEMO:
                cal, source = simulator.open_demo(), "Demo"
            else:
                dev = choice.split(" - ")[0]
                self.q.put(("progress", f"Opening {dev} at {baud} baud", 0.0))
                cal, source = S.open_port(dev, baud), dev
            snap = S.read_all(cal, source, lambda m, f: self.q.put(("progress", m, f)))
            self.q.put(("done", snap))
        except Exception as e:
            self.q.put(("error", f"{type(e).__name__}: {e}"))
        finally:
            try:
                if cal is not None:
                    cal.link.port.close()
            except Exception:
                pass

    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    self.status.config(text=msg[1])
                    self.prog["value"] = msg[2]
                elif msg[0] == "done":
                    self.busy = False
                    self.read_btn.state(["!disabled"])
                    uid = self.store.save(msg[1])
                    self._refresh_history(select=uid)
                    self.show(msg[1])
                    self.status.config(text="Read complete and saved.")
                elif msg[0] == "error":
                    self.busy = False
                    self.read_btn.state(["!disabled"])
                    self.prog["value"] = 0
                    self.status.config(text="Read failed.")
                    messagebox.showerror("Could not read the calibrator",
                                         msg[1] + "\n\nCheck the cable, the COM port and the baud rate "
                                         "(it must match the calibrator's setting).")
        except queue.Empty:
            pass
        self.after(80, self._pump)

    # ------------------------------------------------------------ display
    def show(self, snap):
        self.snap = snap
        self._nodes = {}
        self.tree.delete(*self.tree.get_children())
        first = None
        for w, groups in snap["lists"].items():
            top = self.tree.insert("", "end", text=f"{S.LISTS.get(w, w)} ({len(groups)})", open=True)
            for g in groups:
                info = S.group_summary(g)
                label = info["name"] or f"Group {g['index']}"
                gid = self.tree.insert(top, "end", text=label)
                self._nodes[gid] = ("group", g)
                if w == "r" and first is None:
                    first = gid
                for a in g["atoms"]:
                    kind = (a.get("decoded") or {}).get("kind", "?").replace("_", " ")
                    aid = self.tree.insert(gid, "end", text=f"{a['index']}: {kind}")
                    self._nodes[aid] = ("atom", g, a)
        dev = snap["device"]
        self.header.config(text=f"{dev['model']}  {' '.join(dev['info'])}   -   read {snap['when'].replace('T', ' ')}"
                                + ("   -   DEMO DATA" if snap["source"] == "Demo" else ""))
        if first:
            self.tree.selection_set(first)
            self.tree.see(first)

    def _on_tree(self, _=None):
        sel = self.tree.selection()
        node = self._nodes.get(sel[0]) if sel else None
        if not node:
            return
        group = node[1]
        self._fill_table(S.readings(self.snap, group))
        if node[0] == "atom":
            self._set_detail(self._atom_text(node[2]))
            self.tabs.select(1)
        else:
            self._set_detail(self._group_text(group))
            self.tabs.select(0)

    def _fill_table(self, t):
        self.table.delete(*self.table.get_children())
        cols = t["columns"] if t["rows"] else ["(no test-point readings in this group)"]
        self.table["columns"] = cols
        for c in cols:
            self.table.heading(c, text=c)
            self.table.column(c, width=90 if c in ("Result set", "Point") else 150, anchor="center", stretch=False)
        for r in t["rows"]:
            self.table.insert("", "end", values=r)

    def _group_text(self, g):
        info = S.group_summary(g)
        t = g.get("time") or {}
        lines = [f"Task:    {info['name']}", f"Tag:     {info['tag']}", f"Serial:  {info['serial']}",
                 f"Stored:  {t.get('year', '')}-{t.get('month', 0):02d}-{t.get('day', 0):02d} "
                 f"{t.get('hour', 0):02d}:{t.get('minute', 0):02d}", f"Records: {len(g['atoms'])}", "",
                 "Select a record on the left to see its decoded contents."]
        return "\n".join(lines)

    def _atom_text(self, a):
        d = dict(a.get("decoded") or {})
        out = [f"Record {a['index']}   type {a['type']} ({d.get('kind', '?')})   {a['size']} bytes", ""]
        if d.get("kind") == "state":
            out.append("Values:")
            for v in S.state_values(self.snap, d):
                out.append(f"  {v['name']:<28} {S._fmt(v['value'])} {v['unit']}")
            out.append("")
        out.append("Decoded:")
        out.append(json.dumps(d, indent=2, default=str))
        raw = (a.get("raw") or {}).get("hex", "")
        out += ["", "Raw bytes:", " ".join(raw[i:i + 2] for i in range(0, len(raw), 2))]
        return "\n".join(out)

    def _set_detail(self, text):
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")

    # ------------------------------------------------------------ export
    def _need_snap(self):
        if self.snap is None:
            messagebox.showinfo("Nothing to export", "Read a calibrator or pick a saved read first.")
            return False
        return True

    def export_csv(self):
        if not self._need_snap():
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="calibrator-readings.csv")
        if path:
            n = store.export_csv(self.snap, path)
            self.status.config(text=f"Exported {n} readings to {path}")

    def export_json(self):
        if not self._need_snap():
            return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")],
                                            initialfile="calibrator-memory.json")
        if path:
            store.export_json(self.snap, path)
            self.status.config(text=f"Exported to {path}")


def selftest(shot=None) -> int:
    """Build the window, run a demo read through the real UI path, check what is shown, exit."""
    import os, tempfile, time
    app = App(db_path=os.path.join(tempfile.mkdtemp(), "selftest.db"))
    app.port.set(DEMO)
    app.read()
    t0 = time.time()
    while (app.busy or app.snap is None) and time.time() - t0 < 20:
        app.update()
        time.sleep(0.02)
    app.update()
    rows = [app.table.item(i, "values") for i in app.table.get_children()]
    ok = (app.snap is not None and len(rows) == 10 and rows[0][2] == "4.021 mA"
          and len(app.hist.get_children()) == 1 and "DEMO DATA" in app.header.cget("text"))
    if shot:
        try:
            from PIL import ImageGrab
            app.lift(); app.attributes("-topmost", True); app.update(); time.sleep(0.4); app.update()
            x, y = app.winfo_rootx(), app.winfo_rooty()
            ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())).save(shot)
        except Exception as e:
            print("screenshot skipped:", e)
    print("SELFTEST", "PASS" if ok else "FAIL", "rows=%d" % len(rows), rows[:1])
    app.destroy()
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        shot = sys.argv[sys.argv.index("--shot") + 1] if "--shot" in sys.argv else None
        sys.exit(selftest(shot))
    App().mainloop()


if __name__ == "__main__":
    main()
