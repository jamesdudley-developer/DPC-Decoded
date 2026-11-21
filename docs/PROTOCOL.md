# Fluke DPC link protocol (dpclnk3.dll v1.4) — recovered spec

Source: `program files/Fluke/DPCTrack21/dpclnk3.dll`
(SHA-256 `814564a6…397a`), decompiled with Ghidra 12.1.4 via REA
(`decompile-all`, 1611 functions → `re/dpclnk3_decomp/functions/`).
Addresses below are the DLL's virtual addresses, so you can jump straight to
the matching function in your own disassembly.

Legend: **[obs]** read directly from the code · **[inf]** inferred, not yet
confirmed against a real calibrator.

---

## 0. Architecture

```
DPCTR2.exe (Delphi 2010, UI + Access/BDE database + Crystal Reports)
  └─ com.procalv5.dpc.fluke.bpl (Delphi glue)
       └─ dpclnk3.dll  (MSVC C++; exports DPC3* / MEM3* / STA3* / MAP3*)
            ├─ text command layer   "id", "ms", "md p,all", "mu p,0,3" …
            ├─ PKTCOM packet layer  DLE/STX framing, CRC-16/X-25, seq + ACK
            └─ serial port          Win32 CreateFileA/ReadFile/WriteFile
```

The calibrators supported are the Fluke 74x/75x documenting process
calibrators (USB on the 753/754 is a CDC-ACM virtual COM port, VID 0x0F7E
PID 0x9009, see `fluke-753_754-usb.inf`), so everything rides over a COM port.

## 1. Serial port  [obs] `0x1002da7c`, `0x1002dbe4`

| Setting | Value |
|---|---|
| Baud | 9600, 19200 or 38400 only (`DPC3open` rejects anything else with 2006) |
| Format | 8 data bits, no parity, 1 stop bit |
| Flow control | none (DCB only sets `fBinary`) |
| Buffers | `SetupComm(1024, 1024)` |
| Read timeout | `ReadIntervalTimeout = MAXDWORD`, `ReadTotalTimeoutMultiplier = MAXDWORD`, `ReadTotalTimeoutConstant = timeout_ms` (caller-supplied). That means "return as soon as any byte arrives, else wait up to timeout_ms." |

`DPC3open(baud, portName, timeout_ms, retries)` — `retries` (a byte) is the
retry count used by every packet operation.

## 2. Packet framing  [obs] encoder `0x100011cb`, decoder `0x10001512`

```
[DLE DLE DLE]  DLE STX  CTRL  payload…  DLE ETX  CRClo' CRChi'
  ^ only for SYNC and type-4 frames
```

* `DLE = 0x10`, `STX = 0x02`, `ETX = 0x03`.
* **Byte stuffing:** a `0x10` inside the payload is sent as `0x10 0x10`.
  CTRL is never stuffed (no CTRL value contains 0x10).
* Max ~254 bytes per write chunk. Long payloads are flushed in pieces, but they
  stay one logical frame.

### CTRL byte  table at `0x1002f1a8`

| idx | Name (inferred) | CTRL low nibble | carries seq? |
|---|---|---|---|
| 0 | DATA | `0x00` | yes |
| 1 | ACK | `0x01` | yes |
| 2 | SYNC | `0x03` | no (sent with 3 extra leading DLEs) |
| 3 | SYNC_ACK | `0x07` | no |
| 4 | RESET? | `0x0B` | no (sent with 3 extra leading DLEs) |

For seq-carrying types: `CTRL = code | (seq & 3) << 5`.
The receiver matches on `CTRL & 0x0F` and checks bits 5–6 against its own seq.

Decoder result codes: 0–4 = the index above, 5 = buffer overflow,
6 = CRC error, 7 = sequence mismatch, 8 = unknown CTRL.

### CRC  [obs] `0x1000181b`, table `0x1002f200`

**CRC-16/X-25**: reflected poly 0x8408 (0x1021), init 0xFFFF, final XOR 0xFFFF.
The CRC is sent low byte first.

