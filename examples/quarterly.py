"""A quarterly three-statement model of a fictional maker of garden equipment.

Every figure is made up, in millions. Sales peak in the second quarter, when gardens do.

One axis, ``quarter``, in two regions: five years of ``history`` and five of ``forecast``.
The workbook has four sheets:

- **Historicals**, where the reported quarters land, with the subtotals a report shows;
- **Assumptions**, the inputs for the forecast, each single value stretched across the
  forecast quarters beside it, so that every quarter reads a cell of its own;
- **Analysis**, the history spread out: growth, margins, working-capital days, and the
  state at the last reported quarter, from which the forecast starts;
- **Forecast**, which copies the assumptions and that initial state, rolls everything
  forward a quarter at a time, picks the three statements out of the roll-forward, and ends
  with ratios.

The forecast looks back only one quarter. Anything further back is carried as state: revenue
grows on the same quarter a year earlier, so the state holds the last four quarters'
revenue, each row the row above one quarter later. The growth rate is the compound annual
growth of the history's twelve-month revenue, which is why the model needs ``first`` and a
fractional power.

Cash runs through a waterfall every quarter. Whatever is above a minimum balance, once
operations and investment are paid for, pays a dividend up to a target; what is left repays
the revolver, or the revolver covers a shortfall up to its limit; and a share of anything
left over buys back shares. There is no IF in the language, so every step is a minimum or a
maximum. The bonds and the term loan stay where they were at the last reported quarter, for
now. The balance sheet balances by construction in every quarter.
"""

from datetime import date
from pathlib import Path

from yupana.result import Result

from ukumari import (
    Blank,
    Heading,
    Line,
    Model,
    Sheet,
    Workbook,
    first,
    lag,
    last,
    maximum,
    minimum,
    scalar,
)
from ukumari.circuit import Circuit
from ukumari.errors import ModelError
from ukumari.model import Declared
from ukumari.pipeline import export
from ukumari.shape import Span
from ukumari.uku import write_uku

MONEY = "_(#,##0.0);(#,##0.0);_(-_)"
PERCENT = "0.0%"
DAYS = "0.0"
DATE = "mmm-yy"
COUNT = "0"
MULTIPLE = '0.0"x"'

HISTORY = 20
FORECAST = 20

# What the landing sheet reports: model name and label. Each is an input on the history,
# named with ``_actual``.
INCOME = {
    "revenue": "Revenue",
    "cost_of_sales": "Cost of sales",
    "operating_expenses": "Operating expenses",
    "depreciation": "Depreciation",
    "interest": "Interest",
    "tax": "Tax",
}
ASSETS = {
    "cash": "Cash",
    "receivables": "Receivables",
    "inventory": "Inventory",
    "ppe": "PP&E",
}
LIABILITIES = {
    "payables": "Payables",
    "revolver": "Revolver",
    "bond_a": "Bond A",
    "bond_b": "Bond B",
    "term_loan": "Term loan",
    "equity": "Equity",
}
CASH_FLOWS = {
    "capex": "Capital expenditure",
    "dividends": "Dividends",
    "buybacks": "Share buybacks",
}
BALANCES = ASSETS | LIABILITIES
DEBT = ("revolver", "bond_a", "bond_b", "term_loan")

# Single values on the Assumptions sheet, each stretched across the forecast: model name,
# label and number format.
STRETCHED = {
    "cost_of_sales_pct": ("Cost of sales, % of revenue", PERCENT),
    "operating_expenses_pct": ("Operating expenses, % of revenue", PERCENT),
    "depreciation_rate": ("Depreciation, % of opening PP&E", PERCENT),
    "capex_pct": ("Capital expenditure, % of revenue", PERCENT),
    "tax_rate": ("Tax, % of profit before tax", PERCENT),
    "receivable_days": ("Receivables, days of revenue", DAYS),
    "inventory_days": ("Inventory, days of cost of sales", DAYS),
    "payable_days": ("Payables, days of cost of sales", DAYS),
    "interest_rate": ("Interest, % a year of opening debt", PERCENT),
    "minimum_cash": ("Minimum cash", MONEY),
    "dividend": ("Target dividend a quarter", MONEY),
    "revolver_limit": ("Revolver limit", MONEY),
    "buyback_share": ("Share buybacks, % of cash left over", PERCENT),
}

# Lines of the three statements that are copies of the roll-forward: model name and label.
STATEMENT_COPIES = {
    "_is": {
        "revenue": "Revenue",
        "cost_of_sales": "Cost of sales",
        "operating_expenses": "Operating expenses",
        "ebitda": "EBITDA",
        "depreciation": "Depreciation",
        "operating_profit": "Operating profit",
        "interest": "Interest",
        "profit_before_tax": "Profit before tax",
        "tax": "Tax",
        "net_income": "Net income",
    },
    "_bs": {name: label for name, label in BALANCES.items()},
    "_cf": {
        "net_income": "Net income",
        "depreciation": "Depreciation",
        "revolver_drawn": "Revolver drawn (repaid)",
        "opening_cash": "Opening cash",
        "cash": "Closing cash",
    },
}


