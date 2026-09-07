"""Read-only access to a Beancount ledger via the beancount library."""

from __future__ import annotations

import bisect
import calendar
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import beanquery
from beancount import loader
from beancount.core import data, getters, position, prices, realization
from beancount.core.inventory import Inventory


DISPLAYED_DIRECTIVES = (
    data.Transaction,
    data.Open,
    data.Close,
    data.Balance,
    data.Pad,
    data.Note,
    data.Price,
    data.Event,
    data.Custom,
    data.Query,
    data.Document,
    data.Commodity,
)


@dataclass
class RegisterRow:
    """One line of a register report: a transaction's effect on an account.

    ``posting_amount`` is the sum of that transaction's posting(s) to the
    account (or its sub-accounts) — usually one posting, but a transaction
    could post to the account and a sub-account, or the account twice.
    ``running_balance`` is the cumulative balance immediately after this row.
    """

    date: datetime.date
    narration: str
    posting_amount: Inventory
    running_balance: Inventory


@dataclass
class IncomeStatement:
    """Per-account and total Income/Expenses balances over a period.

    Amounts follow reporting convention: income is sign-inverted so revenue
    reads positive, and ``net`` is income minus expenses (positive = profit).
    """

    income: list[tuple[str, Inventory]]
    expenses: list[tuple[str, Inventory]]
    income_total: Inventory
    expenses_total: Inventory
    net: Inventory


@dataclass
class BalanceSheet:
    """Per-account and total Assets/Liabilities/Equity balances as of a date.

    Assets amounts are as recorded (debit-normal: a positive balance for a
    normal asset). Liabilities and Equity are sign-inverted so a normal
    credit balance reads positive, the same convention ``IncomeStatement``
    uses for Income. ``net_income`` is the current period's income minus
    expenses (see ``Ledger.income_statement``), the implicit line a
    bean-close would otherwise fold into Equity — include it so:

        assets_total == liabilities_total + equity_total + net_income
    """

    assets: list[tuple[str, Inventory]]
    liabilities: list[tuple[str, Inventory]]
    equity: list[tuple[str, Inventory]]
    assets_total: Inventory
    liabilities_total: Inventory
    equity_total: Inventory
    net_income: Inventory


@dataclass
class Holding:
    """One account's aggregated position in a single commodity, at cost.

    ``cost_basis`` sums each contributing posting's ``quantity * cost.number``
    as an ``Inventory`` (rather than a bare ``Decimal``) so lots opened in
    different cost currencies don't get mixed.

    ``market_value`` is the latest known price (see
    ``Ledger.holdings``/``build_price_map``) times ``quantity``, preferring a
    direct quote in the operating currency; if none exists but the cost
    currency has one, that's used instead (``priced_in_operating_currency`` is
    ``False`` in that case, so it's clear the amount isn't in the ledger's
    operating currency). ``None`` when no price is known in either currency —
    "no price available" rather than a crash.
    """

    account: str
    commodity: str
    quantity: Decimal
    cost_basis: Inventory
    market_value: data.Amount | None
    priced_in_operating_currency: bool


@dataclass
class HoldingsReport:
    """Per-commodity/account holdings plus a net-worth total.

    ``net_worth`` only includes holdings whose ``market_value`` is expressed
    in the operating currency — the "converted to the operating currency
    where prices allow" part of the report; holdings with no price, or with
    a price only in their cost currency, are shown individually but excluded
    from the total rather than silently mis-converted.
    """

    holdings: list[Holding]
    net_worth: Inventory
    operating_currency: str | None


@dataclass
class BudgetEntry:
    """A parsed ``custom "budget"`` directive (Fava's convention).

    Fava's shape is ``YYYY-MM-DD custom "budget" Account "interval" NN.NN
    CCY``, currently stored by beancount as generic ``data.Custom.values``
    (see ``Ledger._parse_budgets``). ``interval`` is canonicalized to one of
    the five long forms (``daily``/``weekly``/``monthly``/``quarterly``/
    ``yearly``) regardless of whether the directive spelled it out in long
    or short form (``day``/``week``/``month``/``quarter``/``year``), so
    downstream code (proration, in a later task) only ever has to handle
    one spelling per interval.
    """

    date: datetime.date
    account: str
    interval: str
    amount: data.Amount


# Fava's five accepted interval spellings, long and short form, mapped to
# their canonical long form. Matching is case-insensitive (see
# ``Ledger._parse_budgets``).
_BUDGET_INTERVALS = {
    "daily": "daily",
    "day": "daily",
    "weekly": "weekly",
    "week": "weekly",
    "monthly": "monthly",
    "month": "monthly",
    "quarterly": "quarterly",
    "quarter": "quarterly",
    "yearly": "yearly",
    "year": "yearly",
}


