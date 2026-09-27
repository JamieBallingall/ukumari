"""A three-statement model of a fictional company. Every figure is made up, in millions.

One axis, ``year``, in two regions: ``actual`` (the last reported year) and ``forecast``.
Every forecast stock rolls forward from its own previous value through ``lag``, seeded with
``last`` of the actual figure: that seed is the join between the two halves of the timeline.

It balances by construction. Cash is the plug: every movement in a balance-sheet line other
than cash appears once in the cash-flow statement with the opposite sign. Cash-flow lines
carry their cash sign, so capital expenditure, debt repayment and dividends are negative.
"""

from pathlib import Path

from yupana.result import Result

from ukumari import Layout, Model, lag, last, minimum, scalar
from ukumari.circuit import Circuit
from ukumari.errors import ModelError
from ukumari.model import Declared
from ukumari.pipeline import export
from ukumari.uku import write_uku


def build() -> Result[Circuit, tuple[ModelError, ...]]:
    m = Model()
    actual = m.region("actual")
    forecast = m.region("forecast")
    m.axis("year", actual, forecast)

    m.input("year_actual", actual)
    m.input("year", forecast)
    growth = m.input("growth", forecast)
    scheduled_repayment = m.input("scheduled_repayment", forecast)
    cost_of_sales_pct = m.input("cost_of_sales_pct", scalar)
    operating_expense_pct = m.input("operating_expense_pct", scalar)
    depreciation_rate = m.input("depreciation_rate", scalar)
    interest_rate = m.input("interest_rate", scalar)
    tax_rate = m.input("tax_rate", scalar)
    receivables_pct = m.input("receivables_pct", scalar)
    payables_pct = m.input("payables_pct", scalar)
    capex_pct = m.input("capex_pct", scalar)
    payout_ratio = m.input("payout_ratio", scalar)
    revenue_actual = m.input("revenue_actual", actual)
    cash_actual = m.input("cash_actual", actual)
    receivables_actual = m.input("receivables_actual", actual)
    ppe_actual = m.input("ppe_actual", actual)
    payables_actual = m.input("payables_actual", actual)
    debt_actual = m.input("debt_actual", actual)
    equity_actual = m.input("equity_actual", actual)

    total_assets_actual, liabilities_and_equity_actual, check_actual = m.vectors(
        actual, "total_assets_actual", "liabilities_and_equity_actual", "check_actual"
    )
    total_assets_actual.define(cash_actual + receivables_actual + ppe_actual)
    liabilities_and_equity_actual.define(payables_actual + debt_actual + equity_actual)
    check_actual.define(total_assets_actual - liabilities_and_equity_actual)

    (
        revenue,
        cost_of_sales,
        gross_profit,
        operating_expenses,
        depreciation,
        operating_profit,
        interest,
        profit_before_tax,
        tax,
        net_income,
        change_in_receivables,
        change_in_payables,
        cash_from_operations,
        capital_expenditure,
        debt_repayment,
        dividends,
        net_change_in_cash,
        cash,
        receivables,
        ppe,
        total_assets,
        payables,
        debt,
        equity,
        liabilities_and_equity,
        check,
    ) = m.vectors(
        forecast,
        "revenue",
        "cost_of_sales",
        "gross_profit",
        "operating_expenses",
        "depreciation",
        "operating_profit",
        "interest",
        "profit_before_tax",
        "tax",
        "net_income",
        "change_in_receivables",
        "change_in_payables",
        "cash_from_operations",
        "capital_expenditure",
        "debt_repayment",
        "dividends",
        "net_change_in_cash",
        "cash",
        "receivables",
        "ppe",
        "total_assets",
        "payables",
        "debt",
        "equity",
        "liabilities_and_equity",
        "check",
    )

    def opening(x: Declared, x_actual: Declared):
        return lag(x, seed=last(x_actual))

    revenue.define(opening(revenue, revenue_actual) * (1 + growth))
    cost_of_sales.define(revenue * cost_of_sales_pct)
    gross_profit.define(revenue - cost_of_sales)
    operating_expenses.define(revenue * operating_expense_pct)
    depreciation.define(opening(ppe, ppe_actual) * depreciation_rate)
    operating_profit.define(gross_profit - operating_expenses - depreciation)
    interest.define(opening(debt, debt_actual) * interest_rate)
    profit_before_tax.define(operating_profit - interest)
    tax.define(profit_before_tax * tax_rate)
    net_income.define(profit_before_tax - tax)
    change_in_receivables.define(opening(receivables, receivables_actual) - receivables)
    change_in_payables.define(payables - opening(payables, payables_actual))
    cash_from_operations.define(
        net_income + depreciation + change_in_receivables + change_in_payables
    )
    capital_expenditure.define(-(revenue * capex_pct))
    debt_repayment.define(-minimum(scheduled_repayment, opening(debt, debt_actual)))
    dividends.define(-(net_income * payout_ratio))
    net_change_in_cash.define(
        cash_from_operations + capital_expenditure + debt_repayment + dividends
    )
    cash.define(opening(cash, cash_actual) + net_change_in_cash)
    receivables.define(revenue * receivables_pct)
    ppe.define(opening(ppe, ppe_actual) - capital_expenditure - depreciation)
    total_assets.define(cash + receivables + ppe)
    payables.define(cost_of_sales * payables_pct)
    debt.define(opening(debt, debt_actual) + debt_repayment)
    equity.define(opening(equity, equity_actual) + net_income + dividends)
    liabilities_and_equity.define(payables + debt + equity)
    check.define(total_assets - liabilities_and_equity)
    return m.build()


