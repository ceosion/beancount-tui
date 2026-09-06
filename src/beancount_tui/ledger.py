"""Read-only access to a Beancount ledger via the beancount library."""

from __future__ import annotations

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

    @classmethod
    def load(cls, path: str | Path) -> "Ledger":
        path = Path(path)
        entries, errors, options = loader.load_file(str(path))
        return cls(path=path, entries=entries, errors=errors, options=options)

    def reload(self) -> None:
        self.entries, self.errors, self.options = loader.load_file(str(self.path))
        self._price_map = None

    @property
    def transactions(self) -> list[data.Transaction]:
        return [e for e in self.entries if isinstance(e, data.Transaction)]

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
        for txn in self.transactions:
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
        for txn in self.transactions:
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
        for txn in self.transactions:
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
        for txn in self.transactions:
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

    def transactions_for_account(self, account: str | None) -> list[data.Transaction]:
        """Transactions posting to ``account`` or any of its sub-accounts."""
        if account is None:
            return self.transactions
        prefix = account + ":"
        return [
            txn
            for txn in self.transactions
            if any(p.account == account or p.account.startswith(prefix) for p in txn.postings)
        ]

    def register(self, account: str) -> list[RegisterRow]:
        """Per-transaction posting amount and running balance for ``account``.

        Mirrors ``bean-report register ACCOUNT``: every transaction posting
        to ``account`` or any of its sub-accounts, in date order, each with
        that transaction's posting(s) to the account summed into a single
        amount and the running balance immediately after. Multiple
        currencies coexist in each ``Inventory`` without mixing.
        """
        prefix = account + ":"
        txns = sorted(self.transactions_for_account(account), key=lambda txn: txn.date)
        running = Inventory()
        rows: list[RegisterRow] = []
        for txn in txns:
            posting_amount = Inventory()
            for posting in txn.postings:
                if posting.account != account and not posting.account.startswith(prefix):
                    continue
                if posting.units is None or posting.units.number is None:
                    continue
                posting_amount.add_amount(posting.units)
            running.add_inventory(posting_amount)
            rows.append(
                RegisterRow(
                    date=txn.date,
                    narration=txn.narration,
                    posting_amount=posting_amount,
                    running_balance=Inventory(running),
                )
            )
        return rows

    def root_account(self) -> realization.RealAccount:
        """The realized account tree, with balances, for the account sidebar."""
        return realization.realize(self.entries)

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


def transaction_amount(txn: data.Transaction) -> str:
    """A one-line summary of a transaction's magnitude, e.g. ``120.50 USD``.

    Sums the absolute value of positive postings per currency; transactions
    always balance, so this is the amount that changed hands. Postings with a
    cost basis (``10 HOOL {500.00 USD}``) or a price annotation
    (``10 HOOL @ 55.00 USD``) contribute their cost/price currency amount
    (e.g. ``5,000.00 USD``) rather than the raw commodity quantity, since
    that's far more useful for at-a-glance scanning.
    """
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
    return format_inventory(inventory)
