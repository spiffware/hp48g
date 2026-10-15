> This document describes the enhanced Python workspace. For original HP ROM execution, native objects and System RPL, see [Original HP 48GX mode](original-calculator.md).

# UserRPL compatibility

This application now has a structured UserRPL interpreter. It is **not fully HP 48G compatible**. The Python engine does not run HP ROM, System RPL, Saturn machine code, or binary HP libraries.

Open **Programs → UserRPL editor** to edit, open, save, check, or execute UTF-8 `.rpl` text. Both `« … »` and `<< … >>` delimit programs. Opening a text file does not execute it. **Add to stack** creates a program object; `EVAL` runs it. Unfinished editor text is included in workspace saves.

## Supported language and objects

- `IF … THEN … ELSE … END`, with optional ELSE; `IFT`, `IFTE`.
- `CASE … THEN … END … END`, including a default branch.
- `FOR … NEXT/STEP`, `START … NEXT/STEP`, `WHILE … REPEAT … END`, and `DO … UNTIL … END`.
- `→` / `->` local-variable bindings around a program or algebraic expression, nested scopes, named programs, and nested calls.
- `IFERR … THEN … ELSE … END`, string error messages through `ERRM` and `DOERR`.
- Distinct `{ lists }`, `[ vectors ]`, `[[ matrices ]]`, quoted strings, program objects, binary integers, tagged objects, and quoted symbolic objects.
- User flags 1–64; binary bases 2, 8, 10, 16; word sizes 1–64; masked binary arithmetic, logic, shifts, and rotations. Real-number logic returns 0 or 1.
- Directory creation/navigation, parent-directory name lookup, local/global stores, and compound store arithmetic.
- List construction/decomposition, indexing, updates, slicing, sorting, mapping, folding, and sequences. Many arithmetic functions process HP lists element by element; `+` concatenates HP lists. Existing bracketed vectors retain vector arithmetic.
- HP-style equations and added symbolic, polynomial, and matrix commands.

Examples (paste the entire input into the entry field):

| Input | Result |
| --- | --- |
| `0 1 10 FOR i i + NEXT` | `55` |
| `5 → x « x SQ »` | `25` |
| `IF 2 3 < THEN "yes" ELSE "no" END` | `"yes"` |
| `{ 1 2 3 } « SQ » DOLIST` | `{ 1 4 9 }` |
| `{ 1 2 3 4 } « + » STREAM` | `10` |
| `'j^2' 'j' 1 4 1 SEQ` | `{ 1 4 9 16 }` |
| `8 STWS # FFh # 1h + B→R` | `0` |
| `'work' CRDIR work 42 'answer' STO HOME work answer` | `42`, in directory `work` |
| `0 3 'x^2' 'x' ∫` | `9` |
| `'x^3' 'x' ∂` | `3*x^2` |
| `IFERR 1 0 / THEN DROP2 "division failed" END` | `"division failed"` |

Flags, binary modes, directory contents/current path, and the new object types survive background-worker transport, save/reload, and Undo. Graph and solver expressions can resolve inherited scalar variables.

## Important differences

**Programs → HP command compatibility** lists registered HP command names, known unsupported names, and application extensions. This is an implementation inventory, not a certification that every overload of a registered command matches HP behavior. The inventory was cross-checked against the [HP 48G AUR command index](https://www.hpcalc.org/hp48/docs/programming/). The [HP Advanced User’s Reference](https://literature.hpcalc.org/community/hp48g-aur-en.pdf) remains the specification.

Remaining gaps include:

- Hundreds of commands, particularly original plotting/display commands, interactive program input/menus, statistics/finance command suites, hardware I/O, libraries, alarms, and equation libraries. Existing desktop graphing and solver panels do not implement the corresponding HP program commands.
- System flags and their effects, exact HP error numbers, HP character encoding/transfer escapes, binary object files, libraries, ports, System RPL, and machine code.
- Dimensional unit objects, graphics objects, all coordinate modes, and all original object/command argument forms. `DEFINE` currently supports variable equations, not function definitions. `ERRN` reports a generic nonzero error indicator, not an HP error number.
- Original decimal arithmetic, rounding, overflow/underflow, display flags, and symbolic evaluation conventions. SymPy exact arithmetic is retained; algebraic trigonometry captures the selected angle mode when parsed. Binary integers currently display in hexadecimal with an explicit `h` suffix, regardless of the selected input base.
- Original debugger/continuation facilities and ROM timing. No RPL command executes host Python or arbitrary system code.

An unsuccessful entry rolls back the entire submitted sequence, as in the existing desktop application; this differs from the original calculator's incremental stack behavior. `IFERR` can handle errors within an entry. Argument state is restored at a failed command boundary; errors propagating through a program call restore that call's starting state. Infinite loops and nested execution share a 100,000-instruction limit, a 10,000-object stack limit, and the desktop worker's 30-second timeout/cancellation. Resource-limit errors cannot be caught to bypass these limits.

The compatibility tests exercise nested branches and loops, local shadowing, directory inheritance, object types, binary operations, list programs, error handling, malformed structures, rollback/Undo, persistence, and the Qt editor. Passing these tests does not establish ROM-level compatibility.
