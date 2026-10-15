# Original HP 48GX mode

Open **Calculator → Original HP 48GX (ROM)** in the desktop application.
This window runs an original HP 48 ROM on the x48ng Saturn processor core.
Supported images are GX revisions K, L, M, P and R, and SX revision J. Each
profile has its own ROM, memory, cards, editor drafts and reminders.
Python and PySide6 provide the window, keyboard, file transfer and saved sessions.
The enhanced Python workspace keeps its own stack and exact symbolic arithmetic.

## Setup

Choose **Original calculator → Download ROM revision…**, or select a local
supported ROM/raw ZIP. Downloads come from HPcalc's
[emulator archive](https://www.hpcalc.org/hp48/pc/emulators/) and are checked
against pinned SHA-256 digests. ROMs are never included in app packages.

Standalone desktop packages include the compiled core, Python and Qt; they need
no compiler or Python installation. Source checkouts require a C compiler
(Command Line Tools on macOS, GCC/Clang on Linux, MinGW GCC on Windows).
Use **Open another ROM profile…** and a separate folder when changing models or
revisions. The app rejects restoring a checkpoint against a different ROM.

For a local development profile:

```sh
python -m hp48g.rom_setup --directory .rom --download-rom
python -m hp48g --rom --rom-directory .rom
```

On first boot, press **ON** if the screen is blank, then **F (NO)** at the ROM's “Try To Recover Memory?” prompt.
A new GX profile has 128 KB main RAM; SX has 32 KB. Both begin with two
virtual 128 KB RAM cards. Memory cards can be changed through Tools.

## Using the calculator

A–F are the six LCD menu keys. You can also click the corresponding labels
along the bottom of the LCD (such as VECTR, MATR, LIST, HYP, REAL and BASE).
This works with each new menu as its labels change. The other buttons send the original physical key
presses and releases, including left shift, right shift and alpha. ON cancels.
The text editor accepts Unicode HP characters, including « », →, ∫, π and √,
and HP ASCII transfer escapes such as `\<<`, `\>>` and `\->`.
Return to the normal stack view before transferring objects or running text;
use ON to cancel unfinished input and turn shift/alpha off. **Run text** sends the text to the ROM's own STR→ parser; use original HP syntax.
For example:

```text
CLEAR 0 1 10 FOR i i + NEXT
```

The result is 55. To store a program:

```text
« DUP * » 'SQUARE' STO
```

**Import object** accepts HPHP48 binary files and places the object on level 1.
**Export level 1** saves the native object in that format. Libraries and native
programs remain original HP objects; install/evaluate them with the normal HP
commands. No translation to Python is involved. Source files use UTF-8.

**Save memory**, automatic recovery points, and closing the window checkpoint CPU, RAM and cards together,
using an atomic replacement of `calculator.hp48state` in the profile directory.
Only one window may own a profile. The HP stack, directories, flags and libraries
are independent of the enhanced workspace JSON file. Keep a copy of the
checkpoint for backups. The backup tool saves the current state and safely
restarts the calculator when restoring a snapshot.

## Desktop tools

The **Tools** menu adds these windows without changing the original calculator keyboard:

* **Backups and restore**: create named memory snapshots, import/export them,
  and restore a selected snapshot. Restoration first saves a “Before restore”
  backup and then restarts the core. Automatic recovery points are saved every
  minute when no desktop transfer is in progress; the newest ten are retained.
  Named snapshots are retained indefinitely. Invalid backups are rejected before
  touching the current calculator. Snapshots include CPU, stack, variables,
  flags and cards, but source text has separate draft/file storage.
* **Program editor**: open/save UTF-8 source, syntax highlighting, check syntax
  with the ROM without executing the program, add a program to the stack, or run
  it. Debug on LCD opens PRG RUN and invokes DBUG; Step uses SST, and Continue
  resumes the program. Use the LCD’s SST↓ button to step into a subprogram.
  Stop interrupts execution and clears halted programs. **Source debugger**
  adds line breakpoints, source highlighting, Step/Continue/Pause, global-name
  watches, captured local variables, a stack view, source scopes and raw RPL
  return addresses. It creates a backup before starting. It executes instrumented
  UserRPL with temporary HALT markers that the host consumes before continuing;
  it does not run the program in Python. Nested program literals and loop/local
  scopes are mapped. Calls into existing stored programs are stepped over.
  Instrumentation changes execution timing and debugger-related state: use the
  original LCD debugger for self-modifying, timing-sensitive, library or native
  programs. Raw return addresses are not a symbolic machine-code call stack.
  Editor drafts are saved
  automatically. Replacing a draft from a file or memory keeps a source recovery
  copy (newest ten) in the profile’s `source-recovery` folder.
* **Memory browser**: inspect the current directory, object types/sizes, free
  memory, attached libraries and ports 0–2. Navigate/create directories, view or
  edit source, recall objects, store level 1, rename and delete variables. Library
  controls install the library on level 1 into a port and attach/detach library
  numbers. Storing, installing or deleting creates a recovery backup. Inspection
  preserves the user stack. New names use letters, digits and underscores.
* **Memory cards**: create, mount, export, resize and eject packed card images.
  Changes make a recovery backup and restart the calculator. Port 1 supports
  32/128 KB; GX port 2 supports powers of two from 128 KB to 4 MB; SX port 2
  supports 32/128 KB. Used cards cannot be shrunk: export and replace them with
  a blank card instead. A card merged into system RAM must first be made
  independent with the button provided; a failed FREE leaves the card in place.
* **Graph tools**: enter multiple expressions separated by semicolons; select
  FUNCTION, POLAR, PARAMETRIC, TRUTH, CONIC, DIFFEQ or SLOPEFIELD and the
  independent variable. These are original ROM plot types, so they require the
  corresponding HP equation and PPAR parameters. Set numeric axis bounds, drag
  to pan, scroll to zoom, or click for coordinates. Function analysis provides
  trace, root, intersection, extremum classification and definite integral.
  Roots/extrema use the two entered guesses and the ROM solver, so convergence
  can be outside the displayed interval; this is not an exhaustive root search.
  Analysis restores the independent variable and preserves the user's stack.
  Loading the current PICT also loads its expressions, type, variable and bounds.
  Export/copy PNG images. Adding expressions preserves the numeric bounds.
  Return from interactive calculator screens to the normal stack before using
  these desktop tools.
* **Background alarms and reminders**: optionally keep the ROM running in the
  menu bar/system tray when its window closes. Open it from the tray; **Save and
  quit** actually stops it. ROM alarms continue to execute their original actions
  while the background process is running. Persistent desktop reminders are
  separate from ROM alarm objects; they notify and sound a tone without running
  RPL. Overdue reminders are delivered after resume or the next launch, once.
  Reminders can be snoozed or cancelled. **Start at login** is opt-in and registers
  only this calculator profile.
* **Wake computer…**: for a selected desktop reminder, register an OS wake request.
  macOS uses a scoped launch agent plus a `pmset` wake event (administrator dialog);
  Windows uses a one-time Task Scheduler task with WakeToRun and an interactive
  login; Linux uses a transient systemd timer with WakeSystem through PolicyKit.
  Cancel a scheduled wake before changing/snoozing its time. No wake requests or
  login items are installed merely by opening the app. Hardware/firmware and OS
  power policies can prevent waking; notifications also depend on OS settings.
  Logging out stops a user session; Linux transient wake timers do not survive
  reboot. The reminder journal remains available for delivery at the next launch.
* **Emulator speed**: maximum throughput or a selected instruction-per-second
  limit. Pacing reduces host-dependent execution speed but is not cycle accuracy.

The **Clipboard** menu copies level 1 both as ROM-formatted text and as a native
HP object. Paste copied HP object restores that exact object to the stack. Other
clipboard text is pasted into the editor for review and is not automatically
executed. Copy LCD image captures the 131×64 display.

The **Sound** menu enables/mutes output, changes volume and plays a test tone.
ROM `BEEP` and alarm programs use their requested pitch/duration; the ROM’s -56
sound flag is respected as well. ON stops current playback. Alarms require the
ROM process to remain running, including in optional background mode. Desktop
reminders can request OS wake separately; ROM alarm objects are not automatically
converted to OS timers. Sound needs an audio output device. Custom machine-code
speaker transitions are streamed as PCM; their timing uses the selected
instruction rate (500,000 instructions/second in maximum-speed mode) and is an
approximation rather than measured Saturn cycles. ROM BEEP uses its requested
frequency and duration directly.

## Compatibility boundary

Original mode executes the ROM's command implementations, UserRPL, System RPL,
Saturn instructions, object types, numeric rounding, system flags, menus,
equation library and original plotting/display code. The enhanced workspace's
command-name inventory does not limit this mode.

This supports the six explicitly listed ROM images, not every HP calculator model.
Timing is host-dependent, and the integration is not certified cycle-accurate.
Physical serial cables and infrared printers/links are not
connected by this bridge. Their ROM commands exist, but operations that require
those devices cannot complete as on connected hardware. Use binary file transfer
for local programs and data. The process bridge has POSIX and Windows pipe backends. The Windows core has
been cross-compiled; native Windows runtime validation is delegated to the
Windows CI job and must pass before a Windows release is declared verified.
A System RPL or machine-code program can corrupt guest calculator memory just as
on the hardware; checkpoints are the recovery mechanism.

## Verification and licenses

Run the complete test suite with a local revision R ROM:

```sh
HP48G_TEST_ROM=.rom/rom QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Without that environment variable, native conformance tests are explicitly
skipped; codec, checkpoint and existing workspace tests still run. Native tests
cover representative arithmetic, units, loops, flags, arrays, program transfer,
graphics objects, persistent memory, source-debugger loops/local scopes, graph
analysis, card changes and cross-ROM checkpoint reloads. They do not cover every
command/argument combination. Run `python scripts/download_test_roms.py` to
fetch all six pinned test images before running the suite. Without the extra
ROM files, the additional-model cases explicitly skip.

The separate Saturn core is GPL software. See
[upstream provenance](../hp48g/native/x48ng/UPSTREAM.md), its LICENSE and AUTHORS.
The ROM remains HP's software and is downloaded separately.

## Building desktop packages

```sh
python -m pip install -e ".[dev,packaging]"
python scripts/build_desktop.py --archive
```

Build on each target OS. Outputs are a macOS application/DMG, a portable Windows
ZIP, or a Linux tarball under `dist/`. Packages include native core source and
license, Python dependency notices, and the compiled core, but no HP ROM.
The Mac build is locally/ad-hoc signed, not Apple-notarized. Windows archives
are not Authenticode-signed. Signing for public distribution requires the
maintainer's credentials. `.github/workflows/desktop.yml` builds and tests on
all three operating systems when manually dispatched or when a version tag is
pushed; it uploads build artifacts without publishing a release.

For local automation, `python -m hp48g --rom --quit-rom --rom-directory PATH`
requests a graceful save and exit from an instance of this version. Reopening an
already-running profile shows its existing window instead of opening another
emulator. Background wake launches do not steal focus.
