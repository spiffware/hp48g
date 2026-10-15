# HP 48G Desktop

A Python / Qt6 scientific RPN calculator inspired by the HP 48G, with a calculator keypad, stack display, command browser, and integrated graphing workspace. Qt is provided by **PySide6**, algebra by SymPy, numerical analysis by SciPy, and interactive plotting by Matplotlib.

## Run

Requires Python 3.10 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m hp48g
```

On macOS, double-click `Launch.command` after setup.

After installation, `hp48g` is also available as an application command. In this workspace dependencies are already installed in `.venv`; launch with `.venv/bin/python -m hp48g`.

The tested dependency versions are recorded in `requirements-lock.txt` (macOS, Python 3.12).

![Application preview](docs/preview.png)

## Using the calculator

Enter `2 3 +` and press Enter, or enter each number separately and click `+`. Empty Enter duplicates the top of the stack. Input can contain a whole RPN sequence; operations consume their arguments from the stack in left-to-right order. Failed sequences roll back stack, variables, and modes. Undo retains up to 100 prior states.

- Scientific: degree/radian/gradian trigonometry, inverse and hyperbolic functions, logarithms, powers, factorials, combinations, permutations, percentages, complex arithmetic, integer bit operations.
- Symbolic: derivatives, indefinite and definite integrals, equation solving, numerical roots, substitution, simplification, expansion, factorization, exact and decimal display.
- Linear algebra: matrices, determinant, inverse, transpose, rank, trace, eigenvalues, linear systems, vector dot/cross products and norms.
- Data: mean, median, sample variance/deviation, sorting, sums, paired-data linear regression and correlation.
- Graphs: multiple functions, polar, parametric, implicit zero contours, 3D surfaces, slope fields, histograms and scatter plots. Pan, zoom and image export are in the plot toolbar.
- Analysis: bracketed roots, numerical integration, bounded extrema, symbolic derivative evaluation.
- Solvers: first-order differential equations with initial conditions, end-of-period time-value-of-money cash flows, normal/Student t/chi-square/binomial/Poisson density, cumulative and inverse probabilities.
- Memory: named variables, straight-line stored RPN programs, session JSON save/load.
- Units: conversions for common length, mass, time, temperature, pressure, energy, volume and angle units.

### Examples

| Input | Operation |
|---|---|
| `'x^3-2*x' x DIFF` | Differentiate with respect to x |
| `'x^2' x 0 3 DINT` | Integrate from 0 to 3 |
| `'x^2-2' x SOLVE` | Symbolic roots |
| `'cos(x)-x' x 1 ROOT` | Numerical root near 1 |
| `[[2,0],[0,4]] [6,8] LSOLVE` | Solve A·x = b |
| `42 'a' STO` then `a` | Store and recall |
| `« DUP * » 'square' STO` then `7 square` | Store and run a program |

Arguments to `SUBST` are expression and `[symbol,value]`; `DINT` takes expression, symbol, lower, upper; `ROOT` takes expression, symbol, guess. The command browser lists every registered calculation command. Stack and memory commands are described in the Guide tab. Literal lists use commas. Unquoted unknown names become symbolic variables.

Graph expressions use radians regardless of keypad angle mode. Function plots initially use the domain for both x and y limits; adjust with the navigation toolbar. Redrawing functions preserves your custom axis limits; changing the domain updates the x range while retaining the y range. Enter a second function in the optional second field to plot both with Draw graph. Separate additional curves with semicolons. The second field becomes y(t) in Parametric mode and y values in Scatter mode; it is hidden in other modes. Polar and parametric plots use `t`; surfaces and implicit plots use `x,y`. Analysis operates on the first function. Root analysis needs a sign-changing bracket. Extrema are local bounded results, not certified global optima.

## Compatibility boundary

**This is not a complete HP 48G replica or ROM emulator.** It is a working independently implemented scientific calculator. The request for all original analysis, math, graphing and programming behavior is not yet fulfilled. In particular, this release does not implement the full HP command catalog, full User RPL control flow/local scopes, original menus and shift mappings, HP binary object formats, flags and word-size semantics, directory trees, physical I/O, equation libraries, every original plot type, or dimensional unit algebra. The keypad layout is inspired by the device rather than pixel-identical. SymPy exact arithmetic differs from original HP floating-point behavior. Eigenvalue output contains distinct eigenvalues rather than multiplicity expansion.

The parser uses a restricted mathematical AST, not Python evaluation. Expensive symbolic calculations currently run on the UI thread and can delay the interface; use reasonable expressions and trusted session files. Program execution has a step limit, but this is not a hostile-input sandbox.

Reference: [HP 48G Series User’s Guide](https://www.hp.com/ctg/Manual/c00442262.pdf), [Advanced User’s Reference](https://literature.hpcalc.org/community/hp48g-aur-en.pdf), [Qt for Python](https://doc.qt.io/qtforpython-6/).

## Development

```sh
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/hp48g-matplotlib .venv/bin/python -m pytest -q
```

`hp48g/engine.py` contains the transactional calculator, `analysis.py` the numerical tools, `plot.py` graphing, `tools_panel.py` additional solvers, and `app.py` the Qt application and session persistence. Tests cover numerical results, rollback, programs, parser restrictions, graph modes, session object round trips, and UI actions.
