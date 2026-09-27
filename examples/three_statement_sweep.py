"""The three-statement model over 1,000 scenarios, in one call to its NumPy program.

Revenue growth is flat across the forecast in each scenario, from 0% to 10%. Everything
else is held at the example's data, passed as single rows, which the program uses for every
scenario. It prints timings and writes the program to ``target/``.
"""

from pathlib import Path
from time import perf_counter

import numpy as np
import three_statement

from ukumari.emit import emit, load

SCENARIOS = 1000


def main() -> None:
    started = perf_counter()
    circuit = three_statement.build().unwrap()
    built = perf_counter()
    source = emit(circuit)
    program = load(source)
    emitted = perf_counter()

    data = three_statement.data()
    inputs = {name: np.asarray([values], dtype=float) for name, values in data.items()}
    rates = np.linspace(0.0, 0.10, SCENARIOS)
    inputs["growth"] = np.repeat(rates[:, None], len(data["growth"]), axis=1)
    ran = perf_counter()
    out = program.run(inputs)
    finished = perf_counter()

    target = Path(__file__).resolve().parent.parent / "target"
    target.mkdir(exist_ok=True)
    path = target / "three_statement_program.py"
    path.write_text(source, encoding="utf-8", newline="")

    cash = out["cash"][:, -1]
    worst = float(np.max(np.abs(out["check"])))
    print(f"build:  {1000 * (built - started):8.1f} ms")
    print(f"emit:   {1000 * (emitted - built):8.1f} ms")
    print(f"run:    {1000 * (finished - ran):8.1f} ms for {SCENARIOS} scenarios")
    print(f"final-year cash from {cash.min():,.1f} (0% growth) to {cash.max():,.1f}")
    print(f"largest balance-check residual: {worst:.3g}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