def build() -> Result[Circuit, tuple[ModelError, ...]]:
    m = Model()
    history = m.region("history")
    forecast = m.region("forecast")
    m.axis("quarter", history, forecast)

    def copy(name: str, source: Declared) -> Declared:
        """A vector or single value defined as another: a link in the workbook."""
        copied = m.vector(name, source.shape)
        copied.define(source)
        return copied

    def earlier(name: str, source: Declared, span: Span, count: int) -> list[Declared]:
        """``source`` one, two, … ``count`` quarters earlier: each row the row above,
        lagged, so each looks back only one quarter."""
        found = []
        before = source
        for k in range(1, count + 1):
            row = m.vector(f"{name}_{k}q", span[k:])
            row.define(lag(before))
            found.append(row)
            before = row
        return found

    # --- Historicals: the reported quarters, and the subtotals a report shows. ------------
    quarter_end_actual = m.input("quarter_end_actual", history)
    actual = {
        name: m.input(f"{name}_actual", history)
        for name in (*INCOME, *BALANCES, *CASH_FLOWS)
    }
    (
        gross_profit_actual,
        ebitda_actual,
        operating_profit_actual,
        profit_before_tax_actual,
        net_income_actual,
        total_assets_actual,
        total_liabilities_and_equity_actual,
        balance_check_actual,
    ) = m.vectors(
        history,
        "gross_profit_actual",
        "ebitda_actual",
        "operating_profit_actual",
        "profit_before_tax_actual",
        "net_income_actual",
        "total_assets_actual",
        "total_liabilities_and_equity_actual",
        "balance_check_actual",
    )
    gross_profit_actual.define(actual["revenue"] - actual["cost_of_sales"])
    ebitda_actual.define(gross_profit_actual - actual["operating_expenses"])
    operating_profit_actual.define(ebitda_actual - actual["depreciation"])
    profit_before_tax_actual.define(operating_profit_actual - actual["interest"])
    net_income_actual.define(profit_before_tax_actual - actual["tax"])
    total_assets_actual.define(
        actual["cash"] + actual["receivables"] + actual["inventory"] + actual["ppe"]
    )
    total_liabilities_and_equity_actual.define(
        actual["payables"]
        + actual["revolver"]
        + actual["bond_a"]
        + actual["bond_b"]
        + actual["term_loan"]
        + actual["equity"]
    )
    balance_check_actual.define(
        total_assets_actual - total_liabilities_and_equity_actual
    )

    # --- Assumptions: inputs for the forecast, single values stretched across it. -------
    quarter_end = m.input("quarter_end", forecast)
    growth_adjustment = m.input("growth_adjustment", forecast)
    stretched: dict[str, Declared] = {}
    for name in STRETCHED:
        stretched[name] = m.vector(f"{name}_stretched", forecast)
        stretched[name].define(m.input(name, scalar))

    # --- Analysis: the history spread out, and the state at its last quarter. -----------
    quarter_end_a = copy("quarter_end_a", quarter_end_actual)
    quarter_number = m.vector("quarter_number", history)
    quarter_number.define(lag(quarter_number + 1, seed=1))
    revenue_a = copy("revenue_a", actual["revenue"])
    revenue_1q, revenue_2q, revenue_3q, revenue_4q = earlier(
        "revenue", revenue_a, history, 4
    )
    revenue_12m = m.vector("revenue_12m", history[3:])
    revenue_12m.define(revenue_a + revenue_1q + revenue_2q + revenue_3q)
    revenue_growth_a = m.vector("revenue_growth_a", history[4:])
    revenue_growth_a.define(revenue_a / revenue_4q - 1)
    # Twelve-month revenue first covers a whole year at the fourth quarter.
    years, cagr = m.vectors(scalar, "years", "cagr")
    years.define((last(quarter_number) - 4) / 4)
    cagr.define((last(revenue_12m) / first(revenue_12m)) ** (1 / years) - 1)

    gross_margin_a, ebitda_margin_a, capex_pct_a, tax_rate_a = m.vectors(
        history, "gross_margin_a", "ebitda_margin_a", "capex_pct_a", "tax_rate_a"
    )
    gross_margin_a.define(gross_profit_actual / revenue_a)
    ebitda_margin_a.define(ebitda_actual / revenue_a)
    capex_pct_a.define(actual["capex"] / revenue_a)
    tax_rate_a.define(actual["tax"] / profit_before_tax_actual)
    # The first quarter has no quarter before it to count its days from.
    days_a, receivable_days_a, inventory_days_a, payable_days_a = m.vectors(
        history[1:], "days_a", "receivable_days_a", "inventory_days_a", "payable_days_a"
    )
    days_a.define(quarter_end_a - lag(quarter_end_a))
    receivable_days_a.define(actual["receivables"] / revenue_a * days_a)
    inventory_days_a.define(actual["inventory"] / actual["cost_of_sales"] * days_a)
    payable_days_a.define(actual["payables"] / actual["cost_of_sales"] * days_a)

    ebitda_a = copy("ebitda_a", ebitda_actual)
    ebitda_1q, ebitda_2q, ebitda_3q = earlier("ebitda", ebitda_a, history, 3)
    ebitda_12m_a = m.vector("ebitda_12m_a", history[3:])
    ebitda_12m_a.define(ebitda_a + ebitda_1q + ebitda_2q + ebitda_3q)

    def at_the_end(name: str, source: Declared) -> Declared:
        start = m.vector(name, scalar)
        start.define(last(source))
        return start

    start_quarter_end = at_the_end("start_quarter_end", quarter_end_a)
    start_revenue = [
        at_the_end(f"start_revenue_{k}q", source)
        for k, source in enumerate((revenue_a, revenue_1q, revenue_2q, revenue_3q))
    ]
    start_ebitda = [
        at_the_end(f"start_ebitda_{k}q", source)
        for k, source in enumerate((ebitda_a, ebitda_1q, ebitda_2q))
    ]
    start_balance = {
        name: at_the_end(f"start_{name}", actual[name]) for name in BALANCES
    }

    # --- Forecast: copies of the assumptions and of the initial state. ------------------
    quarter_end_f = copy("quarter_end_f", quarter_end)
    growth_adjustment_f = copy("growth_adjustment_f", growth_adjustment)
    use = {name: copy(f"{name}_f", row) for name, row in stretched.items()}
    start_quarter_end_f = copy("start_quarter_end_f", start_quarter_end)
    cagr_f = copy("cagr_f", cagr)
    start_revenue_f = [copy(f"{s.name}_f", s) for s in start_revenue]
    start_ebitda_f = [copy(f"{s.name}_f", s) for s in start_ebitda]
    start = {name: copy(f"{s.name}_f", s) for name, s in start_balance.items()}

    # --- Forecast: the roll-forward, one quarter at a time. -----------------------------
    days = m.vector("days", forecast)
    days.define(quarter_end_f - lag(quarter_end_f, seed=start_quarter_end_f))

    # Revenue grows on the same quarter a year earlier. The state is the last four
    # quarters' revenue: each row is the row above, one quarter later.
    revenue, revenue_growth = m.vectors(forecast, "revenue", "revenue_growth")
    revenue_state = []
    before = revenue
    for k, seed in enumerate(start_revenue_f, start=1):
        row = m.vector(f"revenue_{k}q_f", forecast)
        row.define(lag(before, seed=seed))
        revenue_state.append(row)
        before = row
    revenue_growth.define(cagr_f + growth_adjustment_f)
    revenue.define(revenue_state[-1] * (1 + revenue_growth))

    cost_of_sales, operating_expenses, ebitda = m.vectors(
        forecast, "cost_of_sales", "operating_expenses", "ebitda"
    )
    cost_of_sales.define(revenue * use["cost_of_sales_pct"])
    operating_expenses.define(revenue * use["operating_expenses_pct"])
    ebitda.define(revenue - cost_of_sales - operating_expenses)

    opening_ppe, capex, depreciation, ppe = m.vectors(
        forecast, "opening_ppe", "capex", "depreciation", "ppe"
    )
    opening_ppe.define(lag(ppe, seed=start["ppe"]))
    capex.define(revenue * use["capex_pct"])
    depreciation.define(opening_ppe * use["depreciation_rate"])
    ppe.define(opening_ppe + capex - depreciation)

    receivables, inventory, payables, working_capital, working_capital_increase = (
        m.vectors(
            forecast,
            "receivables",
            "inventory",
            "payables",
            "working_capital",
            "working_capital_increase",
        )
    )
    receivables.define(revenue / days * use["receivable_days"])
    inventory.define(cost_of_sales / days * use["inventory_days"])
    payables.define(cost_of_sales / days * use["payable_days"])
    working_capital.define(receivables + inventory - payables)
    start_working_capital = (
        start["receivables"] + start["inventory"] - start["payables"]
    )
    working_capital_increase.define(
        working_capital - lag(working_capital, seed=start_working_capital)
    )

    # The bonds and the term loan stay where they were at the last reported quarter, for
    # now; the revolver moves with the waterfall below.
    held = {name: m.vector(name, forecast) for name in DEBT if name != "revolver"}
    for name, row in held.items():
        row.define(start[name])
    opening_revolver, revolver = m.vectors(forecast, "opening_revolver", "revolver")
    opening_revolver.define(lag(revolver, seed=start["revolver"]))
    opening_debt, debt, interest = m.vectors(
        forecast, "opening_debt", "debt", "interest"
    )
    debt.define(revolver + held["bond_a"] + held["bond_b"] + held["term_loan"])
    start_debt = (
        start["revolver"] + start["bond_a"] + start["bond_b"] + start["term_loan"]
    )
    # Interest on the opening balance, so the revolver drawn this quarter costs nothing
    # until the next: no circular reference.
    opening_debt.define(lag(debt, seed=start_debt))
    interest.define(opening_debt * use["interest_rate"] / 4)

    operating_profit, profit_before_tax, tax, net_income = m.vectors(
        forecast, "operating_profit", "profit_before_tax", "tax", "net_income"
    )
    operating_profit.define(ebitda - depreciation)
    profit_before_tax.define(operating_profit - interest)
    tax.define(maximum(profit_before_tax, 0) * use["tax_rate"])  # no credit for a loss
    net_income.define(profit_before_tax - tax)

    cash_from_operations = m.vector("cash_from_operations", forecast)
    cash_from_operations.define(net_income + depreciation - working_capital_increase)

    # The waterfall. Each step is a minimum or a maximum: the language has no IF.
    (
        opening_cash,
        available,
        dividends,
        after_dividends,
        revolver_drawn,
        after_revolver,
        buybacks,
        cash,
    ) = m.vectors(
        forecast,
        "opening_cash",
        "available",
        "dividends",
        "after_dividends",
        "revolver_drawn",
        "after_revolver",
        "buybacks",
        "cash",
    )
    opening_cash.define(lag(cash, seed=start["cash"]))
    # Cash above the minimum once operations and investment are paid for.
    available.define(opening_cash - use["minimum_cash"] + cash_from_operations - capex)
    # A dividend up to the target, and only out of cash that is there.
    dividends.define(minimum(use["dividend"], maximum(available, 0)))
    after_dividends.define(available - dividends)
    # Repay the revolver out of a surplus, or draw on it for a shortfall, within its limit.
    room = use["revolver_limit"] - opening_revolver
    revolver_drawn.define(maximum(-opening_revolver, minimum(room, -after_dividends)))
    after_revolver.define(after_dividends + revolver_drawn)
    # A share of whatever is left over buys back shares; the rest stays as cash.
    buybacks.define(maximum(after_revolver, 0) * use["buyback_share"])
    cash.define(use["minimum_cash"] + after_revolver - buybacks)
    revolver.define(opening_revolver + revolver_drawn)

    opening_equity, equity = m.vectors(forecast, "opening_equity", "equity")
    opening_equity.define(lag(equity, seed=start["equity"]))
    equity.define(opening_equity + net_income - dividends - buybacks)

    ebitda_state = []
    before = ebitda
    for k, seed in enumerate(start_ebitda_f, start=1):
        row = m.vector(f"ebitda_{k}q_f", forecast)
        row.define(lag(before, seed=seed))
        ebitda_state.append(row)
        before = row
    ebitda_12m = m.vector("ebitda_12m", forecast)
    ebitda_12m.define(ebitda + ebitda_state[0] + ebitda_state[1] + ebitda_state[2])

    # --- Forecast: the three statements, picked out of the roll-forward. ----------------
    rolled = {
        "revenue": revenue,
        "cost_of_sales": cost_of_sales,
        "operating_expenses": operating_expenses,
        "ebitda": ebitda,
        "depreciation": depreciation,
        "operating_profit": operating_profit,
        "interest": interest,
        "profit_before_tax": profit_before_tax,
        "tax": tax,
        "net_income": net_income,
        "cash": cash,
        "receivables": receivables,
        "inventory": inventory,
        "ppe": ppe,
        "payables": payables,
        "revolver": revolver,
        **held,
        "equity": equity,
        "revolver_drawn": revolver_drawn,
        "opening_cash": opening_cash,
    }
    picked = {
        (name, suffix): copy(f"{name}{suffix}", rolled[name])
        for suffix, lines in STATEMENT_COPIES.items()
        for name in lines
    }

    def income(name: str) -> Declared:
        return picked[(name, "_is")]

    def balance(name: str) -> Declared:
        return picked[(name, "_bs")]

    def flow(name: str) -> Declared:
        return picked[(name, "_cf")]

    gross_profit, gross_margin, ebitda_margin, net_margin = m.vectors(
        forecast, "gross_profit", "gross_margin", "ebitda_margin", "net_margin"
    )
    gross_profit.define(income("revenue") - income("cost_of_sales"))
    gross_margin.define(gross_profit / income("revenue"))
    ebitda_margin.define(income("ebitda") / income("revenue"))
    net_margin.define(income("net_income") / income("revenue"))

    total_assets, total_liabilities_and_equity, balance_check = m.vectors(
        forecast, "total_assets", "total_liabilities_and_equity", "balance_check"
    )
    total_assets.define(
        balance("cash") + balance("receivables") + balance("inventory") + balance("ppe")
    )
    total_liabilities_and_equity.define(
        balance("payables")
        + balance("revolver")
        + balance("bond_a")
        + balance("bond_b")
        + balance("term_loan")
        + balance("equity")
    )
    balance_check.define(total_assets - total_liabilities_and_equity)

    (
        working_capital_cf,
        cash_from_operations_cf,
        capex_cf,
        dividends_cf,
        buybacks_cf,
        cash_from_financing,
        net_change_in_cash,
    ) = m.vectors(
        forecast,
        "working_capital_cf",
        "cash_from_operations_cf",
        "capex_cf",
        "dividends_cf",
        "buybacks_cf",
        "cash_from_financing",
        "net_change_in_cash",
    )
    working_capital_cf.define(-working_capital_increase)
    cash_from_operations_cf.define(
        flow("net_income") + flow("depreciation") + working_capital_cf
    )
    capex_cf.define(-capex)
    dividends_cf.define(-dividends)
    buybacks_cf.define(-buybacks)
    cash_from_financing.define(flow("revolver_drawn") + dividends_cf + buybacks_cf)
    net_change_in_cash.define(cash_from_operations_cf + capex_cf + cash_from_financing)

    # --- Forecast: ratios that are not part of the statements. -------------------------
    net_debt, debt_to_ebitda, net_debt_to_ebitda, interest_cover = m.vectors(
        forecast, "net_debt", "debt_to_ebitda", "net_debt_to_ebitda", "interest_cover"
    )
    net_debt.define(debt - cash)
    debt_to_ebitda.define(debt / ebitda_12m)
    net_debt_to_ebitda.define(net_debt / ebitda_12m)
    interest_cover.define(ebitda / interest)
    revolver_room, liquidity = m.vectors(forecast, "revolver_room", "liquidity")
    revolver_room.define(use["revolver_limit"] - revolver)
    liquidity.define(cash + revolver_room)
    return m.build()


