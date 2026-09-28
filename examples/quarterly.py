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

The workbook is dressed as a modeller would dress it. Every number typed in is blue and
every formula black; each section sits under a pale band, totals under a line and grand
totals over a double one, and ratios and checks are in italics. The dates, labels and
single values stay in view as a sheet scrolls, and each sheet's tab has its own colour.

Revenue grows on the same quarter a year earlier, so the seasons survive. Its growth is the
compound annual growth of the history's twelve-month revenue (which is why the model needs
``first`` and a fractional power), plus the effects of GDP growth and of the company's own
price changes, each measured from its average over the same quarters, since the compound
growth already includes the economy the history had, plus a surprise. The surprise follows a
seasonal autoregression, SARIMAX(1,0,0)(1,0,0) with a season of four quarters and those
two exogenous regressors: each quarter's surprise carries part of the last quarter's and
part of the same quarter's a year earlier. The coefficients are loaded, not fitted, and
the history's surprises seed the forecast.

The forecast looks back only one quarter. Anything further back is carried as state: the
last four quarters' revenue and the last five surprises, each row the row above one
quarter later.

Cash runs through a waterfall every quarter. Whatever is above a minimum balance, once
operations and investment are paid for, pays a dividend up to a target; what is left repays
the revolver, or the revolver covers a shortfall up to its limit; and a share of anything
left over buys back shares. There is no IF in the language, so every step is a minimum or a
maximum.

