# ukumari

**Spreadsheets defined as text.** A model is a short Python script. Running it builds a
calculation graph that carries no numbers and does no arithmetic. From that one graph,
ukumari:

- checks the model, naming every error at once;
- computes it over data, at any length and over thousands of scenarios in one call;
- lays it out as a workbook of live formulas;
- writes it back out as data.

**Not stable yet.** The format, the API and the names may all change.

## A model

```python
from ukumari import Layout, Model, lag, minimum, scalar
from ukumari.emit import emit, load
from ukumari.pipeline import export

m = Model()
period = m.region("period")
m.axis("month", period)
principal = m.input("principal", scalar)
scheduled = m.input("scheduled", period)
opening, payment, closing = m.vectors(period, "opening", "payment", "closing")
opening.define(lag(closing, seed=principal))
payment.define(minimum(scheduled, opening))  # never pay more than is owed
closing.define(opening - payment)
circuit = m.build().unwrap()

# A standalone NumPy program: any length, many scenarios in one call.
program = load(emit(circuit))
print(program.run({"principal": [100], "scheduled": [30] * 5})["closing"])

# A workbook of live formulas, checked cell by cell against a second computation.
data = {"principal": [100], "scheduled": [30] * 5}
result = export(circuit, data, layout=Layout(label_width=20)).unwrap()
print(result.yup)
```

Every vector is declared first and defined afterwards, which is what lets a recurrence refer to
itself. The model says where each vector lives, never how long it is: lengths arrive with
the data.

## Install from source

ukumari depends on yupana, which is not yet on PyPI, so clone the two side by side:

```bash
git clone <yupana's repository> yupana
git clone <this repository> ukumari
cd ukumari
uv sync
uv run pytest
```

The tests that have the spreadsheet app check a workbook need Windows with the app installed,
and run only when `UKUMARI_APP_TESTS=1` is set.

## The examples

- `examples/debt_schedule.py`: the loan above.
- `examples/three_statement.py`: a three-statement model of a fictional company (every figure is
  made up). It balances by construction, in every year, at any horizon.
- `examples/three_statement_sweep.py`: the same model over 1,000 growth scenarios in one call.

Each example writes its model (`.uku`), its workbook cells (`.yup`), their values and a workbook
to `target/`: `uv run python examples/three_statement.py`.

## The name

Ukumari is the [Quechua](https://en.wikipedia.org/wiki/Quechuan_languages) name for the
[spectacled bear](https://en.wikipedia.org/wiki/Spectacled_bear).