def data() -> dict[str, list[float]]:
    return {
        "year_actual": [2025],
        "year": [2026, 2027, 2028, 2029, 2030],
        "growth": [0.08, 0.07, 0.06, 0.05, 0.04],
        "scheduled_repayment": [50, 50, 50, 50, 50],
        "cost_of_sales_pct": [0.60],
        "operating_expense_pct": [0.20],
        "depreciation_rate": [0.10],
        "interest_rate": [0.05],
        "tax_rate": [0.25],
        "receivables_pct": [0.15],
        "payables_pct": [0.15],
        "capex_pct": [0.08],
        "payout_ratio": [0.40],
        "revenue_actual": [1000],
        "cash_actual": [120],
        "receivables_actual": [150],
        "ppe_actual": [600],
        "payables_actual": [90],
        "debt_actual": [300],
        "equity_actual": [480],
    }


MONEY = "#,##0.0;(#,##0.0)"
PERCENT = "0.0%"

ASSUMPTIONS = {
    "Revenue growth": "growth",
    "Cost of sales, % of revenue": "cost_of_sales_pct",
    "Operating expenses, % of revenue": "operating_expense_pct",
    "Depreciation, % of opening PP&E": "depreciation_rate",
    "Interest, % of opening debt": "interest_rate",
    "Tax, % of profit before tax": "tax_rate",
    "Receivables, % of revenue": "receivables_pct",
    "Payables, % of cost of sales": "payables_pct",
    "Capital expenditure, % of revenue": "capex_pct",
    "Dividends, % of net income": "payout_ratio",
    "Scheduled debt repayment": "scheduled_repayment",
}

STATEMENTS = {
    "Revenue": ("revenue_actual", "revenue"),
    "Cost of sales": ("cost_of_sales",),
    "Gross profit": ("gross_profit",),
    "Operating expenses": ("operating_expenses",),
    "Depreciation": ("depreciation",),
    "Operating profit": ("operating_profit",),
    "Interest": ("interest",),
    "Profit before tax": ("profit_before_tax",),
    "Tax": ("tax",),
    "Net income": ("net_income",),
    "Cash": ("cash_actual", "cash"),
    "Receivables": ("receivables_actual", "receivables"),
    "PP&E": ("ppe_actual", "ppe"),
    "Total assets": ("total_assets_actual", "total_assets"),
    "Payables": ("payables_actual", "payables"),
    "Debt": ("debt_actual", "debt"),
    "Equity": ("equity_actual", "equity"),
    "Liabilities and equity": (
        "liabilities_and_equity_actual",
        "liabilities_and_equity",
    ),
    "Balance check": ("check_actual", "check"),
    "Change in receivables": ("change_in_receivables",),
    "Change in payables": ("change_in_payables",),
    "Cash from operations": ("cash_from_operations",),
    "Capital expenditure": ("capital_expenditure",),
    "Debt repayment": ("debt_repayment",),
    "Dividends": ("dividends",),
    "Net change in cash": ("net_change_in_cash",),
}

WORKING_LINES = (
    "Cost of sales",
    "Operating expenses",
    "Depreciation",
    "Interest",
    "Tax",
    "Change in receivables",
    "Change in payables",
    "Capital expenditure",
    "Debt repayment",
    "Dividends",
)


def layout() -> Layout:
    rows: dict[str, tuple[str, ...]] = {"Year": ("year_actual", "year")}
    rows |= {label: (name,) for label, name in ASSUMPTIONS.items()}
    rows |= STATEMENTS
    formats = {"Year": "0"}
    formats |= {label: PERCENT for label in ASSUMPTIONS}
    formats |= {label: MONEY for label in STATEMENTS if label != "Balance check"}
    formats["Scheduled debt repayment"] = MONEY
    indents = {label: 1 for label in (*ASSUMPTIONS, *WORKING_LINES)}
    return Layout(
        rows=rows,
        formats=formats,
        indents=indents,
        label_width=34,
        period_width=10,
    )


def outputs() -> dict[str, str]:
    """The files this example writes, by name: the model, the workbook cells and values."""
    circuit = build().unwrap()
    result = export(circuit, data(), layout=layout()).unwrap()
    return {
        "three_statement.uku": write_uku(circuit),
        "three_statement.yup": result.yup,
        "three_statement.values.csv": result.values_csv,
    }


def main() -> None:
    """Write this example's files, and its workbook, to ``target/`` at the repository root."""
    target = Path(__file__).resolve().parent.parent / "target"
    target.mkdir(exist_ok=True)
    for name, text in outputs().items():
        (target / name).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {target / name}")
    workbook = export(build().unwrap(), data(), layout=layout()).unwrap().xlsx()
    (target / "three_statement.xlsx").write_bytes(workbook)
    print(f"wrote {target / 'three_statement.xlsx'}")


if __name__ == "__main__":
    main()