The CRC covers **CTRL + payload bytes as they appear on the wire (stuffed
DLEs count twice) + the trailing `DLE ETX`**. It does not cover the leading
`DLE STX`. The receiver accepts a frame when
`crc_running ^ (lo | hi<<8) == 0xFFFF`.

### Decoder state machine  table `0x1002f1bc` (rows = state; cols = DLE, STX, ETX, other)

```
0 idle      : 1 0 0 0
1 got DLE   : 1 2 0 0
2 got CTRL  : 3 3 3 3        (byte in state 2 = CTRL)
3 payload   : 4 3 3 3
4 DLE in pl : 3 2 5 0        (DLE DLE = literal 0x10; DLE STX = restart; DLE ETX = end)
5 crc lo    : 6 6 6 6
6 crc hi    : (done)
```

## 3. Link layer (PKTCOM)  [obs] `0x1000e941`, `0x1000ec15`, `0x1000eaad`

State is a 2-bit sequence counter shared by both directions. Every DATA↔ACK
exchange advances it by one.

* **Sync** (`0x1000e941`): for up to `retries` attempts: purge the port, send
  SYNC, and wait for a frame. A SYNC_ACK resets seq to 0, and the link is up.
* **Send** (`0x1000ec15`): send DATA(seq). Wait for a reply:
  * ACK with matching seq → seq++, success.
  * DATA / RESET / seq-mismatch → re-sync, then retry.
  * Timeout / CRC error → retry.
  * Gives up after `retries` attempts.
* **Receive** (`0x1000eaad`): wait for DATA(seq) → reply ACK(seq) → seq++.
  RESET or seq mismatch → re-sync and fail. Timeout/CRC → retry.

## 4. Command layer  [obs] `0x1000210e`, `0x1000216e`, `0x100023b7`

Each command is **one DATA frame of ASCII text, no terminator** (max 256 bytes).
The calibrator answers with a series of DATA frames:

```
"0"             status: '0' = OK; anything else = command error
<record> …      zero or more CSV records (or raw binary chunks for mu/mx)
"\x04"          end of response (EOT)
```

CSV fields are split on `,`. Leading spaces and tabs are skipped. A literal
comma inside a field is sent as `|`. The PC applies the same rule in reverse
when it sends display text.

### Known commands (strings at `0x1002f400`–`0x1002f650`)

| Command | Used by | Response / meaning |
|---|---|---|
| `id` | `DPC3open`, `DPC3get7XX`, `DPC3get74X` | 1 record: `model, <40-char field>, <10-char field>` [obs]. Field meaning (model/serial/firmware) [inf] |
| `ed` | `DPC3get7XX`/`get74X` | 1 record, ≥9 fields; field 8 (0-based) → a long (`0x100026ac`) [obs] |
| `ms` | `DPC3memstats`, `DPC3uplStart` | Several records, ≥6 fields. `memstats` sums field 2 → out1 and field 3 → out2 [obs]. `uplStart` reads two records and takes field 5 of each as the procedure and result counts [obs] |
| `cs y,mo,d,h,mi,s,x` | `DPC3setClock` | Set clock. Year is offset by 56 internally [obs] |
| `ps <text>` | progress | Shows text on the calibrator's screen during transfers. `ps ` with empty text clears it [obs] |
| `md p,all` / `md r,all` | `DPC3uplStart` | Directory of **p**rocedures / **r**esults. One record per group, 16 CSV fields (vendor, type, version, alias, size, sys/user flags, date/time…) [obs: field count; inf: names] |
| `mu p,<g>,<a>` / `mu r,<g>,<a>` | `DPC3uplStep` | Upload atom `a` of group `g`. Header record has 8 CSV fields, and field 7 = byte length. Then raw binary DATA frames until that length is reached, then EOT [obs] |
| `mc p` / `mc r` | `DPC3clear` / download | Clear procedure / result memory [obs] |
| `ds` | clear, download | Unknown (issued after `mc p`) [inf: "done/sync"] |
| `mg p,…` / `ma p,…,len` | `DPC3dnlStep` | Download: begin group / allocate atom of `len` bytes [obs strings] |
| `mv …`, `mx …` | `DPC3validate`, download | Validate / transfer atom data [inf] |
| `mp` / `mp <name>` | `DPC3mapStart/Step` | Upload the "map" (enum / text table) directory, then each map [obs] |
| `ot …` | `DPC3mapTextId` | Text-ID lookup [inf] |
| `mf p` | — | Unknown [inf: memory free / format] |