The debt is two bonds and two floating loans. Each bond pays a fixed coupon and is repaid
whole at maturity: its quarters to maturity count down one a quarter, and, with no
comparisons in the language, it is outstanding for ``min(1, max(0, quarters left))`` of its
face. The term loan and the revolver pay a margin over a base rate that the assumptions set
quarter by quarter, so the model's interest follows rates. Interest is on opening balances,
so there is no circular reference. The balance sheet balances by construction in every
quarter.
"""

from datetime import date
from pathlib import Path

from yupana import LineStyle
from yupana.result import Result

from ukumari import (
    GRAND_TOTAL,
    HEADING,
    INPUT,
    TOTAL,
    Blank,
    Heading,
    Line,
    Model,
    Sheet,
    Style,
    View,
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

MONEY = "_(#,##0.0_);(#,##0.0);_(-_)"
PERCENT = "0.0%"
DAYS = "0.0"
DATE = "mmm-yy"
COUNT = "0"
MULTIPLE = '0.0"x"'

# How the workbook looks: the dates across the top over a line, each section under a pale
# band, totals under a line and grand totals over a double one, ratios and checks in
# italics, a thin gap between sections, and every number typed in, in blue.
HEADER = Style(bold=True, border_bottom=LineStyle.THIN)
SECTION = HEADING | Style(fill="DDEBF7")
ASIDE = Style(italic=True)
GAP = Blank(height=8)

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

# Single values on the Assumptions sheet, each stretched across the forecast: model name,
# label and number format.
REVENUE_MODEL = {
    "gdp_beta": ("Growth per point of GDP growth", "0.00"),
    "price_beta": ("Growth per point of price change", "0.00"),
    "ar": ("Surprise kept from the last quarter", "0.00"),
    "seasonal_ar": ("Surprise kept from a year earlier", "0.00"),
}
OPERATIONS = {
    "cost_of_sales_pct": ("Cost of sales, % of revenue", PERCENT),
    "operating_expenses_pct": ("Operating expenses, % of revenue", PERCENT),
    "depreciation_rate": ("Depreciation, % of opening PP&E", PERCENT),
    "capex_pct": ("Capital expenditure, % of revenue", PERCENT),
    "tax_rate": ("Tax, % of profit before tax", PERCENT),
    "receivable_days": ("Receivables, days of revenue", DAYS),
    "inventory_days": ("Inventory, days of cost of sales", DAYS),
    "payable_days": ("Payables, days of cost of sales", DAYS),
}
FINANCING = {
    "bond_a_coupon": ("Bond A coupon", PERCENT),
    "bond_b_coupon": ("Bond B coupon", PERCENT),
    "term_loan_margin": ("Term loan, margin over base rate", PERCENT),
    "term_loan_repayment": ("Term loan, repayment a quarter", MONEY),
    "revolver_margin": ("Revolver, margin over base rate", PERCENT),
    "revolver_limit": ("Revolver limit", MONEY),
    "minimum_cash": ("Minimum cash", MONEY),
    "dividend": ("Target dividend a quarter", MONEY),
    "buyback_share": ("Buybacks, % of cash left over", PERCENT),
}
STRETCHED = REVENUE_MODEL | OPERATIONS | FINANCING

# Single values used once, as the seed of a countdown, so never stretched.
MATURITIES = {
    "bond_a_quarters": "Bond A, quarters to maturity",
    "bond_b_quarters": "Bond B, quarters to maturity",
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
    "_bs": BALANCES,
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
    gdp_growth_actual = m.input("gdp_growth_actual", history)
    price_change_actual = m.input("price_change_actual", history)
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
    gdp_growth = m.input("gdp_growth", forecast)
    price_change = m.input("price_change", forecast)
    base_rate = m.input("base_rate", forecast)
    maturity = {name: m.input(name, scalar) for name in MATURITIES}
    single: dict[str, Declared] = {}
    stretched: dict[str, Declared] = {}
    for name in STRETCHED:
        single[name] = m.input(name, scalar)
        stretched[name] = m.vector(f"{name}_stretched", forecast)
        stretched[name].define(single[name])

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
    # Twelve-month revenue first covers a whole year at the fourth quarter, so every
    # quarter after it has a year-on-year growth rate, and a quarter is a quarter-year.
    growth_quarters, cagr = m.vectors(scalar, "growth_quarters", "cagr")
    growth_quarters.define(last(quarter_number) - 4)
    cagr.define((last(revenue_12m) / first(revenue_12m)) ** (4 / growth_quarters) - 1)
    # The compound growth already includes the economy the history had, so the economy's
    # effects are measured from its average over the quarters that have a growth rate:
    # a running total, carried a quarter at a time, over their count.
    (
        revenue_growth_a,
        gdp_total,
        price_total,
        gdp_effect_a,
        price_effect_a,
        surprise_a,
    ) = m.vectors(
        history[4:],
        "revenue_growth_a",
        "gdp_total",
        "price_total",
        "gdp_effect_a",
        "price_effect_a",
        "surprise_a",
    )
    revenue_growth_a.define(revenue_a / revenue_4q - 1)
    gdp_total.define(lag(gdp_total, seed=0) + gdp_growth_actual)
    price_total.define(lag(price_total, seed=0) + price_change_actual)
    gdp_average, price_average = m.vectors(scalar, "gdp_average", "price_average")
    gdp_average.define(last(gdp_total) / growth_quarters)
    price_average.define(last(price_total) / growth_quarters)
    # Each quarter's growth, less what the compound growth and the economy explain, is
    # that quarter's surprise.
    gdp_effect_a.define(single["gdp_beta"] * (gdp_growth_actual - gdp_average))
    price_effect_a.define(single["price_beta"] * (price_change_actual - price_average))
    surprise_a.define(revenue_growth_a - cagr - gdp_effect_a - price_effect_a)
    surprise_earlier = earlier("surprise", surprise_a, history[4:], 4)

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
    start_surprise = [
        at_the_end(f"start_surprise_{k}q", source)
        for k, source in enumerate((surprise_a, *surprise_earlier))
    ]
    start_balance = {
        name: at_the_end(f"start_{name}", actual[name]) for name in BALANCES
    }

    # --- Forecast: copies of the assumptions and of the initial state. ------------------
    quarter_end_f = copy("quarter_end_f", quarter_end)
    growth_adjustment_f = copy("growth_adjustment_f", growth_adjustment)
    gdp_growth_f = copy("gdp_growth_f", gdp_growth)
    price_change_f = copy("price_change_f", price_change)
    base_rate_f = copy("base_rate_f", base_rate)
    maturity_f = {name: copy(f"{name}_f", given) for name, given in maturity.items()}
    use = {name: copy(f"{name}_f", row) for name, row in stretched.items()}
    start_quarter_end_f = copy("start_quarter_end_f", start_quarter_end)
    cagr_f = copy("cagr_f", cagr)
    gdp_average_f = copy("gdp_average_f", gdp_average)
    price_average_f = copy("price_average_f", price_average)
    start_revenue_f = [copy(f"{s.name}_f", s) for s in start_revenue]
    start_ebitda_f = [copy(f"{s.name}_f", s) for s in start_ebitda]
    start_surprise_f = [copy(f"{s.name}_f", s) for s in start_surprise]
    start = {name: copy(f"{s.name}_f", s) for name, s in start_balance.items()}

    # --- Forecast: the roll-forward, one quarter at a time. -----------------------------
    days = m.vector("days", forecast)
    days.define(quarter_end_f - lag(quarter_end_f, seed=start_quarter_end_f))

    def rolled_on(name: str, source: Declared, seeds: list[Declared]) -> list[Declared]:
        """``source`` one, two, … quarters earlier, each row the row above one quarter
        later, the first quarters seeded with the initial state."""
        rows = []
        before = source
        for k, seed in enumerate(seeds, start=1):
            row = m.vector(f"{name}_{k}q_f", forecast)
            row.define(lag(before, seed=seed))
            rows.append(row)
            before = row
        return rows

    # The surprise: SARIMAX(1,0,0)(1,0,0) with a season of four quarters, so it needs the
    # surprises one, four and five quarters earlier.
    surprise, gdp_effect, price_effect = m.vectors(
        forecast, "surprise", "gdp_effect", "price_effect"
    )
    surprise_state = rolled_on("surprise", surprise, start_surprise_f)
    ar, seasonal_ar = use["ar"], use["seasonal_ar"]
    surprise.define(
        ar * surprise_state[0]
        + seasonal_ar * surprise_state[3]
        - ar * seasonal_ar * surprise_state[4]
    )
    gdp_effect.define(use["gdp_beta"] * (gdp_growth_f - gdp_average_f))
    price_effect.define(use["price_beta"] * (price_change_f - price_average_f))

    # Revenue grows on the same quarter a year earlier. The state is the last four
    # quarters' revenue: each row is the row above, one quarter later.
    revenue, revenue_growth = m.vectors(forecast, "revenue", "revenue_growth")
    revenue_state = rolled_on("revenue", revenue, start_revenue_f)
    revenue_growth.define(
        cagr_f + growth_adjustment_f + gdp_effect + price_effect + surprise
    )
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

    # A bond is repaid whole at maturity. Its quarters to maturity count down one a
    # quarter, and, with no comparisons in the language, it is outstanding for
    # min(1, max(0, quarters left)) of its face: all of it until maturity, then none.
    def bond(name: str) -> tuple[Declared, Declared, Declared]:
        left, opening, closing, repaid, interest = m.vectors(
            forecast,
            f"{name}_quarters_left",
            f"opening_{name}",
            name,
            f"{name}_repaid",
            f"{name}_interest",
        )
        left.define(lag(left, seed=maturity_f[f"{name}_quarters"]) - 1)
        opening.define(lag(closing, seed=start[name]))
        closing.define(start[name] * minimum(1, maximum(left, 0)))
        repaid.define(opening - closing)
        interest.define(opening * use[f"{name}_coupon"] / 4)
        return closing, repaid, interest

    bond_a, bond_a_repaid, bond_a_interest = bond("bond_a")
    bond_b, bond_b_repaid, bond_b_interest = bond("bond_b")

    # The term loan repays a fixed amount a quarter, until nothing is left, and floats.
    opening_term_loan, term_loan_repaid, term_loan, term_loan_interest = m.vectors(
        forecast,
        "opening_term_loan",
        "term_loan_repaid",
        "term_loan",
        "term_loan_interest",
    )
    opening_term_loan.define(lag(term_loan, seed=start["term_loan"]))
    term_loan_repaid.define(minimum(use["term_loan_repayment"], opening_term_loan))
    term_loan.define(opening_term_loan - term_loan_repaid)
    term_loan_interest.define(
        opening_term_loan * (base_rate_f + use["term_loan_margin"]) / 4
    )

    # The revolver moves with the waterfall below, and floats too. Interest is on opening
    # balances, so the revolver drawn this quarter costs nothing until the next: no
    # circular reference.
    opening_revolver, revolver, revolver_interest = m.vectors(
        forecast, "opening_revolver", "revolver", "revolver_interest"
    )
    opening_revolver.define(lag(revolver, seed=start["revolver"]))
    revolver_interest.define(
        opening_revolver * (base_rate_f + use["revolver_margin"]) / 4
    )
    scheduled_repayment, interest, debt = m.vectors(
        forecast, "scheduled_repayment", "interest", "debt"
    )
    scheduled_repayment.define(bond_a_repaid + bond_b_repaid + term_loan_repaid)
    interest.define(
        bond_a_interest + bond_b_interest + term_loan_interest + revolver_interest
    )
    debt.define(revolver + bond_a + bond_b + term_loan)

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
    # Cash above the minimum once operations, investment and the debt falling due are paid
    # for.
    available.define(
        opening_cash
        - use["minimum_cash"]
        + cash_from_operations
        - capex
        - scheduled_repayment
    )
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

    # Twelve-month EBITDA, for leverage, needs the last three quarters' as state.
    ebitda_state = rolled_on("ebitda", ebitda, start_ebitda_f)
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
        "bond_a": bond_a,
        "bond_b": bond_b,
        "term_loan": term_loan,
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
        debt_repaid_cf,
        dividends_cf,
        buybacks_cf,
        cash_from_financing,
        net_change_in_cash,
    ) = m.vectors(
        forecast,
        "working_capital_cf",
        "cash_from_operations_cf",
        "capex_cf",
        "debt_repaid_cf",
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
    debt_repaid_cf.define(-scheduled_repayment)
    dividends_cf.define(-dividends)
    buybacks_cf.define(-buybacks)
    cash_from_financing.define(
        debt_repaid_cf + flow("revolver_drawn") + dividends_cf + buybacks_cf
    )
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
    reported["gdp_growth_actual"] = [round(g / 100, 6) for g in gdp_growth]
    reported["price_change_actual"] = [round(p / 100, 6) for p in price_change]
    return reported


def data(history: int = HISTORY, forecast: int = FORECAST) -> dict[str, list[float]]:
    """The last ``history`` of the twenty reported quarters, and ``forecast`` ahead."""
    assert 9 <= history <= HISTORY, (
        "the model needs nine quarters, and there are twenty"
    )
    reported_quarters = {name: values[-history:] for name, values in reported().items()}
    return {
        "quarter_end_actual": [
            serial(d) for d in quarter_ends(2021, HISTORY)[-history:]
        ],
        **reported_quarters,
        "quarter_end": [serial(d) for d in quarter_ends(2026, forecast)],
        "growth_adjustment": [0.0] * forecast,
        # The economy slows a little in 2026, and grows at 2% from 2028.
        "gdp_growth": (
            [0.018, 0.016, 0.015, 0.016, 0.018, 0.02, 0.021, 0.022] + [0.02] * forecast
        )[:forecast],
        "price_change": (
            [0.025, 0.024, 0.023, 0.022, 0.022, 0.023, 0.024, 0.025]
            + [0.025] * forecast
        )[:forecast],
        "gdp_beta": [1.5],
        "price_beta": [-0.5],
        "ar": [0.6],
        "seasonal_ar": [-0.3],
        # Rates fall a quarter point a quarter to 3%, and stay there.
        "base_rate": [max(0.03, 0.04 - 0.0025 * t) for t in range(forecast)],
        "cost_of_sales_pct": [0.60],
        "operating_expenses_pct": [0.22],
        "depreciation_rate": [0.025],
        "capex_pct": [0.055],
        "tax_rate": [0.25],
        "receivable_days": [55.0],
        "inventory_days": [110.0],
        "payable_days": [50.0],
        "bond_a_coupon": [0.0475],
        "bond_b_coupon": [0.06],
        "term_loan_margin": [0.025],
        "term_loan_repayment": [2.5],
        "revolver_margin": [0.0175],
        "revolver_limit": [150.0],
        "minimum_cash": [20.0],
        "dividend": [4.0],
        "buyback_share": [0.5],
        # Bond A is repaid at the end of 2027, and bond B in the middle of 2030.
        "bond_a_quarters": [8.0],
        "bond_b_quarters": [18.0],
    }


def line(
    label: str,
    *names: str,
    fmt: str | None = MONEY,
    indent: int = 1,
    style: Style | None = None,
) -> Line:
    return Line(label, names, fmt, indent, style)


def heading(label: str) -> Heading:
    """The title of a section, on a band across the sheet."""
    return Heading(label, SECTION)


def part(label: str) -> Line:
    """The title of a part of a section: a row of no values, indented under the heading."""
    return Line(label, (), None, 1, ASIDE)


def step(label: str, *names: str, fmt: str | None = MONEY) -> Line:
    """A line within a part of a section."""
    return Line(label, names, fmt, 2)


def view(tab: str) -> View:
    """How every sheet is shown: without gridlines, with the dates and the labels and
    single values held in view as it scrolls, and with a tab of its own colour."""
    return View(
        gridlines=False, zoom=90, tab_color=tab, freeze_rows=1, freeze_columns=2
    )


def workbook() -> Workbook:
    historicals = Sheet(
        "Historicals",
        (
            Line("Quarter ending", ("quarter_end_actual",), DATE, style=HEADER),
            GAP,
            heading("Income statement"),
            line("Revenue", "revenue_actual"),
            line("Cost of sales", "cost_of_sales_actual"),
            line("Gross profit", "gross_profit_actual", style=TOTAL),
            line("Operating expenses", "operating_expenses_actual"),
            line("EBITDA", "ebitda_actual", style=TOTAL),
            line("Depreciation", "depreciation_actual"),
            line("Operating profit", "operating_profit_actual", style=TOTAL),
            line("Interest", "interest_actual"),
            line("Profit before tax", "profit_before_tax_actual", style=TOTAL),
            line("Tax", "tax_actual"),
            line("Net income", "net_income_actual", style=GRAND_TOTAL),
            GAP,
            heading("Balance sheet"),
            *(line(label, f"{name}_actual") for name, label in ASSETS.items()),
            line("Total assets", "total_assets_actual", style=GRAND_TOTAL),
            *(line(label, f"{name}_actual") for name, label in LIABILITIES.items()),
            line(
                "Total liabilities and equity",
                "total_liabilities_and_equity_actual",
                style=GRAND_TOTAL,
            ),
            line("Balance check", "balance_check_actual", fmt=None, style=ASIDE),
            GAP,
            heading("Cash flow"),
            *(line(label, f"{name}_actual") for name, label in CASH_FLOWS.items()),
            GAP,
            heading("Economy"),
            line("GDP growth, year on year", "gdp_growth_actual", fmt=PERCENT),
            line("Own price change, year on year", "price_change_actual", fmt=PERCENT),
        ),
        start="history",
        label_width=32,
        period_width=9,
        view=view("A6A6A6"),
    )
    assumptions = Sheet(
        "Assumptions",
        (
            Line("Quarter ending", ("quarter_end",), DATE, style=HEADER),
            GAP,
            heading("Revenue"),
            line("Growth adjustment, year on year", "growth_adjustment", fmt=PERCENT),
            line("GDP growth, year on year", "gdp_growth", fmt=PERCENT),
            line("Own price change, year on year", "price_change", fmt=PERCENT),
            *(
                line(label, name, f"{name}_stretched", fmt=fmt)
                for name, (label, fmt) in REVENUE_MODEL.items()
            ),
            GAP,
            heading("Operations"),
            *(
                line(label, name, f"{name}_stretched", fmt=fmt)
                for name, (label, fmt) in OPERATIONS.items()
            ),
            GAP,
            heading("Financing"),
            line("Base rate", "base_rate", fmt=PERCENT),
            *(
                line(label, name, f"{name}_stretched", fmt=fmt)
                for name, (label, fmt) in FINANCING.items()
            ),
            *(line(label, name, fmt=COUNT) for name, label in MATURITIES.items()),
        ),
        start="forecast",
        label_width=38,
        period_width=9,
        view=view("0070C0"),
    )
    analysis = Sheet(
        "Analysis",
        (
            Line("Quarter ending", ("quarter_end_a",), DATE, style=HEADER),
            line("Quarter", "quarter_number", fmt=COUNT, indent=0),
            GAP,
            heading("Revenue"),
            line("Revenue", "revenue_a"),
            line("1 quarter earlier", "revenue_1q"),
            line("2 quarters earlier", "revenue_2q"),
            line("3 quarters earlier", "revenue_3q"),
            line("4 quarters earlier", "revenue_4q"),
            line("Last 12 months", "revenue_12m", style=TOTAL),
            line("Quarters with a growth rate", "growth_quarters", fmt=COUNT),
            line("Compound annual growth", "cagr", fmt=PERCENT),
            line("Growth, year on year", "revenue_growth_a", fmt=PERCENT),
            line("GDP growth, running total", "gdp_total", fmt=PERCENT),
            line("Price change, running total", "price_total", fmt=PERCENT),
            line("GDP growth, average", "gdp_average", fmt=PERCENT),
            line("Own price change, average", "price_average", fmt=PERCENT),
            line("GDP effect", "gdp_effect_a", fmt=PERCENT),
            line("Price effect", "price_effect_a", fmt=PERCENT),
            line("Surprise", "surprise_a", fmt=PERCENT),
            line("1 quarter earlier", "surprise_1q", fmt=PERCENT),
            line("2 quarters earlier", "surprise_2q", fmt=PERCENT),
            line("3 quarters earlier", "surprise_3q", fmt=PERCENT),
            line("4 quarters earlier", "surprise_4q", fmt=PERCENT),
            GAP,
            heading("Margins and working capital"),
            line("Gross margin", "gross_margin_a", fmt=PERCENT),
            line("EBITDA margin", "ebitda_margin_a", fmt=PERCENT),
            line("Days in the quarter", "days_a", fmt=COUNT),
            line("Receivable days", "receivable_days_a", fmt=DAYS),
            line("Inventory days", "inventory_days_a", fmt=DAYS),
            line("Payable days", "payable_days_a", fmt=DAYS),
            line("Capital expenditure, % of revenue", "capex_pct_a", fmt=PERCENT),
            line("Tax, % of profit before tax", "tax_rate_a", fmt=PERCENT),
            GAP,
            heading("EBITDA"),
            line("EBITDA", "ebitda_a"),
            line("1 quarter earlier", "ebitda_1q"),
            line("2 quarters earlier", "ebitda_2q"),
            line("3 quarters earlier", "ebitda_3q"),
            line("Last 12 months", "ebitda_12m_a", style=TOTAL),
            GAP,
            heading("Initial state, at the last reported quarter"),
            line("Quarter ending", "start_quarter_end", fmt=DATE),
            line("Revenue", "start_revenue_0q"),
            line("Revenue, 1 quarter earlier", "start_revenue_1q"),
            line("Revenue, 2 quarters earlier", "start_revenue_2q"),
            line("Revenue, 3 quarters earlier", "start_revenue_3q"),
            line("EBITDA", "start_ebitda_0q"),
            line("EBITDA, 1 quarter earlier", "start_ebitda_1q"),
            line("EBITDA, 2 quarters earlier", "start_ebitda_2q"),
            line("Surprise", "start_surprise_0q", fmt=PERCENT),
            *(
                line(
                    f"Surprise, {k} quarter{'s' if k > 1 else ''} earlier",
                    name,
                    fmt=PERCENT,
                )
                for k, name in enumerate(
                    (
                        "start_surprise_1q",
                        "start_surprise_2q",
                        "start_surprise_3q",
                        "start_surprise_4q",
                    ),
                    start=1,
                )
            ),
            *(line(label, f"start_{name}") for name, label in BALANCES.items()),
        ),
        start="history",
        label_width=38,
        period_width=9,
        view=view("70AD47"),
    )
    forecast = Sheet(
        "Forecast",
        (
            Line("Quarter ending", ("quarter_end_f",), DATE, style=HEADER),
            GAP,
            heading("Assumptions"),
            line("Revenue growth adjustment", "growth_adjustment_f", fmt=PERCENT),
            line("GDP growth", "gdp_growth_f", fmt=PERCENT),
            line("Own price change", "price_change_f", fmt=PERCENT),
            *(
                line(label, f"{name}_f", fmt=fmt)
                for name, (label, fmt) in REVENUE_MODEL.items()
            ),
            *(
                line(label, f"{name}_f", fmt=fmt)
                for name, (label, fmt) in OPERATIONS.items()
            ),
            line("Base rate", "base_rate_f", fmt=PERCENT),
            *(
                line(label, f"{name}_f", fmt=fmt)
                for name, (label, fmt) in FINANCING.items()
            ),
            *(
                line(label, f"{name}_f", fmt=COUNT)
                for name, label in MATURITIES.items()
            ),
            GAP,
            heading("Initial state"),
            line("Quarter ending", "start_quarter_end_f", fmt=DATE),
            line("Compound annual growth", "cagr_f", fmt=PERCENT),
            line("GDP growth, average", "gdp_average_f", fmt=PERCENT),
            line("Own price change, average", "price_average_f", fmt=PERCENT),
            line("Revenue", "start_revenue_0q_f"),
            line("Revenue, 1 quarter earlier", "start_revenue_1q_f"),
            line("Revenue, 2 quarters earlier", "start_revenue_2q_f"),
            line("Revenue, 3 quarters earlier", "start_revenue_3q_f"),
            line("EBITDA", "start_ebitda_0q_f"),
            line("EBITDA, 1 quarter earlier", "start_ebitda_1q_f"),
            line("EBITDA, 2 quarters earlier", "start_ebitda_2q_f"),
            line("Surprise", "start_surprise_0q_f", fmt=PERCENT),
            *(
                line(
                    f"Surprise, {k} quarter{'s' if k > 1 else ''} earlier",
                    name,
                    fmt=PERCENT,
                )
                for k, name in enumerate(
                    (
                        "start_surprise_1q_f",
                        "start_surprise_2q_f",
                        "start_surprise_3q_f",
                        "start_surprise_4q_f",
                    ),
                    start=1,
                )
            ),
            *(line(label, f"start_{name}_f") for name, label in BALANCES.items()),
            GAP,
            heading("Roll-forward"),
            line("Days in the quarter", "days", fmt=COUNT),
            part("Surprise"),
            *(
                step(
                    f"{k} quarter{'s' if k > 1 else ''} earlier",
                    f"surprise_{k}q_f",
                    fmt=PERCENT,
                )
                for k in range(1, 6)
            ),
            step("Surprise", "surprise", fmt=PERCENT),
            part("Revenue"),
            step("1 quarter earlier", "revenue_1q_f"),
            step("2 quarters earlier", "revenue_2q_f"),
            step("3 quarters earlier", "revenue_3q_f"),
            step("4 quarters earlier", "revenue_4q_f"),
            step("GDP effect", "gdp_effect", fmt=PERCENT),
            step("Price effect", "price_effect", fmt=PERCENT),
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
            *(
                row
                for name in ("bond_a", "bond_b")
                for row in (
                    part(LIABILITIES[name]),
                    step("Quarters to maturity", f"{name}_quarters_left", fmt=COUNT),
                    step("Opening", f"opening_{name}"),
                    step("Repaid", f"{name}_repaid"),
                    step("Closing", name),
                )
            ),
            part("Term loan"),
            step("Opening", "opening_term_loan"),
            step("Repaid", "term_loan_repaid"),
            step("Closing", "term_loan"),
            part("Interest"),
            step("Bond A", "bond_a_interest"),
            step("Bond B", "bond_b_interest"),
            step("Term loan", "term_loan_interest"),
            step("Revolver", "revolver_interest"),
            step("Total", "interest"),
            part("Profit"),
            step("Operating profit", "operating_profit"),
            step("Profit before tax", "profit_before_tax"),
            step("Tax", "tax"),
            step("Net income", "net_income"),
            step("Cash from operations", "cash_from_operations"),
            part("Waterfall"),
            step("Opening cash", "opening_cash"),
            step("Debt falling due", "scheduled_repayment"),
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
            GAP,
            heading("Income statement"),
            line("Revenue", "revenue_is"),
            line("Cost of sales", "cost_of_sales_is"),
            line("Gross profit", "gross_profit", style=TOTAL),
            line("Gross margin", "gross_margin", fmt=PERCENT, indent=2, style=ASIDE),
            line("Operating expenses", "operating_expenses_is"),
            line("EBITDA", "ebitda_is", style=TOTAL),
            line("EBITDA margin", "ebitda_margin", fmt=PERCENT, indent=2, style=ASIDE),
            line("Depreciation", "depreciation_is"),
            line("Operating profit", "operating_profit_is", style=TOTAL),
            line("Interest", "interest_is"),
            line("Profit before tax", "profit_before_tax_is", style=TOTAL),
            line("Tax", "tax_is"),
            line("Net income", "net_income_is", style=GRAND_TOTAL),
            line("Net margin", "net_margin", fmt=PERCENT, indent=2, style=ASIDE),
            GAP,
            heading("Balance sheet"),
            *(line(label, f"{name}_bs") for name, label in ASSETS.items()),
            line("Total assets", "total_assets", style=GRAND_TOTAL),
            *(line(label, f"{name}_bs") for name, label in LIABILITIES.items()),
            line(
                "Total liabilities and equity",
                "total_liabilities_and_equity",
                style=GRAND_TOTAL,
            ),
            line("Balance check", "balance_check", fmt=None, style=ASIDE),
            GAP,
            heading("Cash flow statement"),
            line("Net income", "net_income_cf"),
            line("Depreciation", "depreciation_cf"),
            line("Change in working capital", "working_capital_cf"),
            line("Cash from operations", "cash_from_operations_cf", style=TOTAL),
            line("Capital expenditure", "capex_cf"),
            line("Debt repaid", "debt_repaid_cf"),
            line("Revolver drawn (repaid)", "revolver_drawn_cf"),
            line("Dividends", "dividends_cf"),
            line("Share buybacks", "buybacks_cf"),
            line("Cash from financing", "cash_from_financing", style=TOTAL),
            line("Net change in cash", "net_change_in_cash", style=TOTAL),
            line("Opening cash", "opening_cash_cf"),
            line("Closing cash", "cash_cf", style=GRAND_TOTAL),
            GAP,
            heading("Ratios"),
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
        label_width=38,
        period_width=9,
        view=view("ED7D31"),
    )
    return Workbook((historicals, assumptions, analysis, forecast), input_style=INPUT)


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
