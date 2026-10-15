# Saturn core provenance

This directory is a separately compiled GPL emulator executable, controlled by the
Python/Qt application through newline-delimited JSON replies and text requests.
It is not a Python extension and contains no HP ROM image.

Sources: [x48ng](https://codeberg.org/gwh/x48ng), commit
`5792522e335ee0c1b05b9887e61e07a94803047b` (version 1.3.1).
The core, emulator_api, romio and options files are copied from that revision.
See LICENSE (GPL version 2) and AUTHORS. Original x48 source notices allow GPL
version 2 or later; preserve the notices in individual files when distributing.

The temporary-object allocation and stack insertion algorithm in objects.c is
adapted from RPL_CreateTemp/RPL_Push in Droid48's binio.c, copyright 1994 Eddie C.
Dost (GPL-2.0-or-later), at
https://github.com/shagr4th/droid48/tree/26eb2750d1681449f5c1b49bfbbe7fa603c27711.

Local changes:

* bridge.c, objects.c/h and ui4x/src/api.h provide a headless process interface,
  bounded native-object transfer, LCD frames, keyboard events and profile paths.
* SHUTDN exposes idle state, so host transfers do not interrupt active RPL work.
* Fix keyboard index bounds and macOS serial compilation.
* Read the three version bytes that persistence writes, close the RAM probe
  file, and expose card loading for cold starts.
* Fix the 8 Hz timer's seconds scale and repeated elapsed-time accumulation.
  Preserve upstream key-held instruction throttling for ROM key debounce.
* Add resolved host inspection values and a stack-reply transfer operation.
* Observe the revision R makebeep routine and speaker output to emit frequency
  and duration events while respecting ROM sound flags. The OUT bit 11 speaker
  mapping is documented by Droid48 device.c; the 0x017A6 entry and D[A]/C[A]
  register convention were cross-checked against Emu48 Android, commit
  `0e5908bcbcb068019ac5ea7ec1b2f52bbe9eb809`, calculators/patch.48 and
  core/apple.c, at https://github.com/dgis/emu48android. No ROM bytes are patched.
* Release host key state when loading a checkpoint.
* Cast file sizes for portable diagnostic formatting.

Build: `python -m hp48g.rom_setup --directory PATH` compiles the included sources
with the system C compiler. Linux/macOS use nonblocking pipes and Windows uses PeekNamedPipe. A portable
monotonic tick replaces the signal timer; binary memory I/O is used on Windows. No UI toolkit, Lua or SDL is linked.
The matching source and license must accompany redistributed core binaries in
accordance with the GPL. The top-level Python license does not relicense these
sources. Keep this directory available in source and wheel distributions.

Additional desktop bridge changes:

* SX/GX stack-system addresses selected by model, verified against Emu48's
  `core/RPL.c` at the previously cited commit. Merged-card stack ranges accepted.
* Read-only bounded RPL return-stack/data-stack inspection for the source debugger.
* Configurable instruction-rate pacing, not a cycle-accurate timing model.
* PCM output from non-BEEP speaker edges, timed by instruction count; known ROM
  BEEP retains its parameter-based pitch/duration path.
* Explicit disconnected serial stubs; no physical transport is compiled in.
* Portable local-time offset calculation and 64-bit timer absolute values.
* GX K/L/M/P/R and SX J ROM files verified by pinned hashes; checkpoint identity
  prevents restoring a CPU/RAM image under a different ROM revision.

* Native object transfers allow expanded SX/GX heaps; allocation remains bounded by actual free emulated RAM.