### Return codes (DPC3* API)

`0` ok · `2004` (0x7d4) upload inconsistency · `2006` bad argument ·
`2007` port open failed · `2008` bad response terminator · `2009` command
rejected (status ≠ '0') · `2010` link sync failed · `2011` send failed ·
`2012` receive failed · `2015` not open · `2016` port busy (open returned 2).

## 5. Memory image format  (decoder: `dpcreader/memfmt.py`)

Everything here is **[obs]** from the code unless marked **[inf]**.

**Validated against the original DLL**, in two directions (scripts in `tools/validate/`):

1. *DLL writes, we read* (`gen.ps1`, `check.py`): the DLL builds a task through
   its own `MEM3*`/`STA3*` API and `memfmt.py` decodes the raw atoms. Types
   2, 5, 6, 9, 10 and 12 match byte for byte.
2. *We write, DLL reads* (`build2.py`, `build3.py`, `gen2.ps1`, `gen3.ps1`,
   `check2.py`): atoms hand-built from this spec are written into the DLL and
   read back through its accessors (`MEM3*Info`, `STA3restore`/`STA3get*`).
   Types 3, 4, 8, 14, 17 and 18 are read exactly as `memfmt.py` decodes them,
   including bucket lists, value / int / string / value+range buckets and
   2-byte bucket ids.

Still unconfirmed: types 7, 11, 13, 15 (log buffer) and 16, unit / time /
reference buckets, state diffs against a base atom, and anything about how a
real calibrator *fills in* these records (e.g. which buckets it uses).

### 5.1 Container

* Two memory lists: **p** (procedures / tasks) and **r** (results). Each is a
  list of **groups**, and each group is a list of **atoms**.