def _bucket_day_count(interval: str, day: datetime.date) -> int:
    """Number of days in the calendar bucket of ``interval`` containing ``day``.

    ``daily``/``weekly`` are a flat 1/7. ``monthly``/``quarterly``/``yearly``
    are computed from the real calendar rather than averaged (e.g. a
    365.25-day year or a 30-day month): a February bucket is 28 or 29 days
    depending on ``day.year``, a quarterly bucket sums the real lengths of
    its three months, and a yearly bucket is 366 in a leap year, 365
    otherwise. This is Fava's proration model — see ``Ledger.budget_target``.
    """
    if interval == "daily":
        return 1
    if interval == "weekly":
        return 7
    if interval == "monthly":
        return calendar.monthrange(day.year, day.month)[1]
    if interval == "quarterly":
        quarter_start_month = 3 * ((day.month - 1) // 3) + 1
        return sum(
            calendar.monthrange(day.year, month)[1]
            for month in range(quarter_start_month, quarter_start_month + 3)
        )
    if interval == "yearly":
        return 366 if calendar.isleap(day.year) else 365
    raise ValueError(f"unknown budget interval: {interval!r}")


def _advance_date(
    day: datetime.date, interval: str, anchor_day: int | None = None
) -> datetime.date:
    """Advance ``day`` forward by one occurrence of ``interval`` (FORECAST-04).

    A separate concern from ``_bucket_day_count`` above (which counts a
    bucket's length for budget proration, but never advances a date) — this
    is what ``Ledger.project_recurring`` calls to walk a
    ``RecurringTemplate`` forward one occurrence at a time.

    ``daily``/``weekly`` are a flat +1 day / +7 days. ``monthly``/
    ``quarterly``/``yearly`` advance the calendar month by 1/3/12 and set
    the result's day-of-month to ``anchor_day`` (``day.day`` if not given),
    clamped to the target month's actual last day when it doesn't exist
    there — e.g. Jan 31 + 1 month lands on Feb 28 (or 29 in a leap year),
    never skipping to March or raising.

    Callers walking a multi-step recurrence must pass a fixed
    ``anchor_day`` — the *original* first-occurrence day-of-month — on
    every step, not the previous step's (possibly already-clamped) ``day``.
    Otherwise a 31st-of-the-month recurrence would drift downward after
    passing through February instead of snapping back once the month is
    long enough again: with a fixed anchor of 31, Jan 31 -> Feb 28 -> Mar
    31 -> Apr 30 -> May 31; re-deriving the anchor from each clamped
    result would instead give Jan 31 -> Feb 28 -> Mar 28 -> ... (the day
    ratchets down and never recovers).
    """
    if interval == "daily":
        return day + datetime.timedelta(days=1)
    if interval == "weekly":
        return day + datetime.timedelta(weeks=1)
    if interval == "monthly":
        months_ahead = 1
    elif interval == "quarterly":
        months_ahead = 3
    elif interval == "yearly":
        months_ahead = 12
    else:
        raise ValueError(f"unknown recurring interval: {interval!r}")

    if anchor_day is None:
        anchor_day = day.day
    total_months = day.year * 12 + (day.month - 1) + months_ahead
    year, zero_based_month = divmod(total_months, 12)
    month = zero_based_month + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    return datetime.date(year, month, min(anchor_day, last_day_of_month))


@dataclass
class BudgetReportRow:
    """One row of a budget-vs-actual report (see ``Ledger.budget_report``).

    ``budgeted`` is the day-prorated target for the period
    (``Ledger.budget_target``). ``actual`` is this exact account's postings
    in ``currency`` summed over the same period — the same per-account
    summation idiom ``income_statement``/``balance_sheet`` use, narrowed to
    one account and one currency, with no sign inversion for Income-side
    accounts (unlike those reports' display convention): budgets and their
    actuals are entered/posted with the same sign, so ``remaining =
    budgeted - actual`` reads directly (positive means under budget for a
    typical Expense account). There's no sub-account rollup here — a parent
    account with descendants of its own is a separate row, if it has its own
    direct budget; see ``Ledger.budget_report_rolled_up`` for the opt-in
    view that sums descendants into a parent row instead.
    """

    account: str
    currency: str
    budgeted: Decimal
    actual: Decimal
    remaining: Decimal


@dataclass
class QueryResult:
    """The result of running a BQL query: column names plus row tuples.

    Mirrors what ``beanquery`` (the Beancount 3.x successor to the
    `beancount.query` package that shipped in 2.x) hands back from a
    ``Cursor``: ``columns`` is the ``description``'s column names, in
    order, and ``rows`` are the raw fetched row tuples (mixed scalar
    types — ``str``, ``Decimal``, ``datetime.date``, ``Inventory``,
    ``Position``, etc.) — see ``format_query_value`` for rendering them.
    """

    columns: list[str]
    rows: list[tuple]


@dataclass
class RecurringTemplate:
    """A ``#recurring``-tagged transaction, parsed as a projection template.

    The convention (``FORECAST-01``): an ordinary ``data.Transaction`` is
    marked as a template by tagging it ``#recurring`` and attaching
    ``recurring-freq`` (required) and ``recurring-until`` (optional)
    metadata, e.g.::

        2026-01-01 * "Landlord" "Rent" #recurring
          recurring-freq: "monthly"
          recurring-until: "2026-12-31"
          Expenses:Rent      1450.00 USD
          Assets:Checking

    Rather than re-deriving the payee/narration/postings shape separately,
    ``transaction`` keeps a reference to that original entry — it's a real,
    editable ``data.Transaction`` (see ``Ledger._parse_recurring_templates``)
    that a later task (``FORECAST-04``) reads postings/payee/narration off
    of when generating virtual future instances. ``first_date`` is just
    ``transaction.date`` surfaced under its own name for readability at call
    sites that only care about the recurrence, not the entry itself.
    ``interval`` is canonicalized the same way ``BudgetEntry.interval`` is
    (see ``_BUDGET_INTERVALS``) — one of the five long forms regardless of
    which spelling ``recurring-freq`` used. ``until`` is ``None`` when
    ``recurring-until`` is absent, meaning the recurrence has no end date of
    its own (projects indefinitely, bounded only by whatever date range the
    caller asks for).
    """

    first_date: datetime.date
    interval: str
    until: datetime.date | None
    transaction: data.Transaction


@dataclass
class ProjectedTransaction:
    """One virtual, in-memory instance of a ``RecurringTemplate`` (``FORECAST-04``).

    Generated by ``Ledger.project_recurring`` — never constructed as
    parseable Beancount text, never appended to ``self.entries``, and never
    written to disk. ``date`` is this specific occurrence's computed date
    (the template's own ``first_date`` for the first instance, then each
    subsequent occurrence per ``_advance_date``); ``payee``/``narration``/
    ``postings`` are the source template's real ``transaction`` fields,
    reused as-is (same shape a real ``data.Transaction`` exposes) rather
    than re-derived. ``template`` keeps a reference back to the
    ``RecurringTemplate`` that generated this instance, so a caller can
    trace an instance back to its source (e.g. to read ``interval`` or
    ``until``) without re-deriving anything.
    """

    date: datetime.date
    payee: str | None
    narration: str
    postings: list[data.Posting]
    template: RecurringTemplate


@dataclass
class ForecastedActivity:
    """One day's blended projected amount for one account/currency (``FORECAST-05``).

    ``Ledger.forecast`` produces one of these per ``(account, currency,
    date)`` that has either a template instance or a budget covering it —
    never both for the same day, per ``explicit``:

    - ``explicit=True``: ``amount`` is the sum of a ``ProjectedTransaction``
      instance's actual posting amount(s) to this account/currency on this
      date (``FORECAST-04``'s generated instances) — real template data,
      not an estimate.
    - ``explicit=False``: no template instance touched this account/currency
      on this date, so ``amount`` is the budget fallback — this single
      day's prorated share of the account's ``BUDGET-02`` target
      (``Ledger.budget_target(account, currency, date, date)``), an assumed
      figure rather than something a template actually specified.

    ``FORECAST-06``'s report screen uses ``explicit`` to visually
    distinguish "explicit" (from a template) rows from "assumed"
    (budget-fallback) rows, so it's carried on every row rather than left
    for the caller to re-derive.
    """

    date: datetime.date
    account: str
    currency: str
    amount: Decimal
    explicit: bool


@dataclass
class ForecastReportRow:
    """One blended row of ``Ledger.forecast_report`` (``FORECAST-06``): real
    activity through ``today`` plus projected activity for the rest of the
    period, for one account/currency.

    ``actual`` is real posted activity dated in ``[start, today)`` (today
    itself excluded, matching where ``forecast`` starts projecting from) —
    the same date-filter-then-sum idiom ``income_statement``/
    ``budget_report`` use, narrowed to one account/currency with no sign
    inversion (same convention as ``BudgetReportRow``: budgets and their
    actuals share a sign, so summing them directly is meaningful).

    ``projected`` is the sum of ``Ledger.forecast``'s amounts touching this
    account/currency in ``[today, end]``. ``status`` describes what backs
    ``projected``:

    - ``"explicit"``: every contributing forecast row came from a
      recurring-template instance.
    - ``"assumed"``: every contributing row was a budget-fallback figure.
    - ``"mixed"``: some of both, on different days within the period.
    - ``"actual"``: no forecast rows at all for this account/currency in
      the period's future portion (``projected`` is a flat zero) — either
      the requested range ends before ``today``, or this account/currency
      simply has no template/budget coverage in the future window even
      though it appeared in the report's account universe via past
      activity.

    ``total`` is ``actual + projected``, the one number a user skimming the
    report cares about most: what this account is on track to net over the
    whole period, real and projected combined.
    """

    account: str
    currency: str
    actual: Decimal
    projected: Decimal
    status: str
    total: Decimal


@dataclass
class Ledger:
    """A loaded Beancount ledger.

    Wraps ``beancount.loader`` and exposes the pieces the UI needs:
    transactions, the account hierarchy with balances, and validation errors.
    """

    path: Path
    entries: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    options: dict = field(default_factory=dict)
    # Lazily built and cached; invalidated on reload. Not part of equality.
    _price_map: object = field(default=None, repr=False, compare=False)
    # Parsed eagerly at load/reload time (see ``_parse_budgets``), not part
    # of equality, since parsing appends to ``errors`` as a side effect and
    # that shouldn't happen more than once per load.
    _budgets: list = field(default_factory=list, repr=False, compare=False)
    # Parsed eagerly at load/reload time (see ``_parse_recurring_templates``),
    # same reasoning as ``_budgets``.
    _recurring_templates: list = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        path = Path(path)
        entries, errors, options = loader.load_file(str(path))
        ledger = cls(path=path, entries=entries, errors=errors, options=options)
        ledger._parse_budgets()
        ledger._parse_recurring_templates()
        return ledger

    def reload(self) -> None:
        self.entries, self.errors, self.options = loader.load_file(str(self.path))
        self._price_map = None
        self._parse_budgets()
        self._parse_recurring_templates()

    @property
    def transactions(self) -> list[data.Transaction]:
        return [e for e in self.entries if isinstance(e, data.Transaction)]

    @property
    def _actual_entries(self) -> list[data.Directive]:
        """``self.entries`` minus ``#recurring`` template transactions.

        A ``#recurring``-tagged transaction (see ``_parse_recurring_templates``)
        is a template, not something that actually happened, so every
        actual-data report (income statement, balance sheet, trial balance,
        register, holdings, the account-tree realization) must exclude it.
        Non-transaction entries (opens, closes, pads, prices, ...) all stay,
        since only transactions can carry the ``#recurring`` tag.
        """
        return [
            e
            for e in self.entries
            if not (isinstance(e, data.Transaction) and "recurring" in (e.tags or set()))
        ]

    @property
    def _actual_transactions(self) -> list[data.Transaction]:
        """``self.transactions`` minus ``#recurring`` template transactions.

        The filtered counterpart every report method should iterate instead
        of ``self.transactions``, so a template's postings never skew a
        computed total. The main transaction table deliberately keeps using
        ``self.transactions`` (via ``transactions_for_account``) so templates
        remain visible and editable there, marked with a "↻" prefix
        (see ``transaction_table._entry_row``).
        """
        return [e for e in self._actual_entries if isinstance(e, data.Transaction)]

    @property
    def accounts(self) -> list[str]:
        """All account names that appear in the ledger, sorted."""
        return sorted(getters.get_accounts(self.entries))

    @property
    def directives(self) -> list[data.Directive]:
        """All entries of the types the UI displays, transactions included."""
        return [e for e in self.entries if isinstance(e, DISPLAYED_DIRECTIVES)]

    def entries_for_account(self, account: str | None) -> list[data.Directive]:
        """Displayable entries touching ``account`` or any of its sub-accounts."""
        if account is None:
            return self.directives
        prefix = account + ":"
        return [
            entry
            for entry in self.directives
            if any(
                a == account or a.startswith(prefix)
                for a in getters.get_entry_accounts(entry)
            )
        ]

    @property
    def budgets(self) -> list[BudgetEntry]:
        """Parsed ``custom "budget"`` entries (see ``BudgetEntry``).

        Populated at load/reload time by ``_parse_budgets``; a directive
        with an unrecognized interval is excluded here and instead reported
        via ``self.errors``, the same mechanism the beancount loader itself
        uses for malformed entries — it never crashes ``Ledger.load``.
        """
        return self._budgets

    def _parse_budgets(self) -> None:
        """Parse ``custom "budget"`` entries into ``self._budgets``.

        Filters ``self.entries`` for ``data.Custom`` entries typed
        ``"budget"`` and extracts ``(account, interval, amount)`` from
        ``entry.values`` (Fava's convention: an account value, a string
        interval value, and an ``Amount`` value, in that order). Before
        ``BUDGET-01``, any ``custom`` directive — including one typed
        ``"budget"`` — was only ever handled generically (``LANG-06``), so a
        ``budget``-typed entry that doesn't actually match this 3-value
        shape is left alone (excluded from ``self.budgets``, generic
        ``Custom`` display unaffected, no new error) rather than treated as
        a broken budget. Only an entry that *does* match the shape but
        whose interval string isn't one of Fava's five accepted values
        (long or short form, case-insensitive — see ``_BUDGET_INTERVALS``)
        is reported: as a ``loader.LoadError`` appended to ``self.errors``
        (mirroring how the real beancount loader surfaces its own
        validation errors), not a raised exception, and excluded from
        ``self.budgets``.
        """
        budgets: list[BudgetEntry] = []
        for entry in self.entries:
            if not (isinstance(entry, data.Custom) and entry.type == "budget"):
                continue
            if len(entry.values) != 3:
                continue
            account = entry.values[0].value
            raw_interval = entry.values[1].value
            amount = entry.values[2].value
            if not isinstance(account, str) or not isinstance(amount, data.Amount):
                continue
            interval = _BUDGET_INTERVALS.get(str(raw_interval).strip().lower())
            if interval is None:
                self.errors.append(
                    loader.LoadError(
                        entry.meta,
                        f'Invalid budget interval "{raw_interval}": expected one of '
                        "daily/weekly/monthly/quarterly/yearly "
                        "(or day/week/month/quarter/year)",
                        entry,
                    )
                )
                continue
            budgets.append(
                BudgetEntry(date=entry.date, account=account, interval=interval, amount=amount)
            )
        self._budgets = budgets

    @property
    def recurring_templates(self) -> list[RecurringTemplate]:
        """Parsed ``#recurring``-tagged transactions (see ``RecurringTemplate``).

        Populated at load/reload time by ``_parse_recurring_templates``; a
        ``#recurring`` transaction with a missing or invalid
        ``recurring-freq``, or a malformed ``recurring-until``, is excluded
        here and instead reported via ``self.errors`` — same convention as
        ``budgets``.
        """
        return self._recurring_templates

    def _parse_recurring_templates(self) -> None:
        """Parse ``#recurring``-tagged transactions into ``self._recurring_templates``.

        Filters ``self.entries`` for ``data.Transaction`` entries tagged
        ``#recurring`` (``"recurring" in entry.tags``; tags are stored
        without their ``#`` prefix). Each such transaction is expected to
        carry ``recurring-freq`` metadata naming one of Fava's five interval
        values (reusing ``_BUDGET_INTERVALS`` — the same dict and
        normalization ``_parse_budgets`` uses, rather than a second copy of
        either) and, optionally, ``recurring-until`` as an ISO
        ``YYYY-MM-DD`` date string.

        A ``#recurring`` transaction is a template only, not actual
        activity, but it's still real Beancount data — so a template that
        fails to parse is reported the same way an invalid budget interval
        is: a ``loader.LoadError`` appended to ``self.errors`` (never a
        raised exception), and excluded from ``self.recurring_templates``.
        This covers three failure shapes, each surfaced with its own
        message: ``recurring-freq`` missing entirely, ``recurring-freq``
        present but not one of the five accepted values, and
        ``recurring-until`` present but not a parseable ISO date. A missing
        ``recurring-until`` is not a failure — it's the "projects
        indefinitely" case (see ``RecurringTemplate.until``).
        """
        templates: list[RecurringTemplate] = []
        for entry in self.entries:
            if not (isinstance(entry, data.Transaction) and "recurring" in (entry.tags or set())):
                continue
            raw_interval = entry.meta.get("recurring-freq")
            if raw_interval is None:
                self.errors.append(
                    loader.LoadError(
                        entry.meta,
                        "Missing recurring-freq metadata on #recurring transaction",
                        entry,
                    )
                )
                continue
            interval = _BUDGET_INTERVALS.get(str(raw_interval).strip().lower())
            if interval is None:
                self.errors.append(
                    loader.LoadError(
                        entry.meta,
                        f'Invalid recurring-freq "{raw_interval}": expected one of '
                        "daily/weekly/monthly/quarterly/yearly "
                        "(or day/week/month/quarter/year)",
                        entry,
                    )
                )
                continue
            raw_until = entry.meta.get("recurring-until")
            until: datetime.date | None = None
            if raw_until is not None:
                try:
                    until = datetime.date.fromisoformat(str(raw_until).strip())
                except ValueError:
                    self.errors.append(
                        loader.LoadError(
                            entry.meta,
                            f'Invalid recurring-until "{raw_until}": expected an '
                            "ISO date (YYYY-MM-DD)",
                            entry,
                        )
                    )
                    continue
            templates.append(
                RecurringTemplate(
                    first_date=entry.date,
                    interval=interval,
                    until=until,
                    transaction=entry,
                )
            )
        self._recurring_templates = templates

    def project_recurring(
        self, start: datetime.date, end: datetime.date
    ) -> list[ProjectedTransaction]:
        """Virtual instances of every recurring template within ``[start, end]``.

        For each ``RecurringTemplate`` (``self.recurring_templates``), walks
        forward from its own ``first_date`` — never from ``start`` — one
        occurrence at a time via ``_advance_date``, using the template's
        original first-occurrence day-of-month as the fixed anchor for
        month/quarter/year advancement (see ``_advance_date``'s docstring
        for why that has to stay fixed rather than being re-derived each
        step). The walk stops once it passes ``min(end, template.until)``
        (or plain ``end`` when ``until`` is ``None``, meaning the template
        has no end date of its own). Occurrences before ``start`` are
        skipped but still counted in the walk — so a template whose
        ``first_date`` predates ``start`` by several occurrences still
        lands on its correct calendar dates within the range rather than
        restarting the recurrence from ``start``. Conversely, a template
        whose ``first_date`` is *after* ``start`` only ever generates
        instances from that first occurrence onward — it never generates
        anything before its own start.

        The result is unordered across templates (each template's own
        instances are in date order, but templates are processed in
        ``self.recurring_templates`` order) — a caller that wants a single
        chronological feed should sort on ``.date``.
        """
        instances: list[ProjectedTransaction] = []
        for template in self.recurring_templates:
            cutoff = end if template.until is None else min(end, template.until)
            if template.first_date > cutoff:
                continue
            anchor_day = template.first_date.day
            day = template.first_date
            while day <= cutoff:
                if day >= start:
                    instances.append(
                        ProjectedTransaction(
                            date=day,
                            payee=template.transaction.payee,
                            narration=template.transaction.narration,
                            postings=template.transaction.postings,
                            template=template,
                        )
                    )
                day = _advance_date(day, template.interval, anchor_day)
        return instances

    def _budget_series(self, account: str, currency: str) -> list[BudgetEntry]:
        """This account/currency's budget time series, sorted by date.

        Budget entries for other accounts or other currencies of the same
        account are a different series entirely (see ``budget_target``'s
        "latest wins, tracked independently per currency" model) and are
        excluded here.
        """
        return sorted(
            (b for b in self.budgets if b.account == account and b.amount.currency == currency),
            key=lambda b: b.date,
        )

    def budget_target(
        self,
        account: str,
        currency: str,
        start: datetime.date,
        end: datetime.date,
    ) -> Decimal:
        """Fava's day-by-day prorated budget target for ``account``/``currency``.

        Walks every day in ``[start, end]`` (inclusive on both ends) and
        adds that day's share of the applicable budget: the most recent
        ``BudgetEntry`` for this exact ``account``/``currency`` pair whose
        ``date`` is on or before the day (per-currency time series — see
        ``_budget_series``; a EUR and a USD budget for the same account each
        have their own independent "most recent" pointer, and a later entry
        supersedes an earlier one only from its own date onward, so days
        before it still resolve to whatever was current then). A day's
        share is ``entry.amount / _bucket_day_count(entry.interval, day)`` —
        the exact number of days in the real calendar month/quarter/year (or
        flat 7/1 for weekly/daily) containing that specific day, not a flat
        average, so proration is exact across month/quarter/leap-year
        boundaries even for a single unchanging entry.

        A day with no applicable entry (before this series' earliest date,
        or no entry exists at all for this account/currency) contributes
        nothing — a clean absence rather than a zero-with-a-flag — so an
        account/currency with no budget anywhere in the range returns a
        plain ``Decimal(0)``, indistinguishable from a budget of zero; the
        caller (BUDGET-03's report) is expected to already know which
        account/currency pairs have a budget at all via ``self.budgets``
        before calling this.
        """
        series = self._budget_series(account, currency)
        if not series:
            return Decimal(0)
        dates = [entry.date for entry in series]

        total = Decimal(0)
        one_day = datetime.timedelta(days=1)
        day = start
        while day <= end:
            idx = bisect.bisect_right(dates, day) - 1
            if idx >= 0:
                entry = series[idx]
                total += entry.amount.number / _bucket_day_count(entry.interval, day)
            day += one_day
        return total

    def _account_currency_activity(
        self,
        account: str,
        currency: str,
        start: datetime.date,
        end: datetime.date,
    ) -> Decimal:
        """Sum of ``account``'s postings in ``currency``, dated in ``[start, end]``.

        The same date-filter-then-sum idiom ``income_statement``/
        ``balance_sheet`` use for their per-account totals, narrowed to a
        single exact account (no sub-account rollup — see
        ``BudgetReportRow``) and a single currency, since a budget target is
        per-currency (``budget_target``) and the "actual" side needs to
        match it exactly rather than mixing currencies into an ``Inventory``.
        Iterates ``self._actual_transactions`` (excluding ``#recurring``
        templates), same as every other actual-data view (``FORECAST-02``) —
        a template transaction is projection data, not something that
        happened, so it must not skew this "Actual" column either.
        """
        total = Decimal(0)
        for txn in self._actual_transactions:
            if txn.date < start or txn.date > end:
                continue
            for posting in txn.postings:
                if posting.account != account:
                    continue
                if posting.units is None or posting.units.number is None:
                    continue
                if posting.units.currency != currency:
                    continue
                total += posting.units.number
        return total

    def budget_report(
        self, start: datetime.date, end: datetime.date
    ) -> list[BudgetReportRow]:
        """Budget-vs-actual rows for every account/currency active in ``[start, end]``.

        First derives the universe of ``(account, currency)`` pairs that
        have a budget at all from ``self.budgets`` (deduped), since
        ``budget_target`` alone can't tell a "no budget ever" pair apart
        from a "budget target happens to prorate to zero" one. A pair is
        then "active" in this period if its time series
        (``_budget_series``) has an entry on or before ``end`` — i.e. some
        day within ``[start, end]`` would resolve to an applicable target;
        a series whose earliest entry postdates ``end`` hasn't taken effect
        yet within this period and is excluded (a budget entry keeps
        applying indefinitely once its date arrives, so only the *earliest*
        entry's date needs checking against ``end``, not every entry's).
        Accounts with no budget at all never appear (this is the flat
        per-leaf view described in ``BudgetReportRow``; see
        ``budget_report_rolled_up`` for the opt-in parent rollup). Rows are
        sorted by account, then currency.
        """
        pairs: dict[tuple[str, str], None] = {}
        for budget in self.budgets:
            pairs.setdefault((budget.account, budget.amount.currency), None)

        rows: list[BudgetReportRow] = []
        for account, currency in sorted(pairs):
            series = self._budget_series(account, currency)
            if not series or series[0].date > end:
                continue
            budgeted = self.budget_target(account, currency, start, end)
            actual = self._account_currency_activity(account, currency, start, end)
            rows.append(
                BudgetReportRow(
                    account=account,
                    currency=currency,
                    budgeted=budgeted,
                    actual=actual,
                    remaining=budgeted - actual,
                )
            )
        return rows

    def budget_report_rolled_up(
        self, start: datetime.date, end: datetime.date
    ) -> list[BudgetReportRow]:
        """``budget_report``, plus synthesized parent-account rollup rows.

        Opt-in (BUDGET-04), mirroring Fava's ``calculate_budget_children``:
        starts from the flat ``budget_report`` rows — one per leaf
        ``(account, currency)`` pair with an active budget — then, per
        currency, considers every proper ancestor of a budgeted account
        (e.g. ``Expenses:Food`` and ``Expenses`` for
        ``Expenses:Food:Groceries``, split on ``:``). An ancestor that has
        no flat row of its own gets a synthesized row summing the
        Budgeted/Actual/Remaining of every flat row whose account is one of
        its descendants (string-prefix match on ``ancestor + ":"``) — not
        just its immediate children, so a grandparent's synthesized row
        totals every budgeted leaf beneath it directly, rather than
        compounding through an intermediate synthesized row.

        An ancestor that already has its own flat row (its own direct
        budget entry) is left alone — no synthesized row is added for it,
        so its own figures aren't double-counted against a sum of its
        children's. That account's descendants, if any of them are
        separately budgeted, still contribute to *their own* ancestors
        further up the tree.

        The result is the flat rows plus these synthesized rows, sorted by
        account then currency, same as ``budget_report``.
        """
        flat_rows = self.budget_report(start, end)
        by_currency: dict[str, list[BudgetReportRow]] = {}
        for row in flat_rows:
            by_currency.setdefault(row.currency, []).append(row)

        synthesized: list[BudgetReportRow] = []
        for currency, rows in by_currency.items():
            direct_accounts = {row.account for row in rows}
            ancestors: set[str] = set()
            for row in rows:
                parts = row.account.split(":")
                for i in range(1, len(parts)):
                    ancestors.add(":".join(parts[:i]))
            for ancestor in ancestors:
                if ancestor in direct_accounts:
                    continue
                prefix = ancestor + ":"
                descendants = [row for row in rows if row.account.startswith(prefix)]
                if not descendants:
                    continue
                budgeted = sum((row.budgeted for row in descendants), Decimal(0))
                actual = sum((row.actual for row in descendants), Decimal(0))
                synthesized.append(
                    BudgetReportRow(
                        account=ancestor,
                        currency=currency,
                        budgeted=budgeted,
                        actual=actual,
                        remaining=budgeted - actual,
                    )
                )

        return sorted(flat_rows + synthesized, key=lambda row: (row.account, row.currency))

    def forecast(
        self, start: datetime.date, end: datetime.date
    ) -> list[ForecastedActivity]:
        """Blended per-day projected activity for ``[start, end]`` (``FORECAST-05``).

        Combines two layers, per ``(account, currency, date)``, matching the
        milestone's "explicit beats assumed, never both" rule:

        - **Explicit**: every ``ProjectedTransaction`` from
          ``project_recurring(start, end)`` (``FORECAST-04``) contributes its
          posting amounts, summed per account/currency on that instance's
          own date, as an ``explicit=True`` row.
        - **Assumed (budget fallback)**: for every ``(account, currency)``
          pair that has a budget at all — derived from ``self.budgets`` the
          same way ``budget_report`` derives its universe, since
          ``budget_target`` alone can't tell "no budget" apart from "budget
          prorates to zero" — and whose series has actually started by
          ``end`` (mirrors ``budget_report``'s own "active in period" check,
          so a budget that hasn't taken effect yet doesn't generate a run of
          meaningless zero rows), each day in ``[start, end]`` with no
          explicit row for that exact account/currency gets an
          ``explicit=False`` row: that single day's prorated target
          (``budget_target(account, currency, day, day)``).

        Resolution is per account/currency/day, not per account overall: a
        template instance on the 5th only suppresses that account/currency's
        budget fallback on the 5th, not the rest of the month. An
        account/currency with neither a template instance nor a budget never
        appears (clean absence, the same convention ``budget_target`` itself
        documents).

        Sorted by date, then account, then currency.
        """
        explicit: dict[tuple[datetime.date, str, str], Decimal] = {}
        for instance in self.project_recurring(start, end):
            for posting in instance.postings:
                if posting.units is None or posting.units.number is None:
                    continue
                key = (instance.date, posting.account, posting.units.currency)
                explicit[key] = explicit.get(key, Decimal(0)) + posting.units.number

        rows: list[ForecastedActivity] = [
            ForecastedActivity(
                date=date, account=account, currency=currency, amount=amount, explicit=True
            )
            for (date, account, currency), amount in explicit.items()
        ]

        budget_pairs: dict[tuple[str, str], None] = {}
        for budget in self.budgets:
            budget_pairs.setdefault((budget.account, budget.amount.currency), None)

        one_day = datetime.timedelta(days=1)
        for account, currency in budget_pairs:
            series = self._budget_series(account, currency)
            if not series or series[0].date > end:
                continue
            day = start
            while day <= end:
                if (day, account, currency) not in explicit:
                    rows.append(
                        ForecastedActivity(
                            date=day,
                            account=account,
                            currency=currency,
                            amount=self.budget_target(account, currency, day, day),
                            explicit=False,
                        )
                    )
                day += one_day

        rows.sort(key=lambda row: (row.date, row.account, row.currency))
        return rows

    def forecast_report(
        self,
        start: datetime.date,
        end: datetime.date,
        today: datetime.date | None = None,
    ) -> list[ForecastReportRow]:
        """Blended actual-through-today + projected-from-today report (``FORECAST-06``).

        Splits ``[start, end]`` at ``today`` (real current date unless
        overridden, matching ``budget_target``/``resolve_date_preset``'s own
        testability convention): real posted activity covers
        ``[start, today)``, ``Ledger.forecast`` covers ``[today, end]`` —
        ``forecast`` is a template+budget *projection*, not a general ledger
        query, so it's never asked for a day that's already happened.

        The account/currency universe reported on is independent of
        ``start``/``end`` (any budget active by ``end``, plus every account
        a recurring template posts to) rather than "whatever happened to
        have activity in this exact window" — so a request landing entirely
        on one side of ``today`` still resolves the same meaningful set of
        accounts instead of an arbitrarily empty or actual-data-only table.

        Rows are sorted by account, then currency.
        """
        if today is None:
            today = datetime.date.today()

        # Universe: every (account, currency) pair this report cares about,
        # mirroring how ``forecast`` itself derives "has a budget at all"
        # and "template posts to this account" -- see below.
        universe: set[tuple[str, str]] = set()
        budget_pairs: dict[tuple[str, str], None] = {}
        for budget in self.budgets:
            budget_pairs.setdefault((budget.account, budget.amount.currency), None)
        for account, currency in budget_pairs:
            series = self._budget_series(account, currency)
            if series and series[0].date <= end:
                universe.add((account, currency))
        for template in self.recurring_templates:
            for posting in template.transaction.postings:
                if posting.units is not None and posting.units.number is not None:
                    universe.add((posting.account, posting.units.currency))

        actual_totals: dict[tuple[str, str], Decimal] = {}
        real_end = min(end, today - datetime.timedelta(days=1))
        if start <= real_end:
            for txn in self._actual_transactions:
                if txn.date < start or txn.date > real_end:
                    continue
                for posting in txn.postings:
                    if posting.units is None or posting.units.number is None:
                        continue
                    key = (posting.account, posting.units.currency)
                    if key not in universe:
                        continue
                    actual_totals[key] = actual_totals.get(key, Decimal(0)) + posting.units.number

        projected_totals: dict[tuple[str, str], Decimal] = {}
        explicit_keys: set[tuple[str, str]] = set()
        assumed_keys: set[tuple[str, str]] = set()
        forecast_start = max(start, today)
        if forecast_start <= end:
            for row in self.forecast(forecast_start, end):
                key = (row.account, row.currency)
                projected_totals[key] = projected_totals.get(key, Decimal(0)) + row.amount
                if row.explicit:
                    explicit_keys.add(key)
                else:
                    assumed_keys.add(key)

        rows: list[ForecastReportRow] = []
        for account, currency in sorted(universe):
            key = (account, currency)
            actual = actual_totals.get(key, Decimal(0))
            projected = projected_totals.get(key, Decimal(0))
            if key not in projected_totals:
                status = "actual"
            elif key in explicit_keys and key in assumed_keys:
                status = "mixed"
            elif key in explicit_keys:
                status = "explicit"
            else:
                status = "assumed"
            rows.append(
                ForecastReportRow(
                    account=account,
                    currency=currency,
                    actual=actual,
                    projected=projected,
                    status=status,
                    total=actual + projected,
                )
            )
        return rows

    @property
    def queries(self) -> list[data.Query]:
        """Saved named BQL queries (``data.Query`` directives) in the ledger."""
        return [e for e in self.entries if isinstance(e, data.Query)]

    def run_query(self, query_string: str) -> QueryResult:
        """Run a BQL query against this ledger via ``beanquery``.

        ``beanquery`` is the package that provides the query engine in
        Beancount 3.x (the ``beancount.query`` module from 2.x was split
        out into it). Connects to the in-memory ``entries``/``options``
        directly (the ``beancount:`` DSN with no path, plus ``entries=``/
        ``options=`` kwargs) rather than having it re-load the ledger file
        itself, since it's already loaded here.

        Raises ``beanquery.Error`` (``ParseError`` for bad syntax,
        ``CompilationError`` for e.g. an unknown column) on an invalid
        query — callers should catch it and show a message rather than
        letting it propagate.
        """
        connection = beanquery.connect(
            "beancount:", entries=self.entries, errors=self.errors, options=self.options
        )
        cursor = connection.execute(query_string)
        columns = [column.name for column in cursor.description]
        rows = cursor.fetchall()
        return QueryResult(columns=columns, rows=rows)

    @property
    def files(self) -> list[Path]:
        """All source files of the ledger: the top-level file, then includes.

        Beancount records every processed file in ``options["include"]``.
        """
        top = self.path.resolve()
        included = {Path(name).resolve() for name in self.options.get("include", [])}
        return [top] + sorted(f for f in included if f != top)

    def income_statement(
        self,
        start: datetime.date | None = None,
        end: datetime.date | None = None,
    ) -> IncomeStatement:
        """Summarize Income and Expenses postings dated in [start, end]."""
        name_income = self.options.get("name_income", "Income")
        name_expenses = self.options.get("name_expenses", "Expenses")
        per_account: dict[str, Inventory] = {}
        for txn in self._actual_transactions:
            if start is not None and txn.date < start:
                continue
            if end is not None and txn.date > end:
                continue
            for posting in txn.postings:
                root = posting.account.split(":", 1)[0]
                if root not in (name_income, name_expenses):
                    continue
                if posting.units is None or posting.units.number is None:
                    continue
                per_account.setdefault(posting.account, Inventory()).add_amount(posting.units)

        income: list[tuple[str, Inventory]] = []
        expenses: list[tuple[str, Inventory]] = []
        income_total = Inventory()
        expenses_total = Inventory()
        for account in sorted(per_account):
            balance = per_account[account]
            if account.split(":", 1)[0] == name_income:
                income.append((account, -balance))
                income_total.add_inventory(-balance)
            else:
                expenses.append((account, balance))
                expenses_total.add_inventory(balance)
        net = Inventory()
        net.add_inventory(income_total)
        net.add_inventory(-expenses_total)
        return IncomeStatement(income, expenses, income_total, expenses_total, net)

    def trial_balance(self, as_of: datetime.date | None = None) -> list[tuple[str, Inventory]]:
        """Nonzero balances for every account, as of ``as_of`` (default: today).

        Sums every posting dated on or before ``as_of`` per account, across
        all five account types, and drops accounts whose net balance is
        zero. Sorted by account name.
        """
        if as_of is None:
            as_of = datetime.date.today()
        per_account: dict[str, Inventory] = {}
        for txn in self._actual_transactions:
            if txn.date > as_of:
                continue
            for posting in txn.postings:
                if posting.units is None or posting.units.number is None:
                    continue
                per_account.setdefault(posting.account, Inventory()).add_amount(posting.units)
        return [
            (account, balance)
            for account, balance in sorted(per_account.items())
            if not balance.is_empty()
        ]

    def balance_sheet(self, as_of: datetime.date | None = None) -> BalanceSheet:
        """Summarize Assets/Liabilities/Equity postings as of ``as_of`` (default: today).

        Sums every posting dated on or before ``as_of`` per account, the same
        approach ``trial_balance`` uses across all five account types, but
        restricted to Assets/Liabilities/Equity and split into those three
        sections. Liabilities and Equity are sign-inverted to read as
        positive credit-normal balances (like ``income_statement`` does for
        Income), and the current period's net income (all transactions
        through ``as_of``) is included as an implicit Equity-section line,
        so ``assets_total == liabilities_total + equity_total + net_income``
        even before a bean-close would fold it into Equity for real.
        """
        if as_of is None:
            as_of = datetime.date.today()
        name_assets = self.options.get("name_assets", "Assets")
        name_liabilities = self.options.get("name_liabilities", "Liabilities")
        name_equity = self.options.get("name_equity", "Equity")
        per_account: dict[str, Inventory] = {}
        for txn in self._actual_transactions:
            if txn.date > as_of:
                continue
            for posting in txn.postings:
                root = posting.account.split(":", 1)[0]
                if root not in (name_assets, name_liabilities, name_equity):
                    continue
                if posting.units is None or posting.units.number is None:
                    continue
                per_account.setdefault(posting.account, Inventory()).add_amount(posting.units)

        assets: list[tuple[str, Inventory]] = []
        liabilities: list[tuple[str, Inventory]] = []
        equity: list[tuple[str, Inventory]] = []
        assets_total = Inventory()
        liabilities_total = Inventory()
        equity_total = Inventory()
        for account in sorted(per_account):
            balance = per_account[account]
            if balance.is_empty():
                continue
            root = account.split(":", 1)[0]
            if root == name_assets:
                assets.append((account, balance))
                assets_total.add_inventory(balance)
            elif root == name_liabilities:
                liabilities.append((account, -balance))
                liabilities_total.add_inventory(-balance)
            else:
                equity.append((account, -balance))
                equity_total.add_inventory(-balance)

        net_income = self.income_statement(start=None, end=as_of).net
        return BalanceSheet(
            assets=assets,
            liabilities=liabilities,
            equity=equity,
            assets_total=assets_total,
            liabilities_total=liabilities_total,
            equity_total=equity_total,
            net_income=net_income,
        )

    def holdings(self, as_of: datetime.date | None = None) -> HoldingsReport:
        """Aggregate costed lots in Assets/Liabilities into per-commodity holdings.

        Groups every costed posting (``Posting.cost`` is not ``None``) dated
        on or before ``as_of`` (default: today) by ``(account, commodity)`` —
        grouping by ``units.currency``, not by cost currency, per
        ``Holding``'s docstring. Postings without a cost (plain currency
        holdings, e.g. a checking account balance) aren't lots and are out of
        scope for this report.

        Market value uses ``beancount.core.prices.build_price_map`` over all
        ``Price`` directives (plus the inverses it derives for free), looked
        up as of ``as_of``: first a direct commodity-to-operating-currency
        quote, falling back to a commodity-to-cost-currency quote if that's
        all that's known. No further chaining (e.g. cost-currency into
        operating-currency) is attempted, so a holding can end up with a
        market value that isn't in the operating currency — see
        ``Holding.priced_in_operating_currency``.
        """
        if as_of is None:
            as_of = datetime.date.today()
        name_assets = self.options.get("name_assets", "Assets")
        name_liabilities = self.options.get("name_liabilities", "Liabilities")
        operating_currencies = self.options.get("operating_currency") or []
        operating_currency = operating_currencies[0] if operating_currencies else None

        price_map = prices.build_price_map(self.entries)

        per_key: dict[tuple[str, str], dict] = {}
        for txn in self._actual_transactions:
            if txn.date > as_of:
                continue
            for posting in txn.postings:
                root = posting.account.split(":", 1)[0]
                if root not in (name_assets, name_liabilities):
                    continue
                if posting.units is None or posting.units.number is None:
                    continue
                if posting.cost is None or posting.cost.number is None:
                    continue
                key = (posting.account, posting.units.currency)
                agg = per_key.setdefault(key, {"quantity": Decimal(0), "cost_basis": Inventory()})
                agg["quantity"] += posting.units.number
                agg["cost_basis"].add_amount(
                    data.Amount(posting.units.number * posting.cost.number, posting.cost.currency)
                )

        holdings: list[Holding] = []
        net_worth = Inventory()
        for (account, commodity), agg in sorted(per_key.items()):
            quantity: Decimal = agg["quantity"]
            if quantity == Decimal(0):
                continue
            cost_basis: Inventory = agg["cost_basis"]

            market_value: data.Amount | None = None
            priced_in_operating_currency = False
            if operating_currency is not None:
                _, rate = prices.get_price(price_map, (commodity, operating_currency), as_of)
                if rate is not None:
                    market_value = data.Amount(quantity * rate, operating_currency)
                    priced_in_operating_currency = True
            if market_value is None:
                cost_currency = next(
                    (pos.units.currency for pos in cost_basis.get_positions()), None
                )
                if cost_currency is not None and cost_currency != operating_currency:
                    _, rate = prices.get_price(price_map, (commodity, cost_currency), as_of)
                    if rate is not None:
                        market_value = data.Amount(quantity * rate, cost_currency)

            holdings.append(
                Holding(
                    account=account,
                    commodity=commodity,
                    quantity=quantity,
                    cost_basis=cost_basis,
                    market_value=market_value,
                    priced_in_operating_currency=priced_in_operating_currency,
                )
            )
            if priced_in_operating_currency and market_value is not None:
                net_worth.add_amount(market_value)

        return HoldingsReport(
            holdings=holdings, net_worth=net_worth, operating_currency=operating_currency
        )

    def file_mtimes(self) -> dict[Path, float]:
        """Modification times of all source files, for change detection."""
        mtimes = {}
        for file in self.files:
            try:
                mtimes[file] = file.stat().st_mtime
            except OSError:
                mtimes[file] = -1.0
        return mtimes

    def transactions_for_account(
        self,
        account: str | None,
        transactions: list[data.Transaction] | None = None,
    ) -> list[data.Transaction]:
        """Transactions posting to ``account`` or any of its sub-accounts.

        Filters ``transactions`` (default ``self.transactions``, i.e.
        including ``#recurring`` templates — the main transaction table
        relies on that default so templates stay visible/editable there).
        ``register`` passes ``self._actual_transactions`` instead, so its
        report excludes them, without duplicating this account-matching
        logic.
        """
        if transactions is None:
            transactions = self.transactions
        if account is None:
            return transactions
        prefix = account + ":"
        return [
            txn
            for txn in transactions
            if any(p.account == account or p.account.startswith(prefix) for p in txn.postings)
        ]

    def _register_walk(
        self, account: str, only_cleared: bool = False
    ) -> list[tuple[data.Transaction, Inventory, Inventory]]:
        """Shared chronological walk behind ``register``/``running_balances`` (RPT-07).

        Every transaction posting to ``account`` or any of its sub-accounts
        (excluding ``#recurring`` templates, per ``_actual_transactions``),
        in date order, paired with that transaction's summed posting
        amount to the account and the cumulative running balance
        immediately after. Multiple currencies coexist in each
        ``Inventory`` without mixing.

        ``only_cleared=True`` restricts the walk to ``flag == "*"``
        (cleared) transactions: a non-cleared transaction is skipped
        entirely -- it contributes nothing to the running total and never
        appears in the result -- which is exactly the "Cleared Balance"
        figure (only cleared activity counts, independent of any
        still-pending ``!`` activity also in the ledger).
        """
        prefix = account + ":"
        txns = sorted(
            self.transactions_for_account(account, self._actual_transactions),
            key=lambda txn: txn.date,
        )
        running = Inventory()
        rows: list[tuple[data.Transaction, Inventory, Inventory]] = []
        for txn in txns:
            if only_cleared and txn.flag != "*":
                continue
            posting_amount = Inventory()
            for posting in txn.postings:
                if posting.account != account and not posting.account.startswith(prefix):
                    continue
                if posting.units is None or posting.units.number is None:
                    continue
                posting_amount.add_amount(posting.units)
            running.add_inventory(posting_amount)
            rows.append((txn, posting_amount, Inventory(running)))
        return rows

    def register(self, account: str) -> list[RegisterRow]:
        """Per-transaction posting amount and running balance for ``account``.

        Mirrors ``bean-report register ACCOUNT``: every transaction posting
        to ``account`` or any of its sub-accounts, in date order, each with
        that transaction's posting(s) to the account summed into a single
        amount and the running balance immediately after. Multiple
        currencies coexist in each ``Inventory`` without mixing.
        ``#recurring`` template transactions are excluded, like every other
        actual-data report (see ``_actual_transactions``). See
        ``_register_walk`` for the shared implementation (also used by
        ``running_balances``, RPT-07's inline main-table columns).
        """
        return [
            RegisterRow(
                date=txn.date,
                narration=txn.narration,
                posting_amount=posting_amount,
                running_balance=running_balance,
            )
            for txn, posting_amount, running_balance in self._register_walk(account)
        ]

    def running_balances(
        self, account: str, only_cleared: bool = False
    ) -> dict[int, Inventory]:
        """``account``'s running balance after each contributing transaction (RPT-07).

        Same chronological, sub-account-inclusive, ``#recurring``-exclusive
        walk as ``register`` (see ``_register_walk``), re-keyed for direct
        lookup by transaction instead of a plain list -- what
        ``TransactionTable``'s inline Balance/Cleared Balance columns need,
        since they render rows in whatever order the table is currently
        sorted in rather than chronological order, but the balances
        themselves must always reflect the earliest-to-latest walk.

        Keyed by ``id(transaction)`` rather than the transaction itself:
        ``data.Transaction`` carries a ``meta`` dict, which makes the whole
        namedtuple unhashable, so it can't be a real dict key. ``id()`` is
        the practical stand-in for "this exact transaction object" --
        correct as long as the caller matches keys against transactions
        drawn from this same ``Ledger`` snapshot (e.g. the same
        ``self.entries`` a table's rows came from), not across a
        ``reload()``, which produces entirely new entry objects.

        ``only_cleared=True`` returns the Cleared Balance variant: only
        ``flag == "*"`` transactions contribute to the running total, and a
        non-cleared transaction is simply absent from the result -- a
        lookup miss is the correct "doesn't contribute" signal for a
        caller, rather than a stale or zero entry.
        """
        return {
            id(txn): running_balance
            for txn, _, running_balance in self._register_walk(account, only_cleared=only_cleared)
        }

    def root_account(self) -> realization.RealAccount:
        """The realized account tree, with balances, for the account sidebar.

        Realized over ``_actual_entries`` rather than ``self.entries``, so a
        ``#recurring`` template's postings don't skew sidebar balances —
        opens/closes/pads/etc. are all still included, only template
        transactions are excluded.
        """
        return realization.realize(self._actual_entries)

    def _price_map_cached(self):
        """The ledger's price map (from ``Price`` directives), built once and
        cached until the next :meth:`reload`."""
        if self._price_map is None:
            self._price_map = prices.build_price_map(self.entries)
        return self._price_map

    def converted_total(self, inventory: Inventory) -> tuple[Decimal | None, list[str]]:
        """Convert ``inventory`` to the ledger's primary operating currency.

        The "primary" operating currency is the first entry of
        ``options["operating_currency"]`` (that list's order is the
        ledger's own priority ordering; multiple operating currencies aren't
        otherwise handled here). Conversion rates come from
        ``beancount.core.prices.build_price_map`` over all of the ledger's
        ``Price`` directives, using the latest available price for each
        currency (no as-of date).

        Returns ``(total, unpriced)``: ``total`` is the summed value in the
        operating currency, or ``None`` if no operating currency is
        configured or none of the inventory's currencies could be valued at
        all. ``unpriced`` lists (in currency order) any currencies that
        couldn't be converted — these are excluded from ``total`` rather
        than silently included as zero.
        """
        operating_currencies = self.options.get("operating_currency") or []
        if not operating_currencies:
            return None, []
        target = operating_currencies[0]
        price_map = self._price_map_cached()
        positions = sorted(inventory.get_positions(), key=lambda pos: pos.units.currency)
        total = Decimal(0)
        unpriced: list[str] = []
        found_any = False
        for pos in positions:
            currency = pos.units.currency
            number = pos.units.number
            if number is None:
                continue
            if currency == target:
                total += number
                found_any = True
                continue
            _, rate = prices.get_price(price_map, (currency, target))
            if rate is None:
                unpriced.append(currency)
                continue
            total += number * rate
            found_any = True
        if not found_any:
            return None, unpriced
        return total, unpriced


def filter_transactions(
    transactions: list[data.Directive],
    query: str,
    today: datetime.date | None = None,
) -> list[data.Directive]:
    """Filter entries by text or by date range.

    A query of the form ``START..END`` — ISO dates, either side optional
    (``2026-01-01..2026-01-31``, ``2026-01-15..``, ``..2026-01-10``) —
    selects a date range, inclusive on both ends. A query matching one of the
    quick preset tokens (``month``, ``last-month``, ``year``, ``last-year``;
    see :func:`resolve_date_preset`) selects the equivalent date range
    computed from ``today`` (defaults to the real current date). Any other
    query is a case-insensitive substring match: against payee and narration
    for transactions, and against the directive keyword, accounts, and note
    comment for other directives.
    """
    query = query.strip()
    if not query:
        return transactions
    date_range = parse_date_range(query, today=today)
    if date_range is not None:
        start, end = date_range
        return [
            txn
            for txn in transactions
            if (start is None or txn.date >= start) and (end is None or txn.date <= end)
        ]
    needle = query.lower()
    return [txn for txn in transactions if needle in _entry_search_text(txn).lower()]


_META_KEYS_EXCLUDED = ("filename", "lineno")


def _user_meta_values(meta: dict | None) -> list[str]:
    """Values of user-added metadata keys, excluding parser-added ones.

    Every entry's ``meta`` dict always carries ``filename``/``lineno`` from
    the parser; those aren't user metadata.
    """
    if not meta:
        return []
    return [str(v) for k, v in meta.items() if k not in _META_KEYS_EXCLUDED]


def has_user_metadata(entry: data.Directive) -> bool:
    """Whether ``entry`` (or, for transactions, any of its postings) carries
    user-added metadata beyond the standard filename/lineno fields."""
    if _user_meta_values(entry.meta):
        return True
    if isinstance(entry, data.Transaction):
        return any(_user_meta_values(posting.meta) for posting in entry.postings)
    return False


def _entry_search_text(entry: data.Directive) -> str:
    if isinstance(entry, data.Transaction):
        parts = [entry.payee or "", entry.narration or "", *_user_meta_values(entry.meta)]
        for posting in entry.postings:
            parts.extend(_user_meta_values(posting.meta))
        if entry.tags:
            parts.extend(sorted(entry.tags))
        if entry.links:
            parts.extend(sorted(entry.links))
        return " ".join(parts)
    parts = [type(entry).__name__.lower(), *sorted(getters.get_entry_accounts(entry))]
    if isinstance(entry, data.Note):
        parts.append(entry.comment)
    parts.extend(_user_meta_values(entry.meta))
    return " ".join(parts)


def resolve_date_preset(
    token: str, today: datetime.date | None = None
) -> tuple[datetime.date, datetime.date] | None:
    """Expand a quick preset token into a ``(start, end)`` date range.

    ``today`` defaults to the real current date; tests pass a fixed date to
    make the resolution deterministic. Recognized tokens (case-insensitive,
    surrounding whitespace ignored):

    - ``month``: from the 1st of the current month through ``today``.
    - ``last-month``: the entirety of the previous calendar month.
    - ``year``: from January 1st of the current year through ``today``.
    - ``last-year``: the entirety of the previous calendar year.

    Returns ``None`` if ``token`` isn't one of the above.
    """
    if today is None:
        today = datetime.date.today()
    token = token.strip().lower()
    if token == "month":
        return today.replace(day=1), today
    if token == "last-month":
        first_of_this_month = today.replace(day=1)
        last_of_last_month = first_of_this_month - datetime.timedelta(days=1)
        return last_of_last_month.replace(day=1), last_of_last_month
    if token == "year":
        return today.replace(month=1, day=1), today
    if token == "last-year":
        return datetime.date(today.year - 1, 1, 1), datetime.date(today.year - 1, 12, 31)
    return None


def parse_date_range(
    query: str,
    today: datetime.date | None = None,
) -> tuple[datetime.date | None, datetime.date | None] | None:
    """Parse ``START..END`` or a quick preset token into dates.

    Returns ``None`` if ``query`` is neither. Preset tokens (``month``,
    ``last-month``, ``year``, ``last-year``) are tried first via
    :func:`resolve_date_preset`, using ``today`` if given.
    """
    preset = resolve_date_preset(query, today=today)
    if preset is not None:
        return preset
    if ".." not in query:
        return None
    start_text, _, end_text = query.partition("..")
    try:
        start = datetime.date.fromisoformat(start_text.strip()) if start_text.strip() else None
        end = datetime.date.fromisoformat(end_text.strip()) if end_text.strip() else None
    except ValueError:
        return None
    if start is None and end is None:
        return None
    return start, end


def format_inventory(inventory: Inventory) -> str:
    """Render an inventory as ``1,234.56 USD, 20 EUR`` (empty string if empty)."""
    positions = sorted(inventory.get_positions(), key=lambda pos: pos.units.currency)
    return ", ".join(f"{pos.units.number:,} {pos.units.currency}" for pos in positions)


def format_query_value(value: object) -> str:
    """Render one BQL result cell for display in a table.

    Most cells are already simple scalars (``str``, ``datetime.date``);
    ``str()`` suffices for those, and for ``None`` (a SQL NULL) it's an
    empty cell rather than the Python string ``"None"``. The Beancount
    value types beanquery hands back for things like ``sum(position)`` or
    a bare ``position``/``amount`` column render with their own
    ``__str__`` too, but not in this codebase's ``1,234.56 USD`` style
    (e.g. an ``Inventory``'s is ``(1234.56 USD)``, no thousands
    separator) — so those, plus bare ``Decimal`` cells, get the same
    comma-grouped formatting as :func:`format_inventory` for consistency
    with the rest of the UI.
    """
    if value is None:
        return ""
    if isinstance(value, Inventory):
        return format_inventory(value)
    if isinstance(value, position.Position):
        return f"{value.units.number:,} {value.units.currency}"
    if isinstance(value, data.Amount):
        return f"{value.number:,} {value.currency}"
    if isinstance(value, Decimal):
        return f"{value:,}"
    return str(value)


def _transaction_amount_inventory(txn: data.Transaction) -> Inventory:
    """The inventory of positive-posting magnitudes underlying ``transaction_amount``."""
    inventory = Inventory()
    for posting in txn.postings:
        if posting.units is not None and posting.units.number is not None:
            if posting.units.number > Decimal(0):
                amount = posting.units
                if posting.cost is not None and posting.cost.number is not None:
                    amount = data.Amount(
                        amount.number * posting.cost.number, posting.cost.currency
                    )
                elif posting.price is not None and posting.price.number is not None:
                    amount = data.Amount(
                        amount.number * posting.price.number, posting.price.currency
                    )
                inventory.add_amount(amount)
    return inventory


def transaction_amount(txn: data.Transaction) -> str:
    """A one-line summary of a transaction's magnitude, e.g. ``120.50 USD``.

    Sums the absolute value of positive postings per currency; transactions
    always balance, so this is the amount that changed hands. Postings with a
    cost basis (``10 HOOL {500.00 USD}``) or a price annotation
    (``10 HOOL @ 55.00 USD``) contribute their cost/price currency amount
    (e.g. ``5,000.00 USD``) rather than the raw commodity quantity, since
    that's far more useful for at-a-glance scanning.
    """
    return format_inventory(_transaction_amount_inventory(txn))


def transaction_amount_value(txn: data.Transaction) -> Decimal:
    """The numeric magnitude backing ``transaction_amount``, for sorting.

    Sums the (possibly multiple, mixed-currency) position numbers from the
    same inventory ``transaction_amount`` formats; mixed-currency
    transactions are rare, and a single sortable number is more useful here
    than a currency-aware comparison.
    """
    positions = _transaction_amount_inventory(txn).get_positions()
    return sum((pos.units.number for pos in positions), Decimal(0))