def quarter_ends(first_year: int, quarters: int) -> list[date]:
    """The last day of each quarter, from the first quarter of ``first_year``."""
    ends = [(3, 31), (6, 30), (9, 30), (12, 31)]
    return [date(first_year + i // 4, *ends[i % 4]) for i in range(quarters)]


def serial(day: date) -> float:
    """A date as the spreadsheet app counts it: days since 1899-12-30."""
    return float((day - date(1899, 12, 30)).days)


def reported() -> dict[str, list[float]]:
    """Twenty reported quarters, from a small simulation. Every figure is made up.

    Revenue grows on the same quarter a year earlier, faster when the economy grows and
    slower when prices rise; costs and working capital follow it. Cash is held at 20: a
    revolver covers a shortfall and is repaid from a surplus, a dividend of 4 is paid when
    cash allows, and half of anything left over buys back shares. Every line is rounded to
    a tenth, as a report would show it, and the balance sheet balances in every quarter.
    """
    gdp_growth = [5.5, 5.0, 4.2, 3.5, 3.0, 2.4, 2.0, 1.6, 1.0, 0.4]
    gdp_growth += [0.1, 0.3, 0.8, 1.2, 1.6, 1.8, 2.0, 2.1, 2.0, 1.9]
    price_change = [2.0, 2.2, 2.5, 3.0, 5.0, 6.5, 7.0, 6.0, 4.5, 3.5]
    price_change += [3.0, 2.5, 2.4, 2.2, 2.0, 2.0, 2.2, 2.4, 2.5, 2.5]
    surprise = [0.004, -0.006, 0.002, 0.005, -0.003, 0.001, -0.004, 0.006]
    surprise += [0.0, -0.002, 0.003, -0.005, 0.002, 0.004, -0.001, 0.0]
    base_rate = [0.25] * 4 + [0.5, 1.5, 3.0, 4.0, 4.75, 5.25, 5.5, 5.5]
    base_rate += [5.25, 5.0, 4.75, 4.5, 4.25, 4.25, 4.0, 4.0]

    def tenth(x: float) -> float:
        return round(x, 1)

    revenue = [96.0, 132.0, 104.0, 78.0]
    for t in range(4, HISTORY):
        growth = (
            0.05
            + 1.5 * (gdp_growth[t] / 100 - 0.02)
            - 0.5 * (price_change[t] / 100 - 0.03)
            + surprise[t - 4]
        )
        revenue.append(tenth(revenue[t - 4] * (1 + growth)))

    cash, receivables, inventory, ppe, payables = 30.0, 58.0, 70.0, 200.0, 32.0
    revolver, bond_a, bond_b, term_loan = 0.0, 60.0, 80.0, 120.0
    debt = revolver + bond_a + bond_b + term_loan
    equity = cash + receivables + inventory + ppe - payables - debt
    reported: dict[str, list[float]] = {
        f"{name}_actual": [] for name in (*INCOME, *BALANCES, *CASH_FLOWS)
    }
    previous_end = date(2020, 12, 31)
    for t, end in enumerate(quarter_ends(2021, HISTORY)):
        days = (end - previous_end).days
        previous_end = end
        sales = revenue[t]
        cost_of_sales = tenth(sales * (0.61 if 4 <= t < 12 else 0.60))
        operating_expenses = tenth(sales * 0.22)
        depreciation = tenth(ppe * 0.025)
        interest = tenth(
            bond_a * 0.0475 / 4
            + bond_b * 0.06 / 4
            + term_loan * (base_rate[t] + 2.5) / 400
            + revolver * (base_rate[t] + 1.75) / 400
        )
        profit_before_tax = (
            sales - cost_of_sales - operating_expenses - depreciation - interest
        )
        tax = tenth(max(0.0, profit_before_tax) * 0.25)
        net_income = profit_before_tax - tax
        new_receivables = tenth(sales * 55 / days)
        new_inventory = tenth(cost_of_sales * 110 / days)
        new_payables = tenth(cost_of_sales * 50 / days)
        working_capital_increase = (new_receivables + new_inventory - new_payables) - (
            receivables + inventory - payables
        )
        capex = tenth(sales * 0.055)
        repaid = min(2.5, term_loan)
        available = (
            cash - 20.0 + net_income + depreciation - working_capital_increase
        ) - (capex + repaid)
        dividends = tenth(min(4.0, max(0.0, available)))
        drawn = max(-revolver, min(150.0 - revolver, dividends - available))
        buybacks = tenth(max(0.0, available - dividends + drawn) * 0.5)
        cash = 20.0 + available - dividends + drawn - buybacks
        receivables, inventory, payables = new_receivables, new_inventory, new_payables
        ppe += capex - depreciation
        revolver += drawn
        term_loan -= repaid
        equity += net_income - dividends - buybacks
        quarter = {
            "revenue": sales,
            "cost_of_sales": cost_of_sales,
            "operating_expenses": operating_expenses,
            "depreciation": depreciation,
            "interest": interest,
            "tax": tax,
            "cash": cash,
            "receivables": receivables,
            "inventory": inventory,
            "ppe": ppe,
            "payables": payables,
            "revolver": revolver,
            "bond_a": bond_a,
            "bond_b": bond_b,
            "term_loan": term_loan,
            "equity": equity,
            "capex": capex,
            "dividends": dividends,
            "buybacks": buybacks,
        }
        for name, value in quarter.items():
            # Sums of tenths, rounded back to what they are, as a report shows them.
            reported[f"{name}_actual"].append(round(value, 6))
    return reported


def data(history: int = HISTORY, forecast: int = FORECAST) -> dict[str, list[float]]:
    """The last ``history`` of the twenty reported quarters, and ``forecast`` ahead."""
    assert 5 <= history <= HISTORY, (
        "the model needs five quarters, and there are twenty"
    )
    reported_quarters = {name: values[-history:] for name, values in reported().items()}
    return {
        "quarter_end_actual": [
            serial(d) for d in quarter_ends(2021, HISTORY)[-history:]
        ],
        **reported_quarters,
        "quarter_end": [serial(d) for d in quarter_ends(2026, forecast)],
        "growth_adjustment": [0.0] * forecast,
        "cost_of_sales_pct": [0.60],
        "operating_expenses_pct": [0.22],
        "depreciation_rate": [0.025],
        "capex_pct": [0.055],
        "tax_rate": [0.25],
        "receivable_days": [55.0],
        "inventory_days": [110.0],
        "payable_days": [50.0],
        "interest_rate": [0.06],
        "minimum_cash": [20.0],
        "dividend": [4.0],
        "revolver_limit": [150.0],
        "buyback_share": [0.5],
    }


def line(label: str, *names: str, fmt: str | None = MONEY, indent: int = 1) -> Line:
    return Line(label, names, fmt, indent)


def part(label: str) -> Line:
    """The title of a part of a section: a row of no values, indented under the heading."""
    return Line(label, (), None, 1)


def step(label: str, *names: str, fmt: str | None = MONEY) -> Line:
    """A line within a part of a section."""
    return Line(label, names, fmt, 2)


def workbook() -> Workbook:
    historicals = Sheet(
        "Historicals",
        (
            Line("Quarter ending", ("quarter_end_actual",), DATE),
            Blank(),
            Heading("Income statement"),
            line("Revenue", "revenue_actual"),
            line("Cost of sales", "cost_of_sales_actual"),
            line("Gross profit", "gross_profit_actual"),
            line("Operating expenses", "operating_expenses_actual"),
            line("EBITDA", "ebitda_actual"),
            line("Depreciation", "depreciation_actual"),
            line("Operating profit", "operating_profit_actual"),
            line("Interest", "interest_actual"),
            line("Profit before tax", "profit_before_tax_actual"),
            line("Tax", "tax_actual"),
            line("Net income", "net_income_actual"),
            Blank(),
            Heading("Balance sheet"),
            *(line(label, f"{name}_actual") for name, label in ASSETS.items()),
            line("Total assets", "total_assets_actual"),
            *(line(label, f"{name}_actual") for name, label in LIABILITIES.items()),
            line("Total liabilities and equity", "total_liabilities_and_equity_actual"),
            line("Balance check", "balance_check_actual", fmt=None),
            Blank(),
            Heading("Cash flow"),
            *(line(label, f"{name}_actual") for name, label in CASH_FLOWS.items()),
        ),
        start="history",
        label_width=30,
        period_width=9,
    )
    assumptions = Sheet(
        "Assumptions",
        (
            Line("Quarter ending", ("quarter_end",), DATE),
            Blank(),
            Heading("Revenue"),
            line("Growth adjustment, year on year", "growth_adjustment", fmt=PERCENT),
            Blank(),
            Heading("Operations and financing"),
            *(
                line(label, name, f"{name}_stretched", fmt=fmt)
                for name, (label, fmt) in STRETCHED.items()
            ),
        ),
        start="forecast",
        label_width=36,
        period_width=9,
    )
    analysis = Sheet(
        "Analysis",
        (
            Line("Quarter ending", ("quarter_end_a",), DATE),
            line("Quarter", "quarter_number", fmt=COUNT, indent=0),
            Blank(),
            Heading("Revenue"),
            line("Revenue", "revenue_a"),
            line("1 quarter earlier", "revenue_1q"),
            line("2 quarters earlier", "revenue_2q"),
            line("3 quarters earlier", "revenue_3q"),
            line("4 quarters earlier", "revenue_4q"),
            line("Last 12 months", "revenue_12m"),
            line("Growth, year on year", "revenue_growth_a", fmt=PERCENT),
            line("Years of 12-month revenue", "years", fmt="0.00"),
            line("Compound annual growth", "cagr", fmt=PERCENT),
            Blank(),
            Heading("Margins and working capital"),
            line("Gross margin", "gross_margin_a", fmt=PERCENT),
            line("EBITDA margin", "ebitda_margin_a", fmt=PERCENT),
            line("Days in the quarter", "days_a", fmt=COUNT),
            line("Receivable days", "receivable_days_a", fmt=DAYS),
            line("Inventory days", "inventory_days_a", fmt=DAYS),
            line("Payable days", "payable_days_a", fmt=DAYS),
            line("Capital expenditure, % of revenue", "capex_pct_a", fmt=PERCENT),
            line("Tax, % of profit before tax", "tax_rate_a", fmt=PERCENT),
            Blank(),
            Heading("EBITDA"),
            line("EBITDA", "ebitda_a"),
            line("1 quarter earlier", "ebitda_1q"),
            line("2 quarters earlier", "ebitda_2q"),
            line("3 quarters earlier", "ebitda_3q"),
            line("Last 12 months", "ebitda_12m_a"),
            Blank(),
            Heading("Initial state, at the last reported quarter"),
            line("Quarter ending", "start_quarter_end", fmt=DATE),
            line("Revenue", "start_revenue_0q"),
            line("Revenue, 1 quarter earlier", "start_revenue_1q"),
            line("Revenue, 2 quarters earlier", "start_revenue_2q"),
            line("Revenue, 3 quarters earlier", "start_revenue_3q"),
            line("EBITDA", "start_ebitda_0q"),
            line("EBITDA, 1 quarter earlier", "start_ebitda_1q"),
            line("EBITDA, 2 quarters earlier", "start_ebitda_2q"),
            *(line(label, f"start_{name}") for name, label in BALANCES.items()),
        ),
        start="history",
        label_width=36,
        period_width=9,
    )
    forecast = Sheet(
        "Forecast",
        (
            Line("Quarter ending", ("quarter_end_f",), DATE),
            Blank(),
            Heading("Assumptions"),
            line("Revenue growth adjustment", "growth_adjustment_f", fmt=PERCENT),
            *(
                line(label, f"{name}_f", fmt=fmt)
                for name, (label, fmt) in STRETCHED.items()
            ),
            Blank(),
            Heading("Initial state"),
            line("Quarter ending", "start_quarter_end_f", fmt=DATE),
            line("Compound annual growth", "cagr_f", fmt=PERCENT),
            line("Revenue", "start_revenue_0q_f"),
            line("Revenue, 1 quarter earlier", "start_revenue_1q_f"),
            line("Revenue, 2 quarters earlier", "start_revenue_2q_f"),
            line("Revenue, 3 quarters earlier", "start_revenue_3q_f"),
            line("EBITDA", "start_ebitda_0q_f"),
            line("EBITDA, 1 quarter earlier", "start_ebitda_1q_f"),
            line("EBITDA, 2 quarters earlier", "start_ebitda_2q_f"),
            *(line(label, f"start_{name}_f") for name, label in BALANCES.items()),
            Blank(),
            Heading("Roll-forward"),
            line("Days in the quarter", "days", fmt=COUNT),
            part("Revenue"),
            step("1 quarter earlier", "revenue_1q_f"),
            step("2 quarters earlier", "revenue_2q_f"),
            step("3 quarters earlier", "revenue_3q_f"),
            step("4 quarters earlier", "revenue_4q_f"),
            step("Growth, year on year", "revenue_growth", fmt=PERCENT),
            step("Revenue", "revenue"),
            part("Operations"),
            step("Cost of sales", "cost_of_sales"),
            step("Operating expenses", "operating_expenses"),
            step("EBITDA", "ebitda"),
            step("EBITDA, 1 quarter earlier", "ebitda_1q_f"),
            step("EBITDA, 2 quarters earlier", "ebitda_2q_f"),
            step("EBITDA, 3 quarters earlier", "ebitda_3q_f"),
            step("EBITDA, last 12 months", "ebitda_12m"),
            part("PP&E"),
            step("Opening", "opening_ppe"),
            step("Capital expenditure", "capex"),
            step("Depreciation", "depreciation"),
            step("Closing", "ppe"),
            part("Working capital"),
            step("Receivables", "receivables"),
            step("Inventory", "inventory"),
            step("Payables", "payables"),
            step("Working capital", "working_capital"),
            step("Increase", "working_capital_increase"),
            part("Debt and interest"),
            step("Opening debt", "opening_debt"),
            step("Interest", "interest"),
            *(step(LIABILITIES[name], name) for name in DEBT if name != "revolver"),
            part("Profit"),
            step("Operating profit", "operating_profit"),
            step("Profit before tax", "profit_before_tax"),
            step("Tax", "tax"),
            step("Net income", "net_income"),
            step("Cash from operations", "cash_from_operations"),
            part("Waterfall"),
            step("Opening cash", "opening_cash"),
            step("Available above the minimum", "available"),
            step("Dividends", "dividends"),
            step("After dividends", "after_dividends"),
            step("Opening revolver", "opening_revolver"),
            step("Revolver drawn (repaid)", "revolver_drawn"),
            step("Closing revolver", "revolver"),
            step("After the revolver", "after_revolver"),
            step("Share buybacks", "buybacks"),
            step("Closing cash", "cash"),
            step("Debt", "debt"),
            part("Equity"),
            step("Opening", "opening_equity"),
            step("Closing", "equity"),
            Blank(),
            Heading("Income statement"),
            line("Revenue", "revenue_is"),
            line("Cost of sales", "cost_of_sales_is"),
            line("Gross profit", "gross_profit"),
            line("Gross margin", "gross_margin", fmt=PERCENT, indent=2),
            line("Operating expenses", "operating_expenses_is"),
            line("EBITDA", "ebitda_is"),
            line("EBITDA margin", "ebitda_margin", fmt=PERCENT, indent=2),
            line("Depreciation", "depreciation_is"),
            line("Operating profit", "operating_profit_is"),
            line("Interest", "interest_is"),
            line("Profit before tax", "profit_before_tax_is"),
            line("Tax", "tax_is"),
            line("Net income", "net_income_is"),
            line("Net margin", "net_margin", fmt=PERCENT, indent=2),
            Blank(),
            Heading("Balance sheet"),
            *(line(label, f"{name}_bs") for name, label in ASSETS.items()),
            line("Total assets", "total_assets"),
            *(line(label, f"{name}_bs") for name, label in LIABILITIES.items()),
            line("Total liabilities and equity", "total_liabilities_and_equity"),
            line("Balance check", "balance_check", fmt=None),
            Blank(),
            Heading("Cash flow statement"),
            line("Net income", "net_income_cf"),
            line("Depreciation", "depreciation_cf"),
            line("Change in working capital", "working_capital_cf"),
            line("Cash from operations", "cash_from_operations_cf"),
            line("Capital expenditure", "capex_cf"),
            line("Revolver drawn (repaid)", "revolver_drawn_cf"),
            line("Dividends", "dividends_cf"),
            line("Share buybacks", "buybacks_cf"),
            line("Cash from financing", "cash_from_financing"),
            line("Net change in cash", "net_change_in_cash"),
            line("Opening cash", "opening_cash_cf"),
            line("Closing cash", "cash_cf"),
            Blank(),
            Heading("Ratios"),
            part("Leverage"),
            step("Net debt", "net_debt"),
            step("Debt / EBITDA, last 12 months", "debt_to_ebitda", fmt=MULTIPLE),
            step("Net debt / EBITDA", "net_debt_to_ebitda", fmt=MULTIPLE),
            part("Coverage"),
            step("EBITDA / interest, quarter", "interest_cover", fmt=MULTIPLE),
            part("Liquidity"),
            step("Revolver undrawn", "revolver_room"),
            step("Cash and undrawn revolver", "liquidity"),
        ),
        start="forecast",
        label_width=34,
        period_width=9,
    )
    return Workbook((historicals, assumptions, analysis, forecast))


def outputs() -> dict[str, str]:
    """The files this example writes, by name: the model, the workbook cells and values."""
    circuit = build().unwrap()
    result = export(circuit, data(), layout=workbook()).unwrap()
    return {
        "quarterly.uku": write_uku(circuit),
        "quarterly.yup": result.yup,
        "quarterly.values.csv": result.values_csv,
    }


def main() -> None:
    """Write this example's files, and its workbook, to ``target/`` at the repository root."""
    target = Path(__file__).resolve().parent.parent / "target"
    target.mkdir(exist_ok=True)
    for name, text in outputs().items():
        (target / name).write_text(text, encoding="utf-8", newline="")
        print(f"wrote {target / name}")
    result = export(build().unwrap(), data(), layout=workbook()).unwrap()
    (target / "quarterly.xlsx").write_bytes(result.xlsx().unwrap())
    print(f"wrote {target / 'quarterly.xlsx'}")


if __name__ == "__main__":
    main()
