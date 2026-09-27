"""Spreadsheets defined as text.

A model is a short Python script. Running it builds a calculation graph that carries no
numbers and does no arithmetic. Everything else is an interpretation of that one graph:
checking it, computing it over data at any length and over many scenarios at once, laying
it out as a workbook of live formulas, and writing it back out as data.

Declare, then define. Every vector is named first and defined afterwards, which is what
lets a recurrence refer to itself. Here is a loan whose payment is clamped, so the balance
never goes negative:

>>> from ukumari import Model, lag, minimum, scalar
>>> m = Model()
>>> period = m.region("period")
>>> m.axis("month", period)
>>> principal = m.input("principal", scalar)
>>> scheduled = m.input("scheduled", period)
>>> opening, payment, closing = m.vectors(period, "opening", "payment", "closing")
>>> opening.define(lag(closing, seed=principal))
>>> payment.define(minimum(scheduled, opening))
>>> closing.define(opening - payment)
>>> circuit = m.build().unwrap()

The model says where each vector lives, never how long it is: lengths arrive with the data.
Its NumPy program runs at any length, and over many scenarios in one call:

>>> from ukumari.emit import emit, load
>>> program = load(emit(circuit))
>>> program.run({"principal": [100], "scheduled": [30, 30, 30, 30, 30]})["closing"]
array([[70., 40., 10.,  0.,  0.]])
>>> program.run({"principal": [[100], [50]], "scheduled": [30] * 3})["payment"]
array([[30., 30., 30.],
       [30., 20.,  0.]])

A broken model is refused with every error named at once:

>>> m = Model()
>>> period = m.region("period")
>>> m.axis("month", period)
>>> a, b, c = m.vectors(period, "a", "b", "c")
>>> a.define(b + 1)
>>> b.define(a * 2)
>>> for error in m.build().unwrap_err():
...     print(error)
'c' is declared but never defined
a cycle of references that no lag crosses: 'a' -> 'b' -> 'a'
"""

from ukumari.layout import Layout
from ukumari.model import Model, lag, last, maximum, minimum
from ukumari.shape import scalar

__all__ = [
    "Layout",
    "Model",
    "lag",
    "last",
    "maximum",
    "minimum",
    "scalar",
]
