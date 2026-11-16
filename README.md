# DPC Reader

A small Windows app that reads the procedure and results memory of Fluke 74x / 75x
documenting process calibrators over a serial (COM) port, shows what is stored,
keeps a local history of reads, and exports readings to CSV.

Independent project. Not made, endorsed or supported by Fluke.

## Status - read this first

* **Not yet tested on a real calibrator.** The link protocol and memory decoder
  were checked against a simulator and against the original link library, but
  no real 753/754 has been connected. Treat real-device readings as unverified.
* **Read-only.** The app never writes to or erases the calibrator.
* The built-in **Demo (simulated calibrator)** uses invented names and readings.

## Install

Run `DPCReader-0.1.0-setup.msi`. It installs for the current user only (no
administrator rights needed), adds Start menu and desktop shortcuts, and can be
removed from *Settings > Apps*. Saved reads live in `%LOCALAPPDATA%\DPCReader`.

## Use

1. Connect the calibrator (the 753/754 USB cable appears as a COM port once
   Fluke's USB driver is installed).
2. Pick the COM port and the baud rate set on the calibrator, then **Read calibrator**.
3. Pick a task under *Results* to see its test points; pick a record to see
   everything decoded from it, plus the raw bytes.
4. **Export CSV** saves all readings from the current read.

## Build from source

`.\build.ps1` (needs Python 3.10+ and the .NET SDK). Run from source with
`python run_dpcreader.py`.

## Repository layout

- `dpcreader/` - the app and library (`link.py` serial protocol, `memfmt.py` memory decoder, `maps.py` name tables, `app.py` window)
- `tests/` - run with `python -m unittest discover tests`
- `docs/PROTOCOL.md` - the protocol and memory-format notes
- `tools/validate/` - optional cross-check against the original link library (needs your own copy)
- `installer/` - WiX definition for the MSI

## Licence

MIT. Fluke is a trademark of Fluke Corporation; this project is not affiliated with it.
