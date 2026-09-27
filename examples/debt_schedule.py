"""A loan with a clamp: the smallest model with a recurrence.

Each month the payment is the scheduled amount, or whatever is left if that is less, so the
balance never goes negative however long the schedule runs.
"""

from pathlib import Path

from yupana.result import Result

from ukumari import Layout, Model, lag, minimum, scalar
from ukumari.circuit import Circuit
from ukumari.errors import ModelError
from ukumari.pipeline import export
from ukumari.uku import write_uku


def build() -> Result[Circuit, tuple[ModelError, ...]]:
    m = Model()
    period = m.region("period")
    m.axis("month", period)
    principal = m.input("principal", scalar)
    scheduled = m.input("scheduled", period)
    opening, payment, closing = m.vectors(period, "opening", "payment", "closing")
    opening.define(lag(closing, seed=principal))
    payment.define(minimum(scheduled, opening))
    closing.define(opening - payment)
    return m.build()


def data() -> dict[str, list[float]]:
    return {"principal": [100.0], "scheduled": [30.0, 30.0, 30.0, 30.0, 30.0]}


def layout() -> Layout:
    money = "#,##0.00"
    return Layout(
        rows={
            "Principal": ("principal",),
            "Scheduled payment": ("scheduled",),
            "Opening balance": ("opening",),
            "Payment": ("payment",),
            "Closing balance": ("closing",),
        },
        formats={
            label: money
            for label in (
                "Principal",
                "Scheduled payment",
                "Opening balance",
                "Payment",
                "Closing balance",
            )
        },
        indents={"Payment": 1},
        label_width=20,
        period_width=10,
    )


def outputs() -> dict[str, str]:
    """The files this example writes, by name: the model, the workbook cells and values."""
    circuit = build().unwrap()
    result = export(circuit, data(), layout=layout()).unwrap()
    return {
        "debt_schedule.uku": write_uku(circuit),
        "debt_schedule.yup": result.yup,
        "debt_schedule.values.csv": result.values_csv,
    }


def main() -> None:
    """Write this example's files, and its workbook, to ``target/`` at the repository root."""
    target = Path(__file__).resolve().parent.parent / "target"
    target.mkdir(exist_ok=True)
    for name, text in outputs().items():
        (target / name).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {target / name}")
    workbook = export(build().unwrap(), data(), layout=layout()).unwrap().xlsx()
    (target / "debt_schedule.xlsx").write_bytes(workbook)
    print(f"wrote {target / 'debt_schedule.xlsx'}")


if __name__ == "__main__":
    main()
