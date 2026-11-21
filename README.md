# DPC Reader

A small Windows app that reads the procedure and results memory of Fluke 74x / 75x
documenting process calibrators over a serial (COM) port, shows what is stored,
keeps a local history of reads, exports results to CSV in the calibrator's own layout,
and creates PDF calibration certificates.

Independent project. Not made, endorsed or supported by Fluke.

## Status - read this first

* **Checked against one real calibrator.** A Fluke 754 (firmware 1.18) has been read
  over USB, and the decoded results matched what it shows on its own Results screens
  (2W RTD and thermocouple source, 4-20 mA measure). Other models, firmware versions
  and test types (switch tests, pressure, logged data) have not been checked yet, so
  compare a few readings against the instrument before relying on them.
* **Read-only.** The app never writes to or erases the calibrator.
* The built-in **Demo (simulated calibrator)** uses invented names and readings.

## Install

1. Download `DPCReader-<version>-setup.msi` from the
   [latest release](https://github.com/jamesdudley-developer/DPC-Decoded/releases/latest).
2. Run it. It installs for the current user only (no administrator rights needed),
   adds Start menu and desktop shortcuts, and can be removed from *Settings > Apps*.
   Installing a newer version replaces the old one and keeps your saved reads.

**Nothing else to install.** The installer contains everything the app needs
(its own copy of Python, the Microsoft C++ runtime, and the PDF, image and serial
libraries), so the PC does not need Python or an internet connection. The only
requirement is **64-bit Windows 10 or 11**; the installer checks this and stops
with a message on anything older.

**Calibrator connection.** A 753/754 on its USB cable shows up as a standard
Windows "USB Serial Device", which Windows 10/11 sets up by itself (no Fluke
driver needed). The app finds it automatically and picks its COM port; if it
says *No calibrator found*, check the cable and that the calibrator is on, wait
a few seconds, and click **Refresh**.

Saved reads and certificate settings live in `%LOCALAPPDATA%\DPCReader`.

## Use

1. Connect the calibrator with its USB cable and switch it on.
2. Check the COM port (the calibrator is picked automatically) and the baud rate
   set on the calibrator (9600 by default), then **Read calibrator**.
3. Pick a task under *Results* to see its test points; pick a record to see
   everything decoded from it, plus the raw bytes.
4. **Export CSV** saves the calibration results as the calibrator shows them: tag, As Found / As Left, measure and source setup, and Source / Measure / Error % per test point. *File > Export all decoded values* gives every raw value instead.
5. To remove saved reads, select them (Ctrl/Shift-click for several) and click **Delete selected**, press Delete, or right-click. **Delete all...** clears the whole history.
6. **Create certificate** makes a PDF calibration certificate in the same layout as the
   Calibration-Certificate app. Pick the calibration, check the fields (those marked * come
   from the calibrator), fill in the rest, and save. Technician, equipment, signature and
   similar fields are remembered for next time.

## Build from source

`.\build.ps1` (needs Python 3.10+ and the .NET SDK). Run from source with
`python run_dpcreader.py`.

## Repository layout

- `dpcreader/` - the app and library (`link.py` serial protocol, `memfmt.py` memory decoder, `maps.py` name tables,
  `report.py` calibrator-style results, `certificate.py` / `certdialog.py` PDF certificates, `app.py` window)
- `tests/` - run with `python -m unittest discover tests`
- `docs/PROTOCOL.md` - the protocol and memory-format notes
- `tools/validate/` - optional cross-check against the original link library (needs your own copy)
- `installer/` - WiX definition for the MSI

## Licence

MIT. Fluke is a trademark of Fluke Corporation; this project is not affiliated with it.