* An atom has **no header of its own**. Its signature `(vendor, type, version,
  alias)` lives in the directory, and the type selects the layout (`0x100112a9`
  compares the directory signature with the class's expected one).
* All multi-byte values are **big-endian** (`0x100127d1` byte-swaps on the PC).
* Strings are NUL-terminated (`0x10012a0f`).

### 5.2 Directory records (`md p,all` / `md r,all`)  `0x10003d84`

Group record (16 numbers, then `"name`):
`index, natoms, vendor, type, version, ?, year-2000, month, day, dow, hour, min, sec, alias, sysflags, userflags, "name"`

followed by `natoms` atom records (8 numbers, then `"name`):
`index, vendor, type, version, size, alias, sysflags, userflags, "name"`

The date field order is [inf] from the clock byte layout in 5.4.

### 5.3 Typed values ("quarks")  `0x1001cdb5`, `0x1001ca4a`

One tag byte: low 5 bits = type, high 3 bits = packing.

| Type | Meaning | | Type | Meaning |
|---|---|---|---|---|
| 0 | none | | 11–18 | arrays of f32, f64, i32, u32, i16, u16, i8, u8 |
| 1 | compound (list of values, ends with a tag `0xE0`) | | 19 | string array (u16 count, then strings) |
| 2 / 3 | f32 / f64 | | 20 | nil |
| 4 / 5 | i32 / u32 | | 21 | byte |
| 6 / 7 | i16 / u16 | | | |
| 8 / 9 | i8 / u8 | | | |
| 10 | string | | | |

| Packing (tag & 0xE0) | Meaning |
|---|---|
| `0x00` | full-size value follows |
| `0x20` | value is 0, nothing follows |
| `0x40` | value is 1, nothing follows |
| `0x60` | value fits one byte (signed or unsigned per type) |
| `0x80` | value fits two bytes. For f32 these are the **upper** 16 bits (low 16 are zero) |
| `0xA0` | i8 stored in the low 5 bits (sign-extended) |
| `0xC0` | u8 stored in the low 5 bits |
| `0xE0` | end-of-compound marker |

Numeric arrays are prefixed by a **byte count**: one byte if < 128, else
`0x80|n` followed by `n` big-endian bytes (`0x10012e2b`).

A **QUARK** is an id plus a typed value. The id is one byte, or two bytes with
the top bit set for ids ≥ 128 (`0x1001de72`).

### 5.4 Embedded structs

| Struct | Layout | Function |
|---|---|---|
| Group address | i16 group, i8 memlist (−1 = none) | `0x100106dc` |
| Atom address | i8 memlist (1 = procedures, 2 = results; −2 = null, nothing follows; −1 = no memlist), i16 group, i16 atom | `0x100108b4` |
| Time | 7 bytes: sec, min, hour, day-of-week (0–6), day, month, year−1944 | `0x1002046b`, `0x1002084a` |

### 5.5 Atom types (vendor 1 = Fluke)

Type numbers come from the class constructors (RTTI names recovered into
`vtables.txt`). Field **names** are mostly [inf]; field **types and order** are [obs].

| Type | Class | Layout |
|---|---|---|
| 2 | STATE_SETUP_ATOM | repeated ops until end: u8 op, u16 item, u8 nargs, nargs × QUARK. Ops: 1 = init, 2 = set, 4 = eval. `set` with item 1 and quark id 0 selects a bucket list; with item 0 the quark id is the bucket id and its value is what to set |
| 3 | STATE_BUCKET_ATOM | u8 version, u8 colormap, u8 redefines, atom address (base state this one is a diff of), u8, then bucket stream (5.6) |
| 4 | STRATEGY_SUMMARY | atom addr (state), atom addr (strategy), u8, u8, u32, u8, u16 array: for each test point, the atom index (in the same group) of that step's result atom |
| 5 | PROC_STRAT_REF | atom addr, atom addr, u8, u8, u32, string, string |
| 6 | PROMPT_DEFINITION | string prompt, u8 input kind (0 ordinary, 1 alphanumeric, 2 numeric, 3 boolean), u8, u8 font (value from the `font` map), string |
| 7 | PROMPT | atom addr (definition) |
| 8 | PROMPT_RESULT | string, atom addr, typed value (the answer) |
| 9 | TASK_START | string, u16, string |
| 10 | STRATEGY | string name, u16 array of test points (fraction of span × 10000; 0 ≤ fraction < 3) |
| 11 | INSTRUMENT_TAG | 3 strings (tag ID and two more identifiers) |
| 12 | USER_LIST_DEFN | string name, u16 count, count × string |
| 13 | USER_LIST_REF | atom addr, atom addr, u8 |
| 14 | USER_LIST_RESULT | string, atom addr, u8, u16 array (selected items) |
| 15 | STATE_LOG_BUFFER | time start, time stop, u32, u32, u32, f32 array (logged values), u8 array, u16 count, count × range records (not decoded) |
| 16 | SWITCH_TEST | 3 strings, atom addr |
| 17 | SWITCH_TEST_RESULT | atom addr, atom addr |
| 18 | TASK_RESULT_REF | group address |

### 5.6 State buckets (where measurements and settings live)  `0x100290fb`, `0x1002a448`, `0x100278ac`

A calibrator "state" is a set of numbered **buckets** grouped into lists.

* `QUARK(id 0x7FFF, value = list id)` starts a bucket list.
* Each bucket is `QUARK(id = bucket id, compound)`. The compound's first
  element is a u8 **kind**, and the remaining elements are the bucket's fields:

  | Kind | Bucket | Fields |
  |---|---|---|
  | 0 | value | f32 |
  | 1 | value + range | f32, then range fields |
  | 2 | integer (also text ids and mapped enums) | int |
  | 3 | unit | |
  | 4 | time | |
  | 5 | string | |
  | 6 | reference ("@" buckets: points at a bucket in another list) | u8 flags, u16 bucket id, optional u16 list id, optional f32 |

* A bucket id with a non-compound value is an "antiquark": the bucket is
  deleted relative to the base state.
* A state atom can be a **diff** against a base atom (the address in its
  header), so a full state is the base chain applied in order.

### 5.7 What is still missing

* **Range records in the log buffer** (same format as below, but outside a bucket).
* The *meaning* of the range numbers (see 5.8).
* **Applying state diffs** to build the full as-found / as-left picture.
* The **download** direction (writing procedures to the calibrator).

### 5.8 Range record (after the value in a value+range bucket)  `0x10028784`, `0x100284b2`

Layout confirmed through `STA3getRange`; what each number means is not known yet.

1. u8 array header, 3 or 4 bytes: `b0` = flag (bit 7), 4-bit field (bits 3-6),
   2-bit mode (bits 1-2); `b1` = two 4-bit fields; `b2` = signed byte; optional `b3`.
2. If mode = 0: u8 count (3 or 4), then that many f32 (`f0`, `f1`, `f2`, and
   `f3`, which equals `f0` when only 3 are stored).
3. Unit: a string (custom unit name), or a u8 unit id, or an i8 holding
   unit id − 16 (followed by a name string when the id is 1).

A 1-byte header instead means "same range as one stored earlier" and is
followed by three ints: group, atom, position.

## 6. Maps: names for the numbers  (decoder: `dpcreader/maps.py`)

Maps are plain text tables held by the calibrator. **[obs]** from
`DPC3mapStart` `0x100057d7`, `DPC3mapStep` `0x10005c93`, schema builder
`0x10023ff4`. The actual map contents only exist on a calibrator, so none are
known yet.

| Command | Response records |
|---|---|
| `mp` | one per map: `name,count,checksum`. The PC skips maps whose count and checksum match its cache |
| `mp <name>` | one per entry: `value,text[,extra]` (split at the first two commas only) |
| `ot <id>[,arg]` | text-id lookup: status `0` (or `2` = bad arg), a count, then that many strings |

How state buckets get their names:

* Map **`sbucket`**: bucket-list id -> list name. The list named `root` is the top of the tree.
* Map **`sbucket/<list name>`**: bucket id -> bucket name, with `extra` = a type spec:

  | Spec | Bucket |
  |---|---|
  | `V` | float value |
  | `VR` | float value with range |
  | `I` | integer |
  | `txtid` | integer that is a text id (resolve with `ot`) |
  | `U` | unit |
  | `T` | time |
  | `ST[n]` | string of up to n bytes |
  | `<map name>` | integer enum, translated through that map |
  | `V@` `VR@` `I@` `U@` `T@` `ST@` | reference to a bucket of that type in another list |

  Optional suffixes, in this order: `,exp` (exported), `,ro` (read-only), `,unr`, `,su` (meaning of the last two [inf] unknown).

## 7. Download: writing procedures to the calibrator  (`dpcreader/link.py` `Calibrator.download`)

Confirmed from `DPC3dnlStart` `0x10002e9d` and `DPC3dnlStep` `0x10003353`.
The sequence to replace procedure memory:

1. `ds` — start download. The calibrator drops the link; the PC waits ~1 s
   (`Sleep`, `0x10002f98`) and re-syncs.
2. `mc p` — clear procedure memory.
3. For each group: `mg p,<vendor>,<type>,<version>,<alias>,<sysflags>,<userflags>`.
4. For each atom: `ma p,<same 6 fields>,<byte length>`. The calibrator replies
   with the atom index it allocated (must match).
5. The atom bytes are sent in chunks of **0x6F (111)** bytes, each as a binary
   command: `"mbp"` + u16 chunk length + u32 group + u32 atom + u32 offset +
   the chunk (all big-endian). This is the only command whose arguments are
   binary, not text.
6. `mf p` — finish the group; the calibrator replies with the group index.
7. After the last group: `mc r` — clear results memory.

`mv` (`DPC3validate` `0x10002fb3`) asks the calibrator to check memory:
`mv p` / `mv p,<group>` / `mv p,<group>,<atom>`. Status `0` = OK; status `2`
means a record follows giving `type, group, atom, message` for the first bad
item. Download direction is implemented but **only tested against the
simulator** — it has not been run against the DLL or a device.

## 8. Real bucket names and as-found / as-left

The bucket numbers in section 5.6 get their names from the maps (section 6),
but the **conventions** are visible as string literals in
`com.procalv5.dpc.fluke.bpl` (string literals in that plugin). This is how the
Fluke plugin turns raw buckets into calibration results.

Bucket naming convention (prefix + dotted sub-field):

* Prefix `m…` = **measure** side, `s…` = **source** side.
* `mPrimary` / `sPrimary` — the main reading, `mSecondary`/`sSecondary` the second.
* `mUEV` / `sUEV` — electrical value; `mFS`/`sFS` full scale, `mZero`/`sZero` zero,
  `mUutFS`/`mUutZero` the unit-under-test range.
* Sub-fields accessed by dotted name: `.float` (value), `.unit`, `.FormattedUnit`,
  `.rangemult`, `.rangeprecision`, `.vRange`, `.RangeMax`, `.RangeZero`,
  `.RangeFullScale`, `.RangePolarity`, `.RangeNumDigits`.
* Switch test: `swtSetpoint1/2`, `swtReset1/2`, `swtTrip1/2`, `swtTolerance`,
  `swtMaxDeadband`, `swtMinDeadband`, `swtIsHigh1/2`, `swtIsNC1/2`, `swtNumLimits`.

As-found / as-left is **not a bucket flag** — it is which result atom the bucket
state belongs to. The plugin and database use the labels `As Found Result` /
`As Left Result` (`FOUNDAS` / `LEFTAS`), with set/reset points `AF Set Point`,
`AL Set Point`, `AF Reset Point`, `AL Reset Point`. A task's strategy summary
(atom type 4) points at the result atoms; a calibration typically carries both
an as-found and an as-left state, and the two are compared against the spec.

Enum maps referenced by the plugin (map name : entry id):
`unit.common:N` (engineering units), `tc.common:N` (thermocouple types),
`rtd.common:N` (RTD types), `mode.common`/`mode.fluke`, `unittype.fluke`,
`tripstate.fluke`, `tempstd.common` (IPTS-68 / ITS-90). These are the maps whose
numbers section 6 could not name; a real `mp` upload fills them in.

## 9. Where the original software keeps results

The original desktop application stores uploads in an Access (`.mdb`) database:
one row per calibration event, with per-group and per-test-point detail rows
holding input, output, limits and the as-found / as-left readings, plus tables
for logged data series and upload sessions. That application and its database
are outside the scope of this project.

## 10. Confirmed on a real Fluke 754 (firmware 1.18)

Read over USB on 21 Nov 2026. The 754 enumerates as a standard CDC "USB Serial
Device" (`VID_0F7E&PID_9009`, Windows' own driver) and talks at 9600 baud.
Everything below is [obs] against that device; the decoded results matched the
calibrator's own Results screens.

* **Directory year** is sent as the full year (`2026`), not year − 2000.
* **States are diffs.** Each result state names a base state (atom address); a
  calibration's first state is the base for the others. Apply the chain to get the
  full state. Antiquarks (a bucket id with no compound value) delete a bucket.
* **Shared-value quark.** Bucket id `0` with value `[[id, id, ...], [kind, fields...]]`
  gives the same value to every listed bucket.
* **Alias buckets** (kind 6, spec `VR@`): `[6, mode, target bucket id, (cached value)]`.
  `mPrimary` → `mDamped` (11), `sPrimary` → `sUser` (37), `mUutFS`/`mUutZero` → 28/29,
  `sUutFS`/`sUutZero` → 119/120.
* **Range back-reference.** A value+range bucket whose range header is a single byte
  (`[0], g, a, mark`) reuses a range stored earlier; the unit comes from that bucket
  in the base state.
* **STRATEGY_SUMMARY:** `status` 1 = As Found, 0 = As Left; `srcd` = source settle
  delay in ms (10000 = 10 s, shown as *Delay*); `results` = atom indices of each test
  point's state; `strategy` addresses the procedure-list STRATEGY atom (e.g. "3 ↑").
* **Strategy names** are UTF-8 with private-use glyphs: U+E08C = ↑, U+E08D = ↓.
* **Buckets used for a result** (map `sbucket/root`): `tol` (tolerance %), `error`
  (error % of span, as displayed), `scMode`/`mcMode` (map `mode`), `sRtdType` (map
  `rtd`), `sTcType` (map `tc`), units from map `unit` (5 = Amps, 13 = Celsius ...).
